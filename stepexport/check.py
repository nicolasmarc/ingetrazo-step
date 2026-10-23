"""Weld, orient, close-check and measure a Part's faces.

Input faces are arbitrary polygons with holes. Output: a list of *shells*,
each ``{"faces": [[loop, loop...]...], "closed": bool, "volume": float,
"problems": [...]}`` where loops are lists of vertex indices into ``verts``,
oriented so that outer loops are counter-clockwise seen from OUTSIDE the
solid (holes clockwise).
"""
from collections import defaultdict, deque
import numpy as np

PLANAR_TOL = 1e-6          # relative to face size
PLANAR_ABS = 5e-6          # absolute, input units (5 µm for IngeTrazo metres):
                           # stored coordinates carry float noise of that order


def newell(pts):
    """Area vector (normal * area) of a polygon loop."""
    p = np.asarray(pts, float)
    q = np.roll(p, -1, axis=0)
    return 0.5 * np.cross(p, q).sum(axis=0)


class Welder:
    def __init__(self, tol):
        self.tol = tol
        self.index = {}
        self.verts = []

    def add(self, p):
        k = tuple(int(round(c / self.tol)) for c in p)
        i = self.index.get(k)
        if i is None:
            i = self.index[k] = len(self.verts)
            self.verts.append(tuple(float(c) for c in p))
        return i


def _clean_loop(loop):
    """Drop consecutive duplicates (and the closing duplicate)."""
    out = []
    for i in loop:
        if not out or out[-1] != i:
            out.append(i)
    while len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def _is_planar(face_pts, tol, abs_tol=None):
    """All corners within ``max(tol * size, abs_tol)`` of their best plane."""
    pts = np.vstack([np.asarray(l, float) for l in face_pts])
    if len(pts) < 4:
        return True
    c = pts.mean(axis=0)
    _, sv, vt = np.linalg.svd(pts - c, full_matrices=False)
    if len(sv) < 3:
        return True
    size = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
    dev = float(np.abs((pts - c) @ vt[-1]).max())
    limit = max(tol * size, PLANAR_ABS if abs_tol is None else abs_tol)
    return dev <= limit


def best_plane(pts, normal_hint):
    """(point, unit normal) of the least-squares plane, normal oriented
    like ``normal_hint``."""
    P = np.asarray(pts, float)
    c = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - c, full_matrices=False)
    n = vt[-1]
    if n @ normal_hint < 0:
        n = -n
    return c, n / np.linalg.norm(n)


def _ear_clip(pts, normal):
    """Triangulate a simple polygon loop (3D, near-planar). Returns index triples."""
    n = len(pts)
    idx = list(range(n))
    tris = []
    p = np.asarray(pts, float)

    def cross_n(a, b, c):
        return np.cross(p[b] - p[a], p[c] - p[a]) @ normal

    guard = 0
    while len(idx) > 3 and guard < 10 * n * n:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross_n(a, b, c) <= 1e-14:
                continue
            ok = True
            for o in idx:
                if o in (a, b, c):
                    continue
                if (cross_n(a, b, o) >= 0 and cross_n(b, c, o) >= 0
                        and cross_n(c, a, o) >= 0):
                    ok = False
                    break
            if ok:
                tris.append((a, b, c))
                idx.pop(k)
                break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def _absorb(faces, cap, V, tol):
    """Merge loop ``cap`` into a single-loop face of ``faces`` sharing an
    edge with it and lying in its plane. True when merged."""
    ce = {(min(a, b), max(a, b)) for a, b in zip(cap, cap[1:] + cap[:1])}
    nc = newell(V[cap])
    if np.linalg.norm(nc) == 0:
        return False
    nc = nc / np.linalg.norm(nc)
    for fi, loops in enumerate(faces):
        if len(loops) != 1:
            continue
        l = loops[0]
        le = [(min(a, b), max(a, b)) for a, b in zip(l, l[1:] + l[:1])]
        if not ce.intersection(le):
            continue
        if np.abs((V[l] - V[cap[0]]) @ nc).max() > tol:
            continue
        nl = newell(V[l])
        c = cap if (nl @ nc) > 0 else cap[::-1]   # same sense as l
        edges = [(a, b) for a, b in zip(l, l[1:] + l[:1])] + \
                [(a, b) for a, b in zip(c, c[1:] + c[:1])]
        und = {}
        for a, b in edges:
            und[(min(a, b), max(a, b))] = und.get((min(a, b), max(a, b)), 0) + 1
        bnd = [(a, b) for a, b in edges if und[(min(a, b), max(a, b))] == 1]
        if not bnd:                      # cap is the face itself
            return False
        nxt = {}
        for a, b in bnd:
            if a in nxt:
                return False
            nxt[a] = b
        start = bnd[0][0]
        loop, x = [start], nxt[start]
        while x != start and len(loop) <= len(bnd):
            loop.append(x)
            x = nxt.get(x)
            if x is None:
                return False
        if len(loop) != len(bnd):
            return False
        faces[fi] = [loop]
        return True
    return False


def _flat_sheet_border(cap, loops, V, tol):
    """True when every loop sharing an edge with ``cap`` lies in its plane."""
    nc = newell(V[cap])
    if np.linalg.norm(nc) == 0:
        return False
    nc = nc / np.linalg.norm(nc)
    ce = {(min(a, b), max(a, b)) for a, b in zip(cap, cap[1:] + cap[:1])}
    touching = [l for l in loops
                if ce.intersection((min(a, b), max(a, b)) for a, b in zip(l, l[1:] + l[:1]))]
    return bool(touching) and all(
        np.abs((V[l] - V[cap[0]]) @ nc).max() <= tol for l in touching)


def _repair(welded, verts, tol, notes):
    """Stitch T-junctions and cap small planar holes over the whole part
    (``welded``: list of faces, each a list of index loops)."""
    from .repair import split_t_junctions, cap_planar_holes
    V = np.asarray(verts, float)
    seen, kept = set(), []
    for loops in welded:                 # stacked duplicates: keep one
        k = frozenset(loops[0])
        if k in seen:
            continue
        seen.add(k)
        kept.append(loops)
    if len(kept) < len(welded):
        notes.append(f"{len(welded) - len(kept)} duplicate face(s) dropped")
    welded = kept
    flat, owner = [], []
    for fi, loops in enumerate(welded):
        for li, l in enumerate(loops):
            flat.append(l)
            owner.append((fi, li))
    flat, nt = split_t_junctions(flat, V, tol)
    n0 = len(flat)
    flat, nc = cap_planar_holes(flat, V, tol)
    out = [list(loops) for loops in welded]
    for (fi, li), l in zip(owner, flat[:n0]):
        out[fi][li] = l
    # a planar "hole" whose neighbouring faces all lie in its own plane is
    # the open border of a flat sheet (a lone face, a flat panel of several
    # faces): capping it would glue a face back to back and fake a
    # zero-volume solid, so the sheet stays open
    caps = [c for c in flat[n0:] if not _flat_sheet_border(c, flat[:n0], V, tol)]
    nc -= len(flat) - n0 - len(caps)
    for cap in caps:                # fold a cap into its coplanar neighbour
        if not _absorb(out, cap, V, tol):
            out.append([cap])
    if nt:
        notes.append(f"{nt} T-junction(s) stitched")
    if nc:
        notes.append(f"{nc} planar hole(s) capped")
    return out


def _drop_redundant(welded, srcs, notes):
    """Remove stray faces lying over others: a source face (all the pieces
    cut from it) whose every border edge is already carried by two other
    faces adds nothing to the solid but makes those edges non-manifold."""
    from collections import Counter
    def edges(loops):
        for l in loops:
            for a, b in zip(l, l[1:] + l[:1]):
                yield (min(a, b), max(a, b))
    count = Counter(e for loops in welded for e in edges(loops))
    groups = {}
    for i, s in enumerate(srcs):
        groups.setdefault(s, []).append(i)
    if max(count.values(), default=0) <= 2:
        return welded
    drop = set()
    for s, idx in groups.items():
        inner = Counter(e for i in idx for e in edges(welded[i]))
        border = [e for e, n in inner.items() if n == 1]
        if border and all(count[e] - 1 >= 2 for e in border) \
                and any(count[e] >= 3 for e in border):
            drop.update(idx)
            for e, n in inner.items():
                count[e] -= n
    if drop:
        notes.append(f"{len({srcs[i] for i in drop})} stray face(s) dropped")
    return [l for i, l in enumerate(welded) if i not in drop]


def prepare_faces(part, weld_tol, repair_tol=None):
    """Weld vertices; optionally stitch T-junctions and cap planar holes
    (``repair_tol``); split non-planar faces into triangles.
    Returns (verts, faces, notes) with faces = [[loop,...],...]."""
    w = Welder(weld_tol)
    faces, notes = [], []
    welded, srcs = [], []
    for k, f in enumerate(part.faces):
        loops_pts = [list(f.outer)] + [list(h) for h in f.holes]
        loops = [_clean_loop([w.add(p) for p in l]) for l in loops_pts]
        if len(loops[0]) < 3:
            continue
        welded.append([l for i, l in enumerate(loops) if len(l) >= 3 or i == 0])
        srcs.append(getattr(f, "src", None) or ("f", k))
    if repair_tol:
        seen, keep = set(), []
        for i, loops in enumerate(welded):   # stacked duplicates first
            k = frozenset(loops[0])
            if k not in seen:
                seen.add(k)
                keep.append(i)
        if len(keep) < len(welded):
            notes.append(f"{len(welded) - len(keep)} duplicate face(s) dropped")
            welded = [welded[i] for i in keep]
            srcs = [srcs[i] for i in keep]
        welded = _drop_redundant(welded, srcs, notes)
        welded = _repair(welded, w.verts, repair_tol, notes)
    for loops in welded:
        pts = [[w.verts[i] for i in l] for l in loops]
        P0 = np.asarray(pts[0], float)
        span = float(np.linalg.norm(P0 - P0[0], axis=1).max())
        if np.linalg.norm(newell(P0)) <= 1e-9 * max(span * span, 1e-30):
            notes.append("zero-area face dropped")
            continue
        if _is_planar(pts, PLANAR_TOL):
            # holes must run opposite to the outer loop, whatever the input
            nv = newell(pts[0])
            for k in range(1, len(loops)):
                if newell(pts[k]) @ nv > 0:
                    loops[k] = list(reversed(loops[k]))
            faces.append(loops)
            continue
        notes.append("non-planar face triangulated")
        if len(loops) > 1:
            notes.append("holes of a non-planar face were dropped")
        nrm = newell(pts[0])
        ln = np.linalg.norm(nrm)
        if ln < 1e-18:
            continue
        for a, b, c in _ear_clip(pts[0], nrm / ln):
            faces.append([[loops[0][a], loops[0][b], loops[0][c]]])
    return w.verts, faces, notes


def _directed_edges(face):
    for loop in face:
        n = len(loop)
        for k in range(n):
            yield loop[k], loop[(k + 1) % n]


def split_components(faces):
    """Connected components of faces through shared (undirected) edges."""
    by_edge = defaultdict(list)
    for fi, f in enumerate(faces):
        for a, b in _directed_edges(f):
            by_edge[(min(a, b), max(a, b))].append(fi)
    seen, comps = set(), []
    for s in range(len(faces)):
        if s in seen:
            continue
        comp, q = [], deque([s])
        seen.add(s)
        while q:
            f = q.popleft()
            comp.append(f)
            for a, b in _directed_edges(faces[f]):
                for g in by_edge[(min(a, b), max(a, b))]:
                    if g not in seen:
                        seen.add(g)
                        q.append(g)
        comps.append(sorted(comp))
    return comps


def _flip(face):
    return [list(reversed(l)) for l in face]


def orient_component(faces, comp):
    """Make orientation consistent over ``comp`` (list of face ids).
    Returns (oriented faces list aligned with comp, problems)."""
    f = {i: faces[i] for i in comp}
    by_edge = defaultdict(list)
    for i in comp:
        for a, b in _directed_edges(f[i]):
            by_edge[(min(a, b), max(a, b))].append((i, a, b))
    problems = []
    for e, uses in by_edge.items():
        if len(uses) > 2:
            problems.append("non-manifold edge")
            break
    flipped = {comp[0]: False}
    q = deque([comp[0]])
    while q:
        i = q.popleft()
        for a, b in _directed_edges(f[i]):
            if flipped[i]:
                a, b = b, a
            for (j, ja, jb) in by_edge[(min(a, b), max(a, b))]:
                if j == i:
                    continue
                # in face j (unflipped) the edge runs ja->jb; it must run
                # opposite to a->b (as seen in face i's current orientation)
                same = (ja, jb) == (a, b)
                want = same                     # flip j iff same direction
                if j not in flipped:
                    flipped[j] = want
                    q.append(j)
                elif flipped[j] != want and "inconsistent orientation" not in problems:
                    problems.append("inconsistent orientation")
    out = [(_flip(f[i]) if flipped.get(i, False) else f[i]) for i in comp]
    return out, problems


def is_closed(faces):
    c = defaultdict(int)
    for f in faces:
        for a, b in _directed_edges(f):
            c[(a, b)] += 1
    return all(n == 1 and c.get((b, a), 0) == 1 for (a, b), n in c.items())


def signed_volume(verts, faces):
    v = np.asarray(verts, float)
    tot = 0.0
    for f in faces:
        avec = np.zeros(3)
        for loop in f:
            avec += newell(v[loop])
        tot += avec @ v[f[0][0]] / 3.0
    return float(tot)


def analyse(part, weld_tol=1e-6, repair_tol=None):
    """-> (verts, shells, notes). Each shell is a dict (see module doc)."""
    verts, faces, notes = prepare_faces(part, weld_tol, repair_tol)
    shells = []
    for comp in split_components(faces):
        fs, problems = orient_component(faces, comp)
        closed = is_closed(fs) and not problems
        vol = signed_volume(verts, fs) if closed else 0.0
        if closed and vol < 0:
            fs = [_flip(x) for x in fs]
            vol = -vol
        if not closed and not problems:
            problems.append("open edges")
        shells.append({"faces": fs, "closed": closed, "volume": vol,
                       "problems": problems})
    return verts, shells, notes


def soft_index_pairs(part, verts, weld_tol=1e-6):
    """The part's soft edges as welded vertex-index pairs ``(min, max)``,
    ``None`` when the part carries no soft-edge hint."""
    if not part.soft_edges:
        return None
    index = {}
    for i, p in enumerate(verts):
        index.setdefault(tuple(int(round(c / weld_tol)) for c in p), i)
    out = set()
    for a, b in part.soft_edges:
        ia = index.get(tuple(int(round(c / weld_tol)) for c in a))
        ib = index.get(tuple(int(round(c / weld_tol)) for c in b))
        if ia is not None and ib is not None and ia != ib:
            out.add((min(ia, ib), max(ia, ib)))
    return out

"""Weld, orient, close-check and measure a Part's faces.

Input faces are arbitrary polygons with holes. Output: a list of *shells*,
each ``{"faces": [[loop, loop...]...], "closed": bool, "volume": float,
"problems": [...]}`` where loops are lists of vertex indices into ``verts``,
oriented so that outer loops are counter-clockwise seen from OUTSIDE the
solid (holes clockwise).
"""
from collections import defaultdict, deque
import math
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


def _walk(face_ids, faces, neighbours):
    seen, comps = set(), []
    for s in face_ids:
        if s in seen:
            continue
        comp, q = [], deque([s])
        seen.add(s)
        while q:
            f = q.popleft()
            comp.append(f)
            for g in neighbours(f):
                if g not in seen:
                    seen.add(g)
                    q.append(g)
        comps.append(sorted(comp))
    return comps


def _radial_order(edge, fids, faces, V):
    """Faces around an edge, sorted by the angle of the way each one leaves
    the edge (the direction from the edge to the face's centroid)."""
    a, b = V[edge[0]], V[edge[1]]
    t = b - a
    t = t / np.linalg.norm(t)
    u = np.cross(t, [1.0, 0, 0] if abs(t[0]) < 0.9 else [0, 1.0, 0])
    u /= np.linalg.norm(u)
    w = np.cross(t, u)
    ang = []
    for f in fids:
        c = V[faces[f][0]].mean(axis=0) - a
        d = c - (c @ t) * t
        ang.append((math.atan2(d @ w, d @ u), f))
    return [f for _, f in sorted(ang)]


def _pair_pinches(comp, faces, V, max_edges=10):
    """Split a component held together at edges carried by four (or six...)
    of its faces — two parts butting along an edge, a rail against a post —
    into closed shells. Around such an edge the faces alternate between
    material and empty wedges; each face pairs with one angular neighbour,
    and of the two ways to pair them the one that closes the most shells is
    kept (every combination is tried, the edges are few)."""
    import itertools
    uses = defaultdict(list)
    for f in comp:
        for x, y in _directed_edges(faces[f]):
            uses[(min(x, y), max(x, y))].append(f)
    pinch = [e for e, fs in uses.items() if len(fs) > 2]
    if not pinch or len(pinch) > max_edges or any(len(uses[e]) % 2 for e in pinch):
        return [comp]
    orders = [_radial_order(e, uses[e], faces, V) for e in pinch]
    best, best_score = [comp], (-1, 0)
    for choice in itertools.product((0, 1), repeat=len(pinch)):
        partner = defaultdict(set)
        for e, order, off in zip(pinch, orders, choice):
            n = len(order)
            for k in range(off, off + n, 2):
                f, g = order[k % n], order[(k + 1) % n]
                partner[(e, f)].add(g)
                partner[(e, g)].add(f)

        def neighbours(f):
            for x, y in _directed_edges(faces[f]):
                e = (min(x, y), max(x, y))
                if len(uses[e]) > 2:
                    yield from partner[(e, f)]
                else:
                    yield from (g for g in uses[e] if g != f)
        subs = _walk(comp, faces, neighbours)
        closed = 0
        for sub in subs:
            cnt = defaultdict(int)
            for f in sub:
                for x, y in _directed_edges(faces[f]):
                    cnt[(min(x, y), max(x, y))] += 1
            closed += all(v == 2 for v in cnt.values())
        score = (closed, len(subs))
        if score > best_score:
            best, best_score = subs, score
    return best


def split_components(faces, verts=None):
    """Connected components of faces through shared (undirected) edges.

    An edge carried by more than two faces is where separate parts touch
    (two balusters on a rail edge, two treads meeting edge to edge in one
    layer of a DXF): the walk does not cross it, so each part comes out as
    its own shell instead of one non-manifold lump. A component still held
    together at such an edge (two parts butting along it) is split there by
    pairing its faces around the edge (``verts`` needed)."""
    by_edge = defaultdict(list)
    for fi, f in enumerate(faces):
        for a, b in _directed_edges(f):
            by_edge[(min(a, b), max(a, b))].append(fi)
    multi = {k for k, fs in by_edge.items() if len(fs) > 2}

    def neighbours(f):
        for a, b in _directed_edges(faces[f]):
            k = (min(a, b), max(a, b))
            if k not in multi:
                yield from by_edge[k]
    comps = _walk(range(len(faces)), faces, neighbours)
    if verts is None or not multi:
        return comps
    V = np.asarray(verts, float)
    out = []
    for comp in comps:
        out.extend(_pair_pinches(comp, faces, V))
    return out


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


def _unpinch(comp, faces, verts, max_edges=10):
    """A shell that touches itself along an edge (four of its faces on one
    edge: a rail butting a post in a DXF where both were welded into one
    body) is a closed solid, but not a manifold one. Pair the faces around
    each such edge (try both ways, keep the one that leaves a closed,
    consistently oriented shell) and give the second pair its own copy of
    the edge's vertices: the solid is unchanged, its B-rep becomes valid.
    Returns (faces of comp, possibly with new vertex ids, appended to
    ``verts``) or ``None`` when nothing works."""
    import itertools
    uses = defaultdict(list)
    for f in comp:
        for x, y in _directed_edges(faces[f]):
            uses[(min(x, y), max(x, y))].append(f)
    pinch = [e for e, fs in uses.items() if len(fs) > 2]
    if not pinch or len(pinch) > max_edges or any(len(uses[e]) % 2 for e in pinch):
        return None
    V = np.asarray(verts, float)
    orders = [_radial_order(e, uses[e], faces, V) for e in pinch]
    pinch_set = set(pinch)
    touched = sorted({v for e in pinch for v in e})
    for choice in itertools.product((0, 1), repeat=len(pinch)):
        partner = defaultdict(set)
        for e, order, off in zip(pinch, orders, choice):
            n = len(order)
            for k in range(off, off + n, 2):
                f, g = order[k % n], order[(k + 1) % n]
                partner[(e, f)].add(g)
                partner[(e, g)].add(f)
        new = {f: [list(l) for l in faces[f]] for f in comp}
        added = []
        for v in touched:
            around = [f for f in comp if any(v in l for l in faces[f])]

            def nb(f, v=v, around=around):
                for x, y in _directed_edges(faces[f]):
                    if v not in (x, y):
                        continue
                    e = (min(x, y), max(x, y))
                    if e in pinch_set:
                        yield from partner[(e, f)]
                    else:
                        yield from (g for g in uses[e] if g != f and g in around)
            groups = _walk(around, faces, nb)
            for grp in groups[1:]:
                nid = len(verts) + len(added)
                added.append(verts[v])
                for f in grp:
                    new[f] = [[nid if i == v else i for i in l] for l in new[f]]
        fl = [new[f] for f in comp]
        cnt = defaultdict(int)
        for f in fl:
            for x, y in _directed_edges(f):
                cnt[(min(x, y), max(x, y))] += 1
        if not all(c == 2 for c in cnt.values()):
            continue
        _, problems = orient_component(fl, list(range(len(fl))))
        if problems:
            continue
        verts.extend(added)
        return fl
    return None


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


def _lend_shared_faces(faces, comps, verts):
    """Two parts that share a whole face (a beam and the block it rests on,
    cut along one slanted plane) arrive with that face once: it belongs to
    both, so after the split each part is open by exactly that face, and
    the face itself (one polygon or a few triangles) is left as a small
    open sheet. Lend the sheet: an open component whose border contains a
    sheet's whole border gets the sheet's faces too (the writer orients the
    copy); a sheet lent away is dropped as a shell of its own."""
    def border(comp):
        cnt = defaultdict(int)
        for f in comp:
            for a, b in _directed_edges(faces[f]):
                cnt[(min(a, b), max(a, b))] += 1
        return {e for e, c in cnt.items() if c == 1}
    V = np.asarray(verts, float)

    def sheet(comp):                     # all its faces in one plane
        P = V[sorted({i for f in comp for l in faces[f] for i in l})]
        if len(P) < 3:
            return False
        c = P.mean(axis=0)
        n = np.linalg.svd(P - c, full_matrices=False)[2][-1]
        span = float(np.linalg.norm(P - c, axis=1).max())
        return float(np.abs((P - c) @ n).max()) <= 1e-9 * max(span, 1.0) + 1e-9
    borders = [border(c) for c in comps]
    sheets = [len(c) <= 8 and bool(b) and sheet(c) for c, b in zip(comps, borders)]
    lent = set()
    out = []
    for i, comp in enumerate(comps):
        bi = borders[i]
        if not bi:
            out.append(comp)
            continue
        extra = []
        for j, other in enumerate(comps):
            bj = borders[j]
            if j == i or not sheets[j] or sheets[i]:
                continue
            if bj <= bi:
                extra.append(j)
        cover = set().union(*(borders[j] for j in extra)) if extra else set()
        if extra and cover == bi:
            lent.update(extra)
            comp = sorted(set(comp).union(*(comps[j] for j in extra)))
        out.append(comp)
    return [c for k, c in enumerate(out) if k not in lent]


def analyse(part, weld_tol=1e-6, repair_tol=None):
    """-> (verts, shells, notes). Each shell is a dict (see module doc)."""
    verts, faces, notes = prepare_faces(part, weld_tol, repair_tol)
    shells = []
    comps = _lend_shared_faces(faces, split_components(faces, verts), verts)
    for comp in comps:
        fs, problems = orient_component(faces, comp)
        if problems:
            fixed = _unpinch(comp, faces, verts)
            if fixed is not None:
                fs, problems = orient_component(fixed, list(range(len(fixed))))
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

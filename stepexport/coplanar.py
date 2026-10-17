"""Merge triangles / small facets lying in one plane into polygon faces
(outer loop + holes), as needed for a mesh coming from 3DFACE soups (DXF)
before it is written as a B-rep.

Pure numpy. Works on welded vertex indices so the merged faces still share
their edges exactly (no T-junctions created). A vertex is dropped from the
loops only when it is a straight-line point for every merged face around it.
"""
from collections import defaultdict
import numpy as np
from .check import newell


class NearWelder:
    """Weld points closer than ``tol`` (checks the neighbour cells, so two
    points just across a grid line still weld, unlike plain rounding)."""

    def __init__(self, tol):
        self.tol = tol
        self.grid = defaultdict(list)
        self.verts = []

    def add(self, p):
        p = tuple(float(c) for c in p)
        k = tuple(int(np.floor(c / self.tol)) for c in p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for i in self.grid.get((k[0] + dx, k[1] + dy, k[2] + dz), ()):
                        q = self.verts[i]
                        if (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 + (q[2] - p[2]) ** 2 <= self.tol ** 2:
                            return i
        self.verts.append(p)
        self.grid[k].append(len(self.verts) - 1)
        return len(self.verts) - 1


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def merge_coplanar(polys, weld_tol=1e-6, ang_tol=1e-6, dist_tol=1e-6,
                   repair=False, stats=None, plane_tol=None, simplify=False,
                   merge=True):
    """``polys``: list of point loops (each a list of (x, y, z)).
    Returns (faces, verts) with faces = [[outer_idx, hole_idx...], ...].
    ``repair``: True or a stitching tolerance — weld / zip the open seams,
    drop zero-area slivers, stitch T-junctions and cap planar holes first
    (counts go in the ``stats`` dict when given).
    ``plane_tol`` (absolute): faces whose corners all lie within it of a
    larger neighbour's plane join it, and every vertex is then snapped onto
    the exact intersection of the merged planes around it (what a healer
    does with a slightly noisy export)."""
    w = NearWelder(weld_tol)
    loops = []
    for p in polys:
        idx = []
        for q in p:
            i = w.add(q)
            if not idx or idx[-1] != i:
                idx.append(i)
        while len(idx) > 1 and idx[0] == idx[-1]:
            idx.pop()
        if len(idx) >= 3:
            loops.append(idx)
    V = np.asarray(w.verts, float)

    def flat(l):                 # zero-area loop: all corners on one line
        P = V[l]
        span = max(np.linalg.norm(P - P[0], axis=1).max(), 1e-30)
        return np.linalg.norm(newell(P)) < weld_tol * span

    def note(k, n):
        if stats is not None:
            stats[k] = stats.get(k, 0) + n

    if repair:
        from .repair import split_t_junctions, cap_planar_holes, zip_boundary
        zt = repair if not isinstance(repair, bool) else 50 * weld_tol
        loops, nz = zip_boundary(loops, V, zt)
        note("zipped", nz)
    n0 = len(loops)
    loops = [l for l in loops if not flat(l)]
    note("flat", n0 - len(loops))
    if repair:
        loops, nt = split_t_junctions(loops, V, zt)
        loops, nc = cap_planar_holes(loops, V, 50 * weld_tol)
        note("t_junctions", nt)
        note("caps", nc)
    if not merge:                    # repaired facets as they are
        return [[l] for l in loops], list(w.verts)
    nrm, off, keep = [], [], []
    for l in loops:
        a = newell(V[l])
        if np.linalg.norm(a) < 1e-14:          # degenerate sliver
            continue
        n = _unit(a)
        keep.append(l)
        nrm.append(n)
        off.append(float(n @ V[l].mean(axis=0)))
    loops = keep
    by_edge = defaultdict(list)
    for fi, l in enumerate(loops):
        for k in range(len(l)):
            a, b = l[k], l[(k + 1) % len(l)]
            by_edge[(min(a, b), max(a, b))].append(fi)

    area = [float(np.linalg.norm(newell(V[l]))) for l in loops]

    def same_plane(f, g):
        if plane_tol is not None:
            return bool(np.abs(V[loops[g]] @ nrm[f] - off[f]).max() < plane_tol)
        c = float(nrm[f] @ nrm[g])
        if abs(abs(c) - 1) > ang_tol:
            return False
        s = 1 if c > 0 else -1
        return abs(off[f] - s * off[g]) < dist_tol * max(1.0, abs(off[f]))

    # regions of coplanar faces connected through shared edges
    region = [-1] * len(loops)
    regions = []
    order = sorted(range(len(loops)), key=lambda i: -area[i])
    for s in order:
        if region[s] >= 0:
            continue
        rid = len(regions)
        region[s] = rid
        stack, members = [s], [s]
        while stack:
            f = stack.pop()
            l = loops[f]
            for k in range(len(l)):
                e = (min(l[k], l[(k + 1) % len(l)]), max(l[k], l[(k + 1) % len(l)]))
                fs = by_edge[e]
                if len(fs) != 2:
                    continue
                for g in fs:
                    if region[g] < 0 and same_plane(s, g):
                        region[g] = rid
                        stack.append(g)
                        members.append(g)
        regions.append(members)

    out = []
    for members in regions:
        n0 = nrm[members[0]]
        # orient every member like the first one
        oriented = [l if nrm[f] @ n0 > 0 else l[::-1]
                    for f, l in ((f, loops[f]) for f in members)]
        cnt = defaultdict(int)
        for l in oriented:
            for k in range(len(l)):
                cnt[(l[k], l[(k + 1) % len(l)])] += 1
        bnd = [e for e, c in cnt.items() if c - cnt.get((e[1], e[0]), 0) > 0]
        nxt = defaultdict(list)
        for a, b in bnd:
            nxt[a].append(b)
        chains, used = [], set()
        for a, b in bnd:
            if (a, b) in used:
                continue
            chain, x, y = [a], a, b
            ok = True
            while True:
                used.add((x, y))
                if y == chain[0]:
                    break
                chain.append(y)
                cands = [z for z in nxt[y] if (y, z) not in used]
                if not cands:
                    ok = False
                    break
                x, y = y, cands[0]
            if ok and len(chain) >= 3:
                chains.append(chain)
        if not chains:
            continue
        # classify loops: positive area along n0 = outer, negative = hole
        outers, holes = [], []
        for c in chains:
            (outers if newell(V[c]) @ n0 > 0 else holes).append(c)
        if not outers:
            continue
        u = _unit(np.cross(n0, [1, 0, 0] if abs(n0[0]) < .9 else [0, 1, 0]))
        v2 = np.cross(n0, u)

        def inside(pt, loop):
            x, y = pt @ u, pt @ v2
            P = V[loop]
            xs, ys = P @ u, P @ v2
            ins = False
            for i in range(len(loop)):
                x1, y1, x2, y2 = xs[i], ys[i], xs[i - 1], ys[i - 1]
                if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                    ins = not ins
            return ins
        faces = [[o] for o in outers]
        for h in holes:
            pt = V[h].mean(axis=0)
            host = [i for i, o in enumerate(outers) if inside(pt, o)]
            if host:
                best = min(host, key=lambda i: np.linalg.norm(newell(V[outers[i]])))
                faces[best].append(h)
            else:
                faces.append([h[::-1]])
        out.extend(faces)

    if plane_tol is not None and out:
        V = _snap(V, out, plane_tol)
        if stats is not None:
            stats["snapped"] = True

    if not simplify:
        return out, [tuple(p) for p in V]
    # drop straight-line vertices used by exactly two merged faces
    uses = defaultdict(set)
    for fi, f in enumerate(out):
        for l in f:
            for i in l:
                uses[i].add(fi)

    def straight(l, k):
        a, b, c = V[l[k - 1]], V[l[k]], V[l[(k + 1) % len(l)]]
        d1, d2 = b - a, c - b
        n1, n2 = np.linalg.norm(d1), np.linalg.norm(d2)
        if n1 == 0 or n2 == 0:
            return True
        return np.linalg.norm(np.cross(d1 / n1, d2 / n2)) < 1e-9 and d1 @ d2 > 0

    removable = set()
    for i, fs in uses.items():
        if len(fs) != 2:
            continue
        ok = True
        for fi in fs:
            for l in out[fi]:
                if i in l and not straight(l, l.index(i)):
                    ok = False
        if ok:
            removable.add(i)
    out = [[[i for i in l if i not in removable] for l in f] for f in out]
    out = [[l for l in f if len(l) >= 3] for f in out]
    out = [f for f in out if f]
    return out, [tuple(p) for p in V]


def _snap(V, faces, tol):
    """Move each vertex onto the intersection of the planes of its faces
    (least squares, minimal move); moves beyond ``10 * tol`` are skipped."""
    V = np.array(V, float)
    planes = []
    for f in faces:
        P = V[f[0]]
        n = _unit(newell(P))
        allp = np.vstack([V[l] for l in f])
        planes.append((n, float((allp @ n).mean())))
    inc = defaultdict(list)
    for fi, f in enumerate(faces):
        for l in f:
            for i in l:
                inc[i].append(fi)
    out = V.copy()
    for i, fs in inc.items():
        N = np.array([planes[f][0] for f in set(fs)])
        d = np.array([planes[f][1] for f in set(fs)])
        r = d - N @ V[i]
        if np.abs(r).max() < 1e-12:
            continue
        move = np.linalg.pinv(N, rcond=0.05) @ r
        if np.linalg.norm(move) <= 10 * tol:
            out[i] = V[i] + move
    return out

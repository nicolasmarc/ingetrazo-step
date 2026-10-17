"""Optional simplification of faceted curved surfaces before writing.

A finely sampled curved surface (hundreds of facets, some only a fraction of
a millimetre wide) reaches CAD as many tiny faces that shade badly. Here,
neighbouring facets that all lie within ``tol`` of one plane are merged into
one face (best-fit plane, its border kept as it is): the surface moves by at
most ``tol``, the border vertices — shared with the neighbouring faces — never
move, so a closed solid stays closed.

Works on one oriented shell: ``faces`` = [[loop, ...], ...] of vertex
indices (outer loops counter-clockwise seen from outside), as produced by
:func:`check.analyse`. Faces listed in ``keep`` (e.g. recognised cylinder
facets) are left alone.
"""
from collections import defaultdict
import numpy as np
from .check import newell


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def simplify_shell(verts, faces, tol, keep=(), max_angle_deg=30.0):
    """-> (new_faces, index_map, stats). ``index_map[old] = new`` for faces
    kept unchanged (so callers can re-index regions); merged faces map to
    nothing. ``stats``: merged (faces removed), max_dev."""
    V = np.asarray(verts, float)
    keep = set(keep)
    n_f = len(faces)
    nrm = [_unit(newell(V[f[0]])) for f in faces]
    area = [float(np.linalg.norm(newell(V[f[0]]))) for f in faces]
    by_edge = defaultdict(list)
    for fi, f in enumerate(faces):
        if len(f) != 1:
            continue                       # faces with holes stay as they are
        l = f[0]
        for a, b in zip(l, l[1:] + l[:1]):
            by_edge[(min(a, b), max(a, b))].append(fi)
    cos_max = np.cos(np.radians(max_angle_deg))
    region = [-1] * n_f
    regions = []
    for s in sorted(range(n_f), key=lambda i: -area[i]):
        if region[s] >= 0 or s in keep or len(faces[s]) != 1:
            continue
        P = V[faces[s][0]]
        c = P.mean(axis=0)
        n0 = nrm[s]
        rid = len(regions)
        region[s] = rid
        members, stack = [s], [s]
        while stack:
            f = stack.pop()
            l = faces[f][0]
            for a, b in zip(l, l[1:] + l[:1]):
                fs = by_edge[(min(a, b), max(a, b))]
                if len(fs) != 2:
                    continue
                for g in fs:
                    if region[g] >= 0 or g in keep or len(faces[g]) != 1:
                        continue
                    if nrm[g] @ n0 < cos_max:
                        continue
                    if np.abs((V[faces[g][0]] - c) @ n0).max() > tol:
                        continue
                    region[g] = rid
                    members.append(g)
                    stack.append(g)
        regions.append(members)

    out, index_map, merged, max_dev = [], {}, 0, 0.0
    for members in regions:
        if len(members) == 1:
            continue
        loops = _border(V, faces, members)
        if loops is None:
            for g in members:
                region[g] = -2               # keep them as they were
            continue
        n0 = nrm[members[0]]
        outer = [l for l in loops if newell(V[l]) @ n0 > 0]
        holes = [l for l in loops if newell(V[l]) @ n0 <= 0]
        if len(outer) != 1:
            for g in members:
                region[g] = -2
            continue
        pts = np.vstack([V[l] for l in loops])
        allp = np.vstack([V[faces[g][0]] for g in members])
        c = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
        dev = float(np.abs((allp - c) @ vt[-1]).max())
        if dev > 2 * tol:                   # best fit drifted: too curved
            for g in members:
                region[g] = -2
            continue
        max_dev = max(max_dev, dev)
        out.append([outer[0]] + holes)
        merged += len(members) - 1
        for g in members:
            region[g] = -3                   # consumed
    for fi, f in enumerate(faces):
        if region[fi] == -3:
            continue
        if region[fi] >= 0 and len(regions[region[fi]]) > 1:
            continue                         # handled above (merged)
        index_map[fi] = len(out)
        out.append(f)
    # merged faces were appended first; unchanged faces get their new index
    return out, index_map, {"merged": merged, "max_dev": max_dev}


def _border(V, faces, members):
    """Border loops of a set of oriented single-loop faces, or ``None``
    when the border is not made of simple loops."""
    cnt = defaultdict(int)
    for g in members:
        l = faces[g][0]
        for a, b in zip(l, l[1:] + l[:1]):
            cnt[(a, b)] += 1
    bnd = [e for e, k in cnt.items() if k == 1 and cnt.get((e[1], e[0]), 0) == 0]
    if any(k > 1 for k in cnt.values()):
        return None
    nxt = {}
    for a, b in bnd:
        if a in nxt:
            return None                      # touching itself at a vertex
        nxt[a] = b
    loops, seen = [], set()
    for a, _ in bnd:
        if a in seen:
            continue
        loop, x = [], a
        while x not in seen:
            seen.add(x)
            loop.append(x)
            x = nxt.get(x)
            if x is None:
                return None
        if x != a or len(loop) < 3:
            return None
        loops.append(loop)
    return loops or None

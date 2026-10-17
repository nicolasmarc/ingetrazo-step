"""Close the small defects of a face soup (DXF 3DFACEs) before it becomes a
solid: T-junctions (a corner lying inside a neighbour's edge) are stitched
by splitting that edge, then every remaining hole whose border is a planar
closed loop is capped with a new face.

Works on welded vertex indices (``check.Welder``). Pure numpy.
"""
from collections import defaultdict
import numpy as np


def _boundary(loops):
    c = defaultdict(int)
    for l in loops:
        for k in range(len(l)):
            a, b = l[k], l[(k + 1) % len(l)]
            if a != b:
                c[(min(a, b), max(a, b))] += 1
    return [e for e, n in c.items() if n == 1]


def split_t_junctions(loops, V, tol, rounds=4):
    """Insert boundary vertices lying inside boundary edges into the loops
    that own those edges. Returns (loops, number of splits)."""
    total = 0
    for _ in range(rounds):
        bnd = _boundary(loops)
        if not bnd:
            break
        bv = np.array(sorted({i for e in bnd for i in e}))
        P = V[bv]
        insert = {}                          # (a, b) undirected -> [vertex...]
        for a, b in bnd:
            pa, pb = V[a], V[b]
            d = pb - pa
            L2 = float(d @ d)
            if L2 == 0:
                continue
            lo, hi = np.minimum(pa, pb) - tol, np.maximum(pa, pb) + tol
            m = np.all((P >= lo) & (P <= hi), axis=1)
            cand = []
            for v, p in zip(bv[m], P[m]):
                if v in (a, b):
                    continue
                t = float((p - pa) @ d) / L2
                if 0 < t < 1 and np.linalg.norm(pa + t * d - p) < tol:
                    cand.append((t, int(v)))
            if cand:
                insert[(a, b)] = [v for _, v in sorted(cand)]
        if not insert:
            break
        new = []
        for l in loops:
            out = []
            for k in range(len(l)):
                a, b = l[k], l[(k + 1) % len(l)]
                out.append(a)
                if (min(a, b), max(a, b)) in insert:
                    vs = insert[(min(a, b), max(a, b))]
                    out.extend(vs if a < b else vs[::-1])
                    total += len(vs)
            new.append(out)
        loops = new
    return loops, total


def cap_planar_holes(loops, V, tol):
    """Add a face on every closed loop of boundary edges that is planar.
    Returns (loops, number of caps)."""
    bnd = _boundary(loops)
    adj = defaultdict(list)
    for a, b in bnd:
        adj[a].append(b)
        adj[b].append(a)
    if any(len(n) != 2 for n in adj.values()):
        # branching borders: only take the simple components
        pass
    seen, caps = set(), []
    for s in list(adj):
        if s in seen or len(adj[s]) != 2:
            continue
        chain, prev, x = [s], None, s
        ok = True
        while True:
            seen.add(x)
            nb = [y for y in adj[x] if y != prev]
            if len(adj[x]) != 2 or not nb:
                ok = False
                break
            prev, x = x, nb[0]
            if x == s:
                break
            if x in seen:
                ok = False
                break
            chain.append(x)
        if not ok or len(chain) < 3:
            continue
        P = V[chain]
        c = P.mean(axis=0)
        sv = np.linalg.svd(P - c, compute_uv=False)
        if sv[-1] / max(np.sqrt(len(chain)), 1) < tol:
            caps.append(chain)
    return loops + caps, len(caps)


def zip_boundary(loops, V, tol, rounds=3):
    """Stitch the remaining open seams of a mesh whose two sides were
    tessellated differently (chords of one curve against chords of
    another): border corners closer than ``tol`` are welded, then border
    corners lying within ``tol`` of a border edge are inserted into it.
    Returns (loops, number of welds + insertions)."""
    done = 0
    for _ in range(rounds):
        bnd = _boundary(loops)
        if not bnd:
            break
        bv = sorted({i for e in bnd for i in e})
        # weld close border corners (keep the lowest index)
        remap = {}
        P = V[bv]
        for i, a in enumerate(bv):
            if a in remap:
                continue
            d = np.linalg.norm(P - P[i], axis=1)
            for j in np.nonzero(d < tol)[0]:
                b = bv[j]
                if b != a and b not in remap:
                    remap[b] = a
        if remap:
            done += len(remap)
            new = []
            for l in loops:
                m = []
                for x in l:
                    x = remap.get(x, x)
                    if not m or m[-1] != x:
                        m.append(x)
                while len(m) > 1 and m[0] == m[-1]:
                    m.pop()
                if len(m) >= 3:
                    new.append(m)
            loops = new
        loops, n = split_t_junctions(loops, V, tol)
        done += n
        if not remap and not n:
            break
    return loops, done

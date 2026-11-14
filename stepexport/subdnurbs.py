# SPDX-License-Identifier: GPL-3.0-or-later
"""A SubD control cage as bicubic B-spline faces (the NURBS export).

The smooth surface IngeTrazo's Subdivision extension draws is the
Catmull-Clark limit surface of a control cage (points, polygons, creases).
Over a quad of the cage whose corners are ordinary (four quads around each,
no crease) that surface *is* a bicubic polynomial patch, so B-spline faces
can carry it exactly; around extraordinary points (valence other than 4)
and creases no polynomial is exact, and the faces are fitted.

The faces follow the cage: **one face per quad of the cage** (a triangle,
pentagon... is cut into its Catmull-Clark quads, one face each), so a
CAD program shows the panels the modeller drew. Each face is a clamped
uniform bicubic B-spline with ``spans`` knot spans per half edge of the
cage, raised until the faces are within the tolerance:

1. the cage is refined (Catmull-Clark) and every point pushed to its limit
   position: points *on* the limit surface, on a regular grid of each face's
   parameters;
2. each edge gets one curve, a least-squares fit of the limit points along
   it with its two ends kept; the faces on either side share that curve,
   so they meet exactly and a closed cage gives a closed solid. An edge of
   the cage next to a non-quad face is cut at its middle (the two halves
   are edges of the quads on the other side); the quad face then carries a
   triple knot there, so its border is exactly the two halves;
3. the inner control points are a least-squares fit of the face's limit
   points, its border being those edge curves.

Creases follow the Subdivision extension's rule: an edge of sharpness ``s``
uses the sharp rules for ``s`` steps, its two halves then keep ``s - 1``;
a vertex on two sharp edges follows the crease rule, on three or more it is
a corner. Open borders are sharp. Edges still sharp when the limit is taken
are treated as fully sharp.

Pure Python + numpy (no scipy, no Qt).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def ekey(a: int, b: int) -> tuple:
    return (a, b) if a < b else (b, a)


# ---- one Catmull-Clark step with creases ----------------------------------------------
def _cc_step(V: np.ndarray, faces: list, sharp: dict):
    """One Catmull-Clark step. ``faces``: lists of point indices (any
    polygon); ``sharp``: ``{edge: sharpness}`` for creased edges (>0).
    Returns ``(V2, quads, sharp2, edge_pt, nv)``: new points (old points
    keep their ids, then face points ``nv + face``, then edge points), the
    quads in face order (one per corner of each face: corner, edge point to
    the next corner, face point, edge point from the previous corner), the
    children's sharpness and the ids of the edge points."""
    nv = len(V)
    edge_faces: dict = {}
    vert_faces = [[] for _ in range(nv)]
    vert_edges = [set() for _ in range(nv)]
    for fi, f in enumerate(faces):
        k = len(f)
        for i in range(k):
            a, b = f[i], f[(i + 1) % k]
            e = ekey(a, b)
            edge_faces.setdefault(e, []).append(fi)
            vert_edges[a].add(e)
            vert_edges[b].add(e)
            vert_faces[a].append(fi)
    fpts = np.array([V[f].mean(axis=0) for f in faces])

    def is_sharp(e):
        return len(edge_faces[e]) != 2 or sharp.get(e, 0) > 0

    edges = list(edge_faces)
    eid = {e: nv + len(faces) + i for i, e in enumerate(edges)}
    epts = np.empty((len(edges), 3))
    for i, e in enumerate(edges):
        a, b = e
        if is_sharp(e):
            epts[i] = (V[a] + V[b]) / 2
        else:
            f1, f2 = edge_faces[e]
            epts[i] = (V[a] + V[b] + fpts[f1] + fpts[f2]) / 4
    vpts = np.empty_like(V)
    for v in range(nv):
        es = vert_edges[v]
        if not es:
            vpts[v] = V[v]
            continue
        sh = [e for e in es if is_sharp(e)]
        if len(sh) >= 3:
            vpts[v] = V[v]                                   # corner
        elif len(sh) == 2:                                   # crease / border
            o = [e[0] if e[1] == v else e[1] for e in sh]
            vpts[v] = (V[o[0]] + 6 * V[v] + V[o[1]]) / 8
        else:                                                # smooth (or dart)
            n = len(es)
            Q = fpts[vert_faces[v]].mean(axis=0)
            R = np.mean([(V[e[0]] + V[e[1]]) / 2 for e in es], axis=0)
            vpts[v] = (Q + 2 * R + (n - 3) * V[v]) / n
    V2 = np.vstack([vpts, fpts, epts])
    quads, sharp2 = [], {}
    for fi, f in enumerate(faces):
        k = len(f)
        fp = nv + fi
        for i in range(k):
            a, b, z = f[i], f[(i + 1) % k], f[i - 1]
            quads.append([a, eid[ekey(a, b)], fp, eid[ekey(z, a)]])
    for e, s in sharp.items():
        if s > 1 and e in eid:
            m = eid[e]
            sharp2[ekey(e[0], m)] = s - 1
            sharp2[ekey(m, e[1])] = s - 1
    return V2, quads, sharp2, eid, nv


def _limit_points(V: np.ndarray, quads: list, sharp: dict) -> np.ndarray:
    """Limit positions of a quad mesh's points (Catmull-Clark): smooth
    ``(n^2 v + 4 sum(edge neighbours) + sum(diagonals)) / (n (n + 5))``,
    crease ``(a + 4 v + b) / 6``, corner fixed."""
    nv = len(V)
    edge_faces: dict = {}
    nbr = [dict() for _ in range(nv)]
    diag = [[] for _ in range(nv)]
    for qi, q in enumerate(quads):
        for i in range(4):
            a, b = q[i], q[(i + 1) % 4]
            edge_faces.setdefault(ekey(a, b), []).append(qi)
            nbr[a][b] = True
            nbr[b][a] = True
            diag[q[i]].append(q[(i + 2) % 4])
    out = V.copy()
    for v in range(nv):
        ns = list(nbr[v])
        if not ns:
            continue
        sh = [w for w in ns if len(edge_faces[ekey(v, w)]) != 2
              or sharp.get(ekey(v, w), 0) > 0]
        if len(sh) >= 3:
            continue
        if len(sh) == 2:
            out[v] = (V[sh[0]] + 4 * V[v] + V[sh[1]]) / 6
            continue
        n = len(ns)
        out[v] = (n * n * V[v] + 4 * V[ns].sum(axis=0)
                  + V[diag[v]].sum(axis=0)) / (n * (n + 5))
    return out


def _refine(V: np.ndarray, faces: list, sharp: dict, samples: int):
    """One Catmull-Clark step, then ``samples`` more on each resulting quad
    kept as a grid of point ids. Returns ``(quads, grids, limit points,
    edge points of the first step)``: ``grids[k][i, j]`` (i along corner
    0 -> 3, j along corner 0 -> 1 of ``quads[k]``) indexes the limit points."""
    V1, quads, sk, eid1, _ = _cc_step(V, faces, sharp)
    grids = [np.array([[q[0], q[1]], [q[3], q[2]]]) for q in quads]
    Vk, quads_k = V1, [list(q) for q in quads]
    for _ in range(samples):
        cells, where = [], []
        for pi, g in enumerate(grids):
            n = g.shape[0] - 1
            for i in range(n):
                for j in range(n):
                    cells.append([g[i, j], g[i, j + 1], g[i + 1, j + 1], g[i + 1, j]])
                    where.append((pi, i, j))
        Vk, quads_k, sk, eid, nv = _cc_step(Vk, cells, sk)
        new = [np.zeros((2 * (g.shape[0] - 1) + 1,) * 2, int) for g in grids]
        for ci, (pi, i, j) in enumerate(where):
            g, G = grids[pi], new[pi]
            a, b, c, d = g[i, j], g[i, j + 1], g[i + 1, j + 1], g[i + 1, j]
            G[2 * i, 2 * j], G[2 * i, 2 * j + 2] = a, b
            G[2 * i + 2, 2 * j + 2], G[2 * i + 2, 2 * j] = c, d
            G[2 * i, 2 * j + 1] = eid[ekey(a, b)]
            G[2 * i + 1, 2 * j + 2] = eid[ekey(b, c)]
            G[2 * i + 2, 2 * j + 1] = eid[ekey(d, c)]
            G[2 * i + 1, 2 * j] = eid[ekey(a, d)]
            G[2 * i + 1, 2 * j + 1] = nv + ci
        grids = new
    return quads, grids, _limit_points(Vk, quads_k, sk), eid1


# ---- B-splines (clamped, cubic) --------------------------------------------------------
def knots_uniform(spans: int, split: bool = False) -> np.ndarray:
    """Clamped cubic knots on [0, 1]: ``spans`` equal spans; ``split``: two
    halves of ``spans // 2`` spans joined by a triple knot at 0.5 (a border
    made of two edge curves)."""
    if not split:
        inner = list(np.arange(1, spans) / spans)
    else:
        h = spans // 2
        inner = list(np.arange(1, h) / spans) + [0.5] * 3 + list(np.arange(h + 1, spans) / spans)
    return np.array([0.0] * 4 + inner + [1.0] * 4)


def basis(knots: np.ndarray, t, deriv: bool = False):
    """Cubic B-spline basis values (and first derivatives) at ``t``:
    arrays of shape (len(t), len(knots) - 4)."""
    t = np.atleast_1d(np.asarray(t, float))
    k = np.asarray(knots, float)
    n = len(k) - 4
    # degree 0
    N = np.zeros((len(t), len(k) - 1))
    for i in range(len(k) - 1):
        if k[i] < k[i + 1]:
            N[:, i] = (t >= k[i]) & (t < k[i + 1])
    last = max(i for i in range(len(k) - 1) if k[i] < k[i + 1])
    N[t >= k[-1], last] = 1.0
    prev = N
    for p in range(1, 4):
        cur = np.zeros((len(t), len(k) - 1 - p))
        for i in range(len(k) - 1 - p):
            d1, d2 = k[i + p] - k[i], k[i + p + 1] - k[i + 1]
            if d1 > 0:
                cur[:, i] += (t - k[i]) / d1 * prev[:, i]
            if d2 > 0:
                cur[:, i] += (k[i + p + 1] - t) / d2 * prev[:, i + 1]
        if p == 2:
            N2 = cur
        prev = cur
    if not deriv:
        return prev[:, :n]
    D = np.zeros((len(t), n))
    for i in range(n):
        d1, d2 = k[i + 3] - k[i], k[i + 4] - k[i + 1]
        if d1 > 0:
            D[:, i] += 3 / d1 * N2[:, i]
        if d2 > 0 and i + 1 < N2.shape[1]:
            D[:, i] -= 3 / d2 * N2[:, i + 1]
    return prev[:, :n], D


def insert_knot(ctrl: np.ndarray, knots: np.ndarray, t: float):
    """Boehm knot insertion (cubic): the same curve with one more knot."""
    k = np.asarray(knots, float)
    m = int(np.searchsorted(k, t, side="right")) - 1
    new = []
    for i in range(len(ctrl) + 1):
        if i <= m - 3:
            new.append(ctrl[i])
        elif i > m:
            new.append(ctrl[i - 1])
        else:
            a = (t - k[i]) / (k[i + 3] - k[i])
            new.append((1 - a) * ctrl[i - 1] + a * ctrl[i])
    return np.array(new), np.insert(k, m + 1, t)


def fit_curve(points: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Cubic B-spline (``knots``) through the first and last of ``points``
    (uniform parameters) closest to the others."""
    m = len(points) - 1
    N = basis(knots, np.arange(m + 1) / m)
    c = np.zeros((N.shape[1], 3))
    c[0], c[-1] = points[0], points[-1]
    rhs = points - np.outer(N[:, 0], c[0]) - np.outer(N[:, -1], c[-1])
    c[1:-1], *_ = np.linalg.lstsq(N[:, 1:-1], rhs, rcond=None)
    return c


def fit_surface(grid: np.ndarray, ku, kv, border: dict) -> np.ndarray:
    """Control net ``P[i][j]`` (i along v, j along u) of the B-spline with
    knots ``ku``, ``kv`` closest to ``grid`` (limit points on uniform
    parameters), its border rows / columns being the given control
    polygons: ``'v0'`` (row 0), ``'v1'`` (last row), ``'u0'`` (column 0),
    ``'u1'`` (last column)."""
    m = grid.shape[0] - 1
    t = np.arange(m + 1) / m
    Nu, Nv = basis(ku, t), basis(kv, t)
    cu, cv = Nu.shape[1], Nv.shape[1]
    P = np.zeros((cv, cu, 3))
    P[0, :], P[-1, :] = border["v0"], border["v1"]
    P[:, 0], P[:, -1] = border["u0"], border["u1"]
    W = np.einsum("ia,jb->ijab", Nv, Nu).reshape((m + 1) ** 2, cv * cu)
    known = np.ones((cv, cu), bool)
    known[1:-1, 1:-1] = False
    kn = known.ravel()
    rhs = grid.reshape(-1, 3) - W[:, kn] @ P.reshape(-1, 3)[kn]
    inner, *_ = np.linalg.lstsq(W[:, ~kn], rhs, rcond=None)
    P.reshape(-1, 3)[~kn] = inner
    return P


def _tensor(Na, Nb, P):
    """sum over a, b of Na[n, a] Nb[n, b] P[a, b] for every n (a matrix
    product, then a weighted sum: no big temporary)."""
    cv, cu, _ = P.shape
    T = (Nb @ P.transpose(1, 0, 2).reshape(cu, cv * 3)).reshape(-1, cv, 3)
    return np.einsum("na,nak->nk", Na, T)


def eval_surface(P, ku, kv, u, v, deriv=False):
    u, v = np.ravel(u), np.ravel(v)
    if not deriv:
        return _tensor(basis(kv, v), basis(ku, u), P)
    Nu, Du = basis(ku, u, True)
    Nv, Dv = basis(kv, v, True)
    return _tensor(Nv, Nu, P), _tensor(Nv, Du, P), _tensor(Dv, Nu, P)


def distance_to_surface(P, ku, kv, pts, u, v, iters: int = 10) -> np.ndarray:
    """Distance from each point to the face: Gauss-Newton from the given
    parameters, kept inside the face. Near an extraordinary point the
    subdivision's own parameters are not the polynomial's, so the gap at
    equal parameters overstates the true (geometric) distance."""
    u = np.asarray(u, float).copy()
    v = np.asarray(v, float).copy()
    for _ in range(iters):
        x, xu, xv = eval_surface(P, ku, kv, u, v, True)
        r = x - pts
        a, b, c = (xu * xu).sum(1), (xu * xv).sum(1), (xv * xv).sum(1)
        g1, g2 = (xu * r).sum(1), (xv * r).sum(1)
        det = a * c - b * b
        det = np.where(np.abs(det) < 1e-30, 1e-30, det)
        u = np.clip(u - (c * g1 - b * g2) / det, 0.0, 1.0)
        v = np.clip(v - (a * g2 - b * g1) / det, 0.0, 1.0)
    return np.linalg.norm(eval_surface(P, ku, kv, u, v) - pts, axis=1)


# ---- the whole conversion -------------------------------------------------------------
@dataclass
class BFace:
    loop: list            # [(edge key, forward)] around the face, counter-clockwise
    net: np.ndarray       # control points P[i][j], i along v, j along u
    ku: np.ndarray
    kv: np.ndarray


@dataclass
class NurbsShell:
    """B-spline faces of one SubD body. Points in the cage's units.

    ``verts``: ``{id: point}``; ``edges``: ``{(a, b): (control points from a
    to b, knots)}`` with a < b; ``faces``: :class:`BFace`; ``closed``."""
    verts: dict
    edges: dict
    faces: list
    closed: bool
    max_fit: float = 0.0           # largest distance from the limit points to the faces
    spans: int = 1
    exact_faces: int = 0           # faces whose fit is exact (ordinary areas)
    notes: list = field(default_factory=list)


def _place_children(grids, k0, M):
    """The four child grids of a cage quad as one (2M+1) grid, u along
    corner 0 -> 1 and v along corner 0 -> 3 of the cage face."""
    F = np.full((2 * M + 1, 2 * M + 1), -1, int)
    g0, g1, g2, g3 = (grids[k0 + i] for i in range(4))
    F[:M + 1, :M + 1] = g0                                  # corner a: u -> b, v -> d
    for i in range(M + 1):
        for j in range(M + 1):
            F[j, 2 * M - i] = g1[i, j]                      # corner b: u -> c, v -> a
            F[2 * M - i, 2 * M - j] = g2[i, j]              # corner c: u -> d, v -> b
            F[2 * M - j, i] = g3[i, j]                      # corner d: u -> a, v -> c
    assert (F >= 0).all()
    return F


def cage_to_bspline(points, faces, creases=None, spans: int = 1, samples: int | None = None,
                    exact_tol: float = 1e-9, merge: bool = True) -> NurbsShell:
    """B-spline faces of a Catmull-Clark cage (see module text): one face per
    quad of the cage, ``spans`` knot spans per half edge. ``merge=False``:
    one face per quad of the once-refined cage instead (every cage face cut
    into its Catmull-Clark quads)."""
    V = np.asarray(points, dtype=float)
    cage = [list(map(int, f)) for f in faces if len(f) >= 3]
    sharp = {ekey(int(a), int(b)): float(s) for (a, b), s in (creases or {}).items()
             if s and s > 0}
    spans = max(1, int(spans))
    if samples is None:
        samples = int(np.ceil(np.log2(spans))) + 2            # 4 points per span
    quads, grids, L, eid1 = _refine(V, cage, sharp, samples)
    M = 2 ** samples
    size = max(1.0, float(np.ptp(V, axis=0).max()))

    first = []                                              # first child of each face
    k = 0
    for f in cage:
        first.append(k)
        k += len(f)
    merged = [merge and len(f) == 4 for f in cage]
    edge_faces: dict = {}
    for fi, f in enumerate(cage):
        for i in range(len(f)):
            edge_faces.setdefault(ekey(f[i], f[(i + 1) % len(f)]), []).append(fi)
    split = {e for e, fs in edge_faces.items() if any(not merged[x] for x in fs)}

    edges: dict = {}

    def edge(a, b, pts, n):
        """The curve from a to b (shared): (key, forward)."""
        key = ekey(a, b)
        if key not in edges:
            p = pts if a < b else pts[::-1]
            kn = knots_uniform(n)
            edges[key] = (fit_curve(p, kn), kn)
        return key, a < b

    def ctrl(key, fwd):
        c, _ = edges[key]
        return c if fwd else c[::-1]

    regions = []                                            # (corner ids, grid)
    for fi, f in enumerate(cage):
        if merged[fi]:
            regions.append((fi, f, _place_children(grids, first[fi], M)))
        else:
            for i in range(len(f)):
                q = quads[first[fi] + i]
                regions.append((None, q, grids[first[fi] + i]))

    out, worst, exact = [], 0.0, 0
    for fi, c, G in regions:
        m = G.shape[0] - 1
        if fi is None:                                       # a child quad: 4 half edges
            loop, sides = [], []
            for i in range(4):
                line = [G[0, :], G[:, m], G[m, ::-1], G[::-1, 0]][i]
                key, fwd = edge(int(line[0]), int(line[-1]), L[line], spans)
                loop.append((key, fwd))
                sides.append(ctrl(key, fwd))
            ku = kv = knots_uniform(spans)
            border = {"v0": sides[0], "u1": sides[1], "v1": sides[2][::-1], "u0": sides[3][::-1]}
        else:                                                # a cage quad: full or halved edges
            a, b, cc, d = c
            cut = [ekey(a, b) in split, ekey(b, cc) in split,
                   ekey(cc, d) in split, ekey(d, a) in split]
            ku = knots_uniform(2 * spans, cut[0] or cut[2])
            kv = knots_uniform(2 * spans, cut[1] or cut[3])
            loop, polys = [], []
            lines = [G[0, :], G[:, m], G[m, ::-1], G[::-1, 0]]
            for i, line in enumerate(lines):
                kn_dir = ku if i in (0, 2) else kv
                if cut[i]:                                   # two half edges, meeting at the middle
                    h = m // 2
                    parts = []
                    for seg in (line[:h + 1], line[h:]):
                        key, fwd = edge(int(seg[0]), int(seg[-1]), L[seg], spans)
                        loop.append((key, fwd))
                        parts.append(ctrl(key, fwd))
                    poly = np.vstack([parts[0], parts[1][1:]])
                else:
                    key, fwd = edge(int(line[0]), int(line[-1]), L[line], 2 * spans)
                    loop.append((key, fwd))
                    poly, kn = ctrl(key, fwd), knots_uniform(2 * spans)
                    if 0.5 in kn_dir[4:-4] and list(kn_dir).count(0.5) == 3:
                        for _ in range(2):                   # same curve, on the face's knots
                            poly, kn = insert_knot(poly, kn, 0.5)
                polys.append(poly)
            border = {"v0": polys[0], "u1": polys[1], "v1": polys[2][::-1], "u0": polys[3][::-1]}
        grid = L[G]
        P = fit_surface(grid, ku, kv, border)
        t = np.arange(m + 1) / m
        uu, vv = np.meshgrid(t, t)
        gap_p = np.linalg.norm(eval_surface(P, ku, kv, uu, vv) - grid.reshape(-1, 3), axis=1)
        if float(gap_p.max()) <= exact_tol * size:
            exact += 1
            gap = float(gap_p.max())
        else:
            # the gap at equal parameters bounds the distance; only the
            # points that could hold the maximum are projected
            hot = gap_p > 0.5 * gap_p.max()
            d = distance_to_surface(P, ku, kv, grid.reshape(-1, 3)[hot],
                                    uu.ravel()[hot], vv.ravel()[hot])
            gap = float(max(np.minimum(d, gap_p[hot]).max(),
                            gap_p[~hot].max() if (~hot).any() else 0.0))
        worst = max(worst, gap)
        out.append(BFace(loop, P, ku, kv))

    count: dict = {}
    for f in out:
        for key, _ in f.loop:
            count[key] = count.get(key, 0) + 1
    closed = bool(count) and all(n == 2 for n in count.values())
    verts = {}
    for key in edges:
        for v in key:
            verts[v] = L[v]
    return NurbsShell(verts, edges, out, closed, worst, spans, exact)


def shell_volume(sh: NurbsShell, order: int = 6) -> float:
    """Volume enclosed by the faces (divergence theorem, Gauss quadrature on
    each knot span: V = 1/3 sum of the integral of P . (Pu x Pv)); 0 for an
    open shell."""
    if not sh.closed:
        return 0.0
    x, w = np.polynomial.legendre.leggauss(order)
    tot = 0.0
    for f in sh.faces:
        bu, bv = np.unique(f.ku), np.unique(f.kv)
        for u0, u1 in zip(bu[:-1], bu[1:]):
            for v0, v1 in zip(bv[:-1], bv[1:]):
                tu = u0 + (x + 1) / 2 * (u1 - u0)
                tv = v0 + (x + 1) / 2 * (v1 - v0)
                uu, vv = np.meshgrid(tu, tv)
                p, pu, pv = eval_surface(f.net, f.ku, f.kv, uu, vv, True)
                W = np.outer(w, w).ravel() * (u1 - u0) * (v1 - v0) / 4
                tot += float(np.sum(W * np.einsum("nk,nk->n", p, np.cross(pu, pv))))
    return tot / 3


def cage_to_patches(points, faces, creases=None, levels: int = 1) -> NurbsShell:
    """Small patches: one bicubic Bezier face per quad of the cage refined
    ``levels`` times (the first export, kept for SubD tools that work on such
    patches, e.g. a CAD program's own subdivision editing)."""
    V = np.asarray(points, dtype=float)
    F = [list(map(int, f)) for f in faces if len(f) >= 3]
    sharp = {ekey(int(a), int(b)): float(s) for (a, b), s in (creases or {}).items()
             if s and s > 0}
    for _ in range(max(1, int(levels)) - 1):
        V, F, sharp, _e, _n = _cc_step(V, F, sharp)
    sh = cage_to_bspline(V, F, sharp, spans=1, merge=False)
    sh.notes.append(f"levels={max(1, int(levels))}")
    return sh


def cage_to_nurbs_tol(points, faces, creases=None, tol=None, max_spans: int = 8,
                      mode: str = "panels", max_levels: int = 3) -> NurbsShell:
    """The faces within ``tol`` (cage units) of the subdivision surface, as
    few as possible. ``mode``: ``"panels"`` one face per cage quad, knot spans
    added until it holds (V2); ``"patches"`` small Bezier patches, the cage
    refined until it holds (V1). Without ``tol``: the coarsest."""
    if mode == "patches":
        lv = 1
        sh = cage_to_patches(points, faces, creases, lv)
        while tol is not None and sh.max_fit > tol and lv < max_levels:
            lv += 1
            sh = cage_to_patches(points, faces, creases, lv)
        return sh
    n = 1
    sh = cage_to_bspline(points, faces, creases, spans=n)
    while tol is not None and sh.max_fit > tol and n < max_spans:
        n *= 2
        sh = cage_to_bspline(points, faces, creases, spans=n)
    return sh


def from_ext(ext: dict):
    """``(points, faces, creases)`` of a SubD group's ``ext`` payload (the
    Subdivision extension's format), or ``None``."""
    data = (ext or {}).get("subdiv")
    if not data or "cage" not in data:
        return None
    cage = data["cage"]
    pts = [tuple(map(float, p)) for p in cage.get("verts", [])]
    fs = [list(map(int, f)) for f in cage.get("faces", [])]
    cr = {ekey(int(a), int(b)): float(s) for a, b, s in cage.get("creases", [])}
    return pts, fs, cr

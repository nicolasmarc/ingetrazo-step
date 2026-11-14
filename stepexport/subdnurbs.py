# SPDX-License-Identifier: GPL-3.0-or-later
"""A SubD control cage as bicubic B-spline faces (the NURBS export, V1).

The smooth surface IngeTrazo's Subdivision extension draws is the
Catmull-Clark limit surface of a control cage (points, polygons, creases).
After one Catmull-Clark step every face is a quad, and over a quad whose
corners are all ordinary (four quads around each, no crease) the limit
surface *is* a uniform bicubic B-spline patch. So one bicubic patch per
quad of that once-refined cage represents the surface: exactly on ordinary
quads, closely around extraordinary points (valence other than 4) and
creases, where no single polynomial patch is exact.

How each patch is built, the same way everywhere:

1. the quad is refined ``samples`` more times (2^samples + 1 points a side)
   and every point pushed to its limit position: points *on* the limit
   surface, at the patch's own dyadic parameters;
2. each edge of the refined cage gets one cubic curve, a least-squares fit
   of the limit points along it with its two corners kept; the two quads on
   either side of an edge share that curve, so the faces meet exactly and a
   closed cage gives a closed solid;
3. the four inner control points of the patch are a least-squares fit of
   its inner limit points, its border being those four edge curves.

On an ordinary quad the limit points lie on a bicubic polynomial at exactly
those parameters, so the fit returns it (to rounding): the export is exact
there. Elsewhere the fit error is measured and reported.

Creases follow the Subdivision extension's rule: an edge of sharpness ``s``
uses the sharp rules for ``s`` steps, its two halves then keep ``s - 1``;
a vertex on two sharp edges follows the crease rule, on three or more it is
a corner. Open borders are sharp. Edges still sharp when the limit is taken
are treated as fully sharp (the remaining smoothing steps are under the
sampling's resolution).

Pure Python + numpy, no Qt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def ekey(a: int, b: int) -> tuple:
    return (a, b) if a < b else (b, a)


# ---- one Catmull-Clark step with creases ----------------------------------------------
def _cc_step(V: np.ndarray, faces: list, sharp: dict):
    """One Catmull-Clark step. ``faces``: lists of point indices (any
    polygon); ``sharp``: ``{edge: sharpness}`` for creased edges (>0).
    Returns ``(V2, quads, sharp2, edge_pt, face_pt)``: new points, the quads
    in face order (one per corner of each face: corner, edge point to the
    next corner, face point, edge point from the previous corner), the
    children's sharpness, and the ids of the edge points and face points."""
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
    # open borders stay sharp by having one face: nothing to carry
    return V2, quads, sharp2, eid, nv


def _limit_points(V: np.ndarray, quads: list, sharp: dict) -> np.ndarray:
    """Limit positions of a quad mesh's points (Catmull-Clark): smooth
    ``(n^2 v + 4 sum(edge neighbours) + sum(diagonals)) / (n (n + 5))``,
    crease ``(a + 4 v + b) / 6``, corner fixed."""
    nv = len(V)
    edge_faces: dict = {}
    nbr = [dict() for _ in range(nv)]                 # v -> {edge nbr: True}
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


# ---- Bernstein fitting ----------------------------------------------------------------
def _bern(t):
    t = np.asarray(t, dtype=float)
    s = 1 - t
    return np.stack([s ** 3, 3 * t * s * s, 3 * t * t * s, t ** 3], axis=-1)


def fit_cubic(points: np.ndarray) -> np.ndarray:
    """Cubic Bezier through the first and last of ``points`` (uniform
    parameters) closest to the others: 4 control points."""
    m = len(points) - 1
    t = np.arange(m + 1) / m
    B = _bern(t)
    p0, p3 = points[0], points[-1]
    rhs = points - np.outer(B[:, 0], p0) - np.outer(B[:, 3], p3)
    A = B[:, 1:3]
    mid, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    return np.vstack([p0, mid, p3])


def fit_patch(grid: np.ndarray, border: dict) -> np.ndarray:
    """Bicubic Bezier net ``P[i][j]`` (i along v, j along u) closest to
    ``grid`` (limit points, (m+1) x (m+1) x 3, uniform parameters), whose
    border rows / columns are the given curves: ``border['v0']`` (row i=0),
    ``'v1'`` (row i=3), ``'u0'`` (column j=0), ``'u1'`` (column j=3)."""
    m = grid.shape[0] - 1
    P = np.zeros((4, 4, 3))
    P[0, :] = border["v0"]
    P[3, :] = border["v1"]
    P[:, 0] = border["u0"]
    P[:, 3] = border["u1"]
    t = np.arange(m + 1) / m
    B = _bern(t)                                      # (m+1, 4)
    W = np.einsum("ia,jb->ijab", B, B).reshape((m + 1) ** 2, 16)
    known = np.ones((4, 4), bool)
    known[1:3, 1:3] = False
    kn = known.reshape(16)
    rhs = grid.reshape(-1, 3) - W[:, kn] @ P.reshape(16, 3)[kn]
    inner, *_ = np.linalg.lstsq(W[:, ~kn], rhs, rcond=None)
    P.reshape(16, 3)[~kn] = inner
    return P


def eval_patch(P: np.ndarray, u, v) -> np.ndarray:
    return np.einsum("...a,...b,abk->...k", _bern(v), _bern(u), P)


def _dbern(t):
    t = np.asarray(t, dtype=float)
    s = 1 - t
    return np.stack([-3 * s * s, 3 * s * s - 6 * t * s, 6 * t * s - 3 * t * t, 3 * t * t], axis=-1)


def distance_to_patch(P: np.ndarray, pts: np.ndarray, u, v, iters: int = 10) -> np.ndarray:
    """Distance from each point to the patch: Gauss-Newton from the given
    parameters, kept inside the patch. Near an extraordinary point the
    subdivision's own parameters are not the polynomial's, so the gap at
    equal parameters overstates the true (geometric) distance."""
    u = np.asarray(u, float).copy()
    v = np.asarray(v, float).copy()
    for _ in range(iters):
        Bu, Bv, Du, Dv = _bern(u), _bern(v), _dbern(u), _dbern(v)
        x = np.einsum("na,nb,abk->nk", Bv, Bu, P)
        xu = np.einsum("na,nb,abk->nk", Bv, Du, P)
        xv = np.einsum("na,nb,abk->nk", Dv, Bu, P)
        r = x - pts
        a, b, c = (xu * xu).sum(1), (xu * xv).sum(1), (xv * xv).sum(1)
        g1, g2 = (xu * r).sum(1), (xv * r).sum(1)
        det = a * c - b * b
        det = np.where(np.abs(det) < 1e-30, 1e-30, det)
        u = np.clip(u - (c * g1 - b * g2) / det, 0.0, 1.0)
        v = np.clip(v - (a * g2 - b * g1) / det, 0.0, 1.0)
    x = np.einsum("na,nb,abk->nk", _bern(v), _bern(u), P)
    return np.linalg.norm(x - pts, axis=1)


# ---- the whole conversion -------------------------------------------------------------
@dataclass
class NurbsShell:
    """Bicubic faces of one SubD body. Points in the cage's units.

    ``verts``: corner points; ``edges``: ``{(a, b): 4x3 Bezier}`` from a to b
    (a < b); ``faces``: ``[(corners (4 ids), net 4x4x3)]``, net ``P[i][j]``
    with u along corner 0 -> 1 and v along corner 0 -> 3; ``closed``."""
    verts: np.ndarray
    edges: dict
    faces: list
    closed: bool
    max_fit: float = 0.0           # largest gap between a patch and its limit points
    exact_faces: int = 0           # faces whose fit is exact (ordinary quads)
    notes: list = field(default_factory=list)


def cage_to_nurbs(points, faces, creases=None, samples: int = 3, levels: int = 1,
                  exact_tol: float = 1e-9) -> NurbsShell:
    """Bicubic B-spline faces of a Catmull-Clark cage (see module text).
    ``creases``: ``{(a, b): sharpness}``; ``samples``: refinement levels used
    to measure the limit surface on each patch (3 = 9 x 9 points);
    ``levels``: Catmull-Clark steps before cutting into patches (1 = one
    face per quad of the once-refined cage; each more step divides the
    patches by 4 and the error around extraordinary points by about 4)."""
    V = np.asarray(points, dtype=float)
    faces = [list(map(int, f)) for f in faces if len(f) >= 3]
    sharp = {ekey(int(a), int(b)): float(s) for (a, b), s in (creases or {}).items()
             if s and s > 0}

    # the once-refined cage: its quads become the faces
    V1, quads, sharp1, _eid, _nv = _cc_step(V, faces, sharp)
    for _ in range(max(1, int(levels)) - 1):
        V1, quads, sharp1, _eid, _nv = _cc_step(V1, quads, sharp1)
    n_patch = len(quads)
    # each patch as a grid of point ids, refined ``samples`` times
    grids = [np.array([[q[0], q[1]], [q[3], q[2]]]) for q in quads]
    Vk, sk = V1, sharp1
    for _ in range(samples):
        cells, where = [], []
        for pi, g in enumerate(grids):
            n = g.shape[0] - 1
            for i in range(n):
                for j in range(n):
                    cells.append([g[i, j], g[i, j + 1], g[i + 1, j + 1], g[i + 1, j]])
                    where.append((pi, i, j))
        Vk2, q2, sk2, eid, nv = _cc_step(Vk, cells, sk)
        new = []
        for g in grids:
            n = g.shape[0] - 1
            G = np.zeros((2 * n + 1, 2 * n + 1), int)
            new.append(G)
        for ci, (pi, i, j) in enumerate(where):
            g = grids[pi]
            G = new[pi]
            a, b, c, d = g[i, j], g[i, j + 1], g[i + 1, j + 1], g[i + 1, j]
            G[2 * i, 2 * j] = a
            G[2 * i, 2 * j + 2] = b
            G[2 * i + 2, 2 * j + 2] = c
            G[2 * i + 2, 2 * j] = d
            G[2 * i, 2 * j + 1] = eid[ekey(a, b)]
            G[2 * i + 1, 2 * j + 2] = eid[ekey(b, c)]
            G[2 * i + 2, 2 * j + 1] = eid[ekey(d, c)]
            G[2 * i + 1, 2 * j] = eid[ekey(a, d)]
            G[2 * i + 1, 2 * j + 1] = nv + ci
        grids, Vk, sk = new, Vk2, sk2
        quads_k = q2
    if samples == 0:
        quads_k = [list(q) for q in quads]
    L = _limit_points(Vk, quads_k, sk)

    # corners of the refined cage = patch corners; ids are those of V1 (kept)
    corner_ids = sorted({int(x) for q in quads for x in q})
    remap = {old: k for k, old in enumerate(corner_ids)}
    verts = L[corner_ids]

    # one curve per edge of the refined cage, from its limit points
    edges = {}
    for g in grids:
        m = g.shape[0] - 1
        for line in (g[0, :], g[m, :], g[:, 0], g[:, m]):
            a, b = int(line[0]), int(line[-1])
            k = (remap[a], remap[b])
            key = ekey(*k)
            if key in edges:
                continue
            pts = L[line]
            if k[0] > k[1]:
                pts = pts[::-1]
            edges[key] = fit_cubic(pts)

    def curve(a, b):
        c = edges[ekey(a, b)]
        return c if a < b else c[::-1]

    out_faces, worst, exact = [], 0.0, 0
    for q, g in zip(quads, grids):
        c = [remap[int(x)] for x in q]
        border = {"v0": curve(c[0], c[1]), "v1": curve(c[3], c[2]),
                  "u0": curve(c[0], c[3]), "u1": curve(c[1], c[2])}
        grid = L[g]
        P = fit_patch(grid, border)
        m = g.shape[0] - 1
        t = np.arange(m + 1) / m
        uu, vv = np.meshgrid(t, t)
        param_gap = np.linalg.norm(eval_patch(P, uu, vv) - grid, axis=-1)
        if float(param_gap.max()) <= exact_tol * max(1.0, float(np.ptp(V, axis=0).max())):
            exact += 1
            gap = float(param_gap.max())
        else:
            gap = float(distance_to_patch(P, grid.reshape(-1, 3), uu.ravel(), vv.ravel()).max())
        worst = max(worst, gap)
        out_faces.append((c, P))

    # closed when every refined edge has two faces
    count: dict = {}
    for c, _ in out_faces:
        for i in range(4):
            e = ekey(c[i], c[(i + 1) % 4])
            count[e] = count.get(e, 0) + 1
    closed = bool(count) and all(n == 2 for n in count.values())
    return NurbsShell(verts, edges, out_faces, closed, worst, exact)


def shell_volume(sh: NurbsShell, order: int = 6) -> float:
    """Volume enclosed by the faces (divergence theorem, Gauss quadrature:
    V = 1/3 sum of the integral of P . (Pu x Pv)); 0 for an open shell."""
    if not sh.closed:
        return 0.0
    x, w = np.polynomial.legendre.leggauss(order)
    t, w = (x + 1) / 2, w / 2
    B, D = _bern(t), _dbern(t)
    W = np.outer(w, w)
    tot = 0.0
    for _c, P in sh.faces:
        p = np.einsum("ia,jb,abk->ijk", B, B, P)
        pu = np.einsum("ia,jb,abk->ijk", B, D, P)
        pv = np.einsum("ia,jb,abk->ijk", D, B, P)
        tot += float(np.sum(W * np.einsum("ijk,ijk->ij", p, np.cross(pu, pv))))
    return tot / 3


def cage_to_nurbs_tol(points, faces, creases=None, tol=None, max_levels: int = 3,
                      samples: int = 3) -> NurbsShell:
    """:func:`cage_to_nurbs` with as few refinement levels as keep the
    patches within ``tol`` (cage units) of the limit surface they were fitted
    to; one level when ``tol`` is None."""
    sh = cage_to_nurbs(points, faces, creases, samples=samples, levels=1)
    lv = 1
    while tol is not None and sh.max_fit > tol and lv < max_levels:
        lv += 1
        sh = cage_to_nurbs(points, faces, creases, samples=samples, levels=lv)
    sh.notes.append(f"levels={lv}")
    return sh


def transformed(sh: NurbsShell, fn) -> NurbsShell:
    """The same shell with every point mapped by ``fn`` (an affine map:
    Bezier nets map point by point)."""
    m = lambda a: np.apply_along_axis(lambda p: np.asarray(fn(tuple(p)), float), -1, a)
    return NurbsShell(m(sh.verts), {k: m(c) for k, c in sh.edges.items()},
                      [(c, m(P)) for c, P in sh.faces], sh.closed, sh.max_fit,
                      sh.exact_faces, list(sh.notes))


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

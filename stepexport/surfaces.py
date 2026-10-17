"""V2 — recognise cylinders in a faceted, closed shell.

A pushed circle, a drilled hole or a fillet reaches us as a ring of narrow
planar facets. We find them back and fit the exact cylinder they were cut
from, so the STEP file can carry a true CYLINDRICAL_SURFACE (and CIRCLE edges)
instead of the facets.

Method (textbook geometry, nothing more):

* candidate "smooth" edges join two facets: the modeller's soft edges when
  the part carries them (``mode="soft"``), else every edge whose dihedral
  angle is below ``angle_max`` (``mode="geometry"``);
* regions grow from a seed of three consecutive facets, face by face across
  smooth edges, and a facet joins only if it lies on the current cylinder:
  its normal perpendicular to the axis and its corners on the circle, within
  ``tol`` — so a flat wall tangent to a fillet stays out of it;
* the fit: the axis is the direction most perpendicular to every facet normal
  (smallest singular vector), then a least-squares circle (Kasa) on the
  corners projected along that axis.

Everything is in the part's own units (metres for IngeTrazo).
"""
from collections import defaultdict, deque
from dataclasses import dataclass
import math
import numpy as np
from .check import newell

NORMAL_TOL = 1e-3          # |n . axis| of a facet of a true cylinder
MIN_TURN = math.radians(5)  # the facets must turn at least this much


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def perp(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(a, n)
    return x / np.linalg.norm(x)


@dataclass
class Cylinder:
    center: np.ndarray        # a point of the axis
    axis: np.ndarray          # unit
    radius: float
    ref: np.ndarray           # unit, perpendicular to axis (angle origin)

    @property
    def v(self):
        return np.cross(self.axis, self.ref)

    def h(self, p):
        return float((np.asarray(p, float) - self.center) @ self.axis)

    def theta(self, p):
        d = np.asarray(p, float) - self.center
        return math.atan2(d @ self.v, d @ self.ref)

    def radial(self, p):
        d = np.asarray(p, float) - self.center
        d = d - (d @ self.axis) * self.axis
        return d / np.linalg.norm(d)

    def residual(self, pts):
        d = np.asarray(pts, float) - self.center
        d = d - np.outer(d @ self.axis, self.axis)
        return float(np.abs(np.linalg.norm(d, axis=1) - self.radius).max())


def fit_cylinder(points, normals, tol):
    """Cylinder through ``points`` whose facets have ``normals``; ``None``
    when they are not on one cylinder within ``tol``."""
    N = np.asarray(normals, float)
    _, s, vt = np.linalg.svd(N)
    a = vt[-1]
    if np.abs(N @ a).max() > NORMAL_TOL:
        return None
    # the normals must really turn (else: a flat strip, radius undefined)
    u = perp(a)
    v = np.cross(a, u)
    ang = np.arctan2(N @ v, N @ u)
    ang = np.sort(np.mod(ang, 2 * math.pi))
    gaps = np.diff(np.concatenate([ang, [ang[0] + 2 * math.pi]]))
    if 2 * math.pi - gaps.max() < MIN_TURN:
        return None
    P = np.asarray(points, float)
    x, y = P @ u, P @ v
    A = np.column_stack([x, y, np.ones_like(x)])
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    cx, cy = sol[0] / 2, sol[1] / 2
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    hmin = float((P @ a).min())
    cyl = Cylinder(cx * u + cy * v + hmin * a, a, r, u)
    if cyl.residual(P) > tol:
        return None
    return cyl


def _directed(face):
    for loop in face:
        for k in range(len(loop)):
            yield loop[k], loop[(k + 1) % len(loop)]


def find_cylinders(verts, faces, soft_pairs=None, mode="soft", tol=1e-5,
                   angle_max=20.0, min_faces=3):
    """-> list of regions ``{"faces": [ids], "cyl": Cylinder, "sense": +1|-1}``
    (+1: material inside the cylinder, a rod or a convex round; -1: a hole or
    a concave fillet). ``faces`` are oriented loops of vertex indices."""
    V = np.asarray(verts, float)
    nrm = [_unit(newell(V[f[0]])) for f in faces]
    facet = [len(f) == 1 for f in faces]          # no holes
    by_edge = defaultdict(list)
    for fi, f in enumerate(faces):
        for a, b in _directed(f):
            by_edge[(min(a, b), max(a, b))].append(fi)
    cos_max = math.cos(math.radians(angle_max))
    nbrs = defaultdict(set)
    for k, fs in by_edge.items():
        if len(fs) != 2 or not (facet[fs[0]] and facet[fs[1]]):
            continue
        f, g = fs
        if mode == "soft":
            ok = soft_pairs is not None and k in soft_pairs
        else:
            c = float(nrm[f] @ nrm[g])
            ok = cos_max < c < 1 - 1e-12
        if ok:
            nbrs[f].add(g)
            nbrs[g].add(f)

    def pts_of(ids):
        return V[sorted({i for fi in ids for i in faces[fi][0]})]

    used, regions = set(), []
    for f in range(len(faces)):
        if f in used or len(nbrs[f] - used) < 2:
            continue
        cyl, seed = None, None
        free = sorted(nbrs[f] - used)
        for i in range(len(free)):
            for j in range(i + 1, len(free)):
                ids = [free[i], f, free[j]]
                c = fit_cylinder(pts_of(ids), [nrm[k] for k in ids], tol)
                if c is not None:
                    cyl, seed = c, ids
                    break
            if cyl:
                break
        if cyl is None:
            continue
        region = set(seed)
        q = deque(seed)
        while q:
            g = q.popleft()
            for h in sorted(nbrs[g]):
                if h in region or h in used:
                    continue
                if abs(nrm[h] @ cyl.axis) > NORMAL_TOL:
                    continue
                if cyl.residual(V[faces[h][0]]) > tol:
                    continue
                trial = region | {h}
                c = fit_cylinder(pts_of(trial), [nrm[k] for k in trial], tol)
                if c is None:
                    continue
                region, cyl = trial, c
                q.append(h)
        if len(region) < min_faces:
            continue
        signs = []
        for fi in region:
            ctr = V[faces[fi][0]].mean(axis=0)
            signs.append(np.sign(nrm[fi] @ cyl.radial(ctr)))
        if len(set(signs)) != 1:
            continue
        used |= region
        regions.append({"faces": sorted(region), "cyl": cyl,
                        "sense": int(signs[0])})
    return regions

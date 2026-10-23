"""Assemble the B-rep topology the writer emits.

Input: one oriented shell (vertex loops) and the cylinder regions found by
:mod:`surfaces`. Output: faces made of loops of *edge uses*, and an edge
table where an edge is either a straight LINE between two vertices or an arc
/ full CIRCLE replacing a chain of facet edges. Planar faces keep their
plane; each accepted region becomes one face on its cylinder, its facets and
inner seams disappear, and the neighbouring faces (caps, walls) share the
same circle edges.

A region is accepted only when its border is made of segments the cylinder
can carry exactly: lines parallel to the axis, and the curves where a plane
face meets it: circle arcs for a cut square to the axis, ellipse arcs for a
cut at an angle (a mitred tube corner, an angled pipe end). Anything else (a
cross-drilled hole, two cylinders meeting...) keeps its facets and is listed
in ``rejected`` with the reason.
"""
import math
from collections import defaultdict
import numpy as np
from .check import newell


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _directed(loop):
    return [(loop[k], loop[(k + 1) % len(loop)]) for k in range(len(loop))]


MIN_CUT_COS = 0.05          # a cut within ~87 deg of the axis: not an ellipse


def face_plane(face, V):
    """(point, unit normal) of a planar face, exactly as the writer gives
    its PLANE (best fit on all corners when it has more than three)."""
    n = _unit(newell(V[face[0]]))
    if len(face[0]) > 3 or len(face) > 1:
        from .check import best_plane
        return best_plane(np.vstack([V[l] for l in face]), n)
    return V[face[0][0]], n


def _plan_region(R, faces, de2f, region_of, V, tol):
    """-> plan dict or a reason string."""
    fs = set(R["faces"])
    cyl = R["cyl"]
    a = cyl.axis
    bnd, internal = [], set()
    for fi in fs:
        for p, q in _directed(faces[fi][0]):
            g = de2f.get((q, p))
            if g is None:
                return "open border"
            if g in fs:
                internal.add((p, q))
            else:
                bnd.append((p, q))
    nxt = {}
    for p, q in bnd:
        if p in nxt:
            return "non-simple border"
        nxt[p] = q
    loops, seen = [], set()
    for p, _ in bnd:
        if p in seen:
            continue
        loop, x = [], p
        while x not in seen:
            seen.add(x)
            loop.append(x)
            x = nxt.get(x)
            if x is None:
                return "open border loop"
        loops.append(loop)

    def kind(p, q):
        d = V[q] - V[p]
        if np.linalg.norm(d - (d @ a) * a) < tol:
            return "ax"
        if abs(cyl.h(V[p]) - cyl.h(V[q])) < tol:
            return "arc"
        # a cut at an angle: the face across is a plane, the curve is the
        # ellipse where that plane meets the cylinder
        g = de2f[(q, p)]
        _, n = face_plane(faces[g], V)
        if abs(n @ a) < MIN_CUT_COS:
            return None
        return "arc"

    windings = []
    for loop in loops:
        w = 0.0
        for p, q in _directed(loop):
            k = kind(p, q)
            if k is None:
                return "border on a plane almost parallel to the axis"
            if k == "arc":
                if de2f[(q, p)] in region_of:
                    return "touches another cylinder"
                w += _wrap(cyl.theta(V[q]) - cyl.theta(V[p]))
        windings.append(w)
    full = [abs(abs(w) - 2 * math.pi) < 1e-6 for w in windings]
    seam = None
    if len(loops) == 1 and abs(windings[0]) < 1e-6:
        span = None
    elif len(loops) == 2 and all(full):
        s0, s1 = set(loops[0]), set(loops[1])
        for p, q in sorted(internal):
            if kind(p, q) == "ax" and p in s0 and q in s1:
                seam = (p, q)
                break
        if seam is None:
            return "no seam edge"
        loops = [loops[0][loops[0].index(seam[0]):] + loops[0][:loops[0].index(seam[0])],
                 loops[1][loops[1].index(seam[1]):] + loops[1][:loops[1].index(seam[1])]]
        span = 360.0
    else:
        return "unsupported topology (%d loops)" % len(loops)

    def key(p, q):
        k = kind(p, q)
        return ("ax", p, q) if k == "ax" else ("arc", de2f[(q, p)])

    arcs, seg_loops = [], []
    for loop in loops:
        segs = _directed(loop)
        if seam is None:            # start where the border changes nature
            starts = [i for i in range(len(segs))
                      if key(*segs[i]) != key(*segs[i - 1])]
            if not starts:
                return "border without axial line"
            i0 = starts[0]
            segs = segs[i0:] + segs[:i0]
        seg_loops.append(segs)
        chain = None
        for i, (p, q) in enumerate(segs):
            k = key(p, q)
            if k[0] == "arc":
                if chain is not None and key(*segs[i - 1]) == k:
                    chain.append(q)
                else:
                    chain = [p, q]
                    arcs.append(chain)
            else:
                chain = None
    if span is None and not arcs:
        return "border without arc"
    if span is None:
        span = max(abs(sum(_wrap(cyl.theta(V[c[i + 1]]) - cyl.theta(V[c[i]]))
                           for i in range(len(c) - 1))) for c in arcs)
        span = math.degrees(span)
    return {"loops": seg_loops, "arcs": arcs, "seam": seam, "span": span}


def build_brep(verts, faces, regions=(), tol=1e-5):
    """-> dict(faces=[...], edges={...}, cylinders=[...], rejected=[...]).

    face: ``{"surface": ("plane", point, normal) | ("cyl", Cylinder),
    "sense": bool, "loops": [[(edge_key, forward), ...], ...]}``.
    edge: ``{"start": vi, "end": vi, "curve": ("line",) |
    ("circle", center, axis, radius, same_sense) |
    ("ellipse", center, axis, major_dir, semi_major, semi_minor, same_sense)}``."""
    V = np.asarray(verts, float)
    de2f = {}
    for fi, f in enumerate(faces):
        for loop in f:
            for p, q in _directed(loop):
                de2f[(p, q)] = fi
    accepted, rejected = list(regions), []
    while True:
        region_of = {fi: ri for ri, R in enumerate(accepted) for fi in R["faces"]}
        plans, bad = [], None
        for ri, R in enumerate(accepted):
            others = {fi: r for fi, r in region_of.items() if r != ri}
            plan = _plan_region(R, faces, de2f, others, V, tol)
            if isinstance(plan, str):
                bad = (ri, plan)
                break
            plans.append(plan)
        if bad is None:
            break
        R = accepted.pop(bad[0])
        rejected.append({"radius": R["cyl"].radius, "facets": len(R["faces"]),
                         "reason": bad[1]})

    edges, seg2use = {}, {}
    for R, plan in zip(accepted, plans):
        cyl = R["cyl"]
        for chain in plan["arcs"]:
            k = ("arc",) + tuple(chain)
            g = de2f[(chain[1], chain[0])]
            p0, n = face_plane(faces[g], V)
            if abs(abs(n @ cyl.axis) - 1) < 1e-9 or \
                    max(abs(cyl.h(V[i]) - cyl.h(V[chain[0]])) for i in chain) < tol:
                h = cyl.h(V[chain[0]])
                center = cyl.center + h * cyl.axis
                d0, d1 = V[chain[0]] - center, V[chain[1]] - center
                same = float(np.cross(d0, d1) @ cyl.axis) > 0
                curve = ("circle", center, cyl.axis, cyl.radius, same)
            else:
                ca = float(n @ cyl.axis)
                center = cyl.center + (float(n @ (p0 - cyl.center)) / ca) * cyl.axis
                minor = _unit(np.cross(cyl.axis, n))
                major = _unit(np.cross(n, minor))
                R1 = cyl.radius / abs(ca)
                curve = ("ellipse", center, _unit(np.cross(major, minor)), major,
                         R1, cyl.radius, True)
                e = {"start": chain[0], "end": chain[-1], "curve": curve}
                t0, t1 = conic_param(e, V[chain[0]]), conic_param(e, V[chain[1]])
                curve = curve[:6] + (_wrap(t1 - t0) > 0,)
            edges[k] = {"start": chain[0], "end": chain[-1], "curve": curve}
            for i in range(len(chain) - 1):
                seg2use[(chain[i], chain[i + 1])] = (k, True)
                seg2use[(chain[i + 1], chain[i])] = (k, False)

    def use(p, q):
        if (p, q) in seg2use:
            return seg2use[(p, q)]
        k = ("line", min(p, q), max(p, q))
        if k not in edges:
            edges[k] = {"start": k[1], "end": k[2], "curve": ("line",)}
        return k, p == k[1]

    def compress(segs):
        uses = [use(p, q) for p, q in segs]
        for i, ((p, _), (k, fwd)) in enumerate(zip(segs, uses)):
            e = edges[k]
            if p == (e["start"] if fwd else e["end"]):
                break
        uses = uses[i:] + uses[:i]
        out = []
        for u in uses:
            if out and out[-1] == u and u[0][0] == "arc":
                continue
            out.append(u)
        return out

    in_region = {fi for R in accepted for fi in R["faces"]}
    out_faces = []
    for fi, f in enumerate(faces):
        if fi in in_region:
            continue
        c, n = face_plane(f, V)            # best fit: corners within µm
        out_faces.append({"surface": ("plane", c, n), "sense": True,
                          "loops": [compress(_directed(l)) for l in f]})
    cylinders = []
    for R, plan in zip(accepted, plans):
        if plan["seam"]:
            p, q = plan["seam"]
            segs = plan["loops"][0] + [(p, q)] + plan["loops"][1] + [(q, p)]
            loops = [compress(segs)]
        else:
            loops = [compress(plan["loops"][0])]
        out_faces.append({"surface": ("cyl", R["cyl"]), "sense": R["sense"] > 0,
                          "loops": loops})
        cylinders.append({"radius": R["cyl"].radius, "facets": len(R["faces"]),
                          "span": plan["span"], "convex": R["sense"] > 0,
                          "full": plan["seam"] is not None})
    return {"faces": out_faces, "edges": edges, "cylinders": cylinders,
            "rejected": rejected}


def conic_frame(edge, V):
    """(center, axis, x, y, rx, ry) of a circle or ellipse edge: the curve is
    center + rx cos(t) x + ry sin(t) y, t increasing about ``axis``."""
    c = edge["curve"]
    if c[0] == "circle":
        _, ctr, ax, r, _ = c
        x = _unit(V[edge["start"]] - ctr)
        return ctr, ax, x, np.cross(ax, x), r, r
    _, ctr, ax, x, rx, ry, _ = c
    return ctr, ax, x, np.cross(ax, x), rx, ry


def conic_param(edge, p):
    c = edge["curve"]
    if c[0] == "circle":
        raise ValueError("circle: use arc_angle")
    _, ctr, ax, x, rx, ry, _ = c
    d = np.asarray(p, float) - ctr
    return math.atan2((d @ np.cross(ax, x)) / ry, (d @ x) / rx)


def arc_angle(edge, V):
    """Signed parameter angle (about the curve axis) swept from start to end."""
    ctr, ax, x, y, rx, ry = conic_frame(edge, V)
    same = edge["curve"][-1]
    d0, d = V[edge["start"]] - ctr, V[edge["end"]] - ctr
    t0 = math.atan2((d0 @ y) / ry, (d0 @ x) / rx)
    t = (math.atan2((d @ y) / ry, (d @ x) / rx) - t0) % (2 * math.pi)
    if edge["start"] == edge["end"] or t < 1e-12:
        t = 2 * math.pi
    return t if same else -(2 * math.pi - t if t < 2 * math.pi else t)


def _cyl_edge_integral(cyl, e, fwd, V):
    """-r * integral of h(theta) (c.e(theta) + r) dtheta along a circle or
    ellipse edge lying on ``cyl`` (Green's theorem term of the cylinder
    face), closed form: on the cut plane h = h0 + al cos + be sin."""
    ctr, ax, x, y, rx, ry = conic_frame(e, V)
    s = e["start"] if fwd else e["end"]
    phi = arc_angle(e, V) * (1 if fwd else -1)
    dth = phi * (1.0 if ax @ cyl.axis > 0 else -1.0)
    t0 = cyl.theta(V[s])
    t1 = t0 + dth
    na = float(ax @ cyl.axis)
    r = cyl.radius
    h0 = float(ax @ (ctr - cyl.center)) / na
    al = -r * float(ax @ cyl.ref) / na
    be = -r * float(ax @ cyl.v) / na
    cu, cv = float(cyl.center @ cyl.ref), float(cyl.center @ cyl.v)
    S1 = math.sin(t1) - math.sin(t0)
    S2 = -(math.cos(t1) - math.cos(t0))
    S2t = (math.sin(2 * t1) - math.sin(2 * t0)) / 4
    Icc, Iss = dth / 2 + S2t, dth / 2 - S2t
    Ics = (math.sin(t1) ** 2 - math.sin(t0) ** 2) / 2
    tot = (h0 * (cu * S1 + cv * S2 + r * dth)
           + al * (cu * Icc + cv * Ics + r * S1)
           + be * (cu * Ics + cv * Iss + r * S2))
    return -r * tot


def brep_volume(verts, brep):
    """Exact enclosed volume (divergence theorem), arcs and cylinders
    included: plane faces by their area vector, cylinder faces by Green's
    theorem in the (angle, height) parameter plane."""
    V = np.asarray(verts, float)
    vol = 0.0
    for f in brep["faces"]:
        srf = f["surface"]
        if srf[0] == "plane":
            A = np.zeros(3)
            for loop in f["loops"]:
                for k, fwd in loop:
                    e = brep["edges"][k]
                    s, t = (e["start"], e["end"]) if fwd else (e["end"], e["start"])
                    if e["curve"][0] == "line":
                        A += 0.5 * np.cross(V[s], V[t])
                    else:
                        ctr, ax, _, _, rx, ry = conic_frame(e, V)
                        phi = arc_angle(e, V) * (1 if fwd else -1)
                        A += 0.5 * (np.cross(ctr, V[t] - V[s]) + rx * ry * phi * ax)
            vol += float(A @ srf[1]) / 3.0
        else:
            cyl = srf[1]
            I = 0.0
            for loop in f["loops"]:
                for k, fwd in loop:
                    e = brep["edges"][k]
                    if e["curve"][0] != "line":
                        I += _cyl_edge_integral(cyl, e, fwd, V)
            vol += I / 3.0
    return vol

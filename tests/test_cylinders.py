"""V2 — cylinder recognition, checked against closed-form volumes and by
re-reading the file with the independent reader (which samples the circles
and integrates over the cylinders on its own)."""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stepexport.model import Face, Part
from stepexport.writer import write_step
from stepexport.reader import read_solids, parse

SOFT_COS = 0.85        # IngeTrazo softens seams flatter than ~31.8 deg


def circle(cx, cy, r, n, a0=0.0, a1=2 * math.pi, closed=True):
    m = n if closed else n + 1
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n),
             cy + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(m)]


def ccw(loop):
    a = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1]))
    return loop if a > 0 else loop[::-1]


def extrude(outer, holes=(), z0=0.0, z1=0.1, soft=True):
    """Prism faces from a 2D profile (+ holes), and the soft edges a pushed
    profile gets in IngeTrazo (vertical seams between walls meeting at a
    shallow angle)."""
    outer = ccw(list(outer))
    holes = [ccw(list(h))[::-1] for h in holes]
    P = lambda p, z: (p[0], p[1], z)
    faces = [Face([P(p, z1) for p in outer], [[P(p, z1) for p in h] for h in holes]),
             Face([P(p, z0) for p in outer[::-1]], [[P(p, z0) for p in h[::-1]] for h in holes])]
    softs = []
    for loop in [outer] + holes:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            faces.append(Face([P(a, z0), P(b, z0), P(b, z1), P(a, z1)]))
            # seam at b between wall (a,b) and wall (b,c)
            c = loop[(i + 2) % n]
            u = np.subtract(b, a); w = np.subtract(c, b)
            cosang = float(u @ w / np.linalg.norm(u) / np.linalg.norm(w))
            if cosang > SOFT_COS:
                softs.append((P(b, z0), P(b, z1)))
    return faces, (softs if soft else None)


def run(part, **kw):
    kw.setdefault("cylinders", True)
    text, rep = write_step([part], **kw)
    s = read_solids(text)
    return text, rep, s


def close(a, b, rel=1e-6):
    return abs(a - b) <= rel * abs(b)


def test_rod_is_one_cylinder():
    r, h, n = 0.02, 0.1, 24                          # Ø40 x 100 mm, 24 facets
    f, soft = extrude(circle(0, 0, r, n), z1=h)
    text, rep, s = run(Part("Tige", f, soft_edges=soft))
    sh = rep["parts"][0]["shells"][0]
    assert s[0]["kind"] == "solid" and s[0]["edge_ok"]
    assert s[0]["faces"] == 3 and s[0]["surfaces"] == {"PLANE": 2, "CYLINDRICAL_SURFACE": 1}
    assert close(s[0]["radii"][0], 20.0)
    exact = math.pi * 20 ** 2 * 100
    assert close(sh["volume"], exact, 1e-9), sh["volume"]
    assert close(s[0]["volume"], exact, 1e-5), s[0]["volume"]
    c = sh["cylinders"][0]
    assert c["full"] and c["convex"] and c["facets"] == 24 and close(c["radius"], 20)


def test_without_v2_rod_stays_faceted():
    f, soft = extrude(circle(0, 0, 0.02, 24), z1=0.1)
    _, rep, s = run(Part("Tige", f, soft_edges=soft), cylinders=False)
    assert s[0]["faces"] == 26
    poly = 0.5 * 24 * 20 ** 2 * math.sin(2 * math.pi / 24) * 100
    assert close(s[0]["volume"], poly, 1e-9)


def test_panel_with_hinge_hole():
    # 600 x 400 x 18 panel, through hole Ø35 (32 facets)
    X, Y, T, R = .6, .4, .018, .0175
    rect = [(0, 0), (X, 0), (X, Y), (0, Y)]
    f, soft = extrude(rect, [circle(.3, .2, R, 32)], z1=T)
    _, rep, s = run(Part("Panneau", f, soft_edges=soft))
    assert s[0]["faces"] == 7 and s[0]["edge_ok"]
    assert s[0]["surfaces"]["CYLINDRICAL_SURFACE"] == 1
    c = rep["parts"][0]["shells"][0]["cylinders"][0]
    assert c["full"] and not c["convex"] and close(c["radius"], 17.5)
    exact = (600 * 400 - math.pi * 17.5 ** 2) * 18
    assert close(rep["parts"][0]["shells"][0]["volume"], exact, 1e-9)
    assert close(s[0]["volume"], exact, 1e-6)


def test_rounded_rectangle_fillets():
    # 100 x 60 plate, 4 corner radii 10 mm (6 facets each), 20 mm thick.
    # The flat walls are tangent to the fillets (soft seams too): they must
    # stay planar.
    W, H, r, n = .1, .06, .01, 6
    pts = []
    for cx, cy, a0 in [(W - r, r, -math.pi / 2), (W - r, H - r, 0),
                       (r, H - r, math.pi / 2), (r, r, math.pi)]:
        pts += circle(cx, cy, r, n, a0, a0 + math.pi / 2, closed=False)
    f, soft = extrude(pts, z1=.02)
    _, rep, s = run(Part("Plaque", f, soft_edges=soft))
    sh = rep["parts"][0]["shells"][0]
    assert s[0]["surfaces"] == {"PLANE": 6, "CYLINDRICAL_SURFACE": 4}, s[0]["surfaces"]
    assert all(not c["full"] and c["convex"] and abs(c["span"] - 90) < 1e-6
               for c in sh["cylinders"])
    exact = (100 * 60 - (4 - math.pi) * 10 ** 2) * 20
    assert close(sh["volume"], exact, 1e-9)
    assert close(s[0]["volume"], exact, 1e-6) and s[0]["edge_ok"]


def test_half_round_bar():
    r, n = .015, 12
    prof = circle(0, 0, r, n, 0, math.pi, closed=False)
    f, soft = extrude(prof, z1=.05)
    _, rep, s = run(Part("Demi-rond", f, soft_edges=soft))
    assert s[0]["surfaces"] == {"PLANE": 3, "CYLINDRICAL_SURFACE": 1}
    exact = math.pi * 15 ** 2 / 2 * 50
    assert close(s[0]["volume"], exact, 1e-6) and s[0]["edge_ok"]


def test_geometry_mode_without_soft_edges():
    f, _ = extrude(circle(0, 0, .02, 24), z1=.1, soft=False)
    _, rep, s = run(Part("Tige", f))                 # no hint -> geometry
    assert s[0]["surfaces"].get("CYLINDRICAL_SURFACE") == 1


def test_seventeen_facet_rod_without_soft_edges_is_a_cylinder():
    # a DXF baluster: 17 facets (21.2 deg each), no soft edges at all
    f, _ = extrude(circle(0, 0, .008, 17), z1=.8, soft=False)
    _, rep, s = run(Part("Balustre", f))
    assert s[0]["surfaces"] == {"PLANE": 2, "CYLINDRICAL_SURFACE": 1}


def test_dodecagon_is_not_a_cylinder_in_geometry_mode():
    f, _ = extrude(circle(0, 0, .02, 12), z1=.1, soft=False)   # 30 deg steps
    _, rep, s = run(Part("Prisme 12", f), cyl_mode="geometry")
    assert s[0]["faces"] == 14 and "CYLINDRICAL_SURFACE" not in s[0]["surfaces"]


def slanted(profile, holes=(), k=(0.0, 0.0), z0=0.0, kb=(0.0, 0.0), z1=0.1):
    """Prism over a 2D profile whose top is the plane z = z1 + kx x + ky y
    and bottom z = z0 + kbx x + kby y (cuts at an angle), with the soft
    seams IngeTrazo gives a pushed profile."""
    zt = lambda x, y: z1 + k[0] * x + k[1] * y
    zb = lambda x, y: z0 + kb[0] * x + kb[1] * y
    outer = ccw(list(profile))
    holes = [ccw(list(h))[::-1] for h in holes]
    faces = [Face([(x, y, zt(x, y)) for x, y in outer], [[(x, y, zt(x, y)) for x, y in h] for h in holes]),
             Face([(x, y, zb(x, y)) for x, y in outer[::-1]], [[(x, y, zb(x, y)) for x, y in h[::-1]] for h in holes])]
    softs = []
    for loop in [outer] + holes:
        n = len(loop)
        for i in range(n):
            (ax, ay), (bx, by) = loop[i], loop[(i + 1) % n]
            faces.append(Face([(ax, ay, zb(ax, ay)), (bx, by, zb(bx, by)),
                               (bx, by, zt(bx, by)), (ax, ay, zt(ax, ay))]))
            c = loop[(i + 2) % n]
            u = np.subtract((bx, by), (ax, ay)); w = np.subtract(c, (bx, by))
            if float(u @ w / np.linalg.norm(u) / np.linalg.norm(w)) > SOFT_COS:
                softs.append(((bx, by, zb(bx, by)), (bx, by, zt(bx, by))))
    return faces, softs


def test_oblique_cut_becomes_a_cylinder_with_an_ellipse():
    # issue #2: a rod whose top is cut at an angle (here ~56 deg off square)
    # is one cylinder bounded by an ELLIPSE; the exact volume is pi r^2 times
    # the mean height, the tilt averaging out over the disc
    r, n = .02, 24
    f, soft = slanted(circle(0, 0, r, n), k=(1.5, 0.0))
    text, rep, s = run(Part("Biseau", f, soft_edges=soft))
    sh = rep["parts"][0]["shells"][0]
    assert sh["rejected"] == [] and len(sh["cylinders"]) == 1, sh["rejected"]
    assert s[0]["kind"] == "solid" and s[0]["edge_ok"]
    assert s[0]["surfaces"] == {"PLANE": 2, "CYLINDRICAL_SURFACE": 1}
    assert text.count("ELLIPSE(") == 1 and text.count("CIRCLE(") == 1
    exact = math.pi * 20 ** 2 * 100
    assert close(sh["volume"], exact, 1e-9), sh["volume"]
    assert close(s[0]["volume"], exact, 1e-5), s[0]["volume"]


def test_pipe_cut_at_both_ends_and_an_angled_hole():
    # a tube with both ends cut at different angles (two ellipses per end):
    # 4 elliptical edges, exact volume = ring area x mean length
    f, soft = slanted(circle(0, 0, .03, 32), [circle(0, 0, .025, 32)],
                      k=(0.6, 0.2), kb=(-0.4, 0.0), z1=.2)
    text, rep, s = run(Part("Tube biais", f, soft_edges=soft))
    sh = rep["parts"][0]["shells"][0]
    assert sh["rejected"] == [] and len(sh["cylinders"]) == 2
    assert s[0]["surfaces"] == {"PLANE": 2, "CYLINDRICAL_SURFACE": 2} and s[0]["edge_ok"]
    assert text.count("ELLIPSE(") == 4
    exact = math.pi * (30 ** 2 - 25 ** 2) * 200
    assert close(sh["volume"], exact, 1e-9) and close(s[0]["volume"], exact, 1e-5)


def test_mitred_rounded_tube_corner():
    # a rounded-rectangle tube (outer radius 10, wall 3) mitred at 45 deg:
    # the 8 corner fillets become cylinders bounded by elliptic arcs at the
    # mitre and circle arcs at the square end
    W, H, ro, t, n = .1, .06, .01, .003, 8

    def rrect(w, h, rr, off):
        pts = []
        for cx, cy, a0 in [(w - rr, rr, -math.pi / 2), (w - rr, h - rr, 0),
                           (rr, h - rr, math.pi / 2), (rr, rr, math.pi)]:
            pts += circle(cx + off, cy + off, rr, n, a0, a0 + math.pi / 2, closed=False)
        return pts
    outer = rrect(W, H, ro, 0.0)
    inner = rrect(W - 2 * t, H - 2 * t, ro - t, t)
    f, soft = slanted(outer, [inner], k=(1.0, 0.0), z1=.15)
    text, rep, s = run(Part("Onglet", f, soft_edges=soft))
    sh = rep["parts"][0]["shells"][0]
    assert sh["rejected"] == [] and len(sh["cylinders"]) == 8, sh["rejected"]
    assert s[0]["kind"] == "solid" and s[0]["edge_ok"]
    assert text.count("ELLIPSE(") == 8 and text.count("CIRCLE(") == 8
    area = (W * H - (4 - math.pi) * ro ** 2) - ((W - 2 * t) * (H - 2 * t) - (4 - math.pi) * (ro - t) ** 2)
    cx = W / 2                                  # mean height: z1 + 1.0 * x over the section
    exact = area * (.15 + cx) * 1e9             # the ring is symmetric about x = W/2
    assert close(sh["volume"], exact, 1e-9), (sh["volume"], exact)
    assert close(s[0]["volume"], exact, 1e-5)


def test_cut_almost_along_the_axis_stays_faceted():
    # a plane within 3 deg of the axis would need a huge ellipse: refused
    r, n = .02, 24
    f, soft = slanted(circle(0, 0, r, n), k=(25.0, 0.0), z1=1.0)
    _, rep, s = run(Part("Long biseau", f, soft_edges=soft))
    sh = rep["parts"][0]["shells"][0]
    assert sh["cylinders"] == [] and "parallel" in sh["rejected"][0]["reason"]
    assert s[0]["kind"] == "solid" and s[0]["edge_ok"]


def test_tube_two_cylinders_and_annular_caps():
    f, soft = extrude(circle(0, 0, .03, 32), [circle(0, 0, .025, 32)], z1=.2)
    _, rep, s = run(Part("Tube", f, soft_edges=soft))
    assert s[0]["surfaces"] == {"PLANE": 2, "CYLINDRICAL_SURFACE": 2}
    assert [round(x, 9) for x in s[0]["radii"]] == [25.0, 30.0]
    exact = math.pi * (30 ** 2 - 25 ** 2) * 200
    assert close(s[0]["volume"], exact, 1e-6) and s[0]["edge_ok"]


def test_simplify_merges_a_finely_sampled_shallow_arc():
    # a 1 m wide plank whose top is a very flat arc in 200 facets (sagitta
    # 0.5 mm): with 0.2 mm tolerance it collapses to a handful of faces,
    # stays a solid, and its volume barely moves
    n, W, R = 200, 1.0, 250.0
    pts = [(0.0, 0.0)] + [(W * k / n, 0.05 + (R - math.sqrt(R * R - (W * k / n - W / 2) ** 2)) * -1 + 0.0005)
                          for k in range(n + 1)] + [(W, 0.0)]
    prof = [(x, y) for x, y in pts]
    f, _ = extrude(prof, z1=0.3, soft=False)
    part = Part("Planche", f)
    _, rep0, s0 = run(part, cylinders=False)
    _, rep1, s1 = run(part, cylinders=False, simplify_tol=0.0002)
    assert s1[0]["kind"] == "solid" and s1[0]["edge_ok"]
    assert s1[0]["faces"] < s0[0]["faces"] / 5, (s0[0]["faces"], s1[0]["faces"])
    assert abs(s1[0]["volume"] - s0[0]["volume"]) / s0[0]["volume"] < 1e-3
    assert any("merged" in n for n in rep1["notes"])


def test_v2_file_references_resolve():
    f, soft = extrude(circle(0, 0, .02, 24), z1=.1)
    text, _ = write_step([Part("C", f, soft_edges=soft)], cylinders=True)
    ents = parse(text)

    def refs(v):
        if isinstance(v, tuple) and v and v[0] == "ref":
            yield v[1]
        elif isinstance(v, (list, tuple)):
            for x in v:
                yield from refs(x)
    for lst in ents.values():
        for t, a in lst:
            for r in refs(a):
                assert r in ents, (t, r)
    assert "CYLINDRICAL_SURFACE" in text and "CIRCLE(" in text and text.isascii()


if __name__ == "__main__":
    for k, fn in list(globals().items()):
        if k.startswith("test_"):
            fn(); print("ok", k)

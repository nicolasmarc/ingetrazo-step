import math, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stepexport.model import Face, Part
from stepexport.writer import write_step
from stepexport.reader import read_solids, parse
from stepexport import check


def box_faces(x0, y0, z0, x1, y1, z1):
    p = lambda x, y, z: (x, y, z)
    a, b, c, d = p(x0, y0, z0), p(x1, y0, z0), p(x1, y1, z0), p(x0, y1, z0)
    e, f, g, h = p(x0, y0, z1), p(x1, y0, z1), p(x1, y1, z1), p(x0, y1, z1)
    quads = [[a, b, c, d], [e, f, g, h], [a, b, f, e], [b, c, g, f],
             [c, d, h, g], [d, a, e, h]]
    return [Face(q) for q in quads]


def roundtrip(parts, **kw):
    text, rep = write_step(parts, **kw)
    return text, rep, read_solids(text)


def test_cube_volume_and_units():
    # 0.1 m cube -> 100 mm cube: volume 1e6 mm3
    text, rep, s = roundtrip([Part("Cube", box_faces(0, 0, 0, .1, .1, .1))])
    assert len(s) == 1 and s[0]["kind"] == "solid"
    assert s[0]["faces"] == 6 and s[0]["edge_ok"]
    assert abs(s[0]["volume"] - 1e6) < 1e-3
    assert s[0]["units"] == "mm"
    assert abs(rep["parts"][0]["shells"][0]["volume"] - 1e6) < 1e-3


def test_inverted_faces_are_fixed():
    fs = box_faces(0, 0, 0, 1, 2, 3)
    flipped = [Face(list(reversed(f.outer))) if i % 2 else f
               for i, f in enumerate(fs)]
    _, rep, s = roundtrip([Part("Mixed", flipped)], scale=1.0, unit="m")
    assert s[0]["kind"] == "solid" and s[0]["edge_ok"]
    assert abs(s[0]["volume"] - 6.0) < 1e-9


def test_whole_inside_out_is_fixed():
    fs = [Face(list(reversed(f.outer))) for f in box_faces(0, 0, 0, 1, 1, 1)]
    _, rep, s = roundtrip([Part("In", fs)], scale=1.0, unit="m")
    assert abs(s[0]["volume"] - 1.0) < 1e-9


def test_through_hole_panel():
    # 600x400x18 mm panel with a square 100x100 through hole, in metres
    X, Y, T = .6, .4, .018
    hx0, hx1, hy0, hy1 = .25, .35, .15, .25
    outer = lambda z: [(0, 0, z), (X, 0, z), (X, Y, z), (0, Y, z)]
    hole = lambda z: [(hx0, hy0, z), (hx1, hy0, z), (hx1, hy1, z), (hx0, hy1, z)]
    faces = [Face(outer(0), [hole(0)]), Face(outer(T), [hole(T)])]
    o = outer(0)
    for i in range(4):
        a, b = o[i], o[(i + 1) % 4]
        faces.append(Face([a, b, (b[0], b[1], T), (a[0], a[1], T)]))
    h0 = hole(0)
    for i in range(4):
        a, b = h0[i], h0[(i + 1) % 4]
        faces.append(Face([a, b, (b[0], b[1], T), (a[0], a[1], T)]))
    text, rep, s = roundtrip([Part("Panneau", faces)])
    assert s[0]["kind"] == "solid" and s[0]["edge_ok"]
    expect = (600 * 400 - 100 * 100) * 18
    assert abs(s[0]["volume"] - expect) < 1e-3, s[0]["volume"]
    assert s[0]["faces"] == 10


def test_concave_L_prism():
    pts = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    z0, z1 = 0.0, 1.0
    f = [Face([(x, y, z0) for x, y in pts]), Face([(x, y, z1) for x, y in pts])]
    for i in range(6):
        a, b = pts[i], pts[(i + 1) % 6]
        f.append(Face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)]))
    _, _, s = roundtrip([Part("L", f)], scale=1.0, unit="m")
    assert abs(s[0]["volume"] - 3.0) < 1e-9 and s[0]["edge_ok"]


def test_two_parts_named_and_colored():
    parts = [Part("Côté gauche 'A'", box_faces(0, 0, 0, 1, 1, 1), (1, 0, 0)),
             Part("Fond", box_faces(2, 0, 0, 3, 1, 1))]
    text, rep, s = roundtrip(parts, scale=1.0, unit="m")
    assert len(s) == 2 and rep["solids"] == 2
    assert "STYLED_ITEM" in text and "COLOUR_RGB" in text
    assert "\\X2\\00F4\\X0\\" in text          # accent encoded as ASCII
    assert text.isascii()


def test_open_box_becomes_shell_with_report():
    fs = box_faces(0, 0, 0, 1, 1, 1)[:-1]       # one face missing
    _, rep, s = roundtrip([Part("Ouvert", fs)], scale=1.0, unit="m")
    assert s[0]["kind"] == "shell"
    assert rep["shells"] == 1 and rep["solids"] == 0
    assert "open edges" in rep["parts"][0]["shells"][0]["problems"]


def test_nonplanar_quad_is_triangulated():
    # raise one top corner: the top quad warps, the two side walls stay planar
    fs = [Face([(x, y, 1.2) if (x, y, z) == (1, 1, 1) else (x, y, z)
                for x, y, z in f.outer]) for f in box_faces(0, 0, 0, 1, 1, 1)]
    text, rep, s = roundtrip([Part("Gauche", fs)], scale=1.0, unit="m")
    assert any("non-planar" in n for n in rep["notes"])
    assert s[0]["faces"] == 7 and s[0]["kind"] == "solid"


def test_duplicate_vertices_weld():
    fs = box_faces(0, 0, 0, 1, 1, 1)
    # nudge points below the weld tolerance: must still close
    fs = [Face([(x + 1e-9, y, z) for x, y, z in f.outer]) if i == 2 else f
          for i, f in enumerate(fs)]
    _, rep, s = roundtrip([Part("Soude", fs)], scale=1.0, unit="m")
    assert s[0]["kind"] == "solid"


def test_file_structure():
    text, _ = write_step([Part("C", box_faces(0, 0, 0, 1, 1, 1))])
    assert text.startswith("ISO-10303-21;") and text.rstrip().endswith("END-ISO-10303-21;")
    ents = parse(text)
    # every reference resolves
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


def test_repair_drops_stacked_duplicate_face():
    fs = box_faces(0, 0, 0, 1, 1, 1)
    fs.append(Face(list(fs[0].outer)))          # same face twice
    _, rep, s = roundtrip([Part("Double", fs)], scale=1.0, unit="m")
    assert s[0]["kind"] == "shell"              # non-manifold without repair
    _, rep, s = roundtrip([Part("Double", fs)], scale=1.0, unit="m", repair_tol=1e-6)
    assert s[0]["kind"] == "solid" and abs(s[0]["volume"] - 1.0) < 1e-9
    assert any("duplicate" in n for n in rep["notes"])


def test_repair_caps_a_missing_planar_face():
    fs = box_faces(0, 0, 0, 1, 2, 3)[1:]          # bottom missing
    _, rep, s = roundtrip([Part("Sans fond", fs)], scale=1.0, unit="m", repair_tol=1e-6)
    assert s[0]["kind"] == "solid" and abs(s[0]["volume"] - 6.0) < 1e-9
    assert any("capped" in n for n in rep["notes"])


def test_repair_leaves_a_lone_face_open():
    # issue #3: one open face (and a flat sheet of two) used to crash
    # with repair_tol, or would have been glued back to back into a fake
    # zero-volume solid; it must stay an open shell, as without repair
    sq = lambda x0: Face([(x0, 0, 0), (x0 + .01, 0, 0), (x0 + .01, .01, 0), (x0, .01, 0)])
    for faces in ([sq(0)], [sq(0), sq(.01)]):
        for rt in (None, 1e-5):
            _, rep = write_step([Part("Sheet", faces)], repair_tol=rt)
            sh = rep["parts"][0]["shells"]
            assert len(sh) == 1 and not sh[0]["closed"], (len(faces), rt, sh)
            assert sh[0]["faces"] == len(faces)


def test_parts_touching_on_an_edge_are_separate_solids():
    # two boxes of one group sharing only an edge (a DXF layer of loose
    # faces): two closed solids, two components, not one non-manifold lump
    a = box_faces(0, 0, 0, 1, 1, 1)
    b = box_faces(1, 1, 0, 2, 2, 1)             # touches a along x=1, y=1
    text, rep, s = roundtrip([Part("Lot", a + b)], scale=1.0, unit="m", repair_tol=1e-6)
    assert [x["kind"] for x in s] == ["solid", "solid"]
    assert all(abs(x["volume"] - 1.0) < 1e-9 for x in s)
    import re
    names = re.findall(r"=PRODUCT\('([^']*)'", text)
    assert "Lot (1)" in names and "Lot (2)" in names


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)

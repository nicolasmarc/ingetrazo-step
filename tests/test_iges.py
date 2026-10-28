"""IGES export, read back by OpenCascade (FreeCAD's kernel) as a neutral
reader: solids valid, volumes equal to the closed-form ones, cylinders and
ellipses kept, names and colours carried."""
import math, os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from stepexport.model import Face, Part
from stepexport.iges import write_iges, _wrap
from test_cylinders import circle, slanted, extrude
from test_step import box_faces
import occt_check

needs_occt = pytest.mark.skipif(not occt_check.available(),
                                reason="OpenCascade (cadquery-ocp) missing")


def entity_count(text, etype):
    """Entities of ``etype`` (directory entries come in pairs)."""
    d = [l for l in text.splitlines() if l[72] == "D"]
    return sum(1 for l in d[::2] if int(l[:8]) == etype)


def close(a, b, rel=1e-6):
    return abs(a - b) <= rel * abs(b)


def test_fixed_columns_and_sections():
    text, rep = write_iges([Part("Cube", box_faces(0, 0, 0, .1, .1, .1))])
    lines = text.splitlines()
    assert all(len(l) == 80 for l in lines)
    kinds = [l[72] for l in lines]
    assert kinds == sorted(kinds, key="SGDPT".index)
    assert lines[-1][72] == "T"
    # every parameter line points back at its directory entry, and every
    # directory entry at its first parameter line
    d = [l for l in lines if l[72] == "D"]
    p = [l for l in lines if l[72] == "P"]
    for i in range(0, len(d), 2):
        de, first, count = i + 1, int(d[i][8:16]), int(d[i + 1][24:32])
        assert all(int(p[first - 1 + k][64:72]) == de for k in range(count))
    assert rep["solids"] == 1 and rep["faces"] == 6


def test_wrap_never_cuts_a_token():
    toks = ["123456789012"] * 20 + ["5HHello"]
    lines = _wrap(toks, 64)
    assert all(len(l) <= 64 for l in lines)
    assert "".join(lines).rstrip(";").split(",") == toks


@needs_occt
def test_cube_solid_mm_and_m():
    cube = Part("Cube", box_faces(0, 0, 0, .1, .1, .1))
    s = occt_check.read_iges(write_iges([cube])[0])
    assert s["solids"] == 1 and s["faces"] == 6 and s["valid"]
    assert close(s["volume"], 1e6)
    # OCCT converts to mm on reading: a file in metres gives the same mm3
    s = occt_check.read_iges(write_iges([cube], scale=1.0, unit="m")[0])
    assert s["solids"] == 1 and close(s["volume"], 1e6)


@needs_occt
def test_panel_with_hole_and_concave_profile():
    outer = [(0, 0), (.2, 0), (.2, .1), (.1, .1), (.1, .2), (0, .2)]
    hole = [(.03, .03), (.07, .03), (.07, .07), (.03, .07)]
    f, _ = extrude(outer, [hole], z1=.02, soft=False)
    s = occt_check.read_iges(write_iges([Part("L", f)])[0])
    exact = (0.2 * 0.1 + 0.1 * 0.1 - 0.04 * 0.04) * 0.02 * 1e9
    assert s["solids"] == 1 and s["valid"] and close(s["volume"], exact)


@needs_occt
def test_rod_cylinder_and_tube_with_ellipses():
    f, soft = slanted(circle(0, 0, .03, 32), [circle(0, 0, .025, 32)],
                      k=(0.6, 0.2), kb=(-0.4, 0.0), z1=.2)
    text, rep = write_iges([Part("Tube biais", f, soft_edges=soft)],
                           cylinders=True, snap=None)
    assert rep["cylinders"] == 2
    assert entity_count(text, 192) == 2 and entity_count(text, 190) == 2
    assert entity_count(text, 104) == 8          # 4 ellipses, cut in halves
    s = occt_check.read_iges(text)
    exact = math.pi * (30 ** 2 - 25 ** 2) * 200
    assert s["solids"] == 1 and s["valid"] and s["faces"] == 4
    assert close(s["volume"], exact, 1e-5), s["volume"]


@needs_occt
def test_mitred_rounded_tube_corner():
    W, H, ro, t, n = .1, .06, .01, .003, 8

    def rrect(w, h, rr, off):
        pts = []
        for cx, cy, a0 in [(w - rr, rr, -math.pi / 2), (w - rr, h - rr, 0),
                           (rr, h - rr, math.pi / 2), (rr, rr, math.pi)]:
            pts += circle(cx + off, cy + off, rr, n, a0, a0 + math.pi / 2,
                          closed=False)
        return pts
    f, soft = slanted(rrect(W, H, ro, 0.0),
                      [rrect(W - 2 * t, H - 2 * t, ro - t, t)],
                      k=(1.0, 0.0), z1=.15)
    text, rep = write_iges([Part("Onglet", f, soft_edges=soft)],
                           cylinders=True, snap=None)
    s = occt_check.read_iges(text)
    area = (W * H - (4 - math.pi) * ro ** 2) - \
        ((W - 2 * t) * (H - 2 * t) - (4 - math.pi) * (ro - t) ** 2)
    exact = area * (.15 + W / 2) * 1e9
    assert rep["cylinders"] == 8
    assert s["solids"] == 1 and s["valid"]
    assert close(s["volume"], exact, 1e-5), (s["volume"], exact)


@needs_occt
def test_full_rod_with_seam():
    f, soft = extrude(circle(0, 0, .02, 24), z1=.1)
    text, rep = write_iges([Part("Rond", f, soft_edges=soft)],
                           cylinders=True, snap=None)
    s = occt_check.read_iges(text)
    assert rep["cylinders"] == 1 and s["solids"] == 1 and s["valid"]
    assert close(s["volume"], math.pi * 20 ** 2 * 100, 1e-6)


@needs_occt
def test_surfaces_mode_sews_back_into_the_same_solids():
    f, soft = slanted(circle(0, 0, .03, 32), [circle(0, 0, .025, 32)],
                      k=(0.6, 0.2), z1=.2)
    parts = [Part("Tube", f, soft_edges=soft),
             Part("Box", box_faces(.1, 0, 0, .2, .05, .03))]
    text, rep = write_iges(parts, mode="surfaces", cylinders=True, snap=None)
    assert entity_count(text, 186) == 0 and rep["surfaces"] == rep["faces"]
    assert entity_count(text, 144) == rep["faces"]
    plain = occt_check.read_iges(text)
    assert plain["solids"] == 0 and plain["faces"] == rep["faces"]
    s = occt_check.read_iges(text, sew=True)
    exact = math.pi * (30 ** 2 - 25 ** 2) * 200 + 100 * 50 * 30
    assert s["solids"] == 2 and close(s["volume"], exact, 1e-5), s


@needs_occt
def test_open_part_goes_out_as_surfaces_in_solid_mode():
    sheet = Part("Tole", [Face([(0, 0, 0), (.1, 0, 0), (.1, .1, 0),
                                (0, .1, 0)])])
    cube = Part("Cube", box_faces(.2, 0, 0, .3, .1, .1))
    text, rep = write_iges([sheet, cube])
    assert rep["solids"] == 1 and rep["surfaces"] == 1
    s = occt_check.read_iges(text)
    assert s["solids"] == 1 and s["faces"] == 7


@needs_occt
def test_names_and_colours():
    parts = [Part("Montant gauche", box_faces(0, 0, 0, .1, .1, .1),
                  (1.0, 0.0, 0.0)),
             Part("Traverse", box_faces(.2, 0, 0, .3, .1, .1),
                  (0.0, 0.5, 1.0))]
    got = occt_check.iges_names_colors(write_iges(parts)[0])
    assert sorted(got) == [("Montant gauche", (1.0, 0.0, 0.0)),
                           ("Traverse", (0.0, 0.5, 1.0))]

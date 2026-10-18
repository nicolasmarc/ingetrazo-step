"""STEP reader, against files written by an independent CAD kernel.

tests/data/*.step and facts.json come from tools/make_step_fixtures.py
(CadQuery / OpenCascade): volumes, bounding boxes and placements there are
the kernel's, not ours.
"""
import json, math, os, sys
from collections import Counter
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from stepexport import stepread

DATA = os.path.join(os.path.dirname(__file__), "data")
FACTS = json.load(open(os.path.join(DATA, "facts.json")))
FINE = dict(tol=0.00002, max_angle=math.radians(4))


def _read(name, **kw):
    return stepread.read(os.path.join(DATA, name + ".step"), **kw)


def _open_edges(T):
    P = np.round(T.reshape(-1, 3) * 1e9).astype(np.int64)
    keys = {}
    ids = np.array([keys.setdefault(tuple(q), len(keys)) for q in P]).reshape(-1, 3)
    ec = Counter()
    for a, b, c in ids:
        if len({a, b, c}) < 3:
            continue
        for e in ((a, b), (b, c), (c, a)):
            ec[tuple(sorted(e))] += 1
    return sum(1 for v in ec.values() if v != 2)


def _centroid(T):
    v = np.einsum("ij,ij->i", T[:, 0], np.cross(T[:, 1], T[:, 2])) / 6
    return (v[:, None] * T.sum(axis=1) / 4).sum(0) / v.sum()


def test_parse_complex_strings_comments():
    txt = """ISO-10303-21; HEADER; ENDSEC; DATA;
    /* a comment; with a semicolon */
    #1 = PRODUCT('it''s','name;x','',(#2));
    #2 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );
    #3 = MEASURE_REPRESENTATION_ITEM('',LENGTH_MEASURE(1.5E-02),#2);
    ENDSEC; END-ISO-10303-21;"""
    e = stepread.parse(txt)
    assert e[1]["PRODUCT"][0] == "it's" and e[1]["PRODUCT"][1] == "name;x"
    assert set(e[2]) == {"LENGTH_UNIT", "NAMED_UNIT", "SI_UNIT"}
    assert e[2]["SI_UNIT"] == ["MILLI", "METRE"]
    assert e[3]["MEASURE_REPRESENTATION_ITEM"][1] == ("LENGTH_MEASURE", [0.015])


def test_block_is_exact():
    asm = _read("bloc")
    assert asm.unit == 1e-3 and len(asm.parts) == 1
    T = asm.parts[0].triangles
    assert len(T) == 12
    assert abs(stepread.volume(T) * 1e9 - FACTS["bloc"]["volume"]) < 1e-6
    lo, hi = T.reshape(-1, 3).min(0) * 1e3, T.reshape(-1, 3).max(0) * 1e3
    assert np.allclose(lo, FACTS["bloc"]["bbox"][0]) and np.allclose(hi, FACTS["bloc"]["bbox"][1])


def test_volumes_planes_cylinders_cones_spheres_tori_bsplines():
    for name in ("platine", "pignon", "galet", "raccord"):
        T = _read(name, **FINE).parts[0].triangles
        v, ref = stepread.volume(T) * 1e9, FACTS[name]["volume"]
        assert abs(v - ref) / ref < 0.003, (name, v, ref)


def test_closed_parts_are_watertight():
    for name in ("bloc", "platine", "pignon", "galet"):
        T = _read(name).parts[0].triangles
        assert _open_edges(T) == 0, name


def test_bounding_box_of_a_plate_with_boss():
    T = _read("platine").parts[0].triangles * 1e3
    lo, hi = T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0)
    ref = np.array(FACTS["platine"]["bbox"])
    assert np.abs(lo - ref[0]).max() < 0.25 and np.abs(hi - ref[1]).max() < 0.25


def test_finer_tolerance_converges():
    ref = FACTS["galet"]["volume"]
    errs = [abs(stepread.volume(_read("galet", tol=t).parts[0].triangles) * 1e9 - ref) / ref
            for t in (0.0004, 0.0001, 0.00002)]
    assert errs[0] > errs[1] > errs[2]


def test_assembly_tree_placements_colours():
    asm = _read("assemblage", **FINE)
    by = {p.path[-1]: p for p in asm.parts}
    assert set(by) == {"socle", "levier_g", "levier_d"}
    assert all(p.path[0] == "mecanisme" for p in asm.parts)
    assert np.allclose(by["socle"].color, (0.6, 0.6, 0.6), atol=1e-6)
    c_local = np.array(FACTS["assemblage"]["lever_center_local"])
    for name in ("levier_g", "levier_d"):
        f = FACTS["assemblage"]["parts"][name]
        a = math.radians(f["angle"])
        R = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
        expect = R @ c_local + np.array(f["center"])
        got = _centroid(by[name].triangles * 1e3)
        assert np.linalg.norm(got - expect) < 0.02, (name, got, expect)
        v = stepread.volume(by[name].triangles) * 1e9
        assert abs(v - f["volume"]) / f["volume"] < 0.003


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)

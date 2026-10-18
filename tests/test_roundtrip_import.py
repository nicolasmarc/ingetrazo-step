"""Export then import: what stepexport writes, stepread reads back —
names, units, colours and volumes against closed forms (the full reader
meshes the cylinders on its own, to a chord tolerance)."""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from stepexport.model import Part
from stepexport.writer import write_step
from stepexport import stepread
from test_step import box_faces
from test_cylinders import extrude, circle

FINE = dict(tol=0.000005, max_angle=math.radians(3))


def _back(parts, **kw):
    kw.setdefault("cylinders", True)
    text, rep = write_step(parts, **kw)
    return stepread.read(text, **FINE), rep


def test_cube_names_units_colour():
    p = Part("Cube rouge", box_faces(0, 0, 0, .1, .1, .1), color=(0.8, 0.1, 0.1))
    asm, rep = _back([p], cylinders=False)
    assert asm.unit == 1e-3 and [q.name for q in asm.parts] == ["Cube rouge"]
    T = asm.parts[0].triangles
    assert abs(stepread.volume(T) - 1e-3) < 1e-12           # 0.1 m cube, back in metres
    assert np.allclose(T.reshape(-1, 3).min(0), 0) and np.allclose(T.reshape(-1, 3).max(0), .1)
    assert asm.parts[0].color is not None and abs(asm.parts[0].color[0] - 0.8) < 1e-6


def test_written_cylinders_read_as_cylinders():
    rod, s1 = extrude(circle(0, 0, .02, 24), z1=.1)
    tube, s2 = extrude(circle(0, 0, .03, 32), [circle(0, 0, .025, 32)], z1=.2)
    asm, rep = _back([Part("Tige", rod, soft_edges=s1), Part("Tube", tube, soft_edges=s2)])
    by = {p.name: p for p in asm.parts}
    exact = {"Tige": math.pi * .02 ** 2 * .1, "Tube": math.pi * (.03 ** 2 - .025 ** 2) * .2}
    for name, v in exact.items():
        got = stepread.volume(by[name].triangles)
        assert abs(got - v) / v < 0.002, (name, got, v)
        kinds = {f.kind for f in by[name].faces}
        assert "cylindre" in kinds and "plane" in kinds, kinds


def test_panel_with_hole_in_cm():
    X, Y, T, R = .6, .4, .018, .0175
    f, soft = extrude([(0, 0), (X, 0), (X, Y), (0, Y)], [circle(.3, .2, R, 32)], z1=T)
    asm, rep = _back([Part("Panneau", f, soft_edges=soft)], scale=100.0, unit="cm")
    assert asm.unit == 1e-2
    v = stepread.volume(asm.parts[0].triangles)
    exact = (X * Y - math.pi * R ** 2) * T
    assert abs(v - exact) / exact < 0.001, (v, exact)


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)

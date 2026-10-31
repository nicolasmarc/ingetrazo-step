"""Export units: the document's units decide the file's (issue raised by
Nicolas, 2026-11-01). Inches and feet are written as ISO 10303-41
conversion-based units in STEP and as unit flags 1 / 4 in IGES; both read
back to the same metres, by our reader and by OpenCascade."""
import math, os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from stepexport.model import Part
from stepexport.writer import UNIT_SCALE, unit_for_document, write_step
from stepexport.iges import write_iges
from stepexport.collect import format_report
from stepexport import stepread
from test_step import box_faces
from test_cylinders import extrude, circle
import occt_check

needs_occt = pytest.mark.skipif(not occt_check.available(),
                                reason="OpenCascade (cadquery-ocp) missing")
FINE = dict(tol=0.000005, max_angle=math.radians(3))


@pytest.mark.parametrize("doc, want", [
    ("mm", "mm"), ("cm", "cm"), ("m", "m"), ("ft", "ft"), ("in", "in"),
    ("in-frac", "in"), ("ft-in", "in"), ("ft-in-frac", "in"), ("??", "mm")])
def test_document_unit_to_export_unit(doc, want):
    assert unit_for_document(doc) == want


@pytest.mark.parametrize("unit, metres", [("in", 0.0254), ("ft", 0.3048),
                                          ("mm", 1e-3), ("cm", 1e-2), ("m", 1.0)])
def test_step_reads_back_in_metres(unit, metres):
    # a 1 ft x 6 in x 1 in board with a 1/2" hole: lengths exact in inches
    X, Y, Z, R = .3048, .1524, .0254, .00635
    f, soft = extrude([(0, 0), (X, 0), (X, Y), (0, Y)],
                      [circle(X / 2, Y / 2, R, 48)], z1=Z)
    text, rep = write_step([Part("Planche", f, soft_edges=soft)],
                           scale=UNIT_SCALE[unit], unit=unit)
    if unit in ("in", "ft"):
        assert ("CONVERSION_BASED_UNIT('INCH'" if unit == "in"
                else "CONVERSION_BASED_UNIT('FOOT'") in text
    asm = stepread.read(text, **FINE)
    assert abs(asm.unit - metres) < 1e-12
    T = asm.parts[0].triangles.reshape(-1, 3)
    assert abs(T.max(0)[0] - X) < 1e-9 and abs(T.max(0)[1] - Y) < 1e-9
    exact = X * Y * Z - math.pi * R * R * Z
    got = stepread.volume(asm.parts[0].triangles)
    assert abs(got - exact) / exact < 0.002


def test_report_volume_in_cm3():
    cube = Part("Cube", box_faces(0, 0, 0, .0254, .0254, .0254))    # 1 in cube
    _, rep = write_step([cube], scale=UNIT_SCALE["in"], unit="in", cylinders=False)
    txt = format_report(rep, "in", "en")
    assert "16.39" in txt, txt                                   # 1 in3 = 16.387 cm3


@pytest.mark.parametrize("unit, flag", [("in", "1,4HINCH"), ("ft", "4,2HFT")])
def test_iges_unit_flag(unit, flag):
    text, _ = write_iges([Part("Cube", box_faces(0, 0, 0, .3048, .3048, .3048))],
                         scale=UNIT_SCALE[unit], unit=unit)
    glob = "".join(l[:72] for l in text.splitlines() if l[72] == "G")
    assert flag in glob, glob


def _occt_volume(text, suffix):
    """Volume in mm3 as OpenCascade reads the file (it answers in mm)."""
    import tempfile
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IGESControl import IGESControl_Reader
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    try:
        r = STEPControl_Reader() if suffix == ".stp" else IGESControl_Reader()
        r.ReadFile(path)
        r.TransferRoots()
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(r.OneShape(), props)
        return abs(props.Mass())
    finally:
        os.remove(path)


@needs_occt
@pytest.mark.parametrize("unit", ["in", "ft"])
@pytest.mark.parametrize("writer, suffix", [(write_step, ".stp"), (write_iges, ".igs")])
def test_occt_reads_imperial_files(unit, writer, suffix):
    cube = Part("Cube", box_faces(0, 0, 0, .3048, .1524, .0254))
    text, _ = writer([cube], scale=UNIT_SCALE[unit], unit=unit)
    want = 304.8 * 152.4 * 25.4
    got = _occt_volume(text, suffix)
    assert abs(got - want) < 1e-6 * want, (got, want)

"""Part names survive the trip: every exported part is its own named
product (what CAD programs show as the component), accents included, and
the reader prefers the name the designer typed ('Marche') over the one a
CAD program gives a solid on its own ('Solide', 'Body1').

The export side is also checked with an independent kernel (OpenCascade,
through CadQuery) when it is installed — a test-data tool only."""
import os, re, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from stepexport.model import Part
from stepexport.writer import write_step
from stepexport import stepread
from test_step import box_faces


def _stair():
    return [Part("Marche 1", box_faces(0, 0, 0, 1, .3, .04), color=(0.8, 0.5, 0.2)),
            Part("Limon gauche", box_faces(-.05, 0, -.5, 0, .3, .5)),
            Part("Pièce d'appui", box_faces(1, 0, -.5, 1.05, .3, .5))]


def test_every_part_is_a_named_product():
    text, _ = write_step(_stair(), filename="Escalier droit.stp")
    names = re.findall(r"=PRODUCT\('([^']*(?:''[^']*)*)'", text)
    assert names == ["Escalier droit", "Marche 1", "Limon gauche", "Pi\\X2\\00E8\\X0\\ce d''appui"]
    assert text.count("NEXT_ASSEMBLY_USAGE_OCCURRENCE") == 3 and text.isascii()


def test_names_and_places_come_back():
    parts = _stair()
    asm = stepread.read(write_step(parts, filename="Escalier droit.stp")[0])
    assert [p.name for p in asm.parts] == ["Marche 1", "Limon gauche", "Pièce d'appui"]
    assert asm.parts[0].path == ("Escalier droit", "Marche 1")
    assert asm.parts[0].color is not None
    for p, q in zip(parts, asm.parts):        # placements: same boxes, in metres
        lo = np.min([v for f in p.faces for v in f.outer], axis=0)
        T = q.triangles.reshape(-1, 3)
        assert np.allclose(T.min(0), lo, atol=1e-9)


def test_single_part_is_one_named_product():
    text, _ = write_step([Part("Marche", box_faces(0, 0, 0, 1, .3, .04))])
    assert "NEXT_ASSEMBLY_USAGE_OCCURRENCE" not in text
    assert re.findall(r"=PRODUCT\('([^']*)'", text) == ["Marche"]
    assert [p.name for p in stepread.read(text).parts] == ["Marche"]


def _rename_solids(text, new):
    return re.sub(r"MANIFOLD_SOLID_BREP\('[^']*'", f"MANIFOLD_SOLID_BREP('{new}'", text)


def test_component_name_beats_generic_solid_name():
    # what other CAD programs write: the component 'Marche' holds a body
    # they called 'Solide' / 'Body1'
    for generic in ("Solide", "Solid1", "Body 2", "Corps(3)", ""):
        text = _rename_solids(write_step(_stair(), filename="Escalier.stp")[0], generic)
        assert [p.name for p in stepread.read(text).parts] == \
            ["Marche 1", "Limon gauche", "Pièce d'appui"], generic
        one = _rename_solids(write_step([Part("Marche", box_faces(0, 0, 0, 1, .3, .04))])[0], generic)
        assert [p.name for p in stepread.read(one).parts] == ["Marche"], generic


def test_files_from_stepexport_0_3_still_read_by_solid_name():
    # 0.3 wrote one product 'model' holding every solid, named after its part
    text = write_step(_stair())[0]
    old = re.sub(r"PRODUCT\('Marche 1','Marche 1'", "PRODUCT('model','model'", text)
    one = write_step([Part("Marche", box_faces(0, 0, 0, 1, .3, .04))])[0]
    one = one.replace("PRODUCT('Marche','Marche'", "PRODUCT('model','model'")
    assert [p.name for p in stepread.read(one).parts] == ["Marche"]
    assert stepread.read(old).parts[0].name == "Marche 1"


def test_step_string_escapes():
    d = stepread._text
    assert d("Pi\\X2\\00E8\\X0\\ce") == "Pièce"
    assert d("caf\\X\\E9") == "café"
    assert d("\\X2\\00C9\\X0\\tag\\X2\\00E8\\X0\\re") == "Étagère"
    assert d("a\\\\b") == "a\\b" and d("plain") == "plain"


def test_independent_kernel_sees_the_names():
    try:
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TDocStd import TDocStd_Document
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.XCAFDoc import XCAFDoc_DocumentTool
        from OCP.TDF import TDF_LabelSequence, TDF_Label
        from OCP.TDataStd import TDataStd_Name
    except ImportError:                       # pragma: no cover
        print("  (OpenCascade not installed: skipped)")
        return
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "escalier.stp")
    write_step(_stair(), path=path, filename="Escalier droit.stp")
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    r = STEPCAFControl_Reader()
    r.SetNameMode(True)
    r.ReadFile(path)
    r.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    def name(lab):
        a = TDataStd_Name()
        return a.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else None
    roots = TDF_LabelSequence()
    st.GetFreeShapes(roots)
    assert roots.Length() == 1 and name(roots.Value(1)) == "Escalier droit"
    kids = TDF_LabelSequence()
    st.GetComponents_s(roots.Value(1), kids)
    got = []
    for i in range(1, kids.Length() + 1):
        ref = TDF_Label()
        st.GetReferredShape_s(kids.Value(i), ref)
        got.append(name(ref))
    assert got == ["Marche 1", "Limon gauche", "Pièce d'appui"], got


if __name__ == "__main__":
    for k, fn in list(globals().items()):
        if k.startswith("test_"):
            fn(); print("ok", k)

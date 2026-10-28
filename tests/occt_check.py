"""OpenCascade (the kernel FreeCAD uses) as a neutral IGES reader for the
tests: ``pip install cadquery-ocp``. Tests skip when it is missing."""
import os
import tempfile


def available():
    try:
        import OCP  # noqa: F401
        return True
    except ImportError:
        return False


def read_iges(text, sew=False):
    """-> dict(solids, shells, faces, volume (mm3 when the file is in mm),
    valid, names, colors) as OCCT reads the file."""
    from OCP.IGESControl import IGESControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL
    from OCP.TopoDS import TopoDS
    fd, path = tempfile.mkstemp(suffix=".igs")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    try:
        r = IGESControl_Reader()
        assert r.ReadFile(path) == IFSelect_RetDone
        r.TransferRoots()
        shape = r.OneShape()
    finally:
        os.remove(path)
    if sew:
        from OCP.BRepBuilderAPI import (BRepBuilderAPI_Sewing,
                                        BRepBuilderAPI_MakeSolid)
        s = BRepBuilderAPI_Sewing(1e-3)
        s.Add(shape)
        s.Perform()
        sewn = s.SewedShape()
        solids = []
        ex = TopExp_Explorer(sewn, TopAbs_SHELL)
        from OCP.TopoDS import TopoDS_Compound
        from OCP.BRep import BRep_Builder
        from OCP.ShapeFix import ShapeFix_Solid
        b = BRep_Builder()
        comp = TopoDS_Compound()
        b.MakeCompound(comp)
        while ex.More():
            sh = TopoDS.Shell(ex.Current())
            fix = ShapeFix_Solid()
            solid = fix.SolidFromShell(sh)
            b.Add(comp, solid)
            ex.Next()
        shape = comp

    def count(kind):
        ex, n = TopExp_Explorer(shape, kind), 0
        while ex.More():
            n += 1
            ex.Next()
        return n
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return {"solids": count(TopAbs_SOLID), "shells": count(TopAbs_SHELL),
            "faces": count(TopAbs_FACE), "volume": abs(props.Mass()),
            "valid": BRepCheck_Analyzer(shape).IsValid()}


def iges_names_colors(text):
    """Names and colours through OCCT's document reader (XCAF)."""
    from OCP.IGESCAFControl import IGESCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    from OCP.TDataStd import TDataStd_Name
    from OCP.Quantity import Quantity_Color
    from OCP.XCAFDoc import XCAFDoc_ColorType
    fd, path = tempfile.mkstemp(suffix=".igs")
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    try:
        doc = TDocStd_Document(TCollection_ExtendedString("doc"))
        r = IGESCAFControl_Reader()
        r.SetColorMode(True)
        r.SetNameMode(True)
        r.ReadFile(path)
        r.Transfer(doc)
    finally:
        os.remove(path)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    ct = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    labels = TDF_LabelSequence()
    st.GetFreeShapes(labels)
    out = []
    for i in range(1, labels.Length() + 1):
        lab = labels.Value(i)
        nm = TDataStd_Name()
        name = (nm.Get().ToExtString() if lab.FindAttribute(
            TDataStd_Name.GetID_s(), nm) else None)
        c = Quantity_Color()
        rgb = None
        shape = st.GetShape_s(lab)
        for ctype in (XCAFDoc_ColorType.XCAFDoc_ColorGen,
                      XCAFDoc_ColorType.XCAFDoc_ColorSurf):
            if ct.GetColor(shape, ctype, c):
                from OCP.Quantity import Quantity_TypeOfColor
                # OCCT keeps colours linear; the file holds sRGB
                rgb = tuple(round(v, 3) for v in c.Values(
                    Quantity_TypeOfColor.Quantity_TOC_sRGB))
                break
        out.append((name, rgb))
    return out

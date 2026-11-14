"""Import inside a real IngeTrazo window (offscreen): the menu's panel and
a .stp opened like any document. Needs PySide6 and an IngeTrazo checkout
(INGETRAZO_SRC, or ../ingetrazo-upstream, ../ingetrazo); skipped otherwise."""
import os, shutil, sys, tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def _src():
    for c in (os.environ.get("INGETRAZO_SRC"), REPO.parent / "ingetrazo-upstream",
              REPO.parent / "ingetrazo"):
        if c and (Path(c) / "views" / "extension_api.py").is_file():
            return Path(c)
    return None


SRC = _src()
try:
    import PySide6  # noqa: F401
    SKIP = None if SRC else "no IngeTrazo checkout"
except ImportError:
    SKIP = "no PySide6"
_s = {}


def _window():
    if "win" in _s:
        return _s["win"]
    sys.path.insert(0, str(SRC))
    os.chdir(SRC)
    plugins = Path(tempfile.mkdtemp()) / "plugins"
    plugins.mkdir()
    # a private data folder: an interrupted run must not leave an autosave
    # that makes the next window ask «Recover it?» and wait for an answer
    os.environ["XDG_DATA_HOME"] = str(plugins.parent / "data")
    shutil.copytree(REPO / "stepexport", plugins / "stepexport",
                    ignore=shutil.ignore_patterns("__pycache__"))
    from PySide6.QtWidgets import QApplication
    _s["qapp"] = QApplication.instance() or QApplication([])
    from core import extensions
    extensions.plugin_dirs = lambda: [plugins]
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    for _ in range(20):
        _s["qapp"].processEvents()
    dock = next(d for d in win._extension_docks if d.objectName() == "extension_stepexport")
    panel = dock.widget()
    if hasattr(panel, "setWidgetResizable"):     # 0.5.9+: a scroll area on short screens
        panel = panel.widget()
    _s.update(win=win, panel=panel)
    return win


def test_import_from_the_panel_one_undo_step():
    if SKIP:
        print("skip:", SKIP); return
    win = _window()
    scene = win.viewport.scene
    n0 = len(scene.groups)
    assert _s["panel"].import_file(str(HERE / "data" / "assemblage.step"))
    names = sorted(g.name for g in scene.groups[n0:])
    assert names == ["levier_d", "levier_g", "socle"]
    assert set(scene.selection) == set(scene.groups[n0:])
    assert "3" in _s["panel"].out.toPlainText()
    win._on_undo()
    assert len(scene.groups) == n0


def test_a_stp_opens_like_a_document():
    if SKIP:
        print("skip:", SKIP); return
    win = _window()
    assert ".stp" in win.file_openers and ".step" in win.file_openers
    scene = win.viewport.scene
    n0 = len(scene.groups)
    f = Path(tempfile.mkdtemp()) / "galet.stp"
    shutil.copy(HERE / "data" / "galet.step", f)
    win.open_path(f)
    assert len(scene.groups) == n0 + 1


def test_dxf_conversion_shows_its_result():
    if SKIP:
        print("skip:", SKIP); return
    try:
        import ezdxf
    except ImportError:
        print("skip: no ezdxf"); return
    win = _window()
    scene = win.viewport.scene
    n0 = len(scene.groups)
    doc = ezdxf.new("R2010"); doc.header["$INSUNITS"] = 4
    for k, name in enumerate(("Marche1", "Marche2")):
        b = doc.blocks.new(name)
        pf = b.add_polyface()
        p = [(0, 0, 0), (900, 0, 0), (900, 250, 0), (0, 250, 0),
             (0, 0, 40), (900, 0, 40), (900, 250, 40), (0, 250, 40)]
        pf.append_faces([[p[i] for i in f] for f in
                         [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                          (2, 3, 7, 6), (3, 0, 4, 7)]])
        doc.modelspace().add_blockref(name, (0, 250 * k, 200 * k))
    d = Path(tempfile.mkdtemp())
    doc.saveas(d / "esc.dxf")
    panel = _s["panel"]
    panel.dxf_show.setChecked(True)
    panel.fmt.setCurrentIndex(1)            # IGES chosen: a .stp is still STEP
    panel.convert_dxf(str(d / "esc.dxf"), str(d / "esc.stp"))
    assert (d / "esc.stp").read_text().startswith("ISO-10303-21;")
    assert (d / "esc.stp").is_file()
    assert sorted(g.name for g in scene.groups[n0:]) == ["Marche1", "Marche2"]
    win._on_undo()
    assert len(scene.groups) == n0


def test_iges_from_the_panel():
    if SKIP:
        print("skip:", SKIP); return
    win = _window()
    from PySide6.QtGui import QVector3D
    scene = win.viewport.scene
    n0 = len(scene.groups)
    assert _s["panel"].import_file(str(HERE / "data" / "assemblage.step"))
    panel = _s["panel"]
    panel.what.setCurrentIndex(1)       # the 3 parts just imported (selected)
    d = Path(tempfile.mkdtemp())
    for idx, name in ((1, "solides.igs"), (2, "surfaces.igs")):
        panel.fmt.setCurrentIndex(idx)
        panel.run(str(d / name))
        text = (d / name).read_text()
        assert text.splitlines()[-1][72] == "T"
        types = {int(l[:8]) for l in text.splitlines() if l[72] == "D"}
        assert (186 in types) == (idx == 1)
        assert str(d / name) in panel.out.toPlainText()
    # the choice is remembered, and the dialog asks for an .igs
    panel.fmt.setCurrentIndex(1)
    assert panel._format()[2][0] == ".igs"
    panel.fmt.setCurrentIndex(0)
    assert panel._format()[2][0] == ".stp"
    win._on_undo()
    assert len(scene.groups) == n0
    try:
        sys.path.insert(0, str(HERE))
        import occt_check
    except ImportError:
        return
    if occt_check.available():
        s = occt_check.read_iges((d / "solides.igs").read_text())
        assert s["solids"] == 3 and s["valid"]


def test_subd_body_exports_as_nurbs():
    """A SubD group (the Subdivision extension's cage in ``ext``) goes out
    as B-spline faces with the option on, as facets with it off and in
    IGES. The Subdivision extension itself is not needed."""
    if SKIP:
        print("skip:", SKIP); return
    win = _window()
    from core.group import Group
    from core.mesh import Mesh
    from PySide6.QtGui import QVector3D
    panel = _s["panel"]
    scene = win.viewport.scene
    cube = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    quads = [[0, 2, 6, 4], [1, 5, 7, 3], [0, 4, 5, 1], [2, 3, 7, 6], [0, 1, 3, 2], [4, 6, 7, 5]]
    mesh = Mesh()
    for q in quads:
        mesh.add_face([QVector3D(*cube[i]) for i in q])
    g = Group(mesh, name="SubD")
    g.ext = {"subdiv": {"cage": {"verts": [list(p) for p in cube], "faces": quads,
                                 "creases": []}, "levels": 2, "lines": "cage"}}
    scene.groups.append(g)
    scene.version += 1
    scene.selection.clear()
    scene.selection.add(g)
    panel.what.setCurrentIndex(1)
    panel.fmt.setCurrentIndex(0)
    d = Path(tempfile.mkdtemp())
    try:
        panel.nurbs.setChecked(True)
        panel.run(str(d / "nurbs.stp"))
        text = (d / "nurbs.stp").read_text()
        assert text.count("B_SPLINE_SURFACE_WITH_KNOTS") == 6      # one face per cage quad
        panel.nurbs_mode.setCurrentIndex(panel.nurbs_mode.findData("patches"))
        panel.run(str(d / "patches.stp"))
        assert (d / "patches.stp").read_text().count("B_SPLINE_SURFACE_WITH_KNOTS") >= 24
        panel.nurbs_mode.setCurrentIndex(panel.nurbs_mode.findData("panels"))
        assert "NURBS" in panel.out.toPlainText()
        panel.nurbs.setChecked(False)
        panel.run(str(d / "facets.stp"))
        assert "B_SPLINE_SURFACE" not in (d / "facets.stp").read_text()
        panel.nurbs.setChecked(True)
        panel.fmt.setCurrentIndex(1)                 # IGES: facets, not B-splines
        panel.run(str(d / "subd.igs"))
        assert (d / "subd.igs").stat().st_size > 0
    finally:
        panel.fmt.setCurrentIndex(0)
        scene.groups.remove(g)
        scene.selection.clear()
        scene.version += 1


def teardown_module(module=None):
    win = _s.pop("win", None)
    if win is not None:
        win._saved_version = win.viewport.scene.version
        win._is_dirty = lambda: False        # 0.6.2+ asks before closing otherwise
        win.close()


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
    teardown_module()


def test_export_follows_the_document_units():
    """«Document» writes the file in the open document's units: inches
    for a feet-and-inches document, millimetres for a millimetre one."""
    if SKIP:
        print("skip:", SKIP); return
    win = _window()
    panel = _s["panel"]
    from core import units
    from stepexport import stepread
    out = Path(tempfile.mkdtemp())
    win.open_path(SRC / "examples" / "arco-yanque.igz")
    panel.what.setCurrentIndex(0)
    panel.unit.setCurrentIndex(panel.unit.findData("doc"))
    for length, want, metres in (("ft-in", "in", 0.0254), ("mm", "mm", 1e-3),
                                 ("ft", "ft", 0.3048)):
        units.apply_units(win.viewport.scene, {"length": length, "precision": 2})
        path = out / f"doc-{length}.stp"
        panel.run(str(path))
        assert panel.unit.itemText(0).endswith(f"({want})"), panel.unit.itemText(0)
        text = path.read_text()
        if want != "mm":
            assert ("'INCH'" if want == "in" else "'FOOT'") in text
        assert abs(stepread.read(text).unit - metres) < 1e-12, length

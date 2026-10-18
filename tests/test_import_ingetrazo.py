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
    _s.update(win=win, panel=dock.widget())
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


def teardown_module(module=None):
    win = _s.pop("win", None)
    if win is not None:
        win._saved_version = win.viewport.scene.version
        win.close()


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
    teardown_module()

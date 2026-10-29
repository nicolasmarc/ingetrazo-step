"""IngeTrazo panel "STEP export" (needs PySide6 — loaded by ``setup``).

Extensions ▸ "Export to STEP…" opens the panel. "Analyse" shows what the
file would contain (solids, open parts, cylinders found) without writing
anything; "Export…" asks for the file and writes it. English, French or Spanish,
following IngeTrazo's language.
"""
import os

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from . import __version__
from .collect import collect_parts, format_report
from .texts import language, texts
from .writer import write_step
from .iges import write_iges

UNITS = [("mm", 1000.0), ("cm", 100.0), ("m", 1.0)]


def _icon():
    """A small solid with a cylinder, drawn in code (no icon API)."""
    pm = QPixmap(32, 32)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#3a3a3a"), 2))
    p.setBrush(QColor("#e8e2d4"))
    p.drawRect(3, 10, 18, 18)
    p.setBrush(QColor("#f39200"))
    p.drawRect(20, 9, 9, 17)
    p.drawEllipse(20, 5, 9, 6)
    p.drawEllipse(20, 23, 9, 6)
    p.end()
    return QIcon(pm)


class StepPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.settings = QSettings("ingetrazo", "stepexport")
        self.lang = language()
        T = self.T = texts(self.lang)
        lay = QVBoxLayout(self)
        title = QLabel(f"<b>{T['title']}</b> <small>v{__version__}</small>")
        lay.addWidget(title)
        form = QFormLayout()
        self.fmt = QComboBox()
        self.fmt.addItems([T["fmt_step"], T["fmt_iges"], T["fmt_iges_surf"]])
        self.fmt.setToolTip(T["fmt_tip"])
        form.addRow(T["format"], self.fmt)
        self.what = QComboBox()
        self.what.addItems([T["all"], T["selection"]])
        form.addRow(T["content"], self.what)
        self.unit = QComboBox()
        self.unit.addItems([u for u, _ in UNITS])
        form.addRow(T["unit"], self.unit)
        self.cyl = QCheckBox(T["cyl"])
        self.cyl.setToolTip(T["cyl_tip"])
        form.addRow(self.cyl)
        self.cyl_mode = QComboBox()
        self.cyl_mode.addItems([T["soft"], T["geometry"]])
        form.addRow(T["detect"], self.cyl_mode)
        self.simplify = QCheckBox(T["simplify"])
        self.simplify.setToolTip(T["simplify_tip"])
        form.addRow(self.simplify)
        self.simp_tol = QDoubleSpinBox()
        self.simp_tol.setRange(0.01, 1.0)
        self.simp_tol.setSingleStep(0.05)
        self.simp_tol.setDecimals(2)
        self.simp_tol.setSuffix(" mm")
        form.addRow(T["tolerance"], self.simp_tol)
        self.simplify.toggled.connect(self.simp_tol.setEnabled)
        self.colors = QCheckBox(T["colors"])
        form.addRow(self.colors)
        self.author = QLineEdit()
        form.addRow(T["author"], self.author)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.btn_check = QPushButton(T["analyse"])
        self.btn_export = QPushButton(T["export"])
        self.btn_export.setDefault(True)
        self.btn_import = QPushButton(T["import"])
        self.btn_import.setToolTip(T["menu_import_tip"])
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_import)
        lay.addLayout(row)
        self.btn_dxf = QPushButton(T["dxf"])
        self.btn_dxf.setToolTip(T["dxf_tip"])
        lay.addWidget(self.btn_dxf)
        self.dxf_show = QCheckBox(T["dxf_show"])
        self.dxf_show.setToolTip(T["dxf_show_tip"])
        lay.addWidget(self.dxf_show)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setPlaceholderText(T["placeholder"])
        lay.addWidget(self.out, 1)
        self.btn_check.clicked.connect(lambda: self.run(None))
        self.btn_export.clicked.connect(self.export)
        self.btn_import.clicked.connect(self.import_dialog)
        self.btn_dxf.clicked.connect(self.dxf_dialog)
        self.cyl.toggled.connect(self.cyl_mode.setEnabled)
        self._load()

    # ---- options ---------------------------------------------------------
    def _load(self):
        s = self.settings
        self.fmt.setCurrentIndex(int(s.value("format", 0)))
        self.unit.setCurrentText(s.value("unit", "mm"))
        self.cyl.setChecked(s.value("cylinders", "true") == "true")
        self.cyl_mode.setCurrentIndex(int(s.value("cyl_mode", 0)))
        self.colors.setChecked(s.value("colors", "true") == "true")
        self.author.setText(s.value("author", ""))
        self.simplify.setChecked(s.value("simplify", "false") == "true")
        self.simp_tol.setValue(float(s.value("simplify_tol", 0.1)))
        self.simp_tol.setEnabled(self.simplify.isChecked())
        self.dxf_show.setChecked(s.value("dxf_show", "true") == "true")
        self.cyl_mode.setEnabled(self.cyl.isChecked())

    def _save(self):
        s = self.settings
        s.setValue("format", self.fmt.currentIndex())
        s.setValue("unit", self.unit.currentText())
        s.setValue("cylinders", "true" if self.cyl.isChecked() else "false")
        s.setValue("cyl_mode", self.cyl_mode.currentIndex())
        s.setValue("colors", "true" if self.colors.isChecked() else "false")
        s.setValue("author", self.author.text())
        s.setValue("simplify", "true" if self.simplify.isChecked() else "false")
        s.setValue("simplify_tol", self.simp_tol.value())
        s.setValue("dxf_show", "true" if self.dxf_show.isChecked() else "false")

    # ---- actions ---------------------------------------------------------
    def _format(self):
        """-> (writer, extra options, extensions, file filter, dialog title,
        default file name) for the chosen format."""
        T, i = self.T, self.fmt.currentIndex()
        if i == 0:
            return (write_step, {}, (".stp", ".step"), "STEP (*.stp *.step)",
                    T["dialog"], T["default_name"])
        return (write_iges, {"mode": "solid" if i == 1 else "surfaces"},
                (".igs", ".iges"), "IGES (*.igs *.iges)", T["dialog_iges"],
                T["default_iges"])

    def _writer_for(self, path):
        """The writer the file name asks for: an .igs/.iges gets IGES (in
        the chosen IGES form, solids when STEP is chosen), anything else
        STEP; the format list only decides the name the dialog offers."""
        if path and path.lower().endswith((".igs", ".iges")):
            mode = "surfaces" if self.fmt.currentIndex() == 2 else "solid"
            return write_iges, {"mode": mode}
        return write_step, {}

    def _ask_path(self, folder, base=None):
        _w, _o, exts, flt, title, default = self._format()
        name = (os.path.splitext(base)[0] + exts[0]) if base else default
        path, _ = QFileDialog.getSaveFileName(
            self, title, os.path.join(folder, name), flt)
        if path and not path.lower().endswith(exts):
            path += exts[0]
        return path

    def export(self):
        last = self.settings.value("last_dir", os.path.expanduser("~"))
        path = self._ask_path(last)
        if not path:
            return
        self.settings.setValue("last_dir", os.path.dirname(path))
        self.run(path)

    def dxf_dialog(self):
        last = self.settings.value("last_dxf_dir", os.path.expanduser("~"))
        src, _ = QFileDialog.getOpenFileName(self, self.T["dxf_open"], last,
                                             "DXF (*.dxf *.DXF)")
        if not src:
            return
        self.settings.setValue("last_dxf_dir", os.path.dirname(src))
        path = self._ask_path(os.path.dirname(src), os.path.basename(src))
        if not path:
            return
        self.convert_dxf(src, path)

    def convert_dxf(self, src, path):
        """DXF straight to STEP in double precision (see :mod:`dxfdirect`):
        the open model is not touched."""
        import time
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from .dxfdirect import read_parts
        self._save()
        unit = self.unit.currentText()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        t0 = time.time()
        try:
            parts, info = read_parts(src)
            if not self.colors.isChecked():
                for p in parts:
                    p.color = None
            writer, extra = self._writer_for(path)
            _, rep = writer(
                parts, path=path, scale=dict(UNITS)[unit], unit=unit,
                author=self.author.text(), filename=os.path.basename(path),
                cylinders=self.cyl.isChecked(), cyl_mode="soft", **extra,
                repair_tol=1e-5,
                simplify_tol=(self.simp_tol.value() / 1000.0
                              if self.simplify.isChecked() else None),
                snap=None)                # the DXF's own digits, untouched
        except Exception as exc:             # report, never crash the app
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "STEP", f"{self.T['failed']}\n{type(exc).__name__}: {exc}")
            return
        QApplication.restoreOverrideCursor()
        head = self.T["dxf_done"].format(
            f=os.path.basename(src), t=time.time() - t0,
            u=self.T["dxf_units_declared"] if info["declared"] else
            self.T["dxf_units_guessed"].format(u="mm" if info["scale"] == 0.001 else "m"))
        report = f"{self.T['written']} {path}\n{head}\n\n" + format_report(rep, unit, self.lang)
        if self.dxf_show.isChecked() and path.lower().endswith((".stp", ".step")) \
                and self.import_file(path):
            # what was written, read back from the .stp itself: the solids
            # as the CAD program will get them, one group each, selected,
            # one Ctrl+Z to take them away again
            report = self.T["dxf_shown"] + "\n\n" + report
        self.out.setPlainText(report)

    def import_dialog(self):
        last = self.settings.value("last_import_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, self.T["import_dialog"], last,
                                              "STEP (*.stp *.step *.STP *.STEP)")
        if path:
            self.settings.setValue("last_import_dir", os.path.dirname(path))
            self.import_file(path)

    def import_file(self, path):
        """Import ``path`` into the open model; returns True when parts
        came in (also used when IngeTrazo opens a .stp)."""
        import time
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from .stepimport import import_into
        T = self.T
        QApplication.setOverrideCursor(Qt.WaitCursor)
        t0 = time.time()
        try:
            asm, groups = import_into(self.app, path)
        except Exception as exc:              # report, never crash the app
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "STEP", f"{T['import_failed']}\n{type(exc).__name__}: {exc}")
            return False
        QApplication.restoreOverrideCursor()
        if not groups:
            self.out.setPlainText(T["import_none"])
            return False
        sel = getattr(self.app.scene, "selection", None)
        if sel is not None:                   # left selected, ready to use
            sel.clear()
            sel.update(groups)
        text = T["imported"].format(n=len(groups), f=os.path.basename(path), t=time.time() - t0)
        if asm.warnings:
            text += "\n" + T["import_unread"].format(
                w=", ".join(f"{k} ×{n}" for k, n in asm.warnings.items()))
        text += "\n\n" + "\n".join(" / ".join(p.path) for p in asm.parts[:200])
        self.out.setPlainText(text)
        return True

    def run(self, path):
        self._save()
        scene = self.app.scene
        parts = collect_parts(scene, self.what.currentIndex() == 1)
        if not parts:
            self.out.setPlainText(self.T["nothing"])
            return
        if not self.colors.isChecked():
            for p in parts:
                p.color = None
        unit = self.unit.currentText()
        default = self._format()[-1]
        writer, extra = (self._writer_for(path) if path
                         else self._format()[:2])
        try:
            _, rep = writer(
                parts, path=path, scale=dict(UNITS)[unit], unit=unit,
                author=self.author.text(), **extra,
                filename=os.path.basename(path or default),
                cylinders=self.cyl.isChecked(),
                cyl_mode="soft" if self.cyl_mode.currentIndex() == 0 else "geometry",
                repair_tol=1e-5,          # 0.01 mm: T-junctions, missing caps
                simplify_tol=(self.simp_tol.value() / 1000.0
                              if self.simplify.isChecked() else None))
        except Exception as exc:             # report, never crash the app
            QMessageBox.warning(self, "STEP", f"{self.T['failed']}\n{exc}")
            return
        text = format_report(rep, unit, self.lang)
        if path:
            text = f"{self.T['written']} {path}\n\n" + text
        self.out.setPlainText(text)


def setup(app):
    panel = StepPanel(app)
    dock = app.add_panel("STEP", panel, start_hidden=True)
    try:
        dock.setWindowIcon(_icon())
    except Exception:                         # cosmetic only
        pass

    def show():
        app.show_panel(dock)
        panel.run(None)                       # fresh analysis on opening

    T = texts()
    app.add_menu_action(T["menu"], show, tip=T["menu_tip"])

    def import_menu():
        app.show_panel(dock)
        panel.import_dialog()

    app.add_menu_action(T["menu_import"], import_menu, tip=T["menu_import_tip"])

    def open_step(path):                      # double-click, Open Recent, CLI
        app.show_panel(dock)
        return panel.import_file(path)

    for suffix in (".stp", ".step"):
        try:
            app.add_file_opener(suffix, open_step)
        except Exception:                     # older IngeTrazo: menu only
            pass

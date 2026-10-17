"""IngeTrazo panel "STEP export" (needs PySide6 — loaded by ``setup``).

Extensions ▸ "Export to STEP…" opens the panel. "Analyse" shows what the
file would contain (solids, open parts, cylinders found) without writing
anything; "Export…" asks for the file and writes it. English or French,
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
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_export)
        lay.addLayout(row)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setPlaceholderText(T["placeholder"])
        lay.addWidget(self.out, 1)
        self.btn_check.clicked.connect(lambda: self.run(None))
        self.btn_export.clicked.connect(self.export)
        self.cyl.toggled.connect(self.cyl_mode.setEnabled)
        self._load()

    # ---- options ---------------------------------------------------------
    def _load(self):
        s = self.settings
        self.unit.setCurrentText(s.value("unit", "mm"))
        self.cyl.setChecked(s.value("cylinders", "true") == "true")
        self.cyl_mode.setCurrentIndex(int(s.value("cyl_mode", 0)))
        self.colors.setChecked(s.value("colors", "true") == "true")
        self.author.setText(s.value("author", ""))
        self.simplify.setChecked(s.value("simplify", "false") == "true")
        self.simp_tol.setValue(float(s.value("simplify_tol", 0.1)))
        self.simp_tol.setEnabled(self.simplify.isChecked())
        self.cyl_mode.setEnabled(self.cyl.isChecked())

    def _save(self):
        s = self.settings
        s.setValue("unit", self.unit.currentText())
        s.setValue("cylinders", "true" if self.cyl.isChecked() else "false")
        s.setValue("cyl_mode", self.cyl_mode.currentIndex())
        s.setValue("colors", "true" if self.colors.isChecked() else "false")
        s.setValue("author", self.author.text())
        s.setValue("simplify", "true" if self.simplify.isChecked() else "false")
        s.setValue("simplify_tol", self.simp_tol.value())

    # ---- actions ---------------------------------------------------------
    def export(self):
        last = self.settings.value("last_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getSaveFileName(
            self, self.T["dialog"], os.path.join(last, self.T["default_name"]),
            "STEP (*.stp *.step)")
        if not path:
            return
        if not path.lower().endswith((".stp", ".step")):
            path += ".stp"
        self.settings.setValue("last_dir", os.path.dirname(path))
        self.run(path)

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
        try:
            _, rep = write_step(
                parts, path=path, scale=dict(UNITS)[unit], unit=unit,
                author=self.author.text(),
                filename=os.path.basename(path or self.T["default_name"]),
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

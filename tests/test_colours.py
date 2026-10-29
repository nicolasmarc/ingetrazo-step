"""Part colours: the paint colour first, the mean colour of a texture when
a face has only a picture, the group's paint for faces wearing the default
material. Pieces without any of these stay without colour."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stepexport import collect
from stepexport.collect import faces_part, texture_rgb
from test_collect import F
from test_step import box_faces

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QImage
except ImportError:                      # pragma: no cover
    QImage = None


def _picture(rgb_left, rgb_right):
    """A 64 x 32 image, left half one colour, right half another."""
    img = QImage(64, 32, QImage.Format_RGB888)
    img.fill(QColor(*rgb_left))
    for x in range(32, 64):
        for y in range(32):
            img.setPixelColor(x, y, QColor(*rgb_right))
    path = os.path.join(tempfile.mkdtemp(), "wood.png")
    assert img.save(path)
    return path


def _faces(attrs):
    out = []
    for f in box_faces(0, 0, 0, .1, .1, .1):
        g = F(f)
        g.attrs = dict(attrs)
        out.append(g)
    return out


def test_texture_mean_colour():
    if QImage is None:
        return
    path = _picture((200, 100, 0), (100, 50, 0))     # mean (150, 75, 0)
    rgb = texture_rgb(path)
    assert all(abs(a - b) < 0.01 for a, b in zip(rgb, (150 / 255, 75 / 255, 0)))
    assert texture_rgb(path) is rgb                  # read once
    assert texture_rgb(os.path.join(tempfile.mkdtemp(), "none.png")) is None


def test_textured_part_gets_the_picture_colour():
    if QImage is None:
        return
    path = _picture((0, 0, 255), (0, 0, 255))
    part = faces_part("Hêtre", _faces({"texture": {"path": path, "sw": 1}}))
    assert part.color == (0.0, 0.0, 1.0)


def test_paint_colour_wins_over_the_texture():
    if QImage is None:
        return
    path = _picture((0, 0, 255), (0, 0, 255))
    part = faces_part("Béton", _faces({"color": (0.5, 0.5, 0.5),
                                       "texture": {"path": path}}))
    assert part.color == (0.5, 0.5, 0.5)


def test_group_paint_on_default_faces():
    part = faces_part("Cloison", _faces({}), paint={"color": (0.9, 0.1, 0.1)})
    assert part.color == (0.9, 0.1, 0.1)
    own = _faces({"color": (0.0, 1.0, 0.0)})
    assert faces_part("x", own, paint={"color": (0.9, 0.1, 0.1)}).color \
        == (0.0, 1.0, 0.0)
    assert faces_part("nu", _faces({})).color is None


def test_unreadable_texture_gives_no_colour(monkeypatch):
    collect._TEXTURE_RGB.clear()
    part = faces_part("x", _faces({"texture": {"path": "/nowhere/a.png"}}))
    assert part.color is None

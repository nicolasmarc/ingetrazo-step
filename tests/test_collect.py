"""Scene -> parts, with small fakes standing for IngeTrazo's mesh objects."""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stepexport.collect import collect_parts, format_report
from stepexport.texts import texts
LOOSE_NAME = texts()["loose"]
from stepexport.writer import write_step
from test_cylinders import extrude, circle


class P:                                   # QVector3D stand-in
    def __init__(self, x, y, z):
        self._v = (x, y, z)

    def x(self): return self._v[0]
    def y(self): return self._v[1]
    def z(self): return self._v[2]


class F:
    def __init__(self, face, color=None):
        self.vertices = [P(*p) for p in face.outer]
        self.holes = [[P(*p) for p in h] for h in face.holes]
        self.attrs = {"color": color} if color else {}


class E:
    def __init__(self, a, b, soft, faces=()):
        self.a, self.b, self.soft, self.faces = P(*a), P(*b), soft, list(faces)


class Mesh:
    def __init__(self, faces, soft, color=None):
        self.faces = [F(f, color) for f in faces]
        self.edges = [E(a, b, True, self.faces) for a, b in (soft or [])]


class G:
    def __init__(self, name, mesh, hidden=False):
        self.name, self.mesh, self.hidden, self.billboard = name, mesh, hidden, False


class Scene:
    def __init__(self, groups, loose):
        self.groups, self.loose_mesh, self.selection = groups, loose, set()

    def entity_visible(self, e):
        return not getattr(e, "hidden", False)


def scene():
    f1, s1 = extrude(circle(0, 0, .02, 24), z1=.1)
    f2, s2 = extrude([(0, 0), (.6, 0), (.6, .4), (0, .4)], [circle(.3, .2, .0175, 32)], z1=.018)
    f3, _ = extrude([(1, 0), (1.1, 0), (1.1, .1), (1, .1)], z1=.1)
    groups = [G("Pied", Mesh(f1, s1, (0.8, 0.6, 0.4, 1.0))),
              G("Pied", Mesh(f1, s1)),
              G("Plateau", Mesh(f2, s2)),
              G("Caché", Mesh(f1, s1), hidden=True)]
    return Scene(groups, Mesh(f3, None))


def test_parts_names_colours_soft():
    sc = scene()
    parts = collect_parts(sc, world_mesh=lambda g: g.mesh)
    assert [p.name for p in parts] == ["Pied", "Pied (2)", "Plateau", LOOSE_NAME]
    assert parts[0].color == (0.8, 0.6, 0.4) and parts[1].color is None
    assert len(parts[0].soft_edges) == 24 and parts[3].soft_edges is None


def test_selection_only():
    sc = scene()
    sc.selection = {sc.groups[2]}
    parts = collect_parts(sc, selection_only=True, world_mesh=lambda g: g.mesh)
    assert [p.name for p in parts] == ["Plateau"]


def test_end_to_end_report_fr_en():
    sc = scene()
    parts = collect_parts(sc, world_mesh=lambda g: g.mesh)
    _, rep = write_step(parts, cylinders=True)
    assert rep["solids"] == 4 and rep["cylinders"] == 3
    fr = format_report(rep, lang="fr")
    assert "tige Ø40.00 mm" in fr and "trou Ø35.00 mm" in fr
    assert "3 faces (au lieu de 26)" in fr
    en = format_report(rep, lang="en")
    assert "rod Ø40.00 mm" in en and "hole Ø35.00 mm" in en
    assert "3 faces (instead of 26)" in en and en.startswith("4 solid(s)")


if __name__ == "__main__":
    for k, fn in list(globals().items()):
        if k.startswith("test_"):
            fn(); print("ok", k)

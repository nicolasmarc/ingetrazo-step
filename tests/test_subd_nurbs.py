"""SubD bodies as bicubic B-spline faces: exact on ordinary quads, close
around extraordinary points and creases, a valid closed solid read back by
OpenCascade with the volume of the subdivision surface."""
import math, os, sys
import numpy as np
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from stepexport.model import Part
from stepexport.subdnurbs import (_cc_step, basis, cage_to_bspline, cage_to_nurbs_tol,
                                  cage_to_patches,
                                  distance_to_surface, eval_surface, from_ext,
                                  insert_knot, knots_uniform, shell_volume)
from stepexport.writer import write_step
import occt_check

needs_occt = pytest.mark.skipif(not occt_check.available(),
                                reason="OpenCascade (cadquery-ocp) missing")

CUBE_V = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
CUBE_F = [[0, 2, 6, 4], [1, 5, 7, 3], [0, 4, 5, 1], [2, 3, 7, 6], [0, 1, 3, 2], [4, 6, 7, 5]]
# a pyramid: a quad next to triangles (its edges are cut in two)
PYR_V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0.5, 0.5, 0.8)]
PYR_F = [[0, 3, 2, 1], [0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]]
TOP = {(0, 2): 10, (2, 6): 10, (4, 6): 10, (0, 4): 10}      # a sharp square rim


def torus(n=8, m=6, R=2.0, r=0.7):
    V, F = [], []
    for i in range(n):
        for j in range(m):
            a, b = 2 * math.pi * i / n, 2 * math.pi * j / m
            V.append(((R + r * math.cos(b)) * math.cos(a),
                      (R + r * math.cos(b)) * math.sin(a), r * math.sin(b)))
    for i in range(n):
        for j in range(m):
            F.append([i * m + j, ((i + 1) % n) * m + j,
                      ((i + 1) % n) * m + (j + 1) % m, i * m + (j + 1) % m])
    return V, F


def dense(V, F, cr, levels=6):
    """The subdivision surface itself, refined ``levels`` times (our own
    step, the rules the Subdivision extension uses)."""
    V = np.asarray(V, float)
    sharp = {(min(a, b), max(a, b)): s for (a, b), s in cr.items()}
    for _ in range(levels):
        V, F, sharp, _e, _n = _cc_step(V, F, sharp)
    return V, F


def mesh_volume(V, F):
    tot = 0.0
    for f in F:
        a = V[f[0]]
        for i in range(1, len(f) - 1):
            tot += float(np.dot(a, np.cross(V[f[i]], V[f[i + 1]]))) / 6
    return tot


def deviation(sh, pts):
    """Largest distance from ``pts`` to the nearest face (closest-point
    search from the nearest sampled face point)."""
    from scipy.spatial import cKDTree
    t = np.linspace(0, 1, 17)
    uu, vv = np.meshgrid(t, t)
    S, I = [], []
    for k, f in enumerate(sh.faces):
        S.append(eval_surface(f.net, f.ku, f.kv, uu, vv))
        I.append(np.stack([np.full(uu.size, k), uu.ravel(), vv.ravel()], 1))
    S, I = np.vstack(S), np.vstack(I)
    _, idx = cKDTree(S).query(pts, k=6)
    best = np.full(len(pts), np.inf)
    for col in range(idx.shape[1]):
        rows = I[idx[:, col]]
        for k in np.unique(rows[:, 0]).astype(int):
            sel = rows[:, 0] == k
            f = sh.faces[k]
            d = distance_to_surface(f.net, f.ku, f.kv, pts[sel], rows[sel, 1], rows[sel, 2])
            best[sel] = np.minimum(best[sel], d)
    return best


def test_bspline_basics():
    t = np.linspace(0, 1, 41)
    for kn in (knots_uniform(1), knots_uniform(6), knots_uniform(6, True)):
        N, D = basis(kn, t, True)
        assert np.allclose(N.sum(1), 1) and np.allclose(D.sum(1), 0, atol=1e-9)
    c = np.random.default_rng(1).random((9, 3))       # 6 spans
    kn = knots_uniform(6)
    c2, kn2 = insert_knot(c, kn, 0.5)
    c3, kn3 = insert_knot(c2, kn2, 0.5)
    assert np.allclose(kn3, knots_uniform(6, True))
    assert np.allclose(basis(kn, t) @ c, basis(kn3, t) @ c3)


def test_one_face_per_cage_quad_exact_on_ordinary_quads():
    V, F = torus()
    sh = cage_to_bspline(V, F)
    assert sh.closed and len(sh.faces) == len(F)
    assert sh.exact_faces == len(sh.faces) and sh.max_fit < 1e-12


def test_faces_share_their_edges():
    for V, F, cr in ((CUBE_V, CUBE_F, TOP), (PYR_V, PYR_F, {})):
        sh = cage_to_bspline(V, F, cr, spans=2)
        count = {}
        for f in sh.faces:
            for key, _ in f.loop:
                count[key] = count.get(key, 0) + 1
        assert set(count.values()) == {2} and sh.closed
    sh = cage_to_bspline(PYR_V, PYR_F)
    # the quad base keeps one face; its four sides are cut at their middle
    assert len(sh.faces) == 1 + 4 * 3 and sorted(len(f.loop) for f in sh.faces)[-1] == 8


@pytest.mark.parametrize("V, F, cr", [(CUBE_V, CUBE_F, {}), (CUBE_V, CUBE_F, TOP),
                                      (PYR_V, PYR_F, {})])
def test_close_to_the_subdivision_surface(V, F, cr):
    """Every face touches an extraordinary point (valence 3 or 4 around a
    triangle), the hardest case: more spans bring the faces closer, within
    0.02 % of the size with 4 spans per half edge."""
    Vd, _Fd = dense(V, F, cr, 6)
    pts = Vd[np.random.default_rng(0).choice(len(Vd), 1500, replace=False)]
    d1 = deviation(cage_to_bspline(V, F, cr, spans=1), pts)
    d4 = deviation(cage_to_bspline(V, F, cr, spans=4), pts)
    assert d4.max() < 2e-4 and d4.max() < d1.max()


def test_small_patches_for_subd_editing():
    """The first export, kept as a choice: one Bezier patch (4 x 4 control
    points, four edges) per quad of the refined cage, more levels until the
    tolerance holds."""
    sh = cage_to_patches(CUBE_V, CUBE_F)
    assert len(sh.faces) == 24 and sh.closed
    assert all(f.net.shape == (4, 4, 3) and len(f.loop) == 4 for f in sh.faces)
    fine = cage_to_nurbs_tol(CUBE_V, CUBE_F, {}, tol=2e-4, mode="patches")
    assert fine.max_fit <= 2e-4 and len(fine.faces) in (96, 384)
    sh = cage_to_patches(PYR_V, PYR_F, {}, 2)
    assert sh.closed and len(sh.faces) == 4 * (4 + 4 * 3)


def test_tolerance_picks_the_spans():
    sh = cage_to_nurbs_tol(CUBE_V, CUBE_F, {}, tol=2e-4)
    assert sh.max_fit <= 2e-4 and len(sh.faces) == 6
    fewer = cage_to_bspline(CUBE_V, CUBE_F, {}, spans=sh.spans // 2)
    assert fewer.max_fit > 2e-4                       # the fewest spans that hold


@pytest.mark.parametrize("cage", ["cube", "cube-rim", "torus", "pyramid"])
def test_volume_of_the_faces(cage):
    V, F, cr = {"cube": (CUBE_V, CUBE_F, {}), "cube-rim": (CUBE_V, CUBE_F, TOP),
                "torus": (*torus(), {}), "pyramid": (PYR_V, PYR_F, {})}[cage]
    sh = cage_to_bspline(V, F, cr, spans=4)
    Vd, Fd = dense(V, F, cr, 6)
    ref = mesh_volume(Vd, Fd)
    assert abs(shell_volume(sh) - ref) / ref < 5e-4


def test_cage_from_a_subd_group_payload():
    payload = {"subdiv": {"cage": {"verts": [list(p) for p in CUBE_V],
                                   "faces": CUBE_F, "creases": [[0, 2, 3.0]]}}}
    pts, fs, cr = from_ext(payload)
    assert len(pts) == 8 and len(fs) == 6 and cr == {(0, 2): 3.0}
    assert from_ext({}) is None


@needs_occt
@pytest.mark.parametrize("mode", ["panels", "patches"])
@pytest.mark.parametrize("cage", ["cube", "cube-rim", "torus", "pyramid"])
def test_opencascade_reads_a_valid_solid(cage, mode, tmp_path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    V, F, cr = {"cube": (CUBE_V, CUBE_F, {}), "cube-rim": (CUBE_V, CUBE_F, TOP),
                "torus": (*torus(), {}), "pyramid": (PYR_V, PYR_F, {})}[cage]
    sh = (cage_to_bspline(V, F, cr, spans=2) if mode == "panels"
          else cage_to_patches(V, F, cr))
    text, rep = write_step([Part("SubD", [], (0.8, 0.5, 0.2), nurbs=sh)],
                           scale=1000.0, unit="mm")
    assert "B_SPLINE_SURFACE_WITH_KNOTS" in text and rep["solids"] == 1
    p = tmp_path / "subd.stp"
    p.write_text(text)
    r = STEPControl_Reader()
    r.ReadFile(str(p))
    r.TransferRoots()
    s = r.OneShape()
    assert BRepCheck_Analyzer(s).IsValid()
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, g)
    assert abs(g.Mass() / 1e9 - shell_volume(sh)) / shell_volume(sh) < 1e-4

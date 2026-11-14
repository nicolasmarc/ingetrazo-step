"""SubD bodies as bicubic B-spline faces: exact on ordinary quads, close
around extraordinary points and creases, a valid closed solid read back by
OpenCascade with the volume of the subdivision surface."""
import math, os, sys
import numpy as np
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from stepexport.model import Part
from stepexport.subdnurbs import (_cc_step, cage_to_nurbs, cage_to_nurbs_tol,
                                  distance_to_patch, from_ext, shell_volume)
from stepexport.writer import write_step
import occt_check

needs_occt = pytest.mark.skipif(not occt_check.available(),
                                reason="OpenCascade (cadquery-ocp) missing")

CUBE_V = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
CUBE_F = [[0, 2, 6, 4], [1, 5, 7, 3], [0, 4, 5, 1], [2, 3, 7, 6], [0, 1, 3, 2], [4, 6, 7, 5]]
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
    """Largest distance from ``pts`` to the nearest patch (closest-point
    search from the nearest sampled patch point)."""
    from scipy.spatial import cKDTree
    t = np.linspace(0, 1, 17)
    uu, vv = np.meshgrid(t, t)
    from stepexport.subdnurbs import eval_patch
    S, I = [], []
    for k, (_c, P) in enumerate(sh.faces):
        S.append(eval_patch(P, uu, vv).reshape(-1, 3))
        I.append(np.stack([np.full(uu.size, k), uu.ravel(), vv.ravel()], 1))
    S, I = np.vstack(S), np.vstack(I)
    _, idx = cKDTree(S).query(pts, k=6)
    best = np.full(len(pts), np.inf)
    for col in range(idx.shape[1]):
        rows = I[idx[:, col]]
        for k in np.unique(rows[:, 0]).astype(int):
            sel = rows[:, 0] == k
            d = distance_to_patch(sh.faces[k][1], pts[sel], rows[sel, 1], rows[sel, 2])
            best[sel] = np.minimum(best[sel], d)
    return best


def test_ordinary_quads_are_exact():
    V, F = torus()
    sh = cage_to_nurbs(V, F)
    assert sh.closed and len(sh.faces) == 4 * len(F)
    assert sh.exact_faces == len(sh.faces)
    assert sh.max_fit < 1e-12


def test_faces_share_their_edges():
    sh = cage_to_nurbs(CUBE_V, CUBE_F, TOP)
    count = {}
    for c, P in sh.faces:
        for i in range(4):
            a, b = c[i], c[(i + 1) % 4]
            count[(min(a, b), max(a, b))] = count.get((min(a, b), max(a, b)), 0) + 1
            # the patch border is exactly the shared edge curve
            k = (min(a, b), max(a, b))
            crv = sh.edges[k] if a < b else sh.edges[k][::-1]
            row = [P[0, :], P[:, 3], P[3, ::-1], P[::-1, 0]][i]
            assert np.allclose(row, crv, atol=1e-12)
    assert set(count.values()) == {2} and sh.closed


@pytest.mark.parametrize("cr, tol", [({}, 6e-4), (TOP, 6e-4)])
def test_close_to_the_subdivision_surface(cr, tol):
    """A cube cage: every patch touches an extraordinary point (valence 3),
    the hardest case; one level stays within 0.06 % of the size, and a
    second level within 0.01 %."""
    Vd, _Fd = dense(CUBE_V, CUBE_F, cr, 6)
    pts = Vd[np.random.default_rng(0).choice(len(Vd), 1500, replace=False)]
    d1 = deviation(cage_to_nurbs(CUBE_V, CUBE_F, cr, levels=1), pts)
    d2 = deviation(cage_to_nurbs(CUBE_V, CUBE_F, cr, levels=2), pts)
    assert d1.max() < tol and d2.max() < 1.5e-4
    assert d2.max() < d1.max()


def test_tolerance_picks_the_levels():
    sh = cage_to_nurbs_tol(CUBE_V, CUBE_F, {}, tol=2e-4)
    assert sh.max_fit <= 2e-4 and len(sh.faces) == 96


@pytest.mark.parametrize("cage", ["cube", "cube-rim", "torus"])
def test_volume_of_the_patches(cage):
    V, F, cr = {"cube": (CUBE_V, CUBE_F, {}), "cube-rim": (CUBE_V, CUBE_F, TOP),
                "torus": (*torus(), {})}[cage]
    sh = cage_to_nurbs(V, F, cr, levels=2)
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
@pytest.mark.parametrize("cage", ["cube", "cube-rim", "torus"])
def test_opencascade_reads_a_valid_solid(cage, tmp_path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    V, F, cr = {"cube": (CUBE_V, CUBE_F, {}), "cube-rim": (CUBE_V, CUBE_F, TOP),
                "torus": (*torus(), {})}[cage]
    sh = cage_to_nurbs(V, F, cr)
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

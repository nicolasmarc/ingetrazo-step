"""DXF -> STEP in double precision (stepexport.dxfdirect): exact sizes far
from the origin, one named part per block, assemblies opened up, loose faces
by layer, polyfaces read, a 2D drawing refused."""
import math, os, re, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ezdxf
from stepexport.dxfdirect import read_parts
from stepexport.writer import write_step
from stepexport.reader import read_solids

BOX_F = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def box(x0, y0, z0, x1, y1, z1):
    return [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]


def faces3d(layout, p, layer="0"):
    for a, b, c, d in BOX_F:                # triangulated, as CAD exports
        layout.add_3dface([p[a], p[b], p[c], p[c]], dxfattribs={"layer": layer})
        layout.add_3dface([p[a], p[c], p[d], p[d]], dxfattribs={"layer": layer})


def save(doc):
    fd, path = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    doc.saveas(path)
    return path


def convert(doc):
    parts, info = read_parts(save(doc))
    text, rep = write_step(parts, cylinders=True, repair_tol=1e-5, simplify_tol=1e-4, snap=None)
    return text, rep, read_solids(text), info


def test_slanted_gap_is_exact_far_from_the_origin():
    # two treads 44 mm thick, 70 mm apart along a 30 deg direction, 2 m out:
    # the plane offset comes back 70 mm to 1e-9, which single precision
    # (IngeTrazo's model) cannot give
    doc = ezdxf.new("R2010"); doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    for k in (0, 1):
        o = 70.0 * k
        pts = [(1700 + c * (o + u) - s * v, -1600 + s * (o + u) + c * v, 2500 + w)
               for u, v, w in [(0, 0, 0), (44, 0, 0), (44, 300, 0), (0, 300, 0),
                               (0, 0, 900), (44, 0, 900), (44, 300, 900), (0, 300, 900)]]
        faces3d(msp, pts, layer="Marches")
    text, rep, s_, info = convert(doc)
    assert [x["kind"] for x in s_] == ["solid", "solid"]
    # the two facing walls, from the written vertices: 70 - 44 = 26 mm gap
    pts = [tuple(map(float, m.group(1).split(","))) for m in
           re.finditer(r"CARTESIAN_POINT\('',\(([^)]*)\)\)", text)]
    along = [(x - 1700) * c + (y + 1600) * s for x, y, z in pts]
    for target in (44.0, 70.0, 114.0):
        near = [a for a in along if abs(a - target) < 0.01]
        assert near and max(abs(a - target) for a in near) < 1e-6, (target, near[:3])
    assert all(abs(x["volume"] / (44 * 300 * 900.0) - 1) < 1e-9 for x in s_)


def test_blocks_are_named_parts_and_assemblies_open_up():
    doc = ezdxf.new("R2010"); doc.header["$INSUNITS"] = 4
    m = doc.blocks.new("Marche")
    faces3d(m, box(0, 0, 0, 900, 250, 40))
    lim = doc.blocks.new("Limon")
    faces3d(lim, box(0, 0, 0, 40, 1000, 300))
    asm = doc.blocks.new("Escalier")         # one block for the whole
    asm.add_blockref("Marche", (40, 0, 200))
    asm.add_blockref("Marche", (40, 250, 400))
    asm.add_blockref("Limon", (0, 0, 0))
    doc.modelspace().add_blockref("Escalier", (1000, 2000, 0))
    text, rep, s_, info = convert(doc)
    names = re.findall(r"=PRODUCT\('([^']*)'", text)
    assert names.count("Marche") == 2 and "Limon" in names, names
    assert all(x["kind"] == "solid" for x in s_) and len(s_) == 3


def test_polyface_and_units_guess():
    doc = ezdxf.new("R2010"); doc.header["$INSUNITS"] = 0       # no units
    pf = doc.modelspace().add_polyface(dxfattribs={"layer": "Plateau"})
    p = box(0, 0, 0, 300, 200, 40)
    pf.append_faces([[p[i] for i in f] for f in BOX_F]); pf.optimize()
    text, rep, s_, info = convert(doc)
    assert not info["declared"] and info["scale"] == 0.001
    assert s_[0]["kind"] == "solid" and abs(s_[0]["volume"] - 300 * 200 * 40.0) < 1e-6


def test_a_2d_drawing_is_refused():
    doc = ezdxf.new("R2010")
    doc.modelspace().add_line((0, 0), (1, 1))
    try:
        read_parts(save(doc))
    except ValueError:
        return
    raise AssertionError("expected ValueError")


if __name__ == "__main__":
    for k, fn in list(globals().items()):
        if k.startswith("test_"):
            fn(); print("ok", k)

"""DXF -> STEP in double precision, without going through the IngeTrazo model.

IngeTrazo keeps positions in single precision (about 7 digits): a part two
metres from the origin comes back a few hundred-thousandths of a millimetre
off. That is invisible in the model, but a CAD program measures it: a 70 mm
gap reads 69.99995 mm. This module reads the DXF itself with ezdxf (double
precision, the file's own digits) and hands the faces straight to the STEP
writer, so the file measures exactly what the DXF says.

What it reads: 3DFACE, SOLID / TRACE, POLYFACE and polygon-mesh POLYLINEs,
MESH. Parts: one per block placement (an assembly block -- a block holding
only INSERTs, the way stair and joinery programs export -- is opened up into
its parts, each named after its block), and the loose faces of the model
space, one part per layer. The writer then splits each part into its
separate solids, as for an IngeTrazo group.
"""
import math

from .coplanar import merge_coplanar
from .model import Face, Part

UNIT_TO_M = {1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 14: 0.1}
MAX_DEPTH = 8


def _guess_scale(doc, loops):
    """Metres per drawing unit: the header when it says, else a guess from
    the size (a model several hundred units across is in millimetres)."""
    u = doc.header.get("$INSUNITS", 0)
    if u in UNIT_TO_M:
        return UNIT_TO_M[u], True
    span = 0.0
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for loop in loops[:5000]:
        for p in loop:
            for k in range(3):
                lo[k] = min(lo[k], p[k])
                hi[k] = max(hi[k], p[k])
    if lo[0] < math.inf:
        span = max(h - l for h, l in zip(hi, lo))
    return (0.001 if span > 50 else 1.0), False


def _clean(pts):
    out = []
    for p in pts:
        p = (float(p[0]), float(p[1]), float(p[2]))
        if not out or max(abs(a - b) for a, b in zip(p, out[-1])) > 1e-12:
            out.append(p)
    if len(out) > 1 and max(abs(a - b) for a, b in zip(out[0], out[-1])) <= 1e-12:
        out.pop()
    return out if len(out) >= 3 else None


def _entity_loops(e):
    """Face loops of a face-carrying entity (drawing units, object space),
    or ``None`` for linework and annotation."""
    t = e.dxftype()
    if t == "3DFACE":
        d = e.dxf
        loop = _clean([d.vtx0, d.vtx1, d.vtx2, d.vtx3])
        return [loop] if loop else []
    if t in ("SOLID", "TRACE"):
        d = e.dxf
        loop = _clean([d.vtx0, d.vtx1, d.vtx3, d.vtx2])
        return [loop] if loop else []
    if t in ("POLYLINE", "MESH"):
        try:
            from ezdxf.render import MeshBuilder
            if t == "POLYLINE":
                if not (e.is_poly_face_mesh or e.is_polygon_mesh):
                    return None
                mb = MeshBuilder.from_polyface(e)
            else:
                mb = MeshBuilder.from_mesh(e)
        except Exception:
            return []
        out = []
        for f in mb.faces:
            loop = _clean([mb.vertices[i] for i in f])
            if loop:
                out.append(loop)
        return out
    return None


def _apply(m, loops):
    return [[tuple(m.transform(p)) for p in loop] for loop in loops]


def _block_loops(doc, name, m, depth, acc):
    """Every face of block ``name`` (nested INSERTs exploded) placed by the
    matrix ``m``, appended to ``acc``."""
    if depth > MAX_DEPTH:
        return
    try:
        blk = doc.blocks[name]
    except Exception:
        return
    for e in blk:
        if e.dxftype() == "INSERT":
            try:
                _block_loops(doc, e.dxf.name, e.matrix44() * m, depth + 1, acc)
            except Exception:
                pass
            continue
        loops = _entity_loops(e)
        if loops:
            acc.extend(_apply(m, loops))


def _is_assembly(doc, name):
    try:
        ents = list(doc.blocks[name])
    except Exception:
        return False
    inserts = [e for e in ents if e.dxftype() == "INSERT"]
    rest = [e for e in ents if e.dxftype() not in ("INSERT", "ATTDEF")]
    return bool(inserts) and not rest


def read_parts(path):
    """-> (parts in metres, info dict). Raises ValueError when the file holds
    no faces at all (a 2D drawing)."""
    import ezdxf
    from ezdxf.math import Matrix44

    doc = ezdxf.readfile(path)
    named = []                               # (name, loops in drawing units)
    loose = {}                               # layer -> loops

    def place(name, m, depth):
        if depth <= MAX_DEPTH and _is_assembly(doc, name):
            for e in doc.blocks[name]:
                if e.dxftype() == "INSERT":
                    try:
                        place(e.dxf.name, e.matrix44() * m, depth + 1)
                    except Exception:
                        pass
            return
        acc = []
        _block_loops(doc, name, m, depth, acc)
        if acc:
            named.append((name, acc))

    for e in doc.modelspace():
        if e.dxftype() == "INSERT":
            try:
                place(e.dxf.name, e.matrix44(), 0)
            except Exception:
                pass
            continue
        loops = _entity_loops(e)
        if loops:
            loose.setdefault(getattr(e.dxf, "layer", "0") or "0", []).extend(loops)
    all_loops = [l for _, ls in named for l in ls] + [l for ls in loose.values() for l in ls]
    if not all_loops:
        raise ValueError("no 3D faces in this DXF (3DFACE, POLYFACE, MESH...)")
    s, declared = _guess_scale(doc, all_loops)
    parts = []
    for name, loops in named + sorted(loose.items()):
        loops_m = [[(x * s, y * s, z * s) for x, y, z in l] for l in loops]
        # coplanar triangles back into polygons (what IngeTrazo's import
        # does), in double precision; welding at 10 nm keeps every digit
        faces, verts = merge_coplanar(loops_m, weld_tol=1e-8, dist_tol=1e-9,
                                      repair=False)
        parts.append(Part(name, [Face([verts[i] for i in f[0]],
                                      [[verts[i] for i in h] for h in f[1:]])
                                 for f in faces]))
    info = {"scale": s, "declared": declared, "parts": len(parts),
            "faces": len(all_loops)}
    return parts, info

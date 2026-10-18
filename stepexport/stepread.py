"""STEP (ISO 10303-21, AP203 / AP214 / AP242) assembly reader, pure Python.

Written from the public standard, for Motion: it gives, for every part of
an assembly, its name, its place in the tree, its placement and its
surface as triangles (plus the planar faces' outlines with their holes),
in metres. It is not a CAD kernel: curved faces are meshed to a chord
tolerance from their boundary, which is what a mechanism needs (bounding
boxes, drawings, collisions).

    asm = read("spider.step", tol=0.0005)
    for part in asm.parts:
        part.name, part.path, part.matrix, part.triangles, part.color

Faces handled: PLANE, CYLINDRICAL_SURFACE, CONICAL_SURFACE,
SPHERICAL_SURFACE, TOROIDAL_SURFACE, SURFACE_OF_LINEAR_EXTRUSION,
SURFACE_OF_REVOLUTION, B_SPLINE_SURFACE(_WITH_KNOTS) incl. rational, plus
faceted B-rep (POLY_LOOP) and tessellated faces (AP242). Curves: LINE,
CIRCLE, ELLIPSE, B_SPLINE_CURVE(_WITH_KNOTS) incl. rational,
SURFACE_CURVE / SEAM_CURVE. Anything else falls back to straight edges and
a best-fit plane, and is counted in ``asm.warnings``.
"""
import math
import re
from dataclasses import dataclass, field

import numpy as np

# -- parsing ISO 10303-21 -------------------------------------------------------


class Ref(int):
    """#123"""


class Enum(str):
    """.T. / .MILLI."""


_TOKEN = re.compile(r"""
    \s*(?:
      (?P<str>'(?:[^']|'')*')          |
      (?P<ref>\#\d+)                   |
      (?P<enum>\.[A-Za-z0-9_]+\.)      |
      (?P<num>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?) |
      (?P<kw>[A-Za-z_][A-Za-z0-9_]*)   |
      (?P<sym>[(),$*])
    )""", re.X)


_ESC = re.compile(r"\\X2\\((?:[0-9A-Fa-f]{4})+)\\X0\\|\\X4\\((?:[0-9A-Fa-f]{8})+)\\X0\\"
                  r"|\\X\\([0-9A-Fa-f]{2})|\\S\\(.)|\\\\")


def _text(s):
    """Text of a STEP string: \\X2\\00E8\\X0\\ -> è, \\X\\E9 -> é (ISO 8859-1),
    \\S\\h -> high half of ISO 8859-1, \\\\ -> \\."""
    if "\\" not in s:
        return s

    def sub(m):
        if m.group(1):
            h = m.group(1)
            return "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4))
        if m.group(2):
            h = m.group(2)
            return "".join(chr(int(h[i:i + 8], 16)) for i in range(0, len(h), 8))
        if m.group(3):
            return chr(int(m.group(3), 16))
        if m.group(4):
            return chr(ord(m.group(4)) + 128)
        return "\\"
    return _ESC.sub(sub, s)


_GENERIC = re.compile(r"(?i)^\s*(|model|unnamed|sans nom|nauo\d*|solid|solide|body|corps|"
                      r"volume|brep|part|pi[eè]ce|component|composant|shape|forme|"
                      r"open ?shell|closed ?shell)\s*[-_ ]?\(?\d*\)?\s*$")


def _generic(name):
    """True for names a CAD program gives on its own ('Solide', 'Body2',
    'NAUO3', '') — a part keeps the name its designer gave instead."""
    return name is None or bool(_GENERIC.match(str(name)))


def _tokens(text):
    pos, n = 0, len(text)
    match = _TOKEN.match
    while pos < n:
        m = match(text, pos)
        if not m:
            if text[pos:].strip() == "":
                return
            raise ValueError(f"STEP: unexpected text near {text[pos:pos + 30]!r}")
        pos = m.end()
        k = m.lastgroup
        yield k, m.group(k)


def _parse_args(toks, i):
    """Parse '(' ... ')' starting at toks[i] == '('. Returns (list, next i)."""
    assert toks[i] == ("sym", "(")
    out, i = [], i + 1
    while True:
        k, v = toks[i]
        if k == "sym" and v == ")":
            return out, i + 1
        if k == "sym" and v == ",":
            i += 1
            continue
        if k == "sym" and v == "(":
            sub, i = _parse_args(toks, i)
            out.append(sub)
        elif k == "kw" and i + 1 < len(toks) and toks[i + 1] == ("sym", "("):
            sub, i = _parse_args(toks, i + 1)       # typed value: LENGTH_MEASURE(1.)
            out.append((v.upper(), sub))
        else:
            if k == "str":
                out.append(_text(v[1:-1].replace("''", "'")))
            elif k == "ref":
                out.append(Ref(int(v[1:])))
            elif k == "enum":
                out.append(Enum(v[1:-1].upper()))
            elif k == "num":
                out.append(float(v))
            elif v in ("$", "*"):
                out.append(None)
            else:
                out.append(v)
            i += 1


class Entities:
    """The DATA section, decoded on demand: ``E[id]`` -> {TYPE: args}
    (several keys for a complex instance); ``E.ids(TYPE)`` lists the
    instances of a type without decoding the others."""

    _STMT = re.compile(r"#(\d+)\s*=\s*((?:[^;']|'(?:[^']|'')*')*);")
    _HEAD = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)")

    def __init__(self, body):
        self.raw, self.done, self.index = {}, {}, {}
        for stmt in self._STMT.finditer(body):
            eid, rhs = int(stmt.group(1)), stmt.group(2).strip()
            self.raw[eid] = rhs
            if rhs.startswith("("):                       # complex: decode now
                rec = self[eid]
                for t in rec:
                    self.index.setdefault(t, []).append(eid)
            else:
                m = self._HEAD.match(rhs)
                if m:
                    self.index.setdefault(m.group(1).upper(), []).append(eid)

    def __getitem__(self, eid):
        rec = self.done.get(eid)
        if rec is None:
            rec = _decode(self.raw[eid])
            self.done[eid] = rec
        return rec

    def get(self, eid, default=None):
        return self[eid] if eid in self.raw else default

    def __contains__(self, eid):
        return eid in self.raw

    def __len__(self):
        return len(self.raw)

    def ids(self, t):
        return self.index.get(t, [])

    def items(self):
        for eid in self.raw:
            yield eid, self[eid]

    def values(self):
        for eid in self.raw:
            yield self[eid]


def _decode(rhs):
    toks = list(_tokens(rhs))
    rec = {}
    if not toks:
        return rec
    if toks[0] == ("sym", "("):                         # complex instance
        i = 1
        while toks[i] != ("sym", ")"):
            name = toks[i][1].upper()
            args, i = _parse_args(toks, i + 1)
            rec[name] = args
    else:
        args, _ = _parse_args(toks, 1)
        rec[toks[0][1].upper()] = args
    return rec


def parse(text):
    """The DATA section as :class:`Entities` ({id: {TYPE: args}})."""
    m = re.search(r"\bDATA\s*;", text)
    if not m:
        raise ValueError("STEP: no DATA section")
    body = text[m.end():]
    end = re.search(r"\bENDSEC\s*;", body)
    body = body[:end.start()] if end else body
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return Entities(body)


# -- result ----------------------------------------------------------------------

@dataclass
class Face:
    kind: str                       # surface type, lower case
    triangles: np.ndarray           # (n, 3, 3) part frame, metres
    loops: list = None              # planar faces: [outer, hole, ...] (k, 3)


@dataclass
class Part:
    name: str
    path: tuple                     # names from the root
    matrix: np.ndarray              # 4x4, part frame -> world
    faces: list = field(default_factory=list)
    color: tuple = None             # (r, g, b) 0..1

    @property
    def triangles(self):
        """World triangles (n, 3, 3)."""
        if not self.faces:
            return np.zeros((0, 3, 3))
        T = np.concatenate([f.triangles for f in self.faces if len(f.triangles)])
        return T @ self.matrix[:3, :3].T + self.matrix[:3, 3]

    def world(self, pts):
        pts = np.asarray(pts, float)
        return pts @ self.matrix[:3, :3].T + self.matrix[:3, 3]


@dataclass
class Assembly:
    parts: list
    unit: float                     # metres per file length unit
    warnings: dict


def volume(triangles):
    """Signed volume enclosed by outward triangles."""
    T = np.asarray(triangles, float)
    if not len(T):
        return 0.0
    return float(np.einsum("ij,ij->i", T[:, 0], np.cross(T[:, 1], T[:, 2])).sum() / 6)


# -- the reader ----------------------------------------------------------------------

class _Reader:
    def __init__(self, ents, tol, max_angle):
        self.e = ents
        self.tol = tol                      # chord tolerance, file units
        self.max_angle = max_angle
        self.warn = {}
        self.unit = self._unit()
        self.tol_f = tol / self.unit        # tolerance in file units
        self._edge_cache = {}

    # basic access
    def get(self, ref, *types):
        rec = self.e.get(int(ref)) or {}
        for t in types:
            if t in rec:
                return rec[t]
        return None

    def kind(self, ref):
        rec = self.e.get(int(ref)) or {}
        return next(iter(rec)) if len(rec) == 1 else "+".join(sorted(rec))

    def note(self, what):
        self.warn[what] = self.warn.get(what, 0) + 1

    def point(self, ref):
        a = self.get(ref, "CARTESIAN_POINT")
        if a is None:
            a = self.get(self.get(ref, "VERTEX_POINT")[1], "CARTESIAN_POINT")
        c = list(a[1]) + [0.0] * (3 - len(a[1]))
        return np.array(c[:3], float)

    def direction(self, ref):
        a = self.get(ref, "DIRECTION")
        d = np.array(list(a[1]) + [0.0] * (3 - len(a[1])), float)[:3]
        return d / np.linalg.norm(d)

    def vector(self, ref):
        a = self.get(ref, "VECTOR")
        return self.direction(a[1]) * float(a[2])

    def axis2(self, ref):
        """(origin, X, Y, Z) of an AXIS2_PLACEMENT_3D."""
        a = self.get(ref, "AXIS2_PLACEMENT_3D")
        o = self.point(a[1])
        z = self.direction(a[2]) if a[2] is not None else np.array([0, 0, 1.0])
        x = self.direction(a[3]) if len(a) > 3 and a[3] is not None else None
        if x is None or abs(x @ z) > 1 - 1e-12:
            x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
        x = x - z * (x @ z)
        x /= np.linalg.norm(x)
        return o, x, np.cross(z, x), z

    def matrix(self, ref):
        o, x, y, z = self.axis2(ref)
        M = np.eye(4)
        M[:3, 0], M[:3, 1], M[:3, 2], M[:3, 3] = x, y, z, o
        return M

    def _unit(self):
        for eid in self.e.ids("LENGTH_UNIT"):
            rec = self.e[eid]
            if "LENGTH_UNIT" in rec:
                if "SI_UNIT" in rec:
                    pre = rec["SI_UNIT"][0]
                    return {"MILLI": 1e-3, "CENTI": 1e-2, "DECI": 1e-1, "KILO": 1e3,
                            "MICRO": 1e-6}.get(pre or "", 1.0)
                if "CONVERSION_BASED_UNIT" in rec:
                    name = str(rec["CONVERSION_BASED_UNIT"][0]).upper()
                    return {"INCH": 0.0254, "FOOT": 0.3048, "MILLIMETRE": 1e-3,
                            "MILLIMETER": 1e-3}.get(name, 1e-3)
        return 1e-3                                       # usual default: mm

    # -- curves -----------------------------------------------------------------
    def _n_arc(self, r, sweep):
        if r <= 0:
            return 1
        step = 2 * math.acos(max(-1.0, 1 - self.tol_f / r)) if self.tol_f < r else math.pi / 2
        step = min(step, self.max_angle)
        return max(1, int(math.ceil(abs(sweep) / step)))

    def curve_points(self, cref, p0, p1, sense=True):
        """Points along curve ``cref`` from p0 to p1 (both included)."""
        k = self.kind(cref)
        a = self.e[int(cref)]
        if k in ("SURFACE_CURVE", "SEAM_CURVE", "INTERSECTION_CURVE"):
            return self.curve_points(a[k][1], p0, p1, sense)
        if k == "LINE":
            return np.array([p0, p1])
        if k in ("CIRCLE", "ELLIPSE"):
            o, x, y, z = self.axis2(a[k][1])
            ra = float(a[k][2])
            rb = float(a[k][3]) if k == "ELLIPSE" else ra

            def ang(p):
                v = p - o
                return math.atan2((v @ y) / rb, (v @ x) / ra)
            t0, t1 = ang(p0), ang(p1)
            if sense:
                sweep = (t1 - t0) % (2 * math.pi)
            else:
                sweep = -((t0 - t1) % (2 * math.pi))
            if abs(sweep) < 1e-12 and np.linalg.norm(p0 - p1) < 1e-9 * max(1, ra):
                sweep = 2 * math.pi if sense else -2 * math.pi          # full turn
            n = self._n_arc(max(ra, rb), sweep)
            ts = t0 + sweep * np.arange(n + 1) / n
            pts = o + np.outer(ra * np.cos(ts), x) + np.outer(rb * np.sin(ts), y)
            pts[0], pts[-1] = p0, p1
            return pts
        if "B_SPLINE_CURVE" in a or k.startswith("B_SPLINE_CURVE") or "B_SPLINE_CURVE_WITH_KNOTS" in a:
            return self._bspline_curve_points(a, p0, p1, sense)
        self.note(f"courbe {k}")
        return np.array([p0, p1])

    def _bspline_curve(self, a):
        if "B_SPLINE_CURVE_WITH_KNOTS" in a and "B_SPLINE_CURVE" not in a:
            b = a["B_SPLINE_CURVE_WITH_KNOTS"]
            deg, cps, mult, knots = int(b[1]), b[2], b[6], b[7]
            w = None
        else:
            b = a["B_SPLINE_CURVE"]
            deg, cps = int(b[1]), b[2]
            kk = a["B_SPLINE_CURVE_WITH_KNOTS"]
            mult, knots = kk[0], kk[1]
            w = a.get("RATIONAL_B_SPLINE_CURVE")
            w = np.array(w[0], float) if w else None
        P = np.array([self.point(c) for c in cps])
        U = np.repeat(np.array(knots, float), np.array(mult, int))
        return deg, P, U, w

    def _bspline_curve_points(self, a, p0, p1, sense):
        deg, P, U, w = self._bspline_curve(a)
        lo, hi = U[deg], U[len(U) - deg - 1]
        # dense evaluation, then the stretch between the two vertices
        n = max(64, 16 * len(P))
        ts = np.linspace(lo, hi, n + 1)
        pts = np.array([_bspline_eval(deg, P, U, w, t) for t in ts])
        i0 = int(np.argmin(np.linalg.norm(pts - p0, axis=1)))
        i1 = int(np.argmin(np.linalg.norm(pts - p1, axis=1)))
        closed = np.linalg.norm(pts[0] - pts[-1]) < 1e-7 * max(1.0, np.ptp(P))
        if not sense:
            i0, i1 = i1, i0
        if i1 > i0:
            seg = pts[i0:i1 + 1]
        elif closed:                                   # wraps over the seam
            seg = np.concatenate([pts[i0:], pts[1:i1 + 1]]) if i1 != i0 else pts
        else:
            seg = pts[i1:i0 + 1][::-1]
        if not sense:
            seg = seg[::-1]
        seg = _simplify(seg, self.tol_f)
        seg[0], seg[-1] = p0, p1
        return seg

    def edge_points(self, eref):
        """Points of an EDGE_CURVE from its start vertex to its end vertex."""
        if eref in self._edge_cache:
            return self._edge_cache[eref]
        a = self.get(eref, "EDGE_CURVE")
        p0, p1 = self.point(a[1]), self.point(a[2])
        sense = a[4] in (True, "T", Enum("T")) or str(a[4]).upper() == "T"
        pts = self.curve_points(a[3], p0, p1, sense)
        self._edge_cache[eref] = pts
        return pts

    def loop_edges(self, lref):
        """[(edge id or None, points in loop order)] of a loop."""
        k = self.kind(lref)
        a = self.e[int(lref)][k]
        if k == "POLY_LOOP":
            return [(None, np.array([self.point(p) for p in a[1]]))]
        if k == "VERTEX_LOOP":
            return [(None, np.array([self.point(a[1])]))]
        out = []
        for oe in a[1]:
            o = self.get(oe, "ORIENTED_EDGE")
            e = self.edge_points(o[3])
            if str(o[4]).upper() != "T":
                e = e[::-1]
            out.append((int(o[3]), e))
        return out

    @staticmethod
    def join(chain):
        pts = [c for _, c in chain]
        P = np.concatenate([pts[0]] + [q[1:] for q in pts[1:]]) if pts else np.zeros((0, 3))
        if len(P) > 1 and np.linalg.norm(P[0] - P[-1]) < 1e-9 * max(1.0, np.ptp(P)):
            P = P[:-1]
        return P

    def loop_points(self, lref):
        return self.join(self.loop_edges(lref))

    # -- faces -------------------------------------------------------------------
    def face(self, fref):
        rec = self.e[int(fref)]
        k = next(iter(rec))
        if k in ("TRIANGULATED_FACE", "COMPLEX_TRIANGULATED_FACE"):
            return self._tess_face(rec[k], k)
        a = rec[k]
        surf = a[2] if k != "FACE_SURFACE" or len(a) > 2 else None
        sk0 = self.kind(surf) if surf is not None else ""
        periodic = sk0 in ("CYLINDRICAL_SURFACE", "CONICAL_SURFACE", "SPHERICAL_SURFACE",
                           "TOROIDAL_SURFACE", "SURFACE_OF_REVOLUTION")
        raw = []
        for b in a[1]:
            bk = self.kind(b)
            ba = self.e[int(b)][bk]
            chain = self.loop_edges(ba[1])
            if str(ba[2]).upper() != "T":
                chain = [(eid, pts[::-1]) for eid, pts in chain[::-1]]
            raw.append((bk == "FACE_OUTER_BOUND", chain))
        def assemble(raw_):
            return [(outer, self.join(chain)) for outer, chain in raw_ if chain]

        loops = assemble(raw)
        if periodic:
            # a loop that encloses nothing in (u, v) (a dome: seam up and down
            # plus one circle) is read again without its seams
            count = {}
            for _, chain in raw:
                for eid, _p in chain:
                    if eid is not None:
                        count[eid] = count.get(eid, 0) + 1
            seams = {e for e, n in count.items() if n == 2}
            if seams:
                S0 = _Surface.make(self, sk0, surf, [L for _, L in loops])
                if S0 is not None and _degenerate([S0.to_uv_loop(L) for _, L in loops], S0):
                    cut = []
                    for outer, chain in raw:
                        for piece in _split_chain(chain, seams):
                            cut.append((False, piece))
                    raw = cut
        loops = assemble(raw)
        same = str(a[3]).upper() == "T" if len(a) > 3 else True
        # outer loop first (if none flagged, the longest)
        if not any(o for o, _ in loops) and loops:
            big = max(range(len(loops)), key=lambda i: _perimeter(loops[i][1]))
            loops[big] = (True, loops[big][1])
        loops.sort(key=lambda t: not t[0])
        P = [L for _, L in loops if len(L) >= 1]
        if not P or len(P[0]) < 3:
            return None
        sk = self.kind(surf) if surf is not None else "PLANE?"
        return self._mesh_face(sk, surf, P, same)

    def _tess_face(self, a, k):
        self.note("faces tessellées")
        return None

    def _mesh_face(self, sk, sref, loops, same):
        S = _Surface.make(self, sk, sref, loops)
        if S is None:
            self.note(f"surface {sk}")
            S = _Surface.plane_fit(loops)
        # loops -> uv (each loop unwrapped continuously)
        uvs = [S.to_uv_loop(L) for L in loops]
        if isinstance(S, _Sphere) and len(loops) == 1:
            w = _winding(uvs[0], S.period_u)
            if abs(abs(w) - S.period_u) < 1e-6 * S.period_u:   # a cap round a pole
                S = _SphereCap(S, (1.0 if w > 0 else -1.0) * (1.0 if same else -1.0))
                uvs = [S.to_uv_loop(L) for L in loops]
        tris_uv, pts_uv = _triangulate_uv(uvs, S, same)
        if tris_uv is None:
            self.note("faces non maillées")
            return None
        if S.curved:
            offs = np.cumsum([0] + [len(u) for u in uvs])
            bnd = [list(range(offs[k], offs[k + 1])) for k in range(len(uvs))]
            pts_uv, tris_uv = _refine(pts_uv, tris_uv, S, self.tol_f, self.max_angle, bnd)
        P3 = S.from_uv(pts_uv)
        # boundary points keep their exact 3D position
        nb = sum(len(L) for L in loops)
        P3[:nb] = np.concatenate(loops)
        T = P3[np.asarray(tris_uv, int)]
        # orientation: along the surface normal (x same_sense)
        c = T.mean(axis=1)
        n_tri = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        n_srf = S.normal_at(c, pts_uv[np.asarray(tris_uv, int)].mean(axis=1))
        flip = np.einsum("ij,ij->i", n_tri, n_srf) * (1 if same else -1) < 0
        T[flip] = T[flip][:, ::-1]
        loops_out = None
        if S.kind == "plane":
            nrm = S.z if same else -S.z
            loops_out = [_orient_loop(loops[0], nrm, True)] + \
                        [_orient_loop(L, nrm, False) for L in loops[1:]]
        return Face(S.kind, T * self.unit, None if loops_out is None
                    else [L * self.unit for L in loops_out])

    # -- shapes and products ------------------------------------------------------
    def items_faces(self, rep):
        """Faces of the geometric items of a representation."""
        out = []
        k = self.kind(rep)
        a = self.e[int(rep)][next(iter(self.e[int(rep)]))] if k else None
        items = a[1] if a else []
        for it in items:
            out += self.item_faces(it)
        return out

    def item_faces(self, it):
        k = self.kind(it)
        rec = self.e[int(it)]
        if k in ("MANIFOLD_SOLID_BREP", "FACETED_BREP"):
            return self.shell_faces(rec[k][1])
        if k == "BREP_WITH_VOIDS":
            a = rec[k]
            out = self.shell_faces(a[1])
            for v in a[2]:
                out += self.shell_faces(v)
            return out
        if k in ("SHELL_BASED_SURFACE_MODEL",):
            out = []
            for sh in rec[k][1]:
                out += self.shell_faces(sh)
            return out
        if k in ("CLOSED_SHELL", "OPEN_SHELL", "ORIENTED_CLOSED_SHELL"):
            return self.shell_faces(it)
        if k in ("ADVANCED_FACE", "FACE_SURFACE"):
            f = self.face(it)
            return [f] if f else []
        if k == "MAPPED_ITEM":
            a = rec[k]
            rmap = self.get(a[1], "REPRESENTATION_MAP")
            faces = self.items_faces(rmap[1])
            T = self.matrix(a[2]) @ np.linalg.inv(self.matrix(rmap[0]))
            return [_transform_face(f, T, self.unit) for f in faces]
        return []

    def shell_faces(self, sref):
        k = self.kind(sref)
        a = self.e[int(sref)][k]
        out = []
        for f in a[1]:
            try:
                face = self.face(f)
            except Exception:
                self.note("faces illisibles")
                face = None
            if face is not None:
                out.append(face)
        return out


def _degenerate(uvs, S):
    """The (u, v) outline encloses (almost) nothing."""
    P = np.concatenate(uvs)
    ext = max(np.ptp(P[:, 0]), 1e-12) * max(np.ptp(P[:, 1]), 1e-12)
    total = sum(abs(_area2(u)) / 2 for u in uvs if len(u) > 2)
    return total < 0.05 * ext


def _split_chain(chain, seams):
    """Edges of a loop without the seam edges, regrouped into closed
    chains (each a whole turn once the seams are gone)."""
    n = len(chain)
    if not n:
        return []
    start = next((i for i in range(n) if chain[i][0] in seams), None)
    if start is None:
        return [chain]
    order = chain[start:] + chain[:start]
    pieces, cur = [], []
    for eid, pts in order:
        if eid in seams:
            if cur:
                pieces.append(cur)
            cur = []
        else:
            cur.append((eid, pts))
    if cur:
        pieces.append(cur)
    return pieces


def _transform_face(f, T, unit):
    R, t = T[:3, :3], T[:3, 3] * unit
    tri = f.triangles @ R.T + t
    loops = None if f.loops is None else [L @ R.T + t for L in f.loops]
    return Face(f.kind, tri, loops)


def _perimeter(P):
    return float(np.linalg.norm(np.diff(np.vstack([P, P[:1]]), axis=0), axis=1).sum())


def _orient_loop(L, n, ccw):
    area = np.cross(L - L.mean(0), np.roll(L, -1, 0) - L.mean(0)).sum(0) @ n
    return L if (area > 0) == ccw else L[::-1]


def _simplify(P, tol):
    """Drop points closer than tol/4 to their predecessor (keep ends)."""
    if len(P) <= 2:
        return P.copy()
    keep = [0]
    for i in range(1, len(P) - 1):
        if np.linalg.norm(P[i] - P[keep[-1]]) > tol / 4:
            keep.append(i)
    keep.append(len(P) - 1)
    return P[keep].copy()


# -- B-splines ------------------------------------------------------------------------

def _span(deg, U, t):
    n = len(U) - deg - 2
    if t >= U[n + 1]:
        return n
    lo, hi = deg, n + 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if t < U[mid]:
            hi = mid
        else:
            lo = mid
    return lo


def _basis(deg, U, t, i):
    N = np.zeros(deg + 1)
    N[0] = 1.0
    left, right = np.zeros(deg + 1), np.zeros(deg + 1)
    for j in range(1, deg + 1):
        left[j] = t - U[i + 1 - j]
        right[j] = U[i + j] - t
        saved = 0.0
        for r in range(j):
            den = right[r + 1] + left[j - r]
            tmp = N[r] / den if den != 0 else 0.0
            N[r] = saved + right[r + 1] * tmp
            saved = left[j - r] * tmp
        N[j] = saved
    return N


def _bspline_eval(deg, P, U, w, t):
    i = _span(deg, U, t)
    N = _basis(deg, U, t, i)
    idx = range(i - deg, i + 1)
    if w is None:
        return sum(N[k] * P[j] for k, j in enumerate(idx))
    num = sum(N[k] * w[j] * P[j] for k, j in enumerate(idx))
    den = sum(N[k] * w[j] for k, j in enumerate(idx))
    return num / den


# -- surfaces -------------------------------------------------------------------------

class _Surface:
    curved = True
    kind = "surface"

    @staticmethod
    def make(rd, sk, sref, loops):
        if sref is None:
            return None
        a = rd.e[int(sref)]
        try:
            if sk == "PLANE":
                return _Plane(*rd.axis2(a[sk][1]))
            if sk == "CYLINDRICAL_SURFACE":
                return _Cylinder(rd.axis2(a[sk][1]), float(a[sk][2]))
            if sk == "CONICAL_SURFACE":
                return _Cone(rd.axis2(a[sk][1]), float(a[sk][2]), float(a[sk][3]))
            if sk == "SPHERICAL_SURFACE":
                return _Sphere(rd.axis2(a[sk][1]), float(a[sk][2]))
            if sk == "TOROIDAL_SURFACE":
                return _Torus(rd.axis2(a[sk][1]), float(a[sk][2]), float(a[sk][3]))
            if sk == "SURFACE_OF_LINEAR_EXTRUSION":
                return _Extrusion(rd, a[sk][1], rd.vector(a[sk][2]), loops)
            if sk == "SURFACE_OF_REVOLUTION":
                ax = rd.get(a[sk][2], "AXIS1_PLACEMENT")
                o = rd.point(ax[1])
                z = rd.direction(ax[2]) if ax[2] is not None else np.array([0, 0, 1.0])
                return _Revolution(o, z)
            if "B_SPLINE_SURFACE" in a or sk.startswith("B_SPLINE_SURFACE") \
                    or "B_SPLINE_SURFACE_WITH_KNOTS" in a:
                return _BSplineSurface(rd, a)
        except Exception:
            return None
        return None

    @staticmethod
    def plane_fit(loops):
        P = np.concatenate(loops)
        c = P.mean(0)
        _, _, vt = np.linalg.svd(P - c)
        x, y, z = vt[0], vt[1], vt[2]
        return _Plane(c, x, y, z)

    def to_uv_loop(self, L):
        return np.array([self.to_uv(p) for p in L])

    def normal_at(self, P, uv):
        return np.array([self.normal(p, q) for p, q in zip(P, uv)])

    def from_uv(self, UV):
        return np.array([self.point(u, v) for u, v in UV])


class _Plane(_Surface):
    curved = False
    kind = "plane"

    def __init__(self, o, x, y, z):
        self.o, self.x, self.y, self.z = o, x, y, z

    def to_uv(self, p):
        d = p - self.o
        return (d @ self.x, d @ self.y)

    def point(self, u, v):
        return self.o + u * self.x + v * self.y

    def normal(self, p, uv):
        return self.z


class _Periodic(_Surface):
    """Surfaces with an angle about an axis: loops are unwrapped."""
    period_u = None

    def to_uv_loop(self, L):
        uv = np.array([self.to_uv(p) for p in L], float)
        if self.period_u is not None and len(uv) > 1:   # continuous angle
            per = self.period_u
            d = np.diff(uv[:, 0])
            d = d - per * np.round(d / per)
            uv[1:, 0] = uv[0, 0] + np.cumsum(d)
        return uv


class _Cylinder(_Periodic):
    kind = "cylindre"

    def __init__(self, ax, r):
        self.o, self.x, self.y, self.z = ax
        self.r = r
        self.period_u = 2 * math.pi * r

    def to_uv(self, p):
        d = p - self.o
        return (self.r * math.atan2(d @ self.y, d @ self.x), d @ self.z)

    def point(self, u, v):
        t = u / self.r
        return self.o + self.r * (math.cos(t) * self.x + math.sin(t) * self.y) + v * self.z

    def normal(self, p, uv):
        d = p - self.o
        d = d - self.z * (d @ self.z)
        return d / (np.linalg.norm(d) or 1)


class _Cone(_Periodic):
    kind = "cône"

    def __init__(self, ax, r, half):
        self.o, self.x, self.y, self.z = ax
        self.r, self.ta = r, math.tan(half)
        self.rm = max(r, 1e-9)
        self.period_u = 2 * math.pi * self.rm

    def to_uv(self, p):
        d = p - self.o
        return (self.rm * math.atan2(d @ self.y, d @ self.x), d @ self.z)

    def point(self, u, v):
        t = u / self.rm
        rr = self.r + v * self.ta
        return self.o + rr * (math.cos(t) * self.x + math.sin(t) * self.y) + v * self.z

    def normal(self, p, uv):
        t = uv[0] / self.rm
        radial = math.cos(t) * self.x + math.sin(t) * self.y
        n = radial - self.ta * self.z
        return n / np.linalg.norm(n)


class _Sphere(_Periodic):
    kind = "sphère"

    def __init__(self, ax, r):
        self.o, self.x, self.y, self.z = ax
        self.r = r
        self.period_u = 2 * math.pi * r

    def to_uv(self, p):
        d = p - self.o
        return (self.r * math.atan2(d @ self.y, d @ self.x),
                self.r * math.asin(max(-1.0, min(1.0, (d @ self.z) / self.r))))

    def point(self, u, v):
        t, f = u / self.r, v / self.r
        return self.o + self.r * (math.cos(f) * (math.cos(t) * self.x + math.sin(t) * self.y)
                                  + math.sin(f) * self.z)

    def normal(self, p, uv):
        d = p - self.o
        return d / (np.linalg.norm(d) or 1)

    def pole_v(self, side):
        return side * self.r * math.pi / 2


class _SphereCap(_Surface):
    """A sphere seen from one pole (azimuthal equidistant): a cap round
    that pole becomes a plain disc."""
    kind = "sphère"

    def __init__(self, sph, side):
        self.s, self.side = sph, side

    def to_uv(self, p):
        s = self.s
        d = p - s.o
        f = math.asin(max(-1.0, min(1.0, (d @ s.z) / s.r)))
        rho = s.r * (math.pi / 2 - self.side * f)
        t = math.atan2(d @ s.y, d @ s.x)
        return (rho * math.cos(t), self.side * rho * math.sin(t))

    def point(self, u, v):
        s = self.s
        rho = math.hypot(u, v)
        t = math.atan2(self.side * v, u)
        f = self.side * (math.pi / 2 - rho / s.r)
        return s.o + s.r * (math.cos(f) * (math.cos(t) * s.x + math.sin(t) * s.y)
                            + math.sin(f) * s.z)

    def normal(self, p, uv):
        d = p - self.s.o
        return d / (np.linalg.norm(d) or 1)


def _winding(u, per):
    if len(u) < 2:
        return 0.0
    close = u[0, 0] - u[-1, 0]
    close -= per * round(close / per)
    return (u[-1, 0] - u[0, 0]) + close


class _Torus(_Periodic):
    kind = "tore"

    def __init__(self, ax, R, r):
        self.o, self.x, self.y, self.z = ax
        self.R, self.r = R, r
        self.period_u = 2 * math.pi * R

    def to_uv_loop(self, L):
        uv = super().to_uv_loop(L)
        per = 2 * math.pi * self.r                      # tube angle too
        if len(uv) > 1:
            d = np.diff(uv[:, 1])
            d = d - per * np.round(d / per)
            uv[1:, 1] = uv[0, 1] + np.cumsum(d)
        return uv

    def to_uv(self, p):
        d = p - self.o
        t = math.atan2(d @ self.y, d @ self.x)
        rad = math.hypot(d @ self.x, d @ self.y) - self.R
        return (self.R * t, self.r * math.atan2(d @ self.z, rad))

    def point(self, u, v):
        t, f = u / self.R, v / self.r
        radial = math.cos(t) * self.x + math.sin(t) * self.y
        return self.o + (self.R + self.r * math.cos(f)) * radial + self.r * math.sin(f) * self.z

    def normal(self, p, uv):
        t = uv[0] / self.R
        c = self.o + self.R * (math.cos(t) * self.x + math.sin(t) * self.y)
        d = p - c
        return d / (np.linalg.norm(d) or 1)


class _Revolution(_Periodic):
    """Revolution of a profile: (angle x mean radius, axial position);
    points are put back at the radius interpolated along the boundary."""
    kind = "révolution"

    def __init__(self, o, z):
        self.o, self.z = o, z
        a = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
        self.x = np.cross(z, a)
        self.x /= np.linalg.norm(self.x)
        self.y = np.cross(self.z, self.x)
        self.rm = 1.0
        self.period_u = 2 * math.pi
        self._prof = None

    def to_uv_loop(self, L):
        d = L - self.o
        h = d @ self.z
        rho = np.linalg.norm(d - np.outer(h, self.z), axis=1)
        self.rm = max(float(rho.mean()), 1e-9)
        self.period_u = 2 * math.pi * self.rm
        order = np.argsort(h)
        self._prof = (h[order], rho[order]) if self._prof is None else (
            np.concatenate([self._prof[0], h]), np.concatenate([self._prof[1], rho]))
        o = np.argsort(self._prof[0])
        self._prof = (self._prof[0][o], self._prof[1][o])
        return super().to_uv_loop(L)

    def to_uv(self, p):
        d = p - self.o
        return (self.rm * math.atan2(d @ self.y, d @ self.x), d @ self.z)

    def point(self, u, v):
        rho = float(np.interp(v, *self._prof)) if self._prof is not None else self.rm
        t = u / self.rm
        return self.o + rho * (math.cos(t) * self.x + math.sin(t) * self.y) + v * self.z

    def normal(self, p, uv):
        d = p - self.o
        d = d - self.z * (d @ self.z)
        return d / (np.linalg.norm(d) or 1)


class _Extrusion(_Surface):
    """Curve swept along a vector: (arc length along the curve, depth)."""
    kind = "extrusion"

    def __init__(self, rd, cref, vec, loops):
        self.d = vec / np.linalg.norm(vec)
        P = np.concatenate(loops)
        # densely sampled base curve, from the boundary projected back
        base = P - np.outer(P @ self.d, self.d)
        k = rd.kind(cref)
        if k in ("LINE",):
            self.curved = False
        c = rd.curve_points(cref, base[0], base[0])
        if len(c) < 8:
            c = base
        self.curve = c - np.outer(c @ self.d, self.d)
        seg = np.linalg.norm(np.diff(self.curve, axis=0), axis=1)
        self.s = np.concatenate([[0], np.cumsum(seg)])

    def to_uv(self, p):
        q = p - self.d * (p @ self.d)
        a, b = self.curve[:-1], self.curve[1:]
        ab = b - a
        t = np.clip(np.einsum("ij,ij->i", q - a, ab) / np.maximum(
            np.einsum("ij,ij->i", ab, ab), 1e-300), 0, 1)
        dist = np.linalg.norm(a + ab * t[:, None] - q, axis=1)
        i = int(np.argmin(dist))
        return (self.s[i] + t[i] * (self.s[i + 1] - self.s[i]), p @ self.d)

    def point(self, u, v):
        x = np.interp(u, self.s, self.curve[:, 0])
        y = np.interp(u, self.s, self.curve[:, 1])
        z = np.interp(u, self.s, self.curve[:, 2])
        return np.array([x, y, z]) + v * self.d

    def normal(self, p, uv):
        u = uv[0]
        e = 1e-6 * max(1.0, self.s[-1])
        t = self.point(u + e, 0) - self.point(u - e, 0)
        n = np.cross(t, self.d)
        return n / (np.linalg.norm(n) or 1)


class _BSplineSurface(_Surface):
    kind = "b-spline"

    def __init__(self, rd, a):
        if "B_SPLINE_SURFACE_WITH_KNOTS" in a and "B_SPLINE_SURFACE" not in a:
            b = a["B_SPLINE_SURFACE_WITH_KNOTS"]
            du, dv, grid = int(b[1]), int(b[2]), b[3]
            mu, mv, ku, kv = b[8], b[9], b[10], b[11]
            w = None
        else:
            b = a["B_SPLINE_SURFACE"]
            du, dv, grid = int(b[0]), int(b[1]), b[2]
            kk = a["B_SPLINE_SURFACE_WITH_KNOTS"]
            mu, mv, ku, kv = kk[0], kk[1], kk[2], kk[3]
            r = a.get("RATIONAL_B_SPLINE_SURFACE")
            w = np.array(r[0], float) if r else None
        self.du, self.dv = du, dv
        self.P = np.array([[rd.point(c) for c in row] for row in grid])
        self.w = w
        self.U = np.repeat(np.array(ku, float), np.array(mu, int))
        self.V = np.repeat(np.array(kv, float), np.array(mv, int))
        self.u0, self.u1 = self.U[du], self.U[len(self.U) - du - 1]
        self.v0, self.v1 = self.V[dv], self.V[len(self.V) - dv - 1]
        # a grid for the inverse, and a metric scale for uv
        n = 24
        self.gu = np.linspace(self.u0, self.u1, n)
        self.gv = np.linspace(self.v0, self.v1, n)
        self.G = np.array([[self._eval(u, v) for v in self.gv] for u in self.gu])
        lu = np.linalg.norm(np.diff(self.G, axis=0), axis=2).sum(0).mean()
        lv = np.linalg.norm(np.diff(self.G, axis=1), axis=2).sum(1).mean()
        self.su = max(lu, 1e-12) / (self.u1 - self.u0 or 1)
        self.sv = max(lv, 1e-12) / (self.v1 - self.v0 or 1)

    def _eval(self, u, v):
        i = _span(self.du, self.U, u)
        j = _span(self.dv, self.V, v)
        Nu = _basis(self.du, self.U, u, i)
        Nv = _basis(self.dv, self.V, v, j)
        num, den = np.zeros(3), 0.0
        for a in range(self.du + 1):
            for b in range(self.dv + 1):
                wgt = Nu[a] * Nv[b]
                ii, jj = i - self.du + a, j - self.dv + b
                if self.w is not None:
                    wgt *= self.w[ii][jj]
                num += wgt * self.P[ii, jj]
                den += wgt
        return num / den

    def _invert(self, p):
        d = np.linalg.norm(self.G - p, axis=2)
        i, j = np.unravel_index(int(np.argmin(d)), d.shape)
        u, v = self.gu[i], self.gv[j]
        hu = (self.u1 - self.u0) * 1e-6
        hv = (self.v1 - self.v0) * 1e-6
        for _ in range(12):                              # Gauss-Newton
            S = self._eval(u, v)
            Su = (self._eval(min(u + hu, self.u1), v) - self._eval(max(u - hu, self.u0), v)) / (2 * hu)
            Sv = (self._eval(u, min(v + hv, self.v1)) - self._eval(u, max(v - hv, self.v0))) / (2 * hv)
            J = np.column_stack([Su, Sv])
            step, *_ = np.linalg.lstsq(J, p - S, rcond=None)
            u = min(max(u + step[0], self.u0), self.u1)
            v = min(max(v + step[1], self.v0), self.v1)
            if np.linalg.norm(step) < 1e-12:
                break
        return u, v

    def to_uv(self, p):
        u, v = self._invert(p)
        return (u * self.su, v * self.sv)

    def point(self, u, v):
        return self._eval(min(max(u / self.su, self.u0), self.u1),
                          min(max(v / self.sv, self.v0), self.v1))

    def normal(self, p, uv):
        u, v = uv[0] / self.su, uv[1] / self.sv
        hu = (self.u1 - self.u0) * 1e-5
        hv = (self.v1 - self.v0) * 1e-5
        Su = self._eval(min(u + hu, self.u1), v) - self._eval(max(u - hu, self.u0), v)
        Sv = self._eval(u, min(v + hv, self.v1)) - self._eval(u, max(v - hv, self.v0))
        n = np.cross(Su, Sv)
        return n / (np.linalg.norm(n) or 1)


# -- triangulation in the face's parameter plane --------------------------------------

def _area2(P):
    x, y = P[:, 0], P[:, 1]
    return float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _triangulate_uv(uvs, S, same=True):
    """Ear clipping with holes bridged to the outer loop. Returns
    (triangles as indices into the stacked loops, stacked uv points).
    A loop that goes once around a periodic surface without enclosing
    anything (a sphere's dome, a cone's base) is closed through the pole
    or the apex, on the side where the face lies."""
    per = getattr(S, "period_u", None) if S.curved else None
    if per:
        def winding(u):
            if len(u) < 2:
                return 0.0
            close = u[0, 0] - u[-1, 0]
            close -= per * round(close / per)
            return (u[-1, 0] - u[0, 0]) + close
        wrap = [len(u) > 2 and abs(abs(winding(u)) - per) < 1e-6 * per for u in uvs]
        points = [u for u in uvs if len(u) == 1]
        loops_w = [u for u, w in zip(uvs, wrap) if w]
        if len(loops_w) == 1 and len(uvs) - len(points) == 1:
            L = loops_w[0]
            goes = 1.0 if winding(L) > 0 else -1.0
            side = goes * (1.0 if same else -1.0)            # face on the left
            if points:
                vp = float(points[0][0, 1])
            else:
                vp = S.pole_v(side) if hasattr(S, "pole_v") else None
            if vp is not None:
                Lx = np.vstack([L, L[:1] + np.array([goes * per, 0.0])])
                n = max(2, int(per / (per / 24)))
                us = np.linspace(Lx[-1, 0], Lx[0, 0], n + 1)
                cap = np.column_stack([us, np.full(len(us), vp)])
                poly = np.vstack([Lx, cap])
                idx = list(range(len(poly)))
                tris = _earclip(idx if _area2(poly) > 0 else idx[::-1], poly)
                return (tris if tris else None), poly
    pts = np.concatenate(uvs)
    offs = np.cumsum([0] + [len(u) for u in uvs])
    loops = [list(range(offs[k], offs[k + 1])) for k in range(len(uvs))]
    # periodic band without a seam: two loops each going once around
    if S.curved and getattr(S, "period_u", None) and len(uvs) == 2:
        spans = [abs(u[-1, 0] - u[0, 0] + (u[1, 0] - u[0, 0] if len(u) > 1 else 0)) for u in uvs]
        wraps = [abs((u[:, 0].max() - u[:, 0].min()) - S.period_u) < 0.02 * S.period_u
                 and abs(_area2(u)) < 1e-9 * S.period_u ** 2 for u in uvs]
        if all(wraps):
            return _band(uvs, offs, pts, S)
    outer = loops[0]
    if _area2(pts[outer]) < 0:
        outer = outer[::-1]
    holes = []
    for h in loops[1:]:
        if len(h) < 3:
            continue
        holes.append(h if _area2(pts[h]) < 0 else h[::-1])
    poly = _bridge(outer, holes, pts)
    tris = _earclip(poly, pts)
    return (tris if tris else None), pts


def _band(uvs, offs, pts, S):
    """Strip between two loops that each wrap once around (no seam)."""
    a = list(range(offs[0], offs[1]))
    b = list(range(offs[1], offs[2]))
    # sort both by u, then zip with a moving front
    a.sort(key=lambda i: pts[i, 0])
    b.sort(key=lambda i: pts[i, 0])
    per = S.period_u
    pts = pts.copy()
    tris, i, j = [], 0, 0
    A, B = a + [a[0]], b + [b[0]]
    ua = [pts[k, 0] for k in a] + [pts[a[0], 0] + per]
    ub = [pts[k, 0] for k in b] + [pts[b[0], 0] + per]
    while i < len(a) or j < len(b):
        if j >= len(b) or (i < len(a) and ua[i + 1] <= ub[j + 1]):
            tris.append([A[i], A[i + 1], B[j]])
            i += 1
        else:
            tris.append([A[i], B[j + 1], B[j]])
            j += 1
    return tris, pts


def _bridge(outer, holes, pts):
    """One polygon from an outer loop and holes (each hole joined to the
    outer loop by a cut from its rightmost point)."""
    poly = list(outer)
    for h in sorted(holes, key=lambda h: -max(pts[i, 0] for i in h)):
        k = max(range(len(h)), key=lambda q: pts[h[q], 0])
        hp = pts[h[k]]
        # nearest visible outer vertex to the right, else simply the nearest
        best, bd = None, None
        for idx, vi in enumerate(poly):
            d = np.linalg.norm(pts[vi] - hp)
            if pts[vi, 0] >= hp[0] - 1e-12 and (bd is None or d < bd) and _visible(hp, pts[vi], poly, pts, h):
                best, bd = idx, d
        if best is None:
            best = min(range(len(poly)), key=lambda q: np.linalg.norm(pts[poly[q]] - hp))
        ring = h[k:] + h[:k] + [h[k]]
        poly = poly[:best + 1] + ring + poly[best:]
    return poly


def _segments_cross(p, q, a, b):
    def o(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])
    d1, d2, d3, d4 = o(p, q, a), o(p, q, b), o(a, b, p), o(a, b, q)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _visible(p, q, poly, pts, hole):
    for ring in (poly, hole):
        n = len(ring)
        for i in range(n):
            a, b = pts[ring[i]], pts[ring[(i + 1) % n]]
            if _segments_cross(p, q, a, b):
                return False
    return True


def _earclip(poly, pts):
    P = [(float(p[0]), float(p[1])) for p in pts]
    idx = list(poly)
    tris = []
    guard = 0
    n0 = len(poly)

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    while len(idx) > 3 and guard < 10 * n0 * n0 + 100:
        guard += 1
        n = len(idx)
        clipped = False
        for i in range(n):
            ia, ib, ic = idx[i - 1], idx[i], idx[(i + 1) % n]
            a, b, c = P[ia], P[ib], P[ic]
            if cross(a, b, c) <= 1e-18:
                continue
            ok = True
            # bounding box of the ear, to skip far points quickly
            x0, x1 = min(a[0], b[0], c[0]), max(a[0], b[0], c[0])
            y0, y1 = min(a[1], b[1], c[1]), max(a[1], b[1], c[1])
            for j in idx:
                if j == ia or j == ib or j == ic:
                    continue
                p = P[j]
                if p[0] < x0 or p[0] > x1 or p[1] < y0 or p[1] > y1:
                    continue
                if p == a or p == b or p == c:
                    continue
                if (cross(a, b, p) >= -1e-15 and cross(b, c, p) >= -1e-15
                        and cross(c, a, p) >= -1e-15):
                    ok = False
                    break
            if ok:
                tris.append([ia, ib, ic])
                del idx[i]
                clipped = True
                break
        if not clipped:                     # degenerate: drop a flat vertex
            n = len(idx)
            k = min(range(n), key=lambda i: abs(cross(P[idx[i - 1]], P[idx[i]],
                                                      P[idx[(i + 1) % n]])))
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % n]
            if abs(cross(P[a], P[b], P[c])) > 1e-18:
                tris.append([a, b, c])
            del idx[k]
    if len(idx) == 3 and cross(P[idx[0]], P[idx[1]], P[idx[2]]) > 1e-18:
        tris.append(list(idx))
    return tris


def _incircle(a, b, c, d):
    """> 0 when d is inside the circle through the CCW triangle a b c."""
    adx, ady = a[0] - d[0], a[1] - d[1]
    bdx, bdy = b[0] - d[0], b[1] - d[1]
    cdx, cdy = c[0] - d[0], c[1] - d[1]
    ad, bd, cd = adx * adx + ady * ady, bdx * bdx + bdy * bdy, cdx * cdx + cdy * cdy
    return (adx * (bdy * cd - bd * cdy) - ady * (bdx * cd - bd * cdx)
            + ad * (bdx * cdy - bdy * cdx))


def _ccw(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _refine(pts, tris, S, tol, max_angle, boundary=None, max_points=6000):
    """Make the uv triangulation Delaunay (boundary edges kept), then
    insert points at the centroid of every triangle whose chord strays
    from the surface by more than ``tol``, keeping it Delaunay."""
    P = [tuple(p) for p in pts]
    T = [list(t) for t in tris]
    nb = len(P)
    fixed = set()
    if boundary is not None:
        for loop in boundary:
            for k in range(len(loop)):
                fixed.add(frozenset((loop[k], loop[(k + 1) % len(loop)])))
    owner = {}                                   # directed edge -> triangle

    def register(ti):
        a, b, c = T[ti]
        owner[(a, b)] = ti
        owner[(b, c)] = ti
        owner[(c, a)] = ti

    def unregister(ti):
        a, b, c = T[ti]
        for e in ((a, b), (b, c), (c, a)):
            if owner.get(e) == ti:
                del owner[e]

    for ti in range(len(T)):
        register(ti)

    def legalize(stack):
        guard = 0
        while stack and guard < 200000:
            guard += 1
            a, b = stack.pop()
            if frozenset((a, b)) in fixed or a == b:
                continue
            t1, t2 = owner.get((a, b)), owner.get((b, a))
            if t1 is None or t2 is None or t1 == t2:
                continue
            c = next(v for v in T[t1] if v not in (a, b))
            d = next((v for v in T[t2] if v not in (a, b)), None)
            if d is None or c == d:
                continue
            pa, pb, pc, pd = P[a], P[b], P[c], P[d]
            if _incircle(pa, pb, pc, pd) <= 1e-18 * (1 + abs(pa[0]) + abs(pa[1])) ** 4:
                continue
            if _ccw(pa, pd, pc) <= 0 or _ccw(pd, pb, pc) <= 0:
                continue                         # not convex: no flip
            unregister(t1)
            unregister(t2)
            T[t1], T[t2] = [a, d, c], [d, b, c]
            register(t1)
            register(t2)
            stack += [(a, d), (d, b), (b, c), (c, a)]

    legalize([e for e in list(owner)])
    cache = {}

    def S3(i):
        if i not in cache:
            cache[i] = S.point(*P[i])
        return cache[i]

    for i in range(nb):                          # boundary points: exact on S
        cache[i] = S.point(*P[i])
    queue = list(range(len(T)))
    while queue and len(P) < max_points:
        ti = queue.pop()
        a, b, c = T[ti]
        pa, pb, pc = P[a], P[b], P[c]
        area = _ccw(pa, pb, pc)
        if area <= 1e-14:
            continue
        g = ((pa[0] + pb[0] + pc[0]) / 3, (pa[1] + pb[1] + pc[1]) / 3)
        chord = (S3(a) + S3(b) + S3(c)) / 3
        if np.linalg.norm(S.point(*g) - chord) <= tol:
            continue
        k = len(P)
        P.append(g)
        unregister(ti)
        T[ti] = [a, b, k]
        T.append([b, c, k])
        T.append([c, a, k])
        for t in (ti, len(T) - 2, len(T) - 1):
            register(t)
        legalize([(a, b), (b, c), (c, a)])
        queue += [ti, len(T) - 2, len(T) - 1]
        # flips may have changed neighbours: look at them again
        for e in ((a, b), (b, c), (c, a)):
            for o in (owner.get(e), owner.get((e[1], e[0]))):
                if o is not None:
                    queue.append(o)
    return np.array(P), np.array(T)


# -- product structure ----------------------------------------------------------------

def read(path_or_text, tol=0.0002, max_angle=math.radians(15)):
    """Read a STEP file (path, or its text). ``tol``: chord tolerance in
    metres. Returns an :class:`Assembly`."""
    text = path_or_text
    if "ISO-10303-21" not in str(path_or_text)[:200]:
        with open(path_or_text, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    ents = parse(text)
    rd = _Reader(ents, tol, max_angle)
    E = ents

    def first(rec_type):
        return [(i, E[i][rec_type]) for i in E.ids(rec_type)]

    # product definitions and their names
    pd_name = {}
    for i, a in first("PRODUCT_DEFINITION"):
        pdf = rd.get(a[2], "PRODUCT_DEFINITION_FORMATION",
                     "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE")
        prod = rd.get(pdf[2], "PRODUCT") if pdf else None
        pd_name[i] = (prod[1] or prod[0]) if prod else f"pièce {i}"
    # product definition -> its shape representation
    pds_def = {i: a[2] for i, a in first("PRODUCT_DEFINITION_SHAPE")}
    pd_rep = {}
    for i, a in first("SHAPE_DEFINITION_REPRESENTATION"):
        d = pds_def.get(int(a[0]))
        if d is not None and int(d) in pd_name:
            pd_rep[int(d)] = int(a[1])
    # representation -> geometric representations without placement
    rep_geo = {}
    for i in E.ids("SHAPE_REPRESENTATION_RELATIONSHIP"):
        rec = E[i]
        if "SHAPE_REPRESENTATION_RELATIONSHIP" in rec and \
                "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION" not in rec:
            a = rec["SHAPE_REPRESENTATION_RELATIONSHIP"]
            r1, r2 = int(a[2]), int(a[3])
            rep_geo.setdefault(r1, []).append(r2)
            rep_geo.setdefault(r2, []).append(r1)
    # assembly links: parent PD -> [(child PD, transform child->parent, name)]
    nauo = {i: a for i, a in first("NEXT_ASSEMBLY_USAGE_OCCURRENCE")}
    children = {}
    placed = {}
    for i in E.ids("CONTEXT_DEPENDENT_SHAPE_REPRESENTATION"):
        rec = E[i]
        a = rec["CONTEXT_DEPENDENT_SHAPE_REPRESENTATION"]
        rel = E[int(a[0])]
        occ = pds_def.get(int(a[1]))
        if occ is None or int(occ) not in nauo:
            continue
        rr = rel.get("REPRESENTATION_RELATIONSHIP")
        rt = rel.get("REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION")
        if not rr or not rt:
            continue
        idt = rd.get(rt[0], "ITEM_DEFINED_TRANSFORMATION")
        if idt is None:
            rd.note("placement non lu")
            continue
        T = rd.matrix(idt[3]) @ np.linalg.inv(rd.matrix(idt[2]))
        o = nauo[int(occ)]
        parent, child = int(o[3]), int(o[4])
        if pd_rep.get(child) == int(rr[3]) and pd_rep.get(parent) == int(rr[2]):
            T = np.linalg.inv(T)                         # written the other way
        T[:3, 3] *= rd.unit
        placed[int(occ)] = True
        children.setdefault(parent, []).append((child, T, o[1] or o[0] or pd_name.get(child)))
    for i, o in nauo.items():                            # links without placement
        if i not in placed:
            children.setdefault(int(o[3]), []).append((int(o[4]), np.eye(4), o[1] or o[0]))
    is_child = {c for lst in children.values() for c, _, _ in lst}
    roots = [p for p in pd_name if p not in is_child]

    # colours: solid / shell / face -> rgb
    colour = {}
    for i, a in first("STYLED_ITEM"):
        rgb = _find_rgb(rd, a[1])
        if rgb is not None and a[2] is not None:
            colour[int(a[2])] = rgb

    geo_cache = {}
    SOLIDS = ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "FACETED_BREP",
              "SHELL_BASED_SURFACE_MODEL", "MAPPED_ITEM")

    def geometry(pd):
        """[(item name, faces, colour)] — one entry per solid of the
        product's shape (a file may put several named solids in one
        product); loose faces and shells are gathered in one entry."""
        rep = pd_rep.get(pd)
        if rep is None:
            return []
        if rep in geo_cache:
            return geo_cache[rep]
        reps = [rep] + rep_geo.get(rep, [])
        out, loose, loose_col = [], [], None
        for r in reps:
            rec = E[r]
            k = next(iter(rec))
            for it in rec[k][1]:
                faces = rd.item_faces(it)
                if not faces:
                    continue
                col = colour.get(int(it))
                kind = rd.kind(it)
                if kind in SOLIDS:
                    name = rec_name(it)
                    out.append((name, faces, col))
                else:
                    loose += faces
                    loose_col = loose_col or col
        if loose:
            out.append(("", loose, loose_col))
        geo_cache[rep] = out
        return out

    def rec_name(it):
        rec = E[int(it)]
        args = rec[next(iter(rec))]
        n = args[0] if args and isinstance(args[0], str) else ""
        return n.strip()

    parts = []

    def walk(pd, M, path):
        items = geometry(pd)
        for k, (iname, faces, col) in enumerate(items):
            # the product (component) name is what the designer typed; a
            # solid inside often only has the CAD program's own 'Solide'
            if len(items) == 1:
                name = path[-1] if not _generic(path[-1]) or _generic(iname) else iname
                p = path if name == path[-1] else path + [name]
            else:
                name = iname if not _generic(iname) else f"{path[-1]} {k + 1}"
                p = path + [name]
            parts.append(Part(name, tuple(p), M.copy(), faces, col))
        for child, T, occ_name in children.get(pd, []):
            nm = occ_name if not _generic(occ_name) else pd_name.get(child)
            walk(child, M @ T, path + [str(nm or occ_name or "")])

    for r in roots:
        walk(r, np.eye(4), [pd_name[r]])
    # name each part after its product when the occurrence name is generic
    return Assembly(parts, rd.unit, rd.warn)


def _find_rgb(rd, styles):
    stack = list(styles or [])
    seen = 0
    while stack and seen < 64:
        seen += 1
        s = stack.pop()
        if isinstance(s, list):
            stack += s
            continue
        if not isinstance(s, Ref):
            continue
        rec = rd.e.get(int(s)) or {}
        if "COLOUR_RGB" in rec:
            a = rec["COLOUR_RGB"]
            return (float(a[1]), float(a[2]), float(a[3]))
        for args in rec.values():
            stack += [x for x in _flat(args) if isinstance(x, Ref)]
    return None


def _flat(a):
    for x in a:
        if isinstance(x, list):
            yield from _flat(x)
        elif isinstance(x, tuple):
            yield from _flat(x[1])
        else:
            yield x

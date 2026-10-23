"""Minimal STEP reader — only what is needed to verify our own output.

Independent of the writer's internals: it re-derives every solid from the
entity graph (shell -> faces -> loops -> oriented edges -> vertices) and
reports volume, face count and edge pairing, so a test can compare them with
what the model said.
"""
import math
import re
import numpy as np
from .check import newell


class StepError(Exception):
    pass


def _split_statements(data):
    out, buf, q = [], [], False
    for ch in data:
        if ch == "'":
            q = not q
        if ch == ";" and not q:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    return [s for s in out if s]


class _Parser:
    def __init__(self, s):
        self.s, self.i = s, 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\r\n":
            self.i += 1

    def value(self):
        self.ws()
        c = self.s[self.i]
        if c == "(":
            self.i += 1
            items = []
            while True:
                self.ws()
                if self.s[self.i] == ")":
                    self.i += 1
                    return items
                items.append(self.value())
                self.ws()
                if self.s[self.i] == ",":
                    self.i += 1
        if c == "'":
            j = self.i + 1
            while True:
                if self.s[j] == "'":
                    if j + 1 < len(self.s) and self.s[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            v = self.s[self.i + 1:j]
            self.i = j + 1
            return v
        m = re.compile(r"#(\d+)").match(self.s, self.i)
        if m:
            self.i = m.end()
            return ("ref", int(m.group(1)))
        m = re.compile(r"\.[A-Z_]+\.").match(self.s, self.i)
        if m:
            self.i = m.end()
            return m.group(0)
        if c in "$*":
            self.i += 1
            return c
        m = re.compile(r"[-+]?\d+\.?\d*(?:[Ee][-+]?\d+)?").match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            return float(t) if ("." in t or "E" in t.upper()) else int(t)
        m = re.compile(r"[A-Z0-9_]+").match(self.s, self.i)
        if m:                                    # typed value, e.g. LENGTH_MEASURE(1.)
            self.i = m.end()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "(":
                return (m.group(0), self.value())
            return m.group(0)
        raise StepError(f"cannot parse near: {self.s[self.i:self.i + 30]!r}")

    def entity(self):
        """-> list of (TYPE, args) (several for a complex entity)."""
        self.ws()
        if self.s[self.i] == "(":
            self.i += 1
            out = []
            while True:
                self.ws()
                if self.s[self.i] == ")":
                    self.i += 1
                    return out
                out.append(self._simple())
        return [self._simple()]

    def _simple(self):
        self.ws()
        m = re.compile(r"[A-Z0-9_]+").match(self.s, self.i)
        if not m:
            raise StepError("entity name expected")
        self.i = m.end()
        self.ws()
        args = self.value() if self.s[self.i] == "(" else []
        return m.group(0), args


def parse(text):
    if not text.lstrip().startswith("ISO-10303-21;"):
        raise StepError("not a STEP file")
    m = re.search(r"\bDATA;(.*)ENDSEC;\s*END-ISO-10303-21;", text, re.S)
    if not m:
        raise StepError("no DATA section")
    ents = {}
    for st in _split_statements(m.group(1)):
        mm = re.match(r"#(\d+)\s*=\s*(.*)$", st, re.S)
        if not mm:
            raise StepError(f"bad statement: {st[:40]}")
        ents[int(mm.group(1))] = _Parser(mm.group(2)).entity()
    return ents


def _get(ents, ref, kind=None):
    for t, a in ents[ref[1]]:
        if kind is None or t == kind:
            return t, a
    raise StepError(f"#{ref[1]} is not {kind}")


def _xyz(ents, ref):
    _, cp = _get(ents, ref, "CARTESIAN_POINT")
    return np.asarray(cp[1], float)


def _dir(ents, ref):
    _, d = _get(ents, ref, "DIRECTION")
    v = np.asarray(d[1], float)
    return v / np.linalg.norm(v)


def _placement(ents, ref):
    _, a = _get(ents, ref, "AXIS2_PLACEMENT_3D")
    c = _xyz(ents, a[1])
    z = _dir(ents, a[2]) if a[2] != "$" else np.array([0, 0, 1.0])
    x = _dir(ents, a[3]) if a[3] != "$" else np.array([1.0, 0, 0])
    x = x - (x @ z) * z
    x /= np.linalg.norm(x)
    return c, z, x, np.cross(z, x)


def _edge_points(ents, ecref, sense, per_turn=4096):
    """Points along an oriented edge, start to end (both included)."""
    _, ec = _get(ents, ecref, "EDGE_CURVE")
    v1, v2, cref, same = ec[1], ec[2], ec[3], ec[4]
    _, vp = _get(ents, v1, "VERTEX_POINT")
    p = _xyz(ents, vp[1])
    _, vq = _get(ents, v2, "VERTEX_POINT")
    q = _xyz(ents, vq[1])
    t, ca = _get(ents, cref)
    if t == "LINE":
        pts = [p, q]
    elif t in ("CIRCLE", "ELLIPSE"):
        c, z, x, y = _placement(ents, ca[1])
        r = float(ca[2])
        r2 = float(ca[3]) if t == "ELLIPSE" else r
        a0 = math.atan2((p - c) @ y / r2, (p - c) @ x / r)
        a1 = math.atan2((q - c) @ y / r2, (q - c) @ x / r)
        closed = v1[1] == v2[1]
        d = (a1 - a0) % (2 * math.pi)
        if same == ".T.":
            d = 2 * math.pi if (closed or d < 1e-12) else d
        else:
            d = -2 * math.pi if (closed or d < 1e-12) else d - 2 * math.pi
        n = max(8, int(abs(d) / (2 * math.pi) * per_turn))
        pts = [c + r * math.cos(a0 + d * k / n) * x + r2 * math.sin(a0 + d * k / n) * y
               for k in range(n + 1)]
    else:
        raise StepError(f"unsupported curve {t}")
    return pts if sense == ".T." else pts[::-1]


def _cyl_integral(loops, c, z, x, y, r):
    """Surface integral of x.n over a cylindrical face, from its loops
    (Green's theorem in the angle/height plane, midpoint rule)."""
    cu, cv = c @ x, c @ y
    tot = 0.0
    for pts in loops:
        P = np.asarray(pts + pts[:1], float) - c
        th = np.arctan2(P @ y, P @ x)
        h = P @ z
        dth = (np.diff(th) + math.pi) % (2 * math.pi) - math.pi
        tm = th[:-1] + dth / 2
        hm = (h[:-1] + h[1:]) / 2
        g = cu * np.cos(tm) + cv * np.sin(tm) + r
        tot += float(np.sum(hm * g * dth))
    return -r * tot


def read_solids(text):
    """-> list of dicts: name, kind ('solid'|'shell'), faces, volume, edge_ok,
    units (str), surfaces ({'PLANE': n, 'CYLINDRICAL_SURFACE': n}), radii."""
    ents = parse(text)
    # units
    unit = None
    for lst in ents.values():
        for t, a in lst:
            if t == "SI_UNIT" and a and a[1] == ".METRE.":
                unit = {".MILLI.": "mm", ".CENTI.": "cm", "$": "m"}.get(a[0], "?")
    solids = []
    for eid, lst in ents.items():
        t, a = lst[0]
        if t == "MANIFOLD_SOLID_BREP":
            name, shell_ref, kind = a[0], a[1], "solid"
        elif t == "SHELL_BASED_SURFACE_MODEL":
            name, kind = a[0], "shell"
            shell_ref = a[1][0]
        else:
            continue
        _, sh = _get(ents, shell_ref)
        edge_uses = {}
        faces, vol, surfaces, radii = [], 0.0, {}, []
        for fref in sh[1]:
            _, fa = _get(ents, fref, "ADVANCED_FACE")
            loops = []
            for bref in fa[1]:
                _, ba = _get(ents, bref)
                _, el = _get(ents, ba[1], "EDGE_LOOP")
                pts = []
                for oref in el[1]:
                    _, oe = _get(ents, oref, "ORIENTED_EDGE")
                    ecref, sense = oe[3], oe[4]
                    pts.extend(_edge_points(ents, ecref, sense)[:-1])
                    edge_uses.setdefault(ecref[1], []).append(sense)
                if ba and ba[2] == ".F.":
                    pts.reverse()
                loops.append(pts)
            st, sa = _get(ents, fa[2])
            surfaces[st] = surfaces.get(st, 0) + 1
            if st == "PLANE":
                av = sum((newell(l) for l in loops), np.zeros(3))
                vol += av @ np.asarray(loops[0][0], float) / 3.0
            elif st == "CYLINDRICAL_SURFACE":
                c, z, x, y = _placement(ents, sa[1])
                r = float(sa[2])
                radii.append(r)
                for l in loops:            # every corner must sit on the surface
                    d = np.asarray(l) - c
                    d = d - np.outer(d @ z, z)
                    if np.abs(np.linalg.norm(d, axis=1) - r).max() > 1e-6 * max(r, 1):
                        raise StepError("edge off its cylinder")
                vol += _cyl_integral(loops, c, z, x, y, r) / 3.0
            else:
                raise StepError(f"unsupported surface {st}")
            faces.append(loops)
        edge_ok = all(sorted(u) == [".F.", ".T."] for u in edge_uses.values())
        solids.append({"name": name, "kind": kind, "faces": len(faces),
                       "volume": vol, "edge_ok": edge_ok, "units": unit,
                       "surfaces": surfaces, "radii": sorted(radii),
                       "face_loops": faces})
    return solids

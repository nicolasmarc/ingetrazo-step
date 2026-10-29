"""IGES 5.3 writer, from the same B-rep as the STEP writer.

Written from the public IGES 5.3 specification (US PRO/IPO-100-1996).
Two forms, chosen by ``mode``:

``"solid"`` (default)
    each closed shell is a MANIFOLD SOLID B-REP OBJECT (186) over a SHELL
    (514) of FACEs (510) bounded by LOOPs (508) that use one EDGE LIST (504)
    and one VERTEX LIST (502) per shell. Open shells, which are not solids,
    are written as trimmed surfaces (as in ``"surfaces"``).
``"surfaces"``
    every face is a TRIMMED SURFACE (144) whose boundaries are CURVEs ON a
    PARAMETRIC SURFACE (142) carrying a COMPOSITE CURVE (102) in model space,
    the oldest form, read by nearly every CAD program; the receiver sews the
    faces back into solids.

Surfaces: PLANE SURFACE (190) and RIGHT CIRCULAR CYLINDRICAL SURFACE (192),
parameterised (form 1). Curves: LINE (110), CIRCULAR ARC (100) and ellipse
CONIC ARC (104, form 1), the arcs placed by a TRANSFORMATION MATRIX (124)
since IGES draws them in their own XY plane, counterclockwise. Colours are
COLOR DEFINITIONs (314) and names NAME properties (406 form 15).
"""
import datetime
import numpy as np
from .writer import prepare_shells

UNIT_FLAGS = {"mm": (2, "MM"), "m": (6, "M"), "cm": (10, "CM")}


def _real(x):
    x = float(x)
    if x == 0 or abs(x) < 1e-300:
        return "0."
    s = f"{x:.15g}"
    if "e" in s:
        m, e = s.split("e")
        if "." not in m:
            m += "."
        return f"{m}E{int(e)}"
    return s if "." in s else s + "."


def _holl(text):
    raw = str(text).encode("ascii", "replace").decode("ascii")
    return f"{len(raw)}H{raw}"


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _perp(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(a, n)
    return x / np.linalg.norm(x)


class _Entity:
    __slots__ = ("type", "form", "params", "status", "color", "xform",
                 "label", "props")

    def __init__(self, etype, params, form=0, status="00010000", color=0,
                 xform=0, label="", props=()):
        self.type, self.form, self.params = etype, form, params
        self.status, self.color, self.xform = status, color, xform
        self.label, self.props = label, list(props)


class _File:
    """Entities in dependency order; ``add`` returns the DE pointer (the
    odd sequence number of the entity's first directory line)."""

    def __init__(self):
        self.ents = []

    def add(self, etype, params, **kw):
        self.ents.append(_Entity(etype, params, **kw))
        return 2 * len(self.ents) - 1

    def render(self, start, global_params):
        out = []
        s_lines = [start[i:i + 72] for i in range(0, max(len(start), 1), 72)]
        out += [f"{l:<72}S{i + 1:>7}" for i, l in enumerate(s_lines)]
        g_lines = _wrap(global_params, 72)
        out += [f"{l:<72}G{i + 1:>7}" for i, l in enumerate(g_lines)]
        d_out, p_out = [], []
        for i, e in enumerate(self.ents):
            de = 2 * i + 1
            toks = [str(e.type)] + [str(t) for t in e.params]
            if e.props:
                toks += ["0", str(len(e.props))] + [str(p) for p in e.props]
            lines = _wrap(toks, 64)
            first = len(p_out) + 1
            p_out += [f"{l:<64}{de:>8}P{first + k:>7}"
                      for k, l in enumerate(lines)]
            label = (e.label or "").encode("ascii", "replace").decode()[:8]
            d_out.append(f"{e.type:>8}{first:>8}{0:>8}{0:>8}{0:>8}{0:>8}"
                         f"{e.xform:>8}{0:>8}{e.status:>8}D{de:>7}")
            d_out.append(f"{e.type:>8}{0:>8}{e.color:>8}{len(lines):>8}"
                         f"{e.form:>8}{'':>8}{'':>8}{label:>8}{0:>8}"
                         f"D{de + 1:>7}")
        out += d_out + p_out
        n_s, n_g = len(s_lines), len(g_lines)
        t = f"S{n_s:>7}G{n_g:>7}D{len(d_out):>7}P{len(p_out):>7}"
        out.append(f"{t:<72}T{1:>7}")
        return "\n".join(out) + "\n"


def _wrap(tokens, width):
    """Tokens joined by ',' and ended by ';', cut between tokens into
    lines of at most ``width`` characters."""
    lines, cur = [], ""
    n = len(tokens)
    for i, tok in enumerate(tokens):
        piece = tok + (";" if i == n - 1 else ",")
        if cur and len(cur) + len(piece) > width:
            lines.append(cur)
            cur = ""
        cur += piece
    if cur:
        lines.append(cur)
    return lines


def _split_closed_ellipses(verts, brep):
    """A full ellipse (start = end) cut into two halves at the opposite
    point. IGES draws an ellipse in standard position, so a closed one has
    no start of its own: a reader (OpenCascade among them) runs it from the
    major axis, not from the seam vertex, and the face it bounds comes out
    wrong. Two half-ellipses between real vertices leave nothing to guess.
    Returns new ``(verts, brep)``; the input is left untouched."""
    from .brep import conic_param
    V = [tuple(map(float, v)) for v in verts]
    edges = dict(brep["edges"])
    halves = {}
    for k, e in brep["edges"].items():
        c = e["curve"]
        if c[0] != "ellipse" or e["start"] != e["end"]:
            continue
        _, ctr, ax, x, rx, ry, _ = c
        y = np.cross(ax, x)
        t = conic_param(e, np.asarray(V[e["start"]])) + np.pi
        V.append(tuple(np.asarray(ctr) + rx * np.cos(t) * np.asarray(x)
                       + ry * np.sin(t) * y))
        m = len(V) - 1
        ka, kb = k + ("a",), k + ("b",)
        edges.pop(k)
        edges[ka] = {"start": e["start"], "end": m, "curve": c}
        edges[kb] = {"start": m, "end": e["start"], "curve": c}
        halves[k] = (ka, kb)
    if not halves:
        return verts, brep
    faces = []
    for f in brep["faces"]:
        loops = []
        for loop in f["loops"]:
            out = []
            for k, fwd in loop:
                if k in halves:
                    ka, kb = halves[k]
                    out += [(ka, True), (kb, True)] if fwd else \
                        [(kb, False), (ka, False)]
                else:
                    out.append((k, fwd))
            loops.append(out)
        faces.append(dict(f, loops=loops))
    return V, dict(brep, edges=edges, faces=faces)


def write_iges(parts, path=None, scale=1000.0, unit="mm", author="",
               filename="model.igs", mode="solid", weld_tol=1e-6,
               cylinders=False, cyl_mode="soft", cyl_tol=1e-5,
               angle_max=25.0, repair_tol=None, simplify_tol=None,
               snap=1e-6, components=True):
    """Write ``parts`` (metres) as IGES text; same options as
    :func:`writer.write_step`, plus ``mode`` (``"solid"`` or
    ``"surfaces"``) and ``components``: each shell in its own named
    subfigure (308 + 408), so CAD shows one component per part under its
    name. Returns ``(text, report)``; writes ``path`` if given."""
    prepared, report = prepare_shells(
        parts, scale, unit, weld_tol, cylinders, cyl_mode, cyl_tol,
        angle_max, repair_tol, simplify_tol, snap)
    F = _File()
    big = [0.0]

    def pt(p):
        p = np.asarray(p, float) * scale
        big[0] = max(big[0], float(np.max(np.abs(p))))
        return p

    def point(p):
        q = pt(p)
        return F.add(116, [_real(c) for c in q])

    def direction(d):
        d = _unit(d)
        d = np.where(np.abs(d) < 1e-15, 0.0, d)
        return F.add(123, [_real(c) for c in d])

    def transform(x, y, z, origin):
        """124: local (x, y, z) frame placed at ``origin`` (metres)."""
        o = pt(origin)
        R = np.column_stack([x, y, z])
        vals = []
        for r in range(3):
            vals += [_real(R[r, 0]), _real(R[r, 1]), _real(R[r, 2]),
                     _real(o[r])]
        return F.add(124, vals)

    def curve(V, e, fwd):
        """Model-space curve of edge ``e`` run from its start to its end
        (``fwd``) or back: 110, or 100/104 placed by a 124."""
        s, t = (e["start"], e["end"]) if fwd else (e["end"], e["start"])
        c = e["curve"]
        if c[0] == "line":
            return F.add(110, [_real(v) for v in
                               list(pt(V[s])) + list(pt(V[t]))])
        same = c[-1] if fwd else not c[-1]
        if c[0] == "circle":
            _, ctr, ax, r, _ = c
            z = _unit(ax) if same else -_unit(ax)
            x = _unit(V[s] - ctr)
        else:
            _, ctr, ax, major, r1, r2, _ = c
            z = _unit(ax) if same else -_unit(ax)
            x = _unit(major)
        y = np.cross(z, x)
        xf = transform(x, y, z, ctr)
        R = np.column_stack([x, y, z])

        def local(p):
            q = R.T @ (np.asarray(p, float) - ctr) * scale
            return q[0], q[1]
        if c[0] == "circle":
            rr = r * scale
            x1, y1 = rr, 0.0
            if s == t:
                x2, y2 = x1, y1
            else:
                a, b = local(V[t])
                k = rr / max(np.hypot(a, b), 1e-300)
                x2, y2 = a * k, b * k
            return F.add(100, ["0.", "0.", "0.", _real(x1), _real(y1),
                               _real(x2), _real(y2)], xform=xf)
        a, b = r1 * scale, r2 * scale
        x1, y1 = local(V[s])
        x2, y2 = (x1, y1) if s == t else local(V[t])
        return F.add(104, [_real(b * b), "0.", _real(a * a), "0.", "0.",
                           _real(-(a * a) * (b * b)), "0.",
                           _real(x1), _real(y1), _real(x2), _real(y2)],
                     form=1, xform=xf)

    def surface(srf):
        if srf[0] == "plane":
            _, p0, n = srf
            return F.add(190, [point(p0), direction(n), direction(_perp(n))],
                         form=1)
        cyl = srf[1]
        return F.add(192, [point(cyl.center), direction(cyl.axis),
                           _real(cyl.radius * scale), direction(cyl.ref)],
                     form=1)

    def colour(rgb):
        if rgb is None:
            return 0
        vals = [_real(round(float(c) * 100.0, 4)) for c in rgb[:3]]
        return -F.add(314, vals, status="00000200")

    def name_prop(name):
        return F.add(406, ["1", _holl(name[:60])], form=15,
                     status="00000300")

    rep = {"solids": 0, "shells": 0, "surfaces": 0, "faces": 0}

    def component(name, members, col=0):
        """The part as a named component: a SUBFIGURE DEFINITION (308)
        holding its entities, placed once by a SINGULAR SUBFIGURE INSTANCE
        (408). CAD programs name an IGES component after the subfigure
        (SpaceClaim showed «Component1…» with the name only on the body);
        the members become physically dependent on the definition."""
        for de in members:
            F.ents[(de - 1) // 2].status = "00010000"
        sub = F.add(308, ["0", _holl(name[:60]), str(len(members))]
                    + [str(m) for m in members], status="00000200",
                    label=name)
        # the colour on the instance too: some readers (OpenCascade) take
        # a component's colour from it, not from the solid inside
        F.add(408, [str(sub), "0.", "0.", "0.", "1."], status="00000000",
              color=col, label=name, props=[name_prop(name)])

    def trimmed_faces(V, brep, col, name):
        """Each face as a 144 with model-space boundaries; their DEs."""
        out = []
        for f in brep["faces"]:
            srf = surface(f["surface"])
            bounds = []
            for loop in f["loops"]:
                segs = [curve(V, brep["edges"][k], fwd) for k, fwd in loop]
                comp = F.add(102, [str(len(segs))] + [str(c) for c in segs])
                bounds.append(F.add(142, ["0", str(srf), "0", str(comp),
                                          "2"]))
            # the face's side: a face against its surface normal keeps it
            # by having its outer loop run the other way, which the 142
            # curves already do (they follow the loop)
            out.append(F.add(144, [str(srf), "1", str(len(bounds) - 1)]
                             + [str(b) for b in bounds], status="00000000",
                             color=col, label=name, props=[name_prop(name)]))
            rep["surfaces"] += 1
            rep["faces"] += 1
        return out

    for part, shells in prepared:
        col_rgb = part.color
        for sh in shells:
            verts, brep = _split_closed_ellipses(sh["verts"], sh["brep"])
            V, name = np.asarray(verts, float), sh["name"]
            col = colour(col_rgb)
            if mode != "solid" or not sh["closed"]:
                members = trimmed_faces(V, brep, col, name)
                if components and members:
                    component(name, members, col)
                rep["shells"] += 1
                continue
            keys = list(brep["edges"])
            used = sorted({brep["edges"][k][w] for k in keys
                           for w in ("start", "end")})
            vidx = {vi: i + 1 for i, vi in enumerate(used)}
            vl = F.add(502, [str(len(used))] +
                       [_real(c) for vi in used for c in pt(V[vi])], form=1)
            curves = [curve(V, brep["edges"][k], True) for k in keys]
            el_params = [str(len(keys))]
            for k, cv in zip(keys, curves):
                e = brep["edges"][k]
                el_params += [str(cv), str(vl), str(vidx[e["start"]]),
                              str(vl), str(vidx[e["end"]])]
            el = F.add(504, el_params, form=1)
            kidx = {k: i + 1 for i, k in enumerate(keys)}
            faces = []
            for f in brep["faces"]:
                srf = surface(f["surface"])
                loops = []
                for loop in f["loops"]:
                    lp = [str(len(loop))]
                    for k, fwd in loop:
                        lp += ["0", str(el), str(kidx[k]), "1" if fwd else "0",
                               "0"]
                    loops.append(F.add(508, lp, form=1))
                faces.append((F.add(510, [str(srf), str(len(loops)), "1"]
                                    + [str(l) for l in loops], form=1),
                              f["sense"]))
            shell = F.add(514, [str(len(faces))] +
                          [v for fa, sense in faces
                           for v in (str(fa), "1" if sense else "0")],
                          form=1)
            solid = F.add(186, [str(shell), "1", "0"], status="00000000",
                          color=col, label=name, props=[name_prop(name)])
            if components:
                component(name, [solid], col)
            rep["solids"] += 1
            rep["faces"] += len(faces)

    flag, uname = UNIT_FLAGS[unit]
    now = datetime.datetime.now().strftime("%Y%m%d.%H%M%S")
    glob = ["1H,", "1H;", _holl("IngeTrazo"), _holl(filename),
            _holl("IngeTrazo ingetrazo-step"), _holl("IGES 5.3 writer"),
            "32", "38", "6", "308", "15", _holl(filename.rsplit(".", 1)[0]),
            "1.", str(flag), _holl(uname), "1", "1.", _holl(now),
            _real(weld_tol * scale), _real(max(big[0], 1.0)),
            _holl(author or ""), _holl(""), "11", "0", _holl(now)]
    text = F.render("IngeTrazo IGES export (ingetrazo-step)", glob)
    report.update(rep)
    report["format"] = "IGES"
    report["mode"] = mode
    if path:
        with open(path, "w", encoding="ascii", newline="\n") as fh:
            fh.write(text)
    return text, report

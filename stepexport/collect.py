"""Read the IngeTrazo scene into plain :class:`model.Part` objects.

Duck-typed on purpose (no Qt import): positions only need ``x() y() z()``,
so the tests drive it with small fakes. One part per top-level group or
component (its nested pieces are folded in, world coordinates), plus the
loose geometry as one more part, split later into its separate shells.
"""
from collections import Counter
from .model import Face, Part
from .texts import texts



def _xyz(p):
    return (float(p.x()), float(p.y()), float(p.z()))


def _color(faces):
    cols = []
    for f in faces:
        c = (getattr(f, "attrs", None) or {}).get("color")
        if c is not None and len(c) >= 3:
            cols.append(tuple(round(float(x), 4) for x in c[:3]))
    return Counter(cols).most_common(1)[0][0] if cols else None


def strip_triangles(face):
    """Triangles for a warped STRIP face (the chamfer or edge band of a
    curved stringer or handrail): its border is two long chains, each
    shared with one side face, joined by two short ends. The strip is cut
    rung by rung between the chains, always along the shorter diagonal —
    short, well-shaped triangles that follow the surface, instead of the
    long slivers a planar ear-clip makes across it. ``None`` when the face
    is not such a strip."""
    loop = list(getattr(face, "loop", []) or [])
    n = len(loop)
    if n < 6:
        return None

    def other(a, b):
        """The neighbour across edge a-b, as a key: stacked duplicates of
        one face (same corners) count as one neighbour."""
        for e in a.edges if hasattr(a, "edges") else ():
            if e.has(b) if hasattr(e, "has") else (e.v0 is b or e.v1 is b):
                keys = {frozenset(id(v) for v in g.loop)
                        for g in e.faces if g is not face}
                return next(iter(keys)) if len(keys) == 1 else None
        return None

    nb = [other(loop[k], loop[(k + 1) % n]) for k in range(n)]
    if any(x is None for x in nb):
        return None
    # runs of consecutive edges against the same neighbour face
    start = next((k for k in range(n) if nb[k] != nb[k - 1]), None)
    if start is None:
        return None
    runs, cur = [], [start]
    for k in range(1, n + 1):
        i = (start + k) % n
        if k < n and nb[i] == nb[cur[-1]]:
            cur.append(i)
        else:
            runs.append(cur)
            cur = [i]
    if len(runs) != 4:
        return None
    lens = [len(r) for r in runs]
    if not (min(lens[0], lens[2]) > max(lens[1], lens[3])
            or min(lens[1], lens[3]) > max(lens[0], lens[2])):
        return None
    if lens[1] > lens[0]:
        runs = runs[1:] + runs[:1]
    ra, rb = runs[0], runs[2]
    A = [loop[i] for i in ra] + [loop[(ra[-1] + 1) % n]]
    B = [loop[i] for i in rb] + [loop[(rb[-1] + 1) % n]]
    B = B[::-1]                         # run alongside A
    P = lambda v: _xyz(v.position)
    a, b = [P(v) for v in A], [P(v) for v in B]

    def d(p, q):
        return sum((x - y) ** 2 for x, y in zip(p, q))
    tris, i, j = [], 0, 0
    while i < len(a) - 1 or j < len(b) - 1:
        if j == len(b) - 1 or (i < len(a) - 1
                               and d(a[i + 1], b[j]) <= d(a[i], b[j + 1])):
            tris.append([a[i], a[i + 1], b[j]])
            i += 1
        else:
            tris.append([a[i], b[j + 1], b[j]])
            j += 1
    return tris


def faces_part(name, faces, edges=()):
    """A Part from mesh faces (``vertices`` / ``holes`` positions) and the
    soft edges among ``edges``."""
    from .check import PLANAR_TOL, _is_planar
    faces = list(faces)
    out = []
    for f in faces:
        outer = [_xyz(p) for p in f.vertices]
        holes = [[_xyz(p) for p in h] for h in (f.holes or [])]
        if len(outer) > 3 and hasattr(f, "triangulate") \
                and not _is_planar([outer] + holes, PLANAR_TOL):
            # a warped face (helical stringer, twisted strip): IngeTrazo's
            # own triangulation, the one it draws, rather than ours
            sid = id(f)
            tris = strip_triangles(f) if not holes else None
            if tris is None:
                tris = [[_xyz(p) for p in tri] for tri in f.triangulate()]
            for tri in tris:
                out.append(Face(tri, src=sid))
            continue
        out.append(Face(outer, holes))
    soft = [(_xyz(e.a), _xyz(e.b)) for e in edges if getattr(e, "soft", False)]
    return Part(name, out, _color(faces), soft or None)


def collect_parts(scene, selection_only=False, world_mesh=None):
    """-> list of Part. ``selection_only``: the selected groups, and the
    selected loose faces."""
    if world_mesh is None:                       # pragma: no cover - in app
        from core.group import world_mesh
    visible = getattr(scene, "entity_visible", lambda _e: True)
    sel = set(getattr(scene, "selection", ()) or ()) if selection_only else None
    parts, names = [], Counter()

    def unique(name):
        names[name] += 1
        return name if names[name] == 1 else f"{name} ({names[name]})"

    for g in getattr(scene, "groups", []):
        if not visible(g) or getattr(g, "billboard", False):
            continue
        if sel is not None and g not in sel:
            continue
        mesh = world_mesh(g)
        if not mesh.faces:
            continue
        parts.append(faces_part(unique(str(getattr(g, "name", "Groupe"))),
                                mesh.faces, mesh.edges))
    loose = getattr(scene, "loose_mesh", None)
    if loose is not None:
        fs = [f for f in loose.faces if visible(f)
              and (sel is None or f in sel)]
        if fs:
            keep = set(map(id, fs))
            es = [e for e in loose.edges
                  if any(id(f) in keep for f in getattr(e, "faces", ()))]
            parts.append(faces_part(unique(texts()["loose"]), fs, es))
    return parts


def _reason(T, text):
    table = T.get("reasons", {})
    base, _, rest = text.partition(" (")
    if text in table:
        return table[text]
    if base in table:                        # "unsupported topology (3 loops)"
        return f"{table[base]} ({rest}"
    return text


def format_report(rep, unit="mm", lang=None):
    """Plain-text summary of a :func:`writer.write_step` report, in the
    IngeTrazo language (English or French)."""
    T = texts(lang)
    u3 = {"mm": 1e-3, "cm": 1.0, "m": 1e6}[unit]      # -> cm3
    lines = [T["summary"].format(s=rep["solids"], o=rep["shells"], f=rep["faces"],
                                 c=rep.get("cylinders", 0))]
    for p in rep["parts"]:
        for sh in p["shells"]:
            state = T["solid"] if sh["closed"] else T["open"]
            line = f"• {sh['name']} — {state}, " + T["faces"].format(n=sh["faces"])
            if sh.get("facets", sh["faces"]) != sh["faces"]:
                line += T["instead"].format(n=sh["facets"])
            if sh["closed"]:
                line += f", {sh['volume'] * u3:.2f} cm³"
            lines.append(line)
            for c in sh.get("cylinders", []):
                what = (T["rod"] if c["full"] else T["round"]) if c["convex"] else \
                       (T["hole"] if c["full"] else T["fillet"])
                ang = "" if c["full"] else f", {c['span']:.0f}°"
                lines.append(f"    ◦ {what} Ø{2 * c['radius']:.2f} {unit}"
                             f" (R{c['radius']:.2f}{ang}, {c['facets']} {T['facets']})")
            for c in sh.get("rejected", []):
                lines.append(f"    ◦ {T['kept']}: R{c['radius']:.2f} {unit} — {_reason(T, c['reason'])}")
            for pb in sh["problems"]:
                lines.append(f"    ⚠ {_reason(T, pb)}")
    for n in rep["notes"]:
        for en, loc in T.get("notes", {}).items():
            n = n.replace(en, loc)
        lines.append(f"⚠ {n}")
    return "\n".join(lines)

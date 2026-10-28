"""ISO 10303-21 writer: B-rep solids (AP214 geometry subset) with planar
faces and, in V2, cylindrical faces bounded by lines, circles and ellipses.

Every part is its own PRODUCT, named after the part, with its own
ADVANCED_BREP_SHAPE_REPRESENTATION; several parts hang under an assembly
PRODUCT named after the file (NEXT_ASSEMBLY_USAGE_OCCURRENCE, identity
placement). CAD programs name components after products, not after the
solids inside them — a single "model" product made every part come back
as an anonymous body. The solids are named after their part too.
Parts that are not closed are written as shells (SHELL_BASED_SURFACE_MODEL
holding an OPEN_SHELL) and listed in the report.
"""
import datetime
import numpy as np
from .check import analyse, soft_index_pairs
from .surfaces import find_cylinders
from .brep import build_brep, brep_volume
from .simplify import simplify_shell


def _real(x):
    s = f"{float(x):.12g}"
    if "e" in s:
        m, e = s.split("e")
        if "." not in m:
            m += "."
        return f"{m}E{int(e):+03d}".replace("+", "+")
    return s if "." in s else s + "."


def _str(s):
    out = []
    for ch in str(s):
        if ch == "'":
            out.append("''")
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append(f"\\X2\\{ord(ch):04X}\\X0\\")
    return "'" + "".join(out) + "'"


class _Emit:
    def __init__(self):
        self.lines = []

    def add(self, text):
        self.lines.append(text)
        return len(self.lines)

    def ref(self, text):
        return f"#{self.add(text)}"


def _unit(a):
    a = np.asarray(a, float)
    return a / np.linalg.norm(a)


def _perp(n):
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(a, n)
    return x / np.linalg.norm(x)


def _snap_part(part, q):
    """Round every coordinate to the grid ``q`` (metres; 1e-6 = 0.001 mm).

    IngeTrazo keeps positions in single precision: a tread drawn 44 mm thick
    at two metres from the origin comes back 44.00003 mm, a 16 mm baluster
    15.99999 mm. Those few hundred-thousandths are noise, not design, and a
    CAD program shows them in every measurement; back on the micrometre grid
    the file says 44 and 16 again."""
    from .model import Face, Part

    def snap1(c):
        g = round(c / q) * q
        # only values that ARE grid values blurred by single precision move
        # (float32 rounds to 6e-8 relative); a coordinate the
        # designer did not put on the grid (a slanted edge's end) keeps its
        # own value instead of being shifted by up to half a grid step
        return g if abs(c - g) <= max(6e-8 * abs(c), 1e-9) else c
    r = lambda p: tuple(snap1(c) for c in p)                   # noqa: E731
    faces = [Face([r(p) for p in f.outer], [[r(p) for p in h] for h in f.holes],
                  getattr(f, "src", None)) for f in part.faces]
    soft = ([(r(a), r(b)) for a, b in part.soft_edges]
            if part.soft_edges is not None else None)
    return Part(part.name, faces, part.color, soft)


def _snap_cylinder(cyl, q):
    """The fitted cylinder on the same grid: radius and axis point rounded,
    an axis within 1e-9 of a world axis made exact. Its facets' corners
    already sit on the grid, so the fit only differs from round values by
    float noise."""
    from .surfaces import Cylinder
    a = np.where(np.abs(cyl.axis) < 1e-9, 0.0, cyl.axis)
    a = a / np.linalg.norm(a)
    ref = cyl.ref - (cyl.ref @ a) * a
    ref = np.where(np.abs(ref) < 1e-9, 0.0, ref)
    ref = ref / np.linalg.norm(ref)
    c = np.asarray(cyl.center, float)
    g = np.round(c / q) * q
    # the axis point moves only when it is a grid value blurred by the
    # fit; an axis the designer placed off the grid stays where it is
    c = np.where(np.abs(c - g) <= np.maximum(6e-8 * np.abs(c), 1e-9), g, c)
    return Cylinder(c, a, max(round(cyl.radius / q) * q, q), ref)


def write_step(parts, path=None, scale=1000.0, unit="mm", author="",
               filename="model.stp", weld_tol=1e-6, cylinders=False,
               cyl_mode="soft", cyl_tol=1e-5, angle_max=25.0, repair_tol=None,
               simplify_tol=None, snap=1e-6):
    """Write ``parts`` (list of :class:`model.Part`, coordinates in metres) to
    STEP text. ``scale`` converts input units to the declared ``unit``.

    ``cylinders`` (V2): recognise faceted cylinders in closed parts and write
    them as true CYLINDRICAL_SURFACE faces with CIRCLE edges. ``cyl_mode``:
    ``"soft"`` uses the part's soft edges (falls back to geometry when the part
    has none), ``"geometry"`` uses dihedral angles below ``angle_max`` degrees.
    ``cyl_tol``: fit tolerance, input units.
    ``repair_tol``: when set (input units), T-junctions are stitched and
    small planar holes capped before the closure check.
    ``simplify_tol``: when set (input units), neighbouring facets within
    that distance of one plane are merged (curved surfaces sampled too
    finely); recognised cylinders are left alone.
    Returns ``(text, report)``; writes the file when ``path`` is given."""
    E = _Emit()
    report = {"parts": [], "solids": 0, "shells": 0, "faces": 0,
              "cylinders": 0, "notes": []}
    now = datetime.datetime.now().replace(microsecond=0).isoformat()

    # --- units / context ---------------------------------------------------
    app = E.ref("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    E.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
    pctx = E.ref(f"PRODUCT_CONTEXT('',{app},'mechanical')")
    prefix = {"mm": ".MILLI.", "m": "$", "cm": ".CENTI."}[unit]
    ulen = E.ref(f"( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT({prefix},.METRE.) )")
    uang = E.ref("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    usol = E.ref("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = E.ref(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),{ulen},'distance_accuracy_value','confusion accuracy')")
    ctx = E.ref(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) "
                f"GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({unc})) "
                f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({ulen},{uang},{usol})) "
                f"REPRESENTATION_CONTEXT('Context3D','3D') )")
    origin = E.ref("CARTESIAN_POINT('',(0.,0.,0.))")
    dz = E.ref("DIRECTION('',(0.,0.,1.))")
    dx = E.ref("DIRECTION('',(1.,0.,0.))")
    world = E.ref(f"AXIS2_PLACEMENT_3D('',{origin},{dz},{dx})")

    styled = []
    part_items = []                      # (part name, [solid refs]) per part
    dir_cache, pt_cache = {}, {}

    def point(p):
        k = tuple(p)
        if k not in pt_cache:
            pt_cache[k] = E.ref("CARTESIAN_POINT('',(%s))" %
                                ",".join(_real(c * scale) for c in p))
        return pt_cache[k]

    def direction(d):
        k = tuple(round(float(c), 12) for c in d)
        if k not in dir_cache:
            dir_cache[k] = E.ref("DIRECTION('',(%s))" % ",".join(_real(c) for c in k))
        return dir_cache[k]

    if snap:
        parts = [_snap_part(p, snap) for p in parts]
    for part in parts:
        verts, shells, notes = analyse(part, weld_tol, repair_tol)
        report["notes"].extend(f"{part.name}: {n}" for n in sorted(set(notes)))
        soft = soft_index_pairs(part, verts, weld_tol) if cylinders else None
        info = {"name": part.name, "shells": []}
        items, item_names = [], []
        for si, sh in enumerate(shells):
            name = part.name if len(shells) == 1 else f"{part.name} ({si + 1})"
            regions = []
            if cylinders and sh["closed"]:
                if cyl_mode == "soft" and soft:
                    regions = find_cylinders(verts, sh["faces"], soft, mode="soft",
                                             tol=cyl_tol, angle_max=angle_max)
                # geometry on whatever the soft edges did not cover: a model
                # imported from elsewhere often softens only a few seams
                used = {fi for r in regions for fi in r["faces"]}
                for r in find_cylinders(verts, sh["faces"], None, mode="geometry",
                                        tol=cyl_tol, angle_max=angle_max):
                    if not used.intersection(r["faces"]):
                        regions.append(r)
            if snap:
                for r in regions:
                    r["cyl"] = cyl = _snap_cylinder(r["cyl"], snap)
                    # its corners onto the round cylinder (they moved a few
                    # tenths of a micrometre when snapped to the grid)
                    for vi in {i for fi in r["faces"] for l in sh["faces"][fi] for i in l}:
                        p = np.asarray(verts[vi], float)
                        d = p - cyl.center
                        h = d @ cyl.axis
                        rad = d - h * cyl.axis
                        n = np.linalg.norm(rad)
                        if n > 0:
                            verts[vi] = tuple(cyl.center + h * cyl.axis + rad * (cyl.radius / n))
            shell_faces = sh["faces"]
            simp = None
            if simplify_tol and sh["closed"]:
                keep = {fi for r in regions for fi in r["faces"]}
                shell_faces, imap, simp = simplify_shell(
                    verts, shell_faces, simplify_tol, keep)
                for r in regions:
                    r["faces"] = [imap[fi] for fi in r["faces"]]
                if simp["merged"]:
                    report["notes"].append(
                        f"{name}: {simp['merged']} facet(s) merged "
                        f"(max {simp['max_dev'] * scale:.3f} {unit})")
            brep = build_brep(verts, shell_faces, regions, tol=cyl_tol)
            cyls = [dict(c, radius=c["radius"] * scale) for c in brep["cylinders"]]
            rej = [dict(c, radius=c["radius"] * scale) for c in brep["rejected"]]
            volume = sh["volume"] * scale ** 3
            if brep["cylinders"] or (simp and simp["merged"]):
                volume = brep_volume(verts, brep) * scale ** 3
            info["shells"].append({"name": name, "closed": sh["closed"],
                                   "volume": volume,
                                   "faces": len(brep["faces"]),
                                   "facets": len(sh["faces"]),
                                   "cylinders": cyls, "rejected": rej,
                                   "problems": sh["problems"]})
            report["cylinders"] += len(cyls)
            vpt, eref = {}, {}

            def vertex(i):
                if i not in vpt:
                    vpt[i] = E.ref(f"VERTEX_POINT('',{point(verts[i])})")
                return vpt[i]

            def edge(k):
                if k not in eref:
                    e = brep["edges"][k]
                    a, b = e["start"], e["end"]
                    if e["curve"][0] == "line":
                        p0, p1 = np.array(verts[a]), np.array(verts[b])
                        d = p1 - p0
                        ln = float(np.linalg.norm(d)) * scale
                        vec = E.ref(f"VECTOR('',{direction(d / np.linalg.norm(d))},{_real(ln)})")
                        geo = E.ref(f"LINE('',{point(p0)},{vec})")
                        same = True
                    elif e["curve"][0] == "circle":
                        _, c, ax, r, same = e["curve"]
                        ref = _unit(np.asarray(verts[a]) - c)
                        pl = E.ref(f"AXIS2_PLACEMENT_3D('',{point(c)},"
                                   f"{direction(ax)},{direction(ref)})")
                        geo = E.ref(f"CIRCLE('',{pl},{_real(r * scale)})")
                    else:                     # cylinder cut at an angle
                        _, c, ax, major, r1, r2, same = e["curve"]
                        pl = E.ref(f"AXIS2_PLACEMENT_3D('',{point(c)},"
                                   f"{direction(ax)},{direction(major)})")
                        geo = E.ref(f"ELLIPSE('',{pl},{_real(r1 * scale)},"
                                    f"{_real(r2 * scale)})")
                    eref[k] = E.ref(f"EDGE_CURVE('',{vertex(a)},{vertex(b)},"
                                    f"{geo},{'.T.' if same else '.F.'})")
                return eref[k]

            face_refs = []
            for f in brep["faces"]:
                bounds = []
                for li, loop in enumerate(f["loops"]):
                    oes = [E.ref(f"ORIENTED_EDGE('',*,*,{edge(k)},{'.T.' if fwd else '.F.'})")
                           for k, fwd in loop]
                    el = E.ref(f"EDGE_LOOP('',({','.join(oes)}))")
                    cls = "FACE_OUTER_BOUND" if li == 0 else "FACE_BOUND"
                    bounds.append(E.ref(f"{cls}('',{el},.T.)"))
                srf = f["surface"]
                if srf[0] == "plane":
                    _, p0, n = srf
                    ax = E.ref(f"AXIS2_PLACEMENT_3D('',{point(p0)},"
                               f"{direction(n)},{direction(_perp(n))})")
                    geo = E.ref(f"PLANE('',{ax})")
                else:
                    cyl = srf[1]
                    ax = E.ref(f"AXIS2_PLACEMENT_3D('',{point(cyl.center)},"
                               f"{direction(cyl.axis)},{direction(cyl.ref)})")
                    geo = E.ref(f"CYLINDRICAL_SURFACE('',{ax},{_real(cyl.radius * scale)})")
                sense = ".T." if f["sense"] else ".F."
                face_refs.append(E.ref(f"ADVANCED_FACE('',({','.join(bounds)}),{geo},{sense})"))
            report["faces"] += len(face_refs)
            if sh["closed"]:
                shell = E.ref(f"CLOSED_SHELL('',({','.join(face_refs)}))")
                solid = E.ref(f"MANIFOLD_SOLID_BREP({_str(name)},{shell})")
                report["solids"] += 1
            else:
                shell = E.ref(f"OPEN_SHELL('',({','.join(face_refs)}))")
                solid = E.ref(f"SHELL_BASED_SURFACE_MODEL({_str(name)},({shell}))")
                report["shells"] += 1
            items.append(solid)
            item_names.append(name)
            if part.color:
                r, g, b = part.color[:3]
                c = E.ref(f"COLOUR_RGB('',{_real(r)},{_real(g)},{_real(b)})")
                fa = E.ref(f"FILL_AREA_STYLE_COLOUR('',{c})")
                fas = E.ref(f"FILL_AREA_STYLE('',({fa}))")
                sfa = E.ref(f"SURFACE_STYLE_FILL_AREA({fas})")
                ss = E.ref(f"SURFACE_SIDE_STYLE('',({sfa}))")
                ssu = E.ref(f"SURFACE_STYLE_USAGE(.BOTH.,{ss})")
                psa = E.ref(f"PRESENTATION_STYLE_ASSIGNMENT(({ssu}))")
                styled.append(E.ref(f"STYLED_ITEM('color',({psa}),{solid})"))
        report["parts"].append(info)
        # a group holding several separate solids (a DXF layer of loose
        # faces: every baluster, tread and rail of a stair in one group) is
        # several parts: each body becomes its own component in CAD,
        # "Group (1)", "Group (2)"..., instead of one component of 180 bodies
        if len(items) > 1:
            part_items.extend((nm, [it]) for nm, it in zip(item_names, items))
        elif items:
            part_items.append((part.name, items))

    # --- products: one per part, under an assembly when there are several --
    pdc = E.ref(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")

    def product(name, rep_cls, items):
        nm = _str(name)
        prod = E.ref(f"PRODUCT({nm},{nm},'',({pctx}))")
        pdf = E.ref(f"PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE('','',{prod},.NOT_KNOWN.)")
        pd = E.ref(f"PRODUCT_DEFINITION('design','',{pdf},{pdc})")
        pds = E.ref(f"PRODUCT_DEFINITION_SHAPE('','',{pd})")
        rep = E.ref(f"{rep_cls}({nm},({','.join([world] + items)}),{ctx})")
        E.add(f"SHAPE_DEFINITION_REPRESENTATION({pds},{rep})")
        return pd, rep

    if len(part_items) == 1:
        product(part_items[0][0], "ADVANCED_BREP_SHAPE_REPRESENTATION", part_items[0][1])
    else:
        root = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        root = root.rsplit(".", 1)[0] if "." in root else root
        apd, arep = product(root or "model", "SHAPE_REPRESENTATION", [])
        idt = E.ref(f"ITEM_DEFINED_TRANSFORMATION('','',{world},{world})")
        for k, (name, items) in enumerate(part_items):
            pd, rep = product(name, "ADVANCED_BREP_SHAPE_REPRESENTATION", items)
            nm = _str(name)
            nauo = E.ref(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{k + 1}',{nm},'',{apd},{pd},$)")
            npds = E.ref(f"PRODUCT_DEFINITION_SHAPE({nm},'',{nauo})")
            rr = E.ref(f"( REPRESENTATION_RELATIONSHIP('','',{rep},{arep}) "
                       f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION({idt}) "
                       f"SHAPE_REPRESENTATION_RELATIONSHIP() )")
            E.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION({rr},{npds})")
    if styled:
        E.add(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({','.join(styled)}),{ctx})")

    head = ("ISO-10303-21;\nHEADER;\n"
            "FILE_DESCRIPTION(('IngeTrazo STEP export'),'2;1');\n"
            f"FILE_NAME({_str(filename)},{_str(now)},({_str(author)}),(''),"
            "'ingetrazo-step','IngeTrazo','');\n"
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\n"
            "ENDSEC;\nDATA;\n")
    body = "".join(f"#{i + 1}={ln};\n" for i, ln in enumerate(E.lines))
    text = head + body + "ENDSEC;\nEND-ISO-10303-21;\n"
    if path:
        with open(path, "w", encoding="ascii", newline="\n") as fh:
            fh.write(text)
    return text, report

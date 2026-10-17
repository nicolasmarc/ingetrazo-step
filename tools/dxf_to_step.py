"""Convert 3DFACE DXF files (one block per part) to STEP solids.

    python tools/dxf_to_step.py file.dxf [more.dxf ...] [--out DIR]

Each block holding 3DFACEs becomes one named solid (its block name), in
world coordinates (nested INSERTs resolved). Triangles lying in one plane are
merged into polygon faces, then the STEP writer checks closure and
orientation and recognises cylinders (geometry mode: no soft edges in a DXF).
DXF units are taken as millimetres. Needs ``ezdxf`` (a tool, not part of the
IngeTrazo extension). Prints a report per file.
"""
import argparse, os, sys
from collections import OrderedDict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from stepexport.coplanar import merge_coplanar      # noqa: E402
from stepexport.model import Face, Part              # noqa: E402
from stepexport.writer import write_step             # noqa: E402
from stepexport.collect import format_report         # noqa: E402
from stepexport.check import analyse                  # noqa: E402


def face_loops(e):
    v = [tuple(e.dxf.vtx0), tuple(e.dxf.vtx1), tuple(e.dxf.vtx2), tuple(e.dxf.vtx3)]
    out = [v[0]]
    for p in v[1:]:
        if max(abs(a - b) for a, b in zip(p, out[-1])) > 1e-9:
            out.append(p)
    if len(out) > 1 and max(abs(a - b) for a, b in zip(out[0], out[-1])) < 1e-9:
        out.pop()
    return out


def collect(doc):
    """-> OrderedDict name -> list of point loops, world coordinates."""
    parts = OrderedDict()

    def walk(entities, owner):
        for e in entities:
            t = e.dxftype()
            if t == "INSERT":
                walk(e.virtual_entities(), e.dxf.name)
            elif t == "3DFACE":
                loop = face_loops(e)
                if len(loop) >= 3:
                    parts.setdefault(owner, []).append(loop)
    walk(doc.modelspace(), "Modelspace")
    return parts


def convert(path, out_dir=None, unit="mm"):
    import ezdxf
    doc = ezdxf.readfile(path)
    parts, fixes = [], []
    for name, loops in collect(doc).items():
        best = None
        for merge in (True, False):
            st = {}
            faces, verts = merge_coplanar(loops, weld_tol=5e-3, dist_tol=1e-6,
                                          repair=0.25, stats=st, merge=merge)
            part = Part(name, [Face([verts[i] for i in f[0]],
                                    [[verts[i] for i in h] for h in f[1:]])
                               for f in faces])
            _, shells, _ = analyse(part, 1e-3)
            closed = all(s["closed"] and s["volume"] > 1.0 for s in shells)
            if best is None or closed:
                best = (part, st, merge)
            if closed:
                break
        part, st, merged = best
        parts.append(part)
        note = [] if merged else ["faces planes non fusionnées"]
        if any(st.values()) or note:
            fixes.append(f"{name}: {st.get('zipped', 0)} couture(s) ≤ 0,25 mm, "
                         f"{st.get('flat', 0)} triangle(s) plat(s) retiré(s), "
                         f"{st.get('t_junctions', 0)} jonction(s) en T recousue(s), "
                         f"{st.get('caps', 0)} trou(s) plan(s) bouché(s)"
                         + "".join(", " + n for n in note))
    base = os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(out_dir or os.path.dirname(path), base + ".stp")
    _, rep = write_step(parts, path=out, scale=1.0, unit=unit, filename=base + ".stp",
                        weld_tol=1e-3, cylinders=True, cyl_mode="geometry",
                        cyl_tol=0.02, angle_max=20.0)
    rep["fixes"] = fixes
    return out, rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--lang", default="fr")
    a = ap.parse_args()
    for f in a.files:
        out, rep = convert(f, a.out)
        print(f"== {os.path.basename(f)} -> {out}")
        print(format_report(rep, "mm", a.lang))
        for line in rep["fixes"]:
            print("  réparé —", line)
        print()


if __name__ == "__main__":
    main()

"""Command line: DXF -> STEP with the extension's engine, no IngeTrazo needed.

    python -m stepexport FILE.dxf        (or: python path/to/stepexport FILE.dxf)
    python -m stepexport FILE.dxf [MORE.dxf | FOLDER ...] [-o OUT_DIR]
                         [--unit mm|cm|m] [--simplify 0.1 | --no-simplify]
                         [--no-cylinders] [--no-colours] [--lang fr|en]

Each DXF becomes a .stp next to it (or in OUT_DIR); a folder converts every
DXF it holds. Needs Python 3 with numpy and ezdxf, nothing else (the
``stepexport`` folder, as installed in IngeTrazo's plugins, is the whole
program). Exit code 0 when every file was written, 1 otherwise.
"""
import argparse
import os
import sys
import time

if not __package__:                  # run as ``python path/to/stepexport``
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "stepexport"       # noqa: A001 - relative imports below
    import stepexport                # noqa: F401

UNITS = {"mm": 1000.0, "cm": 100.0, "m": 1.0}


def targets(args):
    out = []
    for a in args:
        if os.path.isdir(a):
            out += sorted(os.path.join(a, f) for f in os.listdir(a)
                          if f.lower().endswith(".dxf"))
        elif a.lower().endswith(".dxf") and os.path.isfile(a):
            out.append(a)
    return out


def convert(src, out_dir=None, unit="mm", simplify_mm=0.1, cylinders=True,
            colours=True, lang="fr"):
    """Convert one DXF; returns (stp path, report text)."""
    from .dxfdirect import read_parts
    from .writer import write_step
    from .collect import format_report
    t0 = time.time()
    parts, info = read_parts(src)
    if not colours:
        for p in parts:
            p.color = None
    base = os.path.splitext(os.path.basename(src))[0] + ".stp"
    path = os.path.join(out_dir or os.path.dirname(os.path.abspath(src)), base)
    _, rep = write_step(parts, path=path, scale=UNITS[unit], unit=unit,
                        filename=base, cylinders=cylinders, cyl_mode="soft",
                        repair_tol=1e-5,
                        simplify_tol=simplify_mm / 1000.0 if simplify_mm else None,
                        snap=None)
    units = ("unités de l'en-tête" if lang == "fr" else "units from the header") \
        if info["declared"] else \
        (f"pas d'unités : {'mm' if info['scale'] == 0.001 else 'm'} d'après la taille"
         if lang == "fr" else
         f"no units: {'mm' if info['scale'] == 0.001 else 'm'} from the size")
    head = f"{os.path.basename(src)} -> {path}  ({time.time() - t0:.1f} s, {units})"
    return path, head + "\n" + format_report(rep, unit, lang)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m stepexport",
                                 description="DXF 3D -> STEP (exact sizes)")
    ap.add_argument("inputs", nargs="+", help=".dxf files or folders")
    ap.add_argument("-o", "--out", help="output folder (default: next to each DXF)")
    ap.add_argument("--unit", choices=sorted(UNITS), default="mm")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--simplify", type=float, default=0.1, metavar="MM",
                   help="merge facets within this tolerance (default 0.1 mm)")
    g.add_argument("--no-simplify", action="store_true")
    ap.add_argument("--no-cylinders", action="store_true")
    ap.add_argument("--no-colours", action="store_true")
    ap.add_argument("--lang", choices=("fr", "en"), default="fr")
    a = ap.parse_args(argv)
    files = targets(a.inputs)
    if not files:
        print("Aucun fichier .dxf." if a.lang == "fr" else "No .dxf file.", file=sys.stderr)
        return 1
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    ok = True
    for f in files:
        try:
            _, text = convert(f, a.out, a.unit, None if a.no_simplify else a.simplify,
                              not a.no_cylinders, not a.no_colours, a.lang)
            print(text)
        except Exception as exc:                 # one bad file, carry on
            ok = False
            print(f"{os.path.basename(f)} : {'ÉCHEC' if a.lang == 'fr' else 'FAILED'} "
                  f"— {type(exc).__name__}: {exc}")
        print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

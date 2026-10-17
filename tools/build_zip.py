"""Build dist/stepexport-<version>.zip (deterministic) and print its sha256.

The zip extracts to ``plugins/stepexport/__init__.py`` (no extra folder).
Usage: python tools/build_zip.py
"""
import hashlib, os, re, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = "stepexport"


def main():
    src = open(os.path.join(ROOT, PKG, "__init__.py"), encoding="utf-8").read()
    version = re.search(r'__version__ = "([^"]+)"', src).group(1)
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", f"{PKG}-{version}.zip")
    files = sorted(f for f in os.listdir(os.path.join(ROOT, PKG)) if f.endswith(".py"))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in files + ["../LICENSE"]:
            path = os.path.normpath(os.path.join(ROOT, PKG, name))
            arc = f"{PKG}/{os.path.basename(path)}"
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as fh:
                z.writestr(info, fh.read())
    digest = hashlib.sha256(open(out, "rb").read()).hexdigest()
    print(out)
    print("sha256 =", digest)


if __name__ == "__main__":
    main()

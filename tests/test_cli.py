"""Command line (python path/to/stepexport FILE.dxf): no IngeTrazo, a .stp
next to the DXF, a folder converted whole, a bad file reported."""
import os, subprocess, sys, tempfile
import ezdxf

PKG = os.path.join(os.path.dirname(__file__), "..", "stepexport")
BOX = [(0, 0, 0), (900, 0, 0), (900, 250, 0), (0, 250, 0),
       (0, 0, 40), (900, 0, 40), (900, 250, 40), (0, 250, 40)]
F = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def run(*args):
    return subprocess.run([sys.executable, PKG, *args], capture_output=True, text=True)


def test_a_folder_of_dxf_becomes_stp_files():
    d = tempfile.mkdtemp()
    for name in ("a", "b"):
        doc = ezdxf.new("R2010"); doc.header["$INSUNITS"] = 4
        b = doc.blocks.new("Marche")
        pf = b.add_polyface(); pf.append_faces([[BOX[i] for i in f] for f in F])
        doc.modelspace().add_blockref("Marche", (0, 0, 0))
        doc.saveas(os.path.join(d, name + ".dxf"))
    open(os.path.join(d, "c.dxf"), "w").write("not a dxf")
    r = run(d, "--lang", "en")
    assert os.path.isfile(os.path.join(d, "a.stp")) and os.path.isfile(os.path.join(d, "b.stp"))
    assert "1 solid(s), 0 open" in r.stdout and "c.dxf : FAILED" in r.stdout, r.stdout + r.stderr
    assert r.returncode == 1                      # one file failed
    r = run(os.path.join(d, "a.dxf"), "-o", os.path.join(d, "out"))
    assert r.returncode == 0 and os.path.isfile(os.path.join(d, "out", "a.stp")), r.stderr


if __name__ == "__main__":
    for k, fn in list(globals().items()):
        if k.startswith("test_"):
            fn(); print("ok", k)

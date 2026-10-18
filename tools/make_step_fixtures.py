"""Write the STEP test files (tests/data/*.step) with an independent CAD
kernel (CadQuery / OpenCascade), so the reader is checked against files it
did not write. Only needed to regenerate the fixtures; the tests read the
committed files.

    pip install cadquery && python tools/make_step_fixtures.py
"""
import json, math
from pathlib import Path
import cadquery as cq

OUT = Path(__file__).resolve().parents[1] / "tests" / "data"
OUT.mkdir(parents=True, exist_ok=True)
facts = {}

# 1. a plain block (planar faces only), mm
box = cq.Workplane("XY").box(40, 20, 10)
cq.exporters.export(box, str(OUT / "bloc.step"))
facts["bloc"] = {"volume": 40 * 20 * 10, "bbox": [[-20, -10, -5], [20, 10, 5]]}

# 2. a plate with a hole and a cylinder boss: planes + cylinders + circles
part = (cq.Workplane("XY").box(60, 40, 8).faces(">Z").workplane()
        .hole(12).faces(">Z").workplane().center(20, 0).circle(6).extrude(15))
cq.exporters.export(part, str(OUT / "platine.step"))
bb = part.val().BoundingBox()
facts["platine"] = {"volume": part.val().Volume(),
                    "bbox": [[bb.xmin, bb.ymin, bb.zmin], [bb.xmax, bb.ymax, bb.zmax]]}

# 3. a spur-gear-like extrusion (polyline teeth) + a revolved pulley (torus-ish)
pts = []
z, ra, rf = 20, 22.0, 18.0
for k in range(z):
    a = 2 * math.pi * k / z
    for da, r in ((-0.35, rf), (-0.15, ra), (0.15, ra), (0.35, rf)):
        t = a + da * 2 * math.pi / z
        pts.append((r * math.cos(t), r * math.sin(t)))
gear = cq.Workplane("XY").polyline(pts).close().extrude(6).faces(">Z").workplane().hole(8)
cq.exporters.export(gear, str(OUT / "pignon.step"))
facts["pignon"] = {"volume": gear.val().Volume()}

# 4. an assembly: base + two copies of a lever, placed and turned
base = cq.Workplane("XY").box(100, 30, 5)
lever = cq.Workplane("XY").box(50, 8, 4).faces(">Z").workplane().center(-20, 0).hole(4)
asm = (cq.Assembly(name="mecanisme")
       .add(base, name="socle", color=cq.Color(0.6, 0.6, 0.6))
       .add(lever, name="levier_g", loc=cq.Location(cq.Vector(-25, 0, 10), cq.Vector(0, 0, 1), 30))
       .add(lever, name="levier_d", loc=cq.Location(cq.Vector(25, 0, 10), cq.Vector(0, 0, 1), -45)))
asm.save(str(OUT / "assemblage.step"))
facts["assemblage"] = {
    "parts": {"socle": {"volume": 100 * 30 * 5, "center": [0, 0, 0]},
              "levier_g": {"volume": lever.val().Volume(), "center": [-25, 0, 10], "angle": 30},
              "levier_d": {"volume": lever.val().Volume(), "center": [25, 0, 10], "angle": -45}},
    "lever_center_local": list(lever.val().Center().toTuple())}
# 5. a roller: cylinder with filleted (torus) and chamfered (cone) edges,
#    a spherical dome on top
roller = (cq.Workplane("XY").circle(15).extrude(20).faces(">Z").edges().fillet(4)
          .faces("<Z").edges().chamfer(2))
roller = roller.union(cq.Workplane("XY").workplane(offset=20).sphere(6))
cq.exporters.export(roller, str(OUT / "galet.step"))
facts["galet"] = {"volume": roller.val().Volume()}

# 6. a loft between a circle and a rectangle (B-spline faces)
loft = (cq.Workplane("XY").rect(30, 20).workplane(offset=25).circle(9).loft())
cq.exporters.export(loft, str(OUT / "raccord.step"))
facts["raccord"] = {"volume": loft.val().Volume()}

(OUT / "facts.json").write_text(json.dumps(facts, indent=1))
print("written:", sorted(p.name for p in OUT.iterdir()))

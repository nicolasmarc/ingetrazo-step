# Changelog

## 0.4.0 — 2026-10-18
- **Import STEP**: Extensions ▸ Import STEP…, the panel's Import… button, or opening a
  `.stp` / `.step` in IngeTrazo (file opener). One group per part, named and coloured, placed
  as in the assembly, one undo step, left selected.
- `stepread.py`: full reader (product tree, placements, units, colours; planes, cylinders,
  cones, spheres, tori, extrusions, revolutions, B-splines meshed to a tolerance, seams and
  poles handled, closed parts watertight). Several named solids in one product become
  several parts. Same file as in the Motion extension.
- Tests against files written by an independent kernel (OpenCascade via CadQuery) and an
  export -> import round trip.

## 0.3.0 — 2026-10-17
- Repairs before writing: stacked duplicate faces and stray overlapping faces dropped,
  T-junctions stitched, small planar holes capped (merged into their coplanar neighbour).
- Planarity checked against an absolute 5 µm tolerance (float noise no longer splits flat
  faces into slivers); planes fitted on all corners.
- Warped strip faces (curved stringer and handrail edges) triangulated rung by rung.
- Cylinders: soft edges first, then geometry on the rest.
- Optional "Simplify curved surfaces" with a tolerance (file only, model untouched).
- Report notes translated; zero-area faces dropped.
- tools/dxf_to_step.py: 3DFACE DXF to STEP with the same engine.

## 0.2.0 — 2026-10-13
- IngeTrazo panel "STEP" + menu entry "Export to STEP…" (English / French, follows
  IngeTrazo's language): whole model or selection,
  unit, colours, author, analysis report before writing.
- V2: cylinder recognition (rods, holes, tubes, rounds, fillets) written as
  CYLINDRICAL_SURFACE + CIRCLE edges; exact volume in the report; facets kept, with the
  reason, when the border is not exact (oblique cut...).
- Reader: circles and cylinders (independent sampling) for the tests.

## 0.1.0
- Core: planar-face B-rep solids with holes, names, units, colours, weld / orientation /
  closure checks, open parts as shells, non-planar faces triangulated.

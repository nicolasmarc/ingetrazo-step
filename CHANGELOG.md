# Changelog

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

# Changelog

## 0.4.1 — 2026-10-24
- **Cylinders cut at an angle** (#2): a cylinder ending on a plane that is not square to its axis
  (mitred tube corners, angled pipe ends, slanted rods) is now written as one
  `CYLINDRICAL_SURFACE` bounded by an exact `ELLIPSE` arc, shared with the plane face, instead of
  staying faceted with "oblique border". Exact volume (closed form on the ellipse); checked against
  closed-form volumes and against an independent kernel (OpenCascade: valid solids, same volume).
  Only a plane within about 3° of the axis is still refused.
- **Lone open face with repair on** (#3): a part made of one open face, or of a flat sheet of
  faces, no longer crashes the repair step (IndexError in `_absorb`); it stays an open shell, as
  without repair, instead of being capped back to back into a zero-volume solid.

## 0.4.0 — 2026-10-18
- **Import STEP**: Extensions ▸ Import STEP…, the panel's Import… button, or opening a
  `.stp` / `.step` in IngeTrazo (file opener). One group per part, named and coloured, placed
  as in the assembly, one undo step, left selected.
- `stepread.py`: full reader (product tree, placements, units, colours; planes, cylinders,
  cones, spheres, tori, extrusions, revolutions, B-splines meshed to a tolerance, seams and
  poles handled, closed parts watertight). Several named solids in one product become
  several parts. Same file as in the Motion extension.
- **Part names kept, both ways.** Export: every part is now its own PRODUCT named after the
  group, under an assembly named after the file (0.3 wrote a single product "model", so
  other CAD programs showed every part as an anonymous "Solide"/"Body"). Import: the
  component name the designer typed wins over a solid name the CAD program gave on its own
  ("Solide", "Body1", "NAUO3"); accented names (`\X2\` escapes) decoded. Files written by
  0.3 still import with their names.
- Tests against files written by an independent kernel (OpenCascade via CadQuery) and an
  export -> import round trip; OpenCascade reads the exported part names.

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

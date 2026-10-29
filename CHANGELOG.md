# Changelog

## 0.5.0 — 2026-10-28
- **IGES export** (ingelibre/ingetrazo#109). A *Format* choice in the panel: STEP, **IGES solids**
  or **IGES surfaces**, written from the IGES 5.3 specification with the same solids, cylinders
  and ellipses as the STEP. Solids are manifold solid B-reps (186); surfaces are trimmed surfaces
  (144) for programs that do not read IGES solids. Names and colours carried, units mm / cm / m.
  "Convert a DXF…" follows the chosen format. Checked with OpenCascade: every solid valid, same
  volumes as the STEP of the same model on the IngeTrazo examples (1 203 solids for the arch).
- **Faster on large models.** Cylinder recognition no longer re-plans every region each time it
  rejects one, only its neighbours: the 77 000-triangle fountain example exports in 41 s instead of
  129 s, the STEP file byte for byte the same.
- **Spanish.** The panel, its report and its messages now follow IngeTrazo in Spanish too
  (English, French, Spanish; other languages fall back to English).

## 0.4.2 — 2026-10-28
- **Convert a DXF to STEP… (exact sizes).** A new button reads the DXF itself in double
  precision and writes the STEP, without going through the IngeTrazo model (which keeps 7
  digits: a 70 mm gap two metres out reads 69.99995 mm). 3DFACE, SOLID/TRACE, POLYFACE,
  polygon meshes and MESH; one named part per block, assembly blocks opened up into their
  parts, loose faces by layer; units from the header or guessed from the size. Sizes come out
  exact to the file's digits. "Show the result in the model" (on by default) reads the written
  .stp back into the model: one group per solid, selected, one Ctrl+Z to remove them.
- **Parts sharing a whole face** (a beam resting on a block along one slanted plane, the face
  written once) each get that face: two closed solids instead of open pieces.
- **Round sizes stay round.** IngeTrazo keeps positions in single precision, so a 44 mm tread
  came out 44.00003 mm and a 16 mm baluster 15.99999 mm. Coordinates are now snapped to a
  0.001 mm grid on export, fitted cylinders get round radii and exact axes, and their corners
  are put back on the round cylinder: the file measures 44, 16, 40 mm in CAD.
- **Parts that touch on an edge are separate solids.** A group holding many loose parts (a DXF
  layer of 3DFACEs: every tread, baluster and rail in one group) no longer comes out as
  non-manifold lumps where parts meet edge to edge: the shell split stops at edges carried by
  more than two faces.
- **Bodies that touch themselves along an edge are valid solids.** Where a DXF welded two
  parts into one body that meets itself on an edge (a rail butting a post: four faces on one
  edge), the faces are paired around that edge and the edge's vertices are doubled for the
  second pair: the same closed solid, now a valid B-rep instead of an open shell.
- **One CAD component per solid** when a group holds several separate solids, named
  "Group (1)", "Group (2)"…, instead of one component holding them all.
- **Rods in 15 or more facets are found without soft edges**: geometry detection now accepts
  seams up to 25° (was 20°), so a 16- or 17-facet DXF baluster becomes a true cylinder. A
  12-facet prism (30°) still stays a prism.

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

"""Import a STEP assembly into the IngeTrazo model: one group per part
(named after the part, painted with its colour), in one undo step.

Planar faces come in whole, holes included; curved faces as triangles
whose inner edges are softened so they read smooth. Needs IngeTrazo
(``core``) and PySide6; the reading itself is ``motion.stepread``.
"""
import math
import numpy as np

from . import stepread


def build_groups(asm, soft_angle=35.0, orient=False):
    """IngeTrazo groups (not yet in a scene) for the parts of ``asm``.
    The reader already turns every face outward (surface normal and its
    sense in the file), so IngeTrazo's own re-orientation — slow on big
    parts — is only run with ``orient=True``."""
    from core.group import Group
    from core.mesh import Mesh
    groups = []
    cos_t = math.cos(math.radians(soft_angle))
    for part in asm.parts:
        pos, rings, per_face = [], [], []
        for f in part.faces:
            if f.loops is not None and all(len(L) >= 3 for L in f.loops):
                for L in f.loops:
                    pos.append(part.world(L))
                    rings.append(len(L))
                per_face.append(len(f.loops))
            elif len(f.triangles):
                T = part.world(f.triangles.reshape(-1, 3)).reshape(-1, 3, 3)
                ok = np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1) > 1e-14
                T = T[ok]
                if len(T):
                    pos.append(T.reshape(-1, 3))
                    rings += [3] * len(T)
                    per_face += [1] * len(T)
        if not pos:
            continue
        mesh = Mesh()
        mesh.add_faces_bulk(np.vstack(pos), np.array(rings, dtype=np.int64),
                            np.array(per_face, dtype=np.int64))
        if orient:
            try:
                from core.orient import orient_outward
                orient_outward(mesh)
            except Exception:
                pass
        for e in mesh.edges:                     # smooth look on curved faces
            if len(e.faces) == 2:
                try:
                    n0, n1 = e.faces[0].normal(), e.faces[1].normal()
                    if (n0.x() * n1.x() + n0.y() * n1.y() + n0.z() * n1.z()) > cos_t:
                        e.soft = True
                except Exception:
                    pass
        g = Group(mesh, name=part.name or "pièce")
        if part.color is not None:
            g.material = {"color": tuple(float(c) for c in part.color)}
        groups.append(g)
    return groups


def import_into(app, path, tol=0.0002):
    """Read ``path`` and add its parts to the open model (one undo step).
    Returns (assembly, groups)."""
    from core.history import SnapshotImport
    asm = stepread.read(path, tol=tol)
    groups = build_groups(asm)
    vp = app.viewport

    def mutate(scene):
        scene.groups.extend(groups)

    vp.history.execute(SnapshotImport(mutate))
    notify = getattr(vp, "notify_scene_changed", None)
    if callable(notify):
        notify()
    vp.update()
    return asm, groups

"""STEP / IGES export and STEP import for IngeTrazo (clean-room, GPL-3.0-or-later).

Pure Python + numpy core (no Qt): ``model`` (parts/faces), ``check``
(weld, orientation, closure, volume), ``writer`` (ISO 10303-21 text) and
``reader`` (a minimal reader used to verify what we wrote),
``stepread`` (the full reader: assemblies, placements, colours, planes,
cylinders, cones, spheres, tori, extrusions, revolutions, B-splines,
meshed to a tolerance) and ``stepimport`` (parts -> IngeTrazo groups).
``surfaces`` + ``brep`` (V2: cylinders), ``collect`` (scene -> parts),
``iges`` (IGES 5.3 writer from the same B-rep).
The IngeTrazo UI (``panel``) is loaded lazily by ``setup``.
"""
__version__ = "0.5.0"


def setup(app):          # pragma: no cover - UI, needs IngeTrazo
    from .panel import setup as _setup
    _setup(app)

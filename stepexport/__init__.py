"""STEP export for IngeTrazo (clean-room, GPL-3.0-or-later).

Pure Python + numpy core (no Qt): ``model`` (parts/faces), ``check``
(weld, orientation, closure, volume), ``writer`` (ISO 10303-21 text) and
``reader`` (a minimal reader used to verify what we wrote).
``surfaces`` + ``brep`` (V2: cylinders), ``collect`` (scene -> parts).
The IngeTrazo UI (``panel``) is loaded lazily by ``setup``.
"""
__version__ = "0.3.0"


def setup(app):          # pragma: no cover - UI, needs IngeTrazo
    from .panel import setup as _setup
    _setup(app)

"""Plain input model: a Part is a named bag of polygonal faces."""
from dataclasses import dataclass, field


@dataclass
class Face:
    outer: list                       # [(x, y, z), ...] loop, any orientation
    holes: list = field(default_factory=list)   # [[(x,y,z), ...], ...]
    src: int = None      # faces cut from one source face share this id


@dataclass
class Part:
    name: str
    faces: list
    color: tuple = None               # (r, g, b) 0..1 or None
    # Edges the modeller drew smooth (facet seams of a pushed circle, a
    # fillet...): pairs of end points ``((x,y,z), (x,y,z))``. Only a hint for
    # the cylinder recognition (V2); ``None`` = no hint available.
    soft_edges: list = None

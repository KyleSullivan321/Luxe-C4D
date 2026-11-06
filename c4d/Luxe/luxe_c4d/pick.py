"""The surface under the cursor: a ray from the camera through the pixel, against every visible polygon mesh.

Generators (primitives, subdivision surfaces, cloners) and deformers are tested through their caches. Cinema 4D sets
BIT_CONTROLOBJECT on generators themselves as well as on consumed input meshes, so only leaf polygon objects check
BIT_CONTROLOBJECT. Normals are the mesh's smoothed (Phong) normal; under non-uniform object scale they bend slightly
(MulV, not the inverse transpose).
"""
from collections import namedtuple

import c4d
from c4d.utils import GeRayCollider

# size: the hit mesh's bounding diagonal, for default distances. obj: the scene object that draws the hit mesh (the
# generator for a cache), for light linking.
Hit = namedtuple("Hit", "point normal ray size obj", defaults=(None,))


def _meshes(op, parent_mg=None, owner=None):
    """Yield (polygon object, world matrix, scene object) for op, its siblings and everything they draw.

    parent_mg is None for objects in the document and the generator's world matrix inside a cache; owner is the
    document object whose cache is being walked.
    """
    while op is not None:
        mg = op.GetMg() if parent_mg is None else parent_mg * op.GetMl()
        hidden = parent_mg is None and op.GetEditorMode() == c4d.MODE_OFF
        if not hidden:
            obj = op if parent_mg is None else owner
            cache = op.GetDeformCache()
            if cache is None:
                cache = op.GetCache()
            if cache is not None:
                yield from _meshes(cache, mg, obj)
            elif not op.GetBit(c4d.BIT_CONTROLOBJECT) and op.IsInstanceOf(c4d.Opolygon) and op.GetPolygonCount():
                yield op, mg, obj
            yield from _meshes(op.GetDown(), None if parent_mg is None else mg, owner)
        op = op.GetNext()


class Picker:
    """Keeps one ray collider per mesh, so moving the mouse does not rebuild them (Init skips unchanged meshes)."""

    def __init__(self):
        self._colliders = []

    def hit(self, doc, bd, x, y):
        """The surface under screen pixel (x, y) of view `bd`, or None."""
        origin = bd.SW(c4d.Vector(x, y, 0.0))
        return self.cast(doc, origin, (bd.SW(c4d.Vector(x, y, 100000.0)) - origin).GetNormalized())

    def cast(self, doc, origin, ray):
        """The nearest surface along a world-space ray (unit direction), or None."""
        best = None
        for i, (mesh, mg, obj) in enumerate(_meshes(doc.GetFirstObject())):
            if i == len(self._colliders):
                self._colliders.append(GeRayCollider())
            rc = self._colliders[i]
            if not rc.Init(mesh, False):
                continue
            inv = ~mg
            local_dir = inv.MulV(ray)
            if local_dir.GetLength() < 1e-12 or not rc.Intersect(inv * origin, local_dir.GetNormalized(), 1.0e7):
                continue
            res = rc.GetNearestIntersection()
            point = mg * res["hitpos"]
            dist = (point - origin).GetLength()
            if best is None or dist < best[0]:
                normal = mg.MulV(res["s_normal"]).GetNormalized()
                best = (dist, Hit(point, normal, ray, 2.0 * mg.MulV(mesh.GetRad()).GetLength(), obj))
        return best[1] if best else None

    def clear(self):
        self._colliders = []

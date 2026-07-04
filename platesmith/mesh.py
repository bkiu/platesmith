"""Extrude 2D shapely polygons into watertight triangle meshes."""

from __future__ import annotations

from dataclasses import dataclass

from shapely import constrained_delaunay_triangles
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

# Vertices closer than this (mm) are merged so caps and walls share indices.
SNAP = 1e-6


@dataclass
class Mesh:
    vertices: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]


class _VertexPool:
    def __init__(self):
        self.vertices: list[tuple[float, float, float]] = []
        self._index: dict[tuple[int, int, int], int] = {}

    def add(self, x: float, y: float, z: float) -> int:
        key = (round(x / SNAP), round(y / SNAP), round(z / SNAP))
        idx = self._index.get(key)
        if idx is None:
            idx = len(self.vertices)
            self._index[key] = idx
            self.vertices.append((x, y, z))
        return idx


def _signed_area(coords) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        area += x1 * y2 - x2 * y1
    return area / 2.0


def extrude(geom: MultiPolygon | Polygon, z0: float, z1: float,
            simplify: float = 0.02) -> Mesh:
    """Extrude polygons from z0 to z1 (mm). Returns a watertight mesh."""
    # A tiny erode/dilate opens pinch points (rings touching themselves at a
    # single vertex, common after make_valid on traced art). Pinches keep the
    # surface closed but make it non-manifold, which slicers flag for repair.
    eps = 5e-4  # 0.5 µm — far below print resolution
    opened = geom.buffer(-eps).buffer(eps)
    if not opened.is_empty:
        geom = opened
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    pool = _VertexPool()
    tris: list[tuple[int, int, int]] = []

    for poly in geom.geoms:
        if simplify:
            poly = poly.simplify(simplify, preserve_topology=True)
        if poly.is_empty or poly.area <= 0:
            continue
        poly = orient(poly)  # exterior CCW, holes CW

        # Caps via constrained Delaunay triangulation (respects holes, adds
        # no new vertices, so cap vertices coincide with wall vertices).
        for tri in constrained_delaunay_triangles(poly).geoms:
            coords = list(tri.exterior.coords)[:3]
            if abs(_signed_area(coords + coords[:1])) < 1e-12:
                continue
            if _signed_area(coords + coords[:1]) < 0:
                coords.reverse()  # CCW so the top-face normal points +z
            top = [pool.add(x, y, z1) for x, y in coords]
            bot = [pool.add(x, y, z0) for x, y in coords]
            tris.append((top[0], top[1], top[2]))
            tris.append((bot[0], bot[2], bot[1]))

        # Side walls.
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            for (ax, ay), (bx, by) in zip(coords, coords[1:]):
                a0 = pool.add(ax, ay, z0)
                b0 = pool.add(bx, by, z0)
                b1 = pool.add(bx, by, z1)
                a1 = pool.add(ax, ay, z1)
                if a0 == b0:
                    continue
                tris.append((a0, b0, b1))
                tris.append((a0, b1, a1))

    if not tris:
        raise ValueError("Extrusion produced no geometry.")
    return Mesh(vertices=pool.vertices, triangles=tris)


def manifold_errors(mesh: Mesh) -> list[str]:
    """Sanity check: the surface must be closed.

    Every directed edge must be balanced by its reverse. Pinch points (a
    ring touching itself at one vertex) produce edges used twice in each
    direction; that is still a closed surface and slices fine, so only
    unbalanced edges are reported.
    """
    from collections import Counter

    edges = Counter()
    for a, b, c in mesh.triangles:
        for e in ((a, b), (b, c), (c, a)):
            edges[e] += 1
    return [
        f"edge {a}->{b}: {n} forward vs {edges.get((b, a), 0)} reverse"
        for (a, b), n in edges.items()
        if n != edges.get((b, a), 0)
    ]

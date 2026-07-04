"""Convert SVG documents into clean 2D shapely geometry.

Coordinates stay in the SVG's own user units (pixels, y-down). Scaling to
millimeters and the y-flip happen later, once the target size is known.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

from shapely import make_valid, unary_union
from shapely.geometry import LineString, MultiPolygon, Polygon
from svgelements import (
    SVG,
    Arc,
    Close,
    CubicBezier,
    Line,
    Move,
    Path,
    QuadraticBezier,
    Shape,
    SVGImage,
    SVGText,
)

# Maximum chord-to-curve deviation while flattening, in px. Uploaded art is
# typically a few hundred px wide and printed tens of mm wide, so 0.1 px is
# comfortably below nozzle resolution.
FLATTEN_TOLERANCE = 0.1


@dataclass
class SvgGeometry:
    geometry: MultiPolygon
    warnings: list[str] = field(default_factory=list)


def _sample_segment(seg) -> list[tuple[float, float]]:
    """Points along one path segment, excluding the start point."""
    if isinstance(seg, (Line, Close)):
        return [(seg.end.x, seg.end.y)]
    try:
        length = seg.length(error=1e-3)
    except TypeError:
        length = seg.length()
    if not length or not math.isfinite(length):
        return [(seg.end.x, seg.end.y)]
    # Chord count so the sagitta stays under FLATTEN_TOLERANCE for a
    # worst-case (semicircular) arc of this length.
    n = max(2, min(256, int(math.pi * math.sqrt(length / (8 * FLATTEN_TOLERANCE)))))
    pts = []
    for i in range(1, n + 1):
        p = seg.point(i / n)
        pts.append((p.x, p.y))
    return pts


def _subpath_points(subpath) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for seg in subpath:
        if isinstance(seg, Move):
            pts.append((seg.end.x, seg.end.y))
        else:
            pts.extend(_sample_segment(seg))
    return pts


def _rings_to_evenodd(rings: list[list[tuple[float, float]]]):
    """Combine closed rings with the even-odd rule (holes cancel)."""
    acc = None
    for ring in rings:
        if len(ring) < 3:
            continue
        poly = make_valid(Polygon(ring))
        if poly.is_empty:
            continue
        acc = poly if acc is None else acc.symmetric_difference(poly)
    return acc


def _is_none_paint(paint) -> bool:
    return paint is None or getattr(paint, "value", None) is None


def svg_to_geometry(svg_text: str) -> SvgGeometry:
    """Parse an SVG document into a single MultiPolygon (px units, y-down)."""
    svg = SVG.parse(io.StringIO(svg_text), reify=True, ppi=96)
    warnings: list[str] = []
    parts = []

    for element in svg.elements():
        if isinstance(element, SVGText):
            warnings.append(
                "Text element ignored — convert text to paths first "
                "(Inkscape: Path > Object to Path)."
            )
            continue
        if isinstance(element, SVGImage):
            warnings.append("Embedded raster image ignored — only vector shapes are used.")
            continue
        if not isinstance(element, Shape):
            continue
        if element.values.get("visibility") == "hidden" or element.values.get("display") == "none":
            continue

        try:
            path = Path(element)
        except Exception:
            continue
        if len(path) == 0:
            continue

        filled = not _is_none_paint(element.fill)
        stroked = not _is_none_paint(element.stroke) and (element.stroke_width or 0) > 0
        if not filled and not stroked:
            continue

        subpaths = [_subpath_points(sp) for sp in path.as_subpaths()]
        subpaths = [sp for sp in subpaths if len(sp) >= 2]
        if not subpaths:
            continue

        if filled:
            geom = _rings_to_evenodd([sp for sp in subpaths if len(sp) >= 3])
            if geom is not None and not geom.is_empty:
                parts.append(geom)

        if stroked:
            half = element.stroke_width / 2.0
            for sp in subpaths:
                line = LineString(sp)
                if line.length > 0:
                    parts.append(line.buffer(half, quad_segs=8))

    if not parts:
        raise ValueError(
            "No printable shapes found in this SVG. "
            + " ".join(dict.fromkeys(warnings))
        )

    merged = make_valid(unary_union(parts))
    merged = _as_multipolygon(merged)
    if merged.is_empty:
        raise ValueError("SVG shapes collapsed to zero area.")
    return SvgGeometry(geometry=merged, warnings=list(dict.fromkeys(warnings)))


def _as_multipolygon(geom) -> MultiPolygon:
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    # GeometryCollection: keep only polygonal pieces.
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and g.area > 0]
    return MultiPolygon(polys)


def rounded_rect(width: float, height: float, radius: float) -> Polygon:
    """Rounded rectangle centered on the origin (mm, y-up)."""
    radius = max(0.0, min(radius, width / 2, height / 2))
    from shapely.geometry import box

    if radius <= 1e-9:
        return box(-width / 2, -height / 2, width / 2, height / 2)
    inner = box(-(width / 2 - radius), -(height / 2 - radius),
                width / 2 - radius, height / 2 - radius)
    return inner.buffer(radius, quad_segs=32)


def geometry_to_svg_path(geom, precision: int = 3) -> str:
    """Serialize polygons as one SVG path string (even-odd fill)."""
    cmds = []
    for poly in _as_multipolygon(geom).geoms:
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)
            cmds.append(
                "M" + " L".join(f"{x:.{precision}f},{y:.{precision}f}" for x, y in coords[:-1]) + "Z"
            )
    return " ".join(cmds)

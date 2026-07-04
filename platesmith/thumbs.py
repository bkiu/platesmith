"""Render plate thumbnails (top-down) for the 3MF package using Pillow."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw
from shapely.geometry import MultiPolygon, Polygon

BG = (57, 60, 67, 255)
SUPERSAMPLE = 2


def render_top_view(parts: list[tuple[MultiPolygon, str]], size: int) -> bytes:
    """Top-down PNG of colored 2D parts (mm, y-up). First part = plate."""
    parts = [
        (MultiPolygon([g]) if isinstance(g, Polygon) else g, color)
        for g, color in parts
    ]
    minx, miny, maxx, maxy = parts[0][0].bounds
    span = max(maxx - minx, maxy - miny) * 1.15 or 1.0
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    px = size * SUPERSAMPLE
    scale = px / span

    def to_px(x: float, y: float) -> tuple[float, float]:
        # y-up mm -> y-down pixels
        return ((x - cx) * scale + px / 2, (cy - y) * scale + px / 2)

    img = Image.new("RGBA", (px, px), BG)
    for geom, color in parts:
        # Even-odd fill per polygon: exterior opaque, holes punched out,
        # composited so holes reveal whatever is underneath.
        mask = Image.new("L", (px, px), 0)
        d = ImageDraw.Draw(mask)
        for poly in geom.geoms:
            d.polygon([to_px(x, y) for x, y in poly.exterior.coords], fill=255)
            for ring in poly.interiors:
                d.polygon([to_px(x, y) for x, y in ring.coords], fill=0)
        layer = Image.new("RGBA", (px, px), color)
        img = Image.composite(layer, img, mask)

    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()

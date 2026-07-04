"""FastAPI server: serves the editor UI, previews SVG geometry, exports 3MF."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from shapely import affinity

from .bambu import Part, write_3mf
from .geometry import geometry_to_svg_path, rounded_rect, svg_to_geometry
from .mesh import extrude

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Platesmith")


class PreviewRequest(BaseModel):
    svg: str


class PlateSpec(BaseModel):
    width: float = Field(gt=0, le=256)
    height: float = Field(gt=0, le=256)
    radius: float = Field(ge=0)
    thickness: float = Field(gt=0, le=50)
    color: str


class ItemSpec(BaseModel):
    svg: str
    name: str = "svg"
    color: str
    width: float = Field(gt=0)  # target width in mm (geometry bbox width)
    thickness: float = Field(gt=0, le=50)
    x: float = 0.0  # center offset from plate center, mm, screen coords (y down)
    y: float = 0.0
    rotation: float = 0.0  # degrees, clockwise on screen


class Scene(BaseModel):
    name: str = "Platesmith design"
    plate: PlateSpec
    items: list[ItemSpec]


def _check_color(color: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise HTTPException(422, f"Invalid color {color!r}, expected #RRGGBB")
    return color.upper()


@app.post("/api/preview")
def preview(req: PreviewRequest):
    try:
        result = svg_to_geometry(req.svg)
    except ValueError as e:
        raise HTTPException(422, str(e))
    geom = result.geometry.simplify(0.05, preserve_topology=True)
    return {
        "path": geometry_to_svg_path(geom),
        "bbox": list(result.geometry.bounds),
        "warnings": result.warnings,
    }


class PlateMeshRequest(BaseModel):
    width: float = Field(gt=0, le=256)
    height: float = Field(gt=0, le=256)
    radius: float = Field(ge=0)


def _mesh_payload(mesh):
    return {
        "vertices": [round(c, 4) for v in mesh.vertices for c in v],
        "indices": [i for t in mesh.triangles for i in t],
    }


@app.post("/api/mesh")
def item_mesh(req: PreviewRequest):
    """Extruded mesh of an SVG for the 3D preview.

    Same pipeline as export, but at the SVG's native pixel scale (centered,
    y already flipped to 3D convention) and unit height, so the client
    applies size/rotation/thickness as cheap matrix transforms.
    """
    try:
        geom = svg_to_geometry(req.svg).geometry
    except ValueError as e:
        raise HTTPException(422, str(e))
    minx, miny, maxx, maxy = geom.bounds
    geom = affinity.translate(geom, -(minx + maxx) / 2, -(miny + maxy) / 2)
    geom = affinity.scale(geom, 1, -1, origin=(0, 0))
    return _mesh_payload(extrude(geom, 0, 1, simplify=0.1))


@app.post("/api/plate-mesh")
def plate_mesh(req: PlateMeshRequest):
    """Unit-height plate mesh (mm, centered) for the 3D preview."""
    return _mesh_payload(extrude(rounded_rect(req.width, req.height, req.radius), 0, 1))


def _item_geometry(item: ItemSpec):
    try:
        geom = svg_to_geometry(item.svg).geometry
    except ValueError as e:
        raise HTTPException(422, f"{item.name}: {e}")
    minx, miny, maxx, maxy = geom.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    scale = item.width / (maxx - minx)
    geom = affinity.translate(geom, -cx, -cy)
    # Flip y: SVG is y-down, the printer is y-up. Screen-clockwise rotation
    # becomes a negative (CCW) angle after the flip.
    geom = affinity.scale(geom, scale, -scale, origin=(0, 0))
    if item.rotation:
        geom = affinity.rotate(geom, -item.rotation, origin=(0, 0))
    return affinity.translate(geom, item.x, -item.y)


@app.post("/api/export")
def export(scene: Scene):
    plate = scene.plate
    _check_color(plate.color)
    for item in scene.items:
        _check_color(item.color)

    plate_geom = rounded_rect(plate.width, plate.height, plate.radius)
    parts = [
        Part(
            name="plate",
            mesh=extrude(plate_geom, 0, plate.thickness),
            color=plate.color,
            geometry=plate_geom,
        )
    ]
    for item in scene.items:
        geom = _item_geometry(item)
        parts.append(
            Part(
                name=item.name,
                mesh=extrude(geom, plate.thickness, plate.thickness + item.thickness),
                color=item.color,
                geometry=geom,
            )
        )

    data = write_3mf(scene.name, parts)
    filename = re.sub(r"[^\w\- ]", "", scene.name).strip() or "design"
    return Response(
        content=data,
        media_type="application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}.3mf"'},
    )


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main():
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Platesmith — SVG → Bambu 3MF plate builder")
    parser.add_argument("--port", type=int, default=8137)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"Platesmith running at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

import io
import json
import xml.etree.ElementTree as ET
import zipfile

import pytest
from fastapi.testclient import TestClient

from platesmith.geometry import rounded_rect, svg_to_geometry
from platesmith.mesh import extrude, manifold_errors
from platesmith.bambu import write_3mf, Part
from platesmith.server import app

STAR = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <path d="M50 5 L61 39 L97 39 L68 60 L79 95 L50 73 L21 95 L32 60 L3 39 L39 39 Z"/>
  <circle cx="50" cy="52" r="10" fill="none" stroke="black" stroke-width="4"/>
</svg>"""


def test_svg_parse_star():
    g = svg_to_geometry(STAR)
    assert g.geometry.area > 0
    assert not g.warnings


def test_rounded_rect_full_radius_is_circleish():
    p = rounded_rect(40, 40, 20)
    import math
    assert p.area == pytest.approx(math.pi * 20 * 20, rel=0.01)


def test_extrude_watertight():
    g = svg_to_geometry(STAR).geometry
    mesh = extrude(g, 0, 2)
    assert manifold_errors(mesh) == []
    assert min(v[2] for v in mesh.vertices) == 0
    assert max(v[2] for v in mesh.vertices) == 2


def test_write_3mf_structure():
    plate_geom = rounded_rect(60, 40, 5)
    star_geom = svg_to_geometry(STAR).geometry
    plate = extrude(plate_geom, 0, 2)
    star = extrude(star_geom, 2, 3.2)
    data = write_3mf("Test", [Part("plate", plate, "#161616", plate_geom),
                              Part("star", star, "#FFFFFF", star_geom)])

    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model",
            "3D/_rels/3dmodel.model.rels", "3D/Objects/object_1.model",
            "Metadata/model_settings.config", "Metadata/project_settings.config",
            "Metadata/slice_info.config", "Metadata/cut_information.xml",
            "Metadata/filament_sequence.json", "Metadata/plate_1.png",
            "Metadata/plate_1_small.png"} <= names

    # XML well-formed, mesh objects present
    root = ET.fromstring(zf.read("3D/Objects/object_1.model"))
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    objects = root.findall(".//m:object", ns)
    assert len(objects) == 2

    top = ET.fromstring(zf.read("3D/3dmodel.model"))
    comps = top.findall(".//m:component", ns)
    assert len(comps) == 2

    settings = ET.fromstring(zf.read("Metadata/model_settings.config"))
    extruders = [
        m.get("value")
        for part in settings.findall(".//part")
        for m in part.findall("metadata")
        if m.get("key") == "extruder"
    ]
    assert extruders == ["1", "2"]

    proj = json.loads(zf.read("Metadata/project_settings.config"))
    assert proj["filament_colour"] == ["#161616", "#FFFFFF"]
    assert len(proj["filament_settings_id"]) == 2
    assert len(proj["flush_volumes_matrix"]) == 4
    assert proj["printer_settings_id"].startswith("Bambu Lab P1S")
    # Keys Bambu Studio 2.5 requires and older templates lack
    assert proj["nozzle_volume_type"] == ["Standard"]
    assert len(proj["different_settings_to_system"]) == 4  # print + 2 filaments + printer
    # Machine limit pairs are [normal, silent] — must not be filament-sized
    assert len(proj["machine_max_speed_x"]) == 2


def test_project_settings_filament_counts():
    from platesmith.bambu import _project_settings

    for n in (1, 2, 3, 5):
        colors = [f"#0000{i:02X}" for i in range(n)]
        proj = json.loads(_project_settings(colors))
        assert proj["filament_colour"] == colors
        assert len(proj["filament_settings_id"]) == n
        assert len(proj["nozzle_temperature"]) == n
        assert len(proj["flush_volumes_matrix"]) == n * n
        assert len(proj["flush_volumes_vector"]) == 2 * n
        assert len(proj["inherits_group"]) == n + 2
        assert len(proj["machine_max_speed_x"]) == 2


def test_color_dedup():
    geom = rounded_rect(20, 20, 0)
    plate = extrude(geom, 0, 1)
    data = write_3mf("t", [
        Part("plate", plate, "#ffffff", geom),
        Part("a", plate, "#FFFFFF", geom),
        Part("b", plate, "#FF0000", geom),
    ])
    proj = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("Metadata/project_settings.config"))
    assert proj["filament_colour"] == ["#FFFFFF", "#FF0000"]


def test_api_preview_and_export():
    client = TestClient(app)
    r = client.post("/api/preview", json={"svg": STAR})
    assert r.status_code == 200
    body = r.json()
    assert body["path"].startswith("M")
    assert len(body["bbox"]) == 4

    scene = {
        "name": "API Test",
        "plate": {"width": 80, "height": 50, "radius": 25, "thickness": 2, "color": "#161616"},
        "items": [{"svg": STAR, "name": "star", "color": "#FFFFFF", "width": 30,
                   "thickness": 1.2, "x": 5, "y": -3, "rotation": 15}],
    }
    r = client.post("/api/export", json=scene)
    assert r.status_code == 200
    assert "API Test.3mf" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "3D/3dmodel.model" in zf.namelist()


def test_lib3mf_validates_export():
    lib3mf = pytest.importorskip("lib3mf")
    client = TestClient(app)
    scene = {
        "name": "validate",
        "plate": {"width": 60, "height": 40, "radius": 20, "thickness": 2, "color": "#161616"},
        "items": [{"svg": STAR, "name": "star", "color": "#FFFFFF", "width": 25,
                   "thickness": 1.2, "x": 3, "y": 2, "rotation": 30}],
    }
    r = client.post("/api/export", json=scene)
    assert r.status_code == 200

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".3mf", delete=False) as f:
        f.write(r.content)
        path = f.name
    try:
        wrapper = lib3mf.Wrapper()
        model = wrapper.CreateModel()
        reader = model.QueryReader("3mf")
        reader.ReadFromFile(path)
        it = model.GetObjects()
        meshes = 0
        while it.MoveNext():
            obj = it.GetCurrentObject()
            if obj.IsMeshObject():
                meshes += 1
                assert obj.IsManifoldAndOriented(), f"object {obj.GetResourceID()} not manifold"
        assert meshes == 2
    finally:
        os.unlink(path)


def test_api_mesh_endpoints():
    client = TestClient(app)
    r = client.post("/api/mesh", json={"svg": STAR})
    assert r.status_code == 200
    body = r.json()
    assert len(body["vertices"]) % 3 == 0
    assert len(body["indices"]) % 3 == 0
    zs = body["vertices"][2::3]
    assert min(zs) == 0 and max(zs) == 1  # unit height, scaled client-side
    ys = body["vertices"][1::3]
    assert abs(max(ys) + min(ys)) < 0.05  # centered, y flipped

    r = client.post("/api/plate-mesh", json={"width": 80, "height": 50, "radius": 10})
    assert r.status_code == 200
    body = r.json()
    xs = body["vertices"][0::3]
    assert max(xs) == pytest.approx(40, abs=0.01)


def test_api_export_rejects_bad_color():
    client = TestClient(app)
    scene = {
        "name": "x",
        "plate": {"width": 80, "height": 50, "radius": 0, "thickness": 2, "color": "red"},
        "items": [],
    }
    assert client.post("/api/export", json=scene).status_code == 422


def test_api_preview_rejects_empty_svg():
    client = TestClient(app)
    r = client.post("/api/preview", json={"svg": "<svg xmlns='http://www.w3.org/2000/svg'/>"})
    assert r.status_code == 422

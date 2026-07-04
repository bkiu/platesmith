"""Write Bambu Studio project 3MF files.

The package layout mirrors files saved by Bambu Studio 2.5 itself:

    [Content_Types].xml
    _rels/.rels
    3D/3dmodel.model            top-level object built from components
    3D/_rels/3dmodel.model.rels
    3D/Objects/object_1.model   one mesh object per part (plate + each SVG)
    Metadata/model_settings.config    per-part extruder (filament) mapping
    Metadata/project_settings.config  printer/filament profile + colors
    Metadata/slice_info.config
    Metadata/cut_information.xml
    Metadata/filament_sequence.json
    Metadata/plate_1.png (+ _small, _no_light)   rendered thumbnails

Filament colors come from the design; every other setting comes from
``templates/project_settings.json`` — a clean config produced by round-
tripping one of the user's own P1S 0.4-nozzle projects through Bambu
Studio 2.5, so it contains every key that version expects (e.g.
``nozzle_volume_type``, which older templates lack and whose absence
makes the GUI refuse the project).
"""

from __future__ import annotations

import datetime
import io
import json
import uuid
import zipfile
from dataclasses import dataclass
from importlib import resources

from shapely.geometry import MultiPolygon

from .mesh import Mesh
from .thumbs import render_top_view

BED_SIZE = 256.0  # Bambu Lab P1S bed, mm
TOP_OBJECT_ID = 1000
APP_VERSION = "02.05.00.66"
NS = (
    'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
    'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
    'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" '
    'requiredextensions="p"'
)


@dataclass
class Part:
    name: str
    mesh: Mesh
    color: str  # '#RRGGBB'
    geometry: MultiPolygon  # 2D footprint in plate coords (mm, y-up), for thumbnails


def _fmt(v: float) -> str:
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def _uuid() -> str:
    return str(uuid.uuid4())


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _object_file(parts: list[Part]) -> str:
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    out.write(f'<model unit="millimeter" xml:lang="en-US" {NS}>\n')
    out.write(' <metadata name="BambuStudio:3mfVersion">1</metadata>\n')
    out.write(" <resources>\n")
    for i, part in enumerate(parts, start=1):
        out.write(f'  <object id="{i}" p:UUID="{_uuid()}" type="model">\n')
        out.write("   <mesh>\n    <vertices>\n")
        for x, y, z in part.mesh.vertices:
            out.write(f'     <vertex x="{_fmt(x)}" y="{_fmt(y)}" z="{_fmt(z)}"/>\n')
        out.write("    </vertices>\n    <triangles>\n")
        for a, b, c in part.mesh.triangles:
            out.write(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>\n')
        out.write("    </triangles>\n   </mesh>\n  </object>\n")
    out.write(" </resources>\n <build/>\n</model>\n")
    return out.getvalue()


def _root_model(name: str, part_count: int) -> str:
    today = datetime.date.today().isoformat()
    components = "\n".join(
        f'    <component p:path="/3D/Objects/object_1.model" objectid="{i}" '
        f'p:UUID="{_uuid()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
        for i in range(1, part_count + 1)
    )
    half = _fmt(BED_SIZE / 2)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" {NS}>
 <metadata name="Application">BambuStudio-{APP_VERSION}</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="Copyright"></metadata>
 <metadata name="CreationDate">{today}</metadata>
 <metadata name="Description"></metadata>
 <metadata name="Designer"></metadata>
 <metadata name="DesignerCover"></metadata>
 <metadata name="DesignerUserId"></metadata>
 <metadata name="License"></metadata>
 <metadata name="ModificationDate">{today}</metadata>
 <metadata name="Origin"></metadata>
 <metadata name="ProfileCover"></metadata>
 <metadata name="ProfileDescription"></metadata>
 <metadata name="ProfileTitle"></metadata>
 <metadata name="Thumbnail_Middle">/Metadata/plate_1.png</metadata>
 <metadata name="Thumbnail_Small">/Metadata/plate_1_small.png</metadata>
 <metadata name="Title">{_xml_escape(name)}</metadata>
 <resources>
  <object id="{TOP_OBJECT_ID}" p:UUID="{_uuid()}" type="model">
   <components>
{components}
   </components>
  </object>
 </resources>
 <build p:UUID="{_uuid()}">
  <item objectid="{TOP_OBJECT_ID}" p:UUID="{_uuid()}" transform="1 0 0 0 1 0 0 0 1 {half} {half} 0" printable="1"/>
 </build>
</model>
"""


def _model_settings(name: str, parts: list[Part], extruders: list[int]) -> str:
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n')
    out.write(f'  <object id="{TOP_OBJECT_ID}">\n')
    out.write(f'    <metadata key="name" value="{_xml_escape(name)}"/>\n')
    out.write(f'    <metadata key="extruder" value="{extruders[0]}"/>\n')
    total_faces = sum(len(p.mesh.triangles) for p in parts)
    out.write(f'    <metadata face_count="{total_faces}"/>\n')
    for i, (part, extruder) in enumerate(zip(parts, extruders), start=1):
        out.write(f'    <part id="{i}" subtype="normal_part">\n')
        out.write(f'      <metadata key="name" value="{_xml_escape(part.name)}"/>\n')
        out.write('      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n')
        out.write(f'      <metadata key="source_file" value="{_xml_escape(name)}.3mf"/>\n')
        out.write('      <metadata key="source_object_id" value="0"/>\n')
        out.write(f'      <metadata key="source_volume_id" value="{i - 1}"/>\n')
        out.write('      <metadata key="source_offset_x" value="0"/>\n')
        out.write('      <metadata key="source_offset_y" value="0"/>\n')
        out.write('      <metadata key="source_offset_z" value="0"/>\n')
        out.write(f'      <metadata key="extruder" value="{extruder}"/>\n')
        out.write(f'      <mesh_stat face_count="{len(part.mesh.triangles)}" edges_fixed="0" '
                  'degenerate_facets="0" facets_removed="0" facets_reversed="0" '
                  'backwards_edges="0"/>\n')
        out.write("    </part>\n")
    out.write("  </object>\n")
    half = _fmt(BED_SIZE / 2)
    out.write(f"""  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="gcode_file" value=""/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <model_instance>
      <metadata key="object_id" value="{TOP_OBJECT_ID}"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="100"/>
    </model_instance>
  </plate>
  <assemble>
   <assemble_item object_id="{TOP_OBJECT_ID}" instance_id="0" transform="1 0 0 0 1 0 0 0 1 {half} {half} 0" offset="0 0 0" />
  </assemble>
</config>
""")
    return out.getvalue()


# Keys sized by things other than the filament count, even though their
# length may coincide with it (machine limit pairs are [normal, silent]).
_NOT_PER_FILAMENT_PREFIXES = ("machine_max_", "machine_min_")
_NOT_PER_FILAMENT_KEYS = {"start_end_points"}


def _project_settings(colors: list[str]) -> str:
    template = resources.files("platesmith").joinpath("templates/project_settings.json")
    settings = json.loads(template.read_text())

    ids = settings["filament_settings_id"]
    canon = ids.index("Bambu PLA Basic @BBL X1C") if "Bambu PLA Basic @BBL X1C" in ids else 0
    n_template = len(settings["filament_colour"])
    n = len(colors)

    for key, value in settings.items():
        if key.startswith(_NOT_PER_FILAMENT_PREFIXES) or key in _NOT_PER_FILAMENT_KEYS:
            continue
        if isinstance(value, list) and len(value) == n_template:
            settings[key] = [value[canon]] * n

    settings["filament_colour"] = colors
    settings["default_filament_colour"] = [""] * n
    settings["filament_map"] = ["1"] * n
    # One entry per preset: [print, filament 1..n, printer]
    settings["different_settings_to_system"] = [""] * (n + 2)
    settings["inherits_group"] = [""] * (n + 2)
    settings["flush_volumes_matrix"] = [
        "0" if i == j else "300" for i in range(n) for j in range(n)
    ]
    settings["flush_volumes_vector"] = ["140"] * (2 * n)
    return json.dumps(settings, indent=4)


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-4" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"/>
 <Relationship Target="/Metadata/plate_1_small.png" Id="rel-5" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-small"/>
</Relationships>
"""

_MODEL_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""

_SLICE_INFO = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="{APP_VERSION}"/>
  </header>
</config>
"""

_CUT_INFORMATION = """<?xml version="1.0" encoding="utf-8"?>
<objects>
 <object id="1">
  <cut_id id="0" check_sum="1" connectors_cnt="0"/>
 </object>
</objects>"""

_FILAMENT_SEQUENCE = '{"plate_1":{"sequence":[]}}'


def write_3mf(name: str, parts: list[Part]) -> bytes:
    """Build a Bambu Studio project 3MF from colored mesh parts."""
    colors: list[str] = []
    extruders: list[int] = []
    for part in parts:
        color = part.color.upper()
        if color not in colors:
            colors.append(color)
        extruders.append(colors.index(color) + 1)
    if len(colors) > 16:
        raise ValueError(f"{len(colors)} distinct colors — Bambu Studio supports at most 16 filaments.")

    footprints = [(p.geometry, p.color) for p in parts]
    plate_png = render_top_view(footprints, 512)
    plate_png_small = render_top_view(footprints, 128)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", _root_model(name, len(parts)))
        zf.writestr("3D/_rels/3dmodel.model.rels", _MODEL_RELS)
        zf.writestr("3D/Objects/object_1.model", _object_file(parts))
        zf.writestr("Metadata/model_settings.config", _model_settings(name, parts, extruders))
        zf.writestr("Metadata/project_settings.config", _project_settings(colors))
        zf.writestr("Metadata/slice_info.config", _SLICE_INFO)
        zf.writestr("Metadata/cut_information.xml", _CUT_INFORMATION)
        zf.writestr("Metadata/filament_sequence.json", _FILAMENT_SEQUENCE)
        zf.writestr("Metadata/plate_1.png", plate_png)
        zf.writestr("Metadata/plate_1_small.png", plate_png_small)
        zf.writestr("Metadata/plate_no_light_1.png", plate_png)
    return buf.getvalue()

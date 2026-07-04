"""Generate the Platesmith logo: an isometric plate with extruded shapes."""
import math
from shapely import unary_union
from shapely.geometry import Polygon, Point, box
from shapely.affinity import translate

COS30, SIN30 = math.cos(math.pi / 6), math.sin(math.pi / 6)


def iso(poly, cx=256.0, cy=246.0, rise=0.0):
    """Project a 2D ground-plane polygon isometrically into screen space."""
    def pt(x, y):
        return ((x - y) * COS30 + cx, (x + y) * SIN30 + cy - rise)
    return Polygon(
        [pt(x, y) for x, y in poly.exterior.coords],
        [[pt(x, y) for x, y in ring.coords] for ring in poly.interiors],
    )


def swept_sides(top, depth, steps=24):
    """Screen-space region of the extrusion side walls below a top face."""
    layers = [translate(top, 0, depth * i / steps) for i in range(steps + 1)]
    return unary_union(layers).difference(top)


def path_d(geom, prec=2):
    polys = geom.geoms if hasattr(geom, "geoms") else [geom]
    cmds = []
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            pts = list(ring.coords)[:-1]
            cmds.append("M" + "L".join(f"{x:.{prec}f} {y:.{prec}f}" for x, y in pts) + "Z")
    return "".join(cmds)


def rounded_rect(w, h, r, quad=24):
    return box(-(w / 2 - r), -(h / 2 - r), w / 2 - r, h / 2 - r).buffer(r, quad_segs=quad)


def star(cx, cy, r_out, r_in, points=5, rot=-90):
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180 / points)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return Polygon(pts)


PLATE_D, STAR_D, DOT_D = 30, 22, 22

plate = rounded_rect(228, 228, 62)
plate_top = iso(plate)
plate_side = swept_sides(plate_top, PLATE_D)

star_shape = star(-18, -22, 74, 31)
star_top = iso(star_shape, rise=STAR_D)
star_side = swept_sides(star_top, STAR_D).intersection(
    unary_union([plate_top, translate(plate_top, 0, -400)]).buffer(0)
)
# clip not needed: star sits fully on the plate; keep raw sides
star_side = swept_sides(star_top, STAR_D)

dot_shape = Point(62, 58).buffer(26, quad_segs=24)
dot_top = iso(dot_shape, rise=DOT_D)
dot_side = swept_sides(dot_top, DOT_D)

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
 <defs>
  <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
   <stop offset="0" stop-color="#262b36"/><stop offset="1" stop-color="#171a20"/>
  </linearGradient>
  <linearGradient id="ptop" x1="0" y1="0" x2="1" y2="1">
   <stop offset="0" stop-color="#57a5ff"/><stop offset="1" stop-color="#2563eb"/>
  </linearGradient>
  <linearGradient id="stop" x1="0" y1="0" x2="0" y2="1">
   <stop offset="0" stop-color="#ffd75e"/><stop offset="1" stop-color="#f5a623"/>
  </linearGradient>
 </defs>
 <rect width="512" height="512" rx="104" fill="url(#bg)"/>
 <rect x="6" y="6" width="500" height="500" rx="98" fill="none" stroke="#ffffff" stroke-opacity="0.07" stroke-width="4"/>
 <ellipse cx="256" cy="388" rx="164" ry="32" fill="#000000" opacity="0.22"/>
 <path d="{path_d(plate_side)}" fill="#1a3576" fill-rule="evenodd"/>
 <path d="{path_d(plate_top)}" fill="url(#ptop)" fill-rule="evenodd"/>
 <path d="{path_d(dot_side)}" fill="#a02626" fill-rule="evenodd"/>
 <path d="{path_d(dot_top)}" fill="#ef4444" fill-rule="evenodd"/>
 <path d="{path_d(star_side)}" fill="#b97d12" fill-rule="evenodd"/>
 <path d="{path_d(star_top)}" fill="url(#stop)" fill-rule="evenodd"/>
</svg>
"""
out = "/home/brendankiu/projects/svgbuilder/platesmith/static/logo.svg"
open(out, "w").write(svg)
print(out, len(svg), "bytes")

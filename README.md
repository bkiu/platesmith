<p align="center"><img src="platesmith/static/logo.svg" width="150" alt="Platesmith logo"></p>

# Platesmith

A local web app that forges SVG files into multi-color 3MF projects for
Bambu Lab printers. Design a base plate, drop SVGs onto it, set sizes,
colors and thicknesses, preview in 3D, and export a `.3mf` that opens
directly in Bambu Studio with all filament colors already assigned.

## Run

From an RPM install:

```sh
platesmith --host 0.0.0.0        # or just `platesmith` for localhost only
systemctl --user enable --now platesmith   # …or run it as a service
```

From this source tree:

```sh
uv run platesmith
```

Then open <http://127.0.0.1:8137>.

## Using the editor

- **Base plate** — set width/height in the sidebar or drag the edge/corner
  handles after clicking the plate. The corner-radius slider goes all the
  way to fully round (a square plate becomes a circle). Pick thickness and
  color in the sidebar.
- **SVG layers** — “+ Add SVG” uploads one or more SVGs. Each layer can be
  dragged to move, corner-dragged to resize, and rotated with the round
  handle (Shift snaps to 15°). Width, thickness, color, position and
  rotation are also editable as numbers. Arrow keys nudge (Shift = 5 mm),
  Delete removes.
- The canvas preview shows the *actual* geometry that will be exported —
  outlines are computed server-side by the same code that builds the mesh.
- The **3D toggle** (top-right) shows the design extruded on a printer bed —
  drag to orbit, scroll to zoom, right-drag to pan. Sidebar edits update the
  3D scene live; switch back to 2D to move/resize things. The 3D meshes come
  from the same extrusion pipeline as the export (three.js is vendored in
  `platesmith/static/vendor/`, so no internet access is needed).
- **Export 3MF** downloads the project file. Layers sit on top of the plate;
  each distinct color becomes a filament slot in Bambu Studio.
- The design autosaves to the browser's localStorage.

## SVG notes

- Filled shapes are extruded; holes (letter counters etc.) are preserved.
- Stroked lines are turned into solid outlines using their stroke width.
- Text elements are ignored — convert text to paths first
  (Inkscape: *Path → Object to Path*).

## Output format

The exporter writes a Bambu Studio project package (production-extension
3MF with `Metadata/model_settings.config` mapping each part to a filament
slot and `Metadata/project_settings.config` carrying the filament colors).
The printer/process profile is templated from a clean Bambu Lab P1S
0.4-nozzle project saved by Bambu Studio 2.5
(`platesmith/templates/project_settings.json`); regenerate that file by
round-tripping any project of yours through Bambu Studio if you want
different defaults.

## Docker

```sh
docker run -d --name platesmith -p 8137:8137 ghcr.io/bkiu/platesmith:latest
```

Or build locally (`podman` works too):

```sh
docker build -t platesmith .
docker run -d --name platesmith -p 8137:8137 platesmith
```

The image runs as a non-root user and listens on `0.0.0.0:8137`.

## Building the RPM

```sh
./packaging/build-rpm.sh    # uses podman, produces dist/rpm/platesmith-*.noarch.rpm
```

Install with `sudo dnf install ./dist/rpm/platesmith-*.noarch.rpm`, then run
`platesmith` directly or `systemctl --user enable --now platesmith`.

## Development

```sh
uv run pytest          # includes lib3mf validation of exported meshes
```

Pipeline: `svgelements` parses SVGs → shapely polygons (even-odd fill,
stroke buffering) → constrained Delaunay triangulation → watertight
extruded meshes → zipped Bambu project.

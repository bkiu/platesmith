/* svg3mf editor
 *
 * All canvas coordinates are millimeters, origin at the plate center,
 * y pointing down (SVG convention). The server flips y for the printer.
 * Item previews use the exact polygon outlines computed by the server,
 * so the canvas is WYSIWYG for the exported geometry.
 */

"use strict";

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const SVGNS = "http://www.w3.org/2000/svg";
const STORAGE_KEY = "svg3mf-scene-v1";

const state = {
  name: "My design",
  plate: { width: 100, height: 60, radius: 6, thickness: 2, color: "#161616" },
  items: [],
};
let selection = null; // "plate" | item id | null
let view = { x: -80, y: -55, w: 160, h: 110 };
let nextId = 1;
let viewMode = "2d";
let viewer = null; // lazily imported viewer3d module

/* ---------- helpers ---------- */

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = msg;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), isError ? 8000 : 5000);
}

function clientToMm(evt) {
  const pt = new DOMPoint(evt.clientX, evt.clientY);
  return pt.matrixTransform(canvas.getScreenCTM().inverse());
}

function selectedItem() {
  return state.items.find((i) => i.id === selection) || null;
}

function itemHeightMm(item) {
  const bw = item.bbox[2] - item.bbox[0];
  const bh = item.bbox[3] - item.bbox[1];
  return item.width * (bh / bw);
}

function maxRadius() {
  return Math.min(state.plate.width, state.plate.height) / 2;
}

let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ state, nextId }));
    } catch (e) { /* quota — skip autosave */ }
  }, 300);
}

function load() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    Object.assign(state, data.state);
    nextId = data.nextId || 1;
  } catch (e) { /* corrupted — start fresh */ }
}

/* ---------- rendering ---------- */

function applyView() {
  canvas.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
  const bg = $("grid-bg");
  bg.setAttribute("x", view.x); bg.setAttribute("y", view.y);
  bg.setAttribute("width", view.w); bg.setAttribute("height", view.h);
}

function handlePx(mm = 8) {
  return (mm * view.w) / canvas.clientWidth;
}

function itemTransform(item) {
  const bw = item.bbox[2] - item.bbox[0];
  const cx = (item.bbox[0] + item.bbox[2]) / 2;
  const cy = (item.bbox[1] + item.bbox[3]) / 2;
  const k = item.width / bw;
  return `translate(${item.x} ${item.y}) rotate(${item.rotation}) scale(${k}) translate(${-cx} ${-cy})`;
}

function render() {
  if (viewer && viewMode === "3d") {
    viewer.sync(state, (id) => state.items.find((i) => i.id === id)?.svg);
  }
  applyView();

  const p = state.plate;
  const plate = $("plate");
  plate.setAttribute("x", -p.width / 2);
  plate.setAttribute("y", -p.height / 2);
  plate.setAttribute("width", p.width);
  plate.setAttribute("height", p.height);
  plate.setAttribute("rx", clamp(p.radius, 0, maxRadius()));
  plate.setAttribute("fill", p.color);
  plate.dataset.role = "plate";
  plate.classList.toggle("selected", selection === "plate");

  const itemsG = $("items");
  itemsG.replaceChildren();
  for (const item of state.items) {
    const g = svgEl("g", { class: "item-g" + (item.id === selection ? " selected" : "") });
    const path = svgEl("path", {
      class: "item-path",
      d: item.path,
      fill: item.color,
      "fill-rule": "evenodd",
      transform: itemTransform(item),
    });
    path.dataset.role = "item";
    path.dataset.id = item.id;
    g.appendChild(path);
    itemsG.appendChild(g);
  }

  renderOverlay();
  renderSidebar();
}

function renderOverlay() {
  const ov = $("overlay");
  ov.replaceChildren();
  const hs = handlePx(8);

  const addHandle = (parent, x, y, name, cursor) => {
    const r = svgEl("rect", {
      class: "handle", x: x - hs / 2, y: y - hs / 2, width: hs, height: hs,
      rx: hs / 5, style: `cursor:${cursor}`,
    });
    r.dataset.role = "handle";
    r.dataset.handle = name;
    parent.appendChild(r);
  };

  if (selection === "plate") {
    const { width: w, height: h } = state.plate;
    const g = svgEl("g");
    g.appendChild(svgEl("rect", { class: "sel-box", x: -w / 2, y: -h / 2, width: w, height: h }));
    for (const [name, x, y, cur] of [
      ["nw", -w / 2, -h / 2, "nwse-resize"], ["ne", w / 2, -h / 2, "nesw-resize"],
      ["sw", -w / 2, h / 2, "nesw-resize"], ["se", w / 2, h / 2, "nwse-resize"],
      ["n", 0, -h / 2, "ns-resize"], ["s", 0, h / 2, "ns-resize"],
      ["w", -w / 2, 0, "ew-resize"], ["e", w / 2, 0, "ew-resize"],
    ]) addHandle(g, x, y, name, cur);
    ov.appendChild(g);
  }

  const item = selectedItem();
  if (item) {
    const w = item.width, h = itemHeightMm(item);
    const rotOff = handlePx(22);
    const g = svgEl("g", { transform: `translate(${item.x} ${item.y}) rotate(${item.rotation})` });
    g.appendChild(svgEl("rect", { class: "sel-box", x: -w / 2, y: -h / 2, width: w, height: h }));
    g.appendChild(svgEl("line", { class: "rot-stick", x1: 0, y1: -h / 2, x2: 0, y2: -h / 2 - rotOff }));
    const rot = svgEl("circle", {
      class: "handle rot", cx: 0, cy: -h / 2 - rotOff, r: hs / 1.6, style: "cursor:grab",
    });
    rot.dataset.role = "handle";
    rot.dataset.handle = "rot";
    g.appendChild(rot);
    for (const [name, x, y, cur] of [
      ["nw", -w / 2, -h / 2, "nwse-resize"], ["ne", w / 2, -h / 2, "nesw-resize"],
      ["sw", -w / 2, h / 2, "nesw-resize"], ["se", w / 2, h / 2, "nwse-resize"],
    ]) addHandle(g, x, y, name, cur);
    ov.appendChild(g);
  }
}

function renderSidebar() {
  $("design-name").value = state.name;
  const p = state.plate;
  if (document.activeElement !== $("plate-w")) $("plate-w").value = p.width;
  if (document.activeElement !== $("plate-h")) $("plate-h").value = p.height;
  if (document.activeElement !== $("plate-t")) $("plate-t").value = p.thickness;
  $("plate-color").value = p.color;
  const r = $("plate-r");
  r.max = maxRadius();
  r.value = clamp(p.radius, 0, maxRadius());
  $("plate-r-val").textContent =
    p.radius >= maxRadius() ? `${maxRadius().toFixed(1)} mm (full)` : `${(+r.value).toFixed(1)} mm`;

  const list = $("item-list");
  list.replaceChildren();
  if (!state.items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No SVGs yet — click “+ Add SVG”.";
    list.appendChild(li);
  }
  for (const item of state.items) {
    const li = document.createElement("li");
    li.classList.toggle("selected", item.id === selection);
    const sw = document.createElement("span");
    sw.className = "swatch";
    sw.style.background = item.color;
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = item.name;
    const dims = document.createElement("span");
    dims.className = "dims";
    dims.textContent = `${item.width.toFixed(0)}×${itemHeightMm(item).toFixed(0)}`;
    li.append(sw, name, dims);
    li.addEventListener("click", () => { selection = item.id; render(); });
    list.appendChild(li);
  }

  const item = selectedItem();
  $("item-props").hidden = !item;
  if (item) {
    const set = (id, v) => { if (document.activeElement !== $(id)) $(id).value = v; };
    set("item-w", +item.width.toFixed(1));
    $("item-h").textContent = itemHeightMm(item).toFixed(1) + " mm";
    set("item-t", item.thickness);
    $("item-color").value = item.color;
    set("item-x", +item.x.toFixed(1));
    set("item-y", +item.y.toFixed(1));
    set("item-rot", +item.rotation.toFixed(0));
  }
}

function fitView() {
  const p = state.plate;
  let w = p.width * 1.5, h = p.height * 1.5;
  const aspect = canvas.clientWidth / canvas.clientHeight;
  if (w / h < aspect) w = h * aspect; else h = w / aspect;
  view = { x: -w / 2, y: -h / 2, w, h };
  render();
}

/* ---------- pointer interaction ---------- */

let drag = null;

canvas.addEventListener("pointerdown", (evt) => {
  if (evt.button !== 0 && evt.button !== 1) return;
  const role = evt.target.dataset && evt.target.dataset.role;
  const pt = clientToMm(evt);
  canvas.setPointerCapture(evt.pointerId);

  if (evt.button === 1 || !role) {
    drag = { type: "pan", startX: evt.clientX, startY: evt.clientY, view: { ...view } };
    if (evt.button === 0 && !role) { selection = null; render(); }
    return;
  }

  if (role === "plate") {
    selection = "plate";
    drag = { type: "resize-plate", handle: null }; // click only selects; drag via handles
    render();
    return;
  }

  if (role === "item") {
    const id = Number(evt.target.dataset.id);
    selection = id;
    const item = selectedItem();
    drag = { type: "move-item", start: pt, itemX: item.x, itemY: item.y };
    render();
    return;
  }

  if (role === "handle") {
    const name = evt.target.dataset.handle;
    if (selection === "plate") {
      drag = { type: "resize-plate", handle: name };
    } else {
      const item = selectedItem();
      if (!item) return;
      if (name === "rot") {
        const a = Math.atan2(pt.y - item.y, pt.x - item.x) * 180 / Math.PI;
        drag = { type: "rotate-item", startAngle: a, itemRot: item.rotation };
      } else {
        const d = Math.hypot(pt.x - item.x, pt.y - item.y);
        drag = { type: "scale-item", startDist: Math.max(d, 0.01), itemW: item.width };
      }
    }
  }
});

canvas.addEventListener("pointermove", (evt) => {
  if (!drag) return;
  const p = state.plate;

  if (drag.type === "pan") {
    const kx = view.w / canvas.clientWidth;
    view.x = drag.view.x - (evt.clientX - drag.startX) * kx;
    view.y = drag.view.y - (evt.clientY - drag.startY) * kx;
    applyView();
    return;
  }

  const pt = clientToMm(evt);

  if (drag.type === "move-item") {
    const item = selectedItem();
    if (!item) return;
    item.x = drag.itemX + (pt.x - drag.start.x);
    item.y = drag.itemY + (pt.y - drag.start.y);
  } else if (drag.type === "scale-item") {
    const item = selectedItem();
    if (!item) return;
    const d = Math.hypot(pt.x - item.x, pt.y - item.y);
    item.width = clamp(drag.itemW * (d / drag.startDist), 1, 400);
  } else if (drag.type === "rotate-item") {
    const item = selectedItem();
    if (!item) return;
    const a = Math.atan2(pt.y - item.y, pt.x - item.x) * 180 / Math.PI;
    let rot = drag.itemRot + (a - drag.startAngle);
    rot = evt.shiftKey ? Math.round(rot / 15) * 15 : Math.round(rot * 10) / 10;
    item.rotation = ((rot % 360) + 360) % 360;
  } else if (drag.type === "resize-plate" && drag.handle) {
    const h = drag.handle;
    if (h.includes("e") || h.includes("w")) p.width = clamp(Math.abs(pt.x) * 2, 5, 256);
    if (h.includes("n") || h.includes("s")) p.height = clamp(Math.abs(pt.y) * 2, 5, 256);
    p.radius = clamp(p.radius, 0, maxRadius());
  } else {
    return;
  }
  render();
  save();
});

canvas.addEventListener("pointerup", () => { drag = null; });
canvas.addEventListener("pointercancel", () => { drag = null; });

canvas.addEventListener("wheel", (evt) => {
  evt.preventDefault();
  const pt = clientToMm(evt);
  const k = Math.pow(1.0015, evt.deltaY);
  const newW = clamp(view.w * k, 10, 2000);
  const scale = newW / view.w;
  view.x = pt.x - (pt.x - view.x) * scale;
  view.y = pt.y - (pt.y - view.y) * scale;
  view.w *= scale;
  view.h *= scale;
  render();
}, { passive: false });

window.addEventListener("keydown", (evt) => {
  if (/INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
  const item = selectedItem();
  if ((evt.key === "Delete" || evt.key === "Backspace") && item) {
    state.items = state.items.filter((i) => i !== item);
    selection = null;
    render(); save();
    evt.preventDefault();
  }
  if (item && evt.key.startsWith("Arrow")) {
    const step = evt.shiftKey ? 5 : 0.5;
    if (evt.key === "ArrowLeft") item.x -= step;
    if (evt.key === "ArrowRight") item.x += step;
    if (evt.key === "ArrowUp") item.y -= step;
    if (evt.key === "ArrowDown") item.y += step;
    render(); save();
    evt.preventDefault();
  }
});

/* ---------- sidebar wiring ---------- */

function num(id, fallback) {
  const v = parseFloat($(id).value);
  return Number.isFinite(v) ? v : fallback;
}

$("design-name").addEventListener("input", () => { state.name = $("design-name").value; save(); });

for (const [id, key, lo, hi] of [
  ["plate-w", "width", 5, 256],
  ["plate-h", "height", 5, 256],
  ["plate-t", "thickness", 0.4, 50],
]) {
  $(id).addEventListener("input", () => {
    state.plate[key] = clamp(num(id, state.plate[key]), lo, hi);
    state.plate.radius = clamp(state.plate.radius, 0, maxRadius());
    render(); save();
  });
}
$("plate-r").addEventListener("input", () => {
  state.plate.radius = clamp(parseFloat($("plate-r").value), 0, maxRadius());
  render(); save();
});
$("plate-color").addEventListener("input", () => {
  state.plate.color = $("plate-color").value;
  render(); save();
});

function bindItemInput(id, fn) {
  $(id).addEventListener("input", () => {
    const item = selectedItem();
    if (!item) return;
    fn(item);
    render(); save();
  });
}
bindItemInput("item-w", (i) => { i.width = clamp(num("item-w", i.width), 1, 400); });
bindItemInput("item-t", (i) => { i.thickness = clamp(num("item-t", i.thickness), 0.2, 50); });
bindItemInput("item-color", (i) => { i.color = $("item-color").value; });
bindItemInput("item-x", (i) => { i.x = num("item-x", i.x); });
bindItemInput("item-y", (i) => { i.y = num("item-y", i.y); });
bindItemInput("item-rot", (i) => { i.rotation = num("item-rot", i.rotation); });

$("item-dup").addEventListener("click", () => {
  const item = selectedItem();
  if (!item) return;
  const copy = { ...item, id: nextId++, x: item.x + 5, y: item.y + 5 };
  state.items.push(copy);
  selection = copy.id;
  render(); save();
});
$("item-del").addEventListener("click", () => {
  state.items = state.items.filter((i) => i.id !== selection);
  selection = null;
  render(); save();
});

$("fit").addEventListener("click", fitView);
$("add-svg").addEventListener("click", () => $("file-input").click());

/* ---------- 2D / 3D view toggle ---------- */

async function setViewMode(mode) {
  if (mode === viewMode) return;
  if (mode === "3d" && !viewer) {
    try {
      viewer = await import("/static/viewer3d.js");
      viewer.init($("view3d"));
    } catch (e) {
      viewer = null;
      toast(`3D view unavailable: ${e.message}`, true);
      return;
    }
    viewer.frame(state.plate);
  }
  viewMode = mode;
  $("view-2d").classList.toggle("active", mode === "2d");
  $("view-3d").classList.toggle("active", mode === "3d");
  $("view3d").hidden = mode !== "3d";
  $("canvas").style.visibility = mode === "3d" ? "hidden" : "";
  $("hint").textContent = mode === "3d"
    ? "Drag to orbit · scroll to zoom · right-drag to pan · switch to 2D to edit"
    : "Drag to move · corners to resize · scroll to zoom · drag background to pan";
  viewer?.setActive(mode === "3d");
  render();
}

$("view-2d").addEventListener("click", () => setViewMode("2d"));
$("view-3d").addEventListener("click", () => setViewMode("3d"));

$("file-input").addEventListener("change", async (evt) => {
  for (const file of evt.target.files) await addSvgFile(file);
  evt.target.value = "";
});

async function addSvgFile(file) {
  const text = await file.text();
  let data;
  try {
    const res = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ svg: text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    data = await res.json();
  } catch (e) {
    toast(`${file.name}: ${e.message}`, true);
    return;
  }
  for (const w of data.warnings) toast(`${file.name}: ${w}`);
  const item = {
    id: nextId++,
    name: file.name.replace(/\.svg$/i, ""),
    svg: text,
    color: "#FFFFFF",
    width: Math.round(Math.min(state.plate.width, state.plate.height) * 0.6),
    thickness: 1.2,
    x: 0, y: 0, rotation: 0,
    path: data.path,
    bbox: data.bbox,
  };
  state.items.push(item);
  selection = item.id;
  render(); save();
}

$("export").addEventListener("click", async () => {
  const btn = $("export");
  btn.disabled = true;
  btn.textContent = "Exporting…";
  try {
    const payload = {
      name: state.name,
      plate: state.plate,
      items: state.items.map((i) => ({
        svg: i.svg, name: i.name, color: i.color, width: i.width,
        thickness: i.thickness, x: i.x, y: i.y, rotation: i.rotation,
      })),
    };
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (state.name.replace(/[^\w\- ]/g, "").trim() || "design") + ".3mf";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("3MF exported — open it in Bambu Studio.");
  } catch (e) {
    toast(`Export failed: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Export 3MF";
  }
});

/* ---------- boot ---------- */

load();
window.addEventListener("resize", render);
fitView();

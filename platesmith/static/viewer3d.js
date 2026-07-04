/* 3D preview of the design using three.js.
 *
 * Meshes come from /api/mesh and /api/plate-mesh — the same extrusion
 * pipeline used for the 3MF export — at unit height, so thickness, size,
 * rotation and position are applied here as cheap matrix transforms.
 *
 * Coordinates: printer convention, z up, y north (editor y is flipped).
 */

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

let renderer, scene, camera, controls, running = false;
let plateMesh = null;
let plateKey = "";          // "w,h,r" of the geometry currently shown
let plateFetchTimer = null;
const itemMeshes = new Map();   // item id -> THREE.Mesh
const geomCache = new Map();    // item id -> THREE.BufferGeometry
const geomPending = new Set();  // item ids with an in-flight fetch

const EMBED = 0.02; // sink items slightly into the plate to avoid z-fighting

function toGeometry(data) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(data.vertices, 3));
  g.setIndex(data.indices);
  return g;
}

function material(color) {
  return new THREE.MeshStandardMaterial({
    color, roughness: 0.55, metalness: 0.05, flatShading: true,
  });
}

export function init(container) {
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x16181d);

  camera = new THREE.PerspectiveCamera(40, 1, 0.5, 4000);
  camera.up.set(0, 0, 1);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.55; // don't go far below the bed

  scene.add(new THREE.HemisphereLight(0xcfd8ff, 0x30343c, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(120, -160, 220);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const sc = sun.shadow.camera;
  sc.left = sc.bottom = -200;
  sc.right = sc.top = 200;
  sc.far = 800;
  scene.add(sun);

  // Printer bed for context: 256x256 P1S plate, 10 mm grid.
  const bed = new THREE.Mesh(
    new THREE.PlaneGeometry(256, 256),
    new THREE.MeshStandardMaterial({ color: 0x23262d, roughness: 0.95 })
  );
  bed.position.z = -0.1;
  bed.receiveShadow = true;
  scene.add(bed);
  const grid = new THREE.GridHelper(250, 25, 0x3a3f4b, 0x2b2f38);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = 0.01 - 0.1;
  scene.add(grid);

  const resize = () => {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  new ResizeObserver(resize).observe(container);
  resize();
}

export function frame(plate) {
  const dist = Math.max(plate.width, plate.height, 60) * 1.9;
  camera.position.set(0, -dist * 0.85, dist * 0.7);
  controls.target.set(0, 0, plate.thickness);
  controls.update();
}

export function setActive(active) {
  running = active;
  if (active) loop();
}

function loop() {
  if (!running) return;
  requestAnimationFrame(loop);
  controls.update();
  renderer.render(scene, camera);
}

async function fetchJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function syncPlate(plate) {
  const key = `${plate.width},${plate.height},${plate.radius}`;
  if (key !== plateKey) {
    plateKey = key;
    clearTimeout(plateFetchTimer);
    plateFetchTimer = setTimeout(async () => {
      try {
        const data = await fetchJson("/api/plate-mesh", {
          width: plate.width, height: plate.height, radius: plate.radius,
        });
        if (plateKey !== key) return; // superseded while fetching
        const geom = toGeometry(data);
        if (!plateMesh) {
          plateMesh = new THREE.Mesh(geom, material(plate.color));
          plateMesh.castShadow = plateMesh.receiveShadow = true;
          scene.add(plateMesh);
        } else {
          plateMesh.geometry.dispose();
          plateMesh.geometry = geom;
        }
      } catch (e) { /* transient; next change retries */ plateKey = ""; }
    }, plateMesh ? 150 : 0);
  }
  if (plateMesh) {
    plateMesh.scale.set(1, 1, plate.thickness);
    plateMesh.material.color.set(plate.color);
  }
}

function syncItems(state, getSvg) {
  const seen = new Set();
  for (const item of state.items) {
    seen.add(item.id);
    let mesh = itemMeshes.get(item.id);
    if (!mesh) {
      const geom = geomCache.get(item.id);
      if (!geom) {
        if (!geomPending.has(item.id)) {
          geomPending.add(item.id);
          fetchJson("/api/mesh", { svg: getSvg(item.id) })
            .then((data) => geomCache.set(item.id, toGeometry(data)))
            .catch(() => {})
            .finally(() => geomPending.delete(item.id));
        }
        continue;
      }
      mesh = new THREE.Mesh(geom, material(item.color));
      mesh.castShadow = mesh.receiveShadow = true;
      itemMeshes.set(item.id, mesh);
      scene.add(mesh);
    }
    const k = item.width / (item.bbox[2] - item.bbox[0]);
    mesh.scale.set(k, k, item.thickness + EMBED);
    mesh.rotation.z = (-item.rotation * Math.PI) / 180;
    mesh.position.set(item.x, -item.y, state.plate.thickness - EMBED);
    mesh.material.color.set(item.color);
  }
  for (const [id, mesh] of itemMeshes) {
    if (!seen.has(id)) {
      scene.remove(mesh);
      mesh.material.dispose();
      itemMeshes.delete(id);
      geomCache.get(id)?.dispose();
      geomCache.delete(id);
    }
  }
}

let pollTimer = null;

/** Reconcile the 3D scene with editor state. Safe to call on every change;
 *  re-polls briefly while item meshes are still being fetched. */
export function sync(state, getSvg) {
  syncPlate(state.plate);
  syncItems(state, getSvg);
  const missing = state.items.some((i) => !itemMeshes.has(i.id));
  clearTimeout(pollTimer);
  if (missing && running) {
    pollTimer = setTimeout(() => sync(state, getSvg), 250);
  }
}

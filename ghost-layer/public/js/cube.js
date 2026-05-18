import * as THREE from 'three';

// ── Scene setup ──────────────────────────────────────────────────────────────
const scene    = new THREE.Scene();
const camera   = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
document.body.appendChild(renderer.domElement);

// ── Rubik's cube geometry ────────────────────────────────────────────────────
const FACE_COLORS = {
  xrpl:    { px: 0x00FFCC, nx: 0xFF0055, py: 0xAA00FF, ny: 0x00FF88, pz: 0xFFFF00, nz: 0xFFFFFF },
  base:    { px: 0x6644FF, nx: 0xFF4499, py: 0xFF6600, ny: 0x00BBFF, pz: 0xFFEE00, nz: 0xEEEEEE },
  default: { px: 0x00FFCC, nx: 0xFF0055, py: 0xAA00FF, ny: 0x00FF00, pz: 0xFFFF00, nz: 0xFFFFFF },
};

const cubeGroup  = new THREE.Group();
const allMeshes  = [];
const geo        = new THREE.BoxGeometry(0.93, 0.93, 0.93);
const scheme     = FACE_COLORS.default;

function makeMaterial(color, opacity = 1) {
  return new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity });
}

for (let x = -1; x <= 1; x++) {
  for (let y = -1; y <= 1; y++) {
    for (let z = -1; z <= 1; z++) {
      const m = [
        makeMaterial(x ===  1 ? scheme.px : 0x050505),
        makeMaterial(x === -1 ? scheme.nx : 0x050505),
        makeMaterial(y ===  1 ? scheme.py : 0x050505),
        makeMaterial(y === -1 ? scheme.ny : 0x050505),
        makeMaterial(z ===  1 ? scheme.pz : 0x050505),
        makeMaterial(z === -1 ? scheme.nz : 0x050505),
      ];
      const mesh = new THREE.Mesh(geo, m);
      mesh.position.set(x, y, z);
      cubeGroup.add(mesh);
      allMeshes.push({ mesh, x, y, z });
    }
  }
}
scene.add(cubeGroup);
camera.position.z = 5;

// ── Stats overlay DOM ────────────────────────────────────────────────────────
const overlay     = document.getElementById('terminal-overlay');
const statusEl    = document.getElementById('gl-status');
const countEl     = document.getElementById('gl-count');
const chainEl     = document.getElementById('gl-chain');
const txEl        = document.getElementById('gl-tx');
const speedEl     = document.getElementById('gl-speed');
const tachFill    = document.getElementById('tach-fill');

function setStatus(online) {
  if (!statusEl) return;
  statusEl.textContent = online ? '● LIVE' : '○ OFFLINE';
  statusEl.style.color = online ? '#00FFCC' : '#FF0055';
}

function updateOverlay(data) {
  if (countEl) countEl.textContent = data.total_bridges ?? '–';
  if (chainEl) chainEl.textContent = (data.chain ?? '–').toUpperCase();
  if (txEl && data.tx_hash) txEl.textContent = data.tx_hash.slice(0, 16) + '…';
}

// ── Tachometer state ─────────────────────────────────────────────────────────
let rotSpeed       = 0.003;          // current radians/frame on each axis
const BASE_SPEED   = 0.003;
const SPIKE_SPEED  = 0.06;
const DECAY        = 0.97;           // per-frame decay factor

let pulseIntensity = 0;              // 0–1, drives face brightness flash
let pulseChain     = 'default';      // which color scheme to flash

function onBridgeEvent(data) {
  rotSpeed     = SPIKE_SPEED;
  pulseIntensity = 1.0;
  pulseChain   = data.chain === 'base' ? 'base' : 'xrpl';
  updateOverlay(data);
}

// ── Face color flash ─────────────────────────────────────────────────────────
function applyPulse(intensity) {
  const cs = FACE_COLORS[pulseChain];
  for (const { mesh, x, y, z } of allMeshes) {
    // Only outer-facing faces carry color; inner cubies stay dark
    const targets = [
      { mat: mesh.material[0], base: x ===  1 ? cs.px : null },
      { mat: mesh.material[1], base: x === -1 ? cs.nx : null },
      { mat: mesh.material[2], base: y ===  1 ? cs.py : null },
      { mat: mesh.material[3], base: y === -1 ? cs.ny : null },
      { mat: mesh.material[4], base: z ===  1 ? cs.pz : null },
      { mat: mesh.material[5], base: z === -1 ? cs.nz : null },
    ];
    for (const { mat, base } of targets) {
      if (base !== null) {
        const c = new THREE.Color(base);
        c.lerp(new THREE.Color(0xffffff), intensity * 0.5);
        mat.color.set(c);
      }
    }
  }
}

function resetFaceColors() {
  for (const { mesh, x, y, z } of allMeshes) {
    mesh.material[0].color.setHex(x ===  1 ? scheme.px : 0x050505);
    mesh.material[1].color.setHex(x === -1 ? scheme.nx : 0x050505);
    mesh.material[2].color.setHex(y ===  1 ? scheme.py : 0x050505);
    mesh.material[3].color.setHex(y === -1 ? scheme.ny : 0x050505);
    mesh.material[4].color.setHex(z ===  1 ? scheme.pz : 0x050505);
    mesh.material[5].color.setHex(z === -1 ? scheme.nz : 0x050505);
  }
}

// ── SSE connection ────────────────────────────────────────────────────────────
let evtSource = null;
let reconnectDelay = 1000;

function connectSSE(url) {
  if (evtSource) evtSource.close();
  evtSource = new EventSource(url);

  evtSource.onopen = () => {
    setStatus(true);
    reconnectDelay = 1000;
  };

  evtSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === 'BRIDGE_SETTLED') {
        onBridgeEvent(data);
      } else if (data.type === 'CONNECTED') {
        if (countEl) countEl.textContent = data.total_bridges ?? '0';
      }
    } catch (_) {}
  };

  evtSource.onerror = () => {
    setStatus(false);
    evtSource.close();
    evtSource = null;
    setTimeout(() => connectSSE(url), reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };
}

// Fetch config then connect
fetch('/api/config')
  .then(r => r.json())
  .then(cfg => connectSSE(cfg.sse_url ?? '/api/events'))
  .catch(() => connectSSE('/api/events'));

// ── Resize handler ───────────────────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ── Animation loop ───────────────────────────────────────────────────────────
const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);

  // Tachometer decay
  if (rotSpeed > BASE_SPEED) {
    rotSpeed = Math.max(BASE_SPEED, rotSpeed * DECAY);
  }

  // Pulse decay
  if (pulseIntensity > 0) {
    pulseIntensity = Math.max(0, pulseIntensity - 0.018);
    applyPulse(pulseIntensity);
    if (pulseIntensity === 0) resetFaceColors();
  }

  cubeGroup.rotation.x += rotSpeed;
  cubeGroup.rotation.y += rotSpeed * 1.3;

  // Tachometer bar + speed indicator
  const pct = Math.round(((rotSpeed - BASE_SPEED) / (SPIKE_SPEED - BASE_SPEED)) * 100);
  const pctClamped = Math.max(0, Math.min(100, pct));
  if (speedEl)  speedEl.textContent = pctClamped + '%';
  if (tachFill) tachFill.style.width = pctClamped + '%';

  renderer.render(scene, camera);
}

animate();

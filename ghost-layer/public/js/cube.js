import * as THREE from 'three';

// ── Scene setup ──────────────────────────────────────────────────────────────
const scene    = new THREE.Scene();
const camera   = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
document.body.appendChild(renderer.domElement);

// ── Rubik's cube geometry ────────────────────────────────────────────────────
// Face color palettes per event chain / type
const PALETTES = {
  default: { px: 0x00FFCC, nx: 0xFF0055, py: 0xAA00FF, ny: 0x00FF00, pz: 0xFFFF00, nz: 0xFFFFFF },
  xrpl:    { px: 0x00FFCC, nx: 0xFF0055, py: 0xAA00FF, ny: 0x00FF88, pz: 0xFFFF00, nz: 0xFFFFFF },
  base:    { px: 0x6644FF, nx: 0xFF4499, py: 0xFF6600, ny: 0x00BBFF, pz: 0xFFEE00, nz: 0xEEEEEE },
  probe:   { px: 0x004466, nx: 0x002233, py: 0x003355, ny: 0x002244, pz: 0x003344, nz: 0x111111 },
  pay:     { px: 0xFF8800, nx: 0xFF4400, py: 0xFFAA00, ny: 0xFF6600, pz: 0xFFCC00, nz: 0xFF9900 },
  verdict: { px: 0x00FF88, nx: 0xFF3366, py: 0x00FFCC, ny: 0xFF0055, pz: 0x00FF44, nz: 0xFFFFFF },
  squeeze: { px: 0xFFD700, nx: 0xFFA500, py: 0xFFCC00, ny: 0xFF8C00, pz: 0xFFE500, nz: 0xFFBB00 },
};

const cubeGroup = new THREE.Group();
const allMeshes = [];
const geo       = new THREE.BoxGeometry(0.93, 0.93, 0.93);
const BASE_PAL  = PALETTES.default;

function makeMat(color) {
  return new THREE.MeshBasicMaterial({ color });
}

for (let x = -1; x <= 1; x++) {
  for (let y = -1; y <= 1; y++) {
    for (let z = -1; z <= 1; z++) {
      const m = [
        makeMat(x ===  1 ? BASE_PAL.px : 0x050505),
        makeMat(x === -1 ? BASE_PAL.nx : 0x050505),
        makeMat(y ===  1 ? BASE_PAL.py : 0x050505),
        makeMat(y === -1 ? BASE_PAL.ny : 0x050505),
        makeMat(z ===  1 ? BASE_PAL.pz : 0x050505),
        makeMat(z === -1 ? BASE_PAL.nz : 0x050505),
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

// ── DOM refs ─────────────────────────────────────────────────────────────────
const statusEl  = document.getElementById('gl-status');
const countEl   = document.getElementById('gl-count');
const chainEl   = document.getElementById('gl-chain');
const txEl      = document.getElementById('gl-tx');
const speedEl   = document.getElementById('gl-speed');
const tachFill  = document.getElementById('tach-fill');
const eventEl   = document.getElementById('gl-event');

// ── Tachometer state ─────────────────────────────────────────────────────────
const BASE_SPEED  = 0.003;
const DECAY       = 0.97;

// Each event type defines spike speed and palette
const EVENT_CFG = {
  BRIDGE_SETTLED:  { speed: 0.060, palette: 'xrpl',   label: 'SETTLED'  },
  AGENT_PROBE:     { speed: 0.008, palette: 'probe',   label: 'PROBE'    },
  AGENT_PAY:       { speed: 0.020, palette: 'pay',     label: 'INVOICE'  },
  COUNCIL_VERDICT: { speed: 0.025, palette: 'verdict', label: 'VERDICT'  },
  SQUEEZE_ALERT:   { speed: 0.030, palette: 'squeeze', label: 'SQUEEZE'  },
  OPTIONS_SWEEP:   { speed: 0.030, palette: 'squeeze', label: 'SWEEP'    },
};

let rotSpeed      = BASE_SPEED;
let pulseIntensity = 0;
let activePalette  = 'default';
let bridgeCount    = 0;

// ── Face color flash ─────────────────────────────────────────────────────────
function applyPulse(intensity) {
  const cs = PALETTES[activePalette] ?? PALETTES.default;
  for (const { mesh, x, y, z } of allMeshes) {
    const slots = [
      [0, x ===  1 ? cs.px : null],
      [1, x === -1 ? cs.nx : null],
      [2, y ===  1 ? cs.py : null],
      [3, y === -1 ? cs.ny : null],
      [4, z ===  1 ? cs.pz : null],
      [5, z === -1 ? cs.nz : null],
    ];
    for (const [i, base] of slots) {
      if (base !== null) {
        const c = new THREE.Color(base);
        c.lerp(new THREE.Color(0xffffff), intensity * 0.45);
        mesh.material[i].color.set(c);
      }
    }
  }
}

function resetFaceColors() {
  for (const { mesh, x, y, z } of allMeshes) {
    mesh.material[0].color.setHex(x ===  1 ? BASE_PAL.px : 0x050505);
    mesh.material[1].color.setHex(x === -1 ? BASE_PAL.nx : 0x050505);
    mesh.material[2].color.setHex(y ===  1 ? BASE_PAL.py : 0x050505);
    mesh.material[3].color.setHex(y === -1 ? BASE_PAL.ny : 0x050505);
    mesh.material[4].color.setHex(z ===  1 ? BASE_PAL.pz : 0x050505);
    mesh.material[5].color.setHex(z === -1 ? BASE_PAL.nz : 0x050505);
  }
}

function fireEvent(type, data) {
  const cfg = EVENT_CFG[type];
  if (!cfg) return;

  // Only override rotation if incoming spike is higher than current
  if (cfg.speed > rotSpeed) rotSpeed = cfg.speed;
  pulseIntensity = 1.0;
  activePalette  = (type === 'BRIDGE_SETTLED' && data.chain === 'base') ? 'base' : cfg.palette;

  if (eventEl) {
    eventEl.textContent = cfg.label;
    eventEl.style.color = activePalette === 'probe' ? '#334455'
                        : activePalette === 'pay'   ? '#FF8800'
                        : activePalette === 'squeeze' ? '#FFD700'
                        : '#00FFCC';
  }
  if (type === 'BRIDGE_SETTLED') {
    bridgeCount = data.total_bridges ?? bridgeCount + 1;
    if (countEl) countEl.textContent = bridgeCount;
    if (chainEl) chainEl.textContent = (data.chain ?? '–').toUpperCase();
    if (txEl && data.tx_hash) txEl.textContent = data.tx_hash.slice(0, 16) + '…';
  } else if (type === 'COUNCIL_VERDICT') {
    if (chainEl) chainEl.textContent = data.bias ?? 'VERDICT';
  } else if (type === 'AGENT_PROBE' || type === 'AGENT_PAY') {
    if (chainEl) chainEl.textContent = data.path ?? cfg.label;
  } else if (type === 'SQUEEZE_ALERT' || type === 'OPTIONS_SWEEP') {
    if (chainEl) chainEl.textContent = data.symbol ?? cfg.label;
  }
}

// ── SSE connection factory ────────────────────────────────────────────────────
function makeSSE(url, label) {
  let es = null;
  let backoff = 1000;

  function connect() {
    if (es) es.close();
    es = new EventSource(url);

    es.onopen = () => {
      if (label === 'ghost') setStatus(true);
      backoff = 1000;
    };

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.type && data.type !== 'CONNECTED') {
          fireEvent(data.type, data);
        } else if (data.type === 'CONNECTED' && data.total_bridges !== undefined) {
          bridgeCount = data.total_bridges;
          if (countEl) countEl.textContent = bridgeCount;
        }
      } catch (_) {}
    };

    es.onerror = () => {
      if (label === 'ghost') setStatus(false);
      es.close();
      es = null;
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 30000);
    };
  }

  connect();
}

function setStatus(online) {
  if (!statusEl) return;
  statusEl.textContent = online ? '● LIVE' : '○ OFFLINE';
  statusEl.style.color = online ? '#00FFCC' : '#FF0055';
}

// Bootstrap: fetch config, then connect to both SSE streams
fetch('/api/config')
  .then(r => r.json())
  .then(cfg => {
    bridgeCount = cfg.total_bridges ?? 0;
    if (countEl) countEl.textContent = bridgeCount;

    makeSSE(cfg.sse_url ?? '/api/events', 'ghost');
    if (cfg.squeezeos_sse) makeSSE(cfg.squeezeos_sse, 'squeezeos');
  })
  .catch(() => makeSSE('/api/events', 'ghost'));

// ── Resize ────────────────────────────────────────────────────────────────────
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// ── Animation loop ────────────────────────────────────────────────────────────
function animate() {
  requestAnimationFrame(animate);

  if (rotSpeed > BASE_SPEED) {
    rotSpeed = Math.max(BASE_SPEED, rotSpeed * DECAY);
  }

  if (pulseIntensity > 0) {
    pulseIntensity = Math.max(0, pulseIntensity - 0.016);
    applyPulse(pulseIntensity);
    if (pulseIntensity === 0) resetFaceColors();
  }

  cubeGroup.rotation.x += rotSpeed;
  cubeGroup.rotation.y += rotSpeed * 1.3;

  const pct = Math.round(((rotSpeed - BASE_SPEED) / (0.060 - BASE_SPEED)) * 100);
  const p   = Math.max(0, Math.min(100, pct));
  if (speedEl)  speedEl.textContent = p + '%';
  if (tachFill) tachFill.style.width = p + '%';

  renderer.render(scene, camera);
}

animate();

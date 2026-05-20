import * as THREE from 'three';

// ── 6-face execution parameter mapping ───────────────────────────────────────
// Each face of the 3×3×3 cube = one SML execution parameter.
// Each face has 9 blocks (1 center + 4 edges + 4 corners) = 54 total blocks.
const FACE_PARAMS = {
  px: { name: 'LIQUIDITY', desc: 'SML Rail routing depth',   hex: '#00FFCC', color: 0x00FFCC, value: 87,  unit: '%',      max: 100, axis: 'x',  side:  1 },
  nx: { name: 'PRIVACY',   desc: 'Settlement anonymization', hex: '#FF0055', color: 0xFF0055, value: 3,   unit: 'lvl',    max: 10,  axis: 'x',  side: -1 },
  py: { name: 'SPEED',     desc: 'XRPL settlement latency',  hex: '#AA00FF', color: 0xAA00FF, value: 420, unit: 'ms',     max: 5000,axis: 'y',  side:  1 },
  ny: { name: 'POOL',      desc: 'Active RLUSD pools',       hex: '#00FF88', color: 0x00FF88, value: 12,  unit: 'pools',  max: 50,  axis: 'y',  side: -1 },
  pz: { name: 'HOOKS',     desc: 'Xahau Hooks armed',        hex: '#FFFF00', color: 0xFFFF00, value: 6,   unit: 'active', max: 20,  axis: 'z',  side:  1 },
  nz: { name: 'BASE',      desc: 'Base chain gasless bps',   hex: '#AAAAFF', color: 0x8888FF, value: 10,  unit: 'bps',    max: 500, axis: 'z',  side: -1 },
};

// Face index in BoxGeometry material array: [+x, -x, +y, -y, +z, -z]
const FACE_MAT_IDX = { px: 0, nx: 1, py: 2, ny: 3, pz: 4, nz: 5 };
const FACE_KEYS    = ['px', 'nx', 'py', 'ny', 'pz', 'nz'];

// ── Scene setup ──────────────────────────────────────────────────────────────
const container = document.getElementById('canvas-container');
const scene     = new THREE.Scene();
const camera    = new THREE.PerspectiveCamera(65, 1, 0.1, 1000);
const renderer  = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
container.appendChild(renderer.domElement);

function fitRenderer() {
  const w = container.clientWidth;
  const h = container.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
fitRenderer();
camera.position.set(0, 0.5, 5.5);

// ── Rubik's cube geometry ────────────────────────────────────────────────────
const PALETTES = {
  default: { px: 0x00FFCC, nx: 0xFF0055, py: 0xAA00FF, ny: 0x00FF88, pz: 0xFFFF00, nz: 0x334466 },
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
let   activePalette = 'default';

function makeMat(color) {
  return new THREE.MeshBasicMaterial({ color });
}

for (let x = -1; x <= 1; x++) {
  for (let y = -1; y <= 1; y++) {
    for (let z = -1; z <= 1; z++) {
      const pal = PALETTES.default;
      const m = [
        makeMat(x ===  1 ? pal.px : 0x050505),
        makeMat(x === -1 ? pal.nx : 0x050505),
        makeMat(y ===  1 ? pal.py : 0x050505),
        makeMat(y === -1 ? pal.ny : 0x050505),
        makeMat(z ===  1 ? pal.pz : 0x050505),
        makeMat(z === -1 ? pal.nz : 0x050505),
      ];
      const mesh = new THREE.Mesh(geo, m);
      mesh.position.set(x, y, z);
      cubeGroup.add(mesh);
      allMeshes.push({ mesh, x, y, z });
    }
  }
}
scene.add(cubeGroup);

// ── DOM refs ─────────────────────────────────────────────────────────────────
const statusEl    = document.getElementById('gl-status');
const countEl     = document.getElementById('gl-count');
const chainEl     = document.getElementById('gl-chain');
const txEl        = document.getElementById('gl-tx');
const speedEl     = document.getElementById('gl-speed');
const speedBarEl  = document.getElementById('gl-speed-bar');
const tachFill    = document.getElementById('tach-fill');
const eventEl     = document.getElementById('gl-event');
const faceGridEl  = document.getElementById('face-grid');
const faceDetailEl= document.getElementById('face-detail');
const tokenHashEl = document.getElementById('token-hash');
const tokenStatEl = document.getElementById('token-status');
const tokenHooksEl= document.getElementById('token-hooks');
const stateLabelEl= document.getElementById('state-label');
const revTotalEl  = document.getElementById('rev-total');

// ── Build face grid ───────────────────────────────────────────────────────────
const faceEls = {};

function buildFaceGrid() {
  if (!faceGridEl) return;
  faceGridEl.innerHTML = '';
  for (const key of FACE_KEYS) {
    const fp  = FACE_PARAMS[key];
    const el  = document.createElement('div');
    el.className = 'face-block';
    el.dataset.face = key;
    el.style.color = fp.hex;
    el.innerHTML = renderFaceBlock(fp);
    el.addEventListener('click', () => selectFace(key));
    faceEls[key] = el;
    faceGridEl.appendChild(el);
  }
}

function renderFaceBlock(fp) {
  return `<div class="face-name">${fp.name}</div>
<div class="face-val">${fp.value}<span class="face-unit">${fp.unit}</span></div>
<div class="face-desc">${fp.desc}</div>`;
}

// ── Face selection & detail ───────────────────────────────────────────────────
let selectedFace = null;

function selectFace(key) {
  if (selectedFace && faceEls[selectedFace]) {
    faceEls[selectedFace].classList.remove('active');
  }
  selectedFace = key;
  const el = faceEls[key];
  if (el) el.classList.add('active');

  const fp  = FACE_PARAMS[key];
  const pct = Math.min(100, Math.round((fp.value / fp.max) * 100));

  if (faceDetailEl) {
    faceDetailEl.innerHTML = `
      <div class="detail-name" style="color:${fp.hex}">${fp.name}
        <span style="font-size:0.52rem;color:#223344;margin-left:4px">(${key})</span>
      </div>
      <div class="detail-sub">${fp.desc}</div>
      <div style="display:flex;justify-content:space-between;font-size:0.60rem;margin-bottom:3px">
        <span class="stat-label">CURRENT</span>
        <span style="color:${fp.hex};font-weight:bold">${fp.value} ${fp.unit}</span>
      </div>
      <div class="detail-bar">
        <div class="detail-fill" style="width:${pct}%;background:${fp.hex};box-shadow:0 0 4px ${fp.hex}66"></div>
      </div>
      <div class="detail-note">9 blocks active &mdash; center=primary &middot; edges=modifiers &middot; corners=coefficients</div>
    `;
  }

  flashFace(key);
}

function flashFace(key) {
  const fp  = FACE_PARAMS[key];
  const fi  = FACE_MAT_IDX[key];
  const ax  = fp.axis;
  const sd  = fp.side;

  for (const { mesh } of allMeshes) {
    if (Math.round(mesh.position[ax]) === sd) {
      const c = new THREE.Color(fp.color);
      c.lerp(new THREE.Color(0xffffff), 0.5);
      mesh.material[fi].color.set(c);
    }
  }
  setTimeout(resetFaceColors, 500);
}

// ── Face parameter updates ────────────────────────────────────────────────────
function updateFaceParam(key, newValue) {
  FACE_PARAMS[key].value = Math.max(0, newValue);
  const el = faceEls[key];
  if (el) {
    el.innerHTML = renderFaceBlock(FACE_PARAMS[key]);
    el.addEventListener('click', () => selectFace(key));
  }
  if (selectedFace === key) selectFace(key);
  updateStateHash();
}

// ── Cube state hash for dNFT ─────────────────────────────────────────────────
// Deterministic djb2-style hash from all 6 face parameter values.
function updateStateHash() {
  const stateStr = FACE_KEYS.map(k => `${k}:${FACE_PARAMS[k].value}`).join('|');
  let h = 5381;
  for (let i = 0; i < stateStr.length; i++) {
    h = (((h << 5) + h) ^ stateStr.charCodeAt(i)) >>> 0;
  }
  const hash = `CUBE-${h.toString(16).padStart(8,'0').toUpperCase()}`;
  if (tokenHashEl) tokenHashEl.textContent = hash;
  return hash;
}

// ── Tachometer & rotation state ───────────────────────────────────────────────
const BASE_SPEED = 0.003;
const DECAY      = 0.97;

// Each event type: spike speed, palette, left-panel label, face to update, delta
const EVENT_CFG = {
  BRIDGE_SETTLED:  { speed: 0.060, palette: 'xrpl',    label: 'SETTLED', face: 'px', delta:  2 },
  AGENT_PROBE:     { speed: 0.008, palette: 'probe',   label: 'PROBE',   face: 'ny', delta:  1 },
  AGENT_PAY:       { speed: 0.020, palette: 'pay',     label: 'INVOICE', face: 'pz', delta:  1 },
  COUNCIL_VERDICT: { speed: 0.025, palette: 'verdict', label: 'VERDICT', face: 'py', delta: -5 },
  SQUEEZE_ALERT:   { speed: 0.030, palette: 'squeeze', label: 'SQUEEZE', face: 'px', delta:  5 },
  OPTIONS_SWEEP:   { speed: 0.030, palette: 'squeeze', label: 'SWEEP',   face: 'px', delta:  3 },
};

let rotSpeed       = BASE_SPEED;
let pulseIntensity = 0;
let bridgeCount    = 0;
let totalFees      = 0;

// Layer rotation animation
let layerRotating = false;
let layerAngle    = 0;
const LAYER_STEP  = 0.04;
const LAYER_TARGET= Math.PI / 2;

// ── Face color helpers ────────────────────────────────────────────────────────
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
  const pal = PALETTES[activePalette] ?? PALETTES.default;
  for (const { mesh, x, y, z } of allMeshes) {
    mesh.material[0].color.setHex(x ===  1 ? pal.px : 0x050505);
    mesh.material[1].color.setHex(x === -1 ? pal.nx : 0x050505);
    mesh.material[2].color.setHex(y ===  1 ? pal.py : 0x050505);
    mesh.material[3].color.setHex(y === -1 ? pal.ny : 0x050505);
    mesh.material[4].color.setHex(z ===  1 ? pal.pz : 0x050505);
    mesh.material[5].color.setHex(z === -1 ? pal.nz : 0x050505);
  }
}

// ── Event handler ─────────────────────────────────────────────────────────────
function fireEvent(type, data) {
  const cfg = EVENT_CFG[type];
  if (!cfg) return;

  if (cfg.speed > rotSpeed) rotSpeed = cfg.speed;
  pulseIntensity = 1.0;
  activePalette  = (type === 'BRIDGE_SETTLED' && data.chain === 'base') ? 'base' : cfg.palette;

  if (eventEl) {
    eventEl.textContent = cfg.label;
    eventEl.style.color = activePalette === 'probe'   ? '#334455'
                        : activePalette === 'pay'     ? '#FF8800'
                        : activePalette === 'squeeze' ? '#FFD700'
                        : '#00FFCC';
  }

  // Drive the face parameter that corresponds to this event type
  if (cfg.face) {
    const fp = FACE_PARAMS[cfg.face];
    updateFaceParam(cfg.face, fp.value + cfg.delta);
  }

  if (type === 'BRIDGE_SETTLED') {
    bridgeCount = data.total_bridges ?? bridgeCount + 1;
    if (countEl) countEl.textContent = bridgeCount;
    if (chainEl) chainEl.textContent = (data.chain ?? '–').toUpperCase();
    if (txEl && data.tx_hash) txEl.textContent = data.tx_hash.slice(0, 14) + '…';

    totalFees += 0.001;
    if (revTotalEl) revTotalEl.textContent = totalFees.toFixed(4) + ' RLUSD';
    setState('SETTLING');
    setTimeout(() => setState('IDLE'), 2000);

  } else if (type === 'COUNCIL_VERDICT') {
    if (chainEl) chainEl.textContent = data.bias ?? 'VERDICT';
    setState('VERDICT');
    setTimeout(() => setState('IDLE'), 2000);

  } else if (type === 'AGENT_PROBE' || type === 'AGENT_PAY') {
    if (chainEl) chainEl.textContent = data.path ?? cfg.label;
    setState('ROUTING');
    setTimeout(() => setState('IDLE'), 1500);

  } else if (type === 'SQUEEZE_ALERT' || type === 'OPTIONS_SWEEP') {
    if (chainEl) chainEl.textContent = data.symbol ?? cfg.label;
    setState('SQUEEZE');
    setTimeout(() => setState('IDLE'), 2000);
  }
}

function setState(s) {
  if (stateLabelEl) stateLabelEl.textContent = s;
}

// ── SSE connection factory ────────────────────────────────────────────────────
function makeSSE(url, label) {
  let es = null;
  let backoff = 1000;
  let offlineTimer = null;

  function connect() {
    if (es) es.close();
    es = new EventSource(url);

    es.onopen = () => {
      if (label === 'ghost') {
        if (offlineTimer) { clearTimeout(offlineTimer); offlineTimer = null; }
        setStatus(true);
      }
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
      es.close();
      es = null;
      if (label === 'ghost' && !offlineTimer) {
        offlineTimer = setTimeout(() => { offlineTimer = null; setStatus(false); }, 2500);
      }
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

// ── Button handlers ───────────────────────────────────────────────────────────
document.getElementById('btn-rotate')?.addEventListener('click', () => {
  if (layerRotating) return;
  layerRotating = true;
  layerAngle    = 0;
  setState('ROTATING');

  // Randomly shift one face parameter to simulate a parameter rebalance
  const key  = FACE_KEYS[Math.floor(Math.random() * FACE_KEYS.length)];
  const fp   = FACE_PARAMS[key];
  const sign = Math.random() > 0.5 ? 1 : -1;
  updateFaceParam(key, fp.value + sign * Math.ceil(Math.random() * 4));
});

document.getElementById('btn-mint')?.addEventListener('click', () => {
  if (tokenStatEl) { tokenStatEl.textContent = 'PENDING'; tokenStatEl.style.color = '#FF8800'; }
  setState('MINTING');

  setTimeout(() => {
    if (tokenStatEl) { tokenStatEl.textContent = 'MINTED'; tokenStatEl.style.color = '#00FF88'; }
    if (tokenHooksEl) tokenHooksEl.textContent = FACE_PARAMS.pz.value;
    setState('IDLE');
    pulseIntensity = 1.0;
    activePalette  = 'verdict';
    rotSpeed       = 0.04;
    setTimeout(() => { activePalette = 'default'; resetFaceColors(); }, 3000);
  }, 1500);
});

// ── Resize ────────────────────────────────────────────────────────────────────
const ro = new ResizeObserver(fitRenderer);
ro.observe(container);

// ── Bootstrap ─────────────────────────────────────────────────────────────────
buildFaceGrid();
updateStateHash();

fetch('/api/config')
  .then(r => r.json())
  .then(cfg => {
    bridgeCount = cfg.total_bridges ?? 0;
    if (countEl) countEl.textContent = bridgeCount;
    makeSSE(cfg.sse_url ?? '/api/events', 'ghost');
    if (cfg.squeezeos_sse) makeSSE(cfg.squeezeos_sse, 'squeezeos');
  })
  .catch(() => makeSSE('/api/events', 'ghost'));

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

  if (layerRotating) {
    layerAngle += LAYER_STEP;
    cubeGroup.rotation.y += LAYER_STEP;
    if (layerAngle >= LAYER_TARGET) {
      layerRotating = false;
      setState('IDLE');
    }
  } else {
    cubeGroup.rotation.x += rotSpeed;
    cubeGroup.rotation.y += rotSpeed * 1.3;
  }

  const pct = Math.round(((rotSpeed - BASE_SPEED) / (0.060 - BASE_SPEED)) * 100);
  const p   = Math.max(0, Math.min(100, pct));
  if (speedEl)    speedEl.textContent  = p + '%';
  if (speedBarEl) speedBarEl.textContent = p + '%';
  if (tachFill)   tachFill.style.width = p + '%';

  renderer.render(scene, camera);
}

animate();

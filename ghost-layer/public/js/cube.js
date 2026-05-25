import * as THREE from 'three';

// ── Corner coefficient presets ────────────────────────────────────────────────
const CORNER_PRESETS = [0.5, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0];

// ── 6-face × 9-block execution parameter matrix ───────────────────────────────
// center  = computeCenter(fp): weighted-avg of 4 edges using 4 corners as weights
// rotation shifts which corner weights which edge — values never cross face boundaries
// corners: [NW=0, NE=1, SE=2, SW=3]   edges: [N=0, E=1, S=2, W=3]
const FACE_PARAMS = {
  px: {
    name: 'LIQUIDITY', desc: 'SML Rail routing depth',
    hex: '#00FFCC', color: 0x00FFCC,
    min: 0, max: 100, unit: '%',
    axis: 'x', side: 1, rotation: 0,
    edges:      [91, 82, 88, 85],
    edgeLabels: ['POOL_A', 'POOL_B', 'POOL_C', 'POOL_D'],
    edgeUnit: '%', edgeMin: 0, edgeMax: 100, edgeStep: 2,
    corners: [1.1, 0.9, 1.0, 1.1],
  },
  nx: {
    name: 'PRIVACY', desc: 'Settlement anonymization',
    hex: '#FF0055', color: 0xFF0055,
    min: 0, max: 10, unit: 'lvl',
    axis: 'x', side: -1, rotation: 0,
    edges:      [4, 2, 3, 3],
    edgeLabels: ['ANON_1', 'ANON_2', 'SHIELD', 'OBFUSC'],
    edgeUnit: 'lvl', edgeMin: 0, edgeMax: 10, edgeStep: 1,
    corners: [1.0, 0.9, 1.1, 1.0],
  },
  py: {
    name: 'SPEED', desc: 'XRPL settlement latency',
    hex: '#AA00FF', color: 0xAA00FF,
    min: 100, max: 5000, unit: 'ms',
    axis: 'y', side: 1, rotation: 0,
    edges:      [400, 450, 420, 410],
    edgeLabels: ['XRPL_MS', 'BASE_MS', 'ROUTE_MS', 'FINAL_MS'],
    edgeUnit: 'ms', edgeMin: 100, edgeMax: 5000, edgeStep: 10,
    corners: [1.0, 1.0, 1.0, 1.0],
  },
  ny: {
    name: 'POOL', desc: 'Active RLUSD pools',
    hex: '#00FF88', color: 0x00FF88,
    min: 0, max: 50, unit: 'pools',
    axis: 'y', side: -1, rotation: 0,
    edges:      [14, 10, 13, 11],
    edgeLabels: ['RLUSD_1', 'RLUSD_2', 'RLUSD_3', 'RLUSD_4'],
    edgeUnit: 'pools', edgeMin: 0, edgeMax: 20, edgeStep: 1,
    corners: [1.0, 0.9, 1.1, 1.0],
  },
  pz: {
    name: 'HOOKS', desc: 'Xahau Hooks armed',
    hex: '#FFFF00', color: 0xFFFF00,
    min: 0, max: 20, unit: 'active',
    axis: 'z', side: 1, rotation: 0,
    edges:      [6, 7, 6, 5],
    edgeLabels: ['HOOK_1', 'HOOK_2', 'HOOK_3', 'HOOK_4'],
    edgeUnit: 'state', edgeMin: 0, edgeMax: 10, edgeStep: 1,
    corners: [1.0, 0.9, 1.1, 1.0],
  },
  nz: {
    name: 'BASE', desc: 'Base chain gasless bps',
    hex: '#AAAAFF', color: 0x8888FF,
    min: 0, max: 500, unit: 'bps',
    axis: 'z', side: -1, rotation: 0,
    edges:      [8, 12, 9, 11],
    edgeLabels: ['GASLESS', 'EIP3009', 'USDC_RT', 'OVERHEAD'],
    edgeUnit: 'bps', edgeMin: 0, edgeMax: 200, edgeStep: 1,
    corners: [1.0, 0.9, 1.1, 1.0],
  },
};

// Grid cell layout — row-major, 9 positions
const GRID_LAYOUT = [
  { type: 'corner', idx: 0, pos: 'NW' },
  { type: 'edge',   idx: 0, pos: 'N'  },
  { type: 'corner', idx: 1, pos: 'NE' },
  { type: 'edge',   idx: 3, pos: 'W'  },
  { type: 'center'                     },
  { type: 'edge',   idx: 1, pos: 'E'  },
  { type: 'corner', idx: 3, pos: 'SW' },
  { type: 'edge',   idx: 2, pos: 'S'  },
  { type: 'corner', idx: 2, pos: 'SE' },
];

const FACE_KEYS    = ['px', 'nx', 'py', 'ny', 'pz', 'nz'];
const FACE_MAT_IDX = { px: 0, nx: 1, py: 2, ny: 3, pz: 4, nz: 5 };

// ── Center computation ────────────────────────────────────────────────────────
// rotation offsets which corner index weights which edge:
//   rot=0: corner[i] → edge[i]
//   rot=1: corner[(i+1)%4] → edge[i]   etc.
function computeCenter(fp) {
  const rot = fp.rotation % 4;
  let wSum = 0, wTotal = 0;
  for (let i = 0; i < 4; i++) {
    const cIdx = (i + rot) % 4;
    wSum   += fp.edges[i] * fp.corners[cIdx];
    wTotal += fp.corners[cIdx];
  }
  return Math.min(fp.max, Math.max(fp.min, Math.round(wSum / wTotal)));
}

// ── Three.js scene ────────────────────────────────────────────────────────────
const container = document.getElementById('canvas-container');
const scene     = new THREE.Scene();
const camera    = new THREE.PerspectiveCamera(65, 1, 0.1, 1000);
const renderer  = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
container.appendChild(renderer.domElement);

function fitRenderer() {
  const w = container.clientWidth, h = container.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
fitRenderer();
camera.position.set(0, 0.5, 5.5);

// ── Rubik's cube mesh ─────────────────────────────────────────────────────────
const PALETTES = {
  default: { px: 0x00FFCC, nx: 0xFF0055, py: 0xAA00FF, ny: 0x00FF88, pz: 0xFFFF00, nz: 0x334466 },
  xrpl:    { px: 0x00FFCC, nx: 0xFF0055, py: 0xAA00FF, ny: 0x00FF88, pz: 0xFFFF00, nz: 0xFFFFFF },
  base:    { px: 0x6644FF, nx: 0xFF4499, py: 0xFF6600, ny: 0x00BBFF, pz: 0xFFEE00, nz: 0xEEEEEE },
  probe:   { px: 0x004466, nx: 0x002233, py: 0x003355, ny: 0x002244, pz: 0x003344, nz: 0x111111 },
  pay:     { px: 0xFF8800, nx: 0xFF4400, py: 0xFFAA00, ny: 0xFF6600, pz: 0xFFCC00, nz: 0xFF9900 },
  verdict: { px: 0x00FF88, nx: 0xFF3366, py: 0x00FFCC, ny: 0xFF0055, pz: 0x00FF44, nz: 0xFFFFFF },
  squeeze: { px: 0xFFD700, nx: 0xFFA500, py: 0xFFCC00, ny: 0xFF8C00, pz: 0xFFE500, nz: 0xFFBB00 },
};

const cubeGroup     = new THREE.Group();
const allMeshes     = [];
const geo           = new THREE.BoxGeometry(0.93, 0.93, 0.93);
let   activePalette = 'default';

for (let x = -1; x <= 1; x++) {
  for (let y = -1; y <= 1; y++) {
    for (let z = -1; z <= 1; z++) {
      const p = PALETTES.default;
      const m = [
        new THREE.MeshBasicMaterial({ color: x ===  1 ? p.px : 0x050505 }),
        new THREE.MeshBasicMaterial({ color: x === -1 ? p.nx : 0x050505 }),
        new THREE.MeshBasicMaterial({ color: y ===  1 ? p.py : 0x050505 }),
        new THREE.MeshBasicMaterial({ color: y === -1 ? p.ny : 0x050505 }),
        new THREE.MeshBasicMaterial({ color: z ===  1 ? p.pz : 0x050505 }),
        new THREE.MeshBasicMaterial({ color: z === -1 ? p.nz : 0x050505 }),
      ];
      const mesh = new THREE.Mesh(geo, m);
      mesh.position.set(x, y, z);
      cubeGroup.add(mesh);
      allMeshes.push({ mesh, x, y, z });
    }
  }
}
scene.add(cubeGroup);

// ── DOM refs ──────────────────────────────────────────────────────────────────
const statusEl    = document.getElementById('gl-status');
const countEl     = document.getElementById('gl-count');
const chainEl     = document.getElementById('gl-chain');
const txEl        = document.getElementById('gl-tx');
const speedEl     = document.getElementById('gl-speed');
const speedBarEl  = document.getElementById('gl-speed-bar');
const tachFill    = document.getElementById('tach-fill');
const eventEl     = document.getElementById('gl-event');
const tpsEl       = document.getElementById('gl-tps');
const tpsBarEl    = document.getElementById('gl-tps-bar');
const tierEl      = document.getElementById('gl-tier');
const faceGridEl  = document.getElementById('face-grid');
const faceDetailEl= document.getElementById('face-detail');
const tokenHashEl  = document.getElementById('token-hash');
const tokenStatEl  = document.getElementById('token-status');
const tokenHooksEl = document.getElementById('token-hooks');
const tokenXahauEl = document.getElementById('token-xahau');
const tokenChainEl = document.getElementById('token-chain');
const stateLabelEl= document.getElementById('state-label');
const revTotalEl  = document.getElementById('rev-total');

// ── Face summary grid (left panel top) ───────────────────────────────────────
const faceEls = {};

function buildFaceGrid() {
  if (!faceGridEl) return;
  faceGridEl.innerHTML = '';
  for (const key of FACE_KEYS) {
    const el = document.createElement('div');
    el.className = 'face-block';
    el.dataset.face = key;
    el.style.color = FACE_PARAMS[key].hex;
    el.innerHTML = renderFaceBlock(key);
    el.addEventListener('click', () => selectFace(key));
    faceEls[key] = el;
    faceGridEl.appendChild(el);
  }
}

function renderFaceBlock(key) {
  const fp  = FACE_PARAMS[key];
  const ctr = computeCenter(fp);
  return `<div class="face-name">${fp.name}</div>
<div class="face-val">${ctr}<span class="face-unit">${fp.unit}</span></div>
<div class="face-desc">${fp.desc}</div>`;
}

// ── Face selection → render 3×3 interactive grid ─────────────────────────────
let selectedFace = null;

function selectFace(key) {
  if (selectedFace && faceEls[selectedFace]) faceEls[selectedFace].classList.remove('active');
  selectedFace = key;
  if (faceEls[key]) faceEls[key].classList.add('active');
  renderDetail(key);
  flashFace(key);
}

function renderDetail(key) {
  if (!faceDetailEl) return;
  const fp  = FACE_PARAMS[key];
  const ctr = computeCenter(fp);
  const rot = fp.rotation % 4;

  const cells = GRID_LAYOUT.map(cell => {
    if (cell.type === 'center') {
      const pct = Math.min(100, Math.round((ctr - fp.min) / (fp.max - fp.min) * 100));
      return `<div class="grid-cell g-center" style="color:${fp.hex};border-color:${fp.hex}55">
  <div class="gc-label">CENTER</div>
  <div class="gc-val">${ctr}</div>
  <div class="gc-unit">${fp.unit}</div>
  <div class="gc-bar"><div class="gc-fill" style="width:${pct}%;background:${fp.hex}"></div></div>
</div>`;
    }
    if (cell.type === 'edge') {
      const val  = fp.edges[cell.idx];
      const lbl  = fp.edgeLabels[cell.idx];
      const cIdx = (cell.idx + rot) % 4;
      const wt   = fp.corners[cIdx].toFixed(1);
      return `<div class="grid-cell g-edge" data-face="${key}" data-type="edge" data-idx="${cell.idx}"
  style="color:${fp.hex};border-color:${fp.hex}66" title="L-click +${fp.edgeStep} · R-click −${fp.edgeStep}">
  <div class="gc-label">${lbl}</div>
  <div class="gc-val">${val}</div>
  <div class="gc-unit">×${wt}</div>
</div>`;
    }
    // corner
    const val = fp.corners[cell.idx].toFixed(1);
    return `<div class="grid-cell g-corner" data-face="${key}" data-type="corner" data-idx="${cell.idx}"
  title="Click to cycle weight">
  <div class="gc-label">${cell.pos}</div>
  <div class="gc-val" style="color:#556677">×${val}</div>
  <div class="gc-unit" style="color:#223344">WGT</div>
</div>`;
  }).join('');

  faceDetailEl.innerHTML = `
<div class="detail-name" style="color:${fp.hex}">${fp.name}<span class="detail-rot">${key} · ROT ${rot * 90}°</span></div>
<div class="detail-sub">${fp.desc}</div>
<div class="grid-3x3">${cells}</div>
<div class="detail-note">edge L-click=+step · R-click=−step · corner=cycle weight · rotation shifts pairings</div>`;
}

// ── Grid cell click/right-click interaction ───────────────────────────────────
document.addEventListener('click', e => {
  const cell = e.target.closest('[data-type]');
  if (!cell) return;
  const key  = cell.dataset.face;
  const type = cell.dataset.type;
  const idx  = parseInt(cell.dataset.idx, 10);
  const fp   = FACE_PARAMS[key];

  if (type === 'edge') {
    fp.edges[idx] = Math.min(fp.edgeMax, fp.edges[idx] + fp.edgeStep);
    refreshFace(key);
    updateStateHash();
    flashFace(key);
  } else if (type === 'corner') {
    const cur  = fp.corners[idx];
    const curI = CORNER_PRESETS.findIndex(v => Math.abs(v - cur) < 0.05);
    fp.corners[idx] = CORNER_PRESETS[(curI + 1) % CORNER_PRESETS.length];
    refreshFace(key);
    updateStateHash();
  }
});

document.addEventListener('contextmenu', e => {
  const cell = e.target.closest('[data-type="edge"]');
  if (!cell) return;
  e.preventDefault();
  const key = cell.dataset.face;
  const idx = parseInt(cell.dataset.idx, 10);
  const fp  = FACE_PARAMS[key];
  fp.edges[idx] = Math.max(fp.edgeMin, fp.edges[idx] - fp.edgeStep);
  refreshFace(key);
  updateStateHash();
  flashFace(key);
});

// ── Refresh face block + detail if selected ───────────────────────────────────
function refreshFace(key) {
  if (faceEls[key]) {
    faceEls[key].innerHTML = renderFaceBlock(key);
    faceEls[key].addEventListener('click', () => selectFace(key));
  }
  if (selectedFace === key) renderDetail(key);
}

// ── Flash face on 3D cube ─────────────────────────────────────────────────────
function flashFace(key) {
  const fp = FACE_PARAMS[key];
  const fi = FACE_MAT_IDX[key];
  for (const { mesh } of allMeshes) {
    if (Math.round(mesh.position[fp.axis]) === fp.side) {
      const c = new THREE.Color(fp.color);
      c.lerp(new THREE.Color(0xffffff), 0.5);
      mesh.material[fi].color.set(c);
    }
  }
  setTimeout(resetFaceColors, 500);
}

// ── 54-value canonical state hash ────────────────────────────────────────────
// 6 faces × 9 values (1 computed center + 4 edges + 4 corners) = 54 fields
function updateStateHash() {
  const parts = [];
  for (const key of FACE_KEYS) {
    const fp  = FACE_PARAMS[key];
    const ctr = computeCenter(fp);
    parts.push(`${key}c:${ctr}`);
    fp.edges.forEach((v, i)   => parts.push(`${key}e${i}:${v}`));
    fp.corners.forEach((v, i) => parts.push(`${key}k${i}:${v.toFixed(1)}`));
  }
  // djb2 over the full 54-field string
  const str = parts.join('|');
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = (((h << 5) + h) ^ str.charCodeAt(i)) >>> 0;
  const hash = `CUBE-${h.toString(16).padStart(8, '0').toUpperCase()}`;
  if (tokenHashEl) tokenHashEl.textContent = hash;
  return hash;
}

// ── Tachometer & rotation ─────────────────────────────────────────────────────
const BASE_SPEED = 0.003;
const DECAY      = 0.97;

// SSE events target specific edge indices — centers are derived, never set directly
const EVENT_CFG = {
  BRIDGE_SETTLED:       { speed: 0.060, palette: 'xrpl',    label: 'SETTLED',   face: 'px', edgeIdx: 0, delta:  2 },
  AGENT_PROBE:          { speed: 0.008, palette: 'probe',   label: 'PROBE',     face: 'ny', edgeIdx: 1, delta:  1 },
  AGENT_PAY:            { speed: 0.020, palette: 'pay',     label: 'INVOICE',   face: 'pz', edgeIdx: 0, delta:  1 },
  COUNCIL_VERDICT:      { speed: 0.025, palette: 'verdict', label: 'VERDICT',   face: 'py', edgeIdx: 2, delta: -10 },
  SQUEEZE_ALERT:        { speed: 0.030, palette: 'squeeze', label: 'SQUEEZE',   face: 'px', edgeIdx: 2, delta:  5 },
  OPTIONS_SWEEP:        { speed: 0.030, palette: 'squeeze', label: 'SWEEP',     face: 'px', edgeIdx: 3, delta:  3 },
  CUBE_STATE_COMMITTED:  { speed: 0.045, palette: 'verdict', label: 'COMMITTED'                                   },
  XAHAU_MINT_CONFIRMED:  { speed: 0.055, palette: 'verdict', label: 'ON-CHAIN'                                    },
  HEARTBEAT:             { speed: 0,     palette: null,      label: null                                           },
};

let rotSpeed       = BASE_SPEED;
let pulseIntensity = 0;
let bridgeCount    = 0;
let totalFees      = 0;

let layerRotating = false;
let layerAngle    = 0;
let layerRotAxis  = 'y';
let layerRotDir   = 1;
const LAYER_STEP   = 0.04;
const LAYER_TARGET = Math.PI / 2;

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

// ── Unified event handler (handles both SSE and WebSocket frames) ─────────────
function fireEvent(type, data) {
  const cfg = EVENT_CFG[type];
  if (!cfg || type === 'HEARTBEAT') return;

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

  if (cfg.face) {
    const fp = FACE_PARAMS[cfg.face];
    fp.edges[cfg.edgeIdx] = Math.min(fp.edgeMax, Math.max(fp.edgeMin, fp.edges[cfg.edgeIdx] + cfg.delta));
    refreshFace(cfg.face);
    updateStateHash();
  }

  if (type === 'BRIDGE_SETTLED') {
    bridgeCount = data.total_bridges ?? bridgeCount + 1;
    if (countEl) countEl.textContent = bridgeCount;
    if (chainEl) chainEl.textContent = (data.chain ?? '–').toUpperCase();
    if (txEl && data.tx_hash) txEl.textContent = data.tx_hash.slice(0, 14) + '…';
    // Show agent tier badge if present
    if (data.agent_tier) {
      const tierColors = { DIAMOND: '#00FFFF', PLATINUM: '#AA00FF', GOLD: '#FFD700', SILVER: '#AAAAFF', BRONZE: '#FF8800' };
      if (chainEl) {
        const chain = (data.chain ?? '').toUpperCase();
        chainEl.innerHTML = `${chain} <span style="color:${tierColors[data.agent_tier] ?? '#00FFCC'};font-size:0.5rem;margin-left:4px">[${data.agent_tier}]</span>`;
      }
      if (tierEl) {
        const tierColors2 = { DIAMOND: '#00FFFF', PLATINUM: '#AA00FF', GOLD: '#FFD700', SILVER: '#AAAAFF', BRONZE: '#FF8800' };
        tierEl.textContent = data.agent_tier;
        tierEl.style.color = tierColors2[data.agent_tier] ?? '#00FFCC';
      }
    }
    totalFees += 0.001;
    if (revTotalEl) revTotalEl.textContent = totalFees.toFixed(4) + ' RLUSD';
    setState('SETTLING'); setTimeout(() => setState('IDLE'), 2000);
  } else if (type === 'COUNCIL_VERDICT') {
    if (chainEl) chainEl.textContent = data.bias ?? 'VERDICT';
    setState('VERDICT'); setTimeout(() => setState('IDLE'), 2000);
  } else if (type === 'AGENT_PROBE' || type === 'AGENT_PAY') {
    if (chainEl) chainEl.textContent = data.path ?? cfg.label;
    setState('ROUTING'); setTimeout(() => setState('IDLE'), 1500);
  } else if (type === 'SQUEEZE_ALERT' || type === 'OPTIONS_SWEEP') {
    if (chainEl) chainEl.textContent = data.symbol ?? cfg.label;
    setState('SQUEEZE'); setTimeout(() => setState('IDLE'), 2000);
  } else if (type === 'XAHAU_MINT_CONFIRMED') {
    const txHash = data.xahau_tx ?? '';
    if (tokenChainEl) { tokenChainEl.textContent = 'ON-CHAIN'; tokenChainEl.style.color = '#00FF88'; }
    if (tokenXahauEl && txHash) {
      const txUrl = `https://xahau.network/tx/${txHash}`;
      tokenXahauEl.innerHTML = `<a href="${txUrl}" target="_blank" rel="noopener">${txHash.slice(0,16)}…</a>`;
    }
    setState('MINTED'); setTimeout(() => setState('IDLE'), 3000);
  }
}

function setState(s) { if (stateLabelEl) stateLabelEl.textContent = s; }

// ── Sovereign WebSocket Metrics Connection ────────────────────────────────────
// Connects to /ws/metrics for live TPS, fee accumulation, and bridge events.
// Falls back gracefully if WebSocket is unavailable.

let wsMetrics    = null;
let wsBackoff    = 1000;
let wsOfflineTimer = null;
let serverTPS    = 0; // live TPS from /ws/metrics

function connectMetricsWS(url) {
  if (wsMetrics) { try { wsMetrics.close(); } catch(_) {} }

  const wsUrl = url.replace(/^http/, 'ws');
  wsMetrics = new WebSocket(wsUrl);

  wsMetrics.onopen = () => {
    wsBackoff = 1000;
    if (wsOfflineTimer) { clearTimeout(wsOfflineTimer); wsOfflineTimer = null; }
    setStatus(true, 'WS');
    console.log('[GHOST] WebSocket metrics stream connected:', wsUrl);
  };

  wsMetrics.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);

      // Update live TPS — directly drives tachometer speed
      if (typeof data.tps === 'number') {
        serverTPS = data.tps;
        // Map TPS to rotation speed: 0 TPS = BASE_SPEED, 1 TPS = max
        const tpsSpeed = BASE_SPEED + Math.min(data.tps / 1.0, 1.0) * (0.060 - BASE_SPEED);
        if (tpsSpeed > rotSpeed) rotSpeed = tpsSpeed;
      }

      // Sync cumulative bridge count
      if (typeof data.total_bridges === 'number' && data.total_bridges > bridgeCount) {
        bridgeCount = data.total_bridges;
        if (countEl) countEl.textContent = bridgeCount;
      }

      // Fire visual events
      if (data.type && data.type !== 'CONNECTED' && data.type !== 'HEARTBEAT') {
        fireEvent(data.type, data);
      } else if (data.type === 'CONNECTED') {
        bridgeCount = data.total_bridges ?? bridgeCount;
        if (countEl) countEl.textContent = bridgeCount;
      }
    } catch(_) {}
  };

  wsMetrics.onerror = () => {
    console.warn('[GHOST] WebSocket error — will retry in', wsBackoff, 'ms');
  };

  wsMetrics.onclose = () => {
    wsMetrics = null;
    if (!wsOfflineTimer) {
      wsOfflineTimer = setTimeout(() => { wsOfflineTimer = null; setStatus(false); }, 2500);
    }
    setTimeout(() => connectMetricsWS(url), wsBackoff);
    wsBackoff = Math.min(wsBackoff * 2, 30000);
  };
}

// ── Legacy SSE connection factory (kept for squeezeos feed) ──────────────────
function makeSSE(url, label) {
  let es = null, backoff = 1000, offlineTimer = null;
  function connect() {
    if (es) es.close();
    es = new EventSource(url);
    es.onopen = () => {
      if (label === 'ghost') {
        if (offlineTimer) { clearTimeout(offlineTimer); offlineTimer = null; }
        // Don't override WS status if WS is live
        if (!wsMetrics || wsMetrics.readyState !== WebSocket.OPEN) setStatus(true, 'SSE');
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
      es.close(); es = null;
      if (label === 'ghost' && !offlineTimer) {
        offlineTimer = setTimeout(() => { offlineTimer = null; setStatus(false); }, 2500);
      }
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 30000);
    };
  }
  connect();
}

function setStatus(online, transport) {
  if (!statusEl) return;
  if (online) {
    const label = transport === 'WS' ? '● LIVE [WS]' : '● LIVE [SSE]';
    statusEl.textContent = label;
    statusEl.style.color = '#00FFCC';
  } else {
    statusEl.textContent = '○ OFFLINE';
    statusEl.style.color = '#FF0055';
  }
}

// ── Buttons ───────────────────────────────────────────────────────────────────
document.getElementById('btn-rotate')?.addEventListener('click', () => {
  if (layerRotating) return;
  const key = selectedFace ?? FACE_KEYS[Math.floor(Math.random() * FACE_KEYS.length)];
  const fp  = FACE_PARAMS[key];

  // Increment rotation → shifts corner-edge pairings → recomputes center
  fp.rotation = (fp.rotation + 1) % 4;
  refreshFace(key);
  updateStateHash();

  layerRotating = true;
  layerAngle    = 0;
  layerRotAxis  = fp.axis;
  layerRotDir   = fp.side;
  setState('ROTATING');
});

// ── Payment helpers ────────────────────────────────────────────────────────────

function buildMintPayload() {
  const faces = {};
  for (const key of FACE_KEYS) {
    const fp = FACE_PARAMS[key];
    faces[key] = { center: computeCenter(fp), edges: [...fp.edges], corners: [...fp.corners], rotation: fp.rotation };
  }
  return { hash: updateStateHash(), faces };
}

function applyMintSuccess(data) {
  if (tokenStatEl)  { tokenStatEl.textContent = 'MINTED'; tokenStatEl.style.color = '#00FF88'; }
  if (tokenHashEl)  tokenHashEl.textContent  = data.state_hash;
  if (tokenHooksEl) tokenHooksEl.textContent = data.faces?.pz?.center ?? computeCenter(FACE_PARAMS.pz);
  if (data.xahau_tx_hash) {
    const txUrl = `https://xahau.network/tx/${data.xahau_tx_hash}`;
    if (tokenXahauEl) tokenXahauEl.innerHTML = `<a href="${txUrl}" target="_blank" rel="noopener">${data.xahau_tx_hash.slice(0,16)}…</a>`;
    if (tokenChainEl) { tokenChainEl.textContent = 'ON-CHAIN'; tokenChainEl.style.color = '#00FF88'; }
  } else {
    if (tokenXahauEl) tokenXahauEl.textContent = 'mint pending';
    if (tokenChainEl) { tokenChainEl.textContent = 'LOCAL'; tokenChainEl.style.color = '#FF8800'; }
  }
  setState('IDLE');
  pulseIntensity = 1.0;
  activePalette  = 'verdict';
  rotSpeed       = 0.04;
  setTimeout(() => { activePalette = 'default'; resetFaceColors(); }, 3000);
}

async function submitMint(payload, token) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['X-Payment-Token'] = token;
  return fetch('/api/cube/state', { method: 'POST', headers, body: JSON.stringify(payload) });
}

function showPayOverlay(invoice) {
  const overlay = document.getElementById('pay-overlay');
  if (!overlay) return;
  document.getElementById('pay-addr').textContent  = invoice.pay_to  ?? '—';
  document.getElementById('pay-amount').textContent = `${invoice.amount ?? '0.05'} ${invoice.asset ?? 'RLUSD'}`;
  document.getElementById('pay-memo').textContent   = invoice.memo_hex ?? '—';
  document.getElementById('pay-invoice-id').value   = invoice.invoice_id ?? '';
  document.getElementById('pay-status').textContent = '';
  document.getElementById('pay-tx-hash').value      = '';
  document.getElementById('pay-wallet').value       = '';
  overlay.style.display = 'flex';
}

function hidePayOverlay() {
  const overlay = document.getElementById('pay-overlay');
  if (overlay) overlay.style.display = 'none';
}

document.getElementById('pay-cancel-btn')?.addEventListener('click', () => {
  hidePayOverlay();
  if (tokenStatEl) { tokenStatEl.textContent = 'UNMINTED'; tokenStatEl.style.color = ''; }
  setState('IDLE');
});

document.getElementById('pay-verify-btn')?.addEventListener('click', async () => {
  const txHash  = document.getElementById('pay-tx-hash')?.value.trim();
  const wallet  = document.getElementById('pay-wallet')?.value.trim();
  const invoiceId = document.getElementById('pay-invoice-id')?.value.trim();
  const statusEl = document.getElementById('pay-status');

  if (!txHash || !wallet) {
    if (statusEl) statusEl.textContent = 'Enter tx hash and wallet address.';
    return;
  }
  if (statusEl) { statusEl.textContent = 'Verifying…'; statusEl.style.color = '#FF8800'; }

  try {
    const vRes  = await fetch('/api/cube/pay/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ invoice_id: invoiceId, tx_hash: txHash, agent_wallet: wallet }),
    });
    const vData = await vRes.json();
    if (!vRes.ok || !vData.access_token) {
      if (statusEl) { statusEl.textContent = vData.error ?? 'Verification failed — check tx hash and wallet.'; statusEl.style.color = '#FF0055'; }
      return;
    }
    const token = vData.access_token;
    sessionStorage.setItem('cube_mint_token', token);

    if (statusEl) { statusEl.textContent = 'Payment verified. Minting…'; statusEl.style.color = '#00FF88'; }
    hidePayOverlay();

    const payload = buildMintPayload();
    const res  = await submitMint(payload, token);
    const data = await res.json();
    if (res.ok && data.verified) {
      applyMintSuccess(data);
    } else {
      if (tokenStatEl) { tokenStatEl.textContent = 'REJECTED'; tokenStatEl.style.color = '#FF0055'; }
      setState('VERIFY_ERR');
      setTimeout(() => setState('IDLE'), 3000);
    }
  } catch (err) {
    if (statusEl) { statusEl.textContent = 'Network error. Try again.'; statusEl.style.color = '#FF4400'; }
  }
});

document.getElementById('pay-copy-addr')?.addEventListener('click', () => {
  navigator.clipboard?.writeText(document.getElementById('pay-addr')?.textContent ?? '');
  document.getElementById('pay-copy-addr').textContent = 'COPIED';
  setTimeout(() => { document.getElementById('pay-copy-addr').textContent = 'COPY'; }, 1500);
});

document.getElementById('pay-copy-memo')?.addEventListener('click', () => {
  navigator.clipboard?.writeText(document.getElementById('pay-memo')?.textContent ?? '');
  document.getElementById('pay-copy-memo').textContent = 'COPIED';
  setTimeout(() => { document.getElementById('pay-copy-memo').textContent = 'COPY'; }, 1500);
});

// ── Mint button ────────────────────────────────────────────────────────────────

document.getElementById('btn-mint')?.addEventListener('click', async () => {
  if (tokenStatEl) { tokenStatEl.textContent = 'PENDING'; tokenStatEl.style.color = '#FF8800'; }
  setState('MINTING');

  const payload = buildMintPayload();
  const token   = sessionStorage.getItem('cube_mint_token') ?? undefined;

  try {
    const res  = await submitMint(payload, token);
    const data = await res.json();

    if (res.status === 402) {
      setState('IDLE');
      const inv = data.invoice ?? {};
      if (!inv.pay_to) {
        // 402proof still waking up — show status, no overlay needed
        if (tokenStatEl) { tokenStatEl.textContent = data.message ?? 'PAYMENT SERVER STARTING — WAIT 30s'; tokenStatEl.style.color = '#FF8800'; }
        return;
      }
      if (tokenStatEl) { tokenStatEl.textContent = 'PAY 0.05 RLUSD'; tokenStatEl.style.color = '#FF8800'; }
      showPayOverlay(inv);
      return;
    }

    if (res.status === 401) {
      // Token expired or invalid — clear cache, re-click triggers fresh 402 with new invoice
      sessionStorage.removeItem('cube_mint_token');
      if (tokenStatEl) { tokenStatEl.textContent = 'TOKEN EXPIRED — CLICK MINT'; tokenStatEl.style.color = '#FF8800'; }
      setState('IDLE');
      return;
    }

    if (res.ok && data.verified) {
      applyMintSuccess(data);
    } else {
      if (tokenStatEl) { tokenStatEl.textContent = 'REJECTED'; tokenStatEl.style.color = '#FF0055'; }
      setState('VERIFY_ERR');
      console.error('[CUBE] mint rejected:', data.error);
      setTimeout(() => setState('IDLE'), 3000);
    }
  } catch (err) {
    if (tokenStatEl) { tokenStatEl.textContent = 'OFFLINE'; tokenStatEl.style.color = '#FF4400'; }
    setState('NET_ERR');
    setTimeout(() => setState('IDLE'), 3000);
  }
});


// ── Resize ─────────────────────────────────────────────────────────────────────
new ResizeObserver(fitRenderer).observe(container);

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

// ── Animation loop ─────────────────────────────────────────────────────────────
function animate() {
  requestAnimationFrame(animate);

  if (rotSpeed > BASE_SPEED) rotSpeed = Math.max(BASE_SPEED, rotSpeed * DECAY);

  if (pulseIntensity > 0) {
    pulseIntensity = Math.max(0, pulseIntensity - 0.016);
    applyPulse(pulseIntensity);
    if (pulseIntensity === 0) resetFaceColors();
  }

  if (layerRotating) {
    layerAngle += LAYER_STEP;
    cubeGroup.rotation[layerRotAxis] += LAYER_STEP * layerRotDir;
    if (layerAngle >= LAYER_TARGET) { layerRotating = false; setState('IDLE'); }
  } else {
    cubeGroup.rotation.x += rotSpeed;
    cubeGroup.rotation.y += rotSpeed * 1.3;
  }

  const pct = Math.round(((rotSpeed - BASE_SPEED) / (0.060 - BASE_SPEED)) * 100);
  const p   = Math.max(0, Math.min(100, pct));
  if (speedEl)    speedEl.textContent    = p + '%';
  if (speedBarEl) speedBarEl.textContent = p + '%';
  if (tachFill)   tachFill.style.width   = p + '%';

  // Live TPS display — updated from serverTPS fed by WebSocket
  const tpsDisplay = serverTPS.toFixed(3);
  if (tpsEl)    tpsEl.textContent    = tpsDisplay;
  if (tpsBarEl) tpsBarEl.textContent = tpsDisplay;

  renderer.render(scene, camera);
}

animate();

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RGBELoader } from 'three/addons/loaders/RGBELoader.js';
import { Sky } from 'three/addons/objects/Sky.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { OutlinePass } from 'three/addons/postprocessing/OutlinePass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { SMAAPass } from 'three/addons/postprocessing/SMAAPass.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';

// Facade visual mock-up (VMU) yard - future completed state. three.js r160 viewer: canonical materials by name from
// model/materials.json, HDRI sky + NOAA sun, PBR textures, GTAO + SMAA, canopy-extension outline toggle (never red),
// label declutter, still shots and an optional path-traced still (three-gpu-pathtracer + three-mesh-bvh).

// Sun model only: rounded latitude / longitude and time zone (no site georeference).
const SITE = { lat: 1.3, lon: 103.8, tz: 8 };
const $ = (id) => document.getElementById(id);
const app = $('app');
const Q = new URLSearchParams(location.search);

// ---------------- user-switchable parameters (URL overrides) ----------------
const PARAMS = {
  // canopy finish scheme: 'default' (top Mouse Grey, 3 mm parts T02) | 'ral7038' (alternative) [?canopyScheme=ral7038]
  CANOPY_FINISH_SCHEME: /^ral7038$/i.test(Q.get('canopyScheme') || '') ? 'ral7038' : 'default',
  // top-panel override inside either scheme [?canopyTop=AL_T02|AL_RAL7038|AL_MOUSEGREY]
  CANOPY_TOP_OVERRIDE: /^(AL_T02|AL_RAL7038|AL_MOUSEGREY)$/.test(Q.get('canopyTop') || '') ? Q.get('canopyTop') : null,
  PRECAST_HEX: /^#?[0-9a-fA-F]{6}$/.test(Q.get('precast') || '') ? '#' + Q.get('precast').replace('#', '') : null,   // [?precast=RRGGBB]
  HDRI: Q.get('hdri') === 'sunny' ? 'sunny' : 'overcast',                         // [?hdri=sunny]
  EXT_OUTLINE: Q.get('outline') === '1',                                           // extension outline, default off [?outline=1]
  MODEL_DIR: (Q.get('mdir') || 'model/').replace(/([^/])$/, '$1/'),                // optional-GLB folder [?mdir=]
};

// HDRI presets (Poly Haven, CC0)
const HDRIS = {
  overcast: { file: 'textures/hdri/mud_road_puresky_2k.hdr', label: '阴天', exposure: 1.04, sun: 0.35, shadowRadius: 7, bg: 1.75, sunCap: 1e9, align: false, wb: 1.0, sunK0: 4200, sunK1: 1800, ptDiffuseSun: true },
  sunny: { file: 'textures/hdri/kloofendal_48d_partly_cloudy_puresky_2k.hdr', label: '晴间多云', exposure: 0.8, sun: 1.0, shadowRadius: 2, bg: 1.25, sunCap: 30, align: true, wb: 0.4, sunK0: 3300, sunK1: 1700 },
};
// yard concrete look: albedo of the processed texture, trowel-swirl contrast, aggregate specks, damp / dirt darkening [?yard=raw]
const YARD_CAL = { albedo: '#B3ADA1', swirl: 0.55, aggregate: 0.06, normalScale: 0.6, dampK: 0.43, dirtK: 0.34, dampRough: 0.45, macroAmp: 0.07, macroStain: 0.08, off: Q.get('yard') === 'raw' };
const YARD_MAP_BOX = { x0: -140, z0: -150, x1: 136, z1: 66, W: 3072 };
const BOUNCE_CHROMA = +(Q.get('bounceChroma') ?? 0.4);
// galvanised steel: specular IBL gain on fresh hot-dip zinc (materials.json unchanged) [?hdg=raw | ?hdgEnv=x]
const HDG_CAL = { env: Q.get('hdg') === 'raw' ? 1 : ((v) => (Number.isFinite(v) && v > 0 ? v : 1.15))(+(Q.get('hdgEnv') ?? 1.15)), mats: ['STEEL_HDG'] };
const SUN_FULL = 4.2;

// ---------------- renderer / scene ----------------
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
// static scene: the shadow map is redrawn only when the sun, its anchor or a visibility toggle changes
renderer.shadowMap.autoUpdate = false; renderer.shadowMap.needsUpdate = true;
app.appendChild(renderer.domElement);
const labelRenderer = new CSS2DRenderer();
labelRenderer.setSize(innerWidth, innerHeight);
Object.assign(labelRenderer.domElement.style, { position: 'fixed', inset: '0', pointerEvents: 'none' });
app.appendChild(labelRenderer.domElement);
const MAX_ANISO = renderer.capabilities.getMaxAnisotropy();

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.3, 9000);
camera.position.set(70, 45, 40);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.minDistance = 1.5; controls.maxDistance = 2500;
controls.target.set(0, 4, 0);
// keep the orbiting camera above the yard (eye-level views look up, so no fixed maxPolarAngle)
const CAM_MIN_Y = 0.25;
function limitPolar() {
  const r = camera.position.distanceTo(controls.target); if (!(r > 1e-6)) return;
  const c = THREE.MathUtils.clamp((CAM_MIN_Y - controls.target.y) / r, -1, 1);
  controls.maxPolarAngle = Math.min(Math.PI * 0.97, Math.max(0.02, Math.acos(c)));
}
{ const upd = controls.update.bind(controls); controls.update = (...a) => { limitPolar(); return upd(...a); }; }

// sun (NOAA) + fallback procedural sky (only used if the HDRI cannot be loaded)
const sun = new THREE.DirectionalLight(0xfff4e5, 3.2);
sun.castShadow = true; sun.shadow.mapSize.set(4096, 4096);
const sc = sun.shadow.camera; sc.left = -75; sc.right = 75; sc.top = 75; sc.bottom = -75; sc.near = 1; sc.far = 600;
sun.shadow.bias = -0.0002; sun.shadow.normalBias = 0.02;
scene.add(sun, sun.target);
// shadow acne fixes (r160 shader chunks, patched before any program compiles): one-sided receiver-plane depth bias,
// sign-aware slope-scaled normal offset, bilinear PCF taps. [?rpdb=0] [?nofs=0] [?pcfbl=0]
const SHADOW_OPTS = { rpdb: (Q.get('rpdb') ?? '1') !== '0', nofs: (Q.get('nofs') ?? '1') !== '0', bilinear: (Q.get('pcfbl') ?? '1') !== '0', maxTapM: 0.45, depthRangeM: 599 };
{
  const MAXD = (SHADOW_OPTS.maxTapM / SHADOW_OPTS.depthRangeM).toExponential(6);
  let s = THREE.ShaderChunk.shadowmap_pars_fragment, taps = 0; const n0 = s.length;
  if (SHADOW_OPTS.rpdb) {
    s = s.replace('float getShadow( sampler2D shadowMap,', `float rpdbTap( vec2 g, vec2 o, float q ) { return max( min( dot( g, o ) - q, 0.0 ), - ${MAXD} ); }
	float texture2DCompareBL( sampler2D depths, vec2 uv, float compare, vec2 size ) {
		vec2 st = uv * size - 0.5; vec2 i0 = floor( st ); vec2 f = st - i0; vec2 t = 1.0 / size; vec2 b = ( i0 + 0.5 ) * t;
		return mix( mix( texture2DCompare( depths, b, compare ), texture2DCompare( depths, b + vec2( t.x, 0.0 ), compare ), f.x ),
			mix( texture2DCompare( depths, b + vec2( 0.0, t.y ), compare ), texture2DCompare( depths, b + t, compare ), f.x ), f.y );
	}
	float getShadow( sampler2D shadowMap,`);
    s = s.replace('shadowCoord.z += shadowBias;\n', `shadowCoord.z += shadowBias;
		vec3 rpdbX = dFdx( shadowCoord.xyz ), rpdbY = dFdy( shadowCoord.xyz );
		float rpdbDet = rpdbX.x * rpdbY.y - rpdbX.y * rpdbY.x;
		vec2 rpdbG = abs( rpdbDet ) > 1e-16 ? vec2( rpdbX.z * rpdbY.y - rpdbX.y * rpdbY.z, rpdbX.x * rpdbY.z - rpdbX.z * rpdbY.x ) / rpdbDet : vec2( 0.0 );
		float rpdbQ = ${SHADOW_OPTS.bilinear ? '1.0' : '0.5'} * ( abs( rpdbG.x ) + abs( rpdbG.y ) ) / shadowMapSize.x;   // texel quantisation (+ bilinear footprint)
`);
    const TC = SHADOW_OPTS.bilinear ? 'texture2DCompareBL' : 'texture2DCompare', TS = SHADOW_OPTS.bilinear ? ', shadowMapSize' : '';
    s = s.replace(/texture2DCompare\( shadowMap, shadowCoord\.xy \+ vec2\( ([^()]*?) \), shadowCoord\.z \)/g, (m, o) => { taps++; return `${TC}( shadowMap, shadowCoord.xy + vec2( ${o} ), shadowCoord.z + rpdbTap( rpdbG, vec2( ${o} ), rpdbQ )${TS} )`; });
    if (SHADOW_OPTS.bilinear) { const c0 = 'texture2DCompare( shadowMap, shadowCoord.xy, shadowCoord.z ) +'; if (s.includes(c0)) { s = s.replace(c0, 'texture2DCompareBL( shadowMap, shadowCoord.xy, shadowCoord.z - rpdbQ, shadowMapSize ) +'); taps++; } }
    if (taps === (SHADOW_OPTS.bilinear ? 17 : 16) && s.length > n0) THREE.ShaderChunk.shadowmap_pars_fragment = s; else { SHADOW_OPTS.rpdb = false; console.warn('shadow RPDB patch not applied', taps); }
  }
  if (SHADOW_OPTS.nofs) {
    const v0 = THREE.ShaderChunk.shadowmap_vertex;
    const old = 'shadowWorldPosition = worldPosition + vec4( shadowWorldNormal * directionalLightShadows[ i ].shadowNormalBias, 0 );';
    const rep = `vec3 shadowToL = - normalize( vec3( directionalShadowMatrix[ i ][ 0 ][ 2 ], directionalShadowMatrix[ i ][ 1 ][ 2 ], directionalShadowMatrix[ i ][ 2 ][ 2 ] ) );
			float shadowNL = dot( shadowWorldNormal, shadowToL );
			shadowWorldPosition = worldPosition + vec4( shadowWorldNormal * ( ( shadowNL < 0.0 ? - 1.0 : 1.0 ) * directionalLightShadows[ i ].shadowNormalBias * ( 0.25 + 0.75 * sqrt( max( 1.0 - shadowNL * shadowNL, 0.0 ) ) ) ), 0 );`;
    if (v0.includes(old)) THREE.ShaderChunk.shadowmap_vertex = v0.replace(old, rep); else { SHADOW_OPTS.nofs = false; console.warn('shadow normal-offset patch not applied'); }
  }
}
function setShadowSoftness(radius) { sun.shadow.radius = radius; }
const sunDir = new THREE.Vector3(0, 1, 0);
let sunAlt = 0, sunAz = 0;
const pmrem = new THREE.PMREMGenerator(renderer);
let fallbackSky = null;

// ---------------- sun position (NOAA simplified) ----------------
function sunPosition(dateUTC, lat, lon) {
  const rad = Math.PI / 180;
  const n = dateUTC.getTime() / 86400000 + 2440587.5 - 2451545.0;
  const L = (280.460 + 0.9856474 * n) % 360, g = ((357.528 + 0.9856003 * n) % 360) * rad;
  const lam = (L + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad;
  const eps = (23.439 - 0.0000004 * n) * rad;
  const ra = Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam));
  const dec = Math.asin(Math.sin(eps) * Math.sin(lam));
  const gmst = (18.697374558 + 24.06570982441908 * n) % 24;
  const H = (gmst * 15 + lon) * rad - ra;
  const alt = Math.asin(Math.sin(lat * rad) * Math.sin(dec) + Math.cos(lat * rad) * Math.cos(dec) * Math.cos(H));
  const az = Math.atan2(-Math.sin(H), Math.tan(dec) * Math.cos(lat * rad) - Math.sin(lat * rad) * Math.cos(H));
  return { alt, az };
}
$('date').value = Q.get('date') || '2027-03-21';   // neutral default (equinox) [?date=YYYY-MM-DD&t=minutes]
$('time').value = +(Q.get('t') || 600);
const light = { hdri: PARAMS.HDRI, exposure: null, sunK: null };
function kelvinRGB(T) {
  const t = T / 100; let r, g, b;
  if (t <= 66) { r = 255; g = 99.4708025861 * Math.log(t) - 161.1195681661; b = t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307; }
  else { r = 329.698727446 * Math.pow(t - 60, -0.1332047592); g = 288.1221695283 * Math.pow(t - 60, -0.0755148492); b = 255; }
  return [r, g, b].map((v) => Math.min(255, Math.max(0, v)) / 255);
}
function updateSun() {
  const [y, m, d] = $('date').value.split('-').map(Number);
  const mins = +$('time').value;
  const utc = new Date(Date.UTC(y, m - 1, d, 0, 0) + (mins - SITE.tz * 60) * 60000);
  const { alt, az } = sunPosition(utc, SITE.lat, SITE.lon);
  sunAlt = alt; sunAz = az;
  sunDir.set(Math.cos(alt) * Math.sin(az), Math.sin(alt), -Math.cos(alt) * Math.cos(az));
  const hh = String(Math.floor(mins / 60)).padStart(2, '0'), mm = String(mins % 60).padStart(2, '0');
  $('timeval').textContent = `${hh}:${mm}`;
  $('sunval').textContent = `高度 ${(alt * 180 / Math.PI).toFixed(1)}° 方位 ${(((az * 180 / Math.PI) + 360) % 360).toFixed(0)}°`;
  const up = Math.max(0, Math.sin(alt));
  const k = light.sunK ?? HDRIS[light.hdri].sun;
  sun.intensity = alt > 0 ? SUN_FULL * k * Math.min(1, 0.25 + up * 1.6) : 0;
  const K = HDRIS[light.hdri].sunK0 + HDRIS[light.hdri].sunK1 * Math.min(1, up * 2.2);
  sun.color.setRGB(...kelvinRGB(K), THREE.SRGBColorSpace);
  syncSunToTarget(true);
  if (fallbackSky) fallbackSky.material.uniforms.sunPosition.value.copy(sunDir);
  scheduleSkyAlign(); markDirty();
}
// ---------------- render scheduling: idle -> no redraw; moving camera -> no GTAO, cached shadow map ----------------
let dirtyUntil = 0, movingUntil = 0, shadowDirty = true, renderCount = 0;
const shadowAnchor = new THREE.Vector3(1e9, 0, 0), shadowDir = new THREE.Vector3();
function markDirty(ms = 700) { dirtyUntil = Math.max(dirtyUntil, performance.now() + ms); }
function syncSunToTarget(force = false, center = null) {
  const c = center || controls.target;
  if (force || center || shadowAnchor.distanceToSquared(c) > 25 || !shadowDir.equals(sunDir)) { shadowAnchor.copy(c); shadowDir.copy(sunDir); shadowDirty = true; }
  sun.position.copy(shadowAnchor).addScaledVector(sunDir, 250); sun.target.position.copy(shadowAnchor);
}

// ---------------- HDRI environment: sun disc clamp, sky white balance, synthetic ground bounce, fog colour ----------------
const hdrCache = {};
let hdrCurrent = null;
async function loadHDR(key) {
  if (hdrCache[key]) return hdrCache[key];
  const P = HDRIS[key];
  const tex = await new RGBELoader().setDataType(THREE.FloatType).loadAsync(P.file);
  tex.mapping = THREE.EquirectangularReflectionMapping;
  const { data, width: w, height: h } = tex.image;
  let best = -1, bx = 0, by = 0;
  for (let y = 0; y < h / 2; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4; const l = data[i] + data[i + 1] + data[i + 2];
    if (l > best) { best = l; bx = x; by = y; }
  }
  let clamped = 0, groundL = null;
  if (P.sunCap < 1e8) for (let i = 0; i < data.length; i += 4) {
    const mx = Math.max(data[i], data[i + 1], data[i + 2]);
    if (mx > P.sunCap) { const s = P.sunCap / mx; data[i] *= s; data[i + 1] *= s; data[i + 2] *= s; clamped++; }
  }
  let wbGain = [1, 1, 1];
  if (P.wb > 0) {
    const m = [0, 0, 0]; let nm = 0;
    for (let y = 0; y < h / 2; y += 2) for (let x = 0; x < w; x += 4) { const i = (y * w + x) * 4; if (data[i] + data[i + 1] + data[i + 2] > 60) continue; m[0] += data[i]; m[1] += data[i + 1]; m[2] += data[i + 2]; nm++; }
    const Y = 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
    wbGain = m.map((c) => 1 + P.wb * (Y / c - 1));
    for (let i = 0; i < data.length; i += 4) { data[i] *= wbGain[0]; data[i + 1] *= wbGain[1]; data[i + 2] *= wbGain[2]; }
  }
  {
    const m = [0, 0, 0]; let nm = 0;
    for (let y = 0; y < h / 2; y += 2) for (let x = 0; x < w; x += 4) { const i = (y * w + x) * 4; m[0] += data[i]; m[1] += data[i + 1]; m[2] += data[i + 2]; nm++; }
    const alb = MATDB.CTX_CONCRETE_YARD?.linear || [0.552, 0.479, 0.366];
    const E = m.map((c) => c / nm * 0.9 + P.sun * SUN_FULL * 0.7 / Math.PI);
    const L0 = alb.map((a, k) => a * E[k]); const Ly = 0.2126 * L0[0] + 0.7152 * L0[1] + 0.0722 * L0[2];
    const Lg = L0.map((v) => 0.75 * (Ly + BOUNCE_CHROMA * (v - Ly)));
    for (let y = Math.floor(h / 2); y < h; y++) {
      const t = Math.min(1, (y - h / 2) / (h * 0.025));
      for (let x = 0; x < w; x++) { const i = (y * w + x) * 4; for (let k = 0; k < 3; k++) data[i + k] = data[i + k] * (1 - t) + Lg[k] * t; }
    }
    groundL = Lg;
  }
  const fog = [0, 0, 0]; let nf = 0;
  for (let y = Math.floor(h * 0.44); y < Math.floor(h * 0.5); y++) for (let x = 0; x < w; x += 4) {
    const i = (y * w + x) * 4; fog[0] += data[i]; fog[1] += data[i + 1]; fog[2] += data[i + 2]; nf++;
  }
  let Esky = 0;
  for (let y = 0; y < h / 2; y++) {
    const th = (y + 0.5) / h * Math.PI, wgt = Math.cos(th) * Math.sin(th) * (Math.PI / h) * (2 * Math.PI / w);
    let row = 0; for (let x = 0; x < w; x += 2) { const i = (y * w + x) * 4; row += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]; }
    Esky += row * 2 * wgt;
  }
  const rec = { key, tex, P, sunCol: bx, sunRow: by, sunLum: best / 3, fog: fog.map((v) => v / nf), shift: 0, env: null, clamped, wbGain, groundL, Esky };
  hdrCache[key] = rec; return rec;
}
function rotateEquirect(tex, shiftCols) {
  const { data, width, height } = tex.image; const c = 4; const row = new Float32Array(width * c);
  shiftCols = ((Math.round(shiftCols) % width) + width) % width; if (!shiftCols) return;
  for (let y = 0; y < height; y++) {
    const o = y * width * c; row.set(data.subarray(o, o + width * c));
    for (let x = 0; x < width; x++) { const nx = (x + shiftCols) % width; data.set(row.subarray(x * c, x * c + c), o + nx * c); }
  }
  tex.needsUpdate = true;
}
function alignHdrSun(rec) {
  if (!rec.P.align) return false;
  const w = rec.tex.image.width;
  const uWanted = Math.atan2(sunDir.z, sunDir.x) / (2 * Math.PI) + 0.5;
  const target = Math.round(uWanted * w); const cur = (rec.sunCol + rec.shift) % w;
  const d = target - cur; if (Math.abs(d) < 3) return false;
  rotateEquirect(rec.tex, d); rec.shift = (rec.shift + d + w) % w; return true;
}
function applyHDR(rec) {
  hdrCurrent = rec;
  alignHdrSun(rec);
  if (rec.env) rec.env.dispose();
  rec.env = pmrem.fromEquirectangular(rec.tex);
  if (!ptActive()) { scene.environment = rec.env.texture; scene.background = rec.tex; }
  scene.backgroundIntensity = rec.P.bg; scene.backgroundBlurriness = 0;
  if (fallbackSky) fallbackSky.visible = false;
  const fc = new THREE.Color().setRGB(rec.fog[0], rec.fog[1], rec.fog[2], THREE.LinearSRGBColorSpace);
  const fm = Math.max(fc.r, fc.g, fc.b); if (fm > 1.2) fc.multiplyScalar(1.2 / fm);
  scene.fog = new THREE.FogExp2(fc, 0.0011);
  setShadowSoftness(rec.P.shadowRadius);
  shadowDirty = true; markDirty(1500);
}
let skyAlignTimer = null;
function scheduleSkyAlign() {
  if (!hdrCurrent || !hdrCurrent.P.align) return;
  clearTimeout(skyAlignTimer);
  skyAlignTimer = setTimeout(() => { if (hdrCurrent && alignHdrSun(hdrCurrent)) { hdrCurrent.env?.dispose(); hdrCurrent.env = pmrem.fromEquirectangular(hdrCurrent.tex); if (!ptActive()) scene.environment = hdrCurrent.env.texture; markDirty(); } }, 250);
}
async function setHDRI(key, keepLevels = false) {
  light.hdri = key; if (!keepLevels) { light.exposure = null; light.sunK = null; }
  $('hdriOvercast').classList.toggle('on', key === 'overcast'); $('hdriSunny').classList.toggle('on', key === 'sunny');
  syncLightUI();
  try { applyHDR(await loadHDR(key)); } catch (e) { console.warn('HDRI load failed, using procedural sky', e); useFallbackSky(); }
  updateSun();
}
function useFallbackSky() {
  if (!fallbackSky) { fallbackSky = new Sky(); fallbackSky.scale.setScalar(8000); const u = fallbackSky.material.uniforms; u.turbidity.value = 9; u.rayleigh.value = 2.2; u.mieCoefficient.value = 0.005; u.mieDirectionalG.value = 0.8; scene.add(fallbackSky); }
  fallbackSky.visible = true; scene.background = null;
  const s2 = new THREE.Scene(); const sk = new Sky(); sk.scale.setScalar(8000); sk.material.uniforms.sunPosition.value.copy(sunDir); s2.add(sk);
  scene.environment = pmrem.fromScene(s2, 0, 0.3, 9000).texture;
}
function syncLightUI() {
  const P = HDRIS[light.hdri];
  const ex = light.exposure ?? P.exposure, sk = light.sunK ?? P.sun;
  renderer.toneMappingExposure = ex * (ptState ? PT_CFG.exposureGain : 1);
  $('exposure').value = ex; $('expval').textContent = ex.toFixed(2);
  $('sunk').value = sk; $('sunkval').textContent = Math.round(sk * 100) + '%';
}

// ---------------- textures ----------------
const texManager = new THREE.LoadingManager();
const texPending = [];
const texLoader = new THREE.TextureLoader(texManager);
const texCache = {};
function loadTex(file, srgb, repeat = 1) {
  const key = `${file}|${srgb}|${repeat}`; if (texCache[key]) return texCache[key];
  let done; texPending.push(new Promise((res) => { done = res; }));
  const t = texLoader.load(file, () => { done(); markDirty(); }, undefined, () => { console.warn('texture missing:', file); done(); });
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repeat, repeat); t.anisotropy = MAX_ANISO;
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  texCache[key] = t; return t;
}
function canvasTex(w, h, draw, repeat = [1, 1], srgb = true) {
  const c = document.createElement('canvas'); c.width = w; c.height = h; draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat);
  t.anisotropy = MAX_ANISO; if (srgb) t.colorSpace = THREE.SRGBColorSpace; return t;
}
function rnd(seed) { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; }
const srgbToLin = (v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
// yard concrete albedo: brushed_concrete luminance only, damped swirls, fine aggregate specks + grain, tileable
function yardAlbedoTexture(file, onReady) {
  const S = 2048; const cv = document.createElement('canvas'); cv.width = cv.height = S;
  const g = cv.getContext('2d', { willReadFrequently: true }); g.fillStyle = '#808080'; g.fillRect(0, 0, S, S);
  const tex = new THREE.CanvasTexture(cv); tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.anisotropy = MAX_ANISO; tex.colorSpace = THREE.SRGBColorSpace;
  let done; texPending.push(new Promise((r) => { done = r; }));
  const img = new Image();
  img.onload = () => {
    try {
      g.drawImage(img, 0, 0, S, S); const id = g.getImageData(0, 0, S, S); const d = id.data; const N = S * S;
      const L = new Float32Array(N); let m = 0;
      for (let i = 0; i < N; i++) { const l = 0.2126 * d[4 * i] + 0.7152 * d[4 * i + 1] + 0.0722 * d[4 * i + 2]; L[i] = l; m += l; }
      m /= N; const r = rnd(7919);
      for (let i = 0; i < N; i++) L[i] = 132 + (L[i] - m) * YARD_CAL.swirl + (r() - 0.5) * 7;
      for (const [lam, amp] of [[20, 7], [56, 6], [160, 4]]) {
        const n = Math.round(S / lam), lat = new Float32Array(n * n); for (let k = 0; k < n * n; k++) lat[k] = r() * 2 - 1;
        const sm = (t) => t * t * (3 - 2 * t);
        for (let y = 0; y < S; y++) { const fy = y / S * n, iy = Math.floor(fy), ty = sm(fy - iy), y0 = iy % n, y1 = (iy + 1) % n;
          for (let x = 0; x < S; x++) { const fx = x / S * n, ix = Math.floor(fx), tx = sm(fx - ix), x0 = ix % n, x1 = (ix + 1) % n;
            const a = lat[y0 * n + x0] + (lat[y0 * n + x1] - lat[y0 * n + x0]) * tx, b = lat[y1 * n + x0] + (lat[y1 * n + x1] - lat[y1 * n + x0]) * tx;
            L[y * S + x] += amp * (a + (b - a) * ty); } }
      }
      const nAgg = Math.round(N * YARD_CAL.aggregate / 6);
      for (let k = 0; k < nAgg; k++) {
        const cx = r() * S, cy = r() * S, rad = 0.5 + r() * r() * 3.0, dv = (r() < 0.72 ? -1 : 1) * (10 + r() * 32);
        const x0 = Math.floor(cx - rad), x1 = Math.ceil(cx + rad), y0 = Math.floor(cy - rad), y1 = Math.ceil(cy + rad);
        for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
          const q = Math.hypot(x + 0.5 - cx, y + 0.5 - cy) / rad; if (q > 1.25) continue;
          const w = q < 0.75 ? 1 : (1.25 - q) * 2; const j = (((y % S) + S) % S) * S + (((x % S) + S) % S); L[j] += dv * w;
        }
      }
      let ml = 0;
      for (let i = 0; i < N; i++) { const v = Math.max(0, Math.min(255, L[i])); d[4 * i] = d[4 * i + 1] = d[4 * i + 2] = v; d[4 * i + 3] = 255; ml += srgbToLin(Math.round(v) / 255); }
      g.putImageData(id, 0, 0); tex.needsUpdate = true; onReady(ml / N);
    } catch (e) { console.warn('yard texture', e); onReady(srgbToLin(128 / 255)); }
    done(); markDirty();
  };
  img.onerror = () => { console.warn('texture missing:', file); onReady(srgbToLin(128 / 255)); done(); };
  img.src = file;
  return tex;
}
// world-space yard detail map: R = damp patches (soft edges), G = tyre marks + oil stains, B = edge noise
const YARD_U = { uYardMap: { value: null }, uYardO: { value: new THREE.Vector2(YARD_MAP_BOX.x0, YARD_MAP_BOX.z0) }, uYardS: { value: new THREE.Vector2(YARD_MAP_BOX.x1 - YARD_MAP_BOX.x0, YARD_MAP_BOX.z1 - YARD_MAP_BOX.z0) }, uYardDamp: { value: YARD_CAL.dampK }, uYardDirt: { value: YARD_CAL.dirtK }, uYardDampRough: { value: YARD_CAL.dampRough } };
{ const t = new THREE.DataTexture(new Uint8Array(4), 1, 1); t.needsUpdate = true; YARD_U.uYardMap.value = t; }
// sky visibility of the yard (baked once after loading from orthographic depth renders over the sky hemisphere) [?skyvis=0]
const YARD_VIS = { on: (Q.get('skyvis') ?? '1') !== '0', dirs: 64, res: 1024, sm: 2048, bounce: 0.3, layer: 7 };
{ const t = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1); t.needsUpdate = true; YARD_U.uYardVis = { value: t }; YARD_U.uYardVisBounce = { value: YARD_VIS.bounce }; }
const yardMapStats = {};
function buildYardMap(dampMeshes, cars) {
  const B = YARD_MAP_BOX, W = B.W, H = Math.round(W * (B.z1 - B.z0) / (B.x1 - B.x0)), res = (B.x1 - B.x0) / W;
  const P = (x, z) => [(x - B.x0) / res, (z - B.z0) / res];
  const mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; const g = c.getContext('2d', { willReadFrequently: true }); g.fillStyle = '#000'; g.fillRect(0, 0, W, H); return [c, g]; };
  const [cd, gd] = mk(); gd.fillStyle = '#fff'; let nTri = 0; const v = new THREE.Vector3();
  for (const m of dampMeshes) {
    m.updateWorldMatrix(true, false); const pos = m.geometry.attributes.position, idx = m.geometry.index; const pts = [];
    for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld); pts.push(P(v.x, v.z)); }
    const n = idx ? idx.count : pos.count; gd.beginPath();
    for (let t = 0; t < n; t += 3) { const a = pts[idx ? idx.getX(t) : t], b = pts[idx ? idx.getX(t + 1) : t + 1], c = pts[idx ? idx.getX(t + 2) : t + 2]; gd.moveTo(a[0], a[1]); gd.lineTo(b[0], b[1]); gd.lineTo(c[0], c[1]); gd.closePath(); nTri++; }
    gd.fill();
  }
  const [cg, gg] = mk(); gg.globalCompositeOperation = 'lighter'; gg.lineCap = 'round'; gg.lineJoin = 'round';
  const r = rnd(4242); const gauss = () => (r() + r() + r() + r() - 2) * 1.2247;
  const vmuC = [5, 2];
  let nTrk = 0, nOil = 0;
  const track = (x, z, h, len, curv, gauge, wid, alpha) => {
    const Lp = [], Rp = []; for (let s = 0; s <= len; s += 0.5) {
      const nx = -Math.sin(h), nz = Math.cos(h); Lp.push(P(x + nx * gauge / 2, z + nz * gauge / 2)); Rp.push(P(x - nx * gauge / 2, z - nz * gauge / 2));
      x += Math.cos(h) * 0.5; z += Math.sin(h) * 0.5; h += curv * 0.5 + (r() - 0.5) * 0.012;
    }
    gg.lineWidth = Math.max(1.2, wid / res);
    for (const pl of [Lp, Rp]) for (let i = 0; i + 1 < pl.length; i += 6) {
      const f = i / pl.length, a = alpha * Math.sin(Math.PI * Math.min(1, Math.max(0, f + 0.04))) * (0.6 + 0.4 * r());
      gg.strokeStyle = `rgba(255,255,255,${a.toFixed(3)})`; gg.beginPath(); gg.moveTo(...pl[i]); for (let j = i + 1; j <= Math.min(i + 6, pl.length - 1); j++) gg.lineTo(...pl[j]); gg.stroke();
    }
    nTrk++;
  };
  for (let k = 0; k < 46; k++) {
    const x = vmuC[0] + gauss() * 24, z = vmuC[1] + gauss() * 20; const big = r() < 0.3;
    track(x, z, r() * Math.PI * 2, 8 + r() * 26, (r() - 0.5) * (r() < 0.5 ? 0.16 : 0.04), big ? 2.0 + r() * 0.4 : 1.35 + r() * 0.35, big ? 0.32 : 0.2, 0.10 + r() * 0.16);
  }
  const ax = Math.atan2(-0.9377, 0.3475);
  for (let k = 0; k < 16; k++) {
    const t = (r() - 0.5) * 120, o = -18 + gauss() * 14; const x = vmuC[0] + Math.cos(ax) * t + 0.9377 * o, z = vmuC[1] + Math.sin(ax) * t - 0.3475 * o;
    track(x, z, ax + (r() < 0.5 ? 0 : Math.PI) + (r() - 0.5) * 0.08, 20 + r() * 50, (r() - 0.5) * 0.01, 1.6 + r() * 0.5, 0.24, 0.08 + r() * 0.1);
  }
  const oil = (x, z, rad, alpha) => { const [px, pz] = P(x, z); const R = rad / res; const gr = gg.createRadialGradient(px, pz, 0, px, pz, R); gr.addColorStop(0, `rgba(255,255,255,${alpha})`); gr.addColorStop(0.55, `rgba(255,255,255,${alpha * 0.6})`); gr.addColorStop(1, 'rgba(255,255,255,0)'); gg.fillStyle = gr; gg.beginPath(); gg.ellipse(px, pz, R, R * (0.6 + 0.4 * r()), r() * Math.PI, 0, Math.PI * 2); gg.fill(); nOil++; };
  for (const c of cars || []) { if (r() < 0.75) oil(+c.p[0] + gauss() * 0.8, +c.p[2] + gauss() * 0.8, 0.35 + r() * 0.7, 0.25 + r() * 0.3); }
  for (let k = 0; k < 24; k++) oil(vmuC[0] + gauss() * 30, vmuC[1] + gauss() * 26, 0.2 + r() * 0.6, 0.15 + r() * 0.25);
  const [co, go] = mk();
  go.filter = `blur(${(0.6 / res).toFixed(1)}px)`; go.drawImage(cd, 0, 0); const dR = go.getImageData(0, 0, W, H).data;
  go.filter = 'none'; go.fillStyle = '#000'; go.fillRect(0, 0, W, H); go.filter = `blur(${Math.max(0.6, 0.05 / res).toFixed(2)}px)`; go.drawImage(cg, 0, 0); const dG = go.getImageData(0, 0, W, H).data;
  go.filter = 'none'; const id = go.createImageData(W, H); const o = id.data;
  const nB = new Float32Array(W * H);
  for (const [lam, amp] of [[1.9, 0.7], [0.8, 0.3]]) {
    const nx = Math.ceil(W * res / lam) + 2, nz = Math.ceil(H * res / lam) + 2, lat = new Float32Array(nx * nz); for (let k = 0; k < lat.length; k++) lat[k] = r();
    const sm = (t) => t * t * (3 - 2 * t);
    for (let y = 0; y < H; y++) { const fy = y * res / lam, iy = Math.floor(fy), ty = sm(fy - iy);
      for (let x = 0; x < W; x++) { const fx = x * res / lam, ix = Math.floor(fx), tx = sm(fx - ix);
        const a = lat[iy * nx + ix] + (lat[iy * nx + ix + 1] - lat[iy * nx + ix]) * tx, b = lat[(iy + 1) * nx + ix] + (lat[(iy + 1) * nx + ix + 1] - lat[(iy + 1) * nx + ix]) * tx;
        nB[y * W + x] += amp * (a + (b - a) * ty); } }
  }
  for (let i = 0; i < W * H; i++) { o[4 * i] = dR[4 * i]; o[4 * i + 1] = Math.min(255, dG[4 * i + 1]); o[4 * i + 2] = Math.round(255 * nB[i]); o[4 * i + 3] = 255; }
  go.putImageData(id, 0, 0);
  const tex = new THREE.CanvasTexture(co); tex.flipY = false; tex.colorSpace = THREE.NoColorSpace; tex.anisotropy = Math.min(8, MAX_ANISO);
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping; tex.minFilter = THREE.LinearMipmapLinearFilter; tex.generateMipmaps = true;
  YARD_U.uYardMap.value = tex; tex.needsUpdate = true;
  Object.assign(yardMapStats, { px: [W, H], m_per_px: +res.toFixed(4), dampTriangles: nTri, dampMeshes: dampMeshes.length, tyreTracks: nTrk, oilStains: nOil });
  markDirty();
}
const yardVisStats = {};
function bakeYardSkyVis(roots) {
  const t0 = performance.now(); const B = YARD_MAP_BOX, V = YARD_VIS, L = V.layer;
  const RW = V.res, RH = Math.round(RW * (B.z1 - B.z0) / (B.x1 - B.x0));
  const occ = []; for (const root of roots) root.traverse((o) => { if (o.isMesh && isVisibleChain(o) && !o.material?.userData?.glass && !(o.material?.transparent && !o.material?.alphaTest)) { o.layers.enable(L); occ.push(o); } });
  const cx = (B.x0 + B.x1) / 2, cz = (B.z0 + B.z1) / 2, half = Math.hypot(B.x1 - B.x0, B.z1 - B.z0) / 2 + 20, far = 1200;
  const dRT = new THREE.WebGLRenderTarget(V.sm, V.sm, { depthTexture: new THREE.DepthTexture(V.sm, V.sm, THREE.FloatType) });
  const cam = new THREE.OrthographicCamera(-half, half, half, -half, 1, far); cam.layers.set(L);
  const depthMat = new THREE.MeshBasicMaterial({ colorWrite: false, side: THREE.DoubleSide });
  const accRT = new THREE.WebGLRenderTarget(RW, RH, { type: THREE.HalfFloatType, depthBuffer: false, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, generateMipmaps: false });
  const accMat = new THREE.ShaderMaterial({
    uniforms: { uDepth: { value: dRT.depthTexture }, uVP: { value: new THREE.Matrix4() }, uO: { value: new THREE.Vector2(B.x0, B.z0) }, uS: { value: new THREE.Vector2(B.x1 - B.x0, B.z1 - B.z0) }, uW: { value: 1 / V.dirs }, uTexel: { value: 1 / V.sm }, uBias: { value: 0.04 / far } },
    vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4( position.xy, 0.0, 1.0 ); }',
    fragmentShader: `uniform sampler2D uDepth; uniform mat4 uVP; uniform vec2 uO; uniform vec2 uS; uniform float uW; uniform float uTexel; uniform float uBias; varying vec2 vUv;
      void main() { vec3 P = vec3( uO.x + vUv.x * uS.x, 0.06, uO.y + vUv.y * uS.y ); vec4 c = uVP * vec4( P, 1.0 ); vec3 n = c.xyz / c.w * 0.5 + 0.5; float v = 0.0;
        for ( int i = -1; i <= 1; i ++ ) for ( int j = -1; j <= 1; j ++ ) { float d = texture2D( uDepth, n.xy + vec2( float( i ), float( j ) ) * uTexel ).r; v += ( n.z - uBias <= d ) ? 1.0 : 0.0; }
        gl_FragColor = vec4( vec3( v / 9.0 * uW ), 1.0 ); }`,
    blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), accMat); quad.frustumCulled = false; const qScene = new THREE.Scene(); qScene.add(quad); const qCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const prev = { rt: renderer.getRenderTarget(), bg: scene.background, fog: scene.fog, ov: scene.overrideMaterial, auto: renderer.autoClear, smu: renderer.shadowMap.needsUpdate, cc: renderer.getClearColor(new THREE.Color()), ca: renderer.getClearAlpha() };
  try {
    scene.background = null; scene.fog = null; scene.overrideMaterial = depthMat; renderer.shadowMap.needsUpdate = false; renderer.autoClear = false; renderer.setClearColor(0x000000, 1);
    renderer.setRenderTarget(accRT); renderer.clear(true, false, false);
    const ctr = new THREE.Vector3(cx, 0, cz), dir = new THREE.Vector3();
    for (let i = 0; i < V.dirs; i++) {
      const u = (i + 0.5) / V.dirs, st = Math.sqrt(u), ct = Math.sqrt(1 - u), ph = i * 2.399963229728653;
      dir.set(st * Math.cos(ph), ct, st * Math.sin(ph));
      cam.position.copy(ctr).addScaledVector(dir, far / 2); cam.up.set(0, 1, 0); if (ct > 0.98) cam.up.set(0, 0, -1); cam.lookAt(ctr); cam.updateMatrixWorld(); cam.updateProjectionMatrix();
      renderer.setRenderTarget(dRT); renderer.clear(true, true, false); renderer.render(scene, cam);
      accMat.uniforms.uVP.value.multiplyMatrices(cam.projectionMatrix, cam.matrixWorldInverse);
      renderer.setRenderTarget(accRT); renderer.render(qScene, qCam);
    }
  } finally {
    renderer.setRenderTarget(prev.rt); scene.background = prev.bg; scene.fog = prev.fog; scene.overrideMaterial = prev.ov; renderer.autoClear = prev.auto; renderer.shadowMap.needsUpdate = prev.smu; renderer.setClearColor(prev.cc, prev.ca);
    for (const o of occ) o.layers.disable(L);
    dRT.dispose(); depthMat.dispose(); accMat.dispose(); quad.geometry.dispose();
  }
  YARD_U.uYardVis.value = accRT.texture;
  const px = new Uint16Array(RW * RH * 4); renderer.readRenderTargetPixels(accRT, 0, 0, RW, RH, px);
  const at = (x, z) => { const i = Math.round((x - B.x0) / (B.x1 - B.x0) * (RW - 1)), j = Math.round((z - B.z0) / (B.z1 - B.z0) * (RH - 1)); return +THREE.DataUtils.fromHalfFloat(px[4 * (j * RW + i)]).toFixed(3); };
  let cc = null; cadRoot.traverse((o) => { if (!cc && o.name === 'VMU01_CANOPY') cc = new THREE.Box3().setFromObject(o).getCenter(new THREE.Vector3()); });
  Object.assign(yardVisStats, { dirs: V.dirs, px: [RW, RH], m_per_px: +((B.x1 - B.x0) / RW).toFixed(3), occluders: occ.length, ms: Math.round(performance.now() - t0), open_yard_V: at(60, -60), canopy_centre_V: cc ? at(cc.x, cc.z) : null, bounce: V.bounce });
  markDirty();
}
const chainTex = canvasTex(64, 64, (g, w, h) => {
  g.clearRect(0, 0, w, h); g.strokeStyle = 'rgba(200,205,200,1)'; g.lineWidth = 7;
  g.beginPath(); g.moveTo(0, h / 2); g.lineTo(w / 2, 0); g.lineTo(w, h / 2); g.lineTo(w / 2, h); g.closePath(); g.stroke();
}, [1, 1]);

// ---------------- shader patches (world-space; CAD meshes have no UVs) ----------------
const GLSL_NOISE = `
varying vec3 vWPosX; varying vec3 vWNrmX;
float pxHash( vec2 p ) { p = fract( p * vec2( 123.34, 456.21 ) ); p += dot( p, p + 45.32 ); return fract( p.x * p.y ); }
float pxNoise( vec2 p ) { vec2 i = floor( p ), f = fract( p ); vec2 u = f * f * ( 3.0 - 2.0 * f );
  return mix( mix( pxHash( i ), pxHash( i + vec2( 1.0, 0.0 ) ), u.x ), mix( pxHash( i + vec2( 0.0, 1.0 ) ), pxHash( i + vec2( 1.0, 1.0 ) ), u.x ), u.y ); }
float pxFbm( vec2 p ) { float a = 0.5, s = 0.0; for ( int i = 0; i < 4; i ++ ) { s += a * pxNoise( p ); p = p * 2.03 + 17.1; a *= 0.5; } return s / 0.9375; }
`;
const VERT_WORLD = `#include <project_vertex>
{ vec4 wpX = vec4( transformed, 1.0 ); vec3 wnX = objectNormal;
#ifdef USE_INSTANCING
  wpX = instanceMatrix * wpX; wnX = mat3( instanceMatrix ) * wnX;
#endif
  wpX = modelMatrix * wpX; vWPosX = wpX.xyz; vWNrmX = normalize( mat3( modelMatrix ) * wnX ); }`;
function patchMaterial(m, feats) {
  const keys = Object.keys(feats).filter((k) => feats[k]).sort();
  if (!keys.length) return m;
  m.userData.feats = feats;
  m.onBeforeCompile = (sh) => {
    const f = feats;
    if (f.triRough) Object.assign(sh.uniforms, { uTriRough: { value: f.triRough.tex }, uTriScale: { value: f.triRough.scale }, uTriGain: { value: f.triRough.gain } });
    if (f.wood) sh.uniforms.uWoodAmp = { value: f.wood.amp };
    if (f.macro) Object.assign(sh.uniforms, { uMacroAmp: { value: f.macro.amp }, uMacroScale: { value: f.macro.scale }, uMacroStain: { value: f.macro.stain ?? 0.10 } });
    if (f.yard) Object.assign(sh.uniforms, f.yard);
    if (f.ribs) Object.assign(sh.uniforms, { uRibPitch: { value: f.ribs.pitch }, uRibDepth: { value: f.ribs.depth }, uRibW: { value: f.ribs.w }, uRibTop: { value: f.ribs.top }, uRibGroove: { value: f.ribs.groove } });
    if (f.glass) Object.assign(sh.uniforms, { uGlassVLT: { value: f.glass.vlt }, uGlassF0: { value: f.glass.f0 } });
    const needWorld = f.triRough || f.wood || f.macro || f.ribs || f.yard;
    if (needWorld) {
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vWPosX; varying vec3 vWNrmX;').replace('#include <project_vertex>', VERT_WORLD);
      let decl = GLSL_NOISE;
      if (f.triRough) decl += 'uniform sampler2D uTriRough; uniform float uTriScale; uniform float uTriGain;\n';
      if (f.wood) decl += 'uniform float uWoodAmp;\n';
      if (f.macro) decl += 'uniform float uMacroAmp; uniform float uMacroScale; uniform float uMacroStain;\n';
      if (f.yard) decl += 'uniform sampler2D uYardMap; uniform vec2 uYardO; uniform vec2 uYardS; uniform float uYardDamp; uniform float uYardDirt; uniform float uYardDampRough; uniform sampler2D uYardVis; uniform float uYardVisBounce;\n';
      if (f.ribs) decl += 'uniform float uRibPitch; uniform float uRibDepth; uniform float uRibW; uniform float uRibTop; uniform float uRibGroove;\n';
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\n' + decl);
    }
    if (f.glass) sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nuniform float uGlassVLT; uniform float uGlassF0;');
    if (f.triRough) sh.fragmentShader = sh.fragmentShader.replace('#include <roughnessmap_fragment>', `
float roughnessFactor = roughness;
{ vec3 bw = pow( abs( normalize( vWNrmX ) ), vec3( 4.0 ) ); bw /= ( bw.x + bw.y + bw.z );
  vec3 p = vWPosX * uTriScale;
  float r = texture2D( uTriRough, p.zy ).g * bw.x + texture2D( uTriRough, p.xz ).g * bw.y + texture2D( uTriRough, p.xy ).g * bw.z;
  roughnessFactor = clamp( roughness * r * uTriGain, 0.05, 1.0 ); }`);
    let afterMap = '';
    if (f.wood) afterMap += `
{ vec3 nW = normalize( vWNrmX ); vec3 tW = normalize( cross( vec3( 0.0, 1.0, 0.0 ), nW ) + vec3( 1e-4, 0.0, 1e-4 ) );
  float s = abs( nW.y ) > 0.8 ? vWPosX.x : dot( vWPosX, tW );
  float q = s * 110.0 + 2.2 * pxNoise( vec2( s * 7.0, vWPosX.y * 0.4 ) );
  float g = mix( 0.5 + 0.5 * sin( q * 3.14159 ), pxNoise( vec2( q * 0.9, vWPosX.y * 3.0 ) ), 0.45 );
  float aa = clamp( 1.2 - fwidth( q ) * 0.9, 0.0, 1.0 );
  diffuseColor.rgb *= 1.0 + uWoodAmp * ( g * 2.0 - 1.0 ) * aa; }`;
    if (f.macro) afterMap += `
{ float n = pxFbm( vWPosX.xz / uMacroScale ); float st = smoothstep( 0.58, 0.82, pxFbm( vWPosX.xz / 6.5 + 13.1 ) );
  diffuseColor.rgb *= ( 1.0 + uMacroAmp * ( n * 2.0 - 1.0 ) ) * ( 1.0 - uMacroStain * st ); }`;
    if (f.yard) afterMap += `
float yardDampV = 0.0;
{ vec2 yuv = ( vWPosX.xz - uYardO ) / uYardS;
  float inside = step( 0.0, yuv.x ) * step( yuv.x, 1.0 ) * step( 0.0, yuv.y ) * step( yuv.y, 1.0 );
  vec4 yd = texture2D( uYardMap, clamp( yuv, 0.0, 1.0 ) ) * inside;
  float nD = yd.b;   // precomputed edge noise (buildYardMap)
  yardDampV = smoothstep( 0.18, 0.78, yd.r + 0.55 * ( nD - 0.5 ) ) * smoothstep( 0.01, 0.08, yd.r );
  diffuseColor.rgb *= ( 1.0 - uYardDamp * yardDampV * ( 0.8 + 0.2 * nD ) ) * ( 1.0 - uYardDirt * yd.g ); }`;
    if (afterMap) sh.fragmentShader = sh.fragmentShader.replace('#include <map_fragment>', '#include <map_fragment>\n' + afterMap);
    if (f.yard && !f.triRough) sh.fragmentShader = sh.fragmentShader.replace('#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\nroughnessFactor = clamp( roughnessFactor * ( 1.0 - uYardDampRough * yardDampV ), 0.05, 1.0 );');
    if (f.yard) sh.fragmentShader = sh.fragmentShader.replace('#include <aomap_fragment>', `#include <aomap_fragment>
{ vec2 yuvV = ( vWPosX.xz - uYardO ) / uYardS; float inV = step( 0.0, yuvV.x ) * step( yuvV.x, 1.0 ) * step( 0.0, yuvV.y ) * step( yuvV.y, 1.0 );
  float yv = mix( 1.0, texture2D( uYardVis, clamp( yuvV, 0.0, 1.0 ) ).r, inV ); yv += ( 1.0 - yv ) * uYardVisBounce;
  reflectedLight.indirectDiffuse *= yv; reflectedLight.indirectSpecular *= yv; }`);
    if (f.noFlip) sh.fragmentShader = sh.fragmentShader.replace('#include <normal_fragment_begin>', THREE.ShaderChunk.normal_fragment_begin.replace('normal *= faceDirection;', ''));
    if (f.ribs) sh.fragmentShader = sh.fragmentShader.replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
{ vec3 nW = normalize( vWNrmX ) * faceDirection;
  if ( abs( nW.y ) < 0.7 ) {
    vec3 tW = normalize( cross( vec3( 0.0, 1.0, 0.0 ), nW ) );
    float s = dot( vWPosX, tW ) / uRibPitch; float fr = fract( s );
    float sl = fr < uRibW ? 1.0 : ( ( fr > uRibW + uRibTop && fr < 2.0 * uRibW + uRibTop ) ? -1.0 : 0.0 );
    float fade = 1.0 - smoothstep( 0.10, 0.40, fwidth( s ) );
    vec3 nP = normalize( nW - tW * sl * ( uRibDepth / ( uRibW * uRibPitch ) ) * fade );
    normal = normalize( ( viewMatrix * vec4( nP, 0.0 ) ).xyz );
    float groove = fr > 2.0 * uRibW + uRibTop ? 1.0 : 0.0;
    diffuseColor.rgb *= 1.0 - uRibGroove * groove * fade;
  } }`);
    if (f.glass) sh.fragmentShader = sh.fragmentShader.replace('#include <opaque_fragment>', `#include <opaque_fragment>
{ float nvG = saturate( abs( dot( normal, geometryViewDir ) ) );
  float frG = uGlassF0 + ( 1.0 - uGlassF0 ) * pow( 1.0 - nvG, 5.0 );
  gl_FragColor.a = 1.0 - uGlassVLT * ( 1.0 - frG ); }`);
  };
  m.customProgramCacheKey = () => 'px:' + keys.join(',');
  return m;
}

// ---------------- canonical materials (model/materials.json) ----------------
let MATDB = {};
const LIB = {};
const LEGACY_EXTRA = { CTX_CONCRETE: 'CTX_FACTORY_RC', CTX_ALU_STOCK: 'AL_MILL' };
function canonName(name) {
  let n = name, e = MATDB[n], k = 0;
  if (!e && LEGACY_EXTRA[n]) { n = LEGACY_EXTRA[n]; e = MATDB[n]; }
  while (e && e.alias_of && MATDB[e.alias_of] && k++ < 5) { n = e.alias_of; e = MATDB[n]; }
  return e ? n : null;
}
function lumOf(c) { return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b; }
function libMaterial(name, opts = {}) {
  const cn = canonName(name); if (!cn) return null;
  const e = MATDB[cn];
  const noRibs = !!opts.noRibs && e.procedural?.type === 'ribs_normal';
  const key = noRibs ? cn + '#noribs' : cn;
  if (LIB[key]) return LIB[key];
  let m;
  if (e.glass && !e.glass.opaque) m = makeGlass(cn, e);
  else {
    m = new THREE.MeshPhysicalMaterial({ name: cn, color: new THREE.Color(e.hex), metalness: e.metalness ?? 0, roughness: e.roughness ?? 0.6, side: THREE.DoubleSide, envMapIntensity: 1 });
    if (cn === 'PRECAST_FORMLINER' && PARAMS.PRECAST_HEX) m.color.set(PARAMS.PRECAST_HEX);
    if (HDG_CAL.mats.includes(cn) && HDG_CAL.env !== 1) { m.envMapIntensity = HDG_CAL.env; m.userData.hdgCal = { env: HDG_CAL.env }; }
    if (e.clearcoat) { m.clearcoat = e.clearcoat; m.clearcoatRoughness = e.clearcoatRoughness ?? 0.3; }
    if (e.glass && e.glass.opaque) {
      m.ior = e.glass.ior || 1.52; m.specularIntensity = e.glass.specularIntensity ?? 1;
      if (e.glass.specularColor) m.specularColor.setRGB(...e.glass.specularColor, THREE.LinearSRGBColorSpace);
    }
    const feats = {};
    const T = e.textures;
    if (T) {
      const rep = 1 / (T.size_m || 1);
      if (T.map) { m.map = loadTex(T.map.file, true, rep); if (T.color_with_map_linear) m.color.setRGB(...T.color_with_map_linear, THREE.LinearSRGBColorSpace); }
      if (T.normalMap) m.normalMap = loadTex(T.normalMap.file, false, rep);
      if (T.armMap) { const a = loadTex(T.armMap.file, false, rep); m.aoMap = a; m.aoMapIntensity = 0.7; m.roughnessMap = a; if (T.roughness_with_map) m.roughness = Math.min(2, T.roughness_with_map); }
      if (T.map || T.normalMap || T.armMap) m.userData.needsUV = true;
      if (T.roughnessMap && !T.armMap) feats.triRough = { tex: loadTex(T.roughnessMap.file, false, 1), scale: rep, gain: 1 / (T.roughness_map_mean || 0.5) };
    }
    const P = e.procedural;
    if (P && P.type === 'woodgrain') feats.wood = { amp: P.value_amplitude ?? 0.15 };
    if (P && P.type === 'ribs_normal' && !noRibs) {
      const rect = /rect/i.test(P.profile || '');
      feats.ribs = { pitch: P.pitch_m || 0.1, depth: P.depth_m || 0.02, w: rect ? 0.12 : 0.18, top: rect ? 0.38 : 0.30, groove: rect ? 0.10 : 0.05 };
    }
    if (/CONCRETE_YARD/.test(cn)) feats.macro = { amp: /DAMP/.test(cn) ? 0.05 : 0.08, scale: 23 };
    if (cn === 'CTX_CONCRETE_YARD' && !YARD_CAL.off && T?.map) {
      m.map = yardAlbedoTexture(T.map.file, (meanLin) => {
        const c = new THREE.Color(YARD_CAL.albedo); m.color.setRGB(c.r / meanLin, c.g / meanLin, c.b / meanLin, THREE.LinearSRGBColorSpace);
        m.userData.yardCal = { ...YARD_CAL, texMeanLinear: +meanLin.toFixed(4) }; markDirty();
      });
      if (m.normalMap) m.normalScale.set(YARD_CAL.normalScale, YARD_CAL.normalScale);
      feats.macro = { amp: YARD_CAL.macroAmp, scale: 23, stain: YARD_CAL.macroStain };
      feats.yard = YARD_U;
    }
    if (/CONCRETE_YARD|ASPHALT|GRASS|RED_LINE|YELLOW_LINE|ROAD_MARKING/.test(cn)) feats.noFlip = true;
    if (/ASPHALT/.test(cn)) feats.macro = { amp: 0.06, scale: 17 };
    if (/RED_LINE|YELLOW_LINE|ROAD_MARKING|CONCRETE_YARD_DAMP/.test(cn)) { m.polygonOffset = true; m.polygonOffsetFactor = -2; m.polygonOffsetUnits = -4; }
    patchMaterial(m, feats);
  }
  m.userData.canon = cn; m.userData.entry = e;
  if (noRibs) { m.userData.variant = 'noribs'; m.name = cn; }
  LIB[key] = m; return m;
}
// raster glass: reflection added unattenuated, alpha = 1 - VLT * (1 - Fresnel); the path tracer gets a transmissive copy
function makeGlass(cn, e) {
  const g = e.glass; const vlt = g.vlt ?? 0.4;
  const ior = g.ior_for_rext || g.ior || 1.52;
  const spec = new THREE.Color(1, 1, 1); if (g.specularColor) spec.setRGB(...g.specularColor, THREE.LinearSRGBColorSpace);
  const tint = new THREE.Color(g.tint || e.hex);
  const m = new THREE.MeshPhysicalMaterial({
    name: cn, color: tint.clone().multiplyScalar(0.03), metalness: 0, roughness: Math.max(0.02, e.roughness ?? 0.02), ior, specularIntensity: 1, specularColor: spec,
    envMapIntensity: 1, side: THREE.DoubleSide, transparent: true, depthWrite: false,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
  });
  const f0 = Math.min(1, ((ior - 1) / (ior + 1)) ** 2 * lumOf(spec));
  patchMaterial(m, { glass: { vlt, f0 } });
  m.userData.glass = { vlt, rext: g.rext, f0 };
  m.userData.ptMaterial = new THREE.MeshPhysicalMaterial({
    name: cn + ' (PT)', color: new THREE.Color(g.tint_for_vlt_threejs || g.tint || e.hex), metalness: 0, roughness: 0.02,
    transmission: 1, thickness: 0, ior: g.ior || 2.33, specularIntensity: g.specularIntensity ?? 1, specularColor: spec.clone(), side: THREE.DoubleSide, transparent: false,
  });
  return m;
}
const fallbackCache = new Map();
function fallbackMaterial(src) {
  if (!src) return src;
  if (fallbackCache.has(src)) return fallbackCache.get(src);
  let m;
  if (src.name === 'CTX_FENCE_MESH') m = new THREE.MeshStandardMaterial({ name: src.name, map: chainTex, alphaMap: chainTex, alphaTest: 0.02, transparent: true, depthWrite: false, color: 0x9aa39c, metalness: 0.6, roughness: 0.45, side: THREE.DoubleSide });
  else if (src.name === 'CTX_WINDOW') m = new THREE.MeshPhysicalMaterial({ name: src.name, color: 0x1d2327, metalness: 0, roughness: 0.08, ior: 1.8, side: THREE.DoubleSide });
  else {
    m = new THREE.MeshPhysicalMaterial({ name: src.name, color: src.color ? src.color.clone() : 0xcccccc, metalness: src.metalness ?? 0, roughness: src.roughness ?? 0.7, map: src.map || null, side: THREE.DoubleSide, transparent: !!src.transparent, opacity: src.opacity ?? 1, vertexColors: !!src.vertexColors });
    if (src.emissive) { m.emissive.copy(src.emissive); m.emissiveIntensity = src.emissiveIntensity ?? 1; m.emissiveMap = src.emissiveMap || null; }
    if (src.transparent) m.depthWrite = false;
  }
  m.userData.canon = null; fallbackCache.set(src, m); return m;
}
const _p = new THREE.Vector3(), _n = new THREE.Vector3();
function addWorldUV(mesh) {
  const g = mesh.geometry; if (g.attributes.uv || !g.attributes.position) return;
  mesh.updateWorldMatrix(true, false);
  const pos = g.attributes.position, nor = g.attributes.normal, uv = new Float32Array(pos.count * 2);
  const nm = new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld);
  for (let i = 0; i < pos.count; i++) {
    _p.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld);
    if (nor) _n.fromBufferAttribute(nor, i).applyMatrix3(nm); else _n.set(0, 1, 0);
    const ax = Math.abs(_n.x), ay = Math.abs(_n.y), az = Math.abs(_n.z);
    if (ay >= ax && ay >= az) { uv[2 * i] = _p.x; uv[2 * i + 1] = -_p.z; } else if (ax >= az) { uv[2 * i] = _p.z * Math.sign(_n.x || 1); uv[2 * i + 1] = _p.y; } else { uv[2 * i] = -_p.x * Math.sign(_n.z || 1); uv[2 * i + 1] = _p.y; }
  }
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
}
function nodeExtras(o) { let p = o; while (p) { const u = p.userData; if (u && (u.layer_en || u.layer || u.finish || u.context || u.part)) return u; p = p.parent; } return {}; }
const matStats = { upgraded: {}, fallback: {} };
// builders that model ribs as real geometry say so in the node extras -> library material without the procedural rib normal
function ribsNotWanted(ex) {
  if (!ex) return false;
  if (ex.procedural_ribs === false || ex.ribs_modelled === true) return true;
  if (/REAL GEOMETRY|^\s*NONE/i.test(String(ex.formliner_ribs || ''))) return true;
  if (/^\s*real/i.test(String(ex.rib?.geometry || ''))) return true;
  return /must not add .*rib|real (trapezoidal )?rib geometry/i.test(String(ex.refined || '') + ' ' + String(ex.note || ''));
}
// fine real ribs alias in the GTAO G-buffer: AO renders a smoothed proxy, the beauty pass keeps the real ribs
function makeAoProxy(mesh, R, passes = 2) {
  const g = mesh.geometry; const pos = g.attributes.position; const n = pos.count;
  mesh.updateWorldMatrix(true, false); const M = mesh.matrixWorld, Mi = M.clone().invert();
  const P = new Float32Array(n * 3); const v = new THREE.Vector3();
  for (let i = 0; i < n; i++) { v.fromBufferAttribute(pos, i).applyMatrix4(M); P[3 * i] = v.x; P[3 * i + 1] = v.y; P[3 * i + 2] = v.z; }
  const cells = new Map(); const ck = (x, y, z) => `${Math.floor(x / R)},${Math.floor(y / R)},${Math.floor(z / R)}`;
  for (let i = 0; i < n; i++) { const k = ck(P[3 * i], P[3 * i + 1], P[3 * i + 2]); let a = cells.get(k); if (!a) cells.set(k, a = []); a.push(i); }
  const R2 = R * R; let Q = P;
  for (let pass = 0; pass < passes; pass++) {
  const out = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const x = P[3 * i], y = P[3 * i + 1], z = P[3 * i + 2]; const cx = Math.floor(x / R), cy = Math.floor(y / R), cz = Math.floor(z / R);
    let sx = 0, sy = 0, sz = 0, c = 0;
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (let d = -1; d <= 1; d++) {
      const L = cells.get(`${cx + a},${cy + b},${cz + d}`); if (!L) continue;
      for (const j of L) { const dx = P[3 * j] - x, dy = P[3 * j + 1] - y, dz = P[3 * j + 2] - z; if (dx * dx + dy * dy + dz * dz <= R2) { sx += Q[3 * j]; sy += Q[3 * j + 1]; sz += Q[3 * j + 2]; c++; } }
    }
    out[3 * i] = sx / c; out[3 * i + 1] = sy / c; out[3 * i + 2] = sz / c;
  }
  Q = out;
  }
  const out = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { v.set(Q[3 * i], Q[3 * i + 1], Q[3 * i + 2]).applyMatrix4(Mi); out[3 * i] = v.x; out[3 * i + 1] = v.y; out[3 * i + 2] = v.z; }
  const pg = new THREE.BufferGeometry(); pg.setAttribute('position', new THREE.BufferAttribute(out, 3)); if (g.index) pg.setIndex(g.index);
  pg.computeVertexNormals(); pg.computeBoundingSphere(); pg.computeBoundingBox(); return pg;
}
function ribPitchM(ex) { const p = +(ex?.rib?.pitch || 0); return p > 5 ? p / 1000 : p; }
function upgradeMesh(o, kind) {
  const src = o.material; const name = src?.name || '';
  const exN = nodeExtras(o);
  let m = name ? libMaterial(name, { noRibs: ribsNotWanted(exN) }) : null;
  if (m?.userData.variant === 'noribs') {
    matStats.noRibs = (matStats.noRibs || 0) + 1;
    const pitch = ribPitchM(exN);
    if (pitch > 0.01 && pitch < 0.5 && o.geometry?.attributes.position) { o.userData.aoProxy = makeAoProxy(o, 1.2 * pitch, 3); matStats.aoProxy = (matStats.aoProxy || 0) + 1; }
  }
  if (m) matStats.upgraded[m.userData.canon] = (matStats.upgraded[m.userData.canon] || 0) + 1;
  else { m = fallbackMaterial(src); matStats.fallback[name || '(unnamed)'] = (matStats.fallback[name || '(unnamed)'] || 0) + 1; }
  o.material = m;
  if (m.userData.needsUV && !o.geometry.attributes.uv) addWorldUV(o);
  o.receiveShadow = true;
  o.castShadow = !m.userData.glass && !(m.transparent && !m.alphaTest) && kind !== 'flat';
  if (m.userData.glass) { o.userData.noAO = true; o.renderOrder = 2; }
  const ex = exN;
  if (o.geometry && o.geometry.index) triCount += o.geometry.index.count / 3; else if (o.geometry?.attributes.position) triCount += o.geometry.attributes.position.count / 3;
  return ex;
}

// ---------------- surroundings: neutral far ground (CC0 asphalt texture; no aerial imagery) ----------------
const surrGroup = new THREE.Group(); scene.add(surrGroup);
const BACKDROP = { size: 16000, y: -0.45, albedo: '#8E8A82', tile: 2.1, texMeanSRGB: 69,
  map: 'textures/clean_asphalt/clean_asphalt_diff_1k.jpg', normal: 'textures/clean_asphalt/clean_asphalt_nor_gl_1k.jpg' };
function buildBackdropGround(groundMinY) {
  const y = groundMinY !== null ? Math.min(BACKDROP.y, groundMinY - 0.35) : BACKDROP.y;
  const g = new THREE.PlaneGeometry(BACKDROP.size, BACKDROP.size); g.rotateX(-Math.PI / 2);
  const uv = g.attributes.uv, pos = g.attributes.position;   // UVs in texture tiles (metres / tile size)
  for (let i = 0; i < uv.count; i++) uv.setXY(i, pos.getX(i) / BACKDROP.tile, -pos.getZ(i) / BACKDROP.tile);
  const m = new THREE.MeshStandardMaterial({ name: 'BACKDROP_GROUND', map: loadTex(BACKDROP.map, true, 1), normalMap: loadTex(BACKDROP.normal, false, 1), roughness: 0.95, metalness: 0 });
  const c = new THREE.Color(BACKDROP.albedo), k = 1 / srgbToLin(BACKDROP.texMeanSRGB / 255);   // tint the dark asphalt texture to a weathered grey
  m.color.setRGB(c.r * k, c.g * k, c.b * k, THREE.LinearSRGBColorSpace);
  patchMaterial(m, { macro: { amp: 0.12, scale: 45, stain: 0.12 }, noFlip: true });
  const mesh = new THREE.Mesh(g, m); mesh.position.y = y; mesh.receiveShadow = true; mesh.name = 'Backdrop ground';
  mesh.userData = { context: '远景地面', part: '示意地面（CC0 沥青纹理，非实景）' };
  surrGroup.add(mesh);
  return mesh;
}

// ---------------- vegetation (palms + trees, alpha-tested canvas foliage) / people / cars ----------------
const vegGroup = new THREE.Group(); scene.add(vegGroup);
const vegInstanced = [];
function foliageTexture(w, h, draw, thr = 0.4) {
  const c0 = document.createElement('canvas'); c0.width = w; c0.height = h; const g0 = c0.getContext('2d', { willReadFrequently: true }); draw(g0, w, h);
  const cover = (d, s) => { let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] * s > thr * 255) n++; return n / (d.length / 4); };
  const target = cover(g0.getImageData(0, 0, w, h).data, 1);
  const levels = [c0]; let prev = c0;
  while (prev.width > 1 || prev.height > 1) {
    const lw = Math.max(1, prev.width >> 1), lh = Math.max(1, prev.height >> 1);
    const c = document.createElement('canvas'); c.width = lw; c.height = lh; const g = c.getContext('2d', { willReadFrequently: true });
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high'; g.drawImage(prev, 0, 0, lw, lh);
    const id = g.getImageData(0, 0, lw, lh); const d = id.data;
    let lo = 0.5, hi = 12; for (let it = 0; it < 14; it++) { const m = (lo + hi) / 2; if (cover(d, m) < target) lo = m; else hi = m; }
    for (let i = 3; i < d.length; i += 4) d[i] = Math.min(255, d[i] * hi);
    g.putImageData(id, 0, 0); levels.push(c); prev = c;
  }
  const t = new THREE.CanvasTexture(c0); t.mipmaps = levels; t.generateMipmaps = false;
  t.minFilter = THREE.LinearMipmapLinearFilter; t.magFilter = THREE.LinearFilter;
  t.wrapS = THREE.ClampToEdgeWrapping; t.wrapT = THREE.ClampToEdgeWrapping; t.anisotropy = MAX_ANISO; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function frondTexture(seed, baseHSL) {
  return foliageTexture(256, 1024, (g, w, h) => {
    g.clearRect(0, 0, w, h); const r = rnd(seed); const [H0, S0, L0] = baseHSL;
    const N = 78;
    for (let i = 0; i < N; i++) {
      const v = (i + 0.5) / N;
      const L = w * (0.55 + 0.45 * Math.sin(Math.PI * Math.min(1, 0.12 + v * 0.95))) * (0.8 + 0.2 * r());
      const y0 = (1 - v) * h, y1 = y0 - h * (0.05 + 0.04 * r()), lw = 3.2 + 3.2 * r();
      const yellow = r() < 0.05;
      g.fillStyle = yellow ? `hsl(${52 + 8 * r()},${32 + 8 * r()}%,${36 + 8 * r()}%)` : `hsl(${H0 - 8 + 16 * r()},${S0 - 7 + 14 * r()}%,${L0 - 6 + 13 * r()}%)`;
      g.beginPath(); g.moveTo(4, y0 + 1.5);
      g.quadraticCurveTo(L * 0.45, y0 - (y0 - y1) * 0.22 - lw, L, y1 + (r() - 0.5) * 6);
      g.quadraticCurveTo(L * 0.5, y0 - (y0 - y1) * 0.22 + lw * 0.55, 4, y0 + 4.5);
      g.fill();
    }
    g.fillStyle = `hsl(${H0 - 14},${S0 - 6}%,${L0 + 10}%)`; g.fillRect(0, 0, 6, h);
  });
}
function curtainTexture(seed, baseHSL) {
  return foliageTexture(256, 512, (g, w, h) => {
    g.clearRect(0, 0, w, h); const r = rnd(seed); const [H0, S0, L0] = baseHSL;
    for (let k = 0; k < 240; k++) {
      const x = 10 + r() * (w - 20), y = r() * h * 0.9, len = 40 + 50 * r(), wd = 4.5 + 4 * r(), ang = (r() - 0.5) * 0.6;
      g.save(); g.translate(x, y); g.rotate(ang);
      g.fillStyle = `hsl(${H0 - 7 + 14 * r()},${S0 - 8 + 16 * r()}%,${L0 - 6 + 15 * r()}%)`;
      g.beginPath(); g.moveTo(0, 0); g.bezierCurveTo(wd, len * 0.3, -wd * 0.4, len * 0.65, 1.5 * Math.sin(k), len); g.bezierCurveTo(-wd * 1.2, len * 0.6, -wd * 0.6, len * 0.3, 0, 0); g.fill(); g.restore();
    }
  });
}
function trunkTexture() {
  return canvasTex(64, 512, (g, w, h) => {
    const r = rnd(5); g.fillStyle = '#f2f1ec'; g.fillRect(0, 0, w, h);
    for (let y = 0; y < h; y += 4 + r() * 4) { g.fillStyle = `rgba(90,86,76,${0.06 + 0.12 * r()})`; g.fillRect(0, y, w, 1 + r() * 1.5); }
    for (let x = 0; x < w; x += 2) { g.fillStyle = `rgba(80,78,70,${0.04 * r()})`; g.fillRect(x, 0, 1, h); }
    for (let k = 0; k < 40; k++) { g.fillStyle = `rgba(60,58,50,${0.05 + 0.08 * r()})`; g.fillRect(r() * w, r() * h, 2 + r() * 8, 6 + r() * 30); }
  }, [1, 5], true);
}
const lin = (hex) => new THREE.Color(hex);
function palmCrownGeometry(seed, VP) {
  const r = rnd(seed); const F = VP.palm; const pos = [], nor = [], uv = [], col = [], idx = [];
  const up = new THREE.Vector3(0, 1, 0), C = new THREE.Vector3(0, F.shaftLen - 0.05, 0);
  const nF = Math.round(F.count[0] + r() * (F.count[1] - F.count[0])), seg = 12;
  const base = lin(F.frond), old = lin(F.old), dead = lin(F.dead);
  const nOld = 1 + (r() < 0.5 ? 1 : 0);
  for (let f = 0; f < nF + nOld; f++) {
    const isOld = f >= nF; const age = isOld ? 1 : f / Math.max(1, nF - 1);
    const az = f * 2.39996 + r() * 0.4;
    let e0, tipY;
    if (isOld) { e0 = -THREE.MathUtils.degToRad(58 + 14 * r()); tipY = -(2.6 + 0.8 * r()); }
    else if (age < 0.28) { e0 = THREE.MathUtils.degToRad(48 + 14 * r()); tipY = 0.6 + 0.9 * r(); }
    else if (age < 0.7) { e0 = THREE.MathUtils.degToRad(18 + 16 * r()); tipY = -(0.3 + 0.7 * r()); }
    else { e0 = -THREE.MathUtils.degToRad(15 + 30 * r()); tipY = -(0.9 + 1.3 * r()); }
    const Lf = (F.len[0] + r() * (F.len[1] - F.len[0])) * 1.18;
    const d = Math.max(0, Math.sin(e0) - tipY / Lf);
    const dirH = new THREE.Vector3(Math.cos(az), 0, Math.sin(az));
    const rach = (t) => C.clone().addScaledVector(dirH, Lf * t * Math.cos(e0) * (1 - 0.1 * t)).addScaledVector(up, Lf * t * Math.sin(e0) - d * Lf * t * t);
    const Wl = F.leaflet[0] + r() * (F.leaflet[1] - F.leaflet[0]);
    const tint = isOld ? (r() < 0.7 ? old : dead) : null; const lv = 0.9 + 0.2 * r();
    const cr = tint ? tint.r / base.r : lv, cg = tint ? tint.g / base.g : lv, cb = tint ? tint.b / base.b : lv;
    for (const side of [-1, 1]) for (const layer of [0, 1]) {
      const phi = THREE.MathUtils.degToRad(layer ? 6 + 12 * r() : F.leafDroop[0] + r() * (F.leafDroop[1] - F.leafDroop[0]) + (isOld ? 20 : 0));
      const vb = pos.length / 3;
      for (let k = 0; k <= seg; k++) {
        const t = k / seg, P = rach(t), T = rach(Math.min(1, t + 0.02)).sub(rach(Math.max(0, t - 0.02))).normalize();
        const Sr = new THREE.Vector3().crossVectors(T, up); if (Sr.lengthSq() < 1e-6) Sr.set(-dirH.z, 0, dirH.x); Sr.normalize();
        const upL = new THREE.Vector3().crossVectors(Sr, T).normalize();
        const leaf = Sr.clone().multiplyScalar(side * Math.cos(phi)).addScaledVector(upL, -Math.sin(phi)).addScaledVector(T, 0.3).normalize();
        const W = Wl * (layer ? 0.78 : 1) * Math.pow(Math.sin(Math.PI * (0.05 + 0.9 * t)), 0.65);
        const Q2 = P.clone().addScaledVector(leaf, W);
        const n1 = new THREE.Vector3().crossVectors(T, leaf).normalize(); if (n1.y < 0) n1.negate();
        n1.addScaledVector(P.clone().sub(C).setY(0).normalize(), 0.3).normalize();
        pos.push(P.x, P.y, P.z, Q2.x, Q2.y, Q2.z); nor.push(n1.x, n1.y, n1.z, n1.x, n1.y, n1.z); uv.push(0, t, 1, t); col.push(cr, cg, cb, 1, cr, cg, cb, 1);
        if (k < seg) { const b = vb + k * 2; idx.push(b, b + 2, b + 1, b + 1, b + 2, b + 3); }
      }
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2)); g.setAttribute('color', new THREE.Float32BufferAttribute(col, 4)); g.setIndex(idx);
  return g;
}
function palmTrunkGeometry(VP) {
  const T = VP.palm.trunk;
  const prof = [[T.rFlare, 0], [(T.rFlare + T.rBase) / 2, 0.02], [T.rBase, 0.055], [T.rBase * 0.99, 0.18], [T.rBulge, T.bulgeAt], [(T.rBulge + T.rTop) / 2, 0.75], [T.rTop, 1.0]];
  return new THREE.LatheGeometry(prof.map(([x, y]) => new THREE.Vector2(x, y)), 14);
}
function crownshaftGeometry(VP) {
  const P = VP.palm; const shaft = new THREE.CylinderGeometry(P.shaftTop, P.shaftBase, P.shaftLen, 14, 1); shaft.translate(0, P.shaftLen / 2, 0);
  const spear = new THREE.ConeGeometry(P.spearW / 2, P.spearLen, 8); spear.translate(0, P.shaftLen + P.spearLen / 2, 0);
  return mergeGeometries([shaft.toNonIndexed(), spear.toNonIndexed()]);
}
function polyProfile(round, y) {
  if (round) return Math.sqrt(Math.max(0, 1 - Math.pow((y - 0.55) / 0.47, 2)));
  const base = Math.min(1, 0.55 + y / 0.12 * 0.45);
  return (y < 0.35 ? 1 : 1 - 0.75 * (y - 0.35) / 0.65) * base;
}
function polyCardsGeometry(seed, round) {
  const r = rnd(seed); const pos = [], nor = [], uv = [], idx = [];
  const L = 16;
  const quad = (p0, p1, p2, p3, n) => { const b = pos.length / 3; for (const p of [p0, p1, p2, p3]) { pos.push(...p); nor.push(...n); } uv.push(0, 0, 1, 0, 0, 1, 1, 1); idx.push(b, b + 1, b + 2, b + 2, b + 1, b + 3); };
  for (let i = 0; i < L; i++) {
    const yc = (i + 0.5) / L, hc = 2.2 / L, rr = Math.max(0.18, polyProfile(round, yc)); const y0 = Math.max(0, yc - hc / 2), y1 = Math.min(1.04, yc + hc / 2);
    for (let j = 0; j < 2; j++) {
      const a = i * 0.9 + j * Math.PI / 2 + r() * 0.4, cx = Math.cos(a) * rr * 1.05, cz = Math.sin(a) * rr * 1.05;
      quad([-cx, y0, -cz], [cx, y0, cz], [-cx, y1, -cz], [cx, y1, cz], [0, 1, 0]);
    }
    for (let j = 0; j < 4; j++) {
      const a = i * 0.7 + j * Math.PI / 2 + r() * 0.5, R = rr * 0.85, hw = rr * 0.75;
      const cx = Math.cos(a) * R, cz = Math.sin(a) * R, tx = -Math.sin(a) * hw, tz = Math.cos(a) * hw, out = 0.18 * rr;
      const n = new THREE.Vector3(Math.cos(a), 0.5, Math.sin(a)).normalize().toArray();
      quad([cx - tx, y0, cz - tz], [cx + tx, y0, cz + tz], [cx - tx + Math.cos(a) * out, y1, cz - tz + Math.sin(a) * out], [cx + tx + Math.cos(a) * out, y1, cz + tz + Math.sin(a) * out], n);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2)); g.setIndex(idx);
  return g;
}
function polyCoreGeometry(round) {
  const pts = []; for (let i = 0; i <= 14; i++) { const y = i / 14; pts.push(new THREE.Vector2(0.62 * polyProfile(round, y) + 0.01, y * 0.98)); }
  return new THREE.LatheGeometry(pts, 10);
}
function hexHSL(hex) { const c = new THREE.Color(hex); const o = {}; c.getHSL(o, THREE.SRGBColorSpace); return [o.h * 360, o.s * 100, o.l * 100]; }
function rng2(v, d) { return Array.isArray(v) && v.length >= 2 ? [+v[0], +v[1]] : (typeof v === 'number' ? [v, v] : d); }
function vegParams(notes) {
  const P = {
    palm: { frond: MATDB.CTX_PALM_FROND?.hex || '#4C5A34', old: '#6B6A45', dead: '#7A6C4C', trunkColor: MATDB.CTX_PALM_TRUNK?.hex || '#9A988E', crownshaft: '#6F7F45', shaftRough: 0.55,
      count: [14, 18], len: [3.2, 4.2], leaflet: [0.6, 0.9], leafDroop: [30, 50], shaftLen: 1.6, shaftBase: 0.24, shaftTop: 0.2, spearLen: 1.8, spearW: 0.12,
      trunk: { rBase: 0.26, rTop: 0.21, rBulge: 0.28, bulgeAt: 0.45, rFlare: 0.34 }, hMeaning: 'total' },
    poly: { leaf: '#34482B', rough: 0.65, trunk: '#5E5A50', trunkR: 0.08, bottom: 0.6 },
  };
  const n = notes || {}; const rp = n.royal_palm || {}; const po = n.polyalthia || {};
  if (/crownshaft|attach/i.test(String(rp.heights?.h || ''))) P.palm.hMeaning = 'attach';
  if (rp.trunk) { const t = rp.trunk; P.palm.trunk = { rBase: +t.radius_base || 0.26, rTop: +t.radius_top || 0.21, rBulge: +(t.bulge?.radius) || 0.28, bulgeAt: +(t.bulge?.at_fraction) || 0.45, rFlare: +(t.flare?.radius) || 0.34 }; if (t.colour) P.palm.trunkColor = t.colour; }
  if (rp.crownshaft) { const c = rp.crownshaft; P.palm.crownshaft = c.colour || P.palm.crownshaft; P.palm.shaftRough = +c.roughness || 0.55; P.palm.shaftLen = +c.length || 1.6; P.palm.shaftBase = +c.radius_base || 0.24; P.palm.shaftTop = +c.radius_top || 0.2; }
  if (rp.fronds) {
    const f = rp.fronds; P.palm.frond = f.colour || P.palm.frond; P.palm.count = rng2(f.count, P.palm.count); P.palm.len = rng2(f.length, P.palm.len);
    const m1 = String(f.colour_variation || '').match(/#[0-9a-fA-F]{6}/g); if (m1?.[0]) P.palm.old = m1[0]; if (m1?.[1]) P.palm.dead = m1[1];
    const lm = String(f.leaflets || '').match(/(\d\.\d+)\s*-\s*(\d\.\d+)\s*m long/); if (lm) P.palm.leaflet = [+lm[1], +lm[2]];
    const dm = String(f.leaflets || '').match(/drooping at ~?(\d+)\s*-\s*(\d+)\s*deg/); if (dm) P.palm.leafDroop = [+dm[1], +dm[2]];
    if (f.spear_leaf) { P.palm.spearLen = +f.spear_leaf.length || 1.8; P.palm.spearW = +f.spear_leaf.width || 0.12; }
  }
  if (po.crown) { P.poly.leaf = po.crown.colour || P.poly.leaf; P.poly.rough = +po.crown.roughness || 0.65; P.poly.bottom = +po.crown.bottom || 0.6; }
  if (po.trunk) { P.poly.trunk = po.trunk.colour || P.poly.trunk; P.poly.trunkR = +po.trunk.radius || 0.08; }
  P.palm.count = P.palm.count.map((c) => THREE.MathUtils.clamp(Math.round(c) || 15, 8, 22));
  return P;
}
function collectTrees(F, notes) {
  const palms = [], polys = [];
  const push = (t, defSpecies) => {
    if (!t || !t.p) return; const sp = String(t.species || t.type || defSpecies || '').toLowerCase();
    if (/poly|mast|ashoka|broad|tree|rain|angsana|tembusu/.test(sp) && !/palm|royal/.test(sp)) polys.push({ ...t, round: /broad|rain|angsana|tembusu/.test(sp) }); else palms.push(t);
  };
  for (const t of F.palms || []) push(t, 'royal_palm');
  for (const k of ['trees', 'polyalthia', 'broadleaf']) for (const t of F[k] || []) push(t, k === 'trees' ? 'polyalthia' : k);
  if (notes) for (const k of ['palms', 'trees', 'polyalthia']) if (Array.isArray(notes[k])) for (const t of notes[k]) push(t, k === 'palms' ? 'royal_palm' : 'polyalthia');
  return { palms, polys };
}
function buildVegetation(F, notes) {
  const VP = vegParams(notes);
  const mp = F.meta?.params || {}; VP.palm.crownAbove = +mp.CROWN_ABOVE_ATTACH || 1.9;
  if (/overall|total/i.test(String(F.meta?.palm_h || ''))) VP.palm.hMeaning = 'total';
  const { palms, polys } = collectTrees(F, notes);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), v = new THREE.Vector3(), s = new THREE.Vector3();
  const addIM = (geo, mat, n, name, noAO) => { const im = new THREE.InstancedMesh(geo, mat, n); im.name = name; im.castShadow = true; im.receiveShadow = true; im.userData.noAO = !!noAO; im.userData.veg = true; vegGroup.add(im); vegInstanced.push(im); return im; };
  if (palms.length) {
    const trunkMat = new THREE.MeshStandardMaterial({ name: 'CTX_PALM_TRUNK', color: new THREE.Color(VP.palm.trunkColor), map: trunkTexture(), roughness: 0.9 });
    const shaftMat = new THREE.MeshStandardMaterial({ name: 'PALM_CROWNSHAFT', color: new THREE.Color(VP.palm.crownshaft), roughness: VP.palm.shaftRough });
    const trunks = addIM(palmTrunkGeometry(VP), trunkMat, palms.length, 'Royal palm trunks');
    const shafts = addIM(crownshaftGeometry(VP), shaftMat, palms.length, 'Royal palm crownshafts');
    const NV = 4; const crowns = [];
    for (let k = 0; k < NV; k++) {
      const mat = new THREE.MeshStandardMaterial({ name: 'CTX_PALM_FROND', map: frondTexture(31 + k * 17, hexHSL(VP.palm.frond)), alphaTest: 0.4, alphaToCoverage: true, side: THREE.DoubleSide, roughness: 0.7, vertexColors: true, color: 0xffffff });
      const n = palms.filter((_, i) => i % NV === k).length;
      crowns.push(n ? addIM(palmCrownGeometry(101 + 53 * k, VP), mat, n, 'Royal palm fronds ' + k, true) : null);
    }
    const cnt = new Array(NV).fill(0);
    palms.forEach((p, i) => {
      let hAttach = +p.h_crown || +p.h || 11; if (!p.h_crown && VP.palm.hMeaning === 'total') hAttach = Math.max(3, hAttach - VP.palm.crownAbove);
      const trunkH = Math.max(1.2, hAttach - VP.palm.shaftLen);
      const hTot = +p.h_total || (VP.palm.hMeaning === 'total' ? +p.h : hAttach + VP.palm.crownAbove);
      const girth = p.trunk_d ? p.trunk_d / (2 * VP.palm.trunk.rBase) : 0.92 + 0.16 * ((i * 0.618) % 1);
      e.set(p.lean || 0, p.rot || 0, (p.lean || 0) * 0.7); q.setFromEuler(e);
      m4.compose(v.set(...p.p), q, s.set(girth, trunkH, girth)); trunks.setMatrixAt(i, m4);
      const top = new THREE.Vector3(0, trunkH, 0).applyQuaternion(q).add(new THREE.Vector3(...p.p));
      const sc2 = THREE.MathUtils.clamp(hTot / 12.5, 0.85, 1.2);
      const q2 = new THREE.Quaternion().setFromEuler(new THREE.Euler((p.lean || 0) * 0.5, p.rot || 0, (p.lean || 0) * 0.35));
      m4.compose(top, q2, s.set(girth, 1, girth)); shafts.setMatrixAt(i, m4);
      m4.compose(top, q2, s.set(sc2, sc2, sc2)); const k = i % NV; crowns[k].setMatrixAt(cnt[k]++, m4);
    });
  }
  if (polys.length) {
    const byRound = [polys.filter((t) => !t.round), polys.filter((t) => t.round)];
    const trunkMat = new THREE.MeshStandardMaterial({ name: 'POLYALTHIA_TRUNK', color: new THREE.Color(VP.poly.trunk), roughness: 0.9 });
    const tg = new THREE.CylinderGeometry(1, 1.15, 1, 8); tg.translate(0, 0.5, 0);
    const trunks = addIM(tg, trunkMat, polys.length, 'Tree trunks'); let ti = 0;
    byRound.forEach((list, ri) => {
      if (!list.length) return; const round = ri === 1;
      const leafMat = patchMaterial(new THREE.MeshStandardMaterial({ name: 'POLYALTHIA_LEAF', map: curtainTexture(71 + ri, hexHSL(VP.poly.leaf)), alphaTest: 0.4, alphaToCoverage: true, side: THREE.DoubleSide, roughness: VP.poly.rough }), { noFlip: true });
      const coreMat = new THREE.MeshStandardMaterial({ name: 'POLYALTHIA_CORE', color: new THREE.Color(VP.poly.leaf).multiplyScalar(0.55), roughness: 1 });
      const cards = addIM(polyCardsGeometry(9 + ri, round), leafMat, list.length, (round ? 'Broadleaf' : 'Polyalthia') + ' foliage', true);
      const core = addIM(polyCoreGeometry(round), coreMat, list.length, (round ? 'Broadleaf' : 'Polyalthia') + ' core');
      list.forEach((t, i) => {
        const H = +t.h || (round ? 7 : 8); const R = +t.r || +t.crown_r || (t.crown_d ? t.crown_d / 2 : (round ? 2.6 : 1.1));
        const b0 = round ? 2.0 : VP.poly.bottom;
        m4.compose(v.set(t.p[0], (t.p[1] || 0) + b0, t.p[2]), q.setFromEuler(e.set(0, t.rot || i * 1.7, 0)), s.set(R, Math.max(1, H - b0), R)); cards.setMatrixAt(i, m4); core.setMatrixAt(i, m4);
        m4.compose(v.set(...t.p), q.identity(), s.set(VP.poly.trunkR * (round ? 2 : 1), b0 + 0.3, VP.poly.trunkR * (round ? 2 : 1))); trunks.setMatrixAt(ti++, m4);
      });
    });
  }
  if (F.shrubs?.length) {
    const shrubGeo = new THREE.IcosahedronGeometry(1, 2);
    const shrubs = addIM(shrubGeo, new THREE.MeshStandardMaterial({ name: 'VERGE_SHRUB', color: 0x4a5733, roughness: 0.95 }), F.shrubs.length, 'Verge shrubs');
    F.shrubs.forEach((sb, i) => { m4.compose(v.set(sb.p[0], sb.r * 0.25, sb.p[2]), q.identity(), s.set(sb.r, sb.r * 0.42, sb.r)); shrubs.setMatrixAt(i, m4); });
  }
  vegStats.palms = palms.length; vegStats.polys = polys.length; vegStats.hMeaning = VP.palm.hMeaning; vegStats.crownAbove = VP.palm.crownAbove; vegStats.frondCount = VP.palm.count;
  const skin = new THREE.MeshStandardMaterial({ color: 0x9b6f4f, roughness: 0.7 });
  const trousers = new THREE.MeshStandardMaterial({ color: 0x2e3a4b, roughness: 0.85 });
  const helmetMat = new THREE.MeshStandardMaterial({ color: 0xf5f5f0, roughness: 0.4 });
  const legGeo = new THREE.CylinderGeometry(0.075, 0.065, 0.82, 8); legGeo.translate(0, 0.41, 0);
  const torsoGeo = new THREE.CapsuleGeometry(0.19, 0.42, 4, 10); torsoGeo.scale(1, 1, 0.62); torsoGeo.translate(0, 1.17, 0);
  const headGeo = new THREE.SphereGeometry(0.105, 14, 10); headGeo.translate(0, 1.6, 0);
  const helmetGeo = new THREE.SphereGeometry(0.125, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2); helmetGeo.translate(0, 1.63, 0);
  const armGeo = new THREE.CylinderGeometry(0.055, 0.045, 0.62, 6); armGeo.translate(0, -0.31, 0);
  for (const p of F.people || []) {
    const g = new THREE.Group(); const k = (p.h || 1.7) / 1.74;
    const vestMat = new THREE.MeshStandardMaterial({ color: p.vest || '#f2c200', roughness: 0.6 });
    for (const dx of [-0.1, 0.1]) { const l = new THREE.Mesh(legGeo, trousers); l.position.x = dx; g.add(l); }
    g.add(new THREE.Mesh(torsoGeo, vestMat), new THREE.Mesh(headGeo, skin), new THREE.Mesh(helmetGeo, helmetMat));
    for (const dx of [-0.25, 0.25]) { const a = new THREE.Mesh(armGeo, vestMat); a.position.set(dx, 1.42, 0); a.rotation.z = dx * 0.25; g.add(a); }
    g.scale.setScalar(k); g.position.set(...p.p); g.rotation.y = p.rot || 0;
    g.traverse((o) => { if (o.isMesh) { o.castShadow = true; } });
    vegGroup.add(g);
  }
  const carYaw = F.axis_x ? Math.atan2(-F.axis_x[1], F.axis_x[0]) : 0;
  const bodyGeo = new THREE.BoxGeometry(4.5, 0.72, 1.8); bodyGeo.translate(0, 0.62, 0);
  const cabGeo = new THREE.BoxGeometry(2.4, 0.58, 1.62); cabGeo.translate(-0.2, 1.27, 0);
  const wheelGeo = new THREE.CylinderGeometry(0.33, 0.33, 0.24, 14); wheelGeo.rotateX(Math.PI / 2);
  const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x1b2328, metalness: 0, roughness: 0.06, ior: 1.6 });
  const tyre = new THREE.MeshStandardMaterial({ color: 0x151515, roughness: 0.9 });
  for (const c of F.cars || []) {
    const g = new THREE.Group();
    const paint = new THREE.MeshPhysicalMaterial({ color: c.color || '#d9dcdf', metalness: 0.5, roughness: 0.35, clearcoat: 1, clearcoatRoughness: 0.08 });
    g.add(new THREE.Mesh(bodyGeo, paint), new THREE.Mesh(cabGeo, glassMat));
    for (const [x, z] of [[1.45, 0.8], [1.45, -0.8], [-1.45, 0.8], [-1.45, -0.8]]) { const w = new THREE.Mesh(wheelGeo, tyre); w.position.set(x, 0.33, z); g.add(w); }
    g.position.set(...c.p); g.rotation.y = carYaw + (c.rot || 0);
    g.traverse((o) => { if (o.isMesh) o.castShadow = true; }); vegGroup.add(g);
  }
}
const vegStats = { palms: 0, polys: 0 };

// ---------------- labels: screen-space declutter in priority order (VMU names first) [?declutter=0] ----------------
const labelGroup = new THREE.Group(); scene.add(labelGroup);
const DECLUTTER = { on: Q.get('declutter') !== '0', gap: 2, hyst: 4, last: null };
function addLabel(text, pos, cls = '', prio = 50) {
  const d = document.createElement('div'); d.className = 'lbl ' + cls; d.textContent = text;
  const o = new CSS2DObject(d); o.position.copy(pos); o.userData.prio = prio; labelGroup.add(o); return o;
}
function declutterLabels() {
  const root = labelRenderer.domElement, objs = labelGroup.children.filter((o) => o.isCSS2DObject);
  const reset = () => objs.forEach((o) => { o.element.style.visibility = ''; delete o.element.dataset.dc; });
  if (!DECLUTTER.on) { reset(); DECLUTTER.last = null; return; }
  if (root.style.display === 'none' || !labelGroup.visible) return;
  const vw = innerWidth, vh = innerHeight, G = DECLUTTER.gap;
  const blocked = [];
  for (const el of document.querySelectorAll('.panel')) {
    if (getComputedStyle(el).display === 'none') continue; const r = el.getBoundingClientRect(); if (r.width > 0 && r.height > 0) blocked.push([r.left, r.top, r.right, r.bottom]);
  }
  for (const o of measGroup.children) if (o.isCSS2DObject && o.element.style.display !== 'none') { const r = o.element.getBoundingClientRect(); blocked.push([r.left, r.top, r.right, r.bottom]); }
  const items = [];
  for (const o of objs) {
    const el = o.element; if (el.style.display === 'none' || el.parentNode !== root) continue;
    const r = el.getBoundingClientRect(); if (!(r.width > 0 && r.height > 0)) continue;
    items.push({ o, el, prio: o.userData.prio ?? 50, box: [r.left, r.top, r.right, r.bottom], wasHidden: !!el.dataset.dc });
  }
  items.sort((a, b) => a.prio - b.prio);
  const placed = []; const res = { shown: 0, shifted: 0, hidden: [] };
  const hits = (b, m) => { if (b[0] < m || b[1] < m || b[2] > vw - m || b[3] > vh - m) return 'offscreen';
    for (const q of blocked) if (b[0] < q[2] + m && b[2] > q[0] - m && b[1] < q[3] + m && b[3] > q[1] - m) return 'panel';
    for (const q of placed) if (b[0] < q[2] + m && b[2] > q[0] - m && b[1] < q[3] + m && b[3] > q[1] - m) return 'overlap';
    return null; };
  for (const it of items) {
    const h = it.box[3] - it.box[1], m = G + (it.wasHidden ? DECLUTTER.hyst : 0); let dy = null, why = null;
    for (const d of [0, -(h + 3), h + 3]) { const b = [it.box[0], it.box[1] + d, it.box[2], it.box[3] + d]; const w = hits(b, m); if (!w) { dy = d; placed.push(b); break; } if (d === 0) why = w; }
    it.dy = dy; it.why = why;
    if (dy === null) res.hidden.push([it.el.textContent, why]); else { res.shown++; if (dy) res.shifted++; }
  }
  for (const it of items) {
    if (it.dy === null) { it.el.style.visibility = 'hidden'; it.el.dataset.dc = it.why; continue; }
    it.el.style.visibility = ''; delete it.el.dataset.dc;
    if (it.dy) it.el.style.transform += ` translate(0px,${it.dy}px)`;
  }
  DECLUTTER.last = res;
}

// ---------------- load models ----------------
const loader = new GLTFLoader();
loader.setRequestHeader({ 'Cache-Control': 'no-cache' });
const progress = {};
function setProgress(k, loaded, total) {
  progress[k] = [loaded, total || loaded];
  const L = Object.values(progress).reduce((a, b) => a + b[0], 0), T = Object.values(progress).reduce((a, b) => a + b[1], 0);
  const p = T ? Math.min(100, (L / T) * 100) : 0; $('bar').firstElementChild.style.width = p.toFixed(0) + '%';
  $('loadtxt').textContent = `${p.toFixed(0)}%  ·  ${(L / 1048576).toFixed(1)} / ${(T / 1048576).toFixed(1)} MB`;
}
function loadGLB(url, key, tries = 3) {
  return new Promise((res, rej) => loader.load(url + (tries < 3 ? (url.includes('?') ? '&' : '?') + 'retry=' + (3 - tries) : ''), res, (e) => setProgress(key, e.loaded, e.total || 68.6e6), rej))
    .catch(async (e) => {
      if (tries <= 1) throw e;
      console.info('[viewer] retrying', url, '-', e?.message || e);
      await new Promise((r) => setTimeout(r, 1500 * (4 - tries)));
      return loadGLB(url, key, tries - 1);
    });
}
const dirCache = {};
async function fileExists(path) {
  const i = path.lastIndexOf('/'); const dir = path.slice(0, i + 1), name = path.slice(i + 1);
  if (!(dir in dirCache)) dirCache[dir] = fetch(dir || './', { cache: 'no-store' }).then((r) => (r.ok ? r.text() : null)).then((t) => {
    if (!t || !/<a href=/i.test(t)) return null; const s = new Set(); for (const m of t.matchAll(/href="([^"?#]+)"/g)) s.add(decodeURIComponent(m[1])); return s;
  }).catch(() => null);
  const set = await dirCache[dir];
  if (set) return set.has(name);
  try { return (await fetch(path, { method: 'HEAD', cache: 'no-store' })).ok; } catch { return false; }
}
const cadRoot = new THREE.Group(), ctxRoot = new THREE.Group(), groundRoot = new THREE.Group();
cadRoot.name = 'CAD'; ctxRoot.name = 'CONTEXT'; groundRoot.name = 'GROUND';
scene.add(cadRoot, ctxRoot, groundRoot);
const groupBoxes = {}; let features = null, cadMeta = null, canopyMeta = null, triCount = 0;
const loaded = { files: [], skipped: [], replaced: [] };
const extMeshes = [], canopyTopMeshes = [], canopyCladMeshes = [];
const GROUPS = ['VMU01', 'VMU02', 'VMU03', 'VMU04', 'VMU05', 'TRELLIS'];
function groupRootOf(gltfScene, name) {
  const named = gltfScene.getObjectByName(name);
  if (named && named !== gltfScene) return named;
  const g = new THREE.Group(); g.name = name; g.userData = { ...gltfScene.userData, group: name };
  for (const c of [...gltfScene.children]) g.add(c);
  return g;
}
function isExtensionNode(o) { let p = o; while (p) { const u = p.userData || {}; if (u.highlight === 'extension' || u.extension === true || u.is_extension === true) return true; if (/^VMU01[ _]canopy[ _]extension$/.test(p.name)) return true; p = p.parent; } return false; }

async function main() {
  const MD = PARAMS.MODEL_DIR;
  try { MATDB = await (await fetch('model/materials.json', { cache: 'no-store' })).json(); } catch (e) { console.warn('model/materials.json missing - keeping GLB materials', e); MATDB = {}; }
  const hdrP = setHDRI(PARAMS.HDRI, true);
  if (Q.get('exp')) light.exposure = +Q.get('exp');
  if (Q.get('sunk')) light.sunK = +Q.get('sunk');
  syncLightUI(); updateSun();
  features = await (await fetch('model/site_features.json', { cache: 'no-store' })).json();
  let vegNotes = null;
  if (await fileExists('model/vegetation_notes.json')) { try { vegNotes = await (await fetch('model/vegetation_notes.json', { cache: 'no-store' })).json(); loaded.files.push('vegetation_notes.json'); } catch (e) { console.warn(e); } }
  const opt = {};
  for (const f of ['vmu01_canopy', 'vmu02', 'vmu04', 'vmu05', 'site_ground', 'site_context']) opt[f] = await fileExists(MD + f + '.glb') ? MD + f + '.glb' : (MD !== 'model/' && await fileExists('model/' + f + '.glb') ? 'model/' + f + '.glb' : null);
  for (const [k, v] of Object.entries(opt)) if (!v) loaded.skipped.push(k + '.glb');
  const jobs = { cad: loadGLB('model/vmu_cad.glb', 'cad') };
  for (const [k, v] of Object.entries(opt)) if (v) jobs[k] = loadGLB(v, k).catch((e) => { console.warn('optional model failed', v, e); return null; });
  const res = {}; for (const [k, p] of Object.entries(jobs)) res[k] = await p;
  const cad = res.cad; cadMeta = cad.scene.userData || {}; loaded.files.push('vmu_cad.glb');
  for (const [key, grp] of [['vmu02', 'VMU02'], ['vmu04', 'VMU04'], ['vmu05', 'VMU05']]) {
    const g = res[key]; if (!g) continue;
    if (!opt[key].startsWith('model/')) loaded.fixture = (loaded.fixture || []).concat(key);
    const root = groupRootOf(g.scene, grp); const old = cad.scene.getObjectByName(grp);
    if (old) { old.removeFromParent(); loaded.replaced.push(grp); }
    root.name = grp; root.userData.group = root.userData.group || grp; root.userData.file = key + '.glb'; cad.scene.add(root); loaded.files.push(key + '.glb');
  }
  if (res.vmu01_canopy) {
    const g = res.vmu01_canopy; canopyMeta = g.scene.userData || {};
    const holder = new THREE.Group(); holder.name = 'VMU01_CANOPY'; holder.userData = { group: 'VMU01', layer_en: 'Canopy (existing + extension)', file: 'vmu01_canopy.glb', ...canopyMeta };
    for (const c of [...g.scene.children]) holder.add(c);
    holder.traverse((o) => { if (o !== holder && (GROUPS.includes(o.name) || o.name === 'VMU01_CANOPY')) o.name = o.name + (o.name === 'VMU01_CANOPY' ? '_ROOT' : '_CANOPY_ROOT'); });
    const oldExt = cad.scene.getObjectByName('VMU01 canopy extension'); if (oldExt) { oldExt.removeFromParent(); loaded.replaced.push('old canopy extension'); }
    let v01 = cad.scene.getObjectByName('VMU01'); if (!v01) { v01 = new THREE.Group(); v01.name = 'VMU01'; cad.scene.add(v01); }
    v01.add(holder); loaded.files.push('vmu01_canopy.glb');
  }
  try {
    const ov = await (await fetch('model/overrides.json', { cache: 'no-store' })).json();
    for (const o of ov) {
      const g = await loadGLB(o.file, 'ov_' + o.group); const old = cad.scene.getObjectByName(o.group);
      const root = g.scene.getObjectByName(o.group) || g.scene;
      if (old) old.removeFromParent(); root.name = o.group; cad.scene.add(root); loaded.files.push(o.file);
    }
  } catch (e) {  }
  cad.scene.updateMatrixWorld(true);
  cad.scene.traverse((o) => {
    if (!o.isMesh) return;
    upgradeMesh(o, 'cad');
    const ex = nodeExtras(o);
    const inCanopy = (() => { let p = o; while (p) { if (p.name === 'VMU01_CANOPY') return true; p = p.parent; } return false; })();
    if (isExtensionNode(o)) extMeshes.push(o);
    const cn = o.material.userData.canon;
    const nm = ex.layer_en || o.name;
    const isTop = ex.param === 'CANOPY_TOP_MATERIAL' || ex.role === 'top' || (!ex.role && /^AL_/.test(cn || o.material.name || '') && /top/i.test(nm) && !/soffit|fascia|edge|column|plate|plinth|gusset|joint|sealant|band/i.test(nm));
    const isClad = !isTop && (ex.param === 'CLAD_FINISH' || /^(band|fascia|chamfer|soffit)$/.test(ex.role || '') || (!ex.role && cn === 'AL_RAL7038'));
    if (inCanopy && isTop) { o.userData.glbMaterial = o.material; canopyTopMeshes.push(o); }
    else if (inCanopy && isClad) { o.userData.glbMaterial = o.material; canopyCladMeshes.push(o); }
    else if (!res.vmu01_canopy && /Top panels/.test(o.parent?.name || o.name) && isExtensionNode(o)) { o.userData.glbMaterial = o.material; canopyTopMeshes.push(o); }
  });
  cadRoot.add(cad.scene);
  let groundMinY = null;
  if (res.site_ground) {
    res.site_ground.scene.updateMatrixWorld(true);
    res.site_ground.scene.traverse((o) => {
      if (!o.isMesh) return;
      upgradeMesh(o, 'flat');
      const bb = new THREE.Box3().setFromObject(o); const cn = o.material.userData.canon || '';
      o.castShadow = bb.max.y - bb.min.y > 0.05 && !/CONCRETE_YARD|ASPHALT|GRASS|LINE|MARKING/.test(cn) && !o.material.transparent;
    });
    groundRoot.add(res.site_ground.scene); loaded.files.push('site_ground.glb');
    groundMinY = new THREE.Box3().setFromObject(res.site_ground.scene).min.y;
  }
  if (res.site_context) {
    const ctx = res.site_context;
    if (res.site_ground) { const yard = ctx.scene.getObjectByName('Yard'); if (yard) { yard.removeFromParent(); loaded.replaced.push('context Yard slab (site_ground.glb)'); } }
    ctx.scene.updateMatrixWorld(true);
    ctx.scene.traverse((o) => { if (o.isMesh) { upgradeMesh(o, /Yard|Surroundings/.test(o.name) ? 'flat' : 'ctx'); if (/Yard|Surroundings/.test(o.name)) o.castShadow = false; } });
    ctxRoot.add(ctx.scene); loaded.files.push(opt.site_context.replace(/^.*\//, ''));
  }
  ensureYardSlab();
  if (!YARD_CAL.off) {
    const damp = []; groundRoot.traverse((o) => { if (o.isMesh && o.material?.userData?.canon === 'CTX_CONCRETE_YARD_DAMP') damp.push(o); });
    try { buildYardMap(damp, features.cars); damp.forEach((o) => { o.visible = false; o.userData.viewerNote = 'baked into the yard detail map (soft edges)'; }); loaded.yardMap = yardMapStats; }
    catch (e) { console.warn('yard detail map', e); }
    if (YARD_VIS.on) { try { cad.scene.updateMatrixWorld(true); bakeYardSkyVis([cadRoot, ctxRoot]); loaded.yardSkyVis = yardVisStats; } catch (e) { console.warn('yard sky visibility bake', e); } }
  }
  if (res.site_ground && $('groundNote')) $('groundNote').textContent = '地坪（湿斑）、排水沟、龙门吊轨道与红色安全线、主路路面（通用示意断面，假定低于场地约 0.5 m）= site_ground.glb。';
  findPlatformDeck(); placePlatformPeople();
  buildBackdropGround(groundMinY);
  for (const g of GROUPS) { const o = cad.scene.getObjectByName(g); groupBoxes[g] = o ? new THREE.Box3().setFromObject(o) : new THREE.Box3(); }
  const eb = new THREE.Box3(); extMeshes.forEach((m) => eb.expandByObject(m)); groupBoxes.VMU01_EXT = eb;
  if (eb.isEmpty() && !groupBoxes.VMU01.isEmpty()) groupBoxes.VMU01_EXT = groupBoxes.VMU01.clone();
  const LABEL_PRIO = { VMU01: 0, VMU02: 1, VMU03: 2, VMU04: 3, VMU05: 4, VMU01_EXT: 5, TRELLIS: 6 };
  for (const [g, L] of Object.entries(features.labels || {})) {
    const b = groupBoxes[g]; if (!b || b.isEmpty()) continue; const c = b.getCenter(new THREE.Vector3());
    if (g === 'VMU01_EXT') addLabel(L.zh, new THREE.Vector3(c.x, b.max.y + 1.2, c.z), 'ext', LABEL_PRIO.VMU01_EXT);
    else {
      const pos = new THREE.Vector3(c.x, b.max.y + 1.0, c.z);
      if (g === 'VMU03') { const s = b.getSize(new THREE.Vector3()); pos.addScaledVector(new THREE.Vector3(-features.axis_y[0], 0, -features.axis_y[1]), Math.max(s.x, s.z) * 0.38); }
      if (g === 'VMU01') pos.y += 1.5;
      addLabel(L.zh, pos, '', LABEL_PRIO[g] ?? 8);
    }
  }
  (features.ctx_labels || []).forEach((L, i) => addLabel(L.zh, new THREE.Vector3(...L.p), 'ctx', 10 + i));
  snapFeaturesToGround();
  buildVegetation(features, vegNotes);
  applyCanopyFinish();
  writeExtNote(); writeMaterialTexts();
  buildViews(); setupComposer();
  await hdrP;
  await Promise.all(texPending);
  if (PARAMS.EXT_OUTLINE) setOutline(true);
  $('loading').style.display = 'none';
  const hash = location.hash.slice(1); goView(VIEWS[hash] ? hash : 'overview', 0);
  shadowDirty = true; markDirty(2500);
  renderer.setAnimationLoop(tick);
  updatePtEstimate();
  window.__loadReport = { ...loaded, views: Object.fromEntries(Object.entries(VIEWS).map(([k, v]) => [k, { pos: v.pos.toArray().map((x) => +x.toFixed(2)), target: v.target.toArray().map((x) => +x.toFixed(2)), ...(v.block !== undefined ? { block: v.block, swing: v.swing, ...(v.hiddenShare !== undefined ? { hiddenShare: v.hiddenShare } : {}) } : {}), ...(v.info ? { info: v.info } : {}), ...(v.derived !== undefined ? { derived: v.derived } : {}) }])), materials: matStats, veg: vegStats, extMeshes: extMeshes.length, canopyTop: canopyTopMeshes.length, canopyClad: canopyCladMeshes.length, canopyScheme: PARAMS.CANOPY_FINISH_SCHEME, canopyFinish: { ...canopyFinishState }, hdgCal: { ...HDG_CAL }, triangles: Math.round(triCount), hdri: light.hdri, yardCal: LIB.CTX_CONCRETE_YARD?.userData.yardCal || null };
  console.info('[viewer] loaded', JSON.stringify(window.__loadReport));
  readyResolve(window.__loadReport);
}
let readyResolve; window.__ready = new Promise((r) => { readyResolve = r; });

// plain fallback slab while model/site_ground.glb is missing
function ensureYardSlab() {
  let has = false;
  for (const root of [groundRoot, ctxRoot]) root.traverse((o) => { if (o.isMesh && /CONCRETE_YARD$/.test(o.material?.userData?.canon || '')) has = true; });
  if (has) return false;
  const poly = fallbackYardPolygon();
  const g = new THREE.ShapeGeometry(new THREE.Shape(poly.map(([x, z]) => new THREE.Vector2(x, -z)))); g.rotateX(-Math.PI / 2);
  const m = new THREE.Mesh(g, libMaterial('CTX_CONCRETE_YARD') || new THREE.MeshStandardMaterial({ color: 0xc4b8a3, roughness: 0.9 }));
  m.name = 'Yard|Fallback slab'; m.receiveShadow = true;
  m.userData = { context: 'Yard', part: '临时地坪（未找到 model/site_ground.glb）', finish: 'CTX_CONCRETE_YARD' };
  groundRoot.add(m); loaded.fallbackSlab = poly.length; return true;
}
// temporary viewing platform: deck strip -> long axis, top level, plan hull (platform view + people on the deck)
let platformDeck = null;
function findPlatformDeck() {
  let deck = null; ctxRoot.traverse((o) => { if (!deck && o.isMesh && /viewing_?platform/i.test(o.name) && /deck/i.test(o.name)) deck = o; });
  if (!deck) return null;
  deck.updateWorldMatrix(true, false);
  const pos = deck.geometry.attributes.position; const v = new THREE.Vector3(); const pts = []; let top = -Infinity;
  for (let i = 0; i < pos.count; i++) { v.fromBufferAttribute(pos, i).applyMatrix4(deck.matrixWorld); pts.push([v.x, v.z]); top = Math.max(top, v.y); }
  const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length, cz = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  let sxx = 0, szz = 0, sxz = 0; for (const [x, z] of pts) { sxx += (x - cx) ** 2; szz += (z - cz) ** 2; sxz += (x - cx) * (z - cz); }
  const ang = 0.5 * Math.atan2(2 * sxz, sxx - szz); const ax = new THREE.Vector2(Math.cos(ang), Math.sin(ang)), nx = new THREE.Vector2(-ax.y, ax.x);
  let t0 = Infinity, t1 = -Infinity, w0 = Infinity, w1 = -Infinity;
  for (const [x, z] of pts) { const t = (x - cx) * ax.x + (z - cz) * ax.y, w = (x - cx) * nx.x + (z - cz) * nx.y; t0 = Math.min(t0, t); t1 = Math.max(t1, t); w0 = Math.min(w0, w); w1 = Math.max(w1, w); }
  let grp = deck.parent; while (grp && grp.parent && grp.parent !== ctxRoot && /viewing_?platform/i.test(grp.parent.name)) grp = grp.parent;
  platformDeck = { mesh: deck, group: grp || deck.parent, top, c: new THREE.Vector2(cx, cz), ax, nx, t0, t1, w: w1 - w0, wc: (w0 + w1) / 2,
    at: (f, off = 0) => { const t = THREE.MathUtils.lerp(t0, t1, f); return new THREE.Vector3(cx + ax.x * t + nx.x * ((w0 + w1) / 2 + off), top, cz + ax.y * t + nx.y * ((w0 + w1) / 2 + off)); },
    contains: (x, z) => { const t = (x - cx) * ax.x + (z - cz) * ax.y, w = (x - cx) * nx.x + (z - cz) * nx.y; return t >= t0 && t <= t1 && w >= w0 && w <= w1; } };
  return platformDeck;
}
function placePlatformPeople() {
  const D = platformDeck; if (!D || !Array.isArray(features.people)) return;
  const up = features.people.filter((p) => (+p.p[1] || 0) > 1.0 && !D.contains(p.p[0], p.p[2]));
  if (!up.length) return;
  const v01 = cadRoot.getObjectByName('VMU01'); const tc = v01 ? new THREE.Box3().setFromObject(v01).getCenter(new THREE.Vector3()) : new THREE.Vector3();
  up.forEach((p, i) => {
    const f = up.length === 1 ? 0.5 : 0.35 + 0.3 * i / (up.length - 1);
    const q = D.at(f, (i % 2 ? 0.35 : -0.35) * Math.min(1, D.w / 2.6));
    p.moved_from = p.p.slice(); p.p = [+q.x.toFixed(3), +D.top.toFixed(3), +q.z.toFixed(3)];
    p.rot = Math.atan2(tc.x - q.x, tc.z - q.z);
  });
  loaded.platformPeopleMoved = up.length;
}
function fallbackYardPolygon() {
  const OLD = [[-194.79, -12.79], [6.04, 61.65], [109.59, -155.71], [-111.45, -237.64]];
  const lb = features?.lot_boundary; if (!Array.isArray(lb) || lb.length < 3) return OLD;
  const P = lb.map((p) => [+p[0], +p[p.length === 3 ? 2 : 1]]);
  const a = P[0], da = [OLD[0][0] - OLD[3][0], OLD[0][1] - OLD[3][1]], b = OLD[3], db = [OLD[2][0] - OLD[3][0], OLD[2][1] - OLD[3][1]];
  const den = da[0] * db[1] - da[1] * db[0]; if (Math.abs(den) < 1e-9) return OLD;
  const t = ((b[0] - a[0]) * db[1] - (b[1] - a[1]) * db[0]) / den;
  return [...P, [a[0] + t * da[0], a[1] + t * da[1]]];
}
// ---------------- VMU-01 canopy note (numbers from the canopy GLB scene extras only) ----------------
function writeExtNote() {
  const M = canopyMeta || {}; const E = M.extension || M.canopy || M; const C0 = M.canopy || {};
  const ext = cadMeta?.extension || {};
  const pick = (...ks) => { for (const k of ks) { if (E[k] !== undefined) return E[k]; if (M[k] !== undefined) return M[k]; } return undefined; };
  const num = (v) => (typeof v === 'number' && Number.isFinite(v)) || (typeof v === 'string' && /^-?\d+(\.\d+)?$/.test(v)) ? v : undefined;
  const area = num(pick('extension_area_m2') ?? ext.extension_area_m2), exist = num(pick('existing_canopy_area_m2', 'existing_area_m2') ?? ext.existing_canopy_area_m2);
  const cols = num(pick('new_columns', 'columns_new') ?? ext.new_columns), total = num(M.columns_total);
  const ocu = num(pick('oculus_diameter_m') ?? ext.oculus_diameter_m), top = num(pick('top_level_m', 'top_at_tower_m') ?? ext.top_level_m);
  const slope = pick('SLOPE', 'slope', 'fall');
  const parts = [];
  if (area !== undefined) parts.push(`新增面积 <b>${area} m²</b>` + (exist !== undefined ? `（原雨棚 ${exist} m²）` : ''));
  const colFin = String(M.finish?.columns || C0.params?.COLUMN_FINISH || 'STEEL_HDG');
  const finTxt = colFin === 'AL_T02' ? '深色涂装（按 T02 色近似）' : colFin === 'STEEL_HDG' ? '热镀锌' : (/^[A-Z0-9_]{2,24}$/.test(colFin) ? colFin : '');
  if (cols !== undefined || total !== undefined) parts.push(`CHS150 柱 ${total ?? cols} 根${finTxt ? '（饰面：' + finTxt + '）' : ''}`);
  if (ocu !== undefined) parts.push(`圆孔 Ø${ocu} m`);
  if (top !== undefined) parts.push(`顶 +${top} m`);
  const C = M.canopy || {}; const lv = C.measurements?.levels || M.measurements?.levels || {};
  const slopeTxt = typeof slope === 'number' ? (slope < 0.2 ? '1:' + Math.round(1 / slope) : slope + '°') : (typeof slope === 'string' && /^[\d.:°() a-z]{1,24}$/i.test(slope) ? slope : null);
  const brg = num(lv.fall_bearing_deg), fall = num(lv.total_fall_m);
  const compass = (d) => ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'][Math.round(((d % 360) + 360) % 360 / 22.5) % 16];
  const fallTxt = brg !== undefined ? `，单坡向 ${compass(+brg)}（方位 ${Math.round(+brg)}°）` + (fall !== undefined ? `，总落差 ${(+fall * 1000).toFixed(0)} mm` : '') : '';
  if (slopeTxt) parts.push(`坡度 ${slopeTxt}${fallTxt}`);
  parts.push(canopyFinishText());
  $('extNote').innerHTML = parts.join(' · ') + (canopyMeta ? '' : '<br><span style="opacity:.8">（未找到 model/vmu01_canopy.glb：雨棚暂不显示）</span>');
  if ($('q4Note')) {   // VMU-04 precast colour = materials.json PRECAST_FORMLINER unless ?precast= overrides it
    const pe = MATDB.PRECAST_FORMLINER || {}; const hx = (PARAMS.PRECAST_HEX || pe.hex || '').toUpperCase();
    $('q4Note').textContent = hx ? `VMU-04 预制混凝土颜色 ${hx}${PARAMS.PRECAST_HEX ? '（网址参数 ?precast= 指定）' : '（示意值，可用 ?precast=RRGGBB 替换）'}。` : '';
  }
}
// ---------------- canopy finish: default = the GLB's own materials; RAL 7038 = alternative (never red) ----------------
const MOUSE_GREY = 'AL_MOUSEGREY';
// every hex shown in the page comes from model/materials.json (MATDB), never from a literal here
function matHex(cn) { const h = MATDB[canonName(cn) || cn]?.hex; return h ? String(h).toUpperCase() : ''; }
const CANOPY_SCHEMES = {
  default: { top: MOUSE_GREY, clad: 'AL_T02', btn: 'schemeDefault', zh: '默认饰面',
    get text() { return `顶板 25 mm 蜂窝铝板 Mouse Grey（≈RAL 7005${matHex(MOUSE_GREY) ? ' ' + matHex(MOUSE_GREY) : ''}）+ 3 mm 边带 / 封边 / 斜边 / 底板 T02${matHex('AL_T02') ? ' ' + matHex('AL_T02') : ''}`; } },
  ral7038: { top: 'AL_RAL7038', clad: 'AL_RAL7038', btn: 'schemeRAL', zh: 'RAL 7038 备选',
    get text() { return `顶板 + 3 mm 边带 / 封边 / 斜边 / 底板均 RAL 7038${matHex('AL_RAL7038') ? ' ' + matHex('AL_RAL7038') : ''}（备选，仅作对比）`; } },
};
function mouseGreyMaterial() {   // materials.json entry; without it the canopy top keeps the finish embedded in vmu01_canopy.glb
  return libMaterial(MOUSE_GREY) || LIB[MOUSE_GREY] || null;
}
function canopyWant() {   // canonical names wanted for the top field and the 3 mm parts in the active scheme
  const S = CANOPY_SCHEMES[PARAMS.CANOPY_FINISH_SCHEME] || CANOPY_SCHEMES.default;
  return { top: PARAMS.CANOPY_TOP_OVERRIDE || S.top, clad: S.clad };
}
const canopyFinishState = { top: null, clad: null, glbTop: 0, glbClad: 0, repainted: 0 };
function applyCanopyFinish() {
  const want = canopyWant(); const st = { top: want.top, clad: want.clad, glbTop: 0, glbClad: 0, repainted: 0 };
  const matFor = (cn) => (cn === MOUSE_GREY ? mouseGreyMaterial() : libMaterial(cn));
  const paint = (list, cn, key) => {
    const alt = matFor(cn);
    for (const o of list) {
      const g = o.userData.glbMaterial || o.material;
      if (g?.userData?.canon === cn) { o.material = g; st[key]++; }          // the GLB already carries this finish -> show it as delivered
      else if (alt) { o.material = alt; st.repainted++; }                   // older GLB / alternative scheme -> library material
    }
  };
  paint(canopyTopMeshes, want.top, 'glbTop'); paint(canopyCladMeshes, want.clad, 'glbClad');
  Object.assign(canopyFinishState, st);
  for (const [k, S] of Object.entries(CANOPY_SCHEMES)) $(S.btn)?.classList.toggle('on', PARAMS.CANOPY_FINISH_SCHEME === k);
  const short = { [MOUSE_GREY]: 'Mouse Grey', AL_T02: 'T02', AL_RAL7038: 'RAL 7038' };
  const lbl = want.top === want.clad ? `${short[want.top] || want.top}${PARAMS.CANOPY_FINISH_SCHEME === 'ral7038' ? ' 备选' : ''}` : `顶 ${short[want.top] || want.top}，边 / 底 ${short[want.clad] || want.clad}`;
  labelGroup.children.forEach((o) => { const el = o.element; if (el?.classList.contains('ext')) el.textContent = `VMU-01 雨棚延伸（新增；${lbl}）`; });
  shadowDirty = true; markDirty();
  writeExtNote();
}
function writeMaterialTexts() {   // page texts with the hexes of model/materials.json
  const h = (cn) => matHex(cn);
  document.querySelectorAll('[data-mhex]').forEach((el) => { el.textContent = h(el.dataset.mhex) || '（未载入）'; });
  const mb = $('matBasis'); if (mb) mb.textContent = Object.values(MATDB).some((e) => e?.colour_basis === 'SCE') ? '（hex = SCE 等效反照率）' : '';
  const so = $('schemeDefault'); if (so) so.title = `默认：25 mm 蜂窝顶板 AL_MOUSEGREY（Mouse Grey，≈RAL 7005 ${h(MOUSE_GREY)}）；3 mm 边带 / 封边 / 斜边 / 底板 AL_T02 ${h('AL_T02')}`;
  const sr = $('schemeRAL'); if (sr) sr.title = `备选：顶板与 3 mm 件均 AL_RAL7038 ${h('AL_RAL7038')}（仅作对比）`;
  const cp = $('copingNote');
  if (cp) cp.textContent = MATDB.AL_RAL9016 ? `RAL 9016 交通白 ${h('AL_RAL9016')}（VMU-01 塔顶压顶）` : `RAL 9016 白（VMU-01 塔顶压顶，以 WHITE ${h('WHITE')} 代用）`;
}
function setCanopyTop(name) {   // API / URL-level top override; null = scheme top
  PARAMS.CANOPY_TOP_OVERRIDE = /^(AL_T02|AL_RAL7038|AL_MOUSEGREY)$/.test(name || '') ? name : null; applyCanopyFinish();
}
function setCanopyScheme(s) { PARAMS.CANOPY_FINISH_SCHEME = /^ral7038$/i.test(s || '') ? 'ral7038' : 'default'; PARAMS.CANOPY_TOP_OVERRIDE = null; applyCanopyFinish(); }
function canopyFinishText() {
  const S = CANOPY_SCHEMES[PARAMS.CANOPY_FINISH_SCHEME] || CANOPY_SCHEMES.default; const st = canopyFinishState;
  const src = st.glbTop + st.glbClad > 0 && !st.repainted ? '，即 vmu01_canopy.glb 自带材质' : (st.repainted ? `，查看器替换 ${st.repainted} 个构件材质` : '');
  return `饰面（${S.zh}${src}）：${S.text}` + (PARAMS.CANOPY_TOP_OVERRIDE ? `；顶板按网址参数改为 ${PARAMS.CANOPY_TOP_OVERRIDE}` : '') + '。';
}

// ---------------- camera views ----------------
const VIEWS = {};
const toRoad = new THREE.Vector3(), alongRoad = new THREE.Vector3();
function buildViews() {
  toRoad.set(-features.axis_y[0], 0, -features.axis_y[1]).normalize();
  alongRoad.set(features.axis_x[0], 0, features.axis_x[1]).normalize();
  const all = new THREE.Box3(); for (const g of GROUPS) if (!groupBoxes[g].isEmpty()) all.union(groupBoxes[g]);
  const c = all.isEmpty() ? new THREE.Vector3() : all.getCenter(new THREE.Vector3());
  const mk = (target, dirRoad, dirAlong, height, dist) => {
    const d = new THREE.Vector3().addScaledVector(toRoad, dirRoad).addScaledVector(alongRoad, dirAlong).normalize();
    return { target: target.clone(), pos: target.clone().addScaledVector(d, dist).add(new THREE.Vector3(0, height, 0)) };
  };
  VIEWS.overview = { name: '总览（自主路斜视）', ...mk(new THREE.Vector3(c.x, 5, c.z), 1, -0.55, 42, 78) };
  VIEWS.reverse = { name: '反向（自厂房侧）', ...mk(new THREE.Vector3(c.x, 5, c.z), -1, 0.45, 38, 72) };
  VIEWS.top = { name: '俯视（北向上）', target: new THREE.Vector3(c.x, 0, c.z), pos: new THREE.Vector3(c.x, 120, c.z + 0.01) };
  const gv = (g, rd, al, h, k) => { const b = groupBoxes[g]; if (!b || b.isEmpty()) return null; const cc = b.getCenter(new THREE.Vector3()); const s = b.getSize(new THREE.Vector3()).length(); return mk(new THREE.Vector3(cc.x, Math.min(cc.y, 6), cc.z), rd, al, h * s, k * s); };
  const add = (k, name, v, g, samples = null) => { if (v) { VIEWS[k] = { name, ...v }; keepInsideYard(VIEWS[k], 4); unblockView(VIEWS[k], groupBoxes[g], samples); keepInsideYard(VIEWS[k], 4); } };
  add('VMU01', 'VMU-01 塔楼', gv('VMU01', 1, -0.8, 0.35, 1.25), 'VMU01');
  { const t0 = performance.now(); add('EXT', 'VMU-01 雨棚延伸', gv('VMU01_EXT', 0.6, -1, 0.9, 1.1), 'VMU01_EXT', surfaceSamples(extMeshes)); loaded.extViewMs = Math.round(performance.now() - t0); }
  VIEWS.EXT_UNDER = { name: '雨棚下人视', ...(extUnderView() || { target: new THREE.Vector3(1.66, 2.4, 6.88), pos: new THREE.Vector3(6.84, 1.6, 12.83).addScaledVector(toRoad, 7.5).addScaledVector(alongRoad, -1.5), derived: false }) };
  add('VMU02', 'VMU-02', gv('VMU02', 0.8, 0.9, 0.35, 1.3), 'VMU02');
  add('VMU03', 'VMU-03 弧形裙楼', gv('VMU03', 1, 0.25, 0.25, 0.85), 'VMU03');
  add('VMU04', 'VMU-04', gv('VMU04', -0.69, 0.73, 0.22, 1.45), 'VMU04');
  add('VMU05', 'VMU-05', gv('VMU05', 0.6, 1, 0.5, 2.2), 'VMU05');
  add('TRELLIS', 'Trellis', gv('TRELLIS', 0.7, 0.7, 0.8, 1.3), 'TRELLIS');
  const ppl = features.people || [];
  if (!groupBoxes.VMU01.isEmpty()) {
    const tgt = groupBoxes.VMU01.getCenter(new THREE.Vector3()).setY(4);
    const pv = platformView(tgt);
    if (pv) VIEWS.platform = { name: '观景平台人视', ...pv };
    else if (ppl.length >= 2) { const plat = new THREE.Vector3(...ppl[ppl.length - 2].p); VIEWS.platform = { name: '观景平台人视', target: tgt, pos: plat.clone().add(new THREE.Vector3(0, 1.62, 0)) }; }
  }
  VIEWS.street = { name: '主路路边人视', target: new THREE.Vector3(-4.9, 5.5, -1.1), pos: new THREE.Vector3(35.2, 1.6, 12.0).addScaledVector(toRoad, 8) };
  { const gy = groundYAt(VIEWS.street.pos.x, VIEWS.street.pos.z); if (gy !== null) { VIEWS.street.pos.y = gy + 1.6; VIEWS.street.info = { ground_y: +gy.toFixed(3), eye: 1.6 }; } }
  const box = $('views'); box.innerHTML = '';
  for (const [k, v] of Object.entries(VIEWS)) { const b = document.createElement('button'); b.textContent = v.name; b.onclick = () => { goView(k); history.replaceState(null, '', location.search + '#' + k); }; box.appendChild(b); }
}
function snapFeaturesToGround() {
  if (!groundRoot.children.length) return;
  const st = { trees: 0, people: 0, cars: 0, maxFix: 0 };
  const snap = (t, sink, kind) => {
    if (!t || !Array.isArray(t.p)) return; const y0 = +t.p[1] || 0; if (kind !== 'trees' && y0 > 0.5) return;
    const gy = groundYAt(+t.p[0], +t.p[2]); if (gy === null) return;
    const y = gy - sink; if (Math.abs(y - y0) < 0.005) return;
    st.maxFix = Math.max(st.maxFix, Math.abs(y - y0)); t.p = [t.p[0], +y.toFixed(3), t.p[2]]; st[kind]++;
  };
  for (const k of ['palms', 'trees', 'polyalthia', 'broadleaf']) for (const t of features[k] || []) snap(t, 0.05, 'trees');
  for (const t of features.people || []) snap(t, 0, 'people');
  for (const t of features.cars || []) snap(t, 0, 'cars');
  st.maxFix = +st.maxFix.toFixed(3); loaded.groundSnap = st;
}
function groundYAt(x, z) {
  const rc = new THREE.Raycaster(new THREE.Vector3(x, 60, z), new THREE.Vector3(0, -1, 0)); groundRoot.updateMatrixWorld(true);
  const h = rc.intersectObjects([groundRoot], true).find((q) => q.object.isMesh && q.object.visible);
  return h ? h.point.y : null;
}
// group views stay on the yard side of the lot line
function keepInsideYard(v, margin) {
  const lb = features.lot_boundary; if (!lb || lb.length < 3) return;
  const B = new THREE.Vector2(lb[1][0], lb[1][2]), C = new THREE.Vector2(lb[2][0], lb[2][2]), A = new THREE.Vector2(lb[0][0], lb[0][2]);
  const d = C.clone().sub(B).normalize(); const n = new THREE.Vector2(-d.y, d.x); if (n.dot(A.clone().sub(B)) < 0) n.negate();
  const sd = (p) => n.dot(new THREE.Vector2(p.x, p.z).sub(B));
  if (sd(v.pos) >= margin || sd(v.target) <= margin) return;
  const off = v.pos.clone().sub(v.target);
  for (const deg of [20, -20, 40, -40, 60, -60, 80, -80, 100, -100, 130, -130, 160, -160, 180]) {
    const pos = v.target.clone().add(off.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(deg)));
    if (sd(pos) >= margin) { v.pos.copy(pos); return; }
  }
  const t = Math.min(0.4, (margin - sd(v.pos)) / (sd(v.target) - sd(v.pos))); v.pos.lerp(v.target, t);
}
let thinPoles = null;
function getThinPoles() {
  if (thinPoles) return thinPoles; thinPoles = [];
  ctxRoot.updateMatrixWorld(true);
  ctxRoot.traverse((o) => {
    if (!o.isMesh || !/mast|pole|lamp post/i.test(o.name + ' ' + (o.parent?.name || '')) || /head|lens|plinth/i.test(o.name)) return;
    const pos = o.geometry.attributes.position; const v = new THREE.Vector3(); const cl = [];
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
      let c = cl.find((k) => Math.hypot(k.x - v.x, k.z - v.z) < 2.5);
      if (!c) { c = { x: v.x, z: v.z, y0: v.y, y1: v.y, n: 0, w: 1.0 }; cl.push(c); }
      c.y0 = Math.min(c.y0, v.y); c.y1 = Math.max(c.y1, v.y);
    }
    for (const c of cl) if (c.y1 - c.y0 > 4) thinPoles.push(c);
  });
  for (const t of features?.palms || []) thinPoles.push({ x: t.p[0], z: t.p[2], y0: t.p[1] || 0, y1: (t.p[1] || 0) + (+t.h || 10), w: 0.5 });
  return thinPoles;
}
// 5 x 5 probe rays over the group's silhouette (0 = clear, 1 = hidden) + a penalty for thin poles in front
function viewBlockScore(pos, target, box) {
  const rc = new THREE.Raycaster(); const c = box.getCenter(new THREE.Vector3());
  const fwd = target.clone().sub(pos).normalize(); const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize(); const up = new THREE.Vector3().crossVectors(right, fwd);
  let r0 = Infinity, r1 = -Infinity, u0 = Infinity, u1 = -Infinity; const q = new THREE.Vector3();
  for (let i = 0; i < 8; i++) {
    q.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).sub(c);
    const r = q.dot(right), u = q.dot(up); r0 = Math.min(r0, r); r1 = Math.max(r1, r); u0 = Math.min(u0, u); u1 = Math.max(u1, u);
  }
  let blocked = 0, n = 0;
  for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) {
    const pt = c.clone().addScaledVector(right, THREE.MathUtils.lerp(r0, r1, 0.1 + 0.8 * i / 4)).addScaledVector(up, THREE.MathUtils.lerp(u0, u1, 0.08 + 0.84 * j / 4));
    const d = pt.clone().sub(pos); const L = d.length(); rc.set(pos, d.normalize()); rc.far = Math.max(0.1, L - 0.3);
    const hits = rc.intersectObjects([ctxRoot, vegGroup], true).filter((h) => h.object.visible && h.object.isMesh);
    blocked += hits.some((h) => !(h.object.userData.veg && h.object.userData.noAO)) ? 1 : hits.length ? 0.5 : 0; n++;
  }
  let pole = 0; const dC = c.clone().sub(pos).dot(fwd); const halfDepth = Math.abs(box.max.clone().sub(box.min).dot(fwd)) * 0.5;
  for (const p of getThinPoles()) {
    const w = new THREE.Vector3(p.x, (p.y0 + p.y1) / 2, p.z).sub(pos); const depth = w.dot(fwd);
    if (depth < 0.5 || depth > dC - Math.min(halfDepth, dC * 0.3)) continue;
    const sx = w.dot(right) / depth * dC;
    const t0 = (p.y0 - pos.y) / depth * dC + pos.y, t1 = (p.y1 - pos.y) / depth * dC + pos.y;
    if (t1 < box.min.y || t0 > box.max.y) continue;
    const half = Math.max(0.5, (r1 - r0) / 2); const off = Math.abs(sx - (r0 + r1) / 2) / half;
    if (off < 1) pole += (p.w || 1) * 0.25 * (1 - off) * Math.min(1, 12 / depth);
    else if (off < 2.2) pole += (p.w || 1) * 0.03 * Math.min(1, 12 / depth);
  }
  return blocked / n + pole;
}
function surfaceSamples(meshes, re = /Top|band|Fascia|Chamfer|Soffit/i, max = 160) {
  const ms = meshes.filter((m) => m.isMesh && re.test(m.name)); if (!ms.length) return [];
  let tris = 0; for (const m of ms) tris += m.geometry.index ? m.geometry.index.count / 3 : m.geometry.attributes.position.count / 3;
  const step = Math.max(1, Math.floor(tris / max)); const pts = []; const A = new THREE.Vector3(), B = new THREE.Vector3(), C = new THREE.Vector3();
  for (const m of ms) {
    m.updateWorldMatrix(true, false); const pos = m.geometry.attributes.position, idx = m.geometry.index; const nt = idx ? idx.count / 3 : pos.count / 3;
    for (let t = 0; t < nt; t += step) {
      const g = (k) => (idx ? idx.getX(3 * t + k) : 3 * t + k);
      A.fromBufferAttribute(pos, g(0)); B.fromBufferAttribute(pos, g(1)); C.fromBufferAttribute(pos, g(2));
      pts.push(A.add(B).add(C).multiplyScalar(1 / 3).applyMatrix4(m.matrixWorld).clone());
    }
  }
  return pts;
}
function sampleOcclusion(pos, pts) {
  if (!pts || !pts.length) return 0;
  const rc = new THREE.Raycaster(); let hid = 0; const d = new THREE.Vector3();
  for (const p of pts) {
    d.copy(p).sub(pos); const L = d.length(); rc.set(pos, d.normalize()); rc.far = Math.max(0.1, L - 0.05);
    if (rc.intersectObjects([ctxRoot, vegGroup], true).some((h) => h.object.visible && h.object.isMesh)) hid++;
  }
  return hid / pts.length;
}
function unblockView(v, box, samples = null) {
  if (!box || box.isEmpty()) return;
  const base = v.pos.clone().sub(v.target); let best = null;
  for (const deg of [0, 15, -15, 30, -30, 45, -45, 60, -60, 75, -75, 90, -90, 120, -120]) {
    const pos = v.target.clone().add(base.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(deg)));
    let b = viewBlockScore(pos, v.target, box) + Math.abs(deg) / 900;
    if (best && b >= best.b) continue;
    const occ = samples ? sampleOcclusion(pos, samples) : 0; b += 2 * occ;
    if (!best || b < best.b) best = { b, pos, deg, occ };
  }
  if (best) { v.pos.copy(best.pos); v.block = +best.b.toFixed(3); v.swing = best.deg; if (samples) v.hiddenShare = +best.occ.toFixed(3); }
}
function platformView(tgt) {
  const D = platformDeck; if (!D) return null;
  const onDeck = (features.people || []).filter((p) => (+p.p[1] || 0) > 1.0).map((p) => new THREE.Vector2(p.p[0], p.p[2]));
  const g = D.group; const vis = g.visible; g.visible = false;
  let best = null;
  for (let f = 0.08; f <= 0.921; f += 0.04) for (const off of [0, -0.5, 0.5]) {
    const p = D.at(f, off * Math.min(1, D.w / 2.6)); if (onDeck.some((q) => q.distanceTo(new THREE.Vector2(p.x, p.z)) < 1.1)) continue;
    const pos = p.clone().setY(D.top + 1.62);
    const s = viewBlockScore(pos, tgt, groupBoxes.VMU01) + 0.002 * pos.distanceTo(tgt);
    if (!best || s < best.s) best = { s, pos, f };
  }
  g.visible = vis;
  if (!best) return null;
  return { pos: best.pos, target: tgt.clone(), derived: true, info: { deck_top: +D.top.toFixed(3), f: +best.f.toFixed(2), block: +best.s.toFixed(3) } };
}
function inCanopyNode(o) { let p = o; while (p) { if (p.name === 'VMU01_CANOPY') return true; p = p.parent; } return false; }
// eye-level view from under the canopy extension, derived from the canopy nodes
function extUnderView() {
  const eb = groupBoxes.VMU01_EXT; const v01 = cadRoot.getObjectByName('VMU01');
  if (!eb || eb.isEmpty() || !extMeshes.length || !v01) return null;
  cadRoot.updateMatrixWorld(true);
  const canopy = []; cadRoot.traverse((o) => { if (o.isMesh && inCanopyNode(o)) canopy.push(o); });
  const tb = new THREE.Box3(); v01.traverse((o) => { if (o.isMesh && !inCanopyNode(o)) tb.expandByObject(o); });
  if (tb.isEmpty()) return null;
  const tc = tb.getCenter(new THREE.Vector3());
  const posts = canopy.filter((o) => /column|baseplate|plinth/.test(nodeExtras(o).role || ''));
  const obstacles = [...posts, vegGroup, ctxRoot];
  const rc = new THREE.Raycaster(); const EYE = 1.6;
  const cb = new THREE.Box3(); canopy.forEach((o) => cb.expandByObject(o));
  const S = 0.1, X0 = cb.min.x, Z0 = cb.min.z, NX = Math.ceil((cb.max.x - X0) / S) + 1, NZ = Math.ceil((cb.max.z - Z0) / S) + 1;
  const cov = new Uint8Array(NX * NZ); const A = new THREE.Vector3(), B = new THREE.Vector3(), C = new THREE.Vector3();
  for (const o of canopy) {
    if (!/^(soffit|joint)$/.test(nodeExtras(o).role || '') || /top/i.test(nodeExtras(o).layer_en || '')) continue;
    const val = extMeshes.includes(o) ? 2 : 1; const pos = o.geometry.attributes.position; const idx = o.geometry.index;
    const nt = idx ? idx.count / 3 : pos.count / 3;
    for (let t = 0; t < nt; t++) {
      A.fromBufferAttribute(pos, idx ? idx.getX(3 * t) : 3 * t).applyMatrix4(o.matrixWorld);
      B.fromBufferAttribute(pos, idx ? idx.getX(3 * t + 1) : 3 * t + 1).applyMatrix4(o.matrixWorld);
      C.fromBufferAttribute(pos, idx ? idx.getX(3 * t + 2) : 3 * t + 2).applyMatrix4(o.matrixWorld);
      const d = (B.x - A.x) * (C.z - A.z) - (B.z - A.z) * (C.x - A.x); if (Math.abs(d) < 1e-9) continue;
      const i0 = Math.max(0, Math.floor((Math.min(A.x, B.x, C.x) - X0) / S)), i1 = Math.min(NX - 1, Math.ceil((Math.max(A.x, B.x, C.x) - X0) / S));
      const j0 = Math.max(0, Math.floor((Math.min(A.z, B.z, C.z) - Z0) / S)), j1 = Math.min(NZ - 1, Math.ceil((Math.max(A.z, B.z, C.z) - Z0) / S));
      for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) {
        const px = X0 + i * S, pz = Z0 + j * S;
        const u = ((px - A.x) * (C.z - A.z) - (pz - A.z) * (C.x - A.x)) / d, w = ((B.x - A.x) * (pz - A.z) - (B.z - A.z) * (px - A.x)) / d;
        if (u >= -1e-6 && w >= -1e-6 && u + w <= 1 + 1e-6) cov[i * NZ + j] = Math.max(cov[i * NZ + j], val);
      }
    }
  }
  const covAt = (x, z) => { const i = Math.round((x - X0) / S), j = Math.round((z - Z0) / S); return i < 0 || j < 0 || i >= NX || j >= NZ ? 0 : cov[i * NZ + j]; };
  let best = null;
  for (let x = eb.min.x + 0.2; x < eb.max.x; x += 0.4) for (let z = eb.min.z + 0.2; z < eb.max.z; z += 0.4) {
    const p = new THREE.Vector3(x, EYE, z);
    if (covAt(x, z) !== 2) continue;
    let margin = 0;
    for (const r of [1.0, 1.5, 2.0]) { let ok = true; for (let a = 0; a < 16 && ok; a++) ok = covAt(x + Math.cos(a * Math.PI / 8) * r, z + Math.sin(a * Math.PI / 8) * r) > 0; if (!ok) break; margin = r; }
    if (!margin) continue;
    let clear = true;
    for (let a = 0; a < 8 && clear; a++) { rc.set(p, new THREE.Vector3(Math.cos(a * Math.PI / 4), 0, Math.sin(a * Math.PI / 4))); rc.far = 0.9; clear = !rc.intersectObjects(obstacles, true).some((h) => h.object.visible); }
    if (!clear) continue;
    const dist = Math.hypot(tc.x - x, tc.z - z);
    const tgt = new THREE.Vector3(tc.x, EYE + Math.tan(THREE.MathUtils.degToRad(12)) * dist, tc.z);
    const dir = tgt.clone().sub(p); const L = dir.length(); rc.set(p, dir.normalize()); rc.far = L * 0.75;
    const blk = rc.intersectObjects(obstacles, true).filter((h) => h.object.visible && h.object.isMesh).length;
    const score = Math.min(dist, 16) + 1.5 * margin - 4 * Math.min(blk, 2);
    if (!best || score > best.score) best = { score, pos: p, target: tgt, margin, dist, blk };
  }
  if (!best) return null;
  return { pos: best.pos, target: best.target, derived: true, info: { margin: best.margin, dist: +best.dist.toFixed(2), blocked: best.blk } };
}
function nudgeOffTrunks(v) {
  const trunks = [...(features.palms || []), ...(features.trees || [])].map((t) => new THREE.Vector2(t.p[0], t.p[2]));
  const d = new THREE.Vector2(v.target.x - v.pos.x, v.target.z - v.pos.z).normalize(); const base = v.pos.clone();
  const score = (pos) => { const a = new THREE.Vector2(pos.x, pos.z); let sc = 0;
    for (const t of trunks) { const w = t.clone().sub(a); const along = w.dot(d); if (along < -0.5 || along > 20) continue; const lat = Math.abs(w.x * d.y - w.y * d.x); sc += Math.max(0, 1.2 + along * 0.3 - lat) / (1 + along * 0.2); }
    return sc; };
  let best = null;
  for (let k = 0; k <= 16; k++) for (const sgn of k ? [1, -1] : [1]) {
    const pos = base.clone().addScaledVector(alongRoad, sgn * k * 1.0); const sc = score(pos) + k * 0.01;
    if (!best || sc < best.sc) best = { sc, pos };
  }
  v.pos.copy(best.pos);
}
let tween = null;
function goView(k, ms = 1200) {
  const v = VIEWS[k]; if (!v) return;
  if (!ms) { camera.position.copy(v.pos); controls.target.copy(v.target); controls.update(); updateSun(); return; }
  tween = { t0: performance.now(), ms, p0: camera.position.clone(), t0v: controls.target.clone(), p1: v.pos.clone(), t1: v.target.clone() };
}

// ---------------- post-processing: Render -> GTAO -> Outline (extension, optional) -> Output (ACES + sRGB) -> SMAA ----------------
let composer = null, gtao = null, outline = null, smaa = null;
function setupComposer() {
  const rt = new THREE.WebGLRenderTarget(innerWidth, innerHeight, { type: THREE.HalfFloatType, samples: 4 });
  composer = new EffectComposer(renderer, rt);
  composer.setPixelRatio(renderer.getPixelRatio()); composer.setSize(innerWidth, innerHeight);
  composer.addPass(new RenderPass(scene, camera));
  gtao = new GTAOPass(scene, camera, innerWidth, innerHeight);
  gtao.updateGtaoMaterial({ radius: 0.6, distanceExponent: 1.5, thickness: 1.2, scale: 1.0, samples: 16 });
  gtao.updatePdMaterial?.({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 16 });
  gtao.blendIntensity = 0.9;
  gtao.overrideVisibility = function () { const cache = this._visibilityCache; this.scene.traverse((o) => { cache.set(o, o.visible); if (o.isPoints || o.isLine || o.userData.noAO || o.material?.userData?.glass) o.visible = false;
    if (o.userData.aoProxy) { o.userData.aoGeo = o.geometry; o.geometry = o.userData.aoProxy; } }); };
  gtao.restoreVisibility = function () { const cache = this._visibilityCache; this.scene.traverse((o) => { o.visible = cache.get(o); if (o.userData.aoGeo) { o.geometry = o.userData.aoGeo; o.userData.aoGeo = null; } }); cache.clear(); };
  outline = new OutlinePass(new THREE.Vector2(innerWidth, innerHeight), scene, camera, extMeshes);
  outline.visibleEdgeColor.set('#29d3ff'); outline.hiddenEdgeColor.set('#1d6f85');
  outline.edgeStrength = 6; outline.edgeThickness = 1.4; outline.edgeGlow = 0.0; outline.pulsePeriod = 0; outline.enabled = false;
  smaa = new SMAAPass(innerWidth * renderer.getPixelRatio(), innerHeight * renderer.getPixelRatio());
  composer.addPass(gtao); composer.addPass(outline); composer.addPass(new OutputPass()); composer.addPass(smaa);
  gtao.enabled = $('ao').checked; smaa.enabled = $('smaa').checked;
}
function setOutline(on) {
  if (outline) outline.enabled = on && extMeshes.length > 0;
  $('extOutline').classList.toggle('on', on);
}

// ---------------- interaction: pick + measure ----------------
const ray = new THREE.Raycaster(); const mouse = new THREE.Vector2(); let downAt = null; let measuring = false; const measPts = []; const measGroup = new THREE.Group(); scene.add(measGroup);
renderer.domElement.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', (e) => {
  if (ptActive()) return;
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4) return;
  const rc = renderer.domElement.getBoundingClientRect();
  mouse.set(((e.clientX - rc.left) / rc.width) * 2 - 1, -((e.clientY - rc.top) / rc.height) * 2 + 1); ray.setFromCamera(mouse, camera);
  const hits = ray.intersectObjects([cadRoot, ctxRoot, groundRoot, surrGroup, vegGroup], true).filter((h) => h.object.visible && isVisibleChain(h.object) && !(h.object.material?.transparent && measuring));
  if (!hits.length) return; const h = hits[0];
  if (measuring) return addMeasurePoint(h.point);
  showInfo(h);
});
function isVisibleChain(o) { let p = o; while (p) { if (!p.visible) return false; p = p.parent; } return true; }
const MAT_ZH = { AL_RAL7038: 'RAL 7038 玛瑙灰 PVDF 铝板', AL_T02: 'T02 深灰 PVDF', AL_T01: 'T01 深灰粉末', AL_METBLACK: '金属黑', AL_MILL: '铝本色（钝化）', STEEL_HDG: '热镀锌钢', SS_BRUSHED: '不锈钢乱纹拉丝', GL01_VISION: 'GL01 双银 Low-E 夹胶中空玻璃', GL02_SPANDREL: 'GL02 层间玻璃', GL03_VISION_B: 'GL03 夹胶中空玻璃', GL_DOOR: '夹胶门玻璃', SEALANT_BLACK: '黑色密封胶 / 胶条', GMS_RIBBED: '镀锌压型钢板', AL_RAL9016: 'RAL 9016 交通白 PVDF 铝板（VMU-01 塔顶压顶）', RC_PLAIN: '素混凝土', PLYWOOD: '夹板', CTX_CONCRETE_YARD: '场地混凝土地坪' };
// CIE L* of a materials.json entry (lab_sci, else from hex_sci / hex)
function matLstar(cn) {
  const e = MATDB[cn]; if (!e) return null; const l = e.lab_sci;
  if (Array.isArray(l) && Number.isFinite(+l[0])) return +l[0];
  if (l && typeof l === 'object' && Number.isFinite(+l.L)) return +l.L;
  if (typeof l === 'string' && /-?\d/.test(l)) return +l.match(/-?\d+(\.\d+)?/)[0];
  const h = e.hex_sci || e.hex; if (!h) return null; const Y = lumOf(new THREE.Color(h));
  return Y > 216 / 24389 ? 116 * Math.cbrt(Y) - 16 : Y * 24389 / 27;
}
function matZh(cn) {
  const L = (d) => { const v = matLstar(cn); return v === null ? '' : ' L* ' + v.toFixed(d); };
  switch (cn) {
    case 'AL_WOOD': return `木纹转印铝（地面格栅立柱与横档，浅灰木纹，亚光${L(0)}）`;
    case 'AL_MOUSEGREY': return `Mouse Grey 25 mm 蜂窝铝板（按 RAL 7005 名义值${L(1)}）`;
    case 'PRECAST_FORMLINER': return `预制混凝土（模纹，无额外饰面${L(1)}；颜色为示意值）`;
    case 'WHITE': return '白色（单元底吊顶 / 室内完成面占位）' + (matStats.upgraded.AL_RAL9016 ? '' : '；当前模型的 VMU-01 塔顶压顶以此色代用 RAL 9016');
    default: return MAT_ZH[cn] || '';
  }
}
// confidence strings of materials.json / node extras: only the level words are shown
const CONF_WORD = '(?:very low|low-medium|medium-low|medium-high|high|medium|low|none|open)';
const CONF_ALL = new RegExp('^' + CONF_WORD + '(?:\\s*/\\s*' + CONF_WORD + ')*$', 'i'), CONF_FIRST = new RegExp('^' + CONF_WORD, 'i');
function confLevel(v) {
  const s = String(v ?? '').trim(); if (CONF_ALL.test(s)) return s;
  const m = CONF_FIRST.exec(s); return m ? m[0] : '';
}
function showInfo(h) {
  const o = h.object; const ex = nodeExtras(o); let grp = null; let p = o;
  while (p) { if (GROUPS.includes(p.name)) { grp = p; break; } p = p.parent; }
  const rows = []; const tr = (a, b) => { if (b !== undefined && b !== null && b !== '') rows.push(`<tr><td>${a}</td><td>${b}</td></tr>`); };
  let title = (o.name || '').split('|')[0] || o.parent?.name || '构件';
  const cn = o.material?.userData?.canon; const me = cn ? (MATDB[cn] || o.material.userData.entry || null) : null;
  const finish = cn ? `<span class="sw" style="background:${me?.hex || '#888'}"></span>${cn}${matZh(cn) ? ' · ' + matZh(cn) : ''}${me?.hex ? ' · ' + me.hex : ''}` : (ex.finish || o.material?.name);
  if (isExtensionNode(o)) { title = 'VMU-01 雨棚延伸（新增）'; } else if (inCanopyNode(o)) { title = 'VMU-01 雨棚（既有部分）'; }
  const canopyPart = inCanopyNode(o);
  if (grp) {
    tr('VMU', grp.userData.group || grp.name);
    tr('说明', canopyPart ? 'VMU-01 雨棚（既有 + 延伸，vmu01_canopy.glb）' : grp.userData.description);
    if (grp.userData.size_m && !canopyPart) tr('外包尺寸', grp.userData.size_m.map((v) => (+v).toFixed(2)).join(' × ') + ' m');
  }
  if (ex.layer || ex.layer_en) tr('构件图层', `${ex.layer || ''}${ex.layer && ex.layer_en ? '<br>' : ''}${ex.layer_en || ''}`);
  if (ex.context) { title = typeof ex.context === 'string' ? ex.context : (ex.group || title); tr('部件', ex.part); }
  tr('饰面', finish + (o.material?.userData?.yardCal ? `<br>查看器校准：平均反照率 ${o.material.userData.yardCal.albedo}，渲染约 #B9B3A8；柔边湿斑 + 轮胎印 + 天空可见度` : '')
    + (o.material?.userData?.hdgCal ? `<br>查看器校准：新镀锌层镜面环境反射 ×${o.material.userData.hdgCal.env}（materials.json 值不变）` : ''));
  tr('饰面可信度', confLevel(me?.confidence));
  tr('几何可信度', confLevel(ex.confidence));
  if (isExtensionNode(o)) tr('范围', '新增延伸部分（描边开关只画外缘，不改饰面）');
  const tri = o.geometry?.index ? o.geometry.index.count / 3 : (o.geometry?.attributes?.position?.count || 0) / 3;
  tr('三角面', Math.round(ex.triangles || tri).toLocaleString());
  tr('点位 E/N/H', `${h.point.x.toFixed(3)} / ${(-h.point.z).toFixed(3)} / ${h.point.y.toFixed(3)} m`);
  $('info').innerHTML = `<h3>${title}</h3><table>${rows.join('')}</table>`; $('info').style.display = 'block';
  selBox.box.setFromObject(o); selBox.visible = true;
}
const selBox = new THREE.Box3Helper(new THREE.Box3(), 0xffd54a); selBox.visible = false; scene.add(selBox);
function addMeasurePoint(p) {
  const dot = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffd54a, depthTest: false })); dot.renderOrder = 9; dot.position.copy(p); dot.userData.noAO = true; measGroup.add(dot);
  measPts.push(p.clone());
  if (measPts.length % 2 === 0) {
    const a = measPts[measPts.length - 2], b = measPts[measPts.length - 1];
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), new THREE.LineBasicMaterial({ color: 0xffd54a, depthTest: false })); line.renderOrder = 9; measGroup.add(line);
    const d = a.distanceTo(b), dh = Math.hypot(a.x - b.x, a.z - b.z), dz = Math.abs(a.y - b.y);
    const lbl = document.createElement('div'); lbl.className = 'lbl meas'; lbl.textContent = `${d.toFixed(3)} m  (平 ${dh.toFixed(3)} / 高 ${dz.toFixed(3)})`;
    const o = new CSS2DObject(lbl); o.position.copy(a).lerp(b, 0.5); measGroup.add(o);
  }
}
$('measure').onclick = () => { measuring = !measuring; $('measure').classList.toggle('on', measuring); $('hint').textContent = measuring ? '测距：依次点击两个点；再次点击按钮退出（清除测量）' : '左键旋转 · 右键平移 · 滚轮缩放'; if (!measuring) { measGroup.clear(); measPts.length = 0; } };

// ---------------- UI wiring ----------------
$('extOutline').onclick = () => setOutline(!(outline && outline.enabled));
for (const [k, S] of Object.entries(CANOPY_SCHEMES)) if ($(S.btn)) $(S.btn).onclick = () => setCanopyScheme(k);
$('hdriOvercast').onclick = () => setHDRI('overcast'); $('hdriSunny').onclick = () => setHDRI('sunny');
$('exposure').oninput = (e) => { light.exposure = +e.target.value; syncLightUI(); };
$('sunk').oninput = (e) => { light.sunK = +e.target.value; syncLightUI(); updateSun(); };
$('date').oninput = updateSun; $('time').oninput = updateSun;
$('shadows').onchange = (e) => { sun.castShadow = e.target.checked; };
$('ao').onchange = (e) => { if (gtao) gtao.enabled = e.target.checked; };
$('smaa').onchange = (e) => { if (smaa) smaa.enabled = e.target.checked; };
$('showCtx').onchange = (e) => { ctxRoot.visible = e.target.checked; };
$('showSurr').onchange = (e) => { surrGroup.visible = e.target.checked; };
$('showVeg').onchange = (e) => { vegGroup.visible = e.target.checked; };
$('showLbl').onchange = (e) => { labelGroup.visible = e.target.checked; labelRenderer.domElement.style.display = e.target.checked ? '' : 'none'; };
$('shot').onclick = () => {
  if (gtao) gtao.enabled = $('ao').checked; if (sun.castShadow) renderer.shadowMap.needsUpdate = true;
  render(); const a = document.createElement('a'); a.download = `vmu_site_${Date.now()}.png`; a.href = renderer.domElement.toDataURL('image/png'); a.click();
};
function layout() {
  const W = innerWidth, H = innerHeight;
  renderer.setSize(W, H); Object.assign(renderer.domElement.style, { position: 'fixed', left: '0px', top: '0px' });
  labelRenderer.setSize(W, H);
  camera.aspect = W / H; camera.updateProjectionMatrix();
  if (composer) { composer.setPixelRatio(renderer.getPixelRatio()); composer.setSize(W, H); }
}
addEventListener('resize', () => { if (!ptActive()) layout(); });
function setRenderSize(W, H) {
  renderer.setPixelRatio(1); renderer.setSize(W, H, false);
  composer.setPixelRatio(1); composer.setSize(W, H);
  camera.aspect = W / H; camera.updateProjectionMatrix();
}
function restoreRenderSize(pr) { renderer.setPixelRatio(pr); composer.setPixelRatio(pr); layout(); }
// headless: window.__poseShot({ pos, target, fov?, roll? }, 'name.png', W, H, opts) renders an exact camera pose (no controls) and
// POSTs the PNG to serve.py /save. opts.date 'YYYY-MM-DD' + opts.t (minutes) set the sun; opts.ctx === false hides the context,
// surroundings and vegetation. Camera, visibility and date / time are restored afterwards.
window.__poseShot = async (pose, name, W = 1600, H = 1000, opts = null) => {
  shotLock = true;
  const saved = { pos: camera.position.clone(), up: camera.up.clone(), fov: camera.fov, pr: renderer.getPixelRatio(), date: $('date').value, t: $('time').value };
  const vis = [];
  try {
    if (opts && opts.ctx === false) { for (const o of [ctxRoot, surrGroup, vegGroup]) { vis.push(o.visible); o.visible = false; } }
    if (opts?.date) { $('date').value = opts.date; if (opts.t !== null && opts.t !== undefined) $('time').value = opts.t; }
    camera.fov = pose.fov || 45; camera.up.set(Math.sin(pose.roll || 0), Math.cos(pose.roll || 0), 0);
    camera.position.set(...pose.pos); camera.lookAt(...pose.target); camera.updateMatrixWorld();
    setRenderSize(W, H); labelGroup.visible = false;
    updateSun(); syncSunToTarget(true, new THREE.Vector3(...pose.target)); renderer.shadowMap.needsUpdate = true; camera.updateProjectionMatrix();
    if (gtao) gtao.enabled = $('ao').checked;
    composer.render();
    const url = renderer.domElement.toDataURL('image/png'); await fetch('save?name=' + encodeURIComponent(name), { method: 'POST', body: url });
    return name;
  } finally {
    if (vis.length) [ctxRoot, surrGroup, vegGroup].forEach((o, i) => { o.visible = vis[i]; });
    camera.fov = saved.fov; camera.up.copy(saved.up); camera.position.copy(saved.pos); labelGroup.visible = $('showLbl').checked;
    $('date').value = saved.date; $('time').value = saved.t;
    restoreRenderSize(saved.pr); controls.update(); updateSun();
    shotLock = false; shadowDirty = true; markDirty(1000);
  }
};

// ---------------- photoreal still: three-gpu-pathtracer 0.0.23 (r160 shim) ----------------
// Tiled path tracing (one GPU draw stays well under the Windows 2 s TDR), float accumulation, NaN guard, 16-pass jittered raster
// AOVs (albedo, normal, depth) -> serve.py POST /pt_denoise (ptdenoise.py: Intel OIDN + fog + ACES + sRGB); without that endpoint
// the in-browser DenoiseMaterial or the raw result is used. PT-only scene fixes (foliage normals, rib / wood-grain maps, soft
// overcast sun lobe, galvanised-steel gain, yard darkening decal) are applied to temporary copies and undone afterwards.
let pt = null, ptState = null, PTMOD = null;
const PT_RATE = 0.55e6, PT_UI_MAX = 1920, PT_TILE_PX = 0.45e6;
const PT_FIX_ALL = ['foliageN', 'nocore', 'sunLobe', 'nan', 'ribs', 'wood', 'hdg', 'yard', 'fog', 'tex2k', 'sobol'];
function ptParseFixes(s) {
  if (s === undefined || s === null || s === '' || s === 'all') return new Set(PT_FIX_ALL);
  if (s === 'none') return new Set();
  return new Set(String(s).split(/[,+ /]/).filter((f) => PT_FIX_ALL.includes(f)));
}
const ptNum = (v, d) => (Number.isFinite(+v) && v !== null && v !== '' ? +v : d);
const PT_CFG = {
  fixes: ptParseFixes(Q.get('ptFixes')),
  sunLobeDeg: ptNum(Q.get('ptSunLobe'), 5),
  texSize: ptNum(Q.get('ptTex'), 2048),
  exposureGain: ptNum(Q.get('ptExp'), 1.07),
  random: /^(stratified|pcg|sobol)$/.test(Q.get('ptRandom') || '') ? Q.get('ptRandom') : null,
  yardCull: Q.get('ptYardCull') !== '0',
  yardLiftMm: ptNum(Q.get('ptYardLift'), 4.3),
  yardMaxEdge: 3,
  aovPasses: 16, bounces: 5, glossy: 0.5,
  smart: { sigma: 5, threshold: 0.1, kSigma: 1 },
  denoise: /^(auto|oidn|smart|raw)$/.test(Q.get('ptDenoise') || '') ? Q.get('ptDenoise') : null,
};
const SERVER = { probed: false, serve: false, ptDenoise: false, reason: '' };
const serverProbe = fetch('index.html', { cache: 'no-store' }).then(async (r) => {
  await r.text();
  SERVER.serve = !!r.headers.get('X-MOCKUP-Serve'); const d = r.headers.get('X-MOCKUP-PT-Denoise') || '';
  SERVER.ptDenoise = SERVER.serve && /^1/.test(d);
  SERVER.reason = !SERVER.serve ? '静态托管，无 serve.py' : SERVER.ptDenoise ? 'OIDN' : (d.replace(/^0;?\s*/, '') || 'serve.py 无 /pt_denoise');
}).catch(() => { SERVER.reason = '无法探测服务器'; }).finally(() => { SERVER.probed = true; updatePtEstimate(); });
function fmtMin(s) { return s < 90 ? `${Math.round(s)} s` : `${(s / 60).toFixed(s < 600 ? 1 : 0)} 分钟`; }
function ptSizeFor(sel) {
  const m = /^(\d+)x(\d+)$/.exec(sel ?? $('ptSize')?.value ?? 'window'); if (m) return [+m[1], +m[2]];
  const r = renderer.domElement.getBoundingClientRect(); const k = Math.min(1, PT_UI_MAX / Math.max(r.width, r.height, 1));
  return [Math.max(64, Math.round(r.width * k)), Math.max(64, Math.round(r.height * k))];
}
function ptTilesFor(W, H) { return Math.max(1, Math.ceil(Math.sqrt(W * H / PT_TILE_PX))); }
function ptDenoiseMode(o) { return o || PT_CFG.denoise || $('ptDen')?.value || 'auto'; }
function updatePtEstimate() {
  const el = $('ptEst'); if (!el) return;
  const [W, H] = ptSizeFor(); const spp = +$('ptSpp').value || 128; const k = ptTilesFor(W, H); const den = ptDenoiseMode();
  const oidn = (den === 'auto' || den === 'oidn') && SERVER.ptDenoise;
  const denTxt = oidn ? 'Intel OIDN（serve.py）' : den === 'raw' ? '不降噪' : `浏览器内 DenoiseMaterial${SERVER.probed && den !== 'smart' ? '（' + SERVER.reason + '）' : ''}`;
  el.textContent = `${W}×${H}（像素比 1，${k}×${k} 分块）/ ${spp} spp：预计约 ${fmtMin(W * H * spp / PT_RATE)}，另加首次着色器编译 1–2 分钟、BVH 约 15 s、读出与降噪约 ${oidn ? 10 : 5} s。降噪：${denTxt}。`;
  const n = $('ptNote'); if (n) {
    const lobe = PT_CFG.fixes.has('sunLobe') && PT_CFG.sunLobeDeg > 0;
    n.textContent = `three-gpu-pathtracer 0.0.23，分块渲染（每块 ≤ 0.45 Mpx，避开 Windows 显卡 2 s 超时），纹理 ${PT_CFG.fixes.has('tex2k') ? PT_CFG.texSize : 1024}²，曝光 = 实时视图 × ${PT_CFG.exposureGain}。`
      + '参考耗时（集成显卡，ANGLE Vulkan）：2400×1500 / 256 spp 约 24–34 分钟，128 spp 约一半；首次着色器编译另需 1–2 分钟。'
      + '完成后读出浮点结果（NaN 像素按 3×3 邻域修补），经 serve.py 用 Intel OIDN 按反照率 + 法线降噪，按深度补雾，ACES 色调映射；无 serve.py 时改用浏览器内 DenoiseMaterial。'
      + (lobe ? `阴天：直射阳光改为 ${PT_CFG.sunLobeDeg}° 柔和太阳光斑（能量守恒），有柔和阴影。` : '阴天：直射阳光并入均匀天空光，无太阳阴影。')
      + '部分集成显卡须以 ANGLE Vulkan 启动浏览器（D3D11 后端可能出黑 / 白画面）。';
  }
}
function ptActive() { return !!ptState; }
function ptShim() {
  for (const k of ['environmentRotation', 'backgroundRotation']) if (!(k in THREE.Scene.prototype))
    Object.defineProperty(THREE.Scene.prototype, k, { configurable: true, get() { return this['_' + k] ??= new THREE.Euler(); }, set(v) { this['_' + k] = v; } });
}
function ptOutputLooksBroken() {
  const gl = renderer.getContext(); const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
  const px = new Uint8Array(w * h * 4); renderer.setRenderTarget(null); gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
  let dark = 0, white = 0, n = 0;
  for (let i = 0; i < px.length; i += 4 * 7) { const s = px[i] + px[i + 1] + px[i + 2]; n++; if (s < 12) dark++; else if (s > 750) white++; }
  const cx = (w >> 1) - 32, cy = (h >> 1) - 32; let cb = 0; for (let y = 0; y < 64; y++) for (let x = 0; x < 64; x++) { const i = ((cy + y) * w + cx + x) * 4; const s = px[i] + px[i + 1] + px[i + 2]; if (s < 12 || s > 750) cb++; }
  return { broken: dark / n > 0.45 || white / n > 0.45 || cb / 4096 > 0.95, dark: dark / n, white: white / n, center: cb / 4096 };
}
function ptCloneMat(m) { const ud = m.userData; m.userData = {}; try { return m.clone(); } finally { m.userData = ud; } }
function ptWorldGeometry(o) {
  o.updateWorldMatrix(true, false);
  const src = o.geometry, P = src.attributes.position, N = src.attributes.normal, n = P.count;
  const pos = new Float32Array(n * 3), v = new THREE.Vector3(), nm = new THREE.Matrix3().getNormalMatrix(o.matrixWorld);
  for (let i = 0; i < n; i++) { v.fromBufferAttribute(P, i).applyMatrix4(o.matrixWorld); pos[3 * i] = v.x; pos[3 * i + 1] = v.y; pos[3 * i + 2] = v.z; }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  if (N) { const nor = new Float32Array(n * 3); for (let i = 0; i < n; i++) { v.fromBufferAttribute(N, i).applyMatrix3(nm).normalize(); nor[3 * i] = v.x; nor[3 * i + 1] = v.y; nor[3 * i + 2] = v.z; } g.setAttribute('normal', new THREE.BufferAttribute(nor, 3)); }
  if (src.index) g.setIndex(new THREE.BufferAttribute(Uint32Array.from(src.index.array), 1));
  else { const ix = new Uint32Array(n); for (let i = 0; i < n; i++) ix[i] = i; g.setIndex(new THREE.BufferAttribute(ix, 1)); }
  if (o.matrixWorld.determinant() < 0) { const a = g.index.array; for (let i = 0; i < a.length; i += 3) { const t = a[i + 1]; a[i + 1] = a[i + 2]; a[i + 2] = t; } }
  if (!g.attributes.normal) g.computeVertexNormals();
  return g;
}
function ptClipToBox(g, x0, z0, x1, z1) {
  const P = g.attributes.position.array, N = g.attributes.normal?.array, I = g.index ? g.index.array : null;
  const nt = (I ? I.length : P.length / 3) / 3; const op = [], on = [];
  const planes = [[0, 1, x0], [0, -1, -x1], [2, 1, z0], [2, -1, -z1]];
  for (let t = 0; t < nt; t++) {
    let poly = [0, 1, 2].map((k) => { const i = I ? I[3 * t + k] : 3 * t + k; return [P[3 * i], P[3 * i + 1], P[3 * i + 2], N ? N[3 * i] : 0, N ? N[3 * i + 1] : 1, N ? N[3 * i + 2] : 0]; });
    for (const [ax, sg, b] of planes) {
      const out = []; const inside = (v) => sg * v[ax] >= b;
      for (let k = 0; k < poly.length; k++) {
        const a = poly[k], c = poly[(k + 1) % poly.length]; const ia = inside(a), ic = inside(c);
        if (ia) out.push(a);
        if (ia !== ic) { const f = (b - sg * a[ax]) / (sg * (c[ax] - a[ax])); out.push(a.map((x, j) => x + (c[j] - x) * f)); }
      }
      poly = out; if (poly.length < 3) break;
    }
    if (poly.length < 3) continue;
    for (let k = 1; k + 1 < poly.length; k++) for (const v of [poly[0], poly[k], poly[k + 1]]) { op.push(v[0], v[1], v[2]); on.push(v[3], v[4], v[5]); }
  }
  if (!op.length) return null;
  const r = new THREE.BufferGeometry(); r.setAttribute('position', new THREE.Float32BufferAttribute(op, 3)); r.setAttribute('normal', new THREE.Float32BufferAttribute(on, 3));
  const ix = new Uint32Array(op.length / 3); for (let i = 0; i < ix.length; i++) ix[i] = i; r.setIndex(new THREE.BufferAttribute(ix, 1));
  return r;
}
function ptSubdivide(g, maxLen) {
  const P = g.attributes.position.array, N = g.attributes.normal?.array, I = g.index ? g.index.array : null;
  const nt = (I ? I.length : P.length / 3) / 3, m2 = maxLen * maxLen, op = [], on = [], st = [];
  const d2 = (p, q) => (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2, mid = (p, q) => p.map((x, j) => (x + q[j]) / 2);
  for (let t = 0; t < nt; t++) {
    st.push([0, 1, 2].map((k) => { const i = I ? I[3 * t + k] : 3 * t + k; return [P[3 * i], P[3 * i + 1], P[3 * i + 2], N ? N[3 * i] : 0, N ? N[3 * i + 1] : 1, N ? N[3 * i + 2] : 0]; }));
    while (st.length) {
      const [a, b, c] = st.pop(); const e0 = d2(a, b), e1 = d2(b, c), e2 = d2(c, a), e = Math.max(e0, e1, e2);
      if (e <= m2) { for (const w of [a, b, c]) { const l = Math.hypot(w[3], w[4], w[5]) || 1; op.push(w[0], w[1], w[2]); on.push(w[3] / l, w[4] / l, w[5] / l); } continue; }
      if (e === e0) { const m = mid(a, b); st.push([a, m, c], [m, b, c]); } else if (e === e1) { const m = mid(b, c); st.push([a, b, m], [a, m, c]); } else { const m = mid(c, a); st.push([a, b, m], [m, b, c]); }
    }
  }
  const r = new THREE.BufferGeometry(); r.setAttribute('position', new THREE.Float32BufferAttribute(op, 3)); r.setAttribute('normal', new THREE.Float32BufferAttribute(on, 3));
  const ix = new Uint32Array(op.length / 3); for (let i = 0; i < ix.length; i++) ix[i] = i; r.setIndex(new THREE.BufferAttribute(ix, 1));
  return r;
}
let ptYardCache = null;
function ptYardDecal(add) {
  const lib = LIB.CTX_CONCRETE_YARD; const map = YARD_U.uYardMap.value;
  if (!lib || YARD_CAL.off || !map?.image?.getContext || map.image.width < 8) return 'yard map not built';
  if (!ptYardCache || ptYardCache.src !== map || ptYardCache.cull !== PT_CFG.yardCull) {
    const cv = map.image, W = cv.width, H = cv.height;
    const d = cv.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, W, H).data;
    const out = document.createElement('canvas'); out.width = W; out.height = H; const g = out.getContext('2d'); const id = g.createImageData(W, H); const o = id.data;
    const D = YARD_U.uYardDamp.value, K = YARD_U.uYardDirt.value;
    const ss = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
    let sumA = 0;
    const cellPx = Math.max(1, Math.round(2.0 / (YARD_U.uYardS.value.x / W))), CW = Math.ceil(W / cellPx), CH = Math.ceil(H / cellPx), cell = new Uint8Array(CW * CH);
    for (let i = 0; i < W * H; i++) {
      const r = d[4 * i] / 255, gg = d[4 * i + 1] / 255, n = d[4 * i + 2] / 255;
      const v = ss(0.18, 0.78, r + 0.55 * (n - 0.5)) * ss(0.01, 0.08, r);
      const a = 1 - (1 - D * v * (0.8 + 0.2 * n)) * (1 - K * gg); sumA += a;
      const a8 = Math.round(255 * a); o[4 * i + 3] = a8;
      if (a8) { const x = i % W, y = (i - x) / W; cell[((y / cellPx) | 0) * CW + ((x / cellPx) | 0)] = 1; }
    }
    const keep = new Uint8Array(CW * CH);
    for (let cy = 0; cy < CH; cy++) for (let cx = 0; cx < CW; cx++) {
      let k = 0; for (let dy = -1; dy <= 1 && !k; dy++) for (let dx = -1; dx <= 1 && !k; dx++) { const x = cx + dx, y = cy + dy; if (x >= 0 && y >= 0 && x < CW && y < CH && cell[y * CW + x]) k = 1; }
      keep[cy * CW + cx] = k;
    }
    const rects = [];
    for (let cy = 0; cy < CH; cy++) for (let cx = 0; cx < CW;) { if (!keep[cy * CW + cx]) { cx++; continue; } const x0 = cx; while (cx < CW && keep[cy * CW + cx]) cx++; rects.push([x0 * cellPx, cy * cellPx, Math.min(W, cx * cellPx), Math.min(H, (cy + 1) * cellPx)]); }
    let kept = 0; for (const k of keep) kept += k;
    if (!PT_CFG.yardCull) { rects.length = 0; rects.push([0, 0, W, H]); kept = CW * CH; }
    g.putImageData(id, 0, 0);
    const t = new THREE.CanvasTexture(out); t.flipY = false; t.colorSpace = THREE.NoColorSpace; t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
    t.generateMipmaps = false; t.minFilter = THREE.LinearFilter;
    ptYardCache = { src: map, cull: PT_CFG.yardCull, tex: t, meanA: sumA / (W * H), rects, px: [W, H], cellM: +(cellPx * YARD_U.uYardS.value.x / W).toFixed(3), keptFrac: kept / (CW * CH) };
  }
  const O = YARD_U.uYardO.value, S = YARD_U.uYardS.value;
  const mat = new THREE.MeshStandardMaterial({ name: 'PT_YARD_DECAL', color: 0x000000, map: ptYardCache.tex, transparent: true, depthWrite: false,
    roughness: Math.max(0.3, (lib.roughness ?? 0.8) * (1 - YARD_U.uYardDampRough.value)), metalness: 0, side: THREE.DoubleSide });
  mat.castShadow = false;
  mat.polygonOffset = true; mat.polygonOffsetFactor = 0; mat.polygonOffsetUnits = -2;
  const tmp = new THREE.Vector3(); let n = 0, tris = 0; const [PW, PH] = ptYardCache.px; const liftC = PT_CFG.yardLiftMm / 1000, lift = [Infinity, 0];
  const slabs = []; scene.traverse((o) => { if (o.isMesh && !o.userData.ptTemp && o.material === lib && isVisibleChain(o)) slabs.push(o); });
  for (const o of slabs) {
    const wg = ptWorldGeometry(o); const parts = [];
    for (const [px0, py0, px1, py1] of ptYardCache.rects) {
      const c = ptClipToBox(wg, O.x + px0 / PW * S.x, O.y + py0 / PH * S.y, O.x + px1 / PW * S.x, O.y + py1 / PH * S.y); if (c) parts.push(c);
    }
    wg.dispose(); if (!parts.length) continue;
    const g0 = parts.length === 1 ? parts[0] : mergeGeometries(parts); parts.forEach((q) => { if (q !== g0) q.dispose(); });
    const g = ptSubdivide(g0, PT_CFG.yardMaxEdge); g0.dispose();
    const pos = g.attributes.position, uv = new Float32Array(pos.count * 2);
    for (let i = 0; i < pos.count; i++) {
      tmp.fromBufferAttribute(pos, i);
      const s = 1e-4 * (Math.max(Math.abs(tmp.x), Math.abs(tmp.y), Math.abs(tmp.z)) + 1); lift[0] = Math.min(lift[0], s + liftC); lift[1] = Math.max(lift[1], s + liftC);
      pos.setY(i, tmp.y + s + liftC);
      uv[2 * i] = (tmp.x - O.x) / S.x; uv[2 * i + 1] = (tmp.z - O.y) / S.y;
    }
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    const mesh = new THREE.Mesh(g, mat); mesh.name = 'PT yard decal'; mesh.userData.ptTemp = true; add(mesh); n++; tris += g.index.count / 3;
  }
  return { meshes: n, tris, meanDarkening: +ptYardCache.meanA.toFixed(4), cellM: ptYardCache.cellM, keptCellFrac: +ptYardCache.keptFrac.toFixed(3), rects: ptYardCache.rects.length,
    liftMm: n ? [+(lift[0] * 1000).toFixed(2), +(lift[1] * 1000).toFixed(2)] : null, maxEdgeM: PT_CFG.yardMaxEdge, undo: () => mat.dispose() };
}
const ptRibTex = new Map();
function ptRibMeshes(add, hide) {
  const tmp = new THREE.Vector3(), nrm = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0), tW = new THREE.Vector3();
  const list = []; const mats = new Map();
  scene.traverse((o) => {
    if (!o.isMesh || o.userData.ptTemp || !isVisibleChain(o)) return; const m = [].concat(o.material)[0];
    const P = m?.userData?.entry?.procedural; if (!P || P.type !== 'ribs_normal' || m.userData.variant === 'noribs' || !m.userData.feats?.ribs) return;
    list.push([o, m]);
  });
  for (const [o, m] of list) {
    const R = m.userData.feats.ribs; const key = [R.pitch, R.depth, R.w, R.top, R.groove].join(',');
    if (!ptRibTex.has(key)) {
      const N = 256, kx = R.depth / (R.w * R.pitch), nd = new Uint8Array(N * 4 * 4), cd = new Uint8Array(N * 4 * 4);
      for (let i = 0; i < N; i++) {
        const fr = (i + 0.5) / N; const sl = fr < R.w ? 1 : (fr > R.w + R.top && fr < 2 * R.w + R.top ? -1 : 0);
        const nx = -sl * kx, l = Math.hypot(nx, 1); const gr = fr > 2 * R.w + R.top ? 1 - R.groove : 1;
        for (let r = 0; r < 4; r++) { const j = (r * N + i) * 4; nd[j] = Math.round((nx / l * 0.5 + 0.5) * 255); nd[j + 1] = 128; nd[j + 2] = Math.round((1 / l * 0.5 + 0.5) * 255); nd[j + 3] = 255;
          const c = Math.round(gr * 255); cd[j] = cd[j + 1] = cd[j + 2] = c; cd[j + 3] = 255; }
      }
      const mk = (a) => { const t = new THREE.DataTexture(a, N, 4, THREE.RGBAFormat); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.magFilter = t.minFilter = THREE.LinearFilter; t.colorSpace = THREE.NoColorSpace; t.needsUpdate = true; return t; };
      ptRibTex.set(key, { n: mk(nd), c: mk(cd) });
    }
    const T = ptRibTex.get(key); const g = ptWorldGeometry(o);
    const pos = g.attributes.position, nor = g.attributes.normal, uv = new Float32Array(pos.count * 2);
    for (let i = 0; i < pos.count; i++) {
      tmp.fromBufferAttribute(pos, i); nrm.fromBufferAttribute(nor, i).normalize();
      if (Math.abs(nrm.y) < 0.7) { tW.crossVectors(up, nrm).normalize(); uv[2 * i] = tmp.dot(tW) / R.pitch; } else uv[2 * i] = tmp.x / R.pitch;
      uv[2 * i + 1] = tmp.y;
    }
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    let pm = mats.get(m);
    if (!pm) { pm = ptCloneMat(m); pm.name = (m.name || '') + ' (PT ribs)'; pm.normalMap = T.n; pm.normalScale = new THREE.Vector2(1, 1); if (!m.map) pm.map = T.c; mats.set(m, pm); }
    const mesh = new THREE.Mesh(g, pm); mesh.name = o.name + ' (PT ribs)'; mesh.userData.ptTemp = true; add(mesh); hide(o);
  }
  return { meshes: list.length, materials: [...new Set(list.map((x) => x[1].name))], undo: () => mats.forEach((p) => p.dispose()) };
}
let ptWoodTex = null;
function ptWoodTexture() {
  if (ptWoodTex) return ptWoodTex;
  const NU = 1024, NV = 512, TU = 1, TV = 5; const d = new Float32Array(NU * NV);
  const fr = (x) => x - Math.floor(x);
  const hash = (x, y) => { let px = fr(x * 123.34), py = fr(y * 456.21); const q = px * (px + 45.32) + py * (py + 45.32); px += q; py += q; return fr(px * py); };
  const noiseP = (x, y, PX, PY) => {
    const ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy, ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
    const h = (a, b) => hash(((a % PX) + PX) % PX, ((b % PY) + PY) % PY);
    const a0 = h(ix, iy) + (h(ix + 1, iy) - h(ix, iy)) * ux, a1 = h(ix, iy + 1) + (h(ix + 1, iy + 1) - h(ix, iy + 1)) * ux; return a0 + (a1 - a0) * uy;
  };
  for (let j = 0; j < NV; j++) {
    const y = (j + 0.5) / NV * TV;
    for (let i = 0; i < NU; i++) {
      const s = (i + 0.5) / NU * TU;
      const q = s * 110 + 2.2 * noiseP(s * 7, y * 0.4, 7, 2);
      d[j * NU + i] = (0.5 + 0.5 * Math.sin(q * Math.PI)) * 0.55 + noiseP(q * 0.9, y * 3, 99, 15) * 0.45;
    }
  }
  ptWoodTex = { g: d, NU, NV, TU, TV, tex: new Map() };
  return ptWoodTex;
}
function ptWoodMap(amp) {
  const W = ptWoodTexture(); const key = amp.toFixed(4); if (W.tex.has(key)) return W.tex.get(key);
  const a = new Uint8Array(W.NU * W.NV * 4);
  for (let i = 0; i < W.g.length; i++) { const v = Math.round(255 * (1 + amp * (2 * W.g[i] - 1)) / (1 + amp)); a[4 * i] = a[4 * i + 1] = a[4 * i + 2] = v; a[4 * i + 3] = 255; }
  const t = new THREE.DataTexture(a, W.NU, W.NV, THREE.RGBAFormat); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearFilter; t.colorSpace = THREE.NoColorSpace; t.needsUpdate = true;
  W.tex.set(key, t); return t;
}
function ptWoodMeshes(add, hide) {
  const tmp = new THREE.Vector3(), nrm = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0), tW = new THREE.Vector3(); const W = ptWoodTexture();
  const list = []; const mats = new Map();
  scene.traverse((o) => { if (o.isMesh && !o.userData.ptTemp && !Array.isArray(o.material) && o.material?.userData?.feats?.wood && isVisibleChain(o)) list.push(o); });
  for (const o of list) {
    const m = o.material; const amp = +m.userData.feats.wood.amp || 0;
    const g = ptWorldGeometry(o); const pos = g.attributes.position, nor = g.attributes.normal, uv = new Float32Array(pos.count * 2);
    for (let i = 0; i < pos.count; i++) {
      tmp.fromBufferAttribute(pos, i); nrm.fromBufferAttribute(nor, i).normalize();
      tW.crossVectors(up, nrm).add(new THREE.Vector3(1e-4, 0, 1e-4)).normalize();
      const s = Math.abs(nrm.y) > 0.8 ? tmp.x : tmp.dot(tW);
      uv[2 * i] = s / W.TU; uv[2 * i + 1] = tmp.y / W.TV;
    }
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    let pm = mats.get(m);
    if (!pm) { pm = ptCloneMat(m); pm.name = (m.name || '') + ' (PT wood)'; pm.map = ptWoodMap(amp); pm.color.multiplyScalar(1 + amp); mats.set(m, pm); }
    const mesh = new THREE.Mesh(g, pm); mesh.name = o.name + ' (PT wood)'; mesh.userData.ptTemp = true; add(mesh); hide(o);
  }
  return { meshes: list.length, amp: list.length ? +list[0].material.userData.feats.wood.amp : null, undo: () => mats.forEach((p) => p.dispose()) };
}
function ptSunLobeEnv(Esun) {
  const src = hdrCurrent.tex, { width: w, height: h, data } = src.image; const d = sunDir;
  const cosR = Math.cos(PT_CFG.sunLobeDeg * Math.PI / 180); const wts = new Float32Array(w * h); let S = 0;
  const cph = new Float32Array(w), sph = new Float32Array(w);
  for (let x = 0; x < w; x++) { const phi = ((x + 0.5) / w - 0.5) * 2 * Math.PI; cph[x] = Math.cos(phi); sph[x] = Math.sin(phi); }
  for (let y = 0; y < h; y++) {
    const th = (y + 0.5) / h * Math.PI, dy = Math.cos(th), sy = Math.sin(th), dOm = sy * (Math.PI / h) * (2 * Math.PI / w);
    for (let x = 0; x < w; x++) {
      const ca = cph[x] * sy * d.x + dy * d.y + sph[x] * sy * d.z; if (ca <= cosR) continue;
      let f = (ca - cosR) / (1 - cosR); f = f * f * (3 - 2 * f); f *= f;
      wts[y * w + x] = f; if (dy > 0) S += f * dy * dOm;
    }
  }
  if (!(S > 0)) return null;
  const out = new Float32Array(data.length); out.set(data);
  const c = sun.color, lum = lumOf(c), L0 = Esun / S; let Echeck = 0;
  for (let i = 0; i < w * h; i++) { const f = wts[i]; if (!f) continue; const k = i * 4; out[k] += L0 * f * c.r / lum; out[k + 1] += L0 * f * c.g / lum; out[k + 2] += L0 * f * c.b / lum;
    const y = (i / w) | 0, th = (y + 0.5) / h * Math.PI, ct = Math.cos(th); if (ct > 0) Echeck += (0.2126 * (out[k] - data[k]) + 0.7152 * (out[k + 1] - data[k + 1]) + 0.0722 * (out[k + 2] - data[k + 2])) * ct * Math.sin(th) * (Math.PI / h) * (2 * Math.PI / w); }
  const t = new THREE.DataTexture(out, w, h, THREE.RGBAFormat, THREE.FloatType);
  t.mapping = THREE.EquirectangularReflectionMapping; t.flipY = src.flipY; t.colorSpace = src.colorSpace; t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearFilter; t.needsUpdate = true;
  return { tex: t, L0: +L0.toFixed(3), deg: PT_CFG.sunLobeDeg, Echeck: +Echeck.toFixed(4) };
}
const ptSwaps = [];
function ptPrepareScene(fx) {
  const S = ptState; S.fixInfo = {}; S.undo = []; S.temp = []; S.hiddenObjs = [];
  const add = (m) => { scene.add(m); S.temp.push(m); }; const hide = (o) => { if (o.visible) { o.visible = false; S.hiddenObjs.push(o); } };
  scene.traverse((o) => { if (o.isMesh && o.material?.userData?.ptMaterial) { ptSwaps.push([o, o.material]); o.material = o.material.userData.ptMaterial; } });
  if (fx.has('hdg')) {
    const copies = new Map();
    scene.traverse((o) => {
      const m = o.isMesh && !Array.isArray(o.material) ? o.material : null; if (!m?.userData?.hdgCal || !(m.userData.hdgCal.env > 0)) return;
      let c = copies.get(m); if (!c) { c = ptCloneMat(m); c.name = m.name + ' (PT hdg)'; const k = m.userData.hdgCal.env; c.color.setRGB(Math.min(1, m.color.r * k), Math.min(1, m.color.g * k), Math.min(1, m.color.b * k)); copies.set(m, c); }
      ptSwaps.push([o, o.material]); o.material = c;
    });
    S.fixInfo.hdg = { materials: copies.size, gain: HDG_CAL.env }; S.undo.push(() => copies.forEach((c) => c.dispose()));
  }
  const merged = []; let nFol = 0, nCore = 0;
  for (const im of vegInstanced) {
    if (!im.visible || !vegGroup.visible) continue;
    const mn = im.material?.name || '';
    if (fx.has('nocore') && /POLYALTHIA_CORE/.test(mn)) { im.visible = false; im.userData.ptHidden = true; nCore++; continue; }
    const geos = []; const m4 = new THREE.Matrix4();
    const base = im.geometry.index ? im.geometry.toNonIndexed() : im.geometry;
    for (let i = 0; i < im.count; i++) { im.getMatrixAt(i, m4); const g = base.clone(); g.applyMatrix4(m4); for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'uv', 'color'].includes(k)) g.deleteAttribute(k); if (!g.attributes.uv) g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2)); geos.push(g); }
    const mg = mergeGeometries(geos);
    if (fx.has('foliageN') && /LEAF|FROND/.test(mn)) { mg.computeVertexNormals(); nFol++; }
    const mesh = new THREE.Mesh(mg, im.material); mesh.name = im.name + ' (PT)'; mesh.userData.ptTemp = true;
    im.visible = false; im.userData.ptHidden = true; vegGroup.add(mesh); merged.push(mesh);
  }
  S.merged = merged; S.fixInfo.foliageN = nFol; S.fixInfo.nocore = nCore;
  S.hidden = [];
  for (const o of [labelGroup, selBox, measGroup]) { S.hidden.push([o, o.visible]); o.visible = false; }
  labelRenderer.domElement.style.display = 'none';
  if (hdrCurrent) { scene.environment = hdrCurrent.tex; scene.background = hdrCurrent.tex; }
  scene.environmentIntensity = 1; scene.backgroundIntensity = hdrCurrent ? hdrCurrent.P.bg : 1;
  S.sunVisible = sun.visible;
  if (hdrCurrent?.P.ptDiffuseSun && hdrCurrent.Esky > 0) {
    const Esun = sun.visible ? sun.intensity * lumOf(sun.color) * Math.max(0, sunDir.y) : 0; sun.visible = false;
    const lobe = fx.has('sunLobe') && PT_CFG.sunLobeDeg > 0 && Esun > 0 ? ptSunLobeEnv(Esun) : null;
    if (lobe) { scene.environment = lobe.tex; S.undo.push(() => lobe.tex.dispose()); S.sunMode = { mode: `lobe ${lobe.deg} deg`, Esun: +Esun.toFixed(4), EsunLobe: lobe.Echeck, Esky: +hdrCurrent.Esky.toFixed(4), L0: lobe.L0 }; }
    else { scene.environmentIntensity = 1 + Esun / hdrCurrent.Esky; S.sunMode = { mode: 'diffuse (sky x' + scene.environmentIntensity.toFixed(3) + ')', Esun: +Esun.toFixed(3), Esky: +hdrCurrent.Esky.toFixed(3) }; }
  } else S.sunMode = { mode: 'directional', intensity: +sun.intensity.toFixed(3) };
  S.fog = scene.fog; scene.fog = null;
  const run = (k, f) => { if (!fx.has(k)) return; try { const r = f(); if (r && typeof r === 'object' && r.undo) { S.undo.push(r.undo); delete r.undo; } S.fixInfo[k] = r; } catch (e) { console.warn('path tracer fix ' + k, e); S.fixInfo[k] = 'failed: ' + e.message; } };
  run('ribs', () => ptRibMeshes(add, hide));
  run('wood', () => ptWoodMeshes(add, hide));
  run('yard', () => ptYardDecal(add));
}
function ptRestoreScene() {
  const S = ptState;
  for (let i = ptSwaps.length - 1; i >= 0; i--) ptSwaps[i][0].material = ptSwaps[i][1]; ptSwaps.length = 0;
  for (const m of S.merged || []) { m.removeFromParent(); m.geometry.dispose(); }
  for (const m of S.temp || []) { m.removeFromParent(); m.geometry.dispose(); }
  for (const o of S.hiddenObjs || []) o.visible = true;
  for (const im of vegInstanced) if (im.userData.ptHidden) { im.visible = true; im.userData.ptHidden = false; }
  for (const [o, v] of S.hidden || []) o.visible = v;
  for (const f of S.undo || []) { try { f(); } catch (e) {  } }
  labelRenderer.domElement.style.display = $('showLbl').checked ? '' : 'none';
  if (hdrCurrent) { scene.environment = hdrCurrent.env.texture; scene.background = hdrCurrent.tex; }
  scene.environmentIntensity = 1; if (S.sunVisible !== undefined) sun.visible = S.sunVisible;
  scene.fog = S.fog;
}
function ptNanGuard(c, W, H) {
  const bad = [];
  for (let i = 0, n = W * H; i < n; i++) { const k = 4 * i; if ((c[k] - c[k]) + (c[k + 1] - c[k + 1]) + (c[k + 2] - c[k + 2]) !== 0) bad.push(i); }
  const fin = (k) => (c[k] - c[k]) + (c[k + 1] - c[k + 1]) + (c[k + 2] - c[k + 2]) === 0;
  const fix = bad.map((i) => {
    const x = i % W, y = (i - x) / W; let r = 0, g = 0, b = 0, n = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= W || yy >= H) continue; const k = 4 * (yy * W + xx);
      if (fin(k)) { r += c[k]; g += c[k + 1]; b += c[k + 2]; n++; }
    }
    return n ? [r / n, g / n, b / n] : [0, 0, 0];
  });
  bad.forEach((i, j) => { const k = 4 * i; c[k] = fix[j][0]; c[k + 1] = fix[j][1]; c[k + 2] = fix[j][2]; });
  return bad.length;
}
const NRM_VS = `
  uniform mat3 mapT; uniform mat3 alphaT;
  varying vec3 vN; varying float vD; varying vec2 vUvM; varying vec2 vUvA;
  void main() {
    vN = mat3( modelMatrix ) * normal;
    vec4 mv = modelViewMatrix * vec4( position, 1.0 ); vD = - mv.z;
    vUvM = ( mapT * vec3( uv, 1.0 ) ).xy; vUvA = ( alphaT * vec3( uv, 1.0 ) ).xy;
    gl_Position = projectionMatrix * mv;
  }`;
const NRM_FS = `
  uniform sampler2D map; uniform sampler2D alphaMap; uniform float useMap; uniform float useAlpha; uniform float alphaTest;
  varying vec3 vN; varying float vD; varying vec2 vUvM; varying vec2 vUvA;
  void main() {
    float a = 1.0;
    if ( useMap > 0.5 ) a *= texture2D( map, vUvM ).a;
    if ( useAlpha > 0.5 ) a *= texture2D( alphaMap, vUvA ).g;
    if ( a < alphaTest ) discard;
    vec3 n = dot( vN, vN ) > 1e-12 ? normalize( vN ) : vec3( 0.0, 1.0, 0.0 );
    gl_FragColor = vec4( gl_FrontFacing ? n : - n, vD );
  }`;
function ptAovMaterial(src, pass, cache) {
  if (!src) return src; if (cache.has(src)) return cache.get(src);
  const texM = (t) => { if (!t) return new THREE.Matrix3(); if (t.matrixAutoUpdate) t.updateMatrix(); return t.matrix.clone(); };
  const blend = src.transparent && !(src.alphaTest > 0) && !(src.transmission > 0); const at = src.alphaTest > 0 ? src.alphaTest : 0; let m;
  if (src.visible === false) m = new THREE.MeshBasicMaterial({ visible: false });
  else if (blend) m = pass === 0 ? new THREE.MeshBasicMaterial({ color: src.color ? src.color.clone() : new THREE.Color(1, 1, 1), map: src.map || null, alphaMap: src.alphaMap || null,
    transparent: true, opacity: src.opacity ?? 1, depthWrite: false, side: THREE.DoubleSide, fog: false, toneMapped: false,
    polygonOffset: !!src.polygonOffset, polygonOffsetFactor: src.polygonOffsetFactor || 0, polygonOffsetUnits: src.polygonOffsetUnits || 0 }) : new THREE.MeshBasicMaterial({ visible: false });
  else if (pass === 0) m = new THREE.MeshBasicMaterial({ color: src.color ? src.color.clone() : new THREE.Color(1, 1, 1), map: src.map || null,
    alphaMap: at ? (src.alphaMap || null) : null, alphaTest: at, vertexColors: !!src.vertexColors, side: THREE.DoubleSide, fog: false, toneMapped: false });
  else {
    const useMap = at > 0 && !!src.map, useAlpha = at > 0 && !!src.alphaMap;
    m = new THREE.ShaderMaterial({ vertexShader: NRM_VS, fragmentShader: NRM_FS, side: THREE.DoubleSide,
      uniforms: { map: { value: useMap ? src.map : null }, alphaMap: { value: useAlpha ? src.alphaMap : null }, useMap: { value: useMap ? 1 : 0 },
        useAlpha: { value: useAlpha ? 1 : 0 }, alphaTest: { value: at }, mapT: { value: texM(src.map) }, alphaT: { value: texM(src.alphaMap) } } });
  }
  cache.set(src, m); return m;
}
function ptRenderAOVs(W, H, N = PT_CFG.aovPasses) {
  const R = renderer; const t0 = performance.now();
  const rt = new THREE.WebGLRenderTarget(W, H, { type: THREE.FloatType, format: THREE.RGBAFormat, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: true });
  const tmp = new Float32Array(W * H * 4); const acc = [new Float32Array(W * H * 4), new Float32Array(W * H * 4)];
  const caches = [new Map(), new Map()]; const swaps = [], hid = [];
  scene.traverse((o) => { if ((o.isLine || o.isPoints || o.isSprite) && o.visible) hid.push(o); if (o.isMesh) swaps.push([o, o.material]); });
  for (const o of hid) o.visible = false;
  const bg = scene.background, fog = scene.fog, ov = scene.overrideMaterial; scene.background = null; scene.fog = null; scene.overrideMaterial = null;
  const cc = new THREE.Color(); R.getClearColor(cc); const ca = R.getClearAlpha(); R.setClearColor(0x000000, 0);
  const n = Math.max(1, Math.round(Math.sqrt(N))), offs = [];
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) offs.push([(i + 0.5) / n - 0.5, (j + 0.5) / n - 0.5]);
  try {
    for (let pass = 0; pass < 2; pass++) {
      for (const [o, m] of swaps) o.material = Array.isArray(m) ? m.map((x) => ptAovMaterial(x, pass, caches[pass])) : ptAovMaterial(m, pass, caches[pass]);
      const A = acc[pass];
      for (const [dx, dy] of offs) {
        camera.setViewOffset(W, H, dx, dy, W, H);
        R.setRenderTarget(rt); R.clear(true, true, true); R.render(scene, camera);
        R.readRenderTargetPixels(rt, 0, 0, W, H, tmp);
        for (let i = 0; i < A.length; i++) A[i] += tmp[i];
      }
      const k = 1 / offs.length; for (let i = 0; i < A.length; i++) A[i] *= k;
    }
  } finally {
    camera.clearViewOffset(); camera.updateProjectionMatrix();
    for (const [o, m] of swaps) o.material = m;
    for (const o of hid) o.visible = true;
    scene.background = bg; scene.fog = fog; scene.overrideMaterial = ov;
    R.setClearColor(cc, ca); R.setRenderTarget(null); rt.dispose();
    for (const c of caches) c.forEach((m) => m.dispose());
  }
  return { albedo: acc[0], normal: acc[1], passes: offs.length, ms: Math.round(performance.now() - t0) };
}
function ptApplyFog(c, aov, fog) {
  const A = aov.albedo, Nn = aov.normal, [fr, fg, fb] = fog.color, D = fog.density;
  for (let k = 0; k < c.length; k += 4) {
    const cov = Math.min(1, Math.max(0, A[k + 3])); if (!(cov > 1e-4)) continue;
    const z = Nn[k + 3] / cov, t = D * z, f = cov * (1 - Math.exp(-t * t));
    c[k] += f * (fr - c[k]); c[k + 1] += f * (fg - c[k + 1]); c[k + 2] += f * (fb - c[k + 2]);
  }
}
const F16T = (() => {
  const base = new Uint16Array(512), shift = new Uint8Array(512);
  for (let i = 0; i < 256; i++) {
    const e = i - 127; let b, s;
    if (e < -24) { b = 0; s = 24; } else if (e < -14) { b = 0x0400 >> (-e - 14); s = -e - 1; } else if (e <= 15) { b = (e + 15) << 10; s = 13; } else if (e < 128) { b = 0x7c00; s = 24; } else { b = 0x7c00; s = 13; }
    base[i] = b; base[i | 0x100] = b | 0x8000; shift[i] = shift[i | 0x100] = s;
  }
  return { base, shift };
})();
function f32ToF16(src) {
  const u = new Uint32Array(src.buffer, src.byteOffset, src.length), out = new Uint16Array(src.length), { base, shift } = F16T;
  for (let i = 0; i < u.length; i++) { const f = u[i], e = f >>> 23; out[i] = base[e] + ((f & 0x007fffff) >>> shift[e]); }
  return out;
}
async function ptServerDenoise(col, aov, W, H, exposure, fog, meta, tm = {}) {
  const arrays = [], parts = []; let off = 0; let t = performance.now();
  const put = (name, arr, dtype) => { arrays.push({ name, dtype, ch: 4, offset: off, bytes: arr.byteLength }); parts.push(arr); off += arr.byteLength; };
  put('color', col, 'f4');
  if (aov) { put('albedo', f32ToF16(aov.albedo), 'f2'); put('normal', f32ToF16(aov.normal), 'f2'); }
  const j = new TextEncoder().encode(JSON.stringify({ W, H, exposure, toneMapping: 'ACESFilmic', fog, rowsBottomUp: true, arrays, ...meta }));
  const pad = (16 - ((12 + j.length) % 16)) % 16; const head = new Uint8Array(12 + j.length + pad);
  head.set(new TextEncoder().encode('MOCKUPT1')); new DataView(head.buffer).setUint32(8, j.length + pad, true); head.set(j, 12); head.fill(32, 12 + j.length);
  const body = new Blob([head, ...parts]); tm.packMs = Math.round(performance.now() - t); t = performance.now();
  const r = await fetch('pt_denoise', { method: 'POST', body, headers: { 'Content-Type': 'application/octet-stream' } });
  if (!r.ok) { let t = ''; try { t = (await r.text()).slice(0, 300); } catch (e) {  } throw new Error(`HTTP ${r.status} ${t}`); }
  let stats = {}; try { stats = JSON.parse(r.headers.get('X-PT-Stats') || '{}'); } catch (e) {  }
  const blob = await r.blob(); tm.requestMs = Math.round(performance.now() - t); tm.bodyMB = +(body.size / 1048576).toFixed(1);
  return { blob, stats };
}
const PT_VS = 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 ); }';
function ptQuadDraw(material) {
  const q = new FullScreenQuad(material); renderer.setRenderTarget(null); renderer.setViewport(0, 0, renderer.domElement.width, renderer.domElement.height);
  q.render(renderer); q.dispose();
}
function ptDrawFloat(c, W, H, mode) {
  const tex = new THREE.DataTexture(c, W, H, THREE.RGBAFormat, THREE.FloatType); tex.minFilter = tex.magFilter = THREE.NearestFilter; tex.generateMipmaps = false; tex.needsUpdate = true;
  let m;
  if (mode === 'smart' && PTMOD?.DenoiseMaterial) {
    m = new PTMOD.DenoiseMaterial({ map: tex, blending: THREE.NoBlending });
    m.uniforms.sigma.value = PT_CFG.smart.sigma; m.uniforms.threshold.value = PT_CFG.smart.threshold; m.uniforms.kSigma.value = PT_CFG.smart.kSigma;
  } else m = new THREE.ShaderMaterial({ uniforms: { map: { value: tex } }, vertexShader: PT_VS, depthTest: false, depthWrite: false, blending: THREE.NoBlending,
    fragmentShader: 'uniform sampler2D map; varying vec2 vUv;\nvoid main() {\n gl_FragColor = vec4( texelFetch( map, ivec2( gl_FragCoord.xy ), 0 ).rgb, 1.0 );\n #include <tonemapping_fragment>\n #include <colorspace_fragment>\n}' });
  ptQuadDraw(m); const url = renderer.domElement.toDataURL('image/png'); m.dispose(); tex.dispose();
  return url;
}
async function ptDrawPNG(blob) {
  const bmp = await createImageBitmap(blob, { imageOrientation: 'flipY', premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
  const tex = new THREE.Texture(bmp); tex.flipY = false; tex.colorSpace = THREE.NoColorSpace; tex.minFilter = tex.magFilter = THREE.NearestFilter; tex.generateMipmaps = false; tex.needsUpdate = true;
  const m = new THREE.ShaderMaterial({ uniforms: { map: { value: tex } }, vertexShader: PT_VS, depthTest: false, depthWrite: false, blending: THREE.NoBlending, toneMapped: false,
    fragmentShader: 'uniform sampler2D map; varying vec2 vUv;\nvoid main() { gl_FragColor = vec4( texelFetch( map, ivec2( gl_FragCoord.xy ), 0 ).rgb, 1.0 ); }' });
  ptQuadDraw(m); m.dispose(); tex.dispose(); bmp.close?.();
}
const blobToDataURL = (b) => new Promise((res, rej) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.onerror = () => rej(fr.error); fr.readAsDataURL(b); });
async function ptFinalize(tag = '') {
  await serverProbe;
  const S = ptState, R = renderer, T = pt.target, W = T.width, H = T.height, t0 = performance.now();
  const info = { tag, spp: +pt.samples.toFixed(3), W, H, exposure: +R.toneMappingExposure.toFixed(4) };
  const col = new Float32Array(W * H * 4); R.readRenderTargetPixels(T, 0, 0, W, H, col);
  for (let k = 3; k < col.length; k += 4) col[k] = 1;
  info.readMs = Math.round(performance.now() - t0);
  const nan = S.fx.has('nan') ? ptNanGuard(col, W, H) : 0; info.nanFixed = nan;
  const fog = S.fx.has('fog') && S.fog?.isFogExp2 ? { color: [S.fog.color.r, S.fog.color.g, S.fog.color.b], density: S.fog.density } : null; info.fog = !!fog;
  const mode = ptDenoiseMode(S.denoise); info.requested = mode;
  const wantOidn = (mode === 'auto' && SERVER.ptDenoise) || (mode === 'oidn' && SERVER.serve);
  let aov = null;
  if (wantOidn || fog) { aov = ptRenderAOVs(W, H); info.aov = { passes: aov.passes, ms: aov.ms }; }
  let url = null;
  if (wantOidn) {
    const t1 = performance.now();
    try {
      ptSetStatus('Intel OIDN 降噪（serve.py）…');
      const tm = {}; info.t = tm;
      const r = await ptServerDenoise(col, aov, W, H, R.toneMappingExposure, fog, { spp: info.spp, name: S.name || null, nanFixedInViewer: nan, fixes: [...S.fx] }, tm);
      if (ptState !== S) return null;
      let t2 = performance.now(); await ptDrawPNG(r.blob); tm.drawMs = Math.round(performance.now() - t2);
      t2 = performance.now(); url = await blobToDataURL(r.blob); tm.dataUrlMs = Math.round(performance.now() - t2);
      info.method = 'oidn'; info.server = r.stats; info.denoiseMs = Math.round(performance.now() - t1);
    } catch (e) { info.serverError = String(e.message || e).slice(0, 300); console.warn('pt_denoise failed, falling back to DenoiseMaterial', info.serverError); }
  } else if (mode === 'oidn') info.serverError = SERVER.reason || 'no serve.py';
  if (!url) {
    const m = mode === 'raw' ? 'raw' : 'smart';
    if (fog && aov) ptApplyFog(col, aov, fog);
    url = ptDrawFloat(col, W, H, m); info.method = m === 'smart' && PTMOD?.DenoiseMaterial ? 'DenoiseMaterial' : 'raw';
    if (m === 'smart') info.smart = { ...PT_CFG.smart };
  }
  info.ms = Math.round(performance.now() - t0);
  return { url, info };
}
async function ptSave(url, name) {
  if (!url || !SERVER.serve) return null;
  try { const r = await fetch('save?name=' + encodeURIComponent(name), { method: 'POST', body: url }); return r.ok ? 'renders/' + name : null; } catch (e) { return null; }
}
function ptInjectNaN(px) {
  if (!pt) return 0; const gl = renderer.getContext(), T = pt.target, tp = renderer.properties.get(T.texture); if (!tp?.__webglTexture) return 0;
  renderer.state.bindTexture(gl.TEXTURE_2D, tp.__webglTexture);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  for (const [x, y] of px) gl.texSubImage2D(gl.TEXTURE_2D, 0, x, T.height - 1 - y, 1, 1, gl.RGBA, gl.FLOAT, new Float32Array([NaN, NaN, NaN, 1]));
  renderer.state.unbindTexture();
  return px.length;
}
function ptDisposeTracer(p) {
  const d = (o) => { try { o?.dispose?.(); } catch (e) {  } };
  for (const r of [p._pathTracer, p._lowResPathTracer]) {
    const m = r?.material;
    if (m?.uniforms) for (const [k, u] of Object.entries(m.uniforms)) { const v = u.value; if (!v || k === 'backgroundMap' || v === hdrCurrent?.tex || v === scene.background) continue; d(v); }
    d(m); d(r);
  }
  d(p._quad?.material); d(p._quad);
}
function ptLetterbox(W, H) {
  const a = W / H; let w = innerWidth, h = innerHeight; if (w / h > a) w = Math.round(h * a); else h = Math.round(w / a);
  Object.assign(renderer.domElement.style, { position: 'fixed', width: w + 'px', height: h + 'px', left: Math.round((innerWidth - w) / 2) + 'px', top: Math.round((innerHeight - h) / 2) + 'px' });
}
function ptSetStatus(t) { $('ptStatus').textContent = t; }
function ptWarn(html) { for (const id of ['ptWarn', 'ptWarnSide']) { $(id).innerHTML = html; $(id).style.display = html ? 'block' : 'none'; } }
function ptName(suffix = '') {
  const S = ptState; const base = S.name || `photoreal_${new Date(S.startedAt).toISOString().replace(/[-:T]/g, '').slice(0, 14)}.png`;
  return suffix ? base.replace(/\.png$/i, '') + suffix + '.png' : base;
}
async function startPathTrace(opts = {}) {
  if (ptState) return;
  const spp = +(opts.spp || $('ptSpp').value || 128);
  const fx = opts.fixes !== undefined ? ptParseFixes(Array.isArray(opts.fixes) ? opts.fixes.join(',') : opts.fixes) : new Set(PT_CFG.fixes);
  ptState = { spp, t0: performance.now(), startedAt: Date.now(), checked: false, done: false, busy: false, name: opts.name || null, auto: !!opts.auto, W: opts.W, H: opts.H,
    pr: renderer.getPixelRatio(), result: null, lastLog: 0, onDone: opts.onDone, fx, denoise: opts.denoise || null, debug: !!opts.debug,
    checkpoints: (opts.checkpoints || []).map(Number).filter((c) => c > 0 && c < spp).sort((a, b) => a - b), cpResults: [],
    injectNaN: opts.injectNaN ? { spp: +opts.injectNaN.spp || 1, px: opts.injectNaN.px || [], done: false } : null };
  syncLightUI();
  $('ptBar').style.display = 'flex'; $('ptSave').disabled = true; ptWarn(''); $('ptStart').disabled = true;
  ptSetStatus('载入路径追踪库…');
  try {
    ptShim();
    PTMOD = await import('three-gpu-pathtracer'); const { WebGLPathTracer } = PTMOD;
    if (opts.view) goView(opts.view, 0);
    tween = null;
    if (!ptState.W || !ptState.H) { const [W, H] = ptSizeFor(opts.size); ptState.W = W; ptState.H = H; ptState.uiSize = !opts.size; }
    setRenderSize(ptState.W, ptState.H); ptLetterbox(ptState.W, ptState.H);
    ptState.estS = ptState.W * ptState.H * spp / PT_RATE;
    ptPrepareScene(fx);
    ptSetStatus('构建 BVH（约 10–15 s）…');
    await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 30)));
    pt = new WebGLPathTracer(renderer);
    const k = opts.tiles ? [].concat(opts.tiles) : [ptTilesFor(ptState.W, ptState.H)];
    pt.tiles.set(+k[0], +(k[1] ?? k[0])); pt.bounces = PT_CFG.bounces; pt.filterGlossyFactor = PT_CFG.glossy; pt.renderScale = 1; pt.dynamicLowRes = false; pt.minSamples = 1;
    if (fx.has('tex2k')) pt.textureSize.set(PT_CFG.texSize, PT_CFG.texSize);
    ptState.random = opts.random || PT_CFG.random || (fx.has('sobol') ? 'sobol' : 'stratified');
    { const RT = { stratified: 2, sobol: 1, pcg: 0 }[ptState.random]; const m = pt._pathTracer?.material; if (m?.setDefine && RT !== undefined) m.setDefine('RANDOM_TYPE', RT); }
    if ('renderDelay' in pt) pt.renderDelay = 0;
    if ('fadeDuration' in pt) pt.fadeDuration = 0;
    const tb = performance.now(); pt.setScene(scene, camera); ptState.bvhS = (performance.now() - tb) / 1000;
    ptState.t1 = performance.now();
    ptSetStatus(`BVH ${ptState.bvhS.toFixed(1)} s · 编译着色器（首次约 1–2 分钟）… · ${ptState.W}×${ptState.H} / ${spp} spp 预计约 ${fmtMin(ptState.estS)}`);
    renderer.setAnimationLoop(ptTick);
  } catch (e) {
    console.warn('path tracer failed', e); ptWarn('路径追踪启动失败：' + e.message); const r = { error: e.message }; stopPathTrace(); ptLast = r; return r;
  }
}
let ptLast = null;
function ptTick() {
  const S = ptState; if (!S || !pt) return;
  if (S.done || S.paused || S.busy) return;
  controls.update();
  pt.renderSample();
  const s = pt.samples; const now = performance.now();
  if (s >= 1 && !S.tFirst) S.tFirst = now;
  if (S.injectNaN && !S.injectNaN.done && s >= S.injectNaN.spp) { S.injectNaN.n = ptInjectNaN(S.injectNaN.px); S.injectNaN.done = true; }
  if (now - S.lastLog > 400) { S.lastLog = now; ptSetStatus(s < 1 ? `编译着色器… ${((now - S.t1) / 1000).toFixed(0)} s（首次约 1–2 分钟）` : `路径追踪 ${s.toFixed(0)} / ${S.spp} spp · ${((now - S.t1) / 1000).toFixed(0)} s`); }
  if (!S.checked && s >= 8) {
    S.checked = true; const c = ptOutputLooksBroken(); S.check = c;
    if (c.broken) {
      ptWarn('画面几乎全黑 / 全白：这通常是 Chrome/Edge 默认 ANGLE D3D11 后端在部分集成显卡上的着色器编译错误（与模型无关）。请用 <code>--use-angle=vulkan</code> 启动浏览器（或在 <code>chrome://flags/#use-angle</code> 选 Vulkan）后重试。<br><button id="ptContinue">仍然继续</button>');
      S.paused = true; const b = $('ptContinue'); if (b) b.onclick = () => { S.paused = false; ptWarn(''); };
      if (S.auto) { S.done = true; finishPathTrace(false); }
      return;
    }
  }
  if (S.checkpoints.length && s >= S.checkpoints[0] && s < S.spp) { ptGpuSync(); ptCheckpoint(S.checkpoints.shift(), s); return; }
  if (s >= S.spp) { S.done = true; if (S.debug) S.rawCanvas = renderer.domElement.toDataURL('image/png'); ptGpuSync(); S.tDone = performance.now(); finishPathTrace(true); }
}
function ptGpuSync() { try { renderer.readRenderTargetPixels(pt.target, 0, 0, 1, 1, new Float32Array(4)); } catch (e) {  } }
function ptTiming(S, s, now) {
  const p = S.pauseMs || 0, trace = (now - S.t1 - p) / 1000, first = S.tFirst ? (S.tFirst - S.t1) / 1000 : null;
  const rate = S.tFirst && s > 1 ? S.W * S.H * (s - 1) / ((now - S.tFirst - p) / 1000) / 1e6 : null;
  return { seconds: +trace.toFixed(1), firstS: first === null ? null : +first.toFixed(2), rateMpxSpp: rate === null ? null : +rate.toFixed(4) };
}
async function ptCheckpoint(cp, s) {
  const S = ptState; S.busy = true; const now = performance.now();
  const e = { cp, spp: +s.toFixed(3), ...ptTiming(S, s, now) };
  try {
    ptSetStatus(`检查点 ${cp} spp：读出、降噪…`);
    const r = await ptFinalize(`_${cp}spp`); if (!r || ptState !== S) return;
    e.denoise = r.info; e.name = ptName(`_${cp}spp`); e.saved = await ptSave(r.url, e.name);
  } catch (err) { e.error = String(err.message || err); console.warn('checkpoint', err); }
  finally { S.cpResults.push(e); S.pauseMs = (S.pauseMs || 0) + (performance.now() - now); e.outputMs = Math.round(performance.now() - now); if (ptState === S) S.busy = false; }
}
async function finishPathTrace(ok) {
  const S = ptState; const now = S.tDone || performance.now(); const s = pt ? pt.samples : 0;
  S.result = { spp: +s.toFixed(3), ...ptTiming(S, s, now), estS: +(S.estS || 0).toFixed(0), bvhS: +(S.bvhS || 0).toFixed(1), check: S.check,
    W: renderer.domElement.width, H: renderer.domElement.height, tiles: pt ? [pt.tiles.x, pt.tiles.y] : null, textureSize: pt ? pt.textureSize.x : null,
    broken: !ok, random: S.random, sun: S.sunMode, env: +(scene.environmentIntensity ?? 1).toFixed(3), exposure: +renderer.toneMappingExposure.toFixed(4), fixes: [...S.fx], fixInfo: S.fixInfo,
    injectNaN: S.injectNaN ? { spp: S.injectNaN.spp, px: S.injectNaN.px, written: S.injectNaN.n ?? 0 } : null };
  if (ok) {
    S.busy = true;
    try {
      ptSetStatus('读出浮点结果、降噪…');
      const r = await ptFinalize(''); if (!r || ptState !== S) return;
      S.url = r.url; S.result.denoise = r.info;
    } catch (e) { console.warn('path tracer output', e); S.result.outputError = String(e.message || e); S.url = S.rawCanvas || null; }
    S.busy = false;
  }
  if (S.url) {
    $('ptSave').disabled = false;
    const name = ptName(); S.result.name = name; S.result.saved = await ptSave(S.url, name);
    const d = S.result.denoise; const dz = d ? (d.method === 'oidn' ? 'OIDN 降噪' : d.method === 'DenoiseMaterial' ? 'DenoiseMaterial 降噪' : '未降噪') + (d.nanFixed ? ` · 修补 NaN ${d.nanFixed} 像素` : '') : '';
    ptSetStatus(`完成 ${S.result.spp.toFixed(0)} spp · ${S.result.seconds.toFixed(0)} s · ${S.result.W}×${S.result.H} · ${dz}${S.result.saved ? ' · 已存 ' + S.result.saved : ''}`);
    if (!S.auto) downloadURL(S.url, name);
  }
  S.result.checkpoints = S.cpResults;
  if (S.debug) { S.result.rawCanvas = S.rawCanvas || null; S.result.finalUrl = S.url || null; }
  ptLast = S.result;
  if (S.onDone) S.onDone(S.result);
}
function downloadURL(url, name) { const a = document.createElement('a'); a.download = name; a.href = url; a.click(); }
function stopPathTrace() {
  if (!ptState) return;
  renderer.setAnimationLoop(null);
  try { ptRestoreScene(); } catch (e) { console.warn(e); }
  if (pt) { ptDisposeTracer(pt); pt = null; }
  const pr = ptState.pr; ptState = null;
  renderer.setRenderTarget(null); restoreRenderSize(pr); syncLightUI();
  $('ptBar').style.display = 'none'; $('ptStart').disabled = false;
  shadowDirty = true; markDirty(1500);
  renderer.setAnimationLoop(tick);
}
$('ptStart').onclick = () => startPathTrace({});
for (const id of ['ptSpp', 'ptSize', 'ptDen']) if ($(id)) $(id).onchange = updatePtEstimate;
addEventListener('resize', updatePtEstimate);
$('ptExit').onclick = () => stopPathTrace();
$('ptSave').onclick = () => { if (ptState?.url) downloadURL(ptState.url, ptState.result?.name || 'photoreal.png'); };
controls.addEventListener('change', () => { if (pt && ptState && !ptState.done && !ptState.busy) pt.updateCamera(); });
window.__ptShot = (view, name, W = 1280, H = 720, spp = 128, opts = {}) => new Promise((resolve) => {
  startPathTrace({ ...opts, view, name, W, H, spp, auto: true, onDone: (r) => { stopPathTrace(); resolve(r); } }).then((r) => { if (r && r.error) resolve(r); });
});

// ---------------- loop ----------------
let frames = 0, lastT = performance.now(), fps = 0;
function render() { if (!innerWidth || !innerHeight) return; camera.updateProjectionMatrix(); composer.render(); labelRenderer.render(scene, camera); declutterLabels(); }
function tick(now) {
  if (shotLock) return;
  if (tween) {
    const t = Math.min(1, (now - tween.t0) / tween.ms), k = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    camera.position.lerpVectors(tween.p0, tween.p1, k); controls.target.lerpVectors(tween.t0v, tween.t1, k);
    movingUntil = now + 160; markDirty(900);
    if (t >= 1) { tween = null; updateSun(); }
  }
  controls.update();
  syncSunToTarget();
  const bearing = Math.atan2(controls.target.x - camera.position.x, -(controls.target.z - camera.position.z));
  $('needle').setAttribute('transform', `rotate(${(-bearing * 180 / Math.PI).toFixed(1)})`);
  const moving = now < movingUntil;
  if (moving || shadowDirty || now < dirtyUntil) {
    if (gtao) gtao.enabled = $('ao').checked && !moving;
    if (shadowDirty && sun.castShadow) renderer.shadowMap.needsUpdate = true;
    shadowDirty = false;
    render(); frames++; renderCount++;
  }
  if (now - lastT > 1000) {
    if (frames) fps = frames * 1000 / (now - lastT);
    $('stats').textContent = `CAD+场地 ${Math.round(triCount).toLocaleString()} 三角面 · ${frames ? fps.toFixed(0) + ' fps' : '静止（不重绘，上次 ' + fps.toFixed(0) + ' fps）'} · HDRI Poly Haven (CC0)`;
    frames = 0; lastT = now;
  }
}
for (const ev of ['pointerdown', 'pointerup', 'wheel', 'keydown', 'click']) addEventListener(ev, () => markDirty(), true);
for (const ev of ['input', 'change']) addEventListener(ev, () => { shadowDirty = true; markDirty(); }, true);
addEventListener('pointermove', (e) => { if (e.buttons) markDirty(); }, true);
addEventListener('resize', () => markDirty(1000));
controls.addEventListener('change', () => { movingUntil = performance.now() + 160; markDirty(900); });
// headless still renders own the canvas; the interactive loop pauses meanwhile. window.__shots([[view, 'name.png'], ...], W, H)
let shotLock = false;
window.__shots = async (list, W = 2400, H = 1500) => {
  shotLock = true; try { return await shotsImpl(list, W, H); } finally { shotLock = false; markDirty(1000); }
};
async function shotsImpl(list, W, H) {
  const oldPR = renderer.getPixelRatio();
  setRenderSize(W, H);
  labelGroup.visible = false; labelRenderer.domElement.style.display = 'none';
  const out = [];
  for (const [view, name] of list) {
    goView(view, 0); tween = null;
    if (gtao) gtao.enabled = $('ao').checked;
    for (let i = 0; i < 3; i++) { controls.update(); syncSunToTarget(true); renderer.shadowMap.needsUpdate = true; composer.render(); await new Promise((r) => setTimeout(r, 30)); }
    composer.render(); const url = renderer.domElement.toDataURL('image/png');
    await fetch('save?name=' + encodeURIComponent(name), { method: 'POST', body: url }); out.push(name);
  }
  restoreRenderSize(oldPR);
  labelGroup.visible = $('showLbl').checked; labelRenderer.domElement.style.display = $('showLbl').checked ? '' : 'none';
  return out;
}
// debug / automation handle
window.__v = {
  THREE, renderer, scene, camera, controls, groupBoxes, render: () => render(), layout, updateSun, goView, VIEWS,
  setHDRI, setOutline, setCanopyTop, setCanopyScheme, startPathTrace, stopPathTrace, LIB, extMeshes, canopyTopMeshes, canopyCladMeshes, light, syncLightUI, PARAMS,
  get ptLast() { return ptLast; }, composer: () => composer, gtao: () => gtao, smaa: () => smaa, outline: () => outline,
  get renderCount() { return renderCount; }, get platformDeck() { return platformDeck; }, markDirty,
  sun, SHADOW_OPTS, setShadowSoftness, HDRIS, HDG_CAL, CANOPY_SCHEMES, canopyFinishState,
  get hdr() { return hdrCurrent; }, DECLUTTER,
  PT_CFG, SERVER, serverProbe, ptInjectNaN, get ptState() { return ptState; }, get pt() { return pt; }, MATDB: () => MATDB, matZh, writeMaterialTexts,
};
main().catch((e) => { $('loadtxt').textContent = '载入失败：' + e.message; console.error(e); });

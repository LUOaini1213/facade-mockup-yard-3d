/* Real viewer function bodies, isolated from WebGL. Only asynchronous I/O and
 * GPU boundaries are fakes, so cancellation order can be exercised without a
 * multi-minute render. FACADE_VIEWER_SOURCE supports the saved pre-fix source. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(process.env.FACADE_VIEWER_SOURCE || path.join(__dirname, '..', 'viewer.js'), 'utf8');
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
class Vec {
  constructor(...v) { this.v = v; }
  clone() { return new Vec(...this.v); }
  copy(other) { this.v = [...other.v]; return this; }
  set(...v) { this.v = v; return this; }
}
function body(name) {
  const assignment = name.startsWith('__');
  const start = assignment ? source.indexOf(`window.${name} =`) : source.search(new RegExp(`^(?:async )?function ${name}\\(`, 'm'));
  if (start < 0) return '';
  const end = source.indexOf(assignment ? '\n};' : '\n}', start);
  assert.ok(end > start, `function boundary for ${name}`);
  return source.slice(start, end + (assignment ? 3 : 2)).replace("import('three-gpu-pathtracer')", 'loadPathTracerModule()');
}
function context(names, overrides = {}) {
  const elements = new Map();
  const el = id => { if (!elements.has(id)) elements.set(id, { value: '128', checked: true, disabled: false, style: {}, classList: { toggle() {} } }); return elements.get(id); };
  const counters = { prepared: 0, constructed: 0, restored: 0, draws: 0, downloads: 0, warnings: 0, statuses: [], saves: [] };
  class Tracer { constructor() { counters.constructed++; this.tiles = { set() {} }; this.textureSize = { set() {} }; } setScene() {} }
  const renderer = { pr: 2, size: [800, 600], getPixelRatio() { return this.pr; }, setAnimationLoop(f) { this.loop = f; }, setRenderTarget() {}, shadowMap: {}, toneMappingExposure: 1,
    domElement: { width: 800, height: 600, toDataURL: () => 'data:image/png;base64,AAAA' }, readRenderTargetPixels() {} };
  const camera = { position: new Vec(1, 2, 3), up: new Vec(0, 1, 0), fov: 45, lookAt() {}, updateMatrixWorld() {}, updateProjectionMatrix() {} };
  const c = { console: { warn() { counters.warnings++; } }, performance: { now: () => 100 }, Date, Set, Map, Float32Array,
    window: {}, pt: null, ptState: null, ptLast: null, PTMOD: null, shotLock: false, tween: null, shadowDirty: false, lastSunInput: null,
    ptActive: () => !!c.ptState,
    $: el, renderer, camera, controls: { target: new Vec(4, 5, 6), enabled: true, update() {} },
    scene: { fog: { density: .001 }, environment: {}, environmentIntensity: 1 },
    PT_CFG: { fixes: [], bounces: 3, gloss: 1, random: null }, PT_RATE: 100,
    ptSwaps: [], vegInstanced: [], hdrCurrent: null, sun: { visible: true, castShadow: true },
    labelRenderer: { domElement: { style: { display: '' } } }, labelGroup: { visible: true, children: [] }, ctxRoot: { visible: true }, surrGroup: { visible: true }, vegGroup: { visible: true },
    THREE: { Vector3: Vec, Texture: class { dispose() {} }, ShaderMaterial: class { dispose() {} } },
    PT_VS: '', composer: { render() {} }, gtao: { enabled: true },
    loadPathTracerModule: async () => ({ WebGLPathTracer: Tracer }),
    ptPrepareScene() { counters.prepared++; }, ptRestoreScene() { counters.restored++; },
    ptDisposeTracer() {}, ptShim() {}, ptParseFixes: () => new Set(), ptSizeFor: () => [64, 64], ptLetterbox() {}, ptTilesFor: () => 1,
    syncLightUI() {}, updateSun() {}, syncSunToTarget() {}, markDirty() {}, ptTick() {}, tick() {}, fmtMin: String,
    ptWarn() {}, ptSetStatus(t) { counters.statuses.push(t); },
    setRenderSize(w, h) { renderer.pr = 1; renderer.size = [w, h]; }, restoreRenderSize(pr) { renderer.pr = pr; renderer.size = [800, 600]; },
    requestAnimationFrame: f => f(), setTimeout: f => f(),
    goView() { camera.position.set(9, 9, 9); c.controls.target.set(8, 8, 8); },
    fetch: async (url) => { counters.saves.push(url); return { ok: true, status: 200 }; },
    serverProbe: Promise.resolve(), SERVER: { ptDenoise: true, serve: true },
    ptDenoiseMode: () => 'auto', ptRenderAOVs: () => ({ passes: 1, ms: 1 }), ptApplyFog() {},
    ptQuadDraw() { counters.draws++; }, ptDrawFloat() { counters.draws++; return 'fallback'; },
    blobToDataURL: async () => 'data:image/png;base64,AAAA',
    downloadURL() { counters.downloads++; }, ptTiming: () => ({ seconds: 1 }), ptName: () => 'test.png',
    ...overrides,
  };
  const optional = ['captureExportState', 'restoreExportState', 'saveScreenshot', 'settlePathTrace', 'parseSunDate', 'setSceneLabels', 'loadOptionalGLB'];
  const loaded = [...new Set([...optional, ...names])].filter(n => body(n));
  vm.createContext(c);
  vm.runInContext(loaded.map(body).join('\n') + '\nglobalThis.api = {' + loaded.filter(n => !n.startsWith('__')).join(',') + '};', c);
  return { c, counters, el, Tracer };
}
test('cancel while module loads does not prepare or construct a tracer', async () => {
  const pending = deferred();
  const { c, counters, Tracer } = context(['startPathTrace', 'stopPathTrace'], { loadPathTracerModule: () => pending.promise });
  const result = c.api.startPathTrace(); c.api.stopPathTrace();
  pending.resolve({ WebGLPathTracer: Tracer });
  assert.equal((await result).cancelled, true);
  assert.equal(counters.prepared, 0); assert.equal(counters.constructed, 0); assert.equal(counters.warnings, 0);
});
test('late module failure from cancelled task cannot stop its replacement', async () => {
  const old = deferred(), current = deferred(); let calls = 0;
  const { c, Tracer } = context(['startPathTrace', 'stopPathTrace'], { loadPathTracerModule: () => (++calls === 1 ? old : current).promise });
  const first = c.api.startPathTrace(); c.api.stopPathTrace();
  const second = c.api.startPathTrace(); const owner = c.ptState;
  old.reject(new Error('old module failed')); await first;
  assert.equal(c.ptState, owner);
  current.resolve({ WebGLPathTracer: Tracer }); await second;
  assert.equal(c.ptState, owner);
});
test('cancel during preparation frame cannot create an orphan tracer', async () => {
  let frame;
  const { c, counters } = context(['startPathTrace', 'stopPathTrace'], { requestAnimationFrame: f => { frame = f; } });
  const result = c.api.startPathTrace(); await flush();
  assert.equal(counters.prepared, 1); c.api.stopPathTrace(); frame();
  assert.equal((await result).cancelled, true); assert.equal(counters.constructed, 0); assert.equal(c.pt, null);
});
test('exit before preparation preserves the real-time fog', () => {
  const { c } = context(['ptRestoreScene', 'stopPathTrace']);
  const fog = c.scene.fog; c.ptState = { pr: 2 };
  c.api.stopPathTrace(); assert.equal(c.scene.fog, fog);
});
test('cancelled automatic shot settles exactly once', async () => {
  const pending = deferred(); let completed = 0;
  const { c, Tracer } = context(['startPathTrace', 'stopPathTrace'], { loadPathTracerModule: () => pending.promise });
  const run = c.api.startPathTrace({ onDone: r => { assert.equal(r.cancelled, true); completed++; } });
  c.api.stopPathTrace(); c.api.stopPathTrace(); pending.resolve({ WebGLPathTracer: Tracer }); await run;
  assert.equal(completed, 1);
});
test('late denoiser rejection cannot paint over a replacement session', async () => {
  const pending = deferred();
  const { c, counters } = context(['ptFinalize'], { ptServerDenoise: () => pending.promise });
  c.ptState = { fx: new Set(), denoise: 'auto' }; c.pt = { target: { width: 1, height: 1 }, samples: 1 };
  const result = c.api.ptFinalize(); await flush(); c.ptState = { replacement: true };
  pending.reject(new Error('old server request failed'));
  assert.equal(await result, null); assert.equal(counters.draws, 0);
});
test('late bitmap decoding releases pixels without drawing stale output', async () => {
  const pending = deferred(); let closed = 0;
  const { c, counters } = context(['ptDrawPNG'], { createImageBitmap: () => pending.promise });
  const old = c.ptState = {};
  const result = c.api.ptDrawPNG({}, old); c.ptState = {};
  pending.resolve({ close() { closed++; } }); await result;
  assert.equal(counters.draws, 0); assert.equal(closed, 1);
});
test('late save completion cannot download or announce a cancelled session', async () => {
  const pending = deferred(); let notified = 0;
  const { c, counters } = context(['finishPathTrace'], { ptFinalize: async () => ({ url: 'png', info: {} }), ptSave: () => pending.promise });
  c.pt = { samples: 4, tiles: { x: 1, y: 1 }, textureSize: { x: 64 } };
  c.ptState = { fx: new Set(), cpResults: [], onDone: () => { notified++; } };
  const result = c.api.finishPathTrace(true); await flush(); c.ptState = { replacement: true };
  pending.resolve('renders/test.png'); await result;
  assert.equal(counters.downloads, 0); assert.equal(notified, 0);
  assert.equal(counters.statuses.some(t => t.startsWith('完成')), false);
});
test('batch export restores size and labels after network rejection', async () => {
  const { c } = context(['shotsImpl', '__shots'], { fetch: async () => { throw new Error('offline'); } });
  await assert.rejects(c.window.__shots([['overview', 'test.png']], 1600, 1000), /offline/);
  assert.equal(c.renderer.pr, 2); assert.deepEqual(c.renderer.size, [800, 600]);
  assert.equal(c.labelGroup.visible, true); assert.equal(c.labelRenderer.domElement.style.display, ''); assert.equal(c.shotLock, false);
});
for (const type of ['batch', 'pose']) {
  test(`${type} export rejects HTTP failures and restores state`, async () => {
    const { c } = context(['shotsImpl', '__shots', '__poseShot'], { fetch: async () => ({ ok: false, status: 409 }) });
    const run = type === 'batch' ? c.window.__shots([['overview', 'test.png']], 1600, 1000)
      : c.window.__poseShot({ pos: [10, 20, 30], target: [0, 0, 0] }, 'test.png', 1600, 1000);
    await assert.rejects(run, /409/); assert.equal(c.renderer.pr, 2); assert.equal(c.shotLock, false);
  });
  test(`${type} export only opts into overwrite when explicitly true`, async () => {
    const { c, counters } = context(['shotsImpl', '__shots', '__poseShot']);
    for (const overwrite of [undefined, 'true', true]) {
      const opts = { overwrite };
      if (type === 'batch') await c.window.__shots([['overview', 'test name.png']], 1600, 1000, opts);
      else await c.window.__poseShot({ pos: [10, 20, 30], target: [0, 0, 0] }, 'test name.png', 1600, 1000, opts);
    }
    assert.equal(counters.saves[0].includes('overwrite='), false); assert.equal(counters.saves[1].includes('overwrite='), false);
    assert.equal(counters.saves[2], 'save?name=test%20name.png&overwrite=1');
  });
}
test('overlapping exports and export during path tracing are rejected', async () => {
  const { c } = context(['shotsImpl', '__shots', '__poseShot']);
  c.ptState = {}; c.ptActive = () => !!c.ptState;
  await assert.rejects(c.window.__shots([]), /path trac|busy/i);
  c.ptState = null; c.shotLock = true;
  await assert.rejects(c.window.__poseShot({ pos: [1, 2, 3], target: [0, 0, 0] }, 'test.png'), /busy/i);
});
function sunContext(names = []) {
  return context(['sunPosition', 'updateSun', ...names], {
    SITE: { lat: 1.3, lon: 103.8, tz: 8 }, sunAlt: 1, sunAz: 2,
    sunDir: { set(...values) { this.values = values; } },
    light: { hdri: 'overcast', sunK: null }, HDRIS: { overcast: { sun: .35, sunK0: 4200, sunK1: 1800 } }, SUN_FULL: 4.2,
    kelvinRGB: () => [1, 1, 1], sun: { intensity: 2, color: { setRGB() {} } },
    fallbackSky: null, scheduleSkyAlign() {},
  });
}
test('clearing or partially editing the date preserves finite existing lighting', () => {
  for (const value of ['', '2027-02-', '2027-02-30']) {
    const { c, el } = sunContext(); el('date').value = value; el('time').value = '600';
    c.api.updateSun();
    assert.equal(c.sun.intensity, 2); assert.equal(c.sunAlt, 1); assert.equal(c.sunAz, 2);
    assert.equal(el('sunval').textContent.includes('NaN'), false);
  }
});
test('invalid URL date selects the explicit default and valid leap day is retained', () => {
  for (const [input, expected] of [['invalid', '2027-03-21'], ['2027-02-30', '2027-03-21'], ['2028-02-29', '2028-02-29']]) {
    const { c, el } = sunContext(); c.Q = new URLSearchParams({ date: input });
    let start = source.indexOf('const DEFAULT_SUN_DATE');
    if (start < 0) start = source.indexOf("$('date').value =");
    vm.runInContext(source.slice(start, source.indexOf('const light =', start)), c);
    assert.equal(el('date').value, expected);
    c.api.updateSun(); assert.ok(Number.isFinite(c.sun.intensity)); assert.ok(Number.isFinite(c.sunAlt));
  }
});
test('hiding scene labels does not hide measurement readouts', () => {
  const { c, el } = context([]);
  vm.runInContext(source.split('\n').find(line => line.startsWith("$('showLbl').onchange =")), c);
  el('showLbl').onchange({ target: { checked: false } });
  assert.equal(c.labelGroup.visible, false);
  assert.notEqual(c.labelRenderer.domElement.style.display, 'none');
});
test('an optional GLB decode failure is recorded as incomplete loading', async () => {
  const { c } = context([], {
    loaded: { files: [], skipped: [], failed: [] },
    loadGLB: async (_url, key) => { if (key === 'cad') return {}; throw new Error('invalid GLB'); },
  });
  const start = source.indexOf('  const jobs = { cad:');
  const code = source.slice(start, source.indexOf('  const res =', start));
  const result = await vm.runInContext('(async () => { const opt = {vmu02: "broken.glb"};' + code + 'return await jobs.vmu02; })()', c);
  assert.equal(result, null); assert.equal(c.loaded.failed.length, 1);
  assert.equal(c.loaded.failed[0].file, 'vmu02.glb'); assert.equal(c.loaded.skipped.includes('vmu02.glb'), true);
});
test('valid dates update lighting again after an incomplete edit', () => {
  const { c, el } = sunContext(); el('time').value = '600'; el('date').value = '2028-02-29';
  c.api.updateSun(); const first = c.sunAlt;
  el('date').value = ''; c.api.updateSun(); assert.equal(c.sunAlt, first);
  el('date').value = '2028-06-21'; c.api.updateSun();
  assert.ok(Number.isFinite(c.sunAlt)); assert.notEqual(c.sunAlt, first);
  assert.equal(el('sunval').textContent.includes('保留'), false);
});
test('calendar validation rejects impossible days and retains early ISO years', () => {
  const { c } = sunContext();
  for (const value of ['0000-01-01', '2027-02-29', '2028-04-31', '2027-13-01', '2027-2-1']) assert.equal(c.api.parseSunDate(value), null);
  assert.equal(c.api.parseSunDate('0099-01-01').getUTCFullYear(), 99);
  assert.equal(c.api.parseSunDate('2028-02-29').getUTCDate(), 29);
});
test('leaving photo mode preserves measurement visibility with scene labels off', () => {
  const { c, el } = context(['ptRestoreScene', 'stopPathTrace']);
  const measurement = { visible: false }; el('showLbl').checked = false;
  c.labelGroup.visible = false; c.labelRenderer.domElement.style.display = 'none';
  c.ptState = { pr: 2, hidden: [[c.labelGroup, true], [measurement, true]] };
  c.api.stopPathTrace();
  assert.equal(c.labelGroup.visible, false); assert.equal(measurement.visible, true);
  assert.equal(c.labelRenderer.domElement.style.display, '');
});
test('optional model warning is attached visibly with the failed filenames', () => {
  let inserted;
  const side = { querySelector: () => null, insertBefore(el) { inserted = el; } };
  const { c } = context(['showModelWarnings'], {
    loaded: { skipped: ['vmu02.glb', 'site_ground.glb'] },
    $: id => id === 'side' ? side : inserted || null,
    document: { createElement: () => ({ style: {}, attributes: {}, setAttribute(k, v) { this.attributes[k] = v; } }) },
  });
  c.api.showModelWarnings();
  assert.equal(inserted.style.display, 'block'); assert.equal(inserted.attributes.role, 'status');
  assert.match(inserted.textContent, /模型加载不完整/);
  assert.match(inserted.textContent, /vmu02\.glb/); assert.match(inserted.textContent, /site_ground\.glb/);
});
test('successful optional loading returns the scene without an incomplete warning', async () => {
  const scene = { loaded: true };
  const { c } = context(['showModelWarnings'], {
    loaded: { files: [], skipped: [], failed: [] }, loadGLB: async () => scene,
    document: { createElement() { assert.fail('no warning for a complete load'); } },
  });
  assert.equal(await c.api.loadOptionalGLB('vmu02.glb', 'vmu02'), scene);
  assert.equal(c.loaded.skipped.length, 0); assert.equal(c.loaded.failed.length, 0);
  c.api.showModelWarnings();
});
test('successful batch exports restore the prior pose, size and label settings', async () => {
  const { c } = context(['shotsImpl', '__shots']);
  c.labelGroup.visible = false; c.controls.enabled = false;
  const result = await c.window.__shots([['overview', 'first.png'], ['top', 'second.png']], 1200, 750);
  assert.equal(result.join(','), 'first.png,second.png');
  assert.deepEqual(c.camera.position.v, [1, 2, 3]); assert.deepEqual(c.controls.target.v, [4, 5, 6]);
  assert.equal(c.renderer.pr, 2); assert.equal(c.labelGroup.visible, false); assert.equal(c.controls.enabled, false);
});
test('a live path trace starts normally and successful output settles only once', async () => {
  let notified = 0;
  const { c, counters } = context(['startPathTrace', 'stopPathTrace', 'finishPathTrace'], {
    ptFinalize: async () => ({ url: 'png', info: {} }), ptSave: async () => 'renders/test.png',
  });
  await c.api.startPathTrace({ auto: true, onDone: r => { assert.equal(r.saved, 'renders/test.png'); notified++; c.api.stopPathTrace(); } });
  assert.equal(counters.prepared, 1); assert.equal(counters.constructed, 1); assert.equal(c.renderer.loop, c.ptTick);
  c.pt.samples = 4; c.pt.tiles.x = c.pt.tiles.y = 1; c.pt.textureSize.x = 64;
  await c.api.finishPathTrace(true);
  assert.equal(notified, 1); assert.equal(c.ptState, null); assert.equal(counters.downloads, 0);
  assert.equal(c.renderer.loop, c.tick);
});
test('late successful module loading cannot prepare the replacement session twice', async () => {
  const old = deferred(), current = deferred(); let calls = 0;
  const { c, counters, Tracer } = context(['startPathTrace', 'stopPathTrace'], { loadPathTracerModule: () => (++calls === 1 ? old : current).promise });
  const first = c.api.startPathTrace(); c.api.stopPathTrace();
  const second = c.api.startPathTrace(); const owner = c.ptState;
  old.resolve({ WebGLPathTracer: Tracer }); await first;
  assert.equal(c.ptState, owner); assert.equal(counters.prepared, 0);
  current.resolve({ WebGLPathTracer: Tracer }); await second;
  assert.equal(counters.prepared, 1); assert.equal(counters.constructed, 1);
});

test('resize during a pending batch preserves export dimensions and restores the latest window size', async () => {
  const pending = deferred(), snapshots = []; let onResize, saves = 0;
  const { c } = context(['shotsImpl', '__shots', 'layout'], {
    innerWidth: 800, innerHeight: 600,
    addEventListener(name, listener) { assert.equal(name, 'resize'); onResize = listener; },
    fetch: () => ++saves === 1 ? pending.promise : Promise.resolve({ ok: true, status: 200 }),
  });
  c.renderer.setSize = (w, h) => { c.renderer.size = [w, h]; };
  c.renderer.domElement.style = {};
  c.renderer.domElement.toDataURL = () => { snapshots.push([...c.renderer.size]); return 'png'; };
  c.labelRenderer.setSize = () => {};
  c.composer.setPixelRatio = c.composer.setSize = () => {};
  c.restoreRenderSize = pr => { c.renderer.pr = pr; c.api.layout(); };
  vm.runInContext(source.split('\n').find(line => line.startsWith("addEventListener('resize'")), c);
  const run = c.window.__shots([['overview', 'first.png'], ['top', 'second.png']], 1200, 750);
  await flush(); assert.equal(saves, 1);
  c.innerWidth = 1000; c.innerHeight = 800; onResize();
  assert.deepEqual(c.renderer.size, [1200, 750]);
  pending.resolve({ ok: true, status: 200 }); await run;
  assert.deepEqual(snapshots, [[1200, 750], [1200, 750]]);
  assert.deepEqual(c.renderer.size, [1000, 800]); assert.equal(c.camera.aspect, 1.25);
  c.innerWidth = 900; onResize(); assert.deepEqual(c.renderer.size, [900, 800]);
});

test('pose export restores the last valid sunlight while the date editor is empty', async () => {
  const { c, el } = sunContext(['__poseShot']);
  el('date').value = '2027-03-21'; el('time').value = '600';
  c.api.updateSun(); const before = [c.sunAlt, c.sunAz, c.sun.intensity];
  el('date').value = ''; c.api.updateSun();
  await c.window.__poseShot({ pos: [10, 20, 30], target: [0, 0, 0] }, 'test.png', 1200, 750, { date: '2028-06-21', t: 720 });
  assert.equal(el('date').value, ''); assert.equal(el('time').value, '600');
  assert.deepEqual([c.sunAlt, c.sunAz, c.sun.intensity], before);
  assert.match(el('sunval').textContent, /保留/);
});

test('vendored CSS2DRenderer hides scene labels independently of measurement labels', async () => {
  // Use the actual renderer and Three scene graph: r160 CSS2D visibility does
  // not inherit Group.visible. The DOM boundary alone is an in-memory fixture.
  const threeSource = fs.readFileSync(path.join(__dirname, '..', 'vendor', 'three.module.js'), 'utf8');
  const THREE = await import('data:text/javascript;base64,' + Buffer.from(threeSource).toString('base64'));
  const element = () => ({ style: {}, dataset: {}, parentNode: null, setAttribute() {},
    appendChild(child) { child.parentNode = this; }, getBoundingClientRect: () => ({ left: 10, top: 10, right: 60, bottom: 30, width: 50, height: 20 }) });
  const rendererSource = fs.readFileSync(path.join(__dirname, '..', 'vendor', 'jsm', 'renderers', 'CSS2DRenderer.js'), 'utf8')
    .replace(/import\s*\{([\s\S]*?)\}\s*from 'three';/, 'const {$1} = THREE;')
    .replace('export { CSS2DObject, CSS2DRenderer };', 'globalThis.css2d = { CSS2DObject, CSS2DRenderer };');
  const { c } = context(['declutterLabels'], { THREE, document: { createElement: element, querySelectorAll: () => [] },
    innerWidth: 800, innerHeight: 600, DECLUTTER: { on: true, gap: 2, hyst: 4, last: null } });
  vm.runInContext(rendererSource, c);
  const { CSS2DObject, CSS2DRenderer } = c.css2d;
  c.scene = new THREE.Scene(); c.camera = new THREE.PerspectiveCamera(45, 4 / 3, .1, 100); c.camera.position.z = 5;
  c.labelRenderer = new CSS2DRenderer({ element: element() }); c.labelRenderer.setSize(800, 600);
  c.labelGroup = new THREE.Group(); c.measGroup = new THREE.Group(); c.scene.add(c.labelGroup, c.measGroup);
  const site = new CSS2DObject(element()), measurement = new CSS2DObject(element());
  measurement.element.getBoundingClientRect = () => ({ left: 100, top: 100, right: 160, bottom: 120, width: 60, height: 20 });
  c.labelGroup.add(site); c.measGroup.add(measurement);
  for (const declutter of [true, false]) {
    c.DECLUTTER.on = declutter;
    for (const visible of [false, true, false]) {
      c.api.setSceneLabels(visible); c.labelRenderer.render(c.scene, c.camera); c.api.declutterLabels();
      assert.equal(site.element.style.display, visible ? '' : 'none');
      if (visible) assert.notEqual(site.element.style.visibility, 'hidden');
      assert.equal(measurement.element.style.display, '');
      assert.equal(c.labelRenderer.domElement.style.display, '');
    }
  }
});

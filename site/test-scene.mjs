// Execute the real scene with a resource-tracking WebGL fixture. This tests
// lifecycle failures and delayed image callbacks, not GPU rendering accuracy.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('./scene.js', import.meta.url), 'utf8');

class Element {
  constructor(dataset = {}) {
    this.dataset = dataset;
    this.listeners = new Map();
    this.attributes = new Map();
    this.events = [];
    this.disabled = false;
    this.value = '0';
    this.captured = new Set();
  }
  addEventListener(name, handler) {
    const handlers = this.listeners.get(name) || [];
    handlers.push(handler); this.listeners.set(name, handlers);
  }
  dispatchEvent(event) {
    event.preventDefault ||= () => { event.defaultPrevented = true; };
    this.events.push(event.type);
    for (const handler of this.listeners.get(event.type) || []) handler(event);
    return !event.defaultPrevented;
  }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  getBoundingClientRect() { return { width: 800, height: 560, left: 0, top: 0 }; }
  setPointerCapture(id) { this.captured.add(id); }
  hasPointerCapture(id) { return this.captured.has(id); }
  releasePointerCapture(id) { this.captured.delete(id); }
}

function webgl({ failCompileAt = 0, failLinkAt = 0, failBufferAt = 0 } = {}) {
  const live = new Set(), uploads = [], values = new Map();
  const gl = {
    NO_ERROR: 0, COMPILE_STATUS: 1, LINK_STATUS: 2, ACTIVE_UNIFORMS: 3,
    MAX_TEXTURE_SIZE: 4, VERTEX_SHADER: 5, FRAGMENT_SHADER: 6,
    failCompileAt, failLinkAt, failBufferAt, compileCalls: 0, linkCalls: 0, bufferCalls: 0,
    lost: false, drawCalls: 0, live, uploads, values,
    createShader() { return allocate('shader'); },
    shaderSource(shader, text) { valid(shader); shader.source = text; },
    compileShader(shader) { shader.compiled = ++gl.compileCalls !== gl.failCompileAt; },
    getShaderParameter(shader) { return shader.compiled; },
    getShaderInfoLog() { return 'Controlled shader compilation failure'; },
    deleteShader: release,
    createProgram() { return Object.assign(allocate('program'), { shaders: [], uniforms: [] }); },
    attachShader(program, shader) { valid(program); valid(shader); program.shaders.push(shader); },
    linkProgram(program) {
      program.linked = ++gl.linkCalls !== gl.failLinkAt;
      program.uniforms = [...new Set(program.shaders.flatMap(shader =>
        [...shader.source.matchAll(/uniform\s+(?:(?:lowp|mediump|highp)\s+)?\w+\s+(\w+)/g)].map(match => match[1])))];
    },
    getProgramParameter(program, name) { return name === gl.LINK_STATUS ? program.linked : program.uniforms.length; },
    getProgramInfoLog() { return 'Controlled program link failure'; },
    getActiveUniform(program, index) { return { name: program.uniforms[index] }; },
    getUniformLocation(program, name) { valid(program); return { program, name }; },
    deleteProgram: release,
    createBuffer() { return ++gl.bufferCalls === gl.failBufferAt ? null : allocate('buffer'); },
    bindBuffer(target, buffer) { valid(buffer); }, bufferData() {}, bufferSubData() {},
    deleteBuffer: release,
    createTexture() { return allocate('texture'); },
    bindTexture(target, texture) { valid(texture); gl.boundTexture = texture; },
    texImage2D(...args) {
      valid(gl.boundTexture);
      if (args.length === 6) uploads.push({ texture: gl.boundTexture, image: args[5].image });
    },
    texParameteri() {}, pixelStorei() {}, deleteTexture: release,
    getParameter(name) { assert.equal(name, gl.MAX_TEXTURE_SIZE); return 4096; },
    getError() { return gl.NO_ERROR; }, isContextLost() { return gl.lost; },
    useProgram: valid, getAttribLocation() { return 0; },
    disableVertexAttribArray() {}, enableVertexAttribArray() {}, vertexAttribPointer() {},
    uniformMatrix4fv(location, transpose, value) { uniform(location, value); },
    uniform1f: uniform, uniform1i: uniform, uniform2fv: uniform, uniform3fv: uniform,
    uniform3f(location, ...value) { uniform(location, value); },
    activeTexture() {}, viewport() {}, clearColor() {}, clear() {}, enable() {},
    depthFunc() {}, cullFace() {}, blendFunc() {}, depthMask() {},
    drawArrays() { assert.equal(gl.lost, false); ++gl.drawCalls; },
  };
  let nextId = 0;
  function allocate(kind) { const object = { id: ++nextId, kind }; live.add(object); return object; }
  function valid(object) { assert(live.has(object), 'No deleted or previous-generation GPU object may be used'); }
  function release(object) { valid(object); live.delete(object); }
  function uniform(location, value) {
    if (!location) return;
    valid(location.program); values.set(location.name, typeof value === 'number' ? value : Array.from(value));
  }
  return gl;
}

function boot(options = {}) {
  const gl = options.noWebGL ? null : webgl(options);
  const stage = new Element(), status = new Element(), slider = new Element();
  const buttons = ['fold', 'explode', 'reset', 'pause'].map(sceneAction => new Element({ sceneAction }));
  const controls = [...buttons, slider];
  const canvas = new Element({ sceneScreen: '/inner.png', sceneCover: '/remote.png' });
  canvas.parentElement = stage; canvas.getContext = () => gl;
  const document = new Element();
  document.documentElement = { lang: 'en' }; document.hidden = false;
  document.querySelector = selector => ({ '#fold-scene': canvas, '#device-stage': stage, '#scene-status': status,
    '#fold-hinge': slider, '[data-scene-action="pause"]': buttons[3], '[data-scene-action="fold"]': buttons[0] })[selector] || null;
  document.querySelectorAll = selector => selector.includes('#fold-hinge') ? controls : buttons;
  document.createElement = () => {
    const raster = {};
    raster.getContext = () => ({ drawImage(image) { raster.image = image; } });
    return raster;
  };
  const images = [], frames = new Map(); let frameId = 0;
  class Image {
    set src(url) {
      this.url = url; this.naturalWidth = url.includes('remote') ? 352 : 2448;
      this.naturalHeight = url.includes('remote') ? 572 : 1848; images.push(this);
    }
  }
  const reducedMotion = new Element(); reducedMotion.matches = options.reducedMotion !== false;
  const environment = {
    document, Image, window: new Element(), devicePixelRatio: 1, innerHeight: 900,
    matchMedia: query => query.includes('prefers-reduced-motion') ? reducedMotion : { matches: false },
    CustomEvent: class { constructor(type, details) { this.type = type; Object.assign(this, details); } },
    ResizeObserver: class { observe() {} }, IntersectionObserver: class { observe() {} },
    requestAnimationFrame: callback => { frames.set(++frameId, callback); return frameId; },
    cancelAnimationFrame: id => frames.delete(id), console: { warn() {} },
  };
  vm.runInNewContext(source, environment, { filename: 'foldgpt/scene.js', timeout: 5000 });
  const lose = () => { gl.lost = true; canvas.dispatchEvent({ type: 'webglcontextlost' }); };
  const restore = () => { gl.lost = false; canvas.dispatchEvent({ type: 'webglcontextrestored' }); };
  const load = (...items) => items.forEach(image => image.onload());
  return { gl, canvas, stage, status, slider, controls, buttons, images, frames, lose, restore, load, environment };
}

function unavailable(scene) {
  assert.equal(scene.canvas.dataset.sceneReady, 'fallback');
  assert.equal(scene.stage.dataset.ready, 'false', 'The static image must remain visible');
  assert.equal(scene.status.dataset.visible, 'true');
  assert(scene.controls.every(control => control.disabled));
  assert.equal(scene.canvas.attributes.get('aria-disabled'), 'true');
  assert(scene.canvas.events.includes('foldscene:unavailable'));
  assert.equal(scene.frames.size, 0);
  if (scene.gl) assert.equal(scene.gl.live.size, 0, 'No partial or stale GPU resources remain');
}

test('no WebGL exposes the static fallback and disables all renderer controls', () => {
  const scene = boot({ noWebGL: true }); unavailable(scene);
  assert.equal(scene.images.length, 0);
});

for (const failure of [{ failCompileAt: 2 }, { failCompileAt: 3 }, { failLinkAt: 2 }, { failBufferAt: 2 }]) {
  test(`initial GPU failure is cleaned up and can later recover: ${JSON.stringify(failure)}`, () => {
    const scene = boot(failure); unavailable(scene);
    assert.equal(scene.images.length, 0);
    scene.gl.failCompileAt = scene.gl.failLinkAt = scene.gl.failBufferAt = 0;
    scene.restore(); scene.load(...scene.images);
    assert.equal(scene.canvas.dataset.sceneReady, 'true');
    assert(scene.controls.every(control => !control.disabled));
    assert.equal(scene.gl.uploads.length, 2);
    assert.equal(scene.gl.live.size, 7, 'Two programs, three buffers and two textures; no leaked shaders');
  });
}

test('failed restoration stops rendering and ignores callbacks from the lost generation', () => {
  const scene = boot({ reducedMotion: false });
  const previousImages = [...scene.images];
  scene.canvas.dispatchEvent({ type: 'pointerdown', button: 0, pointerId: 9, clientX: 100, clientY: 80 });
  assert(scene.canvas.hasPointerCapture(9));
  scene.lose(); unavailable(scene);
  assert.equal(scene.canvas.hasPointerCapture(9), false);
  scene.gl.failCompileAt = scene.gl.compileCalls + 3;
  assert.doesNotThrow(scene.restore); unavailable(scene);
  const drawCalls = scene.gl.drawCalls;
  assert.doesNotThrow(() => {
    scene.load(...previousImages); previousImages[0].onerror();
    scene.canvas.dispatchEvent({ type: 'pointermove', pointerId: 9, clientX: 300, clientY: 120 });
    scene.canvas.dispatchEvent({ type: 'keydown', key: 'ArrowRight' });
    scene.environment.document.dispatchEvent({ type: 'visibilitychange' });
  });
  assert.equal(scene.gl.drawCalls, drawCalls);
  assert.equal(scene.gl.uploads.length, 0);
  unavailable(scene);
  scene.gl.failCompileAt = 0;
  scene.restore(); scene.load(...scene.images.slice(-2));
  assert.equal(scene.canvas.dataset.sceneReady, 'true');
  assert.equal(scene.gl.uploads.length, 2);
  assert.equal(scene.gl.live.size, 7);
  assert.equal(scene.frames.size, 1, 'Animation resumes after a later successful recovery');
  assert(scene.controls.every(control => !control.disabled));
});

test('successful restoration reloads both textures, preserves keyboard controls and rejects stale images', () => {
  const scene = boot();
  for (let cycle = 0; cycle < 3; cycle++) {
    const previousImages = scene.images.slice(-2);
    scene.lose(); unavailable(scene); scene.restore();
    assert.equal(scene.canvas.dataset.sceneReady, 'true');
    assert.equal(scene.stage.dataset.ready, 'true');
    assert.equal(scene.status.dataset.visible, 'false');
    assert(scene.controls.every(control => !control.disabled));
    assert.equal(scene.canvas.attributes.has('aria-disabled'), false);
    const uploadsBefore = scene.gl.uploads.length;
    scene.load(...previousImages); previousImages[0].onerror();
    assert.equal(scene.gl.uploads.length, uploadsBefore);
    assert.equal(scene.status.dataset.visible, 'false');
    scene.load(...scene.images.slice(-2));
    assert.deepEqual(scene.gl.uploads.slice(-2).map(upload => upload.image.url), ['/inner.png', '/remote.png']);
    assert.notEqual(scene.gl.uploads.at(-1).texture, scene.gl.uploads.at(-2).texture);
    assert.equal(scene.gl.values.get('uScreenLoaded'), 1);
    assert.equal(scene.gl.values.get('uCoverLoaded'), 1);
    assert.equal(scene.gl.live.size, 7);
  }
  scene.canvas.dispatchEvent({ type: 'keydown', key: ' ' });
  assert.equal(scene.gl.values.get('uFold'), 1);
  scene.canvas.dispatchEvent({ type: 'keydown', key: 'Escape' });
  assert.equal(scene.gl.values.get('uFold'), 0);
  assert.equal(scene.frames.size, 0, 'Reduced-motion preference survives every recovery');
});

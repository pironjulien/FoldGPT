/**
 * FoldGPT — a real screen capture inside a reactive, articulated point cloud.
 * Native WebGL; no runtime dependency, telemetry or simulated product session.
 * The host page owns copy, controls and the clearly labelled illustration.
 */
const canvas = document.querySelector('#fold-scene');
const sceneEnglish = document.documentElement.lang.toLowerCase().startsWith('en');
const sceneTranslations = {
  'La scène 3D nécessite WebGL. Les captures réelles sont disponibles plus bas.': 'The 3D scene requires WebGL. Real captures are available below.',
  'La scène 3D est indisponible dans ce navigateur. Retrouvez les captures réelles plus bas.': 'The 3D scene is unavailable in this browser. See the real captures below.',
  'Capture indisponible dans la scène. Les médias documentés restent accessibles plus bas.': 'The scene capture is unavailable. Documented media remain available below.',
  'Activer l’animation': 'Enable animation',
  'Pause': 'Pause',
  'Déplier': 'Unfold',
  'Plier': 'Fold',
  'Fold replié. Faites-le pivoter pour voir l’écran externe et les caméras.': 'Folded. Rotate to see the cover display and cameras.',
  'Charnière articulée. Faites glisser le Fold pour le faire pivoter.': 'Articulated hinge. Drag the Fold to rotate it.',
  'Le Fold se disperse en particules, puis se recompose.': 'The Fold disperses into particles, then reassembles.',
  'Vue initiale. Survolez pour déplacer les particules, faites glisser pour pivoter.': 'Initial view. Hover to move particles; drag to rotate.',
  'Animation en pause. La rotation et la charnière restent disponibles.': 'Animation paused. Rotation and hinge controls remain available.',
  'Animation active. Les particules réagissent au pointeur et au toucher.': 'Animation active. Particles respond to pointer and touch.',
  'Scène suspendue pendant la restauration graphique.': 'Scene paused while graphics are being restored.',
  'Scène restaurée.': 'Scene restored.',
  'Animation désactivée selon vos préférences. Vous pouvez l’activer ou manipuler le Fold au clavier.': 'Animation disabled according to your preferences. Enable it or use the keyboard controls.',
  'Survolez pour déplacer les particules. Glissez pour pivoter. Cliquez pour disperser le Fold.': 'Hover to move particles. Drag to rotate. Click to disperse the Fold.',
};
const sceneText = value => sceneEnglish ? (sceneTranslations[value] || value) : value;

function sceneUnavailable(canvas, message) {
  canvas.dataset.sceneReady = 'fallback';
  canvas.setAttribute('aria-disabled', 'true');
  const stage = document.querySelector('#device-stage') || canvas.parentElement;
  if (stage) stage.dataset.ready = 'false';
  const status = document.querySelector('#scene-status');
  if (status) { status.textContent = sceneText(message); status.dataset.visible = 'true'; }
  document.querySelectorAll('[data-scene-action], #fold-hinge').forEach(control => { control.disabled = true; });
  canvas.dispatchEvent(new CustomEvent('foldscene:unavailable', { bubbles: true }));
}

if (canvas) {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: false, powerPreference: 'low-power' });
  if (gl) startScene(gl, canvas);
  else sceneUnavailable(canvas, 'La scène 3D nécessite WebGL. Les captures réelles sont disponibles plus bas.');
}

function startScene(gl, canvas) {
  const stage = document.querySelector('#device-stage') || canvas.parentElement;
  const status = document.querySelector('#scene-status');
  const slider = document.querySelector('#fold-hinge');
  const pauseButton = document.querySelector('[data-scene-action="pause"]');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const TAU = Math.PI * 2;
  const FOLD_ANGLE = Math.PI / 2;
  const FOV = 35 * Math.PI / 180;
  const W = 2.13;
  const H = 1.63;
  const targets = [];
  const mesh = [];
  let randomSeed = 1618033;
  const random = () => { randomSeed = (1664525 * randomSeed + 1013904223) >>> 0; return randomSeed / 4294967296; };
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const state = {
    width: 1, height: 1, aspect: 1, camera: 8, fold: 0, foldTarget: 0,
    yaw: -.27, pitch: .12, yawTarget: -.27, pitchTarget: .12,
    pointerX: 0, pointerY: 0, pointerActive: 0, pointerTarget: 0,
    pointerDown: false, pointerId: null, previousX: 0, previousY: 0, travel: 0,
    paused: reducedMotion.matches, visible: true, lost: true, lastTime: 0,
    request: 0, time: 0, scatter: 0, screenLoaded: false, coverLoaded: false,
    scroll: 0, scrollTarget: 0, explicitFold: false,
  };
  const rotation = new Float32Array(3);
  const projection = new Float32Array(16);
  const coverScale = new Float32Array([1, 1]);
  const transformed = new Float32Array(3);
  const trig = new Float32Array(10);

  function announce(text, visible) {
    if (!status) return;
    if (visible === undefined && status.dataset.visible === 'true') return;
    status.textContent = sceneText(text);
    if (visible !== undefined) status.dataset.visible = String(visible);
  }

  // Every half carries its own screen UV range. Folding changes the geometry,
  // never the source image: the application shown is the supplied real capture.
  function vertex(x, y, z, nx, ny, nz, u, v, material, side) {
    mesh.push(x, y, z, nx, ny, nz, u, v, material, side);
  }
  function point(x, y, z, side, material = 0, u = 0, v = 0, brightness = 1) {
    targets.push(x, y, z, side, material, u, v, brightness, random());
  }
  function roundedOutline(x0, x1, y0, y1, radius, segments = 10) {
    const result = [];
    // Per-corner radii keep the inner hinge corners square: the open device
    // has one continuous display, rather than two rounded phones side by side.
    const radii = Array.isArray(radius) ? radius : [radius, radius, radius, radius];
    const corners = [
      [x1 - radii[0], y1 - radii[0], 0, radii[0]],
      [x0 + radii[1], y1 - radii[1], Math.PI / 2, radii[1]],
      [x0 + radii[2], y0 + radii[2], Math.PI, radii[2]],
      [x1 - radii[3], y0 + radii[3], Math.PI * 1.5, radii[3]],
    ];
    for (const [cx, cy, start, r] of corners) {
      if (r === 0) { result.push([cx, cy]); continue; }
      for (let i = 0; i <= segments; i++) {
        const a = start + i / segments * Math.PI / 2;
        result.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
      }
    }
    return result;
  }
  function face(x0, x1, y0, y1, z, radius, material, side, uvMode = 'screen') {
    const outline = roundedOutline(x0, x1, y0, y1, radius);
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const n = z >= 0 ? 1 : -1;
    const add = (x, y) => {
      const u = uvMode === 'screen' ? (x + W - .055) / ((W - .055) * 2) : (x - x0) / (x1 - x0);
      const v = uvMode === 'screen' ? (y + H - .055) / ((H - .055) * 2) : (y - y0) / (y1 - y0);
      vertex(x, y, z, 0, 0, n, u, v, material, side);
    };
    for (let i = 0; i < outline.length; i++) {
      const a = outline[i];
      const b = outline[(i + 1) % outline.length];
      add(cx, cy); add(...(n > 0 ? a : b)); add(...(n > 0 ? b : a));
    }
  }
  function shell(x0, x1, side) {
    const corners = side < 0 ? [0, .13, .13, 0] : [.13, 0, 0, .13];
    const outline = roundedOutline(x0, x1, -H, H, corners);
    face(x0, x1, -H, H, .08, corners, 0, side);
    face(x0, x1, -H, H, -.085, corners, 0, side);
    for (let i = 0; i < outline.length; i++) {
      const a = outline[i];
      const b = outline[(i + 1) % outline.length];
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const distance = Math.max(.00001, Math.hypot(dx, dy));
      const hingeEdge = Math.abs(a[0]) < .015 && Math.abs(b[0]) < .015;
      const emit = (p, z) => vertex(p[0], p[1], z, dy / distance, -dx / distance, 0, 0, 0, hingeEdge ? 0 : 1, side);
      emit(a, -.085); emit(b, -.085); emit(b, .08);
      emit(a, -.085); emit(b, .08); emit(a, .08);
      if (hingeEdge) continue;
      const count = Math.max(3, Math.ceil(distance / .014));
      for (let j = 0; j < count; j++) {
        const f = j / count;
        for (const z of [-.087, -.04, .04, .085]) point(a[0] + dx * f, a[1] + dy * f, z, side, 0, 0, 0, .55 + random() * .65);
      }
    }
  }
  function disc(x, y, z, radius, material, side) {
    const n = z >= 0 ? 1 : -1;
    for (let i = 0; i < 40; i++) {
      const a = n * i / 40 * TAU;
      const b = n * (i + 1) / 40 * TAU;
      vertex(x, y, z, 0, 0, n, .5, .5, material, side);
      vertex(x + Math.cos(a) * radius, y + Math.sin(a) * radius, z, 0, 0, n, 0, 0, material, side);
      vertex(x + Math.cos(b) * radius, y + Math.sin(b) * radius, z, 0, 0, n, 1, 1, material, side);
      point(x + Math.cos(a) * radius, y + Math.sin(a) * radius, z + n * .002, side, 0, 0, 0, .75);
    }
  }
  function walls(outline, z0, z1, material, side, center = null) {
    const low = Math.min(z0, z1), high = Math.max(z0, z1);
    for (let i = 0; i < outline.length; i++) {
      const a = outline[i], b = outline[(i + 1) % outline.length];
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const distance = Math.hypot(dx, dy);
      const emit = (p, z) => {
        const nx = center ? p[0] - center[0] : dy;
        const ny = center ? p[1] - center[1] : -dx;
        const length = center ? Math.hypot(nx, ny) : distance;
        vertex(p[0], p[1], z, nx / length, ny / length, 0, 0, 0, material, side);
      };
      // The outline is counterclockwise; these quads face away from its interior.
      emit(a, low); emit(b, low); emit(b, high);
      emit(a, low); emit(b, high); emit(a, high);
    }
  }
  function raisedFace(x0, x1, y0, y1, baseZ, faceZ, radius, material, side) {
    face(x0, x1, y0, y1, faceZ, radius, material, side, 'local');
    walls(roundedOutline(x0, x1, y0, y1, radius), baseZ, faceZ, material, side);
  }
  function raisedDisc(x, y, baseZ, faceZ, radius, material, side) {
    disc(x, y, faceZ, radius, material, side);
    const outline = [];
    for (let i = 0; i < 40; i++) {
      const angle = i / 40 * TAU;
      outline.push([x + Math.cos(angle) * radius, y + Math.sin(angle) * radius]);
    }
    walls(outline, baseZ, faceZ, material, side, [x, y]);
  }

  for (const side of [-1, 1]) {
    const x0 = side < 0 ? -W : .004;
    const x1 = side < 0 ? -.004 : W;
    shell(x0, x1, side);
    const sx0 = side < 0 ? x0 + .055 : 0;
    const sx1 = side < 0 ? 0 : x1 - .055;
    const screenCorners = side < 0 ? [0, .09, .09, 0] : [.09, 0, 0, .09];
    face(sx0, sx1, -H + .055, H - .055, .089, screenCorners, 2, side);
    // A fine metallic rim catches the light; these points are visible even
    // when the textured screen is completely assembled.
    const inner = roundedOutline(sx0, sx1, -H + .055, H - .055, screenCorners, 12);
    for (let i = 0; i < inner.length; i++) {
      const a = inner[i];
      const b = inner[(i + 1) % inner.length];
      if (Math.abs(a[0]) < .015 && Math.abs(b[0]) < .015) continue;
      const count = Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / .018);
      for (let j = 0; j < count; j++) point(a[0] + (b[0] - a[0]) * j / count, a[1] + (b[1] - a[1]) * j / count, .094, side, 0, 0, 0, 1.2);
    }
    const columns = matchMedia('(max-width: 600px)').matches ? 42 : 55;
    const rows = Math.round(columns * (H * 2 - .11) / (sx1 - sx0));
    for (let col = 0; col < columns; col++) {
      for (let row = 0; row < rows; row++) {
        const x = sx0 + (col + .5) / columns * (sx1 - sx0);
        const y = -H + .055 + (row + .5) / rows * (H * 2 - .11);
        point(x, y, .095, side, 2, (x + W - .055) / ((W - .055) * 2), (y + H - .055) / ((H - .055) * 2), .9);
      }
    }
    for (let col = 0; col < 20; col++) {
      for (let row = 0; row < 32; row++) {
        point(x0 + .1 + col / 19 * (x1 - x0 - .2), -H + .13 + row / 31 * (H * 2 - .26), -.089, side, 0, 0, 0, .12 + random() * .12);
      }
    }
  }
  // Galaxy Z Fold8: two rear cameras on the left when viewed from behind;
  // the cover display is on the right. Local X reverses when viewing -Z.
  // Reference: samsung.com/fr/smartphones/galaxy-z-fold8/ (September 2026).
  // Connect the island to the rear shell and each lens tier to the tier below it.
  raisedFace(1.59, 1.98, .55, 1.43, -.085, -.097, .185, 1, 1);
  for (const y of [1.19, .80]) {
    raisedDisc(1.785, y, -.097, -.135, .151, 1, 1);
    raisedDisc(1.785, y, -.135, -.143, .117, 3, 1);
    raisedDisc(1.785, y, -.143, -.149, .067, 4, 1);
    disc(1.805, y + .026, -.151, .021, 5, 1);
  }
  disc(1.785, .60, -.102, .026, 5, 1);
  face(-W + .07, -.07, -H + .07, H - .07, -.095, .115, 7, -1, 'local');
  // The external selfie camera sits above the native Android interface.
  disc(-W / 2, H - .16, -.099, .035, 3, -1);
  for (let y = -H + .12; y <= H - .12; y += .018) {
    point(0, y, -.10, 0, 0, 0, 0, .08);
  }

  const base = new Float32Array(targets);
  const count = base.length / 9;
  const positions = new Float32Array(count * 3);
  const velocities = new Float32Array(count * 3);
  const attributes = new Float32Array(count * 4);
  const meshData = new Float32Array(mesh);
  for (let i = 0; i < count; i++) {
    attributes.set([base[i * 9 + 5], base[i * 9 + 6], base[i * 9 + 4], base[i * 9 + 7]], i * 4);
  }

  const transformGLSL = `
    uniform vec3 uRotation;
    uniform float uFold;
    vec3 turnY(vec3 p, float a) { float c=cos(a),s=sin(a); return vec3(c*p.x+s*p.z,p.y,-s*p.x+c*p.z); }
    vec3 turnX(vec3 p, float a) { float c=cos(a),s=sin(a); return vec3(p.x,c*p.y-s*p.z,s*p.y+c*p.z); }
    vec3 turnZ(vec3 p, float a) { float c=cos(a),s=sin(a); return vec3(c*p.x-s*p.y,s*p.x+c*p.y,p.z); }
    vec3 orient(vec3 p, float side) {
      p=turnY(p,-side*uFold*${FOLD_ANGLE});
      return turnZ(turnX(turnY(p,uRotation.y),uRotation.x),uRotation.z);
    }
    vec3 transform(vec3 p, float side) {
      p=turnY(p,-side*uFold*${FOLD_ANGLE});
      p.x+=side*.094*sin(uFold*${FOLD_ANGLE});
      p.z-=${W * .5}*sin(uFold*${FOLD_ANGLE});
      return turnZ(turnX(turnY(p,uRotation.y),uRotation.x),uRotation.z);
    }
  `;
  const meshVS = `
    precision highp float;
    attribute vec3 aPosition; attribute vec3 aNormal;
    attribute vec2 aUV; attribute float aMaterial; attribute float aSide;
    uniform mat4 uProjection; uniform mediump float uCamera;
    varying mediump vec3 vNormal; varying mediump vec3 vWorld; varying mediump vec2 vUV;
    varying mediump float vMaterial; varying mediump vec2 vScreen;
    ${transformGLSL}
    void main() {
      vec3 p=transform(aPosition,aSide);
      vWorld=p; vNormal=orient(aNormal,aSide); vUV=aUV; vMaterial=aMaterial;
      gl_Position=uProjection*vec4(p.xy,p.z-uCamera,1.);
      vScreen=gl_Position.xy/gl_Position.w;
    }
  `;
  const meshFS = `
    precision mediump float;
    varying mediump vec3 vNormal; varying mediump vec3 vWorld; varying mediump vec2 vUV; varying mediump float vMaterial; varying mediump vec2 vScreen;
    uniform sampler2D uScreen; uniform sampler2D uCover;
    uniform float uScreenLoaded; uniform float uCoverLoaded; uniform float uAssembled;
    uniform vec2 uCoverScale;
    uniform mediump float uCamera; uniform vec3 uPointer; uniform float uAspect;
    void main() {
      vec3 n=normalize(vNormal), light=normalize(vec3(-.5,.8,1.));
      vec3 view=normalize(vec3(0.,0.,uCamera)-vWorld);
      float diffuse=max(dot(n,light),0.);
      float rim=pow(1.-abs(dot(n,view)),3.);
      float spec=pow(max(dot(n,normalize(light+view)),0.),42.);
      vec3 color=vec3(.055,.061,.072)*(.7+diffuse*.5)+vec3(.72,.75,.79)*spec*.16+rim*vec3(.10,.11,.12);
      float alpha=uAssembled;
      if(vMaterial>.5 && vMaterial<1.5) color=vec3(.105,.115,.13)*(.55+diffuse*.5)+spec*vec3(.72,.75,.79)*.26+rim*.08;
      if(vMaterial>1.5 && vMaterial<2.5) {
        vec3 capture=texture2D(uScreen,clamp(vUV,0.,1.)).rgb;
        color=mix(vec3(.066,.075,.084),capture,uScreenLoaded);
        color+=spec*.018;
      }
      if(vMaterial>2.5 && vMaterial<3.5) color=vec3(.019,.025,.033)+spec*.09+rim*.07;
      if(vMaterial>3.5 && vMaterial<4.5) color=vec3(.025,.055,.078)+spec*.23+rim*.1;
      if(vMaterial>4.5 && vMaterial<5.5) color=vec3(.61,.68,.69)*(.5+diffuse*.5);
      if(vMaterial>6.5) {
        // Reverse U for a readable outward-facing screen and contain the
        // reference image without further cropping or stretching its interface.
        vec2 uv=(vec2(1.-vUV.x,vUV.y)-.5)/uCoverScale+.5;
        float inside=step(0.,uv.x)*step(uv.x,1.)*step(0.,uv.y)*step(uv.y,1.);
        vec3 cover=texture2D(uCover,clamp(uv,0.,1.)).rgb;
        vec3 margin=texture2D(uCover,vec2(0.,.5)).rgb;
        color=mix(vec3(.025,.03,.04),mix(margin,cover,inside),uCoverLoaded);
      }
      float d=length((vScreen-uPointer.xy)*vec2(uAspect,1.));
      alpha*=1.-uPointer.z*(1.-smoothstep(.045,.22,d))*.98;
      if(alpha<.008) discard;
      gl_FragColor=vec4(color,alpha);
    }
  `;
  const pointVS = `
    precision highp float;
    attribute vec3 aPosition; attribute vec4 aMeta;
    uniform mat4 uProjection; uniform float uCamera; uniform float uDpr; uniform float uTime; uniform float uScatter;
    varying mediump vec2 vUV; varying mediump float vMaterial; varying mediump float vBrightness;
    void main() {
      gl_Position=uProjection*vec4(aPosition.xy,aPosition.z-uCamera,1.);
      gl_PointSize=clamp((aMeta.z>1.5?2.5:3.0)*uDpr*(7.5/max(2.,uCamera-aPosition.z)),1.,8.);
      vUV=aMeta.xy; vMaterial=aMeta.z;
      vBrightness=aMeta.w*(.78+.22*sin(aPosition.y*2.6+uTime*.65));
      if(vMaterial>1.5) vBrightness*=mix(.13,.98,min(1.,uScatter*4.));
    }
  `;
  const pointFS = `
    precision mediump float;
    varying mediump vec2 vUV; varying mediump float vMaterial; varying mediump float vBrightness;
    uniform sampler2D uScreen; uniform float uScreenLoaded;
    void main() {
      float d=length(gl_PointCoord-.5)*2.;
      if(d>1.) discard;
      float alpha=(1.-smoothstep(.18,1.,d))*vBrightness;
      vec3 color=vec3(.84,.70,.43);
      if(vMaterial>1.5) color=mix(color,texture2D(uScreen,vUV).rgb,uScreenLoaded);
      gl_FragColor=vec4(color,clamp(alpha,0.,1.));
    }
  `;

  function compile(type, source) {
    const shader = gl.createShader(type);
    if (!shader) throw new Error('Unable to allocate a WebGL shader');
    try {
      gl.shaderSource(shader, source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
      return shader;
    } catch (error) {
      gl.deleteShader(shader); throw error;
    }
  }
  function program(vs, fs) {
    const result = gl.createProgram();
    if (!result) throw new Error('Unable to allocate a WebGL program');
    let vertexShader, fragmentShader;
    try {
      vertexShader = compile(gl.VERTEX_SHADER, vs);
      fragmentShader = compile(gl.FRAGMENT_SHADER, fs);
      gl.attachShader(result, vertexShader); gl.attachShader(result, fragmentShader); gl.linkProgram(result);
      if (!gl.getProgramParameter(result, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(result));
      const uniforms = {};
      for (let i = 0; i < gl.getProgramParameter(result, gl.ACTIVE_UNIFORMS); i++) {
        const name = gl.getActiveUniform(result, i).name; uniforms[name] = gl.getUniformLocation(result, name);
      }
      return { id: result, uniforms };
    } catch (error) {
      gl.deleteProgram(result); throw error;
    } finally {
      if (vertexShader) gl.deleteShader(vertexShader);
      if (fragmentShader) gl.deleteShader(fragmentShader);
    }
  }
  function buffer(data, usage) {
    const result = gl.createBuffer();
    if (!result) throw new Error('Unable to allocate a WebGL buffer');
    try {
      gl.bindBuffer(gl.ARRAY_BUFFER, result); gl.bufferData(gl.ARRAY_BUFFER, data, usage); return result;
    } catch (error) {
      gl.deleteBuffer(result); throw error;
    }
  }
  function texture() {
    const result = gl.createTexture();
    if (!result) throw new Error('Unable to allocate a WebGL texture');
    try {
      gl.bindTexture(gl.TEXTURE_2D, result);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([21, 24, 30, 255]));
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      return result;
    } catch (error) {
      gl.deleteTexture(result); throw error;
    }
  }
  function disposeGPU(resources) {
    if (!resources) return;
    for (const name of ['mesh', 'points']) if (resources[name]) gl.deleteProgram(resources[name].id);
    for (const name of ['meshBuffer', 'positionBuffer', 'attributeBuffer']) if (resources[name]) gl.deleteBuffer(resources[name]);
    for (const name of ['screen', 'cover']) if (resources[name]) gl.deleteTexture(resources[name]);
  }
  function createGPU() {
    const resources = {};
    try {
      resources.mesh = program(meshVS, meshFS); resources.points = program(pointVS, pointFS);
      resources.meshBuffer = buffer(meshData, gl.STATIC_DRAW);
      resources.positionBuffer = buffer(positions, gl.DYNAMIC_DRAW);
      resources.attributeBuffer = buffer(attributes, gl.STATIC_DRAW);
      resources.screen = texture(); resources.cover = texture();
      if (gl.isContextLost() || gl.getError() !== gl.NO_ERROR) throw new Error('WebGL resource initialization failed');
      return resources;
    } catch (error) {
      disposeGPU(resources); throw error;
    }
  }
  let gpu = null, gpuGeneration = 0;
  function suspendGraphics(message, error) {
    state.lost = true; ++gpuGeneration; stop();
    const previous = gpu; gpu = null; disposeGPU(previous);
    state.screenLoaded = false; state.coverLoaded = false;
    if (state.pointerId !== null && canvas.hasPointerCapture(state.pointerId)) canvas.releasePointerCapture(state.pointerId);
    state.pointerDown = false; state.pointerId = null; state.pointerTarget = 0; state.pointerActive = 0;
    canvas.dataset.dragging = 'false';
    sceneUnavailable(canvas, message);
    if (error) console.warn('FoldGPT scene initialization failed:', error.message);
  }
  function initializeGraphics(restoring = false) {
    stop(); ++gpuGeneration; state.lost = true;
    const previous = gpu; gpu = null; disposeGPU(previous);
    state.screenLoaded = false; state.coverLoaded = false;
    try { gpu = createGPU(); }
    catch (error) {
      suspendGraphics('La scène 3D est indisponible dans ce navigateur. Retrouvez les captures réelles plus bas.', error);
      return;
    }
    state.lost = false;
    document.querySelectorAll('[data-scene-action], #fold-hinge').forEach(control => { control.disabled = false; });
    canvas.removeAttribute('aria-disabled');
    snap(); resize(); setPaused(state.paused);
    if (!restoring && !state.paused) { assembleEntrance(); draw(); }
    loadTexture(canvas.dataset.sceneScreen, 'screen'); loadTexture(canvas.dataset.sceneCover, 'cover');
    canvas.dataset.sceneReady = 'true'; stage.dataset.ready = 'true';
    canvas.dataset.particleCount = String(count);
    announce(restoring ? 'Scène restaurée.' : state.paused ? 'Animation désactivée selon vos préférences. Vous pouvez l’activer ou manipuler le Fold au clavier.' : 'Survolez pour déplacer les particules. Glissez pour pivoter. Cliquez pour disperser le Fold.', false);
    canvas.dispatchEvent(new CustomEvent('foldscene:ready', { bubbles: true, detail: { particles: count } }));
  }
  function loadTexture(url, name) {
    if (!url || !gpu || state.lost) return;
    const resources = gpu, generation = gpuGeneration;
    const current = () => !state.lost && gpu === resources && gpuGeneration === generation;
    const picture = new Image(); picture.decoding = 'async';
    picture.onload = () => {
      if (!current()) return;
      // Fit reviewed imagery within the GPU's texture budget.
      const textureLimit = Math.min(2048, gl.getParameter(gl.MAX_TEXTURE_SIZE));
      const width = picture.naturalWidth;
      const height = picture.naturalHeight;
      if (name === 'cover') {
        const screenAspect = (W - .14) / (2 * H - .14);
        const captureAspect = width / height;
        coverScale[0] = Math.min(1, captureAspect / screenAspect);
        coverScale[1] = Math.min(1, screenAspect / captureAspect);
      }
      const scale = Math.min(1, textureLimit / Math.max(width, height, 1));
      const raster = document.createElement('canvas');
      raster.width = Math.max(1, Math.round(width * scale));
      raster.height = Math.max(1, Math.round(height * scale));
      raster.getContext('2d').drawImage(picture, 0, 0, raster.width, raster.height);
      gl.bindTexture(gl.TEXTURE_2D, resources[name]); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, raster);
      state[name + 'Loaded'] = true;
      draw();
    };
    picture.onerror = () => {
      if (current()) announce('Capture indisponible dans la scène. Les médias documentés restent accessibles plus bas.', true);
    };
    picture.src = url;
  }

  function transformPoint(x, y, z, side, out) {
    let c = side === 0 ? 1 : trig[0], s = -side * trig[1];
    let a = c * x + s * z, b = -s * x + c * z; x = a + side * .094 * trig[1]; z = b - W * .5 * trig[1];
    c = trig[2]; s = trig[3];
    a = c * x + s * z; b = -s * x + c * z; x = a; z = b;
    c = trig[4]; s = trig[5];
    a = c * y - s * z; b = s * y + c * z; y = a; z = b;
    c = trig[6]; s = trig[7];
    out[0] = c * x - s * y; out[1] = s * x + c * y; out[2] = z;
  }
  function updateRotation() {
    rotation[0] = state.pitch;
    rotation[1] = state.yaw + state.fold * Math.PI / 2 + state.scroll * .18;
    rotation[2] = -.035 + state.scroll * .04;
    trig[0] = Math.cos(state.fold * FOLD_ANGLE); trig[1] = Math.sin(state.fold * FOLD_ANGLE);
    trig[2] = Math.cos(rotation[1]); trig[3] = Math.sin(rotation[1]);
    trig[4] = Math.cos(rotation[0]); trig[5] = Math.sin(rotation[0]);
    trig[6] = Math.cos(rotation[2]); trig[7] = Math.sin(rotation[2]);
  }
  function snap() {
    state.fold = state.foldTarget; state.yaw = state.yawTarget; state.pitch = state.pitchTarget;
    updateRotation();
    for (let i = 0; i < count; i++) {
      transformPoint(base[i * 9], base[i * 9 + 1], base[i * 9 + 2], base[i * 9 + 3], transformed);
      positions.set(transformed, i * 3);
    }
    velocities.fill(0); state.scatter = 0;
  }
  function update(dt) {
    const easing = 1 - Math.exp(-7 * dt);
    state.fold += (state.foldTarget - state.fold) * easing;
    state.yaw += (state.yawTarget - state.yaw) * easing;
    state.pitch += (state.pitchTarget - state.pitch) * easing;
    state.scroll += (state.scrollTarget - state.scroll) * easing;
    state.pointerActive += (state.pointerTarget - state.pointerActive) * (1 - Math.exp(-9 * dt));
    updateRotation();
    const halfH = state.camera * Math.tan(FOV / 2);
    const px = state.pointerX * halfH * state.aspect;
    const py = state.pointerY * halfH;
    const damping = Math.exp(-5.7 * dt);
    const radius = .59;
    const radiusSquared = radius * radius;
    let displacement = 0;
    for (let i = 0; i < count; i++) {
      const p = i * 3, b = i * 9;
      transformPoint(base[b], base[b + 1], base[b + 2], base[b + 3], transformed);
      const dx = transformed[0] - positions[p];
      const dy = transformed[1] - positions[p + 1];
      const dz = transformed[2] - positions[p + 2];
      velocities[p] += dx * 28 * dt;
      velocities[p + 1] += dy * 28 * dt;
      velocities[p + 2] += dz * 28 * dt;
      if (state.pointerActive > .01) {
        const depth = state.camera / Math.max(2, state.camera - positions[p + 2]);
        const ax = positions[p] * depth - px;
        const ay = positions[p + 1] * depth - py;
        const distanceSquared = ax * ax + ay * ay;
        if (distanceSquared < radiusSquared) {
          const distance = Math.sqrt(Math.max(.00001, distanceSquared));
          const force = Math.pow(1 - distance / radius, 2) * state.pointerActive * 56 * dt;
          const angle = base[b + 8] * TAU;
          velocities[p] += (ax / distance + Math.cos(angle) * .18) * force;
          velocities[p + 1] += (ay / distance + Math.sin(angle) * .18) * force;
          velocities[p + 2] += force * .65;
        }
      }
      for (let j = 0; j < 3; j++) {
        velocities[p + j] *= damping;
        positions[p + j] += clamp(velocities[p + j], -18, 18) * dt;
      }
      displacement += Math.sqrt(dx * dx + dy * dy + dz * dz);
    }
    state.scatter = displacement / count;
  }

  function attribute(prog, name, size, stride, offset) {
    const index = gl.getAttribLocation(prog.id, name);
    if (index < 0) return;
    gl.enableVertexAttribArray(index); gl.vertexAttribPointer(index, size, gl.FLOAT, false, stride, offset);
  }
  function common(prog) {
    // Attribute locations are local to a program. Leaving mesh-only locations
    // enabled would make the larger point draw read beyond the mesh buffer.
    for (let i = 0; i < 8; i++) gl.disableVertexAttribArray(i);
    gl.useProgram(prog.id);
    const u = prog.uniforms;
    gl.uniformMatrix4fv(u.uProjection, false, projection); gl.uniform1f(u.uCamera, state.camera);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, gpu.screen); gl.uniform1i(u.uScreen, 0);
    gl.uniform1f(u.uScreenLoaded, Number(state.screenLoaded));
  }
  function draw() {
    if (state.lost || !gpu || state.width < 2) return;
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.depthMask(true);
    common(gpu.mesh);
    let u = gpu.mesh.uniforms;
    gl.uniform3fv(u.uRotation, rotation); gl.uniform1f(u.uFold, state.fold);
    gl.uniform1f(u.uAssembled, 1 - clamp(state.scatter * 1.85, 0, 1));
    gl.uniform3f(u.uPointer, state.pointerX, state.pointerY, state.paused ? 0 : state.pointerActive);
    gl.uniform1f(u.uAspect, state.aspect);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, gpu.cover); gl.uniform1i(u.uCover, 1);
    gl.uniform1f(u.uCoverLoaded, Number(state.coverLoaded)); gl.uniform2fv(u.uCoverScale, coverScale);
    gl.bindBuffer(gl.ARRAY_BUFFER, gpu.meshBuffer);
    attribute(gpu.mesh, 'aPosition', 3, 40, 0); attribute(gpu.mesh, 'aNormal', 3, 40, 12);
    attribute(gpu.mesh, 'aUV', 2, 40, 24); attribute(gpu.mesh, 'aMaterial', 1, 40, 32); attribute(gpu.mesh, 'aSide', 1, 40, 36);
    gl.drawArrays(gl.TRIANGLES, 0, meshData.length / 10);
    // No invisible body may occlude particles while the handset is dispersed.
    if (state.scatter > .5) gl.clear(gl.DEPTH_BUFFER_BIT);
    common(gpu.points); u = gpu.points.uniforms;
    gl.uniform1f(u.uDpr, canvas.width / state.width); gl.uniform1f(u.uTime, state.time); gl.uniform1f(u.uScatter, state.scatter + state.pointerActive * .2);
    gl.bindBuffer(gl.ARRAY_BUFFER, gpu.positionBuffer); gl.bufferSubData(gl.ARRAY_BUFFER, 0, positions);
    attribute(gpu.points, 'aPosition', 3, 12, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, gpu.attributeBuffer); attribute(gpu.points, 'aMeta', 4, 16, 0);
    gl.depthMask(false); gl.drawArrays(gl.POINTS, 0, count); gl.depthMask(true);
  }
  function frame(time) {
    state.request = 0;
    if (state.paused || !state.visible || document.hidden || state.lost) { state.lastTime = 0; return; }
    const dt = Math.min(.035, state.lastTime ? (time - state.lastTime) / 1000 : 1 / 60);
    state.lastTime = time; state.time += dt; update(dt); draw();
    state.request = requestAnimationFrame(frame);
  }
  function wake() {
    if (!state.request && !state.paused && state.visible && !document.hidden && !state.lost) state.request = requestAnimationFrame(frame);
  }
  function stop() { cancelAnimationFrame(state.request); state.request = 0; state.lastTime = 0; }
  function resize() {
    const rect = canvas.getBoundingClientRect();
    state.width = rect.width; state.height = rect.height;
    if (rect.width < 2 || rect.height < 2) return;
    state.aspect = rect.width / rect.height;
    const dpr = Math.min(devicePixelRatio || 1, 1.75, 1800 / Math.max(rect.width, rect.height));
    canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
    state.camera = Math.max(7.3, 4.85 / state.aspect / (2 * Math.tan(FOV / 2)));
    projection.fill(0);
    const f = 1 / Math.tan(FOV / 2), near = .1, far = 40;
    projection[0] = f / state.aspect; projection[5] = f;
    projection[10] = (far + near) / (near - far); projection[11] = -1; projection[14] = (2 * far * near) / (near - far);
    draw(); wake();
  }
  function setPaused(value) {
    state.paused = value; state.pointerTarget = 0; state.pointerActive = 0;
    if (pauseButton) {
      pauseButton.setAttribute('aria-pressed', String(value));
      pauseButton.textContent = sceneText(value ? 'Activer l’animation' : 'Pause');
    }
    canvas.dataset.scenePaused = String(value);
    if (value) { stop(); snap(); draw(); } else wake();
  }
  function setFold(value) {
    state.foldTarget = clamp(value, 0, 1); state.explicitFold = true;
    if (slider) slider.value = String(Math.round(state.foldTarget * 100));
    const foldButton = document.querySelector('[data-scene-action="fold"]');
    if (foldButton) { foldButton.setAttribute('aria-pressed', String(state.foldTarget > .5)); foldButton.textContent = sceneText(state.foldTarget > .5 ? 'Déplier' : 'Plier'); }
    if (state.paused) { snap(); draw(); } else wake();
    announce(state.foldTarget > .8 ? 'Fold replié. Faites-le pivoter pour voir l’écran externe et les caméras.' : 'Charnière articulée. Faites glisser le Fold pour le faire pivoter.');
  }
  function explode() {
    if (state.lost || !gpu) return;
    if (state.paused) setPaused(false); // An explicit request to animate.
    for (let i = 0; i < count; i++) {
      const p = i * 3, b = i * 9;
      const theta = base[b + 8] * TAU;
      const z = random() * 2 - 1;
      const radius = Math.sqrt(1 - z * z);
      const impulse = 6 + random() * 5;
      velocities[p] += Math.cos(theta) * radius * impulse;
      velocities[p + 1] += Math.sin(theta) * radius * impulse;
      velocities[p + 2] += z * impulse;
    }
    announce('Le Fold se disperse en particules, puis se recompose.'); wake();
  }
  function reset() {
    state.yawTarget = -.27; state.pitchTarget = .12; state.scrollTarget = 0;
    state.pointerTarget = 0; state.pointerActive = 0;
    setFold(0);
    if (state.paused) { snap(); draw(); }
    announce('Vue initiale. Survolez pour déplacer les particules, faites glisser pour pivoter.');
  }
  function assembleEntrance() {
    // The opening motion makes the construction legible: a cloud of the same
    // screen pixels and metal edges converges into the articulated handset.
    // It never runs for a visitor who requested reduced motion.
    for (let i = 0; i < count; i++) {
      const p = i * 3, b = i * 9;
      const angle = base[b + 8] * TAU;
      const reach = 1.25 + random() * 1.55;
      positions[p] += Math.cos(angle) * reach;
      positions[p + 1] += Math.sin(angle) * reach * .72;
      positions[p + 2] += (random() - .5) * 2.5;
      velocities[p] = -Math.sin(angle) * 1.8;
      velocities[p + 1] = Math.cos(angle) * 1.8;
    }
    state.scatter = 1.5;
  }
  function pointer(event) {
    const rect = canvas.getBoundingClientRect();
    state.pointerX = (event.clientX - rect.left) / Math.max(1, rect.width) * 2 - 1;
    state.pointerY = 1 - (event.clientY - rect.top) / Math.max(1, rect.height) * 2;
  }
  canvas.addEventListener('pointerdown', event => {
    if (state.lost || !gpu || event.button !== 0 || state.pointerDown) return;
    state.pointerDown = true; state.pointerId = event.pointerId; state.travel = 0;
    state.previousX = event.clientX; state.previousY = event.clientY;
    canvas.setPointerCapture(event.pointerId); pointer(event);
    state.pointerTarget = state.paused ? 0 : 1;
    canvas.dataset.dragging = 'true'; wake();
  });
  canvas.addEventListener('pointermove', event => {
    if (state.lost || !gpu) return;
    pointer(event);
    state.pointerTarget = state.paused ? 0 : 1;
    if (state.pointerDown && event.pointerId === state.pointerId) {
      const dx = event.clientX - state.previousX, dy = event.clientY - state.previousY;
      state.travel += Math.abs(dx) + Math.abs(dy);
      state.yawTarget += dx * .007;
      state.pitchTarget = clamp(state.pitchTarget + dy * .005, -.75, .75);
      state.previousX = event.clientX; state.previousY = event.clientY;
      if (state.paused) { snap(); draw(); }
    }
    wake();
  });
  function endPointer(event) {
    if (event.pointerId !== state.pointerId) return;
    const clicked = state.travel < 7 && event.type === 'pointerup';
    state.pointerDown = false; state.pointerId = null; canvas.dataset.dragging = 'false';
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (event.pointerType !== 'mouse') state.pointerTarget = 0;
    if (clicked && !state.paused) explode();
  }
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);
  canvas.addEventListener('pointerleave', () => { if (!state.pointerDown) state.pointerTarget = 0; });
  canvas.addEventListener('keydown', event => {
    if (state.lost || !gpu) return;
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', ' ', 'Escape'].includes(event.key)) event.preventDefault();
    switch (event.key) {
      case 'ArrowLeft': state.yawTarget -= .18; break;
      case 'ArrowRight': state.yawTarget += .18; break;
      case 'ArrowUp': state.pitchTarget = clamp(state.pitchTarget - .12, -.75, .75); break;
      case 'ArrowDown': state.pitchTarget = clamp(state.pitchTarget + .12, -.75, .75); break;
      case ' ': setFold(state.foldTarget > .5 ? 0 : 1); break;
      case 'Escape': reset(); break;
      default: return;
    }
    if (state.paused) { snap(); draw(); } else wake();
  });
  document.querySelectorAll('[data-scene-action]').forEach(button => {
    button.addEventListener('click', () => {
      switch (button.dataset.sceneAction) {
        case 'fold': setFold(state.foldTarget > .5 ? 0 : 1); break;
        case 'explode': explode(); break;
        case 'reset': reset(); break;
        case 'pause': setPaused(!state.paused); announce(state.paused ? 'Animation en pause. La rotation et la charnière restent disponibles.' : 'Animation active. Les particules réagissent au pointeur et au toucher.'); break;
      }
    });
  });
  slider?.addEventListener('input', () => setFold(Number(slider.value) / 100));
  // Small scroll-driven rotation reveals the depth without taking control of
  // scrolling or overriding a hinge angle selected by the visitor.
  const onScroll = () => {
    if (!state.visible || state.paused || state.pointerDown) return;
    const rect = stage.getBoundingClientRect();
    state.scrollTarget = clamp(-rect.top / Math.max(1, innerHeight), -.5, 1);
    wake();
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else wake(); });
  reducedMotion.addEventListener('change', event => setPaused(event.matches));
  new ResizeObserver(resize).observe(canvas);
  new IntersectionObserver(entries => {
    state.visible = entries[0].isIntersecting;
    if (state.visible) wake(); else stop();
  }, { rootMargin: '100px', threshold: 0 }).observe(stage);
  canvas.addEventListener('webglcontextlost', event => {
    event.preventDefault(); suspendGraphics('Scène suspendue pendant la restauration graphique.');
  });
  canvas.addEventListener('webglcontextrestored', () => initializeGraphics(true));

  initializeGraphics();
}

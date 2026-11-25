// SCOUT Studio — Pure WebGL2 3D Terrain, Drone Fleet & Sensor Frustum Engine + 2D HUD Overlay.
import {cellColorRgb, errorColorRgb, rgbCss} from './replay.mjs';

// ---- Minimal mat4 / vec3 math (column-major for WebGL) ----
function mat4Identity() {
  const m = new Float32Array(16);
  m[0] = m[5] = m[10] = m[15] = 1;
  return m;
}

function mat4Multiply(a, b) {
  const out = new Float32Array(16);
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      out[c * 4 + r] =
        a[0 * 4 + r] * b[c * 4 + 0] +
        a[1 * 4 + r] * b[c * 4 + 1] +
        a[2 * 4 + r] * b[c * 4 + 2] +
        a[3 * 4 + r] * b[c * 4 + 3];
    }
  }
  return out;
}

function mat4Perspective(fovRad, aspect, near, far) {
  const f = 1 / Math.tan(fovRad / 2);
  const nf = 1 / (near - far);
  const m = new Float32Array(16);
  m[0] = f / aspect;
  m[5] = f;
  m[10] = (far + near) * nf;
  m[11] = -1;
  m[14] = 2 * far * near * nf;
  return m;
}

function mat4LookAt(eye, target, up) {
  let zx = eye[0] - target[0], zy = eye[1] - target[1], zz = eye[2] - target[2];
  let len = Math.hypot(zx, zy, zz) || 1;
  zx /= len; zy /= len; zz /= len;
  let xx = up[1] * zz - up[2] * zy;
  let xy = up[2] * zx - up[0] * zz;
  let xz = up[0] * zy - up[1] * zx;
  len = Math.hypot(xx, xy, xz) || 1;
  xx /= len; xy /= len; xz /= len;
  const yx = zy * xz - zz * xy;
  const yy = zz * xx - zx * xz;
  const yz = zx * xy - zy * xx;
  const m = new Float32Array(16);
  m[0] = xx; m[1] = yx; m[2] = zx; m[3] = 0;
  m[4] = xy; m[5] = yy; m[6] = zy; m[7] = 0;
  m[8] = xz; m[9] = yz; m[10] = zz; m[11] = 0;
  m[12] = -(xx * eye[0] + xy * eye[1] + xz * eye[2]);
  m[13] = -(yx * eye[0] + yy * eye[1] + yz * eye[2]);
  m[14] = -(zx * eye[0] + zy * eye[1] + zz * eye[2]);
  m[15] = 1;
  return m;
}

function mat4TRS(tx, ty, tz, rotY, sx, sy, sz) {
  const c = Math.cos(rotY), s = Math.sin(rotY);
  const m = new Float32Array(16);
  m[0] = c * sx;  m[1] = 0;  m[2] = -s * sx; m[3] = 0;
  m[4] = 0;       m[5] = sy; m[6] = 0;       m[7] = 0;
  m[8] = s * sz;  m[9] = 0;  m[10] = c * sz; m[11] = 0;
  m[12] = tx;     m[13] = ty; m[14] = tz;    m[15] = 1;
  return m;
}

function mat4Invert(a) {
  const out = new Float32Array(16);
  const a00 = a[0], a01 = a[1], a02 = a[2], a03 = a[3];
  const a10 = a[4], a11 = a[5], a12 = a[6], a13 = a[7];
  const a20 = a[8], a21 = a[9], a22 = a[10], a23 = a[11];
  const a30 = a[12], a31 = a[13], a32 = a[14], a33 = a[15];
  const b00 = a00 * a11 - a01 * a10, b01 = a00 * a12 - a02 * a10, b02 = a00 * a13 - a03 * a10;
  const b03 = a01 * a12 - a02 * a11, b04 = a01 * a13 - a03 * a11, b05 = a02 * a13 - a03 * a12;
  const b06 = a20 * a31 - a21 * a30, b07 = a20 * a32 - a22 * a30, b08 = a20 * a33 - a23 * a30;
  const b09 = a21 * a32 - a22 * a31, b10 = a21 * a33 - a23 * a31, b11 = a22 * a33 - a23 * a32;
  let det = b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06;
  if (!det) return null;
  det = 1 / det;
  out[0] = (a11 * b11 - a12 * b10 + a13 * b09) * det;
  out[1] = (a02 * b10 - a01 * b11 - a03 * b09) * det;
  out[2] = (a31 * b05 - a32 * b04 + a33 * b03) * det;
  out[3] = (a22 * b04 - a21 * b05 - a23 * b03) * det;
  out[4] = (a12 * b08 - a10 * b11 - a13 * b07) * det;
  out[5] = (a00 * b11 - a02 * b08 + a03 * b07) * det;
  out[6] = (a32 * b02 - a30 * b05 - a33 * b01) * det;
  out[7] = (a20 * b05 - a22 * b02 + a23 * b01) * det;
  out[8] = (a10 * b10 - a11 * b08 + a13 * b06) * det;
  out[9] = (a01 * b08 - a00 * b10 - a03 * b06) * det;
  out[10] = (a30 * b04 - a31 * b02 + a33 * b00) * det;
  out[11] = (a21 * b02 - a20 * b04 - a23 * b00) * det;
  out[12] = (a11 * b07 - a10 * b09 - a12 * b06) * det;
  out[13] = (a00 * b09 - a01 * b07 + a02 * b06) * det;
  out[14] = (a31 * b01 - a30 * b03 - a32 * b00) * det;
  out[15] = (a20 * b03 - a21 * b01 + a22 * b00) * det;
  return out;
}

function projectPoint(vp, x, y, z, w, h) {
  const cx = vp[0] * x + vp[4] * y + vp[8] * z + vp[12];
  const cy = vp[1] * x + vp[5] * y + vp[9] * z + vp[13];
  const cz = vp[2] * x + vp[6] * y + vp[10] * z + vp[14];
  const cw = vp[3] * x + vp[7] * y + vp[11] * z + vp[15];
  if (cw <= 0.01) return null;
  const ndcX = cx / cw, ndcY = cy / cw, ndcZ = cz / cw;
  if (ndcZ < -1 || ndcZ > 1) return null;
  return [(ndcX * 0.5 + 0.5) * w, (0.5 - ndcY * 0.5) * h, cw];
}

// ---- WebGL2 Shaders ----
const TERRAIN_VS = `#version 300 es
precision highp float;
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNorm;
layout(location=2) in vec2 aUv;
uniform mat4 uVP;
out vec3 vNorm;
out vec2 vUv;
out vec3 vWorld;
void main() {
  vNorm = aNorm;
  vUv = aUv;
  vWorld = aPos;
  gl_Position = uVP * vec4(aPos, 1.0);
}`;

const TERRAIN_FS = `#version 300 es
precision highp float;
in vec3 vNorm;
in vec2 vUv;
in vec3 vWorld;
uniform sampler2D uTexEst;
uniform sampler2D uTexRef;
uniform vec2 uGridSize;
uniform int uSplitEnabled;
uniform float uSplitRatio;
uniform int uShowGrid;
uniform vec2 uHoverCell;
uniform int uDark;
out vec4 outColor;
void main() {
  vec3 texCol = (uSplitEnabled == 1 && vUv.x > uSplitRatio)
    ? texture(uTexRef, vUv).rgb
    : texture(uTexEst, vUv).rgb;

  // Directional sunlight + hemisphere ambient fill
  vec3 N = normalize(vNorm);
  vec3 sunDir = normalize(vec3(0.45, 0.85, 0.35));
  float diff = max(dot(N, sunDir), 0.0);
  float hemi = 0.5 + 0.5 * N.y;
  vec3 light = mix(vec3(0.54, 0.58, 0.66), vec3(1.06, 1.04, 0.98), 0.45 * hemi + 0.55 * diff);
  vec3 col = texCol * light;

  // Crisp subtle grid lines in shader
  if (uShowGrid == 1) {
    vec2 cellCoord = vUv * uGridSize;
    vec2 f = abs(fract(cellCoord - 0.5) - 0.5) / max(fwidth(cellCoord), vec2(0.0001));
    float line = 1.0 - min(min(f.x, f.y), 1.0);
    vec3 gridCol = uDark == 1 ? vec3(0.04, 0.07, 0.11) : vec3(0.14, 0.22, 0.19);
    col = mix(col, gridCol, line * 0.26);
  }

  // Hover cell crisp white highlight
  if (uHoverCell.x >= 0.0) {
    vec2 cid = floor(vUv * uGridSize);
    if (cid.x == uHoverCell.x && cid.y == uHoverCell.y) {
      vec2 fc = fract(vUv * uGridSize);
      float edge = max(step(fc.x, 0.09) + step(0.91, fc.x), step(fc.y, 0.09) + step(0.91, fc.y));
      col = mix(col, vec3(1.0), clamp(edge * 0.85 + 0.14, 0.0, 1.0));
    }
  }

  // Glowing split-screen divider line directly on terrain
  if (uSplitEnabled == 1) {
    float dist = abs(vUv.x - uSplitRatio) / max(fwidth(vUv.x), 0.0001);
    float divider = 1.0 - smoothstep(0.5, 2.2, dist);
    col = mix(col, vec3(1.0), divider);
  }

  outColor = vec4(col, 1.0);
}`;

const SOLID_VS = `#version 300 es
precision highp float;
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNorm;
uniform mat4 uVP;
uniform mat4 uModel;
out vec3 vNorm;
void main() {
  vNorm = mat3(uModel) * aNorm;
  gl_Position = uVP * uModel * vec4(aPos, 1.0);
}`;

const SOLID_FS = `#version 300 es
precision highp float;
in vec3 vNorm;
uniform vec4 uColor;
uniform float uUnlit;
out vec4 outColor;
void main() {
  vec3 N = normalize(vNorm);
  vec3 L = normalize(vec3(0.45, 0.85, 0.35));
  float shade = mix(0.58 + 0.42 * max(dot(N, L), 0.0), 1.0, uUnlit);
  outColor = vec4(uColor.rgb * shade, uColor.a);
}`;

const LINE_VS = `#version 300 es
precision highp float;
layout(location=0) in vec3 aPos;
uniform mat4 uVP;
void main() {
  gl_Position = uVP * vec4(aPos, 1.0);
}`;

const LINE_FS = `#version 300 es
precision highp float;
uniform vec4 uColor;
out vec4 outColor;
void main() {
  outColor = uColor;
}`;

function compileShader(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    throw new Error('WebGL shader error: ' + gl.getShaderInfoLog(sh));
  }
  return sh;
}

function createProgram(gl, vsSrc, fsSrc) {
  const prog = gl.createProgram();
  gl.attachShader(prog, compileShader(gl, gl.VERTEX_SHADER, vsSrc));
  gl.attachShader(prog, compileShader(gl, gl.FRAGMENT_SHADER, fsSrc));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    throw new Error('WebGL link error: ' + gl.getProgramInfoLog(prog));
  }
  return prog;
}

// Build a unit cube (pos + norm) for procedural drone/rover/skirt assembly.
function createUnitBoxMesh(gl) {
  const faces = [
    [[0, 0, 1],  [-.5,-.5,.5], [.5,-.5,.5], [.5,.5,.5], [-.5,.5,.5]],
    [[0, 0, -1], [.5,-.5,-.5], [-.5,-.5,-.5], [-.5,.5,-.5], [.5,.5,-.5]],
    [[0, 1, 0],  [-.5,.5,.5], [.5,.5,.5], [.5,.5,-.5], [-.5,.5,-.5]],
    [[0, -1, 0], [-.5,-.5,-.5], [.5,-.5,-.5], [.5,-.5,.5], [-.5,-.5,.5]],
    [[1, 0, 0],  [.5,-.5,.5], [.5,-.5,-.5], [.5,.5,-.5], [.5,.5,.5]],
    [[-1, 0, 0], [-.5,-.5,-.5], [-.5,-.5,.5], [-.5,.5,.5], [-.5,.5,-.5]],
  ];
  const verts = [], idx = [];
  let base = 0;
  for (const [n, a, b, c, d] of faces) {
    for (const p of [a, b, c, d]) verts.push(p[0], p[1], p[2], n[0], n[1], n[2]);
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
    base += 4;
  }
  return uploadIndexedMesh(gl, new Float32Array(verts), new Uint16Array(idx), [3, 3]);
}

function createUnitDiscMesh(gl, segments = 20) {
  const verts = [0, 0, 0, 0, 1, 0];
  const idx = [];
  for (let i = 0; i <= segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    verts.push(Math.cos(a) * 0.5, 0, Math.sin(a) * 0.5, 0, 1, 0);
    if (i > 0) idx.push(0, i, i + 1);
  }
  return uploadIndexedMesh(gl, new Float32Array(verts), new Uint16Array(idx), [3, 3]);
}

function uploadIndexedMesh(gl, vertexData, indexData, attrs) {
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const vbo = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, vertexData, gl.STATIC_DRAW);
  const stride = attrs.reduce((s, n) => s + n, 0) * 4;
  let offset = 0;
  attrs.forEach((count, loc) => {
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, count, gl.FLOAT, false, stride, offset);
    offset += count * 4;
  });
  const ibo = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indexData, gl.STATIC_DRAW);
  gl.bindVertexArray(null);
  return {
    vao, vbo, ibo,
    count: indexData.length,
    indexType: indexData instanceof Uint32Array ? gl.UNSIGNED_INT : gl.UNSIGNED_SHORT,
  };
}

export class Renderer3D {
  constructor(glCanvas, hudCanvas) {
    this.glCanvas = glCanvas;
    this.hudCanvas = hudCanvas;
    this.hudCtx = hudCanvas.getContext('2d');
    this.gl = glCanvas.getContext('webgl2', {antialias: true, alpha: false, preserveDrawingBuffer: false});
    this.supported = Boolean(this.gl);

    // Camera orbit parameters
    this.yaw = -0.62;
    this.pitch = 0.72;
    this.distance = 22;
    this.target = [0, 0.4, 0];
    this.hoverCell = null;

    this._lastVP = null;
    this._lastInvVP = null;
    this._lastReplay = null;
    this._terrainKey = '';
    this._texKey = '';
    this._terrainMesh = null;
    this._skirtMesh = null;
    this._heightGrid = null;
    this._meanHeight = 0;
    this._worldSpan = 16;

    if (this.supported) this._initGL();
  }

  _initGL() {
    const gl = this.gl;
    this.progTerrain = createProgram(gl, TERRAIN_VS, TERRAIN_FS);
    this.progSolid = createProgram(gl, SOLID_VS, SOLID_FS);
    this.progLine = createProgram(gl, LINE_VS, LINE_FS);

    this.boxMesh = createUnitBoxMesh(gl);
    this.discMesh = createUnitDiscMesh(gl, 20);

    // Dynamic buffers for lines & translucent frustums
    this.dynVao = gl.createVertexArray();
    this.dynVbo = gl.createBuffer();
    gl.bindVertexArray(this.dynVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.dynVbo);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 12, 0);
    gl.bindVertexArray(null);

    this.frustumVao = gl.createVertexArray();
    this.frustumVbo = gl.createBuffer();
    gl.bindVertexArray(this.frustumVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.frustumVbo);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 24, 0);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 24, 12);
    gl.bindVertexArray(null);

    this.texEst = this._createTexture();
    this.texRef = this._createTexture();
  }

  _createTexture() {
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return tex;
  }

  fitToReplay(replay) {
    const {width, height, cell_size_m} = replay.data.grid;
    const span = Math.max(width, height) * cell_size_m;
    this._worldSpan = span;
    this.distance = span * 1.48;
    this.target = [0, 0.85, 0];
    this.yaw = -0.62;
    this.pitch = 0.72;
  }

  setPreset(name, replay) {
    const span = this._worldSpan || 16;
    if (name === 'iso') {
      this.yaw = -0.62; this.pitch = 0.72; this.distance = span * 1.48; this.target = [0, 0.85, 0];
    } else if (name === 'top') {
      this.yaw = 0; this.pitch = 1.46; this.distance = span * 1.48; this.target = [0, 0, 0];
    } else if (name === 'low') {
      this.yaw = -0.45; this.pitch = 0.34; this.distance = span * 1.15; this.target = [0, 1.5, 0];
    } else if (name === 'reset') {
      if (replay) this.fitToReplay(replay);
    }
  }

  orbitBy(dx, dy) {
    this.yaw -= dx * 0.007;
    this.pitch = Math.max(0.14, Math.min(1.52, this.pitch + dy * 0.0065));
  }

  panBy(dx, dy) {
    const scale = this.distance * 0.0014;
    const rx = Math.cos(this.yaw), rz = -Math.sin(this.yaw);
    const fx = -Math.sin(this.yaw), fz = -Math.cos(this.yaw);
    this.target[0] += (-dx * rx + dy * fx) * scale;
    this.target[2] += (-dx * rz + dy * fz) * scale;
  }

  zoomBy(factor) {
    const span = this._worldSpan || 16;
    this.distance = Math.max(span * 0.3, Math.min(span * 3.5, this.distance * factor));
  }

  _gridToWorldXZ(replay, gx, gy) {
    const {width, height, cell_size_m} = replay.data.grid;
    return [
      (gx - width / 2) * cell_size_m,
      (gy - height / 2) * cell_size_m,
    ];
  }

  _terrainYAt(replay, gx, gy) {
    if (!this._heightGrid) return 0;
    const {width, height} = replay.data.grid;
    const vx = Math.max(0, Math.min(width, gx));
    const vz = Math.max(0, Math.min(height, gy));
    const x0 = Math.min(width - 1, Math.floor(vx));
    const z0 = Math.min(height - 1, Math.floor(vz));
    const fx = vx - x0, fz = vz - z0;
    const stride = width + 1;
    const h00 = this._heightGrid[z0 * stride + x0];
    const h10 = this._heightGrid[z0 * stride + x0 + 1];
    const h01 = this._heightGrid[(z0 + 1) * stride + x0];
    const h11 = this._heightGrid[(z0 + 1) * stride + x0 + 1];
    return (h00 * (1 - fx) + h10 * fx) * (1 - fz) + (h01 * (1 - fx) + h11 * fx) * fz;
  }

  screenToCell(sx, sy) {
    if (!this._lastInvVP || !this._lastReplay) return null;
    const w = this.glCanvas.clientWidth, h = this.glCanvas.clientHeight;
    if (!w || !h) return null;
    const nx = (sx / w) * 2 - 1;
    const ny = 1 - (sy / h) * 2;
    const inv = this._lastInvVP;

    const unproject = ndcZ => {
      const x = inv[0] * nx + inv[4] * ny + inv[8] * ndcZ + inv[12];
      const y = inv[1] * nx + inv[5] * ny + inv[9] * ndcZ + inv[13];
      const z = inv[2] * nx + inv[6] * ny + inv[10] * ndcZ + inv[14];
      const cw = inv[3] * nx + inv[7] * ny + inv[11] * ndcZ + inv[15];
      return [x / cw, y / cw, z / cw];
    };
    const p0 = unproject(-1);
    const p1 = unproject(1);
    const dy = p1[1] - p0[1];
    if (Math.abs(dy) < 1e-6) return null;
    const t = (this._meanHeight - p0[1]) / dy;
    if (t < 0) return null;
    const wx = p0[0] + (p1[0] - p0[0]) * t;
    const wz = p0[2] + (p1[2] - p0[2]) * t;
    const {width, height, cell_size_m} = this._lastReplay.data.grid;
    const gx = Math.floor(wx / cell_size_m + width / 2);
    const gy = Math.floor(wz / cell_size_m + height / 2);
    if (gx < 0 || gy < 0 || gx >= width || gy >= height) return null;
    return {x: gx, y: gy};
  }

  _ensureTerrainMesh(replay, state, compareMode, verticalExag) {
    const gl = this.gl;
    const elevId = replay.elevationLayerId;
    const refMode = compareMode === 'reference';
    const key = `${replay.data.title}|${elevId ? state.frameIndex : 'sem'}|${refMode}|${verticalExag.toFixed(2)}`;
    if (key === this._terrainKey && this._terrainMesh) return;
    this._terrainKey = key;

    const {width, height, cell_size_m} = replay.data.grid;
    const cellHeights = new Float32Array(width * height);
    let minH = Infinity, maxH = -Infinity;

    if (elevId) {
      const refVals = replay.data.reference_layers?.[elevId];
      const vals = (refMode && refVals) ? refVals : (state.frame.layers[elevId] || refVals);
      const style = replay.styles.get(elevId);
      const fallback = style ? (style.domain[0] + style.domain[1]) * 0.5 : 0;
      for (let i = 0; i < width * height; i++) {
        const v = vals?.[i];
        const h = Number.isFinite(v) ? v : fallback;
        cellHeights[i] = h;
        if (h < minH) minH = h;
        if (h > maxH) maxH = h;
      }
      // Shift so min height sits cleanly near 0
      const base = Number.isFinite(minH) ? minH : 0;
      for (let i = 0; i < cellHeights.length; i++) {
        cellHeights[i] = (cellHeights[i] - base) * verticalExag;
      }
    } else {
      // Subtle relief for semantic-only maps (uses reference or fused class for clean physical texture)
      const semLayer = replay.data.reference_layers?.fused || state.frame.layers.fused || state.frame.layers[replay.data.layers[0].id];
      for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
          const i = y * width + x;
          const v = semLayer?.[i];
          const s = String(v || '').toLowerCase();
          let h = 0;
          if (s.includes('rock') || s.includes('bedrock')) h = 0.24;
          else if (s.includes('veg')) h = 0.10;
          else if (s.includes('gravel')) h = 0.06;
          // Gentle rolling topography wave so 3D diorama has subtle depth
          const wave = 0.06 * Math.sin(x * 0.28) * Math.cos(y * 0.25);
          cellHeights[i] = (h + wave + 0.06) * verticalExag;
        }
      }
    }

    // Build (width+1) x (height+1) vertex height grid by averaging adjacent cells
    const stride = width + 1;
    const vH = new Float32Array((width + 1) * (height + 1));
    let sumH = 0;
    for (let z = 0; z <= height; z++) {
      for (let x = 0; x <= width; x++) {
        let sum = 0, cnt = 0;
        for (const dz of [-1, 0]) {
          for (const dx of [-1, 0]) {
            const cx = x + dx, cz = z + dz;
            if (cx >= 0 && cx < width && cz >= 0 && cz < height) {
              sum += cellHeights[cz * width + cx];
              cnt++;
            }
          }
        }
        const hVal = cnt ? sum / cnt : 0;
        vH[z * stride + x] = hVal;
        sumH += hVal;
      }
    }
    this._heightGrid = vH;
    this._meanHeight = sumH / vH.length;

    // Build terrain vertex buffer (pos3 + norm3 + uv2)
    const verts = new Float32Array((width + 1) * (height + 1) * 8);
    let ptr = 0;
    for (let z = 0; z <= height; z++) {
      for (let x = 0; x <= width; x++) {
        const wx = (x - width / 2) * cell_size_m;
        const wz = (z - height / 2) * cell_size_m;
        const wy = vH[z * stride + x];

        const hL = vH[z * stride + Math.max(0, x - 1)];
        const hR = vH[z * stride + Math.min(width, x + 1)];
        const hU = vH[Math.max(0, z - 1) * stride + x];
        const hD = vH[Math.min(height, z + 1) * stride + x];
        let nx = (hL - hR) / (2 * cell_size_m);
        let ny = 1;
        let nz = (hU - hD) / (2 * cell_size_m);
        const nl = Math.hypot(nx, ny, nz) || 1;
        nx /= nl; ny /= nl; nz /= nl;

        verts[ptr++] = wx; verts[ptr++] = wy; verts[ptr++] = wz;
        verts[ptr++] = nx; verts[ptr++] = ny; verts[ptr++] = nz;
        verts[ptr++] = x / width; verts[ptr++] = z / height;
      }
    }

    const indices = new Uint32Array(width * height * 6);
    let ip = 0;
    for (let z = 0; z < height; z++) {
      for (let x = 0; x < width; x++) {
        const a = z * stride + x;
        const b = a + 1;
        const c = a + stride;
        const d = c + 1;
        indices[ip++] = a; indices[ip++] = c; indices[ip++] = b;
        indices[ip++] = b; indices[ip++] = c; indices[ip++] = d;
      }
    }

    if (this._terrainMesh) {
      gl.deleteVertexArray(this._terrainMesh.vao);
      gl.deleteBuffer(this._terrainMesh.vbo);
      gl.deleteBuffer(this._terrainMesh.ibo);
    }
    this._terrainMesh = uploadIndexedMesh(gl, verts, indices, [3, 3, 2]);

    // Build clean architectural pedestal skirt around all 4 edges
    const baseY = -Math.max(0.45, this._worldSpan * 0.045);
    const sVerts = [];
    const sIdx = [];
    const addSide = (points, normal) => {
      const start = sVerts.length / 6;
      for (let i = 0; i < points.length; i++) {
        const [px, py, pz] = points[i];
        sVerts.push(px, py, pz, normal[0], normal[1], normal[2]);
        sVerts.push(px, baseY, pz, normal[0], normal[1], normal[2]);
        if (i > 0) {
          const k = start + (i - 1) * 2;
          sIdx.push(k, k + 1, k + 2, k + 2, k + 1, k + 3);
        }
      }
    };
    const north = [], south = [], west = [], east = [];
    for (let x = 0; x <= width; x++) {
      const wx = (x - width / 2) * cell_size_m;
      north.push([wx, vH[x], (-height / 2) * cell_size_m]);
      south.push([wx, vH[height * stride + x], (height / 2) * cell_size_m]);
    }
    for (let z = 0; z <= height; z++) {
      const wz = (z - height / 2) * cell_size_m;
      west.push([(-width / 2) * cell_size_m, vH[z * stride], wz]);
      east.push([(width / 2) * cell_size_m, vH[z * stride + width], wz]);
    }
    addSide(north.reverse(), [0, 0, -1]);
    addSide(south, [0, 0, 1]);
    addSide(west, [-1, 0, 0]);
    addSide(east.reverse(), [1, 0, 0]);

    if (this._skirtMesh) {
      gl.deleteVertexArray(this._skirtMesh.vao);
      gl.deleteBuffer(this._skirtMesh.vbo);
      gl.deleteBuffer(this._skirtMesh.ibo);
    }
    this._skirtMesh = uploadIndexedMesh(gl, new Float32Array(sVerts), new Uint32Array(sIdx), [3, 3]);
  }

  _ensureTextures(replay, state, layerId, compareMode, showUncertainty, darkTheme) {
    const gl = this.gl;
    const key = `${replay.data.title}|${state.frameIndex}|${layerId}|${compareMode}|${showUncertainty}|${darkTheme}`;
    if (key === this._texKey) return;
    this._texKey = key;

    const {width, height} = replay.data.grid;
    const style = replay.styles.get(layerId);
    const refStyle = replay.referenceStyles.get(layerId);
    const estVals = state.frame.layers[layerId];
    const refVals = replay.data.reference_layers?.[layerId] || null;
    const confVals = showUncertainty && replay.confidenceLayerId ? state.frame.layers[replay.confidenceLayerId] : null;
    const domainSpan = style ? Math.max(1e-6, style.domain[1] - style.domain[0]) : 1;

    const upload = (tex, mode) => {
      const data = new Uint8Array(width * height * 4);
      for (let i = 0; i < width * height; i++) {
        let rgb;
        if (mode === 'reference' && refVals) {
          rgb = cellColorRgb(refStyle || style, refVals[i], darkTheme);
        } else if (mode === 'error' && refVals) {
          rgb = errorColorRgb(style.layer.kind, estVals?.[i], refVals[i], domainSpan, darkTheme);
        } else {
          rgb = cellColorRgb(style, estVals?.[i], darkTheme);
          if (confVals && estVals?.[i] != null && confVals[i] != null) {
            const c = Math.max(0, Math.min(1, confVals[i]));
            const keep = 0.42 + 0.58 * c;
            const bg = darkTheme ? 22 : 210;
            rgb = [
              Math.round(bg + (rgb[0] - bg) * keep),
              Math.round(bg + (rgb[1] - bg) * keep),
              Math.round(bg + (rgb[2] - bg) * keep),
            ];
          }
        }
        const p = i * 4;
        data[p] = rgb[0]; data[p + 1] = rgb[1]; data[p + 2] = rgb[2]; data[p + 3] = 255;
      }
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    };

    upload(this.texEst, compareMode === 'split' ? 'estimate' : compareMode);
    if (refVals) upload(this.texRef, 'reference');
  }

  _drawSolid(mesh, vp, model, rgba, unlit = 0) {
    const gl = this.gl;
    gl.useProgram(this.progSolid);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.progSolid, 'uVP'), false, vp);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.progSolid, 'uModel'), false, model);
    gl.uniform4fv(gl.getUniformLocation(this.progSolid, 'uColor'), rgba);
    gl.uniform1f(gl.getUniformLocation(this.progSolid, 'uUnlit'), unlit);
    gl.bindVertexArray(mesh.vao);
    gl.drawElements(gl.TRIANGLES, mesh.count, mesh.indexType, 0);
  }

  _drawLines(points, vp, rgba, mode = null) {
    if (!points.length) return;
    const gl = this.gl;
    gl.useProgram(this.progLine);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.progLine, 'uVP'), false, vp);
    gl.uniform4fv(gl.getUniformLocation(this.progLine, 'uColor'), rgba);
    gl.bindVertexArray(this.dynVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.dynVbo);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(points), gl.DYNAMIC_DRAW);
    gl.drawArrays(mode ?? gl.LINE_STRIP, 0, points.length / 3);
  }

  _drawFrustum(apex, corners, vp, rgb, alpha) {
    const gl = this.gl;
    const [ax, ay, az] = apex;
    const verts = [];
    const pushTri = (p1, p2, p3) => {
      const ux = p2[0] - p1[0], uy = p2[1] - p1[1], uz = p2[2] - p1[2];
      const vx = p3[0] - p1[0], vy = p3[1] - p1[1], vz = p3[2] - p1[2];
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      verts.push(...p1, nx, ny, nz, ...p2, nx, ny, nz, ...p3, nx, ny, nz);
    };
    for (let i = 0; i < 4; i++) {
      pushTri([ax, ay, az], corners[i], corners[(i + 1) % 4]);
    }
    // Ground footprint quad tinted
    pushTri(corners[0], corners[1], corners[2]);
    pushTri(corners[0], corners[2], corners[3]);

    gl.useProgram(this.progSolid);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.progSolid, 'uVP'), false, vp);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.progSolid, 'uModel'), false, mat4Identity());
    gl.uniform4f(gl.getUniformLocation(this.progSolid, 'uColor'), rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, alpha);
    gl.uniform1f(gl.getUniformLocation(this.progSolid, 'uUnlit'), 1.0);
    gl.bindVertexArray(this.frustumVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.frustumVbo);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.DYNAMIC_DRAW);
    gl.drawArrays(gl.TRIANGLES, 0, verts.length / 6);

    // Wireframe frustum rays + ground border
    const linePts = [];
    for (let i = 0; i < 4; i++) {
      linePts.push(ax, ay, az, ...corners[i]);
      linePts.push(...corners[i], ...corners[(i + 1) % 4]);
    }
    this._drawLines(linePts, vp, [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, Math.min(1, alpha * 3.4)], gl.LINES);
  }

  _drawDroneModel(vp, x, y, z, heading, rgb, animTime, scale) {
    const col = [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1];
    const carbon = [0.12, 0.16, 0.22, 1];
    // Central fuselage
    this._drawSolid(this.boxMesh, vp, mat4TRS(x, y, z, -heading, 0.44 * scale, 0.14 * scale, 0.34 * scale), carbon, 0);
    // Glowing top beacon
    this._drawSolid(this.boxMesh, vp, mat4TRS(x, y + 0.11 * scale, z, -heading, 0.18 * scale, 0.08 * scale, 0.18 * scale), col, 0.85);
    // Two diagonal X arms
    const armLen = 0.92 * scale;
    this._drawSolid(this.boxMesh, vp, mat4TRS(x, y, z, -heading + Math.PI / 4, armLen, 0.055 * scale, 0.065 * scale), carbon, 0);
    this._drawSolid(this.boxMesh, vp, mat4TRS(x, y, z, -heading - Math.PI / 4, armLen, 0.055 * scale, 0.065 * scale), carbon, 0);

    // 4 motor pods & spinning translucent rotor discs
    const rOff = 0.44 * scale;
    for (let i = 0; i < 4; i++) {
      const ang = -heading + Math.PI / 4 + i * (Math.PI / 2);
      const mx = x + Math.cos(ang) * rOff;
      const mz = z - Math.sin(ang) * rOff;
      this._drawSolid(this.boxMesh, vp, mat4TRS(mx, y + 0.05 * scale, mz, ang, 0.09 * scale, 0.1 * scale, 0.09 * scale), col, 0.3);
      // Spinning blade bar
      this._drawSolid(
        this.boxMesh, vp,
        mat4TRS(mx, y + 0.11 * scale, mz, animTime * 22 + i, 0.42 * scale, 0.015 * scale, 0.04 * scale),
        [0.92, 0.96, 1.0, 0.85], 0.9,
      );
      // Translucent rotor disc
      this._drawSolid(
        this.discMesh, vp,
        mat4TRS(mx, y + 0.105 * scale, mz, 0, 0.45 * scale, 1, 0.45 * scale),
        [col[0], col[1], col[2], 0.32], 1.0,
      );
    }
  }

  _drawRoverModel(vp, x, y, z, heading, rgb, animTime, scale) {
    const col = [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1];
    const bodyCol = [0.22, 0.27, 0.34, 1];
    const wheelCol = [0.09, 0.11, 0.15, 1];
    // Chassis
    this._drawSolid(this.boxMesh, vp, mat4TRS(x, y + 0.18 * scale, z, -heading, 0.62 * scale, 0.18 * scale, 0.42 * scale), bodyCol, 0);
    // Colored top deck stripe
    this._drawSolid(this.boxMesh, vp, mat4TRS(x, y + 0.28 * scale, z, -heading, 0.46 * scale, 0.05 * scale, 0.32 * scale), col, 0.35);
    // LiDAR mast & spinning sensor head
    this._drawSolid(this.boxMesh, vp, mat4TRS(x, y + 0.42 * scale, z, animTime * 4, 0.14 * scale, 0.18 * scale, 0.14 * scale), col, 0.85);
    // 6 wheels
    const cos = Math.cos(-heading), sin = Math.sin(-heading);
    for (const lx of [-0.22, 0, 0.22]) {
      for (const lz of [-0.24, 0.24]) {
        const wx = x + (lx * cos + lz * sin) * scale;
        const wz = z + (-lx * sin + lz * cos) * scale;
        this._drawSolid(this.boxMesh, vp, mat4TRS(wx, y + 0.1 * scale, wz, -heading, 0.16 * scale, 0.16 * scale, 0.08 * scale), wheelCol, 0);
      }
    }
  }

  render(replay, state, opts) {
    if (!this.supported) return;
    const {
      layerId, compareMode = 'estimate', splitRatio = 0.5,
      showUncertainty = false, showTrails = true, showPlans = true,
      showFootprints = true, showGrid = true, verticalExag = 1.0,
      darkTheme = true, animTime = 0,
    } = opts;
    this._lastReplay = replay;

    const gl = this.gl;
    const canvas = this.glCanvas;
    const ratio = Math.min(window.devicePixelRatio || 1, 2.5);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    const pw = Math.round(w * ratio), ph = Math.round(h * ratio);
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw; canvas.height = ph;
    }
    if (this.hudCanvas.width !== pw || this.hudCanvas.height !== ph) {
      this.hudCanvas.width = pw; this.hudCanvas.height = ph;
    }

    this._ensureTerrainMesh(replay, state, compareMode, verticalExag);
    this._ensureTextures(replay, state, layerId, compareMode, showUncertainty, darkTheme);

    gl.viewport(0, 0, pw, ph);
    if (darkTheme) gl.clearColor(0.047, 0.068, 0.095, 1.0);
    else gl.clearColor(0.89, 0.92, 0.90, 1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    // Camera matrices
    const eye = [
      this.target[0] + this.distance * Math.cos(this.pitch) * Math.sin(this.yaw),
      this.target[1] + this.distance * Math.sin(this.pitch),
      this.target[2] + this.distance * Math.cos(this.pitch) * Math.cos(this.yaw),
    ];
    const proj = mat4Perspective(42 * Math.PI / 180, w / h, 0.1, this._worldSpan * 15);
    const view = mat4LookAt(eye, this.target, [0, 1, 0]);
    const vp = mat4Multiply(proj, view);
    this._lastVP = vp;
    this._lastInvVP = mat4Invert(vp);

    // 1. Draw subtle reference horizon grid outside terrain
    const {width, height, cell_size_m} = replay.data.grid;
    const halfW = (width * cell_size_m) / 2;
    const halfH = (height * cell_size_m) / 2;
    const baseY = -Math.max(0.45, this._worldSpan * 0.045);

    // 2. Draw terrain pedestal skirt
    if (this._skirtMesh) {
      const skirtCol = darkTheme ? [0.11, 0.15, 0.21, 1] : [0.64, 0.70, 0.67, 1];
      this._drawSolid(this._skirtMesh, vp, mat4Identity(), skirtCol, 0);
    }

    // 3. Draw 3D terrain mesh
    const hasRef = Boolean(replay.data.reference_layers?.[layerId]);
    const isSplit = compareMode === 'split' && hasRef;
    gl.useProgram(this.progTerrain);
    gl.uniformMatrix4fv(gl.getUniformLocation(this.progTerrain, 'uVP'), false, vp);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texEst);
    gl.uniform1i(gl.getUniformLocation(this.progTerrain, 'uTexEst'), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.texRef);
    gl.uniform1i(gl.getUniformLocation(this.progTerrain, 'uTexRef'), 1);
    gl.uniform2f(gl.getUniformLocation(this.progTerrain, 'uGridSize'), width, height);
    gl.uniform1i(gl.getUniformLocation(this.progTerrain, 'uSplitEnabled'), isSplit ? 1 : 0);
    gl.uniform1f(gl.getUniformLocation(this.progTerrain, 'uSplitRatio'), splitRatio);
    gl.uniform1i(gl.getUniformLocation(this.progTerrain, 'uShowGrid'), showGrid ? 1 : 0);
    gl.uniform2f(
      gl.getUniformLocation(this.progTerrain, 'uHoverCell'),
      this.hoverCell ? this.hoverCell.x : -1,
      this.hoverCell ? this.hoverCell.y : -1,
    );
    gl.uniform1i(gl.getUniformLocation(this.progTerrain, 'uDark'), darkTheme ? 1 : 0);
    gl.bindVertexArray(this._terrainMesh.vao);
    gl.drawElements(gl.TRIANGLES, this._terrainMesh.count, this._terrainMesh.indexType, 0);

    // Scale robot model proportionally to scene size
    const robotScale = Math.max(0.55, Math.min(2.2, this._worldSpan * 0.07));
    const altScale = replay.elevationLayerId ? 1.0 : 0.75; // keep drones comfortably framed above small plots

    // 4. Draw 3D trails & planned paths
    for (const as of state.agentStates) {
      const rgb = as.agent.style.rgb;
      if (showTrails && as.trail.length > 1) {
        const pts3d = [];
        const ptsGround = [];
        for (const p of as.trail) {
          const [wx, wz] = this._gridToWorldXZ(replay, p.xy[0], p.xy[1]);
          const gy = this._terrainYAt(replay, p.xy[0], p.xy[1]);
          const wy = gy + (as.agent.kind === 'rover' ? 0.12 : p.altitude_m * altScale);
          pts3d.push(wx, wy, wz);
          ptsGround.push(wx, gy + 0.04, wz);
        }
        this._drawLines(pts3d, vp, [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 0.92], gl.LINE_STRIP);
        if (as.agent.kind === 'drone') {
          this._drawLines(ptsGround, vp, [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 0.25], gl.LINE_STRIP);
        }
      }

      if (showPlans && as.activeTask) {
        const [ax, az] = this._gridToWorldXZ(replay, as.xy[0], as.xy[1]);
        const agy = this._terrainYAt(replay, as.xy[0], as.xy[1]);
        const ay = agy + (as.agent.kind === 'rover' ? 0.16 : as.altitude * altScale);

        const [tx, tz] = this._gridToWorldXZ(replay, as.activeTask.xy[0], as.activeTask.xy[1]);
        const tgy = this._terrainYAt(replay, as.activeTask.xy[0], as.activeTask.xy[1]);
        const tAlt = as.agent.kind === 'rover' ? 0.16 : (as.activeTask.standoff_m ?? as.altitude) * altScale;
        this._drawLines([ax, ay, az, tx, tgy + tAlt, tz], vp, [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 0.55], gl.LINES);
      }
    }

    // 5. Draw 3D Robots + altitude drop lines
    const hudMarkers = [];
    for (const as of state.agentStates) {
      const [wx, wz] = this._gridToWorldXZ(replay, as.xy[0], as.xy[1]);
      const gy = this._terrainYAt(replay, as.xy[0], as.xy[1]);
      const wy = gy + (as.agent.kind === 'rover' ? 0.0 : as.altitude * altScale);
      const rgb = as.agent.style.rgb;

      if (as.agent.kind === 'rover') {
        this._drawRoverModel(vp, wx, wy, wz, as.heading, rgb, animTime, robotScale);
      } else {
        this._drawDroneModel(vp, wx, wy, wz, as.heading, rgb, animTime, robotScale);
        // Vertical altitude tether line from drone to ground + ground ring
        this._drawLines([wx, wy, wz, wx, gy + 0.03, wz], vp, [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 0.55], gl.LINES);
        const ringPts = [];
        const rad = 0.25 * robotScale;
        for (let i = 0; i <= 16; i++) {
          const a = (i / 16) * Math.PI * 2;
          ringPts.push(wx + Math.cos(a) * rad, gy + 0.05, wz + Math.sin(a) * rad);
        }
        this._drawLines(ringPts, vp, [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 0.75], gl.LINE_STRIP);
      }

      const projected = projectPoint(vp, wx, wy + 0.55 * robotScale, wz, w, h);
      if (projected) hudMarkers.push({as, sx: projected[0], sy: projected[1]});
    }

    // 6. Draw translucent 3D Sensor Frustums & recently completed flashes (depthWrite false for clean blending!)
    if (showFootprints) {
      gl.depthMask(false);
      // Recently completed ground flashes
      for (const {task, age} of state.recentCompleted) {
        const agent = replay.agentMap.get(task.agent_id);
        const [fx, fy, fw, fh] = task.footprint;
        const corners = [
          [fx, fy], [fx + fw, fy], [fx + fw, fy + fh], [fx, fy + fh],
        ].map(([cx, cy]) => {
          const [wx, wz] = this._gridToWorldXZ(replay, cx, cy);
          return [wx, this._terrainYAt(replay, cx, cy) + 0.08, wz];
        });
        const alpha = Math.max(0, 1 - age / 1.2);
        const border = [...corners[0], ...corners[1], ...corners[2], ...corners[3], ...corners[0]];
        const rgb = agent.style.rgb;
        this._drawLines(border, vp, [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, alpha], gl.LINE_STRIP);
      }

      // Active sensor frustums
      for (const as of state.agentStates) {
        const task = as.activeTask;
        if (!task) continue;
        const [fx, fy, fw, fh] = task.footprint;
        const corners = [
          [fx, fy], [fx + fw, fy], [fx + fw, fy + fh], [fx, fy + fh],
        ].map(([cx, cy]) => {
          const [wx, wz] = this._gridToWorldXZ(replay, cx, cy);
          return [wx, this._terrainYAt(replay, cx, cy) + 0.06, wz];
        });
        const measuring = as.stage === 'measure';
        // Apex: live robot position when measuring (or target hover position for preview while in transit)
        const apexXY = measuring ? as.xy : task.xy;
        const [ax, az] = this._gridToWorldXZ(replay, apexXY[0], apexXY[1]);
        const agy = this._terrainYAt(replay, apexXY[0], apexXY[1]);
        const apexY = as.agent.kind === 'rover'
          ? agy + 0.45 * robotScale
          : agy + (measuring ? as.altitude : (task.standoff_m ?? as.altitude)) * altScale;
        const pulse = measuring ? (0.16 + 0.09 * Math.sin(animTime * 6 + as.agent.index)) : 0.07;
        this._drawFrustum([ax, apexY, az], corners, vp, as.agent.style.rgb, pulse);
      }
      gl.depthMask(true);
    }

    // 7. Render crisp 2D HUD overlay (robot callouts, compass, split badges)
    this._renderHUD(hudMarkers, w, h, ratio, isSplit, darkTheme, halfW, halfH, baseY);
  }

  _renderHUD(markers, w, h, ratio, isSplit, darkTheme) {
    const ctx = this.hudCtx;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // Floating agent callouts with viewport clamping & overlap avoidance
    ctx.font = '600 10.5px "IBM Plex Mono", ui-monospace, monospace';
    const safeTop = 58, safeBottom = h - 58, pillH = 19;
    const placed = [];
    const items = markers
      .filter(({sx, sy}) => sx >= -40 && sx <= w + 40 && sy >= -20 && sy <= h + 20)
      .map(({as, sx, sy}) => {
        const stageTxt = as.stage === 'measure' ? ' · POMIAR' : as.stage === 'flight' ? ' · DOLOT' : '';
        const altTxt = as.agent.kind === 'drone' ? ` · ${as.altitude.toFixed(1)}m` : '';
        const text = `${as.agent.index + 1} ${as.agent.label}${altTxt}${stageTxt}`;
        const tw = ctx.measureText(text).width + 14;
        const bx = Math.max(10, Math.min(w - tw - 10, sx - tw / 2));
        const by = Math.max(safeTop, Math.min(safeBottom - pillH, sy - 28));
        return {as, sx, sy, text, tw, bx, by};
      })
      .sort((a, b) => a.by - b.by);

    for (const item of items) {
      let guard = 0;
      while (guard++ < 8) {
        const hit = placed.find(p =>
          item.bx < p.bx + p.tw + 6 && item.bx + item.tw + 6 > p.bx &&
          item.by < p.by + pillH + 5 && item.by + pillH + 5 > p.by
        );
        if (!hit) break;
        const nextUp = hit.by - pillH - 6;
        const nextDown = hit.by + pillH + 6;
        if (nextDown + pillH <= safeBottom) item.by = nextDown;
        else if (nextUp >= safeTop) item.by = nextUp;
        else break;
      }
      placed.push(item);
    }

    for (const item of placed) {
      const {as, sx, sy, text, tw, bx, by} = item;
      const col = as.agent.style.rgb;
      ctx.save();
      // Connector stem from robot to pill
      const anchorX = Math.max(bx + 6, Math.min(bx + tw - 6, sx));
      const anchorY = sy > by + pillH ? by + pillH : by;
      ctx.strokeStyle = rgbCss(col, 0.72);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(anchorX, anchorY);
      ctx.lineTo(sx, sy);
      ctx.stroke();
      // Pill
      ctx.fillStyle = darkTheme ? 'rgba(10,16,24,0.88)' : 'rgba(255,255,255,0.94)';
      ctx.strokeStyle = rgbCss(col, 0.88);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(bx, by, tw, pillH, 5);
      ctx.fill();
      ctx.stroke();
      ctx.font = '600 10.5px "IBM Plex Mono", ui-monospace, monospace';
      ctx.fillStyle = darkTheme ? '#e2e8f0' : '#0f172a';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, bx + tw / 2, by + pillH / 2 + 0.5);
      ctx.restore();
    }

    // Compass rose in top-right corner of 3D viewport
    const cx = w - 34, cy = 62, r = 17;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.fillStyle = darkTheme ? 'rgba(12,18,26,0.78)' : 'rgba(255,255,255,0.85)';
    ctx.strokeStyle = darkTheme ? 'rgba(148,163,184,0.28)' : 'rgba(24,44,40,0.24)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.rotate(-this.yaw);
    // North needle
    ctx.fillStyle = '#f43f5e';
    ctx.beginPath();
    ctx.moveTo(0, -11); ctx.lineTo(3.5, 0); ctx.lineTo(-3.5, 0); ctx.closePath();
    ctx.fill();
    ctx.fillStyle = darkTheme ? '#94a3b8' : '#64748b';
    ctx.beginPath();
    ctx.moveTo(0, 11); ctx.lineTo(3.5, 0); ctx.lineTo(-3.5, 0); ctx.closePath();
    ctx.fill();
    ctx.restore();

    if (isSplit) {
      ctx.save();
      ctx.font = '700 10px "IBM Plex Mono", ui-monospace, monospace';
      const drawBadge = (x, label, fg, align) => {
        const bw = ctx.measureText(label).width + 14;
        const rx = align === 'right' ? x - bw : x;
        ctx.fillStyle = 'rgba(12,18,26,0.85)';
        ctx.strokeStyle = fg;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(rx, 54, bw, 20, 5);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = fg;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(label, rx + bw / 2, 64.5);
      };
      drawBadge(14, 'LEWA: ESTYMACJA', '#38bdf8', 'left');
      drawBadge(w - 64, 'PRAWA: REFERENCJA', '#34d399', 'right');
      ctx.restore();
    }
  }
}

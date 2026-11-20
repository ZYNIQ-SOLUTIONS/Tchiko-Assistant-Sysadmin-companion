// Tchiko RC — Tchiko Sigil decoder.
//
// Mirrors tchiko/remote/sigil.py. Pipeline for one frame:
//   grey -> adaptive threshold -> connected components -> locator-ring candidates
//   -> affine fit from second moments -> least-squares refinement on the ring edge
//   -> rotation search -> Reed-Solomon (fixes 3 bytes) -> CRC-16 -> payload.
// No DOM access here, so the same module runs in the browser and in Node tests.

export const SIGIL_VERSION = 1;
export const RING_CELLS = [72, 64, 56];
export const RING_RADII = [0.765, 0.645, 0.525];
const LOCATOR_INNER = 0.88;
const LOCATOR_MID = 0.94;
const GAP_RADIUS = 0.835;
const PAYLOAD_BYTES = 16;
const RS_PARITY = 6;
const CODEWORD_BYTES = 24;

// ── GF(256), primitive polynomial 0x11D ─────────────────────────────────────
const EXP = new Uint8Array(512);
const LOG = new Uint8Array(256);
{
  let x = 1;
  for (let i = 0; i < 255; i++) {
    EXP[i] = x;
    LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
}
const gmul = (a, b) => (a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]]);
const ginv = (a) => EXP[255 - LOG[a]];

function syndromes(cw) {
  const s = new Uint8Array(RS_PARITY);
  for (let j = 0; j < RS_PARITY; j++) {
    const aj = EXP[j];
    let acc = 0;
    for (let i = 0; i < cw.length; i++) acc = gmul(acc, aj) ^ cw[i];
    s[j] = acc;
  }
  return s;
}

/** Reed-Solomon decode in place. Returns number of corrected bytes, or -1 if uncorrectable. */
export function rsCorrect(cw) {
  const n = cw.length;
  const S = syndromes(cw);
  if (S.every((v) => v === 0)) return 0;

  // Berlekamp-Massey -> error locator C(x) = 1 + c1 x + ... (lowest degree first).
  let C = [1];
  let B = [1];
  let L = 0;
  let m = 1;
  let b = 1;
  for (let k = 0; k < RS_PARITY; k++) {
    let d = S[k];
    for (let i = 1; i <= L; i++) d ^= gmul(C[i] || 0, S[k - i]);
    if (d === 0) {
      m++;
      continue;
    }
    const coef = gmul(d, ginv(b));
    const T = C.slice();
    const need = B.length + m;
    while (C.length < need) C.push(0);
    for (let i = 0; i < B.length; i++) C[i + m] ^= gmul(coef, B[i]);
    if (2 * L <= k) {
      L = k + 1 - L;
      B = T;
      b = d;
      m = 1;
    } else {
      m++;
    }
  }
  if (2 * L > RS_PARITY) return -1;

  // Chien search: roots of C are X^-1, X = alpha^power, power = n - 1 - index.
  const powers = [];
  for (let p = 0; p < n; p++) {
    const xinv = EXP[(255 - p) % 255];
    let v = 0;
    for (let i = C.length - 1; i >= 0; i--) v = gmul(v, xinv) ^ (C[i] || 0);
    if (v === 0) powers.push(p);
  }
  if (powers.length !== L) return -1;

  // Magnitudes: solve sum_k Y_k X_k^j = S_j (j < L) by Gaussian elimination over GF(256).
  const X = powers.map((p) => EXP[p]);
  const M = [];
  for (let j = 0; j < L; j++) {
    const row = [];
    for (let k = 0; k < L; k++) row.push(j === 0 ? 1 : EXP[(LOG[X[k]] * j) % 255]);
    row.push(S[j]);
    M.push(row);
  }
  for (let col = 0; col < L; col++) {
    let piv = col;
    while (piv < L && M[piv][col] === 0) piv++;
    if (piv === L) return -1;
    [M[col], M[piv]] = [M[piv], M[col]];
    const inv = ginv(M[col][col]);
    for (let c = col; c <= L; c++) M[col][c] = gmul(M[col][c], inv);
    for (let r = 0; r < L; r++) {
      if (r !== col && M[r][col] !== 0) {
        const f = M[r][col];
        for (let c = col; c <= L; c++) M[r][c] ^= gmul(f, M[col][c]);
      }
    }
  }
  for (let k = 0; k < L; k++) cw[n - 1 - powers[k]] ^= M[k][L];
  return syndromes(cw).every((v) => v === 0) ? L : -1;
}

export function crc16(bytes) {
  let crc = 0xffff;
  for (const byte of bytes) {
    crc ^= byte << 8;
    for (let i = 0; i < 8; i++) crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
  }
  return crc;
}

/** Validate a 24-byte codeword (after RS) and unpack it. */
export function parseCodeword(cw) {
  const fixed = Uint8Array.from(cw);
  const corrected = rsCorrect(fixed);
  if (corrected < 0) return null;
  const payload = fixed.slice(0, PAYLOAD_BYTES);
  const crc = (fixed[16] << 8) | fixed[17];
  if (crc16(payload) !== crc) return null;
  return parsePayload(payload, corrected);
}

/** Unpack the 16-byte payload (also used for the #pair= link fallback). */
export function parsePayload(payload, corrected = 0) {
  if (!payload || payload.length !== PAYLOAD_BYTES) return null;
  const version = payload[0] >> 4;
  if (version !== SIGIL_VERSION) return null;
  return {
    version,
    sessionId: payload.slice(1, 4),
    secret: payload.slice(4, 16),
    payload: Uint8Array.from(payload),
    corrected,
  };
}

// ── Image analysis ──────────────────────────────────────────────────────────
function toGray(img) {
  const { data, width, height } = img;
  const g = new Float32Array(width * height);
  for (let i = 0, p = 0; i < g.length; i++, p += 4) g[i] = 0.299 * data[p] + 0.587 * data[p + 1] + 0.114 * data[p + 2];
  return g;
}

function adaptiveThreshold(gray, w, h, invert) {
  const integ = new Float64Array((w + 1) * (h + 1));
  for (let y = 0; y < h; y++) {
    let row = 0;
    for (let x = 0; x < w; x++) {
      row += gray[y * w + x];
      integ[(y + 1) * (w + 1) + x + 1] = integ[y * (w + 1) + x + 1] + row;
    }
  }
  const r = Math.max(6, Math.round(Math.min(w, h) / 14));
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - r);
    const y1 = Math.min(h, y + r + 1);
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - r);
      const x1 = Math.min(w, x + r + 1);
      const sum = integ[y1 * (w + 1) + x1] - integ[y0 * (w + 1) + x1] - integ[y1 * (w + 1) + x0] + integ[y0 * (w + 1) + x0];
      const mean = sum / ((x1 - x0) * (y1 - y0));
      const v = gray[y * w + x];
      out[y * w + x] = invert ? (v < mean - 10 ? 1 : 0) : v > mean + 10 ? 1 : 0;
    }
  }
  return out;
}

function components(bin, w, h) {
  const labels = new Int32Array(w * h);
  const stack = new Int32Array(w * h);
  const comps = [];
  let next = 1;
  for (let start = 0; start < bin.length; start++) {
    if (!bin[start] || labels[start]) continue;
    const id = next++;
    let sp = 0;
    stack[sp++] = start;
    labels[start] = id;
    let area = 0, sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
    let minX = w, minY = h, maxX = 0, maxY = 0;
    while (sp) {
      const idx = stack[--sp];
      const x = idx % w;
      const y = (idx - x) / w;
      area++;
      sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
      if (x > 0 && bin[idx - 1] && !labels[idx - 1]) { labels[idx - 1] = id; stack[sp++] = idx - 1; }
      if (x < w - 1 && bin[idx + 1] && !labels[idx + 1]) { labels[idx + 1] = id; stack[sp++] = idx + 1; }
      if (y > 0 && bin[idx - w] && !labels[idx - w]) { labels[idx - w] = id; stack[sp++] = idx - w; }
      if (y < h - 1 && bin[idx + w] && !labels[idx + w]) { labels[idx + w] = id; stack[sp++] = idx + w; }
    }
    if (area >= 150) comps.push({ id, area, sx, sy, sxx, syy, sxy, minX, minY, maxX, maxY });
  }
  return { labels, comps };
}

function ringCandidates(labels, comps, w) {
  const out = [];
  for (const c of comps) {
    const bw = c.maxX - c.minX + 1;
    const bh = c.maxY - c.minY + 1;
    if (bw < 40 || bh < 40) continue;
    const aspect = bw / bh;
    if (aspect < 0.45 || aspect > 2.2) continue;
    const mx = c.sx / c.area;
    const my = c.sy / c.area;
    const off = Math.hypot(mx - (c.minX + bw / 2), my - (c.minY + bh / 2));
    if (off > 0.15 * Math.max(bw, bh)) continue;
    const fill = c.area / (bw * bh);
    if (fill < 0.06 || fill > 0.45) continue;
    if (labels[Math.round(my) * w + Math.round(mx)] === c.id) continue; // must be hollow
    const vxx = c.sxx / c.area - mx * mx;
    const vyy = c.syy / c.area - my * my;
    const vxy = c.sxy / c.area - mx * my;
    out.push({ cx: mx, cy: my, vxx, vyy, vxy, area: c.area });
  }
  return out.sort((a, b) => b.area - a.area).slice(0, 6);
}

/** Symmetric square root of a 2x2 PSD matrix [[a, b], [b, d]]. */
function sqrt2x2(a, b, d) {
  const det = a * d - b * b;
  if (det <= 0) return null;
  const s = Math.sqrt(det);
  const t = Math.sqrt(a + d + 2 * s);
  return [(a + s) / t, b / t, b / t, (d + s) / t];
}

function bilinear(gray, w, h, x, y) {
  if (x < 0 || y < 0 || x >= w - 1 || y >= h - 1) return -1;
  const x0 = x | 0;
  const y0 = y | 0;
  const fx = x - x0;
  const fy = y - y0;
  const i = y0 * w + x0;
  const top = gray[i] + (gray[i + 1] - gray[i]) * fx;
  const bot = gray[i + w] + (gray[i + w + 1] - gray[i + w]) * fx;
  return top + (bot - top) * fy;
}

// Map unit-space (u, v) through the fitted affine frame into image space.
const mapPt = (f, u, v) => [f.cx + f.a * u + f.b * v, f.cy + f.c * u + f.d * v];

/** Refine centre + affine frame with a least-squares fit to the locator's outer edge. */
function refineFrame(gray, w, h, f, invert) {
  const RAYS = 48;
  for (let iter = 0; iter < 3; iter++) {
    const rows = [];
    for (let k = 0; k < RAYS; k++) {
      const ang = (k / RAYS) * Math.PI * 2;
      const du = Math.sin(ang);
      const dv = -Math.cos(ang);
      const prof = [];
      let lo = 1e9, hi = -1e9;
      for (let s = 0.7; s <= 1.16; s += 0.006) {
        const [x, y] = mapPt(f, du * s, dv * s);
        let g = bilinear(gray, w, h, x, y);
        if (g < 0) { prof.length = 0; break; }
        if (invert) g = 255 - g;
        prof.push([s, g]);
        if (g < lo) lo = g;
        if (g > hi) hi = g;
      }
      if (prof.length < 10 || hi - lo < 25) continue;
      const t = (hi + lo) / 2;
      let edge = -1;
      for (let i = prof.length - 1; i > 0; i--) {
        if (prof[i - 1][1] >= t && prof[i][1] < t) {
          const [s0, g0] = prof[i - 1];
          const [s1, g1] = prof[i];
          edge = s0 + ((g0 - t) / (g0 - g1)) * (s1 - s0);
          break;
        }
      }
      if (edge < 0) continue;
      const [px, py] = mapPt(f, du * edge, dv * edge);
      rows.push([du, dv, px, py]);
    }
    if (rows.length < RAYS * 0.6) return iter > 0 ? f : null;
    // Normal equations for p = c + A·d  (two independent 3-parameter fits).
    let n = 0, su = 0, sv = 0, suu = 0, svv = 0, suv = 0;
    let bx0 = 0, bx1 = 0, bx2 = 0, by0 = 0, by1 = 0, by2 = 0;
    for (const [u, v, px, py] of rows) {
      n++; su += u; sv += v; suu += u * u; svv += v * v; suv += u * v;
      bx0 += px; bx1 += u * px; bx2 += v * px;
      by0 += py; by1 += u * py; by2 += v * py;
    }
    const sol = solve3([[n, su, sv], [su, suu, suv], [sv, suv, svv]], [bx0, bx1, bx2]);
    const sol2 = solve3([[n, su, sv], [su, suu, suv], [sv, suv, svv]], [by0, by1, by2]);
    if (!sol || !sol2) return null;
    f = { cx: sol[0], a: sol[1], b: sol[2], cy: sol2[0], c: sol2[1], d: sol2[2] };
  }
  return f;
}

function solve3(A, b) {
  const m = A.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < 3; col++) {
    let piv = col;
    for (let r = col + 1; r < 3; r++) if (Math.abs(m[r][col]) > Math.abs(m[piv][col])) piv = r;
    if (Math.abs(m[piv][col]) < 1e-9) return null;
    [m[col], m[piv]] = [m[piv], m[col]];
    for (let r = 0; r < 3; r++) {
      if (r === col) continue;
      const fct = m[r][col] / m[col][col];
      for (let c = col; c < 4; c++) m[r][c] -= fct * m[col][c];
    }
  }
  return [m[0][3] / m[0][0], m[1][3] / m[1][1], m[2][3] / m[2][2]];
}

function readFrame(gray, w, h, f, invert) {
  const STEPS = 360;
  const sample = (u, v) => {
    const [x, y] = mapPt(f, u, v);
    const g = bilinear(gray, w, h, x, y);
    return g < 0 ? -1 : invert ? 255 - g : g;
  };
  // Local bright (locator) and dark (gap) references every 1 degree.
  const REF = 720;
  const bright = new Float32Array(REF);
  const dark = new Float32Array(REF);
  for (let i = 0; i < REF; i++) {
    const a = (i / REF) * Math.PI * 2;
    const s = Math.sin(a);
    const c = -Math.cos(a);
    bright[i] = sample(s * LOCATOR_MID, c * LOCATOR_MID);
    dark[i] = sample(s * GAP_RADIUS, c * GAP_RADIUS);
    if (bright[i] < 0 || dark[i] < 0) return null;
  }
  // Pre-sample every ring on a fine angular grid, normalised to 0..1 against the references.
  const FINE = 1440;
  const rings = RING_RADII.map((r) => {
    const arr = new Float32Array(FINE);
    for (let i = 0; i < FINE; i++) {
      const a = (i / FINE) * Math.PI * 2;
      const g = sample(Math.sin(a) * r, -Math.cos(a) * r);
      const ref = Math.round((i / FINE) * REF) % REF;
      const span = bright[ref] - dark[ref];
      arr[i] = span > 12 ? (g - dark[ref]) / span : 0;
    }
    return arr;
  });

  const cw = new Uint8Array(CODEWORD_BYTES);
  for (const dir of [1, -1]) {
    for (let step = 0; step < STEPS; step++) {
      const theta = (step / STEPS) * FINE;
      cw.fill(0);
      let bit = 0;
      for (let ring = 0; ring < 3; ring++) {
        const cells = RING_CELLS[ring];
        const arr = rings[ring];
        for (let i = 0; i < cells; i++) {
          let pos = Math.round(theta + dir * ((i + 0.5) / cells) * FINE) % FINE;
          if (pos < 0) pos += FINE;
          if (arr[pos] > 0.5) cw[bit >> 3] |= 0x80 >> (bit & 7);
          bit++;
        }
      }
      const res = parseCodeword(cw);
      if (res) return res;
    }
  }
  return null;
}

/**
 * Decode a sigil from RGBA image data ({data, width, height}).
 * Returns {version, sessionId, secret, payload, corrected} or null.
 */
export function decodeSigil(img) {
  const { width: w, height: h } = img;
  const gray = toGray(img);
  for (const invert of [false, true]) {
    const bin = adaptiveThreshold(gray, w, h, invert);
    const { labels, comps } = components(bin, w, h);
    for (const cand of ringCandidates(labels, comps, w)) {
      // Uniform annulus: E[r^2] / 2 per axis = (1 + rho^2) / 4.
      const k = (1 + LOCATOR_INNER * LOCATOR_INNER) / 4;
      const root = sqrt2x2(cand.vxx / k, cand.vxy / k, cand.vyy / k);
      if (!root) continue;
      let frame = { cx: cand.cx, cy: cand.cy, a: root[0], b: root[1], c: root[2], d: root[3] };
      frame = refineFrame(gray, w, h, frame, invert);
      if (!frame) continue;
      const res = readFrame(gray, w, h, frame, invert);
      if (res) return res;
    }
  }
  return null;
}

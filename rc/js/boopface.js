// Tchiko RC — Procedural BoopFace avatar matching tchiko/svg_ghost_renderer.py.
// Supports all 4 desktop coats, all expressive moods, natural blinking, antenna spring,
// pointer gaze tracking, and elastic squish on boop.

export const COATS = {
  phantom_cyan: {
    label: 'Obsidian Metal',
    headTop: '#1c212e',
    headMid: '#0d0f14',
    headBottom: '#05080a',
    rim: '#47526b',
    eye: '#ffffff',
    accent: '#e5484d',
  },
  astral_violet: {
    label: 'Velvet Slate',
    headTop: '#262b40',
    headMid: '#141724',
    headBottom: '#0a0a14',
    rim: '#5c668f',
    eye: '#f7faff',
    accent: '#e0385c',
  },
  emerald_matrix: {
    label: 'Porcelain Glaze',
    headTop: '#ffffff',
    headMid: '#edf2fa',
    headBottom: '#d1d9e6',
    rim: '#b8c2d6',
    eye: '#0f121a',
    accent: '#eb3d42',
  },
  solar_gold: {
    label: 'Crimson Carbon',
    headTop: '#3d141a',
    headMid: '#1f0a0f',
    headBottom: '#0f0508',
    rim: '#8c333d',
    eye: '#fffaef',
    accent: '#f5a524',
  },
};

export const MOODS = [
  ['idle', 'Hover'],
  ['happy', 'Tippy-tap dance'],
  ['excited', 'Zoomies'],
  ['thinking', 'Curious head-tilt'],
  ['executing', 'Ring juggle'],
  ['roar', 'Puff up'],
  ['wing_slash', 'Tumble spin'],
  ['dizzy', 'Wobbly spin'],
  ['sleepy', 'Nap'],
];

const SVG_NS = 'http://www.w3.org/2000/svg';
let _uid = 0;

function el(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

export class BoopFaceAvatar {
  constructor(container, { size = 112, coat = 'phantom_cyan', interactive = true, animate = true } = {}) {
    this.container = container;
    this.size = size;
    this.coat = COATS[coat] ? coat : 'phantom_cyan';
    this.mood = 'idle';
    this.moodTtl = 0;
    this.phase = Math.random() * 6;
    this.lookX = 0;
    this.lookY = 0;
    this.targetX = 0;
    this.targetY = 0;
    this.squish = 0;
    this.antX = 0;
    this.antVx = 0;
    this.blinkTimer = 2.4;
    this.blinkAmt = 0;
    this._raf = 0;
    this._lastTs = 0;
    this._id = `bf${++_uid}`;

    this._buildDom();
    this._applyCoat();
    if (interactive) this._bindEvents();
    this._render(0);
    if (animate) this.start();
  }

  _buildDom() {
    const svg = el('svg', {
      viewBox: '0 0 120 120',
      width: this.size,
      height: this.size,
      class: 'boopface-svg',
      'aria-hidden': 'true',
    });

    const defs = el('defs');
    const grad = el('linearGradient', { id: `${this._id}-head`, x1: '0', y1: '0', x2: '0', y2: '1' });
    this._stop0 = el('stop', { offset: '0%' });
    this._stop1 = el('stop', { offset: '55%' });
    this._stop2 = el('stop', { offset: '100%' });
    grad.append(this._stop0, this._stop1, this._stop2);
    defs.append(grad);
    svg.append(defs);

    this._root = el('g');
    this._aura = el('circle', { cx: 60, cy: 66, r: 44, fill: 'none', 'stroke-width': 2.5, opacity: 0 });
    this._stem = el('path', { fill: 'none', 'stroke-width': 3.4, 'stroke-linecap': 'round' });
    this._bobble = el('circle', { cx: 60, cy: 18, r: 5.8 });

    // Superellipse-like squircle path centred at (60, 66)
    this._head = el('rect', {
      x: 20,
      y: 34,
      width: 80,
      height: 64,
      rx: 25,
      ry: 25,
      fill: `url(#${this._id}-head)`,
      'stroke-width': 2.2,
    });
    this._shine = el('path', {
      d: 'M 36 41 Q 60 36 84 41',
      fill: 'none',
      stroke: '#ffffff',
      'stroke-width': 2,
      'stroke-linecap': 'round',
      opacity: 0.16,
    });

    this._eyesGroup = el('g');
    this._eyeL = el('rect', { x: 41, y: 56, width: 11, height: 19, rx: 5.5 });
    this._eyeR = el('rect', { x: 68, y: 56, width: 11, height: 19, rx: 5.5 });
    this._smileL = el('path', { fill: 'none', 'stroke-width': 4.4, 'stroke-linecap': 'round', opacity: 0 });
    this._smileR = el('path', { fill: 'none', 'stroke-width': 4.4, 'stroke-linecap': 'round', opacity: 0 });
    this._eyesGroup.append(this._eyeL, this._eyeR, this._smileL, this._smileR);

    this._root.append(this._aura, this._stem, this._bobble, this._head, this._shine, this._eyesGroup);
    svg.append(this._root);
    this.container.innerHTML = '';
    this.container.append(svg);
    this.svg = svg;
  }

  _bindEvents() {
    this.svg.style.cursor = 'pointer';
    this.svg.addEventListener('pointermove', (ev) => {
      const rect = this.svg.getBoundingClientRect();
      this.targetX = Math.max(-1, Math.min(1, ((ev.clientX - rect.left) / rect.width) * 2 - 1));
      this.targetY = Math.max(-1, Math.min(1, ((ev.clientY - rect.top) / rect.height) * 2 - 1));
    });
    this.svg.addEventListener('pointerleave', () => {
      this.targetX = 0;
      this.targetY = 0;
    });
    this.svg.addEventListener('pointerdown', () => {
      this.boop();
    });
  }

  setCoat(coatKey) {
    if (!COATS[coatKey]) return;
    this.coat = coatKey;
    this._applyCoat();
  }

  setMood(mood, ttl = 0) {
    this.mood = mood || 'idle';
    this.moodTtl = ttl;
    this.squish = 0.18;
    this.antVx += 16;
  }

  boop() {
    this.squish = 0.28;
    this.antVx += (Math.random() > 0.5 ? 1 : -1) * 26;
    if (this.mood === 'idle' || this.mood === 'sleepy') {
      this.setMood('happy', 2.4);
    }
  }

  _applyCoat() {
    const c = COATS[this.coat];
    this._stop0.setAttribute('stop-color', c.headTop);
    this._stop1.setAttribute('stop-color', c.headMid);
    this._stop2.setAttribute('stop-color', c.headBottom);
    this._head.setAttribute('stroke', c.rim);
    this._stem.setAttribute('stroke', c.rim);
    this._bobble.setAttribute('fill', c.accent);
    this._aura.setAttribute('stroke', c.accent);
    this._eyeL.setAttribute('fill', c.eye);
    this._eyeR.setAttribute('fill', c.eye);
    this._smileL.setAttribute('stroke', c.eye);
    this._smileR.setAttribute('stroke', c.eye);
  }

  start() {
    if (this._raf) return;
    const tick = (ts) => {
      const dt = this._lastTs ? Math.min(0.05, (ts - this._lastTs) / 1000) : 0.016;
      this._lastTs = ts;
      this._step(dt);
      this._render();
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
  }

  stop() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
  }

  _step(dt) {
    const fast = ['excited', 'happy', 'executing', 'roar', 'wing_slash'].includes(this.mood);
    const mult = this.mood === 'sleepy' ? 0.45 : fast ? 1.65 : 1.0;
    this.phase += dt * 3.4 * mult;
    this.lookX += (this.targetX - this.lookX) * Math.min(1, dt * 10);
    this.lookY += (this.targetY - this.lookY) * Math.min(1, dt * 10);
    this.squish *= Math.pow(0.06, dt);

    const force = -this.antX * 140;
    this.antVx = (this.antVx + force * dt) * Math.pow(0.08, dt);
    this.antX += this.antVx * dt;

    if (this.mood === 'idle' || this.mood === 'thinking') {
      this.blinkTimer -= dt;
      if (this.blinkTimer <= 0) {
        this.blinkAmt = Math.min(1, this.blinkAmt + dt * 14);
        if (this.blinkAmt >= 1) this.blinkTimer = 2.6 + Math.random() * 2.2;
      } else if (this.blinkAmt > 0) {
        this.blinkAmt = Math.max(0, this.blinkAmt - dt * 12);
      }
    } else {
      this.blinkAmt = 0;
    }

    if (this.moodTtl > 0) {
      this.moodTtl = Math.max(0, this.moodTtl - dt);
      if (this.moodTtl === 0 && !['thinking', 'executing'].includes(this.mood)) {
        this.mood = 'idle';
      }
    }
  }

  _render() {
    const bob = Math.sin(this.phase) * (this.mood === 'excited' ? 5.2 : this.mood === 'happy' ? 4.2 : 2.5);
    const tilt =
      this.mood === 'thinking'
        ? -7 + Math.sin(this.phase * 0.7) * 2
        : this.mood === 'wing_slash'
          ? (this.phase * 95) % 360
          : this.mood === 'dizzy'
            ? Math.sin(this.phase * 2.2) * 10
            : Math.sin(this.phase * 0.5) * 1.5;

    const sx = 1 + this.squish * 0.45 + Math.sin(this.phase * 2) * (this.mood === 'happy' ? 0.03 : 0.008);
    const sy = 1 - this.squish * 0.35 - Math.sin(this.phase * 2) * (this.mood === 'happy' ? 0.03 : 0.008);

    this._root.setAttribute(
      'transform',
      `translate(60 ${66 + bob}) rotate(${tilt.toFixed(2)}) scale(${sx.toFixed(3)} ${sy.toFixed(3)}) translate(-60 -66)`,
    );

    const antTipX = 60 + Math.max(-14, Math.min(14, this.antX + Math.sin(this.phase) * 2.4));
    const antTipY = 17 + Math.abs(antTipX - 60) * 0.12;
    this._stem.setAttribute('d', `M 60 35 Q ${((60 + antTipX) / 2).toFixed(1)} 25 ${antTipX.toFixed(1)} ${antTipY.toFixed(1)}`);
    this._bobble.setAttribute('cx', antTipX.toFixed(1));
    this._bobble.setAttribute('cy', antTipY.toFixed(1));

    // Active aura ring while executing / alert / roar
    if (this.mood === 'executing' || this.mood === 'roar' || this.mood === 'alert') {
      const p = (this.phase * 0.25) % 1;
      this._aura.setAttribute('r', (38 + p * 18).toFixed(1));
      this._aura.setAttribute('opacity', ((1 - p) * 0.65).toFixed(2));
    } else {
      this._aura.setAttribute('opacity', '0');
    }

    // Eyes
    let gx = this.lookX * 5;
    let gy = this.lookY * 4;
    if (this.mood === 'thinking') {
      gx = Math.sin(this.phase * 1.4) * 6;
      gy = -2;
    } else if (this.mood === 'executing') {
      gx = Math.cos(this.phase * 1.8) * 4;
      gy = Math.sin(this.phase * 1.8) * 3;
    }

    if (this.mood === 'happy') {
      this._eyeL.setAttribute('opacity', '0');
      this._eyeR.setAttribute('opacity', '0');
      this._smileL.setAttribute('opacity', '1');
      this._smileR.setAttribute('opacity', '1');
      this._smileL.setAttribute('d', `M ${(40 + gx).toFixed(1)} ${(68 + gy).toFixed(1)} Q ${(46.5 + gx).toFixed(1)} ${(57 + gy).toFixed(1)} ${(53 + gx).toFixed(1)} ${(68 + gy).toFixed(1)}`);
      this._smileR.setAttribute('d', `M ${(67 + gx).toFixed(1)} ${(68 + gy).toFixed(1)} Q ${(73.5 + gx).toFixed(1)} ${(57 + gy).toFixed(1)} ${(80 + gx).toFixed(1)} ${(68 + gy).toFixed(1)}`);
    } else {
      this._eyeL.setAttribute('opacity', '1');
      this._eyeR.setAttribute('opacity', '1');
      this._smileL.setAttribute('opacity', '0');
      this._smileR.setAttribute('opacity', '0');

      const baseH =
        this.mood === 'sleepy'
          ? 3.5
          : this.mood === 'thinking'
            ? 11
            : this.mood === 'excited' || this.mood === 'roar'
              ? 23
              : 19;
      const hL = Math.max(2.6, baseH * (1 - this.blinkAmt * 0.88));
      const hR =
        this.mood === 'executing'
          ? Math.max(6, baseH * (0.65 + 0.35 * Math.sin(this.phase * 2.5)))
          : hL;
      const w = this.mood === 'excited' || this.mood === 'roar' ? 13 : 11;

      this._eyeL.setAttribute('x', (46.5 - w / 2 + gx).toFixed(1));
      this._eyeL.setAttribute('y', (65.5 - hL / 2 + gy).toFixed(1));
      this._eyeL.setAttribute('width', w);
      this._eyeL.setAttribute('height', hL.toFixed(1));
      this._eyeL.setAttribute('rx', (Math.min(w, hL) / 2).toFixed(1));

      this._eyeR.setAttribute('x', (73.5 - w / 2 + gx).toFixed(1));
      this._eyeR.setAttribute('y', (65.5 - hR / 2 + gy).toFixed(1));
      this._eyeR.setAttribute('width', w);
      this._eyeR.setAttribute('height', hR.toFixed(1));
      this._eyeR.setAttribute('rx', (Math.min(w, hR) / 2).toFixed(1));
    }
  }
}

// Tchiko RC — Shared UI primitives (RingGauge, SVG icons, clipboard & toast helpers).

const SVG_NS = 'http://www.w3.org/2000/svg';

export const ICONS = {
  monitor: '<path d="M3 12h4l3-9 4 18 3-9h4"/>',
  network: '<circle cx="12" cy="12" r="9"/><path d="M3.6 9h16.8M3.6 15h16.8M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5 19 11"/>',
  memory: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  package: '<path d="M12 2 3 7v10l9 5 9-5V7l-9-5Z"/><path d="m3 7 9 5 9-5M12 22V12"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76Z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>',
  terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
  desktop: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  send: '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
  camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  smile: '<circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/>',
  slash: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  warn: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  disconnect: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><polyline points="21 3 21 9 15 9"/>',
};

export function iconSvg(name, size = 16) {
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
}

export function levelColor(fraction) {
  if (fraction >= 0.88) return '#f43f5e';
  if (fraction >= 0.72) return '#f59e0b';
  return '#10b981';
}

/** Responsive circular utilisation ring gauge styled for the Obsidian Glass theme. */
export class RingGauge {
  constructor(container, size = 84) {
    const stroke = 6.5;
    const r = (size - stroke * 2) / 2;
    const c = size / 2;
    this._circ = 2 * Math.PI * r;

    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
    svg.classList.add('ring-gauge');

    const track = document.createElementNS(SVG_NS, 'circle');
    track.setAttribute('cx', String(c));
    track.setAttribute('cy', String(c));
    track.setAttribute('r', String(r));
    track.setAttribute('fill', 'none');
    track.setAttribute('stroke', 'rgba(255, 255, 255, 0.08)');
    track.setAttribute('stroke-width', String(stroke));

    const arc = document.createElementNS(SVG_NS, 'circle');
    arc.setAttribute('cx', String(c));
    arc.setAttribute('cy', String(c));
    arc.setAttribute('r', String(r));
    arc.setAttribute('fill', 'none');
    arc.setAttribute('stroke', '#10b981');
    arc.setAttribute('stroke-width', String(stroke));
    arc.setAttribute('stroke-linecap', 'round');
    arc.setAttribute('stroke-dasharray', String(this._circ));
    arc.setAttribute('stroke-dashoffset', String(this._circ));
    arc.setAttribute('transform', `rotate(-90 ${c} ${c})`);
    arc.style.transition = 'stroke-dashoffset 420ms cubic-bezier(0.2, 0.8, 0.2, 1), stroke 260ms ease';

    const txt = document.createElementNS(SVG_NS, 'text');
    txt.setAttribute('x', String(c));
    txt.setAttribute('y', String(c));
    txt.setAttribute('text-anchor', 'middle');
    txt.setAttribute('dominant-baseline', 'central');
    txt.setAttribute('fill', '#f4f5f8');
    txt.setAttribute('font-size', String(Math.round(r * 0.54)));
    txt.setAttribute('font-weight', '650');
    txt.setAttribute('class', 'ring-gauge-text');
    txt.textContent = '0%';

    svg.append(track, arc, txt);
    container.innerHTML = '';
    container.append(svg);
    this._arc = arc;
    this._txt = txt;
  }

  setFraction(fraction) {
    const shown = Math.max(0, Math.min(1, Number(fraction) || 0));
    const col = levelColor(shown);
    this._arc.setAttribute('stroke', col);
    this._arc.setAttribute('stroke-dashoffset', String(this._circ * (1 - shown)));
    this._arc.style.filter = `drop-shadow(0 0 6px ${col}55)`;
    this._txt.textContent = `${Math.round(shown * 100)}%`;
  }
}

export async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.append(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }
  if (btn) {
    const prev = btn.innerHTML;
    btn.innerHTML = iconSvg('check', 14);
    btn.classList.add('copied');
    setTimeout(() => {
      btn.innerHTML = prev;
      btn.classList.remove('copied');
    }, 1300);
  }
}

let toastTimer = null;
export function showToast(message, kind = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.className = `toast visible ${kind}`;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.remove('visible');
  }, 3200);
}

// Tchiko RC — One-step Tchiko Sigil scanner (live camera + image upload/paste + #pair= link).

import { decodeSigil, parsePayload } from './sigil.js';
import { b64uDecode } from './channel.js';

/**
 * Check `location.hash` for `#pair=<base64url(16B)>` (one-step link from Tchiko Desktop).
 * Immediately clears the fragment via `history.replaceState` so the secret isn't kept in history.
 */
export function consumeHashPairToken() {
  const hash = window.location.hash || '';
  const match = hash.match(/pair=([A-Za-z0-9_-]{18,40})/);
  if (!match) return null;
  try {
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  } catch {}
  try {
    const raw = b64uDecode(match[1]);
    return parsePayload(raw);
  } catch {
    return null;
  }
}

/** Decode a Tchiko Sigil from a File/Blob (PNG, JPEG, WebP, SVG) using an offscreen canvas. */
export async function decodeSigilFromBlob(blob) {
  const url = URL.createObjectURL(blob);
  try {
    const img = await new Promise((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error('Could not read image'));
      el.src = url;
    });
    const maxDim = 640;
    const scale = Math.min(1, maxDim / Math.max(img.naturalWidth || 480, img.naturalHeight || 480));
    const w = Math.max(120, Math.round((img.naturalWidth || 480) * scale));
    const h = Math.max(120, Math.round((img.naturalHeight || 480) * scale));
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.fillStyle = '#0d0e11';
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(img, 0, 0, w, h);
    const data = ctx.getImageData(0, 0, w, h);
    return decodeSigil(data);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Live rear-camera Tchiko Sigil scanner controller. */
export class SigilCameraScanner {
  constructor(videoEl, { onDetected, onError, onState }) {
    this.videoEl = videoEl;
    this.onDetected = onDetected;
    this.onError = onError || (() => {});
    this.onState = onState || (() => {});
    this._stream = null;
    this._timer = null;
    this._running = false;
    this._canvas = document.createElement('canvas');
    this._ctx = this._canvas.getContext('2d', { willReadFrequently: true });
  }

  get active() {
    return this._running;
  }

  async start() {
    if (this._running) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      this.onError('Camera access requires HTTPS or localhost. You can still upload or paste a sigil image.');
      return;
    }
    this.onState('starting');
    try {
      this._stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 960 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      this.videoEl.srcObject = this._stream;
      this.videoEl.setAttribute('playsinline', 'true');
      await this.videoEl.play();
      this._running = true;
      this.onState('scanning');
      this._scheduleTick();
    } catch (err) {
      this.stop();
      const msg =
        err && err.name === 'NotAllowedError'
          ? 'Camera permission denied. Allow camera access or drop a sigil image instead.'
          : 'Could not open camera. Try dropping or uploading a sigil screenshot instead.';
      this.onError(msg);
    }
  }

  stop() {
    this._running = false;
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
    if (this._stream) {
      for (const track of this._stream.getTracks()) track.stop();
      this._stream = null;
    }
    if (this.videoEl) {
      this.videoEl.srcObject = null;
    }
    this.onState('idle');
  }

  _scheduleTick() {
    if (!this._running) return;
    this._timer = setTimeout(() => {
      if (!this._running) return;
      this._scanFrame();
      if (this._running) this._scheduleTick();
    }, 170);
  }

  _scanFrame() {
    const vw = this.videoEl.videoWidth;
    const vh = this.videoEl.videoHeight;
    if (!vw || !vh) return;
    const maxDim = 520;
    const scale = Math.min(1, maxDim / Math.max(vw, vh));
    const w = Math.round(vw * scale);
    const h = Math.round(vh * scale);
    if (this._canvas.width !== w || this._canvas.height !== h) {
      this._canvas.width = w;
      this._canvas.height = h;
    }
    this._ctx.drawImage(this.videoEl, 0, 0, w, h);
    const frame = this._ctx.getImageData(0, 0, w, h);
    const decoded = decodeSigil(frame);
    if (decoded) {
      this.stop();
      this.onDetected(decoded);
    }
  }
}

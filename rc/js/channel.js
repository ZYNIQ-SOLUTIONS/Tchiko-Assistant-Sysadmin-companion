// Tchiko RC — End-to-end encrypted channel over WebSocket (WebCrypto API).
//
// Matches tchiko/remote/crypto.py + tchiko/remote/service.py byte-for-byte:
//   - Ephemeral ECDH P-256 (65-byte uncompressed public keys, 32-byte shared X)
//   - HKDF-SHA256(shared, salt=secret, info="tchiko-rc v1 keys" || transcript_hash)
//   - Mutual HMAC-SHA256 authentication over the transcript hash
//   - Directional AES-256-GCM framing with strict monotonic 64-bit counters
//
// Works in both browsers (window.crypto.subtle) and Node.js 20+ (globalThis.crypto.subtle).

const ENC = new TextEncoder();
const DEC = new TextDecoder();

export const DIR_CLIENT_TO_SERVER = 1;
export const DIR_SERVER_TO_CLIENT = 2;

const SUBTLE = () => globalThis.crypto.subtle;

export function b64uEncode(bytes) {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let bin = '';
  for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function b64uDecode(str) {
  if (typeof str !== 'string') throw new Error('Expected base64url string');
  const pad = str.length % 4 ? '='.repeat(4 - (str.length % 4)) : '';
  const bin = atob(str.replace(/-/g, '+').replace(/_/g, '/') + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function concatBytes(...parts) {
  let len = 0;
  for (const p of parts) len += p.length;
  const out = new Uint8Array(len);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

export function constTimeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export async function sha256(data) {
  return new Uint8Array(await SUBTLE().digest('SHA-256', data));
}

export async function hmacSha256(keyBytes, data) {
  const key = await SUBTLE().importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await SUBTLE().sign('HMAC', key, data));
}

export async function hkdfSha256(ikm, salt, info, lengthBytes) {
  const base = await SUBTLE().importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  const bits = await SUBTLE().deriveBits(
    { name: 'HKDF', hash: 'SHA-256', salt, info },
    base,
    lengthBytes * 8,
  );
  return new Uint8Array(bits);
}

export async function transcriptHash(context, clientPub, serverPub, clientNonce, serverNonce) {
  const prefix = ENC.encode('TCHIKO-RC/1');
  const parts = [context, clientPub, serverPub, clientNonce, serverNonce];
  const chunks = [prefix];
  for (const p of parts) {
    const hdr = new Uint8Array(2);
    hdr[0] = (p.length >> 8) & 0xff;
    hdr[1] = p.length & 0xff;
    chunks.push(hdr, p);
  }
  return sha256(concatBytes(...chunks));
}

export async function deriveSessionKeys(shared, secret, th) {
  const info = concatBytes(ENC.encode('tchiko-rc v1 keys'), th);
  const okm = await hkdfSha256(shared, secret, info, 96);
  return {
    c2sKey: okm.slice(0, 32),
    s2cKey: okm.slice(32, 64),
    confirmKey: okm.slice(64, 96),
  };
}

export async function makeProof(confirmKey, role, th) {
  return hmacSha256(confirmKey, concatBytes(ENC.encode(role), th));
}

export async function computeSafetyCode(th) {
  const digest = await sha256(concatBytes(ENC.encode('safety'), th));
  const val = ((digest[0] << 24) | (digest[1] << 16) | (digest[2] << 8) | digest[3]) >>> 0;
  const digits = String(val % 1_000_000).padStart(6, '0');
  return `${digits.slice(0, 3)} ${digits.slice(3)}`;
}

export async function generateEcdh() {
  const pair = await SUBTLE().generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
  const pubRaw = new Uint8Array(await SUBTLE().exportKey('raw', pair.publicKey));
  return {
    privateKey: pair.privateKey,
    publicRaw: pubRaw,
    async sharedSecret(peerPubRaw) {
      const peerKey = await SUBTLE().importKey(
        'raw',
        peerPubRaw,
        { name: 'ECDH', namedCurve: 'P-256' },
        false,
        [],
      );
      return new Uint8Array(await SUBTLE().deriveBits({ name: 'ECDH', public: peerKey }, pair.privateKey, 256));
    },
  };
}

function makeNonce(direction, counter) {
  const nonce = new Uint8Array(12);
  const view = new DataView(nonce.buffer);
  view.setUint32(0, direction, false);
  view.setBigUint64(4, counter, false);
  return nonce;
}

function makeAad(direction) {
  return concatBytes(ENC.encode('tchiko-rc'), new Uint8Array([direction]));
}

/** Counter-checked AES-256-GCM bidirectional secure channel. */
export class SecureChannel {
  constructor(sendKey, recvKey, sendDir = DIR_CLIENT_TO_SERVER, recvDir = DIR_SERVER_TO_CLIENT) {
    this._sendKey = sendKey;
    this._recvKey = recvKey;
    this._sendDir = sendDir;
    this._recvDir = recvDir;
    this._sendCtr = 0n;
    this._recvCtr = 0n;
  }

  static async create(sendKeyBytes, recvKeyBytes, sendDir = DIR_CLIENT_TO_SERVER, recvDir = DIR_SERVER_TO_CLIENT) {
    const sendKey = await SUBTLE().importKey('raw', sendKeyBytes, { name: 'AES-GCM' }, false, ['encrypt']);
    const recvKey = await SUBTLE().importKey('raw', recvKeyBytes, { name: 'AES-GCM' }, false, ['decrypt']);
    return new SecureChannel(sendKey, recvKey, sendDir, recvDir);
  }

  async seal(plaintext) {
    const data = plaintext instanceof Uint8Array ? plaintext : ENC.encode(plaintext);
    const ctr = this._sendCtr++;
    const nonce = makeNonce(this._sendDir, ctr);
    const ct = new Uint8Array(
      await SUBTLE().encrypt(
        { name: 'AES-GCM', iv: nonce, additionalData: makeAad(this._sendDir), tagLength: 128 },
        this._sendKey,
        data,
      ),
    );
    const hdr = new Uint8Array(8);
    new DataView(hdr.buffer).setBigUint64(0, ctr, false);
    return concatBytes(hdr, ct);
  }

  async open(frameBytes) {
    const frame = frameBytes instanceof Uint8Array ? frameBytes : new Uint8Array(frameBytes);
    if (frame.length < 24) throw new Error('Encrypted frame too short');
    const ctr = new DataView(frame.buffer, frame.byteOffset, 8).getBigUint64(0, false);
    if (ctr !== this._recvCtr) {
      throw new Error('Unexpected frame counter (replay or reordering detected)');
    }
    const nonce = makeNonce(this._recvDir, ctr);
    const plain = new Uint8Array(
      await SUBTLE().decrypt(
        { name: 'AES-GCM', iv: nonce, additionalData: makeAad(this._recvDir), tagLength: 128 },
        this._recvKey,
        frame.subarray(8),
      ),
    );
    this._recvCtr++;
    return plain;
  }
}

/** Detect a short human-readable device name for the desktop pairing display. */
export function guessDeviceName() {
  const ua = typeof navigator !== 'undefined' ? navigator.userAgent || '' : 'Node Client';
  const os = /Android/i.test(ua)
    ? 'Android'
    : /iPhone/i.test(ua)
      ? 'iPhone'
      : /iPad/i.test(ua)
        ? 'iPad'
        : /Mac OS X/i.test(ua)
          ? 'macOS'
          : /Windows/i.test(ua)
            ? 'Windows'
            : /Linux/i.test(ua)
              ? 'Linux'
              : 'Remote';
  const browser = /Firefox/i.test(ua)
    ? 'Firefox'
    : /Edg\//i.test(ua)
      ? 'Edge'
      : /Chrome/i.test(ua)
        ? 'Chrome'
        : /Safari/i.test(ua)
          ? 'Safari'
          : 'Browser';
  return `${os} · ${browser}`;
}

/**
 * High-level Tchiko RC encrypted WebSocket client.
 *
 * Credentials:
 *   - Pairing:  { mode: 'pair', sessionId: Uint8Array(3), secret: Uint8Array(12) }
 *   - Resume:   { mode: 'resume', deviceId: string(b64u), resumeSecret: string(b64u) }
 */
export class TchikoChannel {
  constructor(wsUrl, { WebSocketImpl = globalThis.WebSocket, onMessage, onStatus, onPaired, onError } = {}) {
    this.wsUrl = wsUrl;
    this.WebSocketImpl = WebSocketImpl;
    this.onMessage = onMessage || (() => {});
    this.onStatus = onStatus || (() => {});
    this.onPaired = onPaired || (() => {});
    this.onError = onError || (() => {});
    this._ws = null;
    this._channel = null;
    this._authenticated = false;
    this._closedByUser = false;
    this._sendChain = Promise.resolve();
    this.safetyCode = '';
    this.host = '';
  }

  get connected() {
    return this._authenticated && this._ws && this._ws.readyState === 1;
  }

  connect(credentials, deviceName = guessDeviceName()) {
    this.disconnect();
    this._closedByUser = false;
    this._authenticated = false;
    this._channel = null;
    this._sendChain = Promise.resolve();
    this.onStatus('connecting', 'Establishing encrypted channel…');

    return new Promise((resolve, reject) => {
      let settled = false;
      const fail = (err, code = 'error') => {
        const message = err instanceof Error ? err.message : String(err);
        if (!settled) {
          settled = true;
          reject(Object.assign(new Error(message), { code }));
        }
        this.onError(message, code);
      };

      let ws;
      try {
        ws = new this.WebSocketImpl(this.wsUrl);
        ws.binaryType = 'arraybuffer';
      } catch (err) {
        fail(err, 'ws_init');
        return;
      }
      this._ws = ws;

      let state = 'wait_hello';
      let pendingKeys = null;
      let expectedServerProof = null;
      let expectedSafetyCode = '';

      ws.addEventListener('error', () => {
        if (!this._authenticated) {
          fail('Could not reach Tchiko Desktop. Check that both devices are on the same network.', 'network');
        }
      });

      ws.addEventListener('close', (ev) => {
        const wasAuth = this._authenticated;
        this._authenticated = false;
        this._channel = null;
        if (!settled) {
          fail(ev.reason || `Connection closed (${ev.code})`, ev.code === 4003 ? 'unpaired' : 'closed');
        } else if (wasAuth && !this._closedByUser) {
          const reason =
            ev.code === 4009
              ? 'Session replaced by another Tchiko RC connection'
              : ev.code === 4008
                ? ev.reason || 'Disconnected by desktop'
                : ev.reason || 'Connection lost';
          this.onStatus('disconnected', reason, ev.code);
        }
      });

      let recvChain = Promise.resolve();
      const handleMessage = async (data) => {
        try {
          if (state === 'wait_hello') {
            if (typeof data !== 'string') throw new Error('Expected hello JSON');
            const hello = JSON.parse(data);
            if (hello.type !== 'hello' || hello.v !== 1) throw new Error('Unsupported Tchiko RC version');

            const serverPub = b64uDecode(hello.server_pub);
            const serverNonce = b64uDecode(hello.server_nonce);
            const clientKp = await generateEcdh();
            const clientNonce = new Uint8Array(16);
            globalThis.crypto.getRandomValues(clientNonce);

            let context;
            let secret;
            const authMsg = {
              type: 'auth',
              mode: credentials.mode,
              client_pub: b64uEncode(clientKp.publicRaw),
              client_nonce: b64uEncode(clientNonce),
              device_name: deviceName,
            };

            if (credentials.mode === 'pair') {
              context = concatBytes(ENC.encode('pair:'), credentials.sessionId);
              secret = credentials.secret;
              authMsg.session_id = b64uEncode(credentials.sessionId);
            } else {
              const devIdBytes = b64uDecode(credentials.deviceId);
              context = concatBytes(ENC.encode('resume:'), devIdBytes);
              secret = b64uDecode(credentials.resumeSecret);
              authMsg.device_id = credentials.deviceId;
            }

            const shared = await clientKp.sharedSecret(serverPub);
            const th = await transcriptHash(context, clientKp.publicRaw, serverPub, clientNonce, serverNonce);
            const keys = await deriveSessionKeys(shared, secret, th);
            const clientProof = await makeProof(keys.confirmKey, 'client', th);
            expectedServerProof = await makeProof(keys.confirmKey, 'server', th);
            expectedSafetyCode = await computeSafetyCode(th);
            pendingKeys = keys;
            authMsg.proof = b64uEncode(clientProof);
            this.host = hello.host || '';

            state = 'wait_auth_ok';
            ws.send(JSON.stringify(authMsg));
            return;
          }

          if (state === 'wait_auth_ok') {
            if (typeof data !== 'string') throw new Error('Expected auth_ok JSON');
            const resp = JSON.parse(data);
            if (resp.type === 'auth_error') {
              fail(resp.message || 'Authentication rejected', resp.code || 'auth_error');
              ws.close(4003, 'auth_error');
              return;
            }
            if (resp.type !== 'auth_ok') throw new Error('Unexpected handshake frame');
            const srvProof = b64uDecode(resp.proof);
            if (!constTimeEqual(srvProof, expectedServerProof)) {
              fail('Server authentication failed — potential MITM detected', 'mitm');
              ws.close(4002, 'server_proof_mismatch');
              return;
            }
            this._channel = await SecureChannel.create(pendingKeys.c2sKey, pendingKeys.s2cKey);
            pendingKeys = null;
            this.safetyCode = expectedSafetyCode;
            this.host = resp.host || this.host;
            this._authenticated = true;
            state = 'ready';
            this.onStatus('connected', `Encrypted · ${this.host}`);
            if (!settled) {
              settled = true;
              resolve({ host: this.host, safetyCode: this.safetyCode });
            }
            return;
          }

          if (state === 'ready') {
            let bytes;
            if (data instanceof ArrayBuffer) {
              bytes = new Uint8Array(data);
            } else if (ArrayBuffer.isView(data)) {
              bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
            } else if (typeof Blob !== 'undefined' && data instanceof Blob) {
              bytes = new Uint8Array(await data.arrayBuffer());
            } else {
              throw new Error('Rejected unencrypted text frame on secure channel');
            }
            if (!this._channel) return;
            const plain = await this._channel.open(bytes);
            const msg = JSON.parse(DEC.decode(plain));
            if (msg.type === 'paired') {
              this.onPaired({
                deviceId: msg.device_id,
                resumeSecret: msg.resume_secret,
                host: msg.host,
                safetyCode: msg.safety_code,
              });
            }
            this.onMessage(msg);
          }
        } catch (err) {
          fail(err, 'protocol');
          try {
            ws.close(4002, 'protocol_error');
          } catch {}
        }
      };

      ws.addEventListener('message', (ev) => {
        const data = ev.data;
        recvChain = recvChain.then(() => handleMessage(data));
      });
    });
  }

  /** Encrypt and queue a JSON object sequentially so counter ordering is guaranteed. */
  send(obj) {
    if (!this.connected || !this._channel) return Promise.reject(new Error('Not connected'));
    const payload = JSON.stringify(obj);
    this._sendChain = this._sendChain.then(async () => {
      if (!this.connected || !this._channel) return;
      const frame = await this._channel.seal(payload);
      this._ws.send(frame);
    });
    return this._sendChain;
  }

  disconnect() {
    this._closedByUser = true;
    this._authenticated = false;
    this._channel = null;
    if (this._ws) {
      try {
        this._ws.close(1000, 'Client disconnected');
      } catch {}
      this._ws = null;
    }
  }
}

// Tchiko RC — Main web application controller.
// Pure vanilla ES modules, zero frameworks, full Tchiko Desktop parity over an encrypted channel.

import { BoopFaceAvatar, COATS, MOODS } from './boopface.js';
import { TchikoChannel } from './channel.js';
import { renderMarkdownInto } from './markdown.js';
import { SigilCameraScanner, consumeHashPairToken, decodeSigilFromBlob } from './scanner.js';
import { RingGauge, copyText, iconSvg, showToast } from './ui.js';

const STORAGE_KEY = 'tchiko_rc_pair_v1';
const SSH_KEY_PROMPT = 'create an ssh key for my remote hetzner server in OpenSSH format';

const STARTERS = [
  { code: 'DIAG // SYS_HEALTH', icon: 'monitor', title: 'System Health Audit', desc: '/doctor · cpu, ram, storage, systemd', prompt: '/doctor' },
  { code: 'NET // PORT_AUDIT', icon: 'network', title: 'Open Socket Radar', desc: 'ss -tulpn · inspect listening daemon ports', prompt: 'check listening ports' },
  { code: 'SEC // SSH_KEYSMITH', icon: 'key', title: 'Ed25519 Key Forge', desc: 'generate hardened OpenSSH auth keypair', prompt: SSH_KEY_PROMPT },
  { code: 'MEM // CONTEXT_LEDGER', icon: 'memory', title: 'Active State & Ledger', desc: '/memory · session notes & active runbooks', prompt: '/memory' },
];

const QUICK_ACTIONS = [
  { code: 'SYS // DOCTOR', icon: 'monitor', title: 'Doctor Audit', desc: 'Full systemd & hardware diagnosis', prompt: '/doctor' },
  { code: 'PROC // TOP_LOAD', icon: 'list', title: 'Process Telemetry', desc: 'Active CPU/RSS memory hogs', prompt: '/procs' },
  { code: 'NET // SOCKETS', icon: 'network', title: 'Listening Ports', desc: 'Inspect listening sockets & bindings', prompt: 'check listening ports' },
  { code: 'CONT // DOCKER', icon: 'package', title: 'Docker Containers', desc: 'Daemon container fleet status', prompt: 'check docker containers' },
  { code: 'ENV // TOOLCHAINS', icon: 'wrench', title: 'Runtime Manifest', desc: 'python, node, git, rust toolchains', prompt: 'check installed tools versions' },
  { code: 'SEC // SSH_KEY', icon: 'key', title: 'Generate SSH Key', desc: 'Hardened Ed25519 OpenSSH pair', prompt: SSH_KEY_PROMPT },
];

const SLASH_MENU = [
  ['System doctor', '/doctor'],
  ['System report', '/sysinfo'],
  ['Top processes', '/procs'],
  ['Listening ports', 'check listening ports'],
  ['Desktop files', '/files ~/Desktop'],
  ['Memory and notes', '/memory'],
  ['Permission policy', '/permissions'],
  ['Help', '/help'],
];

const CAPABILITIES = [
  ['bash_execution', 'terminal', 'Shell commands', 'Run bash and terminal commands'],
  ['filesystem_read_write', 'folder', 'Files', 'Read and write anywhere on the filesystem'],
  ['process_management', 'cpu', 'Processes and services', 'Inspect and manage with ps and systemctl'],
  ['desktop_automation', 'desktop', 'Desktop', 'Open apps, files and links; send notifications'],
  ['package_management', 'package', 'Packages', 'Install and update with apt, pip and npm'],
  ['network_requests', 'network', 'Network', 'Diagnostics and outbound requests'],
];

const TOOL_POLICIES = [
  ['always-proceed', 'Run without asking'],
  ['request-review', 'Ask before each command'],
  ['proceed-in-sandbox', 'Run inside the sandbox'],
  ['strict', 'Read-only'],
];

const ACCESS_CHOICES = [
  ['allow', 'Allow'],
  ['ask', 'Ask first'],
  ['deny', 'Block'],
];

const MODELS = ['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-next', 'antigravity-default'];

const $ = (id) => document.getElementById(id);

function wsEndpoint() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws`;
}

function loadSavedPair() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (obj && obj.deviceId && obj.resumeSecret) return obj;
  } catch {}
  return null;
}

function savePair(rec) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(rec));
  } catch {}
}

function clearSavedPair() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {}
}

class TchikoRCApp {
  constructor() {
    this.channel = null;
    this.scanner = null;
    this.avatars = {};
    this.gauges = {};
    this.config = null;
    this.state = {
      view: 'chat',
      settingsTab: 'access',
      busy: false,
      host: '',
      safetyCode: '',
      deviceName: '',
      engineLabel: '',
      cwd: '~',
      pendingApprovalId: null,
      latencyMs: null,
    };
    this._stream = null;
    this._pingTimer = null;
    this._updatingSettings = false;
    this._coatPreviews = {};
  }

  init() {
    this._initPairScreen();
    this._initAppShell();
    this._initPopovers();
    this._initGlobalPaste();

    // 1. One-step link (#pair=<token>) takes immediate priority.
    const hashPair = consumeHashPairToken();
    if (hashPair) {
      this._connectWithSigil(hashPair);
      return;
    }

    // 2. Previously paired device: auto-resume encrypted channel.
    const saved = loadSavedPair();
    if (saved) {
      this._showSavedBanner(saved);
      this._connectWithResume(saved, true);
    }
  }

  // ── Pair screen ────────────────────────────────────────────────────────────
  _initPairScreen() {
    this.avatars.pair = new BoopFaceAvatar($('pair-boopface'), { size: 96, coat: 'phantom_cyan' });

    const videoEl = $('scanner-video');
    this.scanner = new SigilCameraScanner(videoEl, {
      onDetected: (decoded) => {
        this._hideCameraOverlay();
        showToast('Tchiko Sigil recognized — securing channel…', 'success');
        this._connectWithSigil(decoded);
      },
      onError: (msg) => {
        this._hideCameraOverlay();
        this._setPairError(msg);
      },
      onState: (st) => {
        $('scanner-state').textContent =
          st === 'starting'
            ? 'Opening camera…'
            : st === 'scanning'
              ? 'Align the Tchiko Sigil inside the ring'
              : '';
      },
    });

    $('btn-scan-sigil').addEventListener('click', () => {
      this._setPairError('');
      $('scanner-overlay').hidden = false;
      this.scanner.start();
    });

    $('btn-close-scanner').addEventListener('click', () => {
      this.scanner.stop();
      this._hideCameraOverlay();
    });

    const fileInput = $('sigil-file-input');
    $('btn-upload-sigil').addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = '';
      if (file) await this._handleSigilBlob(file);
    });

    const dropZone = $('pair-dropzone');
    for (const evName of ['dragenter', 'dragover']) {
      dropZone.addEventListener(evName, (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
      });
    }
    for (const evName of ['dragleave', 'drop']) {
      dropZone.addEventListener(evName, (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
      });
    }
    dropZone.addEventListener('drop', async (e) => {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) await this._handleSigilBlob(file);
    });

    $('btn-resume-saved').addEventListener('click', () => {
      const saved = loadSavedPair();
      if (saved) this._connectWithResume(saved, false);
    });
    $('btn-forget-saved').addEventListener('click', () => {
      clearSavedPair();
      $('saved-pair-card').hidden = true;
      showToast('Cleared saved device pairing');
    });
  }

  _initGlobalPaste() {
    window.addEventListener('paste', async (e) => {
      if ($('pair-screen').hidden) return;
      const items = (e.clipboardData && e.clipboardData.items) || [];
      for (const item of items) {
        if (item.type && item.type.startsWith('image/')) {
          const blob = item.getAsFile();
          if (blob) {
            e.preventDefault();
            await this._handleSigilBlob(blob);
            return;
          }
        }
      }
    });
  }

  async _handleSigilBlob(blob) {
    this._setPairError('');
    this._setPairBusy(true, 'Reading Tchiko Sigil…');
    try {
      const decoded = await decodeSigilFromBlob(blob);
      if (!decoded) {
        this._setPairBusy(false);
        this._setPairError('No Tchiko Sigil found in that image. Make sure the full circular ring is visible.');
        return;
      }
      await this._connectWithSigil(decoded);
    } catch (err) {
      this._setPairBusy(false);
      this._setPairError(err.message || 'Could not decode image.');
    }
  }

  _hideCameraOverlay() {
    $('scanner-overlay').hidden = true;
  }

  _showSavedBanner(saved) {
    $('saved-pair-host').textContent = saved.host || 'Tchiko Desktop';
    $('saved-pair-card').hidden = false;
  }

  _setPairError(msg) {
    const el = $('pair-error');
    el.textContent = msg;
    el.hidden = !msg;
  }

  _setPairBusy(busy, label = '') {
    $('pair-busy').hidden = !busy;
    if (label) $('pair-busy-label').textContent = label;
    $('btn-scan-sigil').disabled = busy;
    $('btn-upload-sigil').disabled = busy;
  }

  // ── Connection lifecycle ───────────────────────────────────────────────────
  _createChannel() {
    if (this.channel) this.channel.disconnect();
    this.channel = new TchikoChannel(wsEndpoint(), {
      onMessage: (msg) => this._onServerMessage(msg),
      onPaired: (rec) => {
        savePair(rec);
        this._showSavedBanner(rec);
      },
      onStatus: (status, detail, code) => {
        if (status === 'disconnected') {
          this._stopPing();
          this._showPairScreen(detail || 'Disconnected from Tchiko Desktop');
          if (code === 4009) {
            showToast('Session moved to another Tchiko RC connection', 'warn');
          } else if (code === 4008) {
            showToast(detail || 'Disconnected by desktop', 'warn');
          }
        }
      },
      onError: () => {},
    });
    return this.channel;
  }

  async _connectWithSigil(decoded) {
    this._setPairError('');
    this._setPairBusy(true, 'Handshaking (ECDH P-256 + AES-256-GCM)…');
    try {
      const ch = this._createChannel();
      const res = await ch.connect({
        mode: 'pair',
        sessionId: decoded.sessionId,
        secret: decoded.secret,
      });
      this._onAuthenticated(res);
    } catch (err) {
      this._setPairBusy(false);
      this._setPairError(err.message || 'Pairing failed.');
    }
  }

  async _connectWithResume(saved, silent) {
    this._setPairError('');
    this._setPairBusy(true, `Reconnecting to ${saved.host || 'Tchiko Desktop'}…`);
    try {
      const ch = this._createChannel();
      const res = await ch.connect({
        mode: 'resume',
        deviceId: saved.deviceId,
        resumeSecret: saved.resumeSecret,
      });
      this._onAuthenticated(res);
    } catch (err) {
      this._setPairBusy(false);
      if (err.code === 'unpaired') {
        clearSavedPair();
        $('saved-pair-card').hidden = true;
      }
      if (!silent || err.code === 'unpaired') {
        this._setPairError(err.message || 'Could not reconnect.');
      }
    }
  }

  _onAuthenticated({ host, safetyCode }) {
    this._setPairBusy(false);
    this.state.host = host;
    this.state.safetyCode = safetyCode;
    $('pair-screen').hidden = true;
    $('app-shell').hidden = false;
    $('safety-code-value').textContent = safetyCode;
    $('remote-safety-code').textContent = safetyCode;
    $('remote-host-name').textContent = host || 'Tchiko Desktop';
    $('session-host-label').textContent = host || 'Tchiko Desktop';
    this._startPing();
    showToast(`Encrypted channel active · ${safetyCode}`, 'success');
    $('prompt-input').focus();
  }

  _showPairScreen(reason) {
    $('app-shell').hidden = true;
    $('pair-screen').hidden = false;
    this._setPairBusy(false);
    if (reason) this._setPairError(reason);
    const saved = loadSavedPair();
    if (saved) this._showSavedBanner(saved);
  }

  _startPing() {
    this._stopPing();
    const sendPing = () => {
      if (this.channel && this.channel.connected) {
        this.channel.send({ type: 'ping', t: Date.now() }).catch(() => {});
      }
    };
    sendPing();
    this._pingTimer = setInterval(sendPing, 12000);
  }

  _stopPing() {
    if (this._pingTimer) {
      clearInterval(this._pingTimer);
      this._pingTimer = null;
    }
  }

  // ── App shell setup ────────────────────────────────────────────────────────
  _initAppShell() {
    this.avatars.mini = new BoopFaceAvatar($('header-boopface'), { size: 34, coat: 'phantom_cyan' });
    this.avatars.welcome = new BoopFaceAvatar($('welcome-boopface'), { size: 112, coat: 'phantom_cyan' });

    // Segmented nav switcher
    document.querySelectorAll('[data-nav]').forEach((btn) => {
      btn.addEventListener('click', () => this._switchView(btn.dataset.nav));
    });

    // Header actions
    $('btn-new-chat').addEventListener('click', () => {
      if (this.state.busy) {
        showToast('Wait for Tchiko to finish the current reply', 'warn');
        return;
      }
      this._send({ type: 'new_chat' });
    });

    $('btn-perm-pill').addEventListener('click', () => {
      this._switchView('settings');
      this._switchSettingsTab('access');
    });

    $('btn-security-pill').addEventListener('click', () => {
      $('session-modal').hidden = false;
    });
    $('btn-close-session-modal').addEventListener('click', () => {
      $('session-modal').hidden = true;
    });
    $('session-modal').addEventListener('click', (e) => {
      if (e.target === $('session-modal')) $('session-modal').hidden = true;
    });

    $('btn-modal-disconnect').addEventListener('click', () => {
      $('session-modal').hidden = true;
      this._disconnectManual();
    });
    $('btn-modal-unpair').addEventListener('click', () => {
      $('session-modal').hidden = true;
      this._unpairDevice();
    });

    // Welcome starter tiles
    const starterGrid = $('starter-grid');
    starterGrid.innerHTML = '';
    for (const s of STARTERS) starterGrid.append(this._makeTile(s));

    // Quick actions grid on System page
    const qaGrid = $('quick-actions-grid');
    qaGrid.innerHTML = '';
    for (const a of QUICK_ACTIONS) qaGrid.append(this._makeTile(a));

    // Ring gauges
    this.gauges.cpu = new RingGauge($('gauge-cpu'), 76);
    this.gauges.ram = new RingGauge($('gauge-ram'), 76);
    this.gauges.disk = new RingGauge($('gauge-disk'), 76);

    // System page Full Access toggle
    $('sys-full-access').addEventListener('change', (e) => {
      if (this._updatingSettings) return;
      this._send({ type: 'update_config', patch: { approve_all_system_permissions: e.target.checked } });
    });

    // Approval banner buttons
    $('btn-approve-run').addEventListener('click', () => this._sendApproval('allow'));
    $('btn-approve-always').addEventListener('click', () => this._sendApproval('always'));
    $('btn-approve-deny').addEventListener('click', () => this._sendApproval('deny'));

    // Chat composer
    const input = $('prompt-input');
    const composer = $('composer-box');
    const syncSend = () => {
      $('btn-send').disabled = this.state.busy || !input.value.trim();
    };
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
      syncSend();
    });
    input.addEventListener('focus', () => composer.classList.add('focused'));
    input.addEventListener('blur', () => composer.classList.remove('focused'));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._submitComposer();
      }
    });
    $('btn-send').addEventListener('click', () => this._submitComposer());
    this._syncSend = syncSend;

    // Activity clear
    $('btn-clear-activity').addEventListener('click', () => {
      this._send({ type: 'clear_activity' });
    });

    this._buildSettingsPage();
  }

  _initPopovers() {
    const slashPop = $('slash-popover');
    slashPop.innerHTML = '';
    for (const [label, cmd] of SLASH_MENU) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'popover-item';
      btn.innerHTML = `<span>${label}</span><span class="mono muted">${cmd}</span>`;
      btn.addEventListener('click', () => {
        slashPop.hidden = true;
        this._submitPrompt(cmd);
      });
      slashPop.append(btn);
    }

    const moodPop = $('mood-popover');
    moodPop.innerHTML = '';
    for (const [key, label] of MOODS) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'popover-item';
      btn.textContent = label;
      btn.addEventListener('click', () => {
        moodPop.hidden = true;
        this._triggerMood(key);
      });
      moodPop.append(btn);
    }

    $('btn-slash-menu').addEventListener('click', (e) => {
      e.stopPropagation();
      moodPop.hidden = true;
      slashPop.hidden = !slashPop.hidden;
    });
    $('btn-mood-menu').addEventListener('click', (e) => {
      e.stopPropagation();
      slashPop.hidden = true;
      moodPop.hidden = !moodPop.hidden;
    });
    document.addEventListener('click', () => {
      slashPop.hidden = true;
      moodPop.hidden = true;
    });
  }

  _buildSettingsPage() {
    document.querySelectorAll('[data-settings-tab]').forEach((btn) => {
      btn.addEventListener('click', () => this._switchSettingsTab(btn.dataset.settingsTab));
    });

    // Capabilities rows
    const capsCard = $('settings-caps-card');
    capsCard.innerHTML = '';
    for (const [key, ico, title, desc] of CAPABILITIES) {
      const row = document.createElement('label');
      row.className = 'pref-row';
      row.innerHTML = `
        <span class="pref-ico">${iconSvg(ico, 16)}</span>
        <span class="pref-text">
          <span class="pref-title">${title}</span>
          <span class="pref-desc">${desc}</span>
        </span>
        <input type="checkbox" class="tchiko-switch" data-cap="${key}" />
      `;
      capsCard.append(row);
    }

    // Select choices
    const fillSelect = (id, list) => {
      const sel = $(id);
      sel.innerHTML = '';
      for (const [val, label] of list) {
        const opt = document.createElement('option');
        opt.value = val;
        opt.textContent = label;
        sel.append(opt);
      }
    };
    fillSelect('set-tool-policy', TOOL_POLICIES);
    fillSelect('set-file-access', ACCESS_CHOICES);
    fillSelect('set-net-access', ACCESS_CHOICES);
    fillSelect('set-model', MODELS.map((m) => [m, m]));

    // Coat picker
    const coatGrid = $('settings-coat-grid');
    coatGrid.innerHTML = '';
    for (const [key, spec] of Object.entries(COATS)) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'coat-btn';
      btn.dataset.coat = key;
      const thumb = document.createElement('div');
      thumb.className = 'coat-thumb';
      const lbl = document.createElement('span');
      lbl.textContent = spec.label;
      btn.append(thumb, lbl);
      this._coatPreviews[key] = new BoopFaceAvatar(thumb, { size: 68, coat: key, interactive: false, animate: false });
      btn.addEventListener('click', () => {
        if (this._updatingSettings) return;
        this._send({ type: 'update_config', patch: { ghost_widget: { theme: key } } });
      });
      coatGrid.append(btn);
    }

    // Wire settings controls
    $('set-master-switch').addEventListener('change', (e) => {
      if (this._updatingSettings) return;
      this._send({ type: 'update_config', patch: { approve_all_system_permissions: e.target.checked } });
    });

    const sendPermPatch = () => {
      if (this._updatingSettings) return;
      const capabilities = {};
      document.querySelectorAll('[data-cap]').forEach((el) => {
        capabilities[el.dataset.cap] = el.checked;
      });
      this._send({
        type: 'update_config',
        patch: {
          permissions: {
            tool_execution_policy: $('set-tool-policy').value,
            non_workspace_file_access: $('set-file-access').value,
            internet_access_policy: $('set-net-access').value,
            terminal_sandbox: $('set-sandbox').checked,
            capabilities,
          },
        },
      });
    };

    document.querySelectorAll('[data-cap]').forEach((el) => el.addEventListener('change', sendPermPatch));
    for (const id of ['set-tool-policy', 'set-file-access', 'set-net-access', 'set-sandbox']) {
      $(id).addEventListener('change', sendPermPatch);
    }

    $('set-model').addEventListener('change', (e) => {
      if (this._updatingSettings) return;
      this._send({ type: 'update_config', patch: { agent: { model: e.target.value } } });
    });

    const sendGhostPatch = () => {
      if (this._updatingSettings) return;
      const size = Number($('set-size').value);
      const opacity = Number($('set-opacity').value);
      $('set-size-val').textContent = `${size} px`;
      $('set-opacity-val').textContent = `${Math.round(opacity * 100)}%`;
      this._send({
        type: 'update_config',
        patch: {
          ghost_widget: {
            size,
            opacity,
            always_on_top: $('set-always-top').checked,
            show_speech_bubble: $('set-bubble').checked,
          },
        },
      });
    };
    for (const id of ['set-size', 'set-opacity', 'set-always-top', 'set-bubble']) {
      $(id).addEventListener('input', sendGhostPatch);
      $(id).addEventListener('change', sendGhostPatch);
    }

    $('btn-settings-disconnect').addEventListener('click', () => this._disconnectManual());
    $('btn-settings-unpair').addEventListener('click', () => this._unpairDevice());
  }

  _makeTile({ icon, title, desc, prompt, code }) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'action-tile';
    btn.innerHTML = `
      <span class="tile-icon">${iconSvg(icon, 16)}</span>
      <span class="tile-text">
        ${code ? `<span class="tile-code">${code}</span>` : ''}
        <span class="tile-title">${title}</span>
        <span class="tile-desc">${desc}</span>
      </span>
    `;
    btn.addEventListener('click', () => {
      this._switchView('chat');
      this._submitPrompt(prompt);
    });
    return btn;
  }

  _switchView(view) {
    this.state.view = view;
    document.querySelectorAll('[data-nav]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.nav === view);
    });
    for (const v of ['chat', 'system', 'activity', 'settings']) {
      $(`view-${v}`).hidden = v !== view;
    }
    if (view === 'system') this._send({ type: 'request_telemetry' });
    if (view === 'chat') $('prompt-input').focus();
  }

  _switchSettingsTab(tab) {
    this.state.settingsTab = tab;
    document.querySelectorAll('[data-settings-tab]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.settingsTab === tab);
    });
    for (const t of ['access', 'agent', 'companion', 'remote']) {
      $(`settings-panel-${t}`).hidden = t !== tab;
    }
  }

  // ── Outbound commands ──────────────────────────────────────────────────────
  _send(msg) {
    if (!this.channel || !this.channel.connected) return;
    this.channel.send(msg).catch(() => {});
  }

  _submitComposer() {
    const input = $('prompt-input');
    const text = input.value.trim();
    if (!text || this.state.busy) return;
    input.value = '';
    input.style.height = 'auto';
    this._syncSend();
    this._submitPrompt(text);
  }

  _submitPrompt(text) {
    if (!text.trim() || this.state.busy) return;
    this.state.busy = true;
    this._syncSend();
    this._setStatus('thinking', 'Thinking…');
    this._send({ type: 'prompt', text: text.trim() });
  }

  _sendApproval(decision) {
    const id = this.state.pendingApprovalId;
    if (!id) return;
    this.state.pendingApprovalId = null;
    $('approval-banner').hidden = true;
    this._send({ type: 'approval_response', id, decision });
  }

  _triggerMood(mood) {
    this.avatars.mini.setMood(mood, 6);
    this.avatars.welcome.setMood(mood, 6);
    this._send({ type: 'trigger_mood', mood });
  }

  _disconnectManual() {
    this._stopPing();
    if (this.channel) this.channel.disconnect();
    this._showPairScreen('');
    showToast('Disconnected from Tchiko Desktop');
  }

  _unpairDevice() {
    this._send({ type: 'unpair' });
    clearSavedPair();
    $('saved-pair-card').hidden = true;
    setTimeout(() => {
      this._stopPing();
      if (this.channel) this.channel.disconnect();
      this._showPairScreen('');
      showToast('Device unpaired from Tchiko Desktop', 'warn');
    }, 120);
  }

  // ── Inbound server messages ────────────────────────────────────────────────
  _onServerMessage(msg) {
    switch (msg.type) {
      case 'state_sync':
        this._applyStateSync(msg);
        break;
      case 'telemetry':
        this._applyTelemetry(msg.telemetry);
        if (msg.cwd) this._setCwd(msg.cwd);
        break;
      case 'config_updated':
        this._applyConfig(msg.config);
        break;
      case 'chat_user':
        this._hideWelcome();
        this._appendUserBubble(msg.text);
        break;
      case 'reply_start':
        this.state.busy = true;
        this._syncSend();
        this._startStreamingReply(msg.ts);
        break;
      case 'thought':
        this._appendActivity('think', msg.text, msg.ts);
        this._setStreamChip(msg.text);
        break;
      case 'tool_call':
        this._appendActivity('tool', `${msg.name}  ${msg.args}`, msg.ts);
        this._setStreamChip(`Running ${msg.name}…`);
        this._setStatus('executing', `Running ${msg.name}…`);
        break;
      case 'token':
        this._appendStreamToken(msg.text);
        break;
      case 'reply_complete':
        this._finishStreamingReply(msg);
        break;
      case 'agent_state':
        this._applyAgentState(msg.state, msg.mood);
        break;
      case 'approval_needed':
        this._showApprovalBanner(msg.id, msg.command);
        break;
      case 'approval_resolved':
        if (this.state.pendingApprovalId === msg.id) {
          this.state.pendingApprovalId = null;
          $('approval-banner').hidden = true;
        }
        break;
      case 'chat_reset':
        this._resetChatUi();
        break;
      case 'activity_cleared':
        this._clearActivityUi();
        break;
      case 'watchdog_alert':
        showToast(msg.message.replace(/\*\*/g, ''), 'warn');
        this._appendActivity('think', msg.message);
        break;
      case 'error':
        showToast(msg.message || 'Error', 'error');
        break;
      case 'pong':
        if (msg.t) {
          this.state.latencyMs = Math.max(1, Date.now() - msg.t);
          $('session-latency').textContent = `${this.state.latencyMs} ms`;
        }
        break;
      case 'replaced':
      case 'kicked':
        showToast(msg.reason || 'Disconnected', 'warn');
        break;
    }
  }

  _applyStateSync(sync) {
    this.state.host = sync.host || this.state.host;
    this.state.safetyCode = sync.safety_code || this.state.safetyCode;
    this.state.engineLabel = sync.engine_label || '';
    this.state.busy = Boolean(sync.busy);
    this._syncSend();

    $('remote-host-name').textContent = this.state.host;
    $('session-host-label').textContent = this.state.host;
    $('session-engine-label').textContent = this.state.engineLabel || 'Antigravity';
    $('safety-code-value').textContent = this.state.safetyCode;
    $('remote-safety-code').textContent = this.state.safetyCode;

    if (sync.cwd) this._setCwd(sync.cwd);
    if (sync.telemetry) this._applyTelemetry(sync.telemetry);
    if (sync.config) this._applyConfig(sync.config);
    this._applyAgentState(sync.status || 'idle', sync.mood || 'idle');

    // Restore chat history
    const feed = $('chat-feed');
    feed.innerHTML = '';
    const history = Array.isArray(sync.history) ? sync.history : [];
    if (history.length > 0) {
      $('chat-welcome').hidden = true;
      for (const turn of history) {
        if (turn.role === 'user') {
          this._appendUserBubble(turn.content || '');
        } else {
          this._appendFinishedReply(turn.content || '', '', '');
        }
      }
      this._scrollChatToBottom(true);
    } else {
      $('chat-welcome').hidden = false;
    }

    // Restore activity timeline
    this._clearActivityUi();
    for (const item of sync.activity || []) {
      this._appendActivity(item.kind, item.text, item.ts);
    }

    // Pending approval if any
    if (sync.pending_approvals && sync.pending_approvals.length > 0) {
      const p = sync.pending_approvals[0];
      this._showApprovalBanner(p.id, p.command);
    } else {
      $('approval-banner').hidden = true;
    }
  }

  _applyTelemetry(t) {
    if (!t) return;
    $('sys-hostname').textContent = t.hostname || 'Ubuntu Host';
    $('sys-sub').textContent = `${t.distro || 'Linux'}  ·  up ${t.uptime_str || '—'}`;

    const cores = Math.max(1, Number(t.cpu_cores) || 1);
    const load1 = Number(t.cpu_load_1m) || 0;
    this.gauges.cpu.setFraction(load1 / cores);
    $('val-cpu').textContent = String(t.cpu_load_1m ?? '—');
    $('det-cpu').textContent = `1-min load · ${cores} cores`;

    this.gauges.ram.setFraction((Number(t.ram_percent) || 0) / 100);
    $('val-ram').textContent = `${t.ram_used_gb ?? '—'} GB`;
    $('det-ram').textContent = `of ${t.ram_total_gb ?? '—'} GB`;

    this.gauges.disk.setFraction((Number(t.disk_percent) || 0) / 100);
    $('val-disk').textContent = `${t.disk_used_gb ?? '—'} GB`;
    $('det-disk').textContent = `of ${t.disk_total_gb ?? '—'} GB`;
  }

  _applyConfig(cfg) {
    if (!cfg) return;
    this.config = cfg;
    this._updatingSettings = true;
    try {
      const perms = cfg.permissions || {};
      const allOk = Boolean(perms.approve_all_system_permissions);

      const pill = $('btn-perm-pill');
      pill.classList.toggle('ok', allOk);
      pill.classList.toggle('review', !allOk);
      pill.textContent = allOk ? '●  Full access' : '●  Review mode';

      $('sys-full-access').checked = allOk;
      $('set-master-switch').checked = allOk;

      const hero = $('settings-access-hero');
      hero.classList.toggle('hero-ok', allOk);
      hero.classList.toggle('hero-review', !allOk);
      $('settings-hero-title').textContent = allOk ? 'Full access is on' : 'Supervised mode';
      $('settings-hero-desc').textContent = allOk
        ? 'Tchiko runs commands, edits files and manages services on its own, without asking.'
        : 'Tchiko is limited to the capabilities below and follows the execution policy.';

      const caps = perms.capabilities || {};
      document.querySelectorAll('[data-cap]').forEach((el) => {
        el.checked = Boolean(caps[el.dataset.cap]);
      });

      $('set-tool-policy').value = perms.tool_execution_policy || 'always-proceed';
      $('set-file-access').value = perms.non_workspace_file_access || 'allow';
      $('set-net-access').value = perms.internet_access_policy || 'allow';
      $('set-sandbox').checked = Boolean(perms.terminal_sandbox);
      $('set-model').value = (cfg.agent && cfg.agent.model) || 'gemini-2.5-pro';

      const gw = cfg.ghost_widget || {};
      const coat = gw.theme || 'phantom_cyan';
      this.avatars.mini.setCoat(coat);
      this.avatars.welcome.setCoat(coat);
      this.avatars.pair.setCoat(coat);

      document.querySelectorAll('.coat-btn').forEach((b) => {
        b.classList.toggle('selected', b.dataset.coat === coat);
      });

      const size = Number(gw.size) || 140;
      const opacity = Number(gw.opacity) || 0.96;
      $('set-size').value = String(size);
      $('set-size-val').textContent = `${size} px`;
      $('set-opacity').value = String(opacity);
      $('set-opacity-val').textContent = `${Math.round(opacity * 100)}%`;
      $('set-always-top').checked = Boolean(gw.always_on_top);
      $('set-bubble').checked = Boolean(gw.show_speech_bubble);
    } finally {
      this._updatingSettings = false;
    }
  }

  _applyAgentState(state, mood) {
    const labels = {
      idle: 'Ready',
      happy: 'Ready',
      thinking: 'Thinking…',
      executing: 'Working…',
      alert: 'Needs attention',
    };
    this._setStatus(state, labels[state] || state);
    if (mood) {
      this.avatars.mini.setMood(mood, ['thinking', 'executing'].includes(mood) ? 0 : 4);
      this.avatars.welcome.setMood(mood, ['thinking', 'executing'].includes(mood) ? 0 : 4);
    }
  }

  _setStatus(state, text) {
    const dot = $('header-status-dot');
    dot.className = `status-dot state-${state}`;
    $('header-status-text').textContent = text;
  }

  _setCwd(cwd) {
    this.state.cwd = cwd;
    $('composer-cwd').textContent = cwd;
  }

  // ── Chat rendering ─────────────────────────────────────────────────────────
  _hideWelcome() {
    $('chat-welcome').hidden = true;
  }

  _resetChatUi() {
    $('chat-feed').innerHTML = '';
    $('chat-welcome').hidden = false;
    this._stream = null;
    this._switchView('chat');
    showToast('Started a fresh chat');
  }

  _appendUserBubble(text) {
    const row = document.createElement('div');
    row.className = 'msg-row user';
    const bubble = document.createElement('div');
    bubble.className = 'user-bubble';
    bubble.textContent = text;
    row.append(bubble);
    $('chat-feed').append(row);
    this._scrollChatToBottom(true);
  }

  _startStreamingReply(ts) {
    const wrap = document.createElement('div');
    wrap.className = 'msg-row assistant';

    const head = document.createElement('div');
    head.className = 'reply-head';
    head.innerHTML = `<span class="accent-dot">●</span> <strong>Tchiko</strong> <span class="reply-ts">${ts || ''}</span>`;

    const chip = document.createElement('div');
    chip.className = 'activity-chip';
    chip.innerHTML = '<span class="spinner"></span><span class="chip-text">Thinking…</span>';

    const content = document.createElement('div');
    content.className = 'reply-content';

    const footer = document.createElement('div');
    footer.className = 'reply-footer';
    footer.hidden = true;

    wrap.append(head, chip, content, footer);
    $('chat-feed').append(wrap);
    this._scrollChatToBottom(true);

    this._stream = {
      raw: '',
      chip,
      chipText: chip.querySelector('.chip-text'),
      content,
      footer,
      flushTimer: null,
    };
  }

  _setStreamChip(text) {
    if (!this._stream || !this._stream.chipText) return;
    this._stream.chipText.textContent = String(text || '').replace(/\s+/g, ' ').slice(0, 140);
  }

  _appendStreamToken(tok) {
    if (!this._stream) this._startStreamingReply('');
    this._stream.raw += tok;
    if (!this._stream.flushTimer) {
      this._stream.flushTimer = setTimeout(() => {
        if (!this._stream) return;
        this._stream.flushTimer = null;
        renderMarkdownInto(this._stream.content, this._stream.raw, copyText);
        this._scrollChatToBottom(false);
      }, 45);
    }
  }

  _finishStreamingReply(msg) {
    const full = (msg.text || (this._stream && this._stream.raw) || '').trim();
    const parts = [];
    if (msg.tools) parts.push(`${msg.tools} tool call${msg.tools === 1 ? '' : 's'}`);
    if (msg.elapsed_sec != null) {
      const s = Number(msg.elapsed_sec);
      parts.push(s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m ${Math.floor(s % 60)}s`);
    }
    const meta = parts.join('  ·  ');

    if (this._stream) {
      if (this._stream.flushTimer) clearTimeout(this._stream.flushTimer);
      this._stream.chip.remove();
      renderMarkdownInto(this._stream.content, full || '(no reply)', copyText);
      this._populateFooter(this._stream.footer, full, meta);
      this._stream = null;
    } else {
      this._appendFinishedReply(full, msg.ts || '', meta);
    }

    this.state.busy = false;
    this._syncSend();
    if (msg.cwd) this._setCwd(msg.cwd);
    this._applyAgentState('idle', 'happy');
    this._scrollChatToBottom(false);
  }

  _appendFinishedReply(text, ts, meta) {
    const wrap = document.createElement('div');
    wrap.className = 'msg-row assistant';
    const head = document.createElement('div');
    head.className = 'reply-head';
    head.innerHTML = `<span class="accent-dot">●</span> <strong>Tchiko</strong> <span class="reply-ts">${ts}</span>`;
    const content = document.createElement('div');
    content.className = 'reply-content';
    renderMarkdownInto(content, text, copyText);
    const footer = document.createElement('div');
    footer.className = 'reply-footer';
    this._populateFooter(footer, text, meta);
    wrap.append(head, content, footer);
    $('chat-feed').append(wrap);
  }

  _populateFooter(footer, rawText, meta) {
    footer.hidden = false;
    footer.innerHTML = '';
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'icon-btn';
    copyBtn.title = 'Copy reply';
    copyBtn.innerHTML = iconSvg('copy', 14);
    copyBtn.addEventListener('click', () => copyText(rawText, copyBtn));
    footer.append(copyBtn);
    if (meta) {
      const span = document.createElement('span');
      span.className = 'muted';
      span.textContent = meta;
      footer.append(span);
    }
  }

  _showApprovalBanner(id, command) {
    this.state.pendingApprovalId = id;
    $('approval-cmd').textContent = command;
    $('approval-banner').hidden = false;
    this._setStatus('alert', 'Waiting for approval');
    this._setStreamChip('Waiting for your approval…');
    this._switchView('chat');
  }

  _scrollChatToBottom(force) {
    const scroller = $('chat-scroll');
    const nearBottom = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop < 120;
    if (force || nearBottom) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }

  // ── Activity timeline ──────────────────────────────────────────────────────
  _clearActivityUi() {
    $('activity-list').innerHTML = '';
    $('activity-empty').hidden = false;
  }

  _appendActivity(kind, text, ts) {
    $('activity-empty').hidden = true;
    const row = document.createElement('div');
    row.className = 'timeline-row';
    const timeEl = document.createElement('span');
    timeEl.className = 'tl-time mono';
    timeEl.textContent = ts || new Date().toTimeString().slice(0, 8);
    const badge = document.createElement('span');
    badge.className = `tl-badge ${kind === 'tool' ? 'tool' : ''}`;
    badge.textContent = kind === 'tool' ? 'TOOL' : 'THINK';
    const body = document.createElement('span');
    body.className = kind === 'tool' ? 'tl-body mono' : 'tl-body dim';
    body.textContent = text;
    row.append(timeEl, badge, body);
    const list = $('activity-list');
    list.append(row);
    while (list.children.length > 300) list.firstElementChild.remove();
    list.parentElement.scrollTop = list.parentElement.scrollHeight;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  const app = new TchikoRCApp();
  app.init();
});

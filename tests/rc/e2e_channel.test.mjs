#!/usr/bin/env node
// Full-stack end-to-end test connecting the real JS TchikoChannel (rc/js/channel.js)
// to a live Python RemoteControlService WebSocket server.
//
// Invoked by tests/test_remote_e2e.py with:
//   node tests/rc/e2e_channel.test.mjs <ws_url> <pair_fragment_b64u>

import assert from 'node:assert/strict';
import { TchikoChannel, b64uDecode } from '../../rc/js/channel.js';
import { parsePayload } from '../../rc/js/sigil.js';

const [, , wsUrl, pairFragment] = process.argv;
if (!wsUrl || !pairFragment) {
  console.error('Usage: node e2e_channel.test.mjs <ws_url> <pair_fragment_b64u>');
  process.exit(2);
}

const rawPair = b64uDecode(pairFragment);
assert.equal(rawPair.length, 16, 'pair payload must be 16 bytes');
const parsed = parsePayload(rawPair);
assert.ok(parsed, 'parsePayload must accept valid 16-byte sigil payload');
assert.equal(parsed.version, 1, 'sigil version must be 1');
const { sessionId, secret } = parsed;

function makeQueue() {
  const buf = [];
  const waiters = [];
  return {
    push(item) {
      for (let i = 0; i < waiters.length; i++) {
        if (waiters[i].pred(item)) {
          const w = waiters.splice(i, 1)[0];
          clearTimeout(w.timer);
          w.resolve(item);
          return;
        }
      }
      buf.push(item);
    },
    waitFor(pred, label = 'message', timeoutMs = 10000) {
      for (let i = 0; i < buf.length; i++) {
        if (pred(buf[i])) return Promise.resolve(buf.splice(i, 1)[0]);
      }
      return new Promise((resolve, reject) => {
        const entry = {
          pred,
          resolve,
          timer: setTimeout(() => {
            const idx = waiters.indexOf(entry);
            if (idx >= 0) waiters.splice(idx, 1);
            reject(new Error(`Timed out waiting for ${label}`));
          }, timeoutMs),
        };
        waiters.push(entry);
      });
    },
  };
}

async function run() {
  // ── 1. Pair Client 1 using the Tchiko Sigil payload ───────────────────────
  const q1 = makeQueue();
  let pairedCreds = null;
  let c1Close = null;
  const c1 = new TchikoChannel(wsUrl, {
    onMessage: (m) => q1.push(m),
    onPaired: (p) => { pairedCreds = p; },
    onStatus: (st, detail, code) => {
      if (st === 'disconnected') c1Close = { detail, code };
    },
  });

  const info1 = await c1.connect({ mode: 'pair', sessionId, secret }, 'E2E Client 1');
  assert.match(info1.safetyCode, /^\d{3} \d{3}$/, 'safetyCode must be NNN NNN');

  const pairedMsg = await q1.waitFor((m) => m.type === 'paired', 'paired');
  assert.ok(pairedCreds && pairedCreds.deviceId && pairedCreds.resumeSecret, 'paired credentials received');
  assert.equal(pairedMsg.safety_code, info1.safetyCode);

  const sync1 = await q1.waitFor((m) => m.type === 'state_sync', 'state_sync');
  assert.equal(sync1.safety_code, info1.safetyCode);
  assert.ok(sync1.telemetry && typeof sync1.telemetry.cpu_load_1m === 'number');
  assert.ok(typeof sync1.telemetry.ram_percent === 'number');
  console.log(`SAFETY_CODE=${info1.safetyCode}`);
  console.log('STEP 1 PASS: paired + state_sync + safety code');

  // ── 2. Verify single-use sigil is burned ──────────────────────────────────
  const replayClient = new TchikoChannel(wsUrl);
  let replayErr = null;
  try {
    await replayClient.connect({ mode: 'pair', sessionId, secret }, 'Replay Attacker');
  } catch (err) {
    replayErr = err;
  }
  assert.ok(replayErr, 'reusing a consumed sigil must fail');
  assert.equal(replayErr.code, 'expired', `expected expired error, got ${replayErr.code}`);
  console.log('STEP 2 PASS: consumed sigil rejected');

  // ── 3. Encrypted ping & telemetry ─────────────────────────────────────────
  await c1.send({ type: 'ping', t: 12345 });
  const pong = await q1.waitFor((m) => m.type === 'pong', 'pong');
  assert.equal(pong.t, 12345);

  await c1.send({ type: 'request_telemetry' });
  const tel = await q1.waitFor((m) => m.type === 'telemetry', 'telemetry');
  assert.ok(tel.telemetry && tel.telemetry.hostname);
  console.log('STEP 3 PASS: encrypted ping + telemetry');

  // ── 4. Encrypted prompt execution (direct /run + /sysinfo) ───────────────
  await c1.send({ type: 'prompt', text: '/run echo tchiko-rc-e2e-ok' });
  await q1.waitFor((m) => m.type === 'reply_start', 'reply_start (echo)');
  const doneEcho = await q1.waitFor((m) => m.type === 'reply_complete', 'reply_complete (echo)');
  assert.ok(doneEcho.text.includes('tchiko-rc-e2e-ok'), `unexpected echo reply: ${doneEcho.text}`);

  await c1.send({ type: 'prompt', text: '/sysinfo' });
  await q1.waitFor((m) => m.type === 'reply_start', 'reply_start (/sysinfo)');
  const doneSys = await q1.waitFor((m) => m.type === 'reply_complete', 'reply_complete (/sysinfo)');
  assert.ok(doneSys.text.length > 20, 'expected non-empty /sysinfo output');
  console.log('STEP 4 PASS: encrypted prompt execution');

  // ── 5. Encrypted config update + mood sync ────────────────────────────────
  await c1.send({
    type: 'update_config',
    patch: {
      ghost_widget: { theme: 'emerald_matrix', size: 175 },
      permissions: { tool_execution_policy: 'request-review' },
    },
  });
  const cfgUpd = await q1.waitFor(
    (m) => m.type === 'config_updated' && m.config?.ghost_widget?.theme === 'emerald_matrix',
    'config_updated',
  );
  assert.equal(cfgUpd.config.ghost_widget.size, 175);
  assert.equal(cfgUpd.config.permissions.tool_execution_policy, 'request-review');

  await c1.send({ type: 'trigger_mood', mood: 'excited' });
  const moodMsg = await q1.waitFor((m) => m.type === 'agent_state' && m.mood === 'excited', 'agent_state');
  assert.equal(moodMsg.mood, 'excited');
  console.log('STEP 5 PASS: config update + mood sync');

  // ── 6. Inline command approval over encrypted channel ─────────────────────
  await c1.send({ type: 'prompt', text: '/run echo approval-e2e-pass > /dev/null && echo approval-e2e-pass' });
  const approvalReq = await q1.waitFor((m) => m.type === 'approval_needed', 'approval_needed');
  assert.ok(approvalReq.id && approvalReq.command.includes('approval-e2e-pass'));

  await c1.send({ type: 'approval_response', id: approvalReq.id, decision: 'allow' });
  const resolved = await q1.waitFor(
    (m) => m.type === 'approval_resolved' && m.id === approvalReq.id,
    'approval_resolved',
  );
  assert.equal(resolved.approved, true);
  const doneApproved = await q1.waitFor((m) => m.type === 'reply_complete', 'reply_complete (approved)');
  assert.ok(doneApproved.text.includes('approval-e2e-pass'), `unexpected approved reply: ${doneApproved.text}`);
  console.log('STEP 6 PASS: inline command approval');

  // ── 7. Single-connection enforcement: Client 2 resumes & evicts Client 1 ──
  const q2 = makeQueue();
  const c2 = new TchikoChannel(wsUrl, { onMessage: (m) => q2.push(m) });
  const info2 = await c2.connect(
    { mode: 'resume', deviceId: pairedCreds.deviceId, resumeSecret: pairedCreds.resumeSecret },
    'E2E Client 2',
  );
  assert.match(info2.safetyCode, /^\d{3} \d{3}$/);
  assert.notEqual(info2.safetyCode, info1.safetyCode, 'fresh ephemeral ECDH must produce fresh safety code');

  const sync2 = await q2.waitFor((m) => m.type === 'state_sync', 'state_sync (c2)');
  assert.equal(sync2.safety_code, info2.safetyCode);

  const replaced = await q1.waitFor((m) => m.type === 'replaced', 'replaced (c1)');
  assert.ok(replaced.reason.includes('E2E Client 2'));

  // Wait briefly for close event on c1 to confirm close code 4009
  const deadline = Date.now() + 3000;
  while (!c1Close && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 25));
  }
  assert.ok(c1Close, 'Client 1 must be closed when Client 2 connects');
  assert.equal(c1Close.code, 4009, `expected close code 4009, got ${c1Close.code}`);
  assert.equal(c1.connected, false);
  assert.equal(c2.connected, true);
  console.log('STEP 7 PASS: strictly one active connection enforced (4009 eviction)');

  // ── 8. Unpair revokes credentials ─────────────────────────────────────────
  await c2.send({ type: 'unpair' });
  await q2.waitFor((m) => m.type === 'kicked', 'kicked (unpair)');
  await new Promise((r) => setTimeout(r, 150));

  const c3 = new TchikoChannel(wsUrl);
  let resumeErr = null;
  try {
    await c3.connect(
      { mode: 'resume', deviceId: pairedCreds.deviceId, resumeSecret: pairedCreds.resumeSecret },
      'Revoked Client',
    );
  } catch (err) {
    resumeErr = err;
  }
  assert.ok(resumeErr, 'resuming after unpair must be rejected');
  assert.equal(resumeErr.code, 'unpaired', `expected unpaired error, got ${resumeErr.code}`);
  console.log('STEP 8 PASS: unpair revokes credentials');

  console.log('ALL E2E CHANNEL TESTS PASSED');
}

run().catch((err) => {
  console.error('E2E FAILED:', err);
  process.exit(1);
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = path.join(__dirname, '../src/orch_dashboard/web');
const src = fs.readFileSync(path.join(web, 'pages/settings.js'), 'utf8');
const app = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const panel = src.slice(src.indexOf('function phonePanel('), src.indexOf('async function relayReconnect'));

// owner feedback 14 Nov (fb11/fb24): "Set up relay" opened "This page cannot do that yet" and Pair a phone was greyed
test('no "cannot do that yet" dialog and no dead "Set up relay" button anywhere', () => {
  assert.ok(!/cannot do that yet/.test(src));
  assert.ok(!/relaySetupDialog|relay-setup/.test(src + app));
  assert.ok(!/Set up relay/.test(panel));
});

test('not connected: the next step is written inline; pairing is not offered in the workspace', () => {
  assert.match(panel, /phone-relay-steps/);
  // ORCH-1693: the line is pasted here and Connect runs it; no terminal step
  const paste = src.slice(src.indexOf('function relayPaste('), src.indexOf('async function relayReconnect'));
  assert.doesNotMatch(panel + paste, /terminal/i);
  assert.match(panel, /Paste that line below and press Connect/);
  assert.match(paste, /'data-key':'phone-relay-line'/);
  assert.match(paste, /act\('relay\.connect', \{line\}\)/);
  assert.match(app, /action === 'relay-connect'\) \{ await relayConnect\(\)/);
  assert.ok(!/disabled:true/.test(panel), 'no disabled pair button');
  assert.ok(!/Pair a phone/.test(src + app), 'no pairing entry point in the workspace');
  assert.ok(!/phonePairDialog|'phone-pair'/.test(src + app));
  assert.match(panel, /Phones are paired on your phone link/);
  assert.match(panel, /phone-relay-admin/);
});

test('connected: no setup steps are shown', () => {
  assert.match(panel, /connected \? null : h\('div', \{className:'card-row', 'data-key':'phone-relay-steps'/);
});

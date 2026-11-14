const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = path.join(__dirname, '../src/orch_dashboard/web');
const src = fs.readFileSync(path.join(web, 'pages/settings.js'), 'utf8');
const app = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const panel = src.slice(src.indexOf('function phonePanel('), src.indexOf('function phonePairDialog'));

// owner feedback 14 Nov (fb11/fb24): "Set up relay" opened "This page cannot do that yet" and Pair a phone was greyed
test('no "cannot do that yet" dialog and no dead "Set up relay" button anywhere', () => {
  assert.ok(!/cannot do that yet/.test(src));
  assert.ok(!/relaySetupDialog|relay-setup/.test(src + app));
  assert.ok(!/Set up relay/.test(panel));
});

test('not connected: the next step is written inline and Pair a phone is not a greyed button', () => {
  assert.match(panel, /phone-relay-steps/);
  assert.match(panel, /orch relay connect/);
  assert.ok(!/disabled:true/.test(panel), 'no disabled pair button');
  assert.match(panel, /connected \? btn\('Pair a phone'/);
});

test('connected: no setup steps are shown', () => {
  assert.match(panel, /connected \? null : h\('div', \{className:'card-row', 'data-key':'phone-relay-steps'/);
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const web = path.join(__dirname, '../src/orch_dashboard/web/');
const handoff = fs.readFileSync(web + 'handoff.js', 'utf8');
const fn = handoff.slice(handoff.indexOf('function whenShown'), handoff.indexOf('\n', handoff.indexOf('function whenShown')));

test('a hidden tab does not poll, a shown one does', () => {
  const document = {visibilityState: 'hidden'};
  const c = vm.createContext({document, calls: 0});
  vm.runInContext(fn + '\nthis.tick = whenShown(function () { calls++; });', c);
  c.tick(); c.tick();
  assert.equal(c.calls, 0);
  document.visibilityState = 'visible';
  c.tick();
  assert.equal(c.calls, 1);
});

test('every page poller goes through the visibility guard and a shown tab refreshes once', () => {
  assert.match(handoff, /setInterval\(whenShown\(poll\), 4000\)/);
  assert.match(handoff, /setInterval\(whenShown\(updateStatus\), 4000\)/);
  assert.match(handoff, /addEventListener\("visibilitychange"/);
  const app = fs.readFileSync(web + 'app.js', 'utf8');
  assert.match(app, /setInterval\(whenShown\(refresh\), 3000\)/);
  assert.match(app, /setInterval\(whenShown\(refresh\), up \? 20000 : 3000\)/);
  assert.match(app, /document\.addEventListener\('visibilitychange', whenShown\(refresh\)\)/);
  const settings = fs.readFileSync(web + 'pages/settings.js', 'utf8');
  assert.match(settings, /visibilityState !== 'hidden'\) loadAddon\(id\)/);
});

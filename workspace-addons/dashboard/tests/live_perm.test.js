'use strict';
// ORCH-818: the permission row of a session without a ticket (pages/live-perm.js). The model is plain data.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const P = require(path.join(__dirname, '../src/orch_dashboard/web/pages/live-perm.js'));
const claude = (extra = {}) => ({
  current: 'auto', label: 'Auto', full_warned: false, running: null, running_label: null,
  choices: [{mode: 'ask', label: 'Default', allowed: true}, {mode: 'edits', label: 'Accept edits', allowed: true},
    {mode: 'auto', label: 'Auto', allowed: true}, {mode: 'full', label: 'Bypass permissions', allowed: false}],
  ...extra,
});

test('nothing picked: the kind starts in its remembered mode', () => {
  const r = P.livePermRow({manager: claude()}, 'manager', '');
  assert.equal(r.cur, 'auto');
  assert.equal(r.label, 'Auto');
  assert.deepEqual(r.choices.map(c => c.allowed), [true, true, true, false]);
  assert.equal(r.warn, '');
  assert.deepEqual(P.livePermArgs('manager', ''), {kind: 'manager'});
});

test('a mode the workspace does not allow is never picked', () => {
  const r = P.livePermRow({manager: claude()}, 'manager', 'full');
  assert.equal(r.cur, 'auto');
});

test('bypass permissions warns once, until it was started once', () => {
  const allowed = claude({choices: claude().choices.map(c => ({...c, allowed: true}))});
  const r = P.livePermRow({manager: allowed}, 'manager', 'full');
  assert.equal(r.cur, 'full');
  assert.equal(r.label, 'Bypass permissions');
  assert.equal(r.warn, P.LIVE_PERM_WARN);
  assert.equal(P.livePermRow({manager: {...allowed, full_warned: true}}, 'manager', 'full').warn, '');
  assert.deepEqual(P.livePermArgs('manager', 'full'), {kind: 'manager', permissions: 'full'});
});

test('the pane line says the running mode in words', () => {
  const r = P.livePermRow({chat: claude({running: 'edits', running_label: 'Accept edits'})}, 'chat', '');
  assert.equal(P.livePermPaneText(r), 'Permissions: Accept edits');
  assert.equal(P.livePermPaneText(P.livePermRow({chat: claude()}, 'chat', '')), '');
});

test('the plain terminal, an unknown kind or an older orch: no row', () => {
  assert.equal(P.livePermRow({terminal: claude()}, 'terminal', ''), null);
  assert.equal(P.livePermRow(null, 'manager', ''), null);
  assert.equal(P.livePermRow({manager: {current: 'auto'}}, 'manager', ''), null);
  assert.deepEqual(P.livePermArgs('terminal', 'full'), {kind: 'terminal'});
});

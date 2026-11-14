const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/handoff.js'), 'utf8');

function fn(name) {
  const i = src.indexOf('  function ' + name + '(');
  assert.ok(i >= 0, name);
  const j = src.indexOf('\n  }\n', i) + 4;
  const ctx = vm.createContext({String, Array});
  vm.runInContext(src.slice(i, j) + '\nthis.' + name + ' = ' + name + ';', ctx);
  return ctx[name];
}

// owner feedback 14 Nov: the update request names "orch 16", not only "orch@<sha>"
test('the update request names both versions when orch knows them', () => {
  const words = fn('updateWords');
  assert.equal(words({update_available: true, installed: {label: 'orch 15'}, newest: {label: 'orch 16'}}), 'Update from orch 15 to orch 16?');
  assert.equal(words({update_available: true, newest: {label: 'orch 16'}}), 'Update orch to orch 16?');
});

test('without version facts the sentence stays null (the source sentence is used)', () => {
  const words = fn('updateWords');
  assert.equal(words(null), null);
  assert.equal(words({}), null);
  assert.equal(words({update_available: false, newest: {label: 'orch 16'}}), null);
});

test('what changed comes from orch as plain lines, at most what it sent', () => {
  const ch = fn('updateChanges');
  assert.equal(ch({update_available: true, changes: ['A', 'B']}), 'A\nB');
  assert.equal(ch({update_available: true, changes: []}), '');
  assert.equal(ch(null), '');
});

test('the update banner template uses the version words and keeps the exact source block', () => {
  assert.match(src, /updateWords\(updInfo\)/);
  assert.match(src, /"update": "Exact source:"/);
  assert.match(src, /"What changed:"/);
});

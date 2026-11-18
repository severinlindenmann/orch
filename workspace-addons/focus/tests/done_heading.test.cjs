const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

/* ORCH-608: on a phone the Done heading and its count must stay on one line; the search box gives way instead. */
const css = fs.readFileSync(path.join(__dirname, '../src/orch_focus/web/focus.css'), 'utf8');
const rule = sel => (css.split('\n').find(l => l.startsWith(sel + '{')) || '');

test('Done heading does not shrink or wrap', () => {
  const r = rule('.fx-group-done .row h2');
  assert.match(r, /flex:none/);
  assert.match(r, /white-space:nowrap/);
});

test('search box can shrink beside the heading', () => {
  const r = rule('.fx-group-done input[type=search]');
  assert.match(r, /min-width:0/);
  assert.match(r, /flex:1 1/);
});

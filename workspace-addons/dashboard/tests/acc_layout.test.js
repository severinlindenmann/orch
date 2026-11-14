// Owner feedback 14 Nov fb19: an opened row in a narrow column must keep its value column readable: the row's
// button wraps under the text instead of squeezing it, and a narrow detail panel stacks label over value.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/style.css'), 'utf8');
const rule = sel => (css.split('\n').find(l => l.startsWith(sel + '{')) || '');

test('fb19: the row lets its button wrap and keeps a minimum width for the text', () => {
  assert.match(rule('.acc-li'), /flex-wrap:wrap/);
  assert.match(rule('.acc-li>.grow'), /flex:1 1 \d+px/);
});

test('fb19: a narrow open row stacks the label over the value (container query on the panel)', () => {
  assert.match(rule('.acc-panel'), /container-type:inline-size/);
  assert.match(css, /@container \(max-width:\d+px\)\{\.acc-detail>div\{grid-template-columns:minmax\(0,1fr\)/);
});

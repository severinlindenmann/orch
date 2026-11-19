const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

/* ORCH-691: at phone width a list row must wrap so the title keeps a full line instead of shrinking to three characters. */
const css = fs.readFileSync(path.join(__dirname, '../src/orch_focus/web/focus.css'), 'utf8');
const m = css.match(/@media\(max-width:520px\)\{\.fx-pick a\.fx-pick-row\{([^}]*)\}\.fx-pick a\.fx-pick-row strong\{([^}]*)\}/);

test('phone rows wrap and the title takes the full first line', () => {
  assert.ok(m, 'phone rule for .fx-pick-row exists');
  assert.match(m[1], /flex-wrap:wrap/);
  assert.match(m[2], /flex:1 1 100%/);
});

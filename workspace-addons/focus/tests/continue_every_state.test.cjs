'use strict';
// ORCH-255: the Continue / Pause button is never hidden by a state (open question, not started yet).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_focus/web/focus.js'), 'utf8');
test('Focus shows Continue in every state', () => {
  assert.match(src, /els\.stop\.hidden = false;/);
  assert.doesNotMatch(src, /els\.stop\.hidden = \(asking/);
  assert.match(src, /running \? 'Pause work' : 'Continue'/);
});

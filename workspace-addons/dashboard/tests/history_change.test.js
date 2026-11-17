// ORCH-185 (C8): several note edits in a row each keep their own Activity line with the old and the new text.
const test = require('node:test');
const assert = require('node:assert/strict');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const e = (text, at) => ({by:'human:lume', at, text});
test('a note edit line carries old and new text and still reads "Changed the note"', () => {
  const entry = e('Edited note (was: first | now: second | third)', '2026-11-17T10:00:00Z');
  assert.deepEqual({...helpers.historyChange(entry)}, {field:'note', was:'first', now:'second | third'});
  assert.match(helpers.historyLine(entry, []), /^Changed (the )?note/);
  assert.equal(helpers.historyChange(e('Edited note', '2026-11-17T10:00:00Z')), null);
});
test('two note edits within two minutes are both kept; plain repeats are still folded', () => {
  const list = [e('Edited note (was: (empty) | now: a)', '2026-11-17T10:00:00Z'), e('Edited note (was: a | now: b)', '2026-11-17T10:00:30Z')];
  assert.equal(helpers.dedupeHistory(list, []).length, 2);
  const plain = [e('Edited note', '2026-11-17T10:00:00Z'), e('Edited note', '2026-11-17T10:00:30Z')];
  assert.equal(helpers.dedupeHistory(plain, []).length, 1);
});

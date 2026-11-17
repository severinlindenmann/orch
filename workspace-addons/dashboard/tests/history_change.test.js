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
// ORCH-240: no raw task ids in the Activity; title, owner, due and task renames carry old and new text.
test('task lines name the task, never its id', () => {
  const list = [{id:'c1', text:'Write the intro'}];
  assert.equal(helpers.historyLine(e('Reopened c1', 'x'), list), 'Opened a task again: Write the intro');
  assert.equal(helpers.historyLine(e('Reopened c1 (old evidence: note)', 'x'), list), 'Opened a task again: Write the intro');
  assert.equal(helpers.historyLine(e('Linked c1 to Done when', 'x'), list), 'Linked a task to Done when: Write the intro');
  assert.equal(helpers.historyLine(e("Removed step c2 'Old step' (was open)", 'x'), list), 'Removed a task: Old step');
  assert.equal(helpers.historyLine(e('Renamed c1', 'x'), list), 'Renamed a task: Write the intro');
  for (const t of ['Reopened c1', 'Renamed c1 (was: a | now: b)', 'Linked c1 to Done when', "Removed step c2 'x' (was done; evidence: note)", 'Title changed (was: a | now: b)'])
    assert.doesNotMatch(helpers.historyLine(e(t, 'x'), list), /\bc\d+\b/);
});
test('title, owner, due and task renames show the old and the new text', () => {
  assert.deepEqual({...helpers.historyChange(e('Title changed (was: Old | now: New)', 'x'))}, {field:'title', was:'Old', now:'New'});
  assert.deepEqual({...helpers.historyChange(e('Edited owner (was: (empty) | now: Anna)', 'x'))}, {field:'owner', was:'(empty)', now:'Anna'});
  assert.deepEqual({...helpers.historyChange(e('Edited due (was: 2026-11-20 | now: 2026-11-21)', 'x'))}, {field:'due', was:'2026-11-20', now:'2026-11-21'});
  assert.deepEqual({...helpers.historyChange(e('Renamed c1 (was: a | now: b)', 'x'))}, {field:'task', was:'a', now:'b'});
  assert.equal(helpers.historyLine(e('Title changed (was: Old | now: New)', 'x'), []), 'Changed the title');
  assert.equal(helpers.historyChange(e('Title changed', 'x')), null);
});

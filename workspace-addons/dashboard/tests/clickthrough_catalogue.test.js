// Every dashboard feature brings its click-through (ORCH-308). The feature list is read from the code
// (clickthrough/catalogue.cjs): every op the page can send and every page of the router. A new button that sends a
// new op, or a new page, fails here by name until a file in clickthrough/features/ claims it; the page-smoke job
// then runs that click-through and fails if it never really did the feature.
const test = require('node:test');
const assert = require('node:assert/strict');
const catalogue = require('../clickthrough/catalogue.cjs');

test('the feature list is read from the code, not empty', () => {
  const ops = catalogue.pageOps(), pages = catalogue.pages();
  assert.ok(ops.length >= 60, `only ${ops.length} ops found: the reader in clickthrough/catalogue.cjs no longer matches actions.py`);
  for (const op of ['ticket.new', 'check.set', 'answer', 'addon.set']) assert.ok(ops.includes(op), `${op} missing from the list`);
  for (const p of ['page:home', 'page:tickets', 'page:ticket', 'page:review', 'page:settings/general']) assert.ok(pages.includes(p), `${p} missing`);
});

test('every dashboard feature has a click-through', () => {
  const { missing } = catalogue.coverage();
  assert.deepEqual(missing, [], 'These dashboard features have no click-through. A new feature brings its click-through: add one in ' +
    'workspace-addons/dashboard/clickthrough/features/ (do it, reload, check; see clickthrough/README.md):\n  - ' + missing.join('\n  - '));
});

test('the not-yet list only shrinks: a feature with a click-through comes off it', () => {
  const { done } = catalogue.coverage();
  assert.deepEqual(done, [], 'These features have a click-through now: take them off clickthrough/not-yet.json');
});

test('no click-through claims a feature that is gone', () => {
  const { unknown } = catalogue.coverage();
  assert.deepEqual(unknown, [], 'These claims name no dashboard feature any more (renamed or removed): update covers in the file');
});

test('each click-through names what it does and has a run function', () => {
  for (const c of catalogue.clickthroughs()) {
    assert.equal(typeof c.name, 'string', `${c.file}: name`);
    assert.equal(typeof c.run, 'function', `${c.file}: run`);
    assert.ok(Array.isArray(c.covers) && c.covers.length, `${c.file}: covers lists at least one feature`);
  }
});

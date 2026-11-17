// ORCH-71: Focus shows the ticket page's state and number for the same ticket and helper, and results as plain lines.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const kit = require('./kit_state.cjs');
globalThis.UI = kit;
const H = require('../src/orch_focus/web/helpers.js');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_focus/web', f), 'utf8');
const dash = fs.readFileSync(path.join(__dirname, '../../dashboard/src/orch_dashboard/web/pages/ticket.js'), 'utf8');

const view = (ticket, run = {}, state = 'stopped') => ({state, ticket: {questions: [], checklist: [], ...ticket}, run});
const CASES = [
  ['not started', view({status: 'open'}), 'To do'],
  ['started before, no helper now', view({status: 'open', started: true}), 'To do'],
  ['working', view({status: 'active'}, {running: true, helper: {state: 'working'}}, 'working'), 'Working'],
  ['starting', view({status: 'active'}, {running: true, helper: {state: 'starting'}}, 'working'), 'Starting'],
  ['idle helper', view({status: 'active'}, {running: true, helper: {state: 'idle', detail: 'Nothing running for 8 min'}}, 'waiting'), 'Idle'],
  ['stuck helper', view({status: 'active'}, {running: true, helper: {state: 'stuck'}}, 'waiting'), 'Stuck'],
  ['on hold', view({status: 'active'}, {running: true, helper: {state: 'waiting'}}, 'working'), 'On hold'],
  ['open question', view({status: 'waiting', questions: [{id: 'q1', answer: null}]}, {running: true, helper: {state: 'you'}}, 'needs'), 'Needs you'],
  ['changes waiting', view({status: 'active', bring_back: {state: 'waiting'}}), 'Needs you'],
  ['to check', view({status: 'review'}), 'Check'],
  ['done', view({status: 'done'}, {}, 'done'), 'Done'],
];
for (const [name, v, word] of CASES) {
  test('same word as the ticket page: ' + name, () => {
    assert.equal(H.sessionState(v).pill, word);
    assert.equal(H.headerLine(v).state.word, word);
  });
}

test('the ticket page strip and Focus read the one kit rule (no own copy of the words)', () => {
  assert.match(dash, /window\.UI\.ticketState\(t, run\?\.running \? window\.DashHelpers\.helperState\(run, t\) : null\)/);
  assert.match(web('helpers.js'), /root\.UI && root\.UI\.ticketState/);
  for (const f of ['helpers.js', 'store.js', 'focus.js']) assert.doesNotMatch(web(f), /'Paused'|Ready for review|'Not started'|Helper’s turn/, f);
});

test('the header line: ORCH-n, the pill, Step 3 of 4 · 52 min; never the internal id', () => {
  const checklist = [{id: 'c1', done: true}, {id: 'c2', done: true}, {id: 'c3', state: 'doing'}, {id: 'c4'}];
  const v = view({id: 't_ab12cd', key: 'ORCH-56', status: 'active', checklist}, {running: true, helper: {state: 'working'}, age_seconds: 52 * 60}, 'working');
  const line = H.headerLine(v);
  assert.equal(line.key, 'ORCH-56');
  assert.equal(kit.helperMeta(line.row), 'Step 3 of 4 · 52 min');
  assert.equal(H.headerLine(view({id: 't_ab12cd', key: 't_ab12cd', status: 'open'})).key, '');
  assert.equal(H.headerLine(view({id: 't_ab12cd', status: 'open'})).key, '');
  assert.doesNotMatch(web('focus.js'), /t\.key : TID/);
});

test('a result is one plain line: what, what came out, Open', () => {
  const line = H.resultLine({c: {text: 'Run the test 40 times'}, ev: {type: 'command', ref: 'pytest -q -n 2 tests/x.py', title: 'Test run on macOS', summary: '40 runs, all passed'}});
  assert.deepEqual({...line}, {what: 'Test run on macOS', outcome: '40 runs, all passed'});
  const commit = H.resultLine({c: {text: 'Save the change'}, ev: {type: 'commit', ref: '1d7a100d'}});
  assert.deepEqual({...commit}, {what: 'Save the change', outcome: 'Change saved'});  // never the commit id
  const note = H.resultLine({c: {text: 'Find the cause'}, ev: {type: 'note', text: 'x'.repeat(400)}});
  assert.ok(note.outcome.length <= 160 && note.outcome.endsWith('…'));
  const file = H.resultLine({c: {text: 'Write the report'}, ev: {type: 'file', ref: '.orch/tickets/t_1/evidence/opening-hours.md'}});
  assert.equal(file.outcome, 'Opening hours');
  const src = web('ticket.js'), rows = src.slice(src.indexOf('function resultRows'), src.indexOf('function phoneLine'));
  assert.match(rows, /text: 'Open'/);
  assert.doesNotMatch(src, /proof\.tile|fx-sent-grid|fx-sent-note|fx-result-files/);  // no tiles, no file names in Focus results
  assert.match(src.slice(src.indexOf('function renderProof'), src.indexOf('function resultRows')), /resultRows\(list\)/);
});

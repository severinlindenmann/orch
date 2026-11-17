// ORCH-61: Focus words a running helper with the core's one state, the same as dashboard Home and the ticket page.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
globalThis.UI = require('./kit_state.cjs');  // the kit's one state rule, as the page loads it
const H = require('../src/orch_focus/web/helpers.js');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_focus/web', f), 'utf8');

const view = (state, detail, extra = {}) => ({state: 'waiting', ticket: {questions: [], status: 'active', started: true},
  run: {running: true, helper: {state, detail}}, ...extra});

test('a running helper shows the core word and detail, never Paused', () => {
  assert.deepEqual([H.sessionState(view('stuck', 'Nothing running for 25 min')).pill, H.sessionState(view('stuck', 'Nothing running for 25 min')).detail],
    ['Stuck', 'Nothing running for 25 min']);
  assert.equal(H.sessionState(view('idle', 'Nothing running for 5 min')).pill, 'Idle');
  // an open question reads Needs you, as on the ticket page (ORCH-71)
  assert.equal(H.sessionState(view('you', 'Your answer', {ticket: {questions: [{id: 'q1', answer: null}], status: 'waiting'}})).pill, 'Needs you');
  assert.equal(H.sessionState(view('you', 'Your OK on the screen')).pill, 'Waits for you');
  assert.equal(H.sessionState(view('waiting', 'Waits on pr-green.sh')).pill, 'On hold');
  const working = H.sessionState(view('working', ''));
  assert.equal(working.pill, 'Working'); assert.equal(working.active, true);
});

test('without the core field (older core) the old words stay', () => {
  assert.equal(H.sessionState({state: 'working', ticket: {questions: []}, run: {running: true}}).pill, 'Working');
  assert.equal(H.sessionState({state: 'done', ticket: {questions: []}, run: {running: true, helper: {state: 'idle'}}}).pill, 'Done');
});

test('the header uses the kit pill and line, never "Helper’s turn", and the Helpers list is the kit widget', () => {
  assert.match(web('focus.js'), /window\.UI\.ticketPill\(state\)/);
  assert.doesNotMatch(web('focus.js'), /Helper’s turn|Your turn/);
  assert.match(web('live-now.js'), /window\.UI\.helperList\(cards\.map\(row\)\)/);
  assert.match(web('index.html'), /kit\/widgets\.js/);
  assert.doesNotMatch(web('live-now.js'), /Getting started/);
});

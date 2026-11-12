const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const H = require('../src/orch_focus/web/helpers.js');

const web = name => fs.readFileSync(path.join(__dirname, '../src/orch_focus/web', name), 'utf8');

test('dash21/32: the row shows the next step only when it says more than the action chip', () => {
  assert.equal(H.nextStepText({next_step: 'Answer'}, 'Answer'), '');
  assert.equal(H.nextStepText({}, 'Start'), '');
  assert.equal(H.nextStepText({next_step: 'Which greeting?'}, 'Answer'), 'Which greeting?');
});

test('dash32: a group shows five rows and the rest behind Show all', () => {
  const rows = Array.from({length: 24}, (_, i) => i);
  assert.deepEqual(H.limitGroup(rows), {shown: [0, 1, 2, 3, 4], more: 19});
  assert.equal(H.limitGroup([1, 2]).more, 0);
  const src = web('ticket.js');
  assert.match(src, /Show all \(/);
  assert.match(src, /fx-row-chip/);
  assert.doesNotMatch(src, /row-action/);
});

test('dash30: Results counts tasks, the same unit as the task count', () => {
  const checklist = [{done: true, evidence: [{}, {}, {}]}, {done: false, evidence: [{}]}, {done: true, wont_do: true, evidence: [{}]}];
  assert.equal(H.resultCount(checklist), 1);
  const src = web('ticket.js') + web('used.js');
  assert.match(src, /'What it read'/);
  assert.doesNotMatch(src, /\['used', 'Used'\]/);
  assert.match(src, /showTab\(3, rows\.length > 0\)/);  // empty tabs are hidden
});

test('dash33/07: no "all at once" line; Back to Home and Create a ticket are offered', () => {
  const src = web('ticket.js');
  assert.doesNotMatch(src, /all at once/);
  assert.match(src, /Back to Home/);
  assert.match(src, /Create a ticket/);
  assert.doesNotMatch(src, /'Focus \/ '/);
});

test('dash07/09: one 48px header row like the dashboard; current step in the accent colour', () => {
  const css = web('focus.css');
  assert.doesNotMatch(css, /\.fx-top\{min-height:100px/);
  assert.match(css, /\.fx-top\{flex-wrap:nowrap!important;height:48px/);
  assert.match(css, /\.fx-stepper \[aria-current\]\{color:var\(--brand\)/);
  assert.match(web('ticket.js'), /fx-stepbar'\}, els\.steps, els\.liveWrap/);
});

test('dash24: no vendor name; the composer only has the placeholder', () => {
  const src = web('ticket.js') + web('focus.js');
  assert.match(src, /'Write a message…'/);
  assert.doesNotMatch(src, /messageLabel/);
  assert.match(web('focus.js'), /els\.agent\.textContent = 'Helper'/);
});

test('dash26: Pause work / Continue and a Back to list arrow', () => {
  const src = web('ticket.js') + web('focus.js');
  assert.match(src, /'Pause work'/);
  assert.doesNotMatch(src, /'Stop'|'Exit'|icon: 'x'/);
  assert.match(src, /Back to list/);
});

test('dash27: a fixed menu: greyed when n/a, desktop rows hidden on phones, Start fresh confirmed', () => {
  const t = web('ticket.js'), f = web('focus.js'), css = web('focus.css');
  assert.match(f, /els\.fresh\.disabled = /);
  assert.match(f, /els\.attachBtn\.disabled = /);
  assert.doesNotMatch(f, /els\.(fresh|attachBtn)\.hidden/);
  assert.match(t, /Technical details'\}\), els\.attachBtn/);
  assert.match(t, /fx-menu-divider/);
  assert.match(f, /Click again to start fresh/);
  assert.match(css, /\.fx-action-menu \.fx-desktop\{display:none\}/);
});

test('dash28: no phone switch in Focus', () => {
  const src = web('ticket.js') + web('focus.js');
  assert.doesNotMatch(src, /phoneInput|Send questions to my phone|mobile\.set/);
});

test('dash56: one full-width Add a task field, Enter submits, 44px tall', () => {
  const t = web('ticket.js'), css = web('focus.css');
  assert.doesNotMatch(t + web('focus.js'), /addToggle|'data-act': 'add-task'|fx-adding/);
  assert.match(t, /fx-add-task', id: 'fx-add-task'\}, els\.addInput\)/);
  assert.match(css, /\.fx-add-task \.input\{width:100%;height:44px/);
});

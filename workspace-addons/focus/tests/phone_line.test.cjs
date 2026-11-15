const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function load() {
  const h = (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids: kids.flat().filter(Boolean)});
  const ctx = vm.createContext({window: {}, document: {}, Date});
  const S = {root: {}, ic: () => '', TID: '', P: '', INAPP: false, h, toast() {}, helpPanel() {}, els: {}, act() {}, proof: {}, keyOf: JSON.stringify, stamp: a => a, hhmm: a => a.slice(11, 16), evText: () => '', register: (n, m) => { S.views[n] = m; }, views: {}};
  ctx.window.FocusStore = S;
  const file = path.join(__dirname, '../src/orch_focus/web/ticket.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
  return S.views.ticket.phoneLine;
}
const view = questions => ({ticket: {questions}});

test('an open question sent to the phone says where it also waits', () => {
  const l = load()(view([{id: 'q1', answer: null, sent_at: '2026-11-15T12:31:00Z'}]));
  assert.equal(l.text, 'Sent to your phone 12:31. Answer here or there, whichever is first.');
  assert.equal(l.answered, false);
});

test('a question never sent to a phone shows no line', () => {
  assert.equal(load()(view([{id: 'q1', answer: null}])), null);
});

test('answered on the phone a moment ago shows who, when and what', () => {
  const now = Date.parse('2026-11-15T12:40:00Z');
  const l = load()(view([{id: 'q1', answer: 'Blue', via: 'phone', answered_at: '2026-11-15T12:34:00Z'}]), now);
  assert.equal(l.text, 'Answered on your phone 12:34: Blue');
  assert.equal(l.answered, true);
});

test('an old phone answer, or one given here, shows no line', () => {
  const now = Date.parse('2026-11-15T15:00:00Z');
  assert.equal(load()(view([{id: 'q1', answer: 'Blue', via: 'phone', answered_at: '2026-11-15T12:34:00Z'}]), now), null);
  assert.equal(load()(view([{id: 'q1', answer: 'Blue', via: 'focus', answered_at: '2026-11-15T14:59:00Z'}]), now), null);
});

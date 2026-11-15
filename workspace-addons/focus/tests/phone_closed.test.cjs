const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* live.js renderQuestions with a fake store: a card mounted for an open question, then the question is answered
   on the phone. Returns what the card holds afterwards. */
function setup(typed) {
  const mk = (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids: kids.flat().filter(Boolean), removed: false, hidden: false,
    append(...k) { this.kids.push(...k); }, replaceChildren(...k) { this.kids = k; }, remove() { this.removed = true; }, querySelector(sel) { return sel === 'textarea' ? {value: typed} : null; }});
  const text = n => typeof n === 'string' ? n : !n || typeof n !== 'object' ? '' : [n.attrs.text || n.textContent || '', ...n.kids.map(text)].join(' ');
  const els = {qs: mk('div'), next: mk('section'), msg: {value: '', focus() {}}, agent: {textContent: 'Helper'}, qCount: {}};
  const ctx = vm.createContext({window: {}, document: {}, setTimeout: () => 0});
  const S = {h: mk, TID: 't_x1', toast() {}, els, act() {}, STATUS_WORD: {}, plainNames: s => s, keyOf: JSON.stringify, hhmm: a => String(a).slice(11, 16), evText: () => '', state: {shownQs: new Map(), view: null}, register: (n, m) => { S.views[n] = m; }, views: {}, root: {}};
  ctx.window.FocusStore = S;
  const file = path.join(__dirname, '../src/orch_focus/web/live.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
  const open = {id: 'q1', text: 'Day 1 or 2?', options: ['Day 1', 'Day 2'], answer: null};
  const v = qs => { const x = {ticket: {key: 'PIL-1', questions: qs}, run: {label: 'Helper'}}; S.state.view = x; return x; };
  S.views.live.renderQuestions(v([open]));
  S.views.live.renderQuestions(v([{...open, answer: 'Day 2', via: 'phone', answered_at: '2026-11-15T12:34:00Z'}]));
  const node = els.qs.kids[0];
  return {node, text, els, S};
}

test('answered on the phone with nothing typed: the card closes into one line', () => {
  const {node, text} = setup('');
  assert.equal(node.removed, false);
  assert.equal(text(node).trim(), 'Answered on your phone 12:34: Day 2');
  assert.equal(node.kids[0].attrs.class, 'handoff answered');
});

test('answered on the phone with typed words: the card stays, the line offers Change, Change keeps the words', () => {
  const {node, text, els} = setup('Actually day 3, please');
  assert.equal(node.removed, false);
  const line = node.kids[node.kids.length - 1];
  assert.match(text(line), /Answered on your phone: Day 2/);
  const btn = line.kids.find(k => k.tag === 'button');
  assert.equal(btn.attrs.text, 'Change');
  btn.attrs.onclick();
  assert.equal(els.msg.value, 'Actually day 3, please');
  assert.equal(node.removed, true);
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* ticket.js with a tiny fake store: resultCard(t) returns a fake node; text() flattens it. */
function load() {
  const h = (tag, attrs, ...kids) => ({tag, attrs: attrs || {}, kids: kids.flat().filter(Boolean), replaceChildren(...k) { this.kids = k; }});
  const text = n => !n || typeof n !== 'object' ? '' : [n.attrs.text || '', ...n.kids.map(text)].join(' ');
  const ctx = vm.createContext({window: {}, document: {}, fetch: () => new Promise(() => {}), location: {}});
  const S = {root: {}, ic: () => '', TID: '', P: '', INAPP: false, h, toast() {}, helpPanel() {}, els: {}, act() {}, proof: {}, keyOf: JSON.stringify, stamp: at => 'today 11:20', evText: () => '', register: (n, m) => { S.views[n] = m; }, views: {}};
  ctx.window.FocusStore = S;
  const file = path.join(__dirname, '../src/orch_focus/web/ticket.js');
  vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
  return {card: S.views.ticket.resultCard, text, S};
}
const find = (n, tag) => (n.tag === tag ? [n] : []).concat(...(n.kids || []).map(k => find(k, tag)));

test('a result card shows result name, ticket name, kind, local time and Check result', () => {
  const {card, text} = load();
  const n = card({id: 't_a1b2c3', title: 'Summarise the survey', status: 'review', result: {name: 'Survey summary', kind: 'table', preview: null, at: '2026-11-15T10:20:00Z'}});
  assert.equal(n.attrs.class, 'result-card');
  assert.equal(n.attrs.href, '/t/t_a1b2c3#results');
  const t = text(n);
  for (const w of ['Survey summary', 'Summarise the survey', 'Table', 'today 11:20', 'Check result']) assert.match(t, new RegExp(w));
});

test('a picture preview is an img under the result thumbnail; no preview is a plain kind label', () => {
  const {card} = load();
  const pic = card({id: 't_a1b2c3', title: 'T', result: {name: 'Hero', kind: 'image', preview: '/api/file?t=t_a1b2c3&n=hero.png&m=view', at: null}});
  const img = find(pic, 'img')[0];
  assert.equal(img.src, '/api/file?t=t_a1b2c3&n=hero.png&m=view');
  const plain = card({id: 't_a1b2c3', title: 'T', result: {name: 'Plan', kind: 'pdf', preview: null, at: null}});
  assert.equal(find(plain, 'img').length, 0);
  assert.match(plain.kids[0].attrs.text, /PDF/);
});

test('a review ticket without a result still gets a card with the ticket name', () => {
  const {card, text} = load();
  const t = text(card({id: 't_a1b2c3', title: 'Close books', result: null}));
  assert.match(t, /Close books/); assert.match(t, /Check result/);
});

test('a preview address outside /api/file is never loaded', () => {
  const {card} = load();
  const n = card({id: 't_a1b2c3', title: 'T', result: {name: 'X', kind: 'image', preview: 'https://evil.example/x.png', at: null}});
  assert.equal(find(n, 'img').length, 0);
});

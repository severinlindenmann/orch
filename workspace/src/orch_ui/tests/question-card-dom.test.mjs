import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

// A tiny DOM: enough for question-card.js to build its card and click an option.
class Node_ {
  constructor(tag) { this.tag = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.dataset = {}; this.className = ''; this.textContent = ''; this.hidden = false; }
  append(...c) { this.children.push(...c); }
  replaceChildren(...c) { this.children = c; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  click() { (this.listeners.click || []).forEach(f => f({})); }
  remove() {}
  contains() { return false; }
  focus() {}
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.all && c.all(pred, out)); return out; }
}
const doc = {createElement: tag => new Node_(tag), activeElement: null};

function mountWith(kindOneTap, kind) {
  const w = {};
  globalThis.window = w;
  delete require.cache[require.resolve('../static/question-card-state.js')];
  delete require.cache[require.resolve('../static/question-card.js')];
  w.QuestionCardState = require('../static/question-card-state.js');
  require('../static/question-card.js');
  const host = new Node_('div'); host.ownerDocument = doc;
  const sent = [];
  const storage = {getItem: () => null, setItem() {}, removeItem() {}};
  const question = {ticket: 't_1', id: 'q1', title: 'Allow it?', text: '', options: [{text: 'Yes'}], oneTap: kindOneTap, kind};
  const mounted = w.QuestionCard.mount(host, question, {storage, send: async a => { sent.push(a); return {status: 200}; }});
  const yes = host.all(n => n.tag === 'button' && n.children.some(c => c.textContent === 'Yes'))[0];
  return {mounted, yes, sent};
}

test('a plain question (oneTap) sends the option at once', async () => {
  const {mounted, yes, sent} = mountWith(true);
  yes.click(); await Promise.resolve(); await Promise.resolve();
  assert.deepEqual(sent, ['Yes']);
  assert.notEqual(mounted.state.getState().phase, 'pending');
  mounted.destroy();
});

test('a question with a kind (permission and add-on questions) keeps the Undo wait', async () => {
  for (const flag of [false, undefined]) {
    const {mounted, yes, sent} = mountWith(flag);
    yes.click(); await Promise.resolve();
    assert.deepEqual(sent, []);
    assert.equal(mounted.state.getState().phase, 'pending');
    assert.equal(mounted.state.getState().secondsLeft, 5);
    mounted.destroy();
  }
});

test('a focus:permission question never sends in one tap, even when the caller asks for it', async () => {
  for (const kind of ['focus:permission', 'schedules:run', 'plain']) {
    const {mounted, yes, sent} = mountWith(true, kind);
    yes.click(); await Promise.resolve();
    assert.deepEqual(sent, [], kind);
    assert.equal(mounted.state.getState().phase, 'pending', kind);
    mounted.destroy();
  }
});

// ORCH-2140 W3: on the ticket page the question shows once; the card adds no Needs you line or second title.
// ORCH-2388: its choices are the answer tiles Home shows (one look), Suggested on its tile, a written answer under them.
test('plain: no meta line, the title is for screen readers only, the choices are answer tiles with Suggested on its tile', () => {
  const w = {};
  globalThis.window = w;
  delete require.cache[require.resolve('../static/question-card-state.js')];
  delete require.cache[require.resolve('../static/question-card.js')];
  w.QuestionCardState = require('../static/question-card-state.js');
  require('../static/question-card.js');
  const storage = {getItem: () => null, setItem() {}, removeItem() {}};
  const question = {ticket: 't_1', id: 'q1', title: 'Which day?', text: '', options: [{text: 'Tuesday', suggested: true}, {text: 'Thursday'}]};
  const host = new Node_('div'); host.ownerDocument = doc;
  w.QuestionCard.mount(host, question, {storage, plain: true, send: async () => ({status: 200})});
  assert.equal(host.all(n => n.className === 'row qmeta').length, 0);
  const h3 = host.all(n => n.tag === 'h3')[0];
  assert.equal(h3.className, 'sr-only');
  assert.equal(h3.textContent, 'Your answer');
  assert.equal(host.all(n => n.tag === 'p' && n.className === 'muted').length, 0);
  const options = host.all(n => n.tag === 'button' && /answer-option/.test(n.className));
  assert.deepEqual(options.map(n => n.className), ['answer-option suggested', 'answer-option']);
  const words = n => (n.textContent || '') + (n.children || []).map(words).join('');
  assert.deepEqual(options.map(words), ['TuesdaySuggested', 'Thursday']);
  assert.equal(host.all(n => n.tag === 'button' && /qoption/.test(n.className)).length, 0, 'no second look');
  assert.equal(host.all(n => n.className === 'suggested-label').length, 0);
  const own = host.all(n => n.tag === 'button' && /answer-own/.test(n.className));
  assert.deepEqual(own.map(n => [n.textContent, n.className]), [['Write your own…', 'btn ghost sm answer-own']]);
  assert.equal(host.all(n => n.className === 'answer-options')[0].children.includes(own[0]), false, 'under the tiles, not one of them');
  const other = new Node_('div'); other.ownerDocument = doc;
  w.QuestionCard.mount(other, question, {storage, send: async () => ({status: 200})});
  assert.equal(other.all(n => n.className === 'row qmeta').length, 1);
  assert.equal(other.all(n => n.tag === 'h3')[0].textContent, 'Which day?');
  assert.deepEqual(other.all(n => n.tag === 'button' && /qoption/.test(n.className)).map(n => n.className), ['btn qoption suggested', 'btn qoption']);
});

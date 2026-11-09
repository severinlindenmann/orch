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

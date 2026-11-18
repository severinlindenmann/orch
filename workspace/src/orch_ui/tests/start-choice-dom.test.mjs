// ORCH-485: UI.startButton (static/start-choice.js) on a tiny DOM: one click starts the usual way, the caret opens the
// Start choice, the button says Starting… until the helper runs, a double click sends one start, greyed choices say why.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

class N {
  constructor(tag) { Object.assign(this, {tag, children: [], parent: null, attrs: {}, dataset: {}, className: '', own: '', hidden: false, disabled: false, open: false, id: '', title: '', listeners: {}}); }
  set textContent(v) { this.own = String(v); this.children = []; }
  get textContent() { return this.own + this.children.map(c => c.textContent).join(''); }
  get firstChild() { return this.children[0] || null; }
  get isConnected() { let n = this; while (n.parent) n = n.parent; return n.tag === '#root'; }
  adopt(c) { if (!(c instanceof N)) c = Object.assign(new N('#text'), {own: String(c)}); c.parent?.children.splice(c.parent.children.indexOf(c), 1); c.parent = this; return c; }
  append(...c) { c.forEach(x => this.children.push(this.adopt(x))); }
  replaceChildren(...c) { this.children.forEach(x => { x.parent = null; }); this.children = []; this.own = ''; this.append(...c); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; if (k === 'disabled') this.disabled = false; }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  dispatch(t) { const e = {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }}; (this.listeners[t] || []).forEach(f => f(e)); return e; }
  click() { if (this.disabled) return; const e = this.dispatch('click'); if (this.tag === 'summary' && !e.defaultPrevented && this.parent?.tag === 'details') { this.parent.open = !this.parent.open; this.parent.dispatch('toggle'); } }
  contains(n) { for (; n; n = n.parent) if (n === this) return true; return false; }
  focus() { doc.activeElement = this; }
  querySelector() { return null; }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.all(pred, out)); return out; }
  find(pred) { return this.all(pred)[0] || null; }
}
const doc = {activeElement: null, createElement: tag => new N(tag), createTextNode: t => Object.assign(new N('#text'), {own: String(t)})};
Object.defineProperty(N.prototype, 'disabledAttr', {get() { return this.disabled; }});
// setAttribute('disabled', '') in the widget goes through attr(); mirror it on the property like a browser does
const setA = N.prototype.setAttribute;
N.prototype.setAttribute = function (k, v) { setA.call(this, k, v); if (k === 'disabled') this.disabled = true; };

// Pick a value in one of the Start choice's small selects, as select.js does: set the value, send change.
function pick(m, what, v) { const s = m.q(n => n.dataset.startPick === what); s.value = v; s.dispatch('change'); }
const tick = () => new Promise(r => setImmediate(r));
function mount(o = {}) {
  globalThis.document = doc;
  globalThis.window = {};
  for (const f of ['../static/start-choice-state.js', '../static/start-choice.js']) delete require.cache[require.resolve(f)];
  window.StartChoiceState = require('../static/start-choice-state.js');
  require('../static/start-choice.js');
  const root = new N('#root'), host = new N('div');
  root.append(host);
  const sent = [], toasts = [];
  let reply = {ok: true};
  const send = async (op, args) => { sent.push([op, args]); return typeof reply === 'function' ? reply(op, args) : reply; };
  const btn = window.UI.startButton(host, Object.assign({ticket: 't_1', name: 'ORCH-12', send, toast: (t, k) => toasts.push([t, k]),
    agents: [{name: 'claude', label: 'Claude Code', models: true, chosen: true}, {name: 'codex', label: 'Codex', models: false}],
    sessions: {sessions: []}, runs: {}, settings: {live_max: 6}, line: {waiting: []}}, o));
  const q = pred => host.find(pred);
  const main = () => q(n => n.dataset.start === 'main');
  return {host, btn, sent, toasts, q, main, setReply: r => { reply = r; }, ui: window.UI};
}

test('with no earlier session the main button says Start helper and one click starts on the usual tool', async () => {
  const m = mount();
  assert.equal(m.main().textContent, 'Start helper');
  m.main().click();
  await tick();
  assert.deepEqual(m.sent, [['run.start', {ticket: 't_1'}]]);
  assert.match(m.toasts[0][0], /starts on ORCH-12/);
});

test('with an earlier session here the main button says Continue', () => {
  const m = mount({sessions: {sessions: [{id: 's1', title: 'Draft', reopenable: true, turns: 4, last_used: '2026-11-17T10:00:00Z'}]}});
  assert.equal(m.main().textContent, 'Continue');
});

test('Starting… until the helper runs; a double click and a second button for the same ticket send one start', async () => {
  const m = mount();
  const other = new N('div');
  m.host.parent.append(other);
  const second = m.ui.startButton(other, {ticket: 't_1', name: 'ORCH-12', send: async (op, args) => { m.sent.push([op, args]); return {ok: true}; }, sessions: {sessions: []}, agents: []});
  m.main().click();
  m.main().click(); // the button is already disabled: the second click does nothing
  other.find(n => n.dataset.start === 'main').click();
  await tick();
  assert.equal(m.sent.length, 1);
  const b = m.main();
  assert.equal(b.disabled, true);
  assert.equal(b.getAttribute('aria-busy'), 'true');
  assert.match(b.textContent, /Starting…/);
  assert.equal(m.q(n => n.tag === 'summary').getAttribute('aria-disabled'), 'true', 'the caret is greyed too');
  assert.ok(m.q(n => n.getAttribute('role') === 'status' && /Starting the helper on ORCH-12/.test(n.textContent)));
  assert.match(other.find(n => n.dataset.start === 'main').textContent, /Starting…/, 'the other button shows the same state');
  m.btn.update({running: true});
  assert.equal(m.main().disabled, true, 'a helper works now: the main button is greyed');
  assert.doesNotMatch(m.main().textContent, /Starting/);
  second.update({running: true});
});

test('a busy refusal to a second start is quiet; a real refusal shows its words and ends Starting', async () => {
  const m = mount();
  m.setReply({ok: false, text: 'An agent is already working on this ticket (started by lume at 11:02).'});
  m.main().click();
  await tick();
  assert.deepEqual(m.toasts, []);
  m.setReply({ok: false, text: 'That is not a tool name.'});
  m.main().click();
  await tick();
  assert.deepEqual(m.toasts, [['That is not a tool name.', 'error']]);
  assert.equal(m.main().disabled, false);
});

test('the caret opens the Start choice: fresh start with tool and model, sends the picked tool and model', async () => {
  const m = mount({model: {name: 'opus', by: 'orch'}, runs: {t_9: {running: true}}});
  m.q(n => n.tag === 'summary').click();
  assert.ok(m.q(n => n.className === 'live-start-h' && n.textContent === 'Start a helper'));
  assert.ok(m.q(n => n.textContent === '1 of 6 places in use' && n.className.includes('live-places')));
  assert.equal(m.q(n => n.dataset.start === 'continue'), null, 'no Continue without an earlier session');
  pick(m, 'model', 'sonnet');
  m.q(n => n.dataset.start === 'fresh').click();
  await tick();
  assert.deepEqual(m.sent, [['ticket.model', {ticket: 't_1', model: 'sonnet'}], ['run.start', {ticket: 't_1', fresh: true}]]);
});

test('a tool without models says so instead of the model picker', () => {
  const m = mount();
  m.q(n => n.tag === 'summary').click();
  pick(m, 'tool', 'codex');
  assert.equal(m.q(n => n.dataset.startPick === 'model'), null);
  assert.ok(m.q(n => n.textContent === 'This tool uses its own model.'));
});

test('earlier sessions: the newest shows, the rest fold out behind Show more', () => {
  const s = i => ({id: 's' + i, title: 'T' + i, reopenable: true, turns: 2, last_used: '2026-11-1' + (8 - i) + 'T10:00:00Z'});
  const m = mount({sessions: {sessions: [s(1), s(2), s(3)]}});
  m.btn.open();
  const rows = m.host.all(n => n.className === 'live-hist-row');
  assert.deepEqual(rows.map(r => r.hidden), [false, true, true]);
  const tog = m.q(n => 'startMore' in n.dataset);
  assert.equal(tog.textContent, 'Show 2 more');
  tog.click();
  assert.deepEqual(rows.map(r => r.hidden), [false, false, false]);
  assert.equal(tog.textContent, 'Show less');
  assert.equal(tog.getAttribute('aria-expanded'), 'true');
});

test('no earlier sessions: no Earlier sessions part', () => {
  const m = mount();
  m.btn.open();
  assert.equal(m.q(n => n.dataset.key === 'start-earlier'), null);
});

test('a greyed Reopen says why, tied to the button', () => {
  const m = mount({sessions: {sessions: [
    {id: 's1', title: 'Draft', reopenable: true, turns: 4, last_used: '2026-11-17T10:00:00Z'},
    {id: 's2', title: 'Photos', reopenable: false, label: 'Codex', last_used: '2026-11-16T09:00:00Z'}]}});
  m.q(n => n.tag === 'summary').click();
  const off = m.q(n => n.dataset.start === 'reopen' && n.dataset.id === 's2');
  assert.equal(off.disabled, true);
  const why = m.q(n => n.id === off.getAttribute('aria-describedby'));
  assert.equal(why.textContent, 'On another computer, so it cannot be reopened here.');
  assert.equal(m.q(n => n.dataset.start === 'reopen' && n.dataset.id === 's1').disabled, false);
  assert.ok(m.q(n => n.dataset.start === 'continue'), 'Continue is offered');
});

test('no helper tool on this computer: the main button and Fresh start are greyed and say why', () => {
  const m = mount({agents: []});
  assert.equal(m.main().disabled, true);
  const line = m.q(n => n.id === m.main().getAttribute('aria-describedby'));
  assert.equal(line.textContent, 'No helper tool is set up on this computer.');
  assert.equal(line.hidden, false);
  m.btn.open();
  const fresh = m.q(n => n.dataset.start === 'fresh');
  assert.equal(fresh.disabled, true);
  assert.equal(m.q(n => n.id === fresh.getAttribute('aria-describedby')).textContent, 'No helper tool is set up on this computer.');
});

test('Send and start: the page sends its message first, and nothing starts when it stops', async () => {
  let stop = false;
  const m = mount({label: 'Send and start helper', before: async () => stop ? null : [['run.send', {ticket: 't_1', text: 'hi'}]]});
  assert.equal(m.main().textContent, 'Send and start helper');
  stop = true;
  m.main().click();
  await tick();
  assert.deepEqual(m.sent, []);
  stop = false;
  m.main().click();
  await tick();
  assert.deepEqual(m.sent.map(s => s[0]), ['run.send', 'run.start']);
});

test('fresh: the main button is a fresh start on the usual tool and model, with the page word', async () => {
  const m = mount({fresh: true, label: 'Start fresh', sessions: {sessions: [{id: 's1', title: 'D', reopenable: true, last_used: '2026-11-17T10:00:00Z'}]}});
  assert.equal(m.main().textContent, 'Start fresh');
  m.main().click();
  await tick();
  assert.deepEqual(m.sent, [['run.start', {ticket: 't_1', fresh: true}]]);
});

test('caretOnly: only the caret; before gets the start the person picked', async () => {
  let got = null;
  const m = mount({caretOnly: true, before: async ops => { got = ops; return [['run.send', {ticket: 't_1', text: 'hi'}]]; }});
  assert.equal(m.main(), null);
  m.btn.open();
  m.q(n => n.dataset.start === 'fresh').click();
  await tick();
  assert.deepEqual(got, [['run.start', {ticket: 't_1', fresh: true}]]);
  assert.deepEqual(m.sent.map(s => s[0]), ['run.send', 'run.start']);
  assert.equal(m.btn.starting(), true);
});

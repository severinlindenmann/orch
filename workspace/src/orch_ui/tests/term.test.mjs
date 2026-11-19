import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

// A tiny DOM and a fake xterm: enough for term.js to build its element, take the bridge's events and hand typed data
// out. The real xterm is clicked in the browser (click-through step 22). innerHTML is recorded so a test can prove
// that nothing goes in as markup.
const markup = [];
class Node_ {
  constructor(tag) {
    this.tag = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.dataset = {}; this.className = '';
    this.hidden = false; this._text = ''; this.parentNode = null;
  }
  set innerHTML(v) { markup.push(v); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  append(...c) { for (const x of c) { x.parentNode = this; this.children.push(x); } }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  fire(t, e = {}) {
    const ev = Object.assign({preventDefault() { ev.defaultPrevented = true; }, stopPropagation() {}, target: this}, e);
    (this.listeners[t] || []).forEach(f => f(ev));
    return ev;
  }
  click() { this.fire('click'); }
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  focus() { globalThis.document.activeElement = this; for (let x = this; x; x = x.parentNode) x.fire('focusin', {target: this}); }
  getContext() { return globalThis.noGL ? null : {}; }
  find(pred) { if (pred(this)) return this; for (const c of this.children) { const r = c.find(pred); if (r) return r; } return null; }
}
const terms = [];
class FakeTerminal {
  constructor(options) { this.options = {...options}; this.written = []; this.sizes = []; this.pasted = []; this.sel = ''; terms.push(this); }
  loadAddon(a) { a.term = this; }
  open(host) { this.host = host; this.textarea = new Node_('textarea'); host.append(this.textarea); }
  onData(f) { this.data = f; }
  attachCustomKeyEventHandler(f) { this.keys = f; }
  reset() { this.written = []; }
  resize(c, r) { this.sizes.push([c, r]); }
  write(b) { this.written.push(Buffer.from(b).toString('utf8')); }
  focus() { this.textarea.focus(); }
  paste(t) { this.pasted.push(t); if (!this.options.disableStdin) this.data(t); }
  hasSelection() { return !!this.sel; }
  getSelection() { return this.sel; }
  dispose() { this.disposed = true; }
  type(d) { if (!this.options.disableStdin) this.data(d); }  // what xterm does with a key: nothing while stdin is off
  get buffer() { const w = this.written.join('').split('\n'); return {active: {length: w.length, getLine: i => ({translateToString: () => w[i]})}}; }
}
globalThis.window = globalThis;
globalThis.document = {createElement: t => new Node_(t), activeElement: null};
globalThis.Terminal = FakeTerminal;
globalThis.WebglAddon = {WebglAddon: class { onContextLoss(f) { this.lost = f; } }};
globalThis.FitAddon = {FitAddon: class { proposeDimensions() { return globalThis.fitSize || {cols: 120, rows: 30}; } }};
const copied = [];
Object.defineProperty(globalThis, 'navigator', {value: {clipboard: {writeText: async t => { copied.push(t); }}}, configurable: true});
require('../static/term.js');
const T = window.UI.term;
const byKey = (root, k) => root.find(n => n.attrs['data-key'] === k);
const byClass = (root, c) => root.find(n => String(n.className).split(' ').includes(c));
const wait = ms => new Promise(r => setTimeout(r, ms));
const b64 = s => Buffer.from(s, 'utf8').toString('base64');
const SCREEN = {cols: 80, rows: 24, data: b64('\x1b[31mhello\x1b[0m\r\n$ ')};
function live(opts = {}, allowed = true) {
  const sent = [], sizes = [];
  const ui = T({label: 'ORCH-1', onInput: async d => { sent.push(d); return opts.answer ? opts.answer(d) : {ok: true}; }, onSize: z => sizes.push(z)});
  ui.hello({typing_allowed: allowed});
  ui.screen(SCREEN);
  return {ui, sent, sizes, xt: terms[terms.length - 1]};
}

test('pure parts: paste question, base64 to bytes, sizes the bridge takes', () => {
  assert.equal(T.pasteAsk('one line'), '');
  assert.match(T.pasteAsk('rm -rf x\n'), /1 line and press Enter/);
  assert.match(T.pasteAsk('a\r\nb\nc'), /3 lines/);
  assert.equal(Buffer.from(T.bytes(b64('grün ✓'))).toString('utf8'), 'grün ✓');
  assert.equal(T.bytes('%%%').length, 0);
  assert.deepEqual(T.clamp({cols: 1000, rows: 1}), {cols: 500, rows: 3});
  assert.equal(T.clamp({cols: 0, rows: 5}), null);
});

test('the screen from the bridge is written to the terminal at the helper\'s size, more bytes follow', () => {
  const {ui, xt} = live();
  assert.equal(ui.el.dataset.state, 'live');
  assert.deepEqual(xt.sizes, [[80, 24]]);
  assert.match(xt.written.join(''), /hello/);
  ui.write(b64(' more'));
  assert.match(xt.written.join(''), /\$  more$/);
  ui.size({cols: 100, rows: 30});
  assert.deepEqual(xt.sizes.at(-1), [100, 30]);
  assert.equal(xt.options.disableStdin, true, 'a terminal starts with no input');
  assert.equal(markup.length, 0);
});

test('watching only by default: keys and pastes send nothing until Let me type is on', async () => {
  const {ui, sent, xt} = live();
  assert.equal(ui.el.dataset.typing, 'off');
  assert.match(byClass(ui.el, 'term-say').textContent, /Watching/);
  xt.type('x');
  const p = ui.el.fire('paste', {target: xt.textarea, clipboardData: {getData: () => 'ls'}});
  await wait(40);
  assert.deepEqual(sent, []);
  assert.ok(p.defaultPrevented, 'a paste while watching is stopped');
  byKey(ui.el, 'term-type').click();
  assert.equal(ui.typing(), true);
  assert.equal(xt.options.disableStdin, false);
  assert.equal(byKey(ui.el, 'term-type').getAttribute('aria-checked'), 'true');
  xt.type('l'); xt.type('s'); xt.type('\r');
  await wait(40);
  assert.deepEqual(sent, ['ls\r'], 'typed data goes out in one request');
  const stop = {type: 'keydown', key: 'Tab', shiftKey: true, preventDefault() {}};
  assert.equal(xt.keys(stop), false);
  assert.equal(ui.typing(), false, 'Shift+Tab stops typing');
  assert.equal(xt.options.disableStdin, true);
});

test('Ctrl+C or Cmd+C with a selection copies it and is not sent; without a selection Ctrl+C goes to the helper', () => {
  const {ui, xt} = live();
  ui.setTyping(true);
  xt.sel = 'hello';
  assert.equal(xt.keys({type: 'keydown', key: 'c', ctrlKey: true, preventDefault() {}}), false);
  assert.equal(xt.keys({type: 'keydown', key: 'c', metaKey: true, preventDefault() {}}), false);
  assert.deepEqual(copied.slice(-2), ['hello', 'hello']);
  xt.sel = '';
  assert.equal(xt.keys({type: 'keydown', key: 'c', ctrlKey: true, preventDefault() {}}), true);
  assert.equal(xt.keys({type: 'keydown', key: 'v', metaKey: true, preventDefault() {}}), false, 'Cmd keys stay with the browser');
});

test('Copy copies the selection, or the whole screen', async () => {
  const {ui, xt} = live();
  xt.sel = '';
  byKey(ui.el, 'term-copy').click();
  await wait(5);
  assert.match(copied.at(-1), /hello/);
  xt.sel = 'ell';
  byKey(ui.el, 'term-copy').click();
  await wait(5);
  assert.equal(copied.at(-1), 'ell');
});

test('typing stays off when the workspace setting is off, and a refused request turns it off', async () => {
  const off = live({}, false);
  assert.equal(byClass(off.ui.el, 'term-sw').hidden, true);
  off.ui.setTyping(true);
  assert.equal(off.ui.typing(), false);
  assert.match(byClass(off.ui.el, 'term-say').textContent, /typing is off/);
  const {ui, xt} = live({answer: () => ({ok: false, status: 403, text: 'Sign in to type here.'})});
  ui.setTyping(true);
  xt.type('a');
  await wait(40);
  assert.equal(ui.typing(), false);
  assert.equal(byClass(ui.el, 'term-sw').hidden, true, 'no switch once the server said no');
});

test('a paste with a line end asks once; Cancel sends nothing, Paste hands it to the terminal', async () => {
  const {ui, sent, xt} = live();
  ui.setTyping(true);
  const ask = byClass(ui.el, 'term-ask');
  const p = ui.el.fire('paste', {target: xt.textarea, clipboardData: {getData: () => 'echo hi\nrm x\n'}});
  assert.ok(p.defaultPrevented);
  assert.equal(ask.hidden, false);
  assert.match(ask.textContent, /2 lines/);
  byKey(ui.el, 'term-paste-no').click();
  await wait(40);
  assert.deepEqual(sent, []);
  ui.el.fire('paste', {target: xt.textarea, clipboardData: {getData: () => 'echo hi\n'}});
  byKey(ui.el, 'term-paste-go').click();
  await wait(40);
  assert.deepEqual(xt.pasted, ['echo hi\n']);
  assert.deepEqual(sent, ['echo hi\n']);
  ui.el.fire('paste', {target: xt.textarea, clipboardData: {getData: () => 'plain'}});
  assert.equal(xt.pasted.at(-1), 'plain', 'one line without a line end goes in without asking');
});

test('nothing typed before typing was turned off goes out later', async () => {
  let release;
  const {ui, sent, xt} = live({answer: () => (sent.length === 1 ? new Promise(r => { release = () => r({ok: true}); }) : {ok: true})});
  ui.setTyping(true);
  xt.type('a');
  ui.setTyping(false);
  await wait(40);
  assert.deepEqual(sent, [], 'data still waiting is dropped');
  ui.setTyping(true);
  xt.type('b');
  await wait(40);
  assert.deepEqual(sent, ['b']);
  xt.type('rm -rf x\r');  // waits behind the first request
  ui.setTyping(false); ui.setTyping(true);
  release();
  await wait(40);
  assert.deepEqual(sent, ['b'], 'nothing from before the off and on went out');
});

test('the size: sent while typing when the box differs, never while watching or after typing stopped', async () => {
  const {ui, sizes} = live();
  ui.setTyping(true); ui.setTyping(false);
  await wait(20);
  assert.deepEqual(sizes, [], 'nothing went out while watching');
  ui.setTyping(true);
  await wait(20);
  assert.deepEqual(sizes, [{cols: 120, rows: 30}]);
  globalThis.fitSize = {cols: 80, rows: 24};
  ui.setTyping(false); ui.setTyping(true);
  await wait(20);
  assert.equal(sizes.length, 1, 'the same size as the helper\'s is not sent');
  delete globalThis.fitSize;
});

test('the screen closing ends typing and says so; no screen says why; no WebGL says so', () => {
  const {ui} = live();
  ui.setTyping(true);
  ui.end('none');
  assert.equal(ui.typing(), false);
  assert.equal(ui.el.dataset.state, 'ended');
  const p = ui.el.find(n => n.tag === 'p' && String(n.className).includes('term-state'));
  assert.match(p.textContent, /closed/);
  const none = T({label: 'ORCH-2'});
  none.end('oneshot');
  assert.equal(none.el.dataset.state, 'oneshot');
  globalThis.noGL = true;
  const gl = T({label: 'ORCH-3'});
  gl.hello({typing_allowed: true}); gl.screen(SCREEN);
  assert.equal(gl.el.dataset.state, 'nogl');
  delete globalThis.noGL;
});

test('a redraw gives the keyboard back to the paste question, never away from another field', () => {
  const {ui, xt} = live();
  ui.setTyping(true);
  ui.el.fire('paste', {target: xt.textarea, clipboardData: {getData: () => 'a\nb'}});
  const go = byKey(ui.el, 'term-paste-go');
  assert.equal(document.activeElement, go);
  document.activeElement = null;  // the pane was drawn again
  ui.back();
  assert.equal(document.activeElement, go);
  const other = new Node_('textarea');
  document.activeElement = other;
  ui.back();
  assert.equal(document.activeElement, other);
});

test('links from a program open only http and https, without the page behind them', () => {
  const {xt} = live();
  const opened = [];
  globalThis.open = (...a) => opened.push(a);
  xt.options.linkHandler.activate({}, 'javascript:alert(1)');
  xt.options.linkHandler.activate({}, 'file:///etc/passwd');
  xt.options.linkHandler.activate({}, 'https://example.com/a');
  assert.deepEqual(opened, [['https://example.com/a', '_blank', 'noopener,noreferrer']]);
  assert.equal(xt.options.linkHandler.allowNonHttpProtocols, false);
});

test('reconnecting: typing stops, the last screen stays, typing needs a new hello and the person again', () => {
  const {ui, xt} = live();
  ui.setTyping(true);
  ui.show('loading');
  assert.equal(ui.typing(), false);
  assert.equal(xt.options.disableStdin, true);
  assert.equal(ui.el.find(n => String(n.className) === 'term-screen').hidden, false, 'the last screen stays in view');
  assert.match(byClass(ui.el, 'term-say').textContent, /Connecting/);
  ui.setTyping(true);
  assert.equal(ui.typing(), false, 'no typing before the new stream is there');
  ui.hello({typing_allowed: true}); ui.screen(SCREEN);
  assert.equal(ui.typing(), false, 'the switch stays off until the person turns it on');
  ui.setTyping(true);
  assert.equal(ui.typing(), true);
});

test('a long paste is cut between letters, never inside one; sizes are numbers only', async () => {
  const {ui, sent, xt} = live();
  ui.setTyping(true);
  xt.type('a'.repeat(59999) + '😀' + 'b');
  await wait(60);
  assert.equal(sent.length, 2);
  assert.equal(sent[0].length, 59999);
  assert.ok(sent[1].startsWith('😀'));
  assert.equal(T.clamp({cols: Infinity, rows: 5}), null);
  assert.equal(T.clamp({cols: '80', rows: 24}), null);
  assert.equal(T.clamp({cols: true, rows: 24}), null);
});

test('a size that did not go out is tried again', async () => {
  const sizes = [];
  const ui = T({label: 'ORCH-9', onInput: async () => ({ok: true}), onSize: z => { sizes.push(z); return Promise.resolve({ok: sizes.length > 1}); }});
  ui.hello({typing_allowed: true}); ui.screen(SCREEN);
  ui.setTyping(true);
  await wait(20);
  ui.setTyping(false); ui.setTyping(true);
  await wait(20);
  assert.equal(sizes.length, 2, 'the failed size was sent again');
});

test('a paste never carries control characters: no early end of the bracketed paste, no Ctrl+C inside', () => {
  assert.equal(T.cleanPaste('ok\x1b[201~rm -rf x\x03\tend\r\n'), 'ok[201~rm -rf x\tend\r\n');
  const {ui, xt} = live();
  ui.setTyping(true);
  const p = ui.el.fire('paste', {target: xt.textarea, clipboardData: {getData: () => 'a\x1b[201~b'}});
  assert.ok(p.defaultPrevented, 'the browser\'s own paste never reaches xterm');
  assert.equal(xt.pasted.at(-1), 'a[201~b');
});

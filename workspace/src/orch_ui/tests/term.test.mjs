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
  loadAddon(a) { a.term = this; (this.addons ||= []).push(a); }
  open(host) { this.host = host; this.textarea = new Node_('textarea'); host.append(this.textarea); }
  onData(f) { this.data = f; }
  attachCustomKeyEventHandler(f) { this.keys = f; }
  reset() { this.written = []; }
  resize(c, r) { this.sizes.push([c, r]); }
  write(b) { this.written.push(Buffer.from(b).toString('utf8')); }
  focus() { this.textarea.focus(); }
  paste(t) { this.pasted.push(t); if (!this.options.disableStdin) this.data(t); }
  onSelectionChange(f) { this.selChanged = f; }
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
// fitSize: a size, or a function of the terminal (a box of a set width: fewer columns at a larger font)
globalThis.FitAddon = {FitAddon: class { proposeDimensions() { const z = globalThis.fitSize; return (typeof z === 'function' ? z(this.term) : z) || {cols: 120, rows: 30}; } }};
const copied = [];
Object.defineProperty(globalThis, 'navigator', {value: {clipboard: {writeText: async t => { copied.push(t); }}}, configurable: true});
require('../static/term.js');
const T = window.UI.term;
const byKey = (root, k) => root.find(n => n.attrs['data-key'] === k);
const byClass = (root, c) => root.find(n => String(n.className).split(' ').includes(c));
const wait = ms => new Promise(r => setTimeout(r, ms));
const ESC_GAP = 560;  // a little more than term.js waits for a second Esc
const b64 = s => Buffer.from(s, 'utf8').toString('base64');
const SCREEN = {cols: 80, rows: 24, data: b64('\x1b[31mhello\x1b[0m\r\n$ ')};
function live(opts = {}, allowed = true) {
  const sent = [], sizes = [];
  const ui = T({label: 'ORCH-1', onInput: async d => { sent.push(d); return opts.answer ? opts.answer(d) : {ok: true}; }, onSize: z => sizes.push(z)});
  ui.hello({typing_allowed: allowed});
  ui.screen(SCREEN);
  return {ui, sent, sizes, xt: terms[terms.length - 1]};
}

test('pure parts: what a paste hands over, base64 to bytes, sizes the bridge takes', () => {
  assert.equal(T.pasteText('one line'), 'one line');
  assert.equal(T.pasteText('rm -rf x\n'), 'rm -rf x', 'no Enter at the end (ORCH-2199)');
  assert.equal(T.pasteText('a\r\nb\nc\r\n\n'), 'a\nb\nc', 'line ends inside stay, those at the end go');
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

test('ORCH-2199: no switch; a click into the screen types there, a drag only selects, Esc twice stops', async () => {
  const {ui, sent, xt} = live();
  assert.equal(ui.el.dataset.typing, 'off');
  assert.equal(byClass(ui.el, 'term-sw'), null, 'no Let me type switch');
  assert.equal(byClass(ui.el, 'term-say').hidden, true, 'no explaining line while watching');
  xt.type('x');
  await wait(40);
  assert.deepEqual(sent, [], 'keys before a click send nothing');
  const screen = byClass(ui.el, 'term-screen');
  screen.fire('pointerdown', {button: 0, clientX: 10, clientY: 10});
  screen.fire('pointerup', {clientX: 60, clientY: 30});
  assert.equal(ui.typing(), false, 'a drag selects, it does not start typing');
  screen.fire('pointerdown', {button: 0, clientX: 10, clientY: 10});
  screen.fire('pointerup', {clientX: 11, clientY: 10});
  assert.equal(ui.typing(), true, 'a click types');
  assert.equal(xt.options.disableStdin, false);
  assert.equal(byKey(ui.el, 'term-type').getAttribute('aria-pressed'), 'true', 'the keyboard icon is lit');
  xt.type('l'); xt.type('s'); xt.type('\r');
  await wait(40);
  assert.deepEqual(sent, ['ls\r'], 'typed data goes out in one request');
  assert.equal(xt.keys({type: 'keydown', key: 'Tab', shiftKey: true, preventDefault() {}}), true, 'Shift+Tab goes to the helper');
  assert.equal(ui.typing(), true);
  const esc = {type: 'keydown', key: 'Escape', preventDefault() {}};
  assert.equal(xt.keys(esc), false);
  await wait(ESC_GAP);
  assert.deepEqual(sent.at(-1), '\x1b', 'one Esc goes to the helper a moment later');
  assert.equal(ui.typing(), true);
  xt.keys(esc); xt.keys(esc);
  assert.equal(ui.typing(), false, 'Esc twice stops typing');
  await wait(ESC_GAP);
  assert.equal(sent.filter(x => x === '\x1b').length, 1, 'the two Escs that stopped typing are not sent');
  assert.equal(xt.options.disableStdin, true);
  assert.equal(xt.keys({type: 'keydown', key: 'Enter', preventDefault() {}}), false);
  assert.equal(ui.typing(), true, 'Enter on the screen types there too (the keyboard way in)');
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
  assert.equal(byKey(off.ui.el, 'term-type').hidden, true);
  off.ui.setTyping(true);
  assert.equal(off.ui.typing(), false);
  assert.match(byClass(off.ui.el, 'term-say').textContent, /typing is off/);
  const {ui, xt} = live({answer: () => ({ok: false, status: 403, text: 'Sign in to type here.'})});
  ui.setTyping(true);
  xt.type('a');
  await wait(40);
  assert.equal(ui.typing(), false);
  assert.equal(byKey(ui.el, 'term-type').hidden, true, 'no keyboard icon once the server said no');
});

test('ORCH-2199: a paste goes in as one block without a question and never presses Enter by itself', async () => {
  const {ui, sent, xt} = live();
  const p = ui.el.fire('paste', {target: xt.textarea, clipboardData: {getData: () => 'echo hi\nrm x\n'}});
  assert.ok(p.defaultPrevented);
  assert.equal(byClass(ui.el, 'term-ask'), null, 'no paste question');
  assert.equal(ui.typing(), true, 'a paste into the screen types there');
  await wait(40);
  assert.deepEqual(xt.pasted, ['echo hi\nrm x']);
  assert.deepEqual(sent, ['echo hi\nrm x'], 'the last line end is dropped');
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

test('the screen closing ends typing and says so; no screen says why; no xterm says so', () => {
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
  const saved = globalThis.Terminal;
  globalThis.Terminal = undefined;
  const gl = T({label: 'ORCH-3'});
  gl.hello({typing_allowed: true}); gl.screen(SCREEN);
  assert.equal(gl.el.dataset.state, 'nogl');
  globalThis.Terminal = saved;
});

// ORCH-2204: WebGL off, failing or lost: the normal renderer draws the screen, its rules copied into a CSSOM sheet
test('without WebGL the terminal still opens, drawn by the normal renderer', () => {
  globalThis.noGL = true;
  const n = terms.length;
  const {ui, xt} = live();
  assert.equal(ui.el.dataset.state, 'live');
  assert.equal(ui.el.dataset.renderer, 'dom');
  assert.equal(terms.length, n + 1);
  assert.ok(!xt.addons?.some(a => a.onContextLoss), 'no WebGL addon loaded');
  assert.match(xt.written.join(''), /hello/);
  delete globalThis.noGL;
});

test('a WebGL addon that fails opens the normal renderer instead', () => {
  const Saved = globalThis.WebglAddon;
  globalThis.WebglAddon = {WebglAddon: class { onContextLoss() { throw new Error('no context'); } }};
  const {ui} = live();
  assert.equal(ui.el.dataset.state, 'live');
  assert.equal(ui.el.dataset.renderer, 'dom');
  globalThis.WebglAddon = Saved;
});

test('a lost WebGL context draws the next screen with the normal renderer', () => {
  const {ui, xt} = live();
  assert.equal(ui.el.dataset.renderer, undefined);
  const gl = xt.addons.find(a => a.lost);
  gl.lost();
  assert.equal(xt.disposed, true);
  ui.screen(SCREEN);
  assert.equal(ui.el.dataset.state, 'live');
  assert.equal(ui.el.dataset.renderer, 'dom');
});

test('domSheet copies the renderer\'s blocked style elements into an adopted sheet and follows changes', async () => {
  class Sheet { replaceSync(t) { this.text = t; } }
  const els = [{textContent: '.a{color:red}'}, {textContent: '.b{width:9px}'}];
  const host = {querySelectorAll: () => els};
  const doc = {adoptedStyleSheets: ['page']};
  const savedSheet = globalThis.CSSStyleSheet, savedMO = globalThis.MutationObserver;
  let fire = null;
  globalThis.CSSStyleSheet = Sheet;
  globalThis.MutationObserver = class { constructor(f) { fire = f; } observe() {} disconnect() { this.off = true; } };
  const stop = T.domSheet(host, doc);
  assert.equal(doc.adoptedStyleSheets.length, 2);
  const sheet = doc.adoptedStyleSheets[1];
  assert.equal(sheet.text, '.a{color:red}\n.b{width:9px}');
  els[1].textContent = '.b{width:10px}';
  fire();
  assert.match(sheet.text, /width:10px/);
  stop();
  assert.deepEqual(doc.adoptedStyleSheets, ['page']);
  assert.equal(typeof T.domSheet({querySelectorAll: () => []}, {}), 'function', 'no adoptedStyleSheets: nothing to do');
  globalThis.CSSStyleSheet = savedSheet; globalThis.MutationObserver = savedMO;
});

test('a redraw gives the keyboard back to the screen while typing, never away from another field', () => {
  const {ui, xt} = live();
  ui.setTyping(true);
  assert.equal(document.activeElement, xt.textarea);
  document.activeElement = null;  // the pane was drawn again
  ui.back();
  assert.equal(document.activeElement, xt.textarea);
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

test('a plain terminal says this terminal, not the helper', () => {
  const ui = T({label: 'Plain terminal', plain: true, onInput: async () => ({ok: true})});
  ui.hello({typing_allowed: true}); ui.screen(SCREEN); ui.setTyping(true);
  assert.match(byKey(ui.el, 'term-type').getAttribute('title'), /into this terminal/);
});

test('ORCH-2199: Copy says what it copies; a page can put the tools in its own header', () => {
  const {ui, xt} = live();
  const copy = byKey(ui.el, 'term-copy');
  assert.equal(copy.textContent, 'Copy all');
  xt.sel = 'ell'; xt.selChanged?.();
  assert.equal(copy.textContent, 'Copy selection');
  const out = T({label: 'ORCH-1', toolsOut: true});
  assert.equal(byClass(out.el, 'term-bar'), null, 'no row on top of the screen');
  assert.ok(byKey(out.tools, 'term-copy'), 'the tools are handed to the page');
});

test('Copy gives the lines without the spaces a program pads them with, wrapped lines joined (ORCH-885)', async () => {
  assert.equal(T.plainText([{text: 'one   '}, {text: 'two\t  '}, {text: ''}, {text: '   '}]), 'one\ntwo');
  assert.equal(T.plainText([{text: 'a long li'}, {text: 'ne   ', wrapped: true}, {text: '  indented'}]), 'a long line\n  indented');
  assert.equal(T.plainText([{text: 'hello '}, {text: 'world   ', wrapped: true}]), 'hello world', 'a space at the wrap stays');
  const {ui, xt} = live();
  ui.write(b64('\r\npadded' + ' '.repeat(70)));
  xt.sel = '';
  byKey(ui.el, 'term-copy').click();
  await wait(5);
  assert.ok(!/ \n| $/.test(copied.at(-1)), 'no line ends in spaces');
  assert.match(copied.at(-1), /padded$/);
  xt.sel = 'one   \ntwo  ';
  byKey(ui.el, 'term-copy').click();
  await wait(5);
  assert.equal(copied.at(-1), 'one\ntwo', 'a selection loses its trailing spaces too');
});

test('while watching the box follows the newest line and the cursor (ORCH-882)', () => {
  // a 24-row screen at 16 px a row in a box 200 px tall (the pane under a page): the box scrolls so row 23 shows
  assert.equal(T.followTop({cursorRow: 23, lastRow: 20, rowPx: 16, pad: 8, view: 200, height: 400}), 200);
  // a shell with its prompt on row 2: the top stays in view
  assert.equal(T.followTop({cursorRow: 2, lastRow: 2, rowPx: 16, pad: 8, view: 200, height: 400}), 0);
  // a menu below the cursor: the last row with text counts
  assert.equal(T.followTop({cursorRow: 3, lastRow: 18, rowPx: 16, pad: 0, view: 200, height: 400}), 104);
  // the screen fits: no scroll; never past the end
  assert.equal(T.followTop({cursorRow: 23, lastRow: 23, rowPx: 16, pad: 8, view: 500, height: 500}), 0);
  assert.equal(T.followTop({cursorRow: 299, lastRow: 0, rowPx: 16, pad: 8, view: 200, height: 400}), 200);
});

test('watching fits the helper\'s whole width in the box with a smaller font; typing draws the page font (ORCH-1758)', () => {
  // pure: 120 columns fit at 13 px, the screen has 150: 10.4 px, in half pixels down; never above the page font or under 8
  assert.equal(T.fitFont({base: 13, cur: 13, fitCols: 120, cols: 150}), 10);
  assert.equal(T.fitFont({base: 13, cur: 10, fitCols: 200, cols: 150}), 13);
  assert.equal(T.fitFont({base: 13, cur: 13, fitCols: 40, cols: 300}), 8);
  assert.equal(T.fitFont({base: 13, cur: 13, fitCols: 0, cols: 150}), 13);
  // a box 960 px wide; a cell is 0.6 of the font size, rounded up to whole pixels like xterm does
  globalThis.fitSize = t => ({cols: Math.floor(960 / Math.ceil(t.options.fontSize * 0.6)), rows: 30});
  try {
    const {ui, xt} = live({}, false);  // typing is off in Settings: this page never sizes the helper's screen
    assert.equal(xt.options.fontSize, 13, 'an 80-column screen fits at the page font');
    ui.size({cols: 150, rows: 40});
    assert.ok(xt.options.fontSize < 13, 'a wider screen is drawn smaller');
    assert.ok(globalThis.fitSize(xt).cols >= 150, 'and its whole width fits: ' + xt.options.fontSize);
    ui.size({cols: 600, rows: 40});
    assert.equal(xt.options.fontSize, 8, 'a very wide screen stops at 8 px and scrolls sideways');
  } finally { delete globalThis.fitSize; }
});

test('watching sizes the helper\'s screen to the box when typing is allowed and no other page types (ORCH-1758)', async () => {
  // a box 960 px wide; a cell is 0.6 of the font size, rounded up to whole pixels like xterm does
  globalThis.fitSize = t => ({cols: Math.floor(960 / Math.ceil(t.options.fontSize * 0.6)), rows: Math.floor(468 / (t.options.fontSize * 1.2))});
  const fonts = [];
  try {
    const sizes = [], answers = [];
    const ui = T({label: 'ORCH-1', onInput: async () => ({ok: true}), onSize: z => { sizes.push(z); return answers.shift() || {ok: true}; }});
    ui.hello({typing_allowed: true});
    ui.screen({cols: 200, rows: 50, data: b64('wide')});  // the helper's own 200-column screen
    const xt = terms[terms.length - 1];
    const opts = xt.options; let f = opts.fontSize;
    Object.defineProperty(opts, 'fontSize', {get: () => f, set: v => { f = v; fonts.push(v); }, configurable: true});
    assert.ok(opts.fontSize < 13, 'drawn smaller until the helper takes the box size');
    await wait(5);
    assert.equal(sizes.length, 1, 'the box size goes to the helper while watching');
    assert.ok(Math.abs(sizes[0].cols - 120) <= 2 && sizes[0].rows >= 28, 'the columns at the page font: ' + JSON.stringify(sizes[0]));
    assert.deepEqual(fonts, [], 'measuring never changes the font (no flicker)');
    ui.size(sizes[0]);  // the bridge answers with the new size
    assert.equal(opts.fontSize, 13, 'the screen of the box size is drawn at the page font');
    assert.ok(globalThis.fitSize(xt).cols >= sizes[0].cols, 'and fits');
    ui.screen({cols: sizes[0].cols, rows: sizes[0].rows, data: b64('again')});  // sent again after a gap
    ui.typingBy('other');  // another page types: its size wins, this one draws smaller and sends nothing
    ui.size({cols: 200, rows: 50});
    assert.ok(opts.fontSize < 13);
    await wait(5);
    assert.equal(sizes.length, 1, 'no size after a screen sent again, none while another page types');
    ui.typingBy('none');  // nobody types: this page sizes the window again
    await wait(5);
    assert.equal(sizes.length, 2);
    answers.push({ok: false, status: 403, text: 'Typing is off'});
    ui.size({cols: 150, rows: 40});
    ui.typingBy('none');
    await wait(5);
    assert.equal(sizes.length, 3);
    ui.size({cols: 160, rows: 40});
    ui.typingBy('none');
    await wait(5);
    assert.equal(sizes.length, 3, 'after a refusal (typing off in Settings) no more sizes until the next hello');
    assert.ok(globalThis.fitSize(xt).cols >= 160, 'drawn smaller to fit instead');
    ui.hello({typing_allowed: true});
    ui.setTyping(true);
    assert.equal(opts.fontSize, 13, 'typing draws the page font');
    await wait(5);
    assert.deepEqual(sizes.at(-1), {cols: 120, rows: 30}, 'and sends the box size');
  } finally { delete globalThis.fitSize; }
});

test('another page takes the typing: this one goes back to watching and says so; Let me type takes it back (ORCH-883)', () => {
  const turned = [];
  const ui = T({label: 'ORCH-1', onInput: async () => ({ok: true}), onTyping: (on, byOther) => turned.push([on, byOther])});
  ui.hello({typing_allowed: true});
  ui.screen(SCREEN);
  ui.setTyping(true);
  assert.equal(ui.typing(), true);
  ui.typingBy('you');
  assert.equal(ui.typing(), true, 'its own claim changes nothing');
  ui.typingBy('other');
  assert.equal(ui.typing(), false);
  assert.match(byClass(ui.el, 'term-say').textContent, /Another page is typing/);
  assert.deepEqual(turned, [[true, false], [false, true]]);
  byKey(ui.el, 'term-type').click();
  assert.equal(ui.typing(), true);
  assert.match(byKey(ui.el, 'term-type').getAttribute('title'), /^Typing/);
  ui.setTyping(false);
  ui.typingBy('none');
  assert.equal(byClass(ui.el, 'term-say').hidden, true, 'nothing to say while watching');
});

test('ORCH-1600: with typing off, Turn typing on leads to the switch in Settings; it hides once typing is allowed', () => {
  const ui = T({label: 'ORCH-1', settingsHref: '#settings/addons/focus', onInput: async () => ({ok: true}), onSize: () => {}});
  ui.hello({typing_allowed: false});
  ui.screen(SCREEN);
  const a = byKey(ui.el, 'term-settings');
  assert.equal(a.hidden, false);
  assert.equal(a.getAttribute('href'), '#settings/addons/focus');
  assert.equal(byClass(ui.el, 'term-say').textContent, 'Watch only');  // said once: the link says the rest
  ui.hello({typing_allowed: true});
  assert.equal(a.hidden, true);
  assert.equal(byKey(live().ui.el, 'term-settings'), null);  // no address given: no link
});

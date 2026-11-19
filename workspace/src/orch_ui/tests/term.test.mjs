import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

// A tiny DOM: enough for term.js to build its element and take keys, pastes and clicks. innerHTML is recorded so a
// test can prove that no screen text ever goes in as markup.
const markup = [];
class Node_ {
  constructor(tag) {
    this.tag = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.dataset = {}; this.className = '';
    this.hidden = false; this._text = ''; this.parentNode = null; this.scrollTop = 0;
  }
  set innerHTML(v) { markup.push(v); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  append(...c) { for (const x of c) { x.parentNode = this; this.children.push(x); } }
  replaceChildren(...c) { this.children = []; this.append(...c); }
  replaceWith(n) { const p = this.parentNode, i = p.children.indexOf(this); n.parentNode = p; p.children[i] = n; }
  remove() { const p = this.parentNode; if (p) p.children.splice(p.children.indexOf(this), 1); this.parentNode = null; }
  get lastChild() { return this.children[this.children.length - 1]; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  fire(t, e = {}) {
    let stopped = false;
    const ev = Object.assign({preventDefault() { ev.defaultPrevented = true; }, stopPropagation() { stopped = true; }, target: this}, e);
    (this.listeners[t] || []).forEach(f => f(ev));
    return ev;
  }
  click() { this.fire('click'); }
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  focus() { globalThis.document.activeElement = this; this.fire('focus'); }
  getBoundingClientRect() { return {width: 0, height: 0}; }
  get scrollHeight() { return 0; }
  get clientHeight() { return 0; }
  find(pred) { if (pred(this)) return this; for (const c of this.children) { const r = c.find(pred); if (r) return r; } return null; }
}
globalThis.window = globalThis;
globalThis.document = {createElement: t => new Node_(t), activeElement: null};
globalThis.getSelection = () => ({isCollapsed: true, anchorNode: null});
require('../static/term.js');
const T = window.UI.term;
const byKey = (root, k) => root.find(n => n.attrs['data-key'] === k);
const byClass = (root, c) => root.find(n => String(n.className).split(' ').includes(c));
const wait = ms => new Promise(r => setTimeout(r, ms));
const LIVE = {state: 'live', screen: 'hello\n$ ', cx: 2, cy: 1, cols: 80, rows: 24, cursor: true, typing_allowed: true};

test('paint: colours become classes, a reset ends them, the cursor is its own segment', () => {
  const rows = T.paint('a\x1b[31mred\x1b[0m b\n\x1b[1;44mX\x1b[m', 1, 0, true);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0].map(s => s.t), ['a', 'r', 'ed', ' b']);
  assert.match(rows[0][1].c, /t-c1/); assert.match(rows[0][1].c, /t-cur/);
  assert.equal(rows[0][3].c, 't-seg');
  assert.match(rows[1][0].c, /t-b/); assert.match(rows[1][0].c, /t-g4/);
});

test('paint: links, clipboard writes and title changes from a program are dropped, not drawn', () => {
  const s = 'x\x1b]8;;https://evil.example\x1b\\link\x1b]8;;\x1b\\y\x1b]52;c;aGk=\x07z\x1b]0;title\x07!';
  const text = T.paint(s, 0, 0, false)[0].map(r => r.t).join('');
  assert.equal(text, 'xlinkyz!');
  assert.equal(T.plain(s), 'xlinkyz!');
});

test('paint: 256 colours keep the base 16, true colour keeps the default, blank rows under the text go', () => {
  const rows = T.paint('\x1b[38;5;2mg\x1b[38;2;1;2;3mt\n\n\n', 0, 0, false);
  assert.equal(rows.length, 1);
  assert.match(rows[0][0].c, /t-c2/);
  assert.match(rows[0][1].c, /t-c2/, 'true colour leaves the colour as it was');
});

test('toItem: letters and named keys go, shortcuts stay with the browser', () => {
  const k = (key, more = {}) => T.toItem({key, ...more}, false);
  assert.deepEqual(k('a'), {t: 'a'});
  assert.deepEqual(k('Enter'), {k: 'Enter'});
  assert.deepEqual(k('Backspace'), {k: 'BSpace'});
  assert.deepEqual(k('ArrowUp'), {k: 'Up'});
  assert.deepEqual(k('c', {ctrlKey: true}), {k: 'C-c'});
  assert.equal(T.toItem({key: 'c', ctrlKey: true}, true), null, 'Ctrl+C with a selection copies');
  assert.equal(k('C', {ctrlKey: true, shiftKey: true}), null);
  assert.equal(k('v', {ctrlKey: true}), null, 'Ctrl+V is a paste');
  assert.equal(k('c', {metaKey: true}), null);
  assert.equal(k('Tab', {shiftKey: true}), null, 'Shift+Tab stops typing');
  assert.equal(k('F5'), null);
  assert.equal(k('Shift'), null);
});

test('merge and paste: fast letters in one item, pasted text cleaned and cut at 2000', () => {
  assert.deepEqual(T.merge([{t: 'a'}, {t: 'b'}, {k: 'Enter'}, {t: 'c'}]), [{t: 'ab'}, {k: 'Enter'}, {t: 'c'}]);
  const items = T.pasteItems('a\r\nb\x07c' + 'x'.repeat(2500));
  assert.equal(items.length, 2);
  assert.ok(items[0].t.startsWith('a\nbc'));
  assert.equal(items[0].t.length, 2000);
  assert.equal(T.pasteAsk('one line'), '');
  assert.match(T.pasteAsk('rm -rf x\n'), /1 line and press Enter/);
  assert.match(T.pasteAsk('a\nb\nc'), /3 lines/);
});

test('fit: the size of a box in cells, inside the limits', () => {
  assert.deepEqual(T.fit(800, 360, 8, 18), {cols: 100, rows: 20});
  assert.deepEqual(T.fit(40, 20, 8, 18), {cols: 20, rows: 5});
  assert.equal(T.fit(0, 100, 8, 18), null);
});

test('watching only by default: keys and pastes send nothing until Let me type is on', async () => {
  const sent = [];
  const ui = T({label: 'ORCH-1', onKeys: async items => { sent.push(items); return {ok: true}; }});
  ui.update(LIVE);
  assert.equal(ui.el.dataset.typing, 'off');
  const screen = byClass(ui.el, 'term-screen');
  const e = screen.fire('keydown', {key: 'x'});
  screen.fire('paste', {clipboardData: {getData: () => 'ls'}});
  await wait(60);
  assert.deepEqual(sent, []);
  assert.ok(!e.defaultPrevented, 'a key while watching stays with the page');
  assert.match(byClass(ui.el, 'term-say').textContent, /Watching/);
  byKey(ui.el, 'term-type').click();
  assert.equal(ui.typing(), true);
  assert.equal(byKey(ui.el, 'term-type').getAttribute('aria-checked'), 'true');
  screen.fire('keydown', {key: 'l'}); screen.fire('keydown', {key: 's'}); screen.fire('keydown', {key: 'Enter'});
  await wait(60);
  assert.deepEqual(sent, [[{t: 'ls'}, {k: 'Enter'}]]);
  screen.fire('keydown', {key: 'Tab', shiftKey: true});
  assert.equal(ui.typing(), false, 'Shift+Tab stops typing');
  assert.equal(markup.length, 0, 'no screen text went in as markup');
});

test('typing stays off when the workspace setting is off, and a refused key turns it off', async () => {
  const ui = T({label: 'ORCH-2', onKeys: async () => ({ok: false, status: 403, text: "Typing into the helper's screen is off."})});
  ui.update({...LIVE, typing_allowed: false});
  assert.equal(byClass(ui.el, 'term-sw').hidden, true);
  ui.setTyping(true);
  assert.equal(ui.typing(), false);
  assert.match(byClass(ui.el, 'term-say').textContent, /typing is off/);
  ui.update(LIVE);
  ui.setTyping(true);
  assert.equal(ui.typing(), true);
  byClass(ui.el, 'term-screen').fire('keydown', {key: 'a'});
  await wait(60);
  assert.equal(ui.typing(), false);
  assert.equal(byClass(ui.el, 'term-sw').hidden, true);
});

test('a paste with a line end asks once; Cancel sends nothing, Paste sends it', async () => {
  const sent = [];
  const ui = T({label: 'ORCH-3', onKeys: async items => { sent.push(items); return {ok: true}; }});
  ui.update(LIVE); ui.setTyping(true);
  const screen = byClass(ui.el, 'term-screen'), ask = byClass(ui.el, 'term-ask');
  screen.fire('paste', {clipboardData: {getData: () => 'echo hi\nrm x\n'}});
  assert.equal(ask.hidden, false);
  assert.match(ask.textContent, /2 lines/);
  byKey(ui.el, 'term-paste-no').click();
  await wait(60);
  assert.deepEqual(sent, []);
  screen.fire('paste', {clipboardData: {getData: () => 'echo hi\n'}});
  byKey(ui.el, 'term-paste-go').click();
  await wait(60);
  assert.deepEqual(sent, [[{t: 'echo hi\n'}]]);
  screen.fire('paste', {clipboardData: {getData: () => 'plain'}});
  await wait(60);
  assert.deepEqual(sent[1], [{t: 'plain'}], 'one line without a line end goes in at once');
});

test('the screen closing ends typing and says so; no screen says why', () => {
  const ui = T({label: 'ORCH-4', onKeys: async () => ({ok: true})});
  ui.update({state: 'oneshot'});
  assert.equal(ui.el.dataset.state, 'oneshot');
  ui.update(LIVE); ui.setTyping(true);
  ui.update({state: 'none'});
  assert.equal(ui.typing(), false);
  assert.equal(ui.el.dataset.state, 'ended');
  assert.match(ui.el.find(n => n.tag === 'p' && String(n.className).includes('term-state')).textContent, /closed/);
});

test('only changed rows are written again, so a selection in the others stays', () => {
  const ui = T({label: 'ORCH-5'});
  ui.update({...LIVE, screen: 'one\ntwo\nthree'});
  const rows = byClass(ui.el, 'term-rows');
  const first = rows.children[0], second = rows.children[1];
  ui.update({...LIVE, screen: 'one\nTWO\nthree'});
  assert.equal(rows.children[0], first);
  assert.notEqual(rows.children[1], second);
  assert.equal(rows.children[1].textContent, 'TWO');
});

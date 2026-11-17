import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);

// A tiny DOM: enough for results.js to build every widget and the overlay. innerHTML is recorded so a test can
// prove that no result text ever goes in as markup.
const markup = [];
class Node_ {
  constructor(tag) {
    this.tag = tag; this.children = []; this.listeners = {}; this.attrs = {}; this.dataset = {}; this.className = ''; this.hidden = false;
    this._text = ''; this.style = {};
    const self = this;
    this.classList = {
      add: c => { if (!self.className.split(' ').includes(c)) self.className = (self.className + ' ' + c).trim(); },
      remove: c => { self.className = self.className.split(' ').filter(x => x !== c).join(' '); },
      toggle: c => { const on = !self.className.split(' ').includes(c); on ? self.classList.add(c) : self.classList.remove(c); return on; },
      contains: c => self.className.split(' ').includes(c)
    };
    if (tag === 'template') this.content = new Node_('#fragment');
  }
  set innerHTML(v) { markup.push(v); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent || '').join(''); }
  append(...c) { this.children.push(...c.map(x => typeof x === 'string' ? text(x) : x)); }
  prepend(...c) { this.children.unshift(...c); }
  replaceChildren(...c) { this.children = []; this.append(...c); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  fire(t, e) { (this.listeners[t] || []).forEach(f => f(Object.assign({preventDefault() {}, target: this}, e))); }
  click() { this.fire('click'); }
  get lastChild() { return this.children[this.children.length - 1]; }
  get childNodes() { return this.children; }
  get offsetWidth() { return 0; }
  querySelector() { return null; }
  showModal() { this.open = true; }
  close() { this.open = false; this.fire('close'); }
  remove() {}
  focus() {}
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.all && c.all(pred, out)); return out; }
  find(cls) { return this.all(n => (n.className || '').split(' ').includes(cls)); }
}
const text = t => ({nodeType: 3, textContent: String(t)});
const body = new Node_('body');
globalThis.document = {createElement: t => new Node_(t), createElementNS: (ns, t) => new Node_(t), createTextNode: text, body};
globalThis.location = {href: 'http://127.0.0.1/'};
globalThis.window = {};
require('../static/results.js');
const UI = globalThis.window.UI;

const ALL = [
  {type: 'md', name: 'n.md', text: '# Title\n- one\n- two'}, {type: 'text', name: 'a.log', text: 'a\nb\nc'},
  {type: 'code', name: 'a.py', text: 'def f():\n    return 1'}, {type: 'data', name: 's.json', text: '{"a":[1,2],"b":{"c":true}}'},
  {type: 'table', name: 'p.csv', text: 'a,b\n1,2\n3,4'}, {type: 'page', name: 'p.html', src: 'p.html'},
  {type: 'pdf', name: 'o.pdf', src: 'o.pdf', pages: 4}, {type: 'picture', name: 'p.png', src: 'p.png'},
  {type: 'video', name: 'v.webm', src: 'v.webm', duration: '0:42'}, {type: 'audio', name: 'a.wav', src: 'a.wav', duration: '1:15'},
  {type: 'chart', name: 'Uses', labels: ['Mon', 'Tue'], values: [3, 5]}, {type: 'change', name: 'Fix', files: [['a.css', 4, 1]], diff: '+ a'},
  {type: 'pr', name: 'Pull request 1', status: 'draft', checks: [{name: 'Tests', state: 'pass'}]}, {type: 'archive', name: 'e.zip', files: [['a', '1 KB']], total: 1},
  {type: 'link', name: 'Notes', href: 'https://example.com/notes'}, {type: 'file', name: 'x.sketch', size: 4400000}
];

test('there are 16 kinds and every file name maps to one of them, the rest to unknown file', () => {
  assert.equal(UI.result.TYPES.length, 16);
  const want = {'a.md': 'md', 'b.LOG': 'text', 'c.py': 'code', 'd.yaml': 'data', 'e.json': 'data', 'f.csv': 'table', 'g.html': 'page',
    'h.pdf': 'pdf', 'i.svg': 'picture', 'j.mp4': 'video', 'k.mp3': 'audio', 'l.diff': 'change', 'm.zip': 'archive', 'n.bin': 'file', noext: 'file',
    'https://github.com/o/r/pull/12': 'pr', 'https://example.com/x': 'link'};
  for (const [name, kind] of Object.entries(want)) assert.equal(UI.result.kindOf(name), kind, name);
});

test('every kind builds small and big in every state', () => {
  for (const item of ALL) for (const size of ['sm', 'lg']) for (const state of ['ready', 'empty', 'loading', 'error', 'large']) {
    const w = UI.result(item, {size, state});
    assert.equal(w.dataset.type, item.type, item.type);
    assert.equal(w.dataset.size, size);
    assert.equal(w.dataset.state, item.type === 'link' && state === 'large' ? 'ready' : state, item.type + ' ' + state);
  }
});

test('the state follows the content: nothing in it is empty, over the limit is too big', () => {
  assert.equal(UI.result({type: 'md', name: 'e.md', text: '  '}).dataset.state, 'empty');
  assert.equal(UI.result({type: 'table', name: 't.csv', text: 'only,a,header'}).dataset.state, 'empty');
  assert.equal(UI.result({type: 'text', name: 'big.log', text: 'x', size: UI.result.LIMIT + 1}).dataset.state, 'large');
  assert.equal(UI.result({type: 'md', name: 'n.md', text: 'hi'}).dataset.state, 'ready');
});

test('loading is busy, an error says it plainly and offers Try again and Download when big', () => {
  const l = UI.result(ALL[0], {state: 'loading'});
  assert.equal(l.find('result-state-box')[0].attrs['aria-busy'], 'true');
  let tried = 0;
  const e = UI.result(Object.assign({download: 'n.md'}, ALL[0]), {size: 'lg', state: 'error', onRetry: () => tried++});
  const box = e.find('result-state-box')[0];
  assert.equal(box.attrs.role, 'alert');
  assert.match(box.textContent, /Can.t preview this file\./);
  assert.match(box.textContent, /Try again/);
  assert.match(box.textContent, /Download/);
  box.all(n => n.tag === 'button')[0].click();
  assert.equal(tried, 1);
});

test('result text is never markup and a web page sits in an empty sandbox', () => {
  markup.length = 0;
  const evil = '<img src=x onerror=alert(1)>';
  for (const item of [{type: 'md', name: evil, text: '# ' + evil + '\n- ' + evil}, {type: 'text', name: 'a', text: evil},
    {type: 'table', name: 'a', text: 'a\n' + evil}, {type: 'data', name: 'a', text: JSON.stringify({k: evil})}])
    for (const size of ['sm', 'lg']) UI.result(item, {size});
  assert.ok(markup.every(m => !m.includes('onerror')), 'item text went into innerHTML');
  const frame = UI.result({type: 'page', name: 'p.html', src: 'p.html'}, {size: 'lg'}).all(n => n.tag === 'iframe')[0];
  assert.equal(frame.attrs.sandbox, '');
});

test('numbers in words use the right singular and plural', () => {
  const one = UI.result({type: 'table', name: 't.csv', text: 'a,b\n1,2'}, {size: 'lg'}).textContent;
  assert.match(one, /1 row · 2 columns/);
  const pdf = UI.result({type: 'pdf', name: 'o.pdf', src: 'o.pdf', pages: 1}).textContent;
  assert.match(pdf, /1 page/);
  assert.doesNotMatch(pdf, /1 pages/);
});

test('too big shows only the first part with a plain sentence', () => {
  const rows = 'h\n' + Array.from({length: 20}, (_, i) => 'r' + i).join('\n');
  const w = UI.result({type: 'table', name: 't.csv', text: rows, state: 'large', shown: 3}, {size: 'lg'});
  assert.match(w.textContent, /Too big to show in full/);
  assert.match(w.textContent, /3 of 20 rows/);
});

test('a small widget opens the overlay; the overlay skips links and ← → move through the rest', () => {
  const w = UI.result(ALL[0], {size: 'sm', list: ALL, index: 0});
  const open = w.find('result-open')[0];
  assert.match(open.attrs['aria-label'], /^Open a big preview of n\.md/);
  open.click();
  const d = body.children.at(-1);
  assert.ok(d.open);
  const pos = d.find('result-ov-pos')[0];
  assert.equal(pos.textContent, '1 of 15');
  d.fire('keydown', {key: 'ArrowRight', target: d});
  assert.equal(pos.textContent, '2 of 15');
  d.fire('keydown', {key: 'ArrowLeft', target: d}); d.fire('keydown', {key: 'ArrowLeft', target: d});
  assert.equal(pos.textContent, '15 of 15');
  assert.equal(UI.resultOverlay([ALL[14]], 0), null, 'a plain link has no overlay');
  const link = UI.result(ALL[14]);
  assert.equal(link.tag, 'a');
  assert.equal(link.target, '_blank');
});

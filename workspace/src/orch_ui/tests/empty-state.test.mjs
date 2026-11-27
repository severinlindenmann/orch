import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

// UI.state's one next step (SX-10, R7.2): a button, or a link when the step is another page.
class N {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.className = ''; this.own = ''; }
  set textContent(v) { this.own = String(v); }
  get textContent() { return this.own + this.children.map(c => c.textContent).join(''); }
  append(...c) { c.forEach(x => this.children.push(typeof x === 'string' ? Object.assign(new N('#text'), {own: x}) : x)); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() {}
}
function load() {
  const UI = {};
  const document = {createElement: t => new N(t), createElementNS: (_, t) => new N(t)};
  vm.runInNewContext(readFileSync(new URL('../static/widgets.js', import.meta.url), 'utf8'), {window: {UI}, document, setTimeout, clearTimeout, console});
  return UI;
}
const action = box => box.children.find(c => /\bbtn\b/.test(c.className));

test('an action with href is a link drawn as the outline button, opening where it says', () => {
  const box = load().state({kind: 'empty', title: 'No files yet', action: {label: 'Open tickets', href: '/#tickets', target: '_top'}});
  const a = action(box);
  assert.equal(a.tag, 'a');
  assert.equal(a.href, '/#tickets');
  assert.equal(a.target, '_top');
  assert.equal(a.type, undefined);
  assert.match(a.className, /\boutline\b/);
  assert.equal(a.textContent, 'Open tickets');
});

test('an action without href stays a button', () => {
  let clicked = 0;
  const b = action(load().state({kind: 'empty', title: 'Nothing here', action: {label: 'Show all', onClick: () => { clicked++; }}}));
  assert.equal(b.tag, 'button');
  assert.equal(b.type, 'button');
  b.onclick();
  assert.equal(clicked, 1);
});

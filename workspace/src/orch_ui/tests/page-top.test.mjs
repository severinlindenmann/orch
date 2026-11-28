import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

// ORCH-2282 (owner D1 A): one top for every page. UI.pageTop puts Settings first and the page's buttons after it,
// a page inside another page gets '← <parent>' above its name, and every word is set as text.
const read = f => readFileSync(new URL('../static/' + f, import.meta.url), 'utf8');
class N {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.dataset = {}; this.className = ''; this.own = ''; this.listeners = {}; }
  set textContent(v) { this.own = String(v); this.children = []; }
  get textContent() { return this.own + this.children.map(c => c.textContent).join(''); }
  set innerHTML(v) { this.html = v; }
  append(...c) { c.forEach(x => this.children.push(typeof x === 'string' ? Object.assign(new N('#text'), {own: x}) : x)); }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(k, f) { this.listeners[k] = f; }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach(c => c.all(pred, out)); return out; }
  cls(c) { return this.all(n => n.className.split(' ').includes(c)); }
}
function load() {
  const document = {createElement: t => new N(t), createElementNS: (_, t) => new N(t)};
  const UI = {};
  vm.runInNewContext(read('widgets.js'), {window: {UI}, document, setTimeout, clearTimeout, console});
  return UI;
}

test('name, one sentence, Settings first and the filled button last', () => {
  const UI = load(), primary = Object.assign(new N('button'), {className: 'btn primary sm'});
  const top = UI.pageTop({title: 'Automation', text: 'Repeat work on a plan you choose.', settings: '#settings/addons/automation', actions: [primary], key: 'heading'});
  assert.equal(top.tag, 'header');
  assert.match(top.className, /page-heading page-top/);
  assert.equal(top.dataset.key, 'heading');
  assert.equal(top.all(n => n.tag === 'h1')[0].textContent, 'Automation');
  assert.equal(top.all(n => n.tag === 'p')[0].textContent, 'Repeat work on a plan you choose.');
  const acts = top.cls('page-heading-actions')[0].children;
  assert.equal(acts.length, 2);
  assert.equal(acts[0].href, '#settings/addons/automation');
  assert.match(acts[0].className, /btn outline sm page-settings/);
  assert.equal(acts[0].textContent, 'Settings');
  assert.equal(acts[1], primary);
  assert.equal(top.cls('page-back').length, 0, 'a page of its own has no back link');
});

// W-006 (owner, 28 Nov): the "Preview" pill sat on the title's middle on Files and below its baseline on Personal and
// Skills. One place for it: after the name, inside the h1, the same on every page.
test('W-006: a page tag sits after the name inside the title; no tag, no pill', () => {
  const UI = load();
  const top = UI.pageTop({title: 'Files', tag: 'Preview', text: 'Browse every file in this workspace.'});
  const h1 = top.all(n => n.tag === 'h1')[0];
  assert.equal(h1.children.at(-1).className, 'badge page-tag');
  assert.equal(h1.children.at(-1).textContent, 'Preview');
  assert.match(h1.textContent, /^Files Preview$/);
  assert.equal(UI.pageTop({title: 'Files'}).cls('page-tag').length, 0);
  const css = read('components.css');
  assert.ok(css.includes('.page-heading h1:has(>.badge){display:flex;align-items:center;flex-wrap:wrap;gap:4px 12px}'));
  assert.ok(css.includes('.page-heading>div:first-child{display:grid;gap:4px;min-width:0}'), 'the name and its sentence are 4 px apart');
});

test('a page inside another page: ← parent above the name, no empty actions', () => {
  const UI = load();
  const top = UI.pageTop({title: 'New repeat', back: {label: 'Automation', href: '#addon/automation'}});
  const left = top.cls('page-top-text')[0];
  assert.equal(left.children[0].className, 'page-back');
  assert.equal(left.children[0].href, '#addon/automation');
  assert.equal(left.children[0].textContent, 'Automation');
  assert.equal(left.children[1].tag, 'h1');
  assert.equal(top.cls('page-heading-actions').length, 0);
});

test('words are text, never markup', () => {
  const UI = load();
  const top = UI.pageTop({title: '<img src=x onerror=1>', text: '<b>x</b>', back: {label: '<i>p</i>', href: '#tickets'}});
  assert.equal(top.all(n => n.tag === 'h1')[0].textContent, '<img src=x onerror=1>');
  assert.ok(top.all(n => n.tag !== 'svg' && n.html !== undefined).length === 0, 'only the fixed drawings use markup');
  assert.equal(UI.pageBack({label: 'Tickets', href: '#tickets'}).textContent, 'Tickets');
});

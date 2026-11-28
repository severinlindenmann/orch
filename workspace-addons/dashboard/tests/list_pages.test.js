'use strict';
// W-052 (owner 28 Nov): 796 older lessons sat behind a notice whose only button left the page. An add-on now sends a
// long list as pages (list blocks with the same title); the dashboard shows one page at a time, the notice's button is
// "Show older lessons" and each row keeps its own buttons.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.className = ''; this.dataset = {}; this.attrs = {}; this.kids = []; this.text = ''; this.hidden = false; this.style = {}; this.parent = null; }
  get classList() { const self = this; return {add: c => { self.className = (self.className + ' ' + c).trim(); }, contains: c => self.className.split(' ').includes(c)}; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  set textContent(v) { this.text = String(v); this.kids = []; }
  get textContent() { return this.text + this.kids.map(k => k.textContent).join(''); }
  set href(v) { this.attrs.href = v; } set type(v) { this.attrs.type = v; }
  append(...c) { for (const x of c) { const n = typeof x === 'string' ? Object.assign(new El('#text'), {text: x}) : x; n.parent = this; this.kids.push(n); } }
  replaceChildren(...c) { this.kids = []; this.append(...c); }
  get childNodes() { return this.kids; }
  all() { return this.kids.flatMap(k => [k, ...k.all()]); }
  find(tag, cls) { return this.all().filter(n => n.tagName === tag.toUpperCase() && (!cls || n.className.split(' ').includes(cls))); }
}
global.document = {createElement: t => new El(t), createElementNS: (_, t) => new El(t), createDocumentFragment: () => new El('#frag')};
global.location = {hash: '#addon/lessons'};
const B = require('../src/orch_dashboard/web/blocks.js');

const lesson = i => ({title: `Lesson ${i}`, subtitle: 'Added 15 Nov by Helper', actions: [
  {label: 'Edit', action: {op: 'addon.prompt', args: {verb: 'edit', target: 'l_' + String(i).padStart(6, '0'), value: `Lesson ${i}`, label: 'Edit lesson'}}},
  {label: 'Delete', tone: 'bad', action: {op: 'addon.act', args: {verb: 'rm', target: 'l_' + String(i).padStart(6, '0')}}}]});
const view = (n, title = 'Saved lessons') => Array.from({length: Math.ceil(n / 50)}, (_, p) => ({type: 'list', title, count: n,
  items: Array.from({length: Math.min(50, n - p * 50)}, (_, i) => lesson(n - p * 50 - i))}));
const drawn = blocks => { const root = B.render(blocks, {self: 'lessons'}); return {root, lists: root.find('section'), rows: root.find('li'), pager: root.find('nav', 'blk-pager')[0]}; };
const buttons = nav => nav.find('button').map(b => [b.textContent, b.dataset.to, !!b.disabled]);

test('a list sent in pages shows one page, says where you are and offers the next page', () => {
  const blocks = view(846, 'Paged A');
  const d = drawn(blocks);
  assert.equal(d.lists.length, 1, 'one card, not seventeen');
  assert.equal(d.rows.length, 50);
  assert.equal(d.rows[0].textContent.includes('Lesson 846'), true);
  assert.deepEqual(buttons(d.pager), [['Previous page', '-1', true], ['Next page', '1', false]]);
  assert.equal(d.pager.find('span', 'meta')[0].textContent, '1–50 of 846 · page 1 of 17');
  assert.equal(d.pager.find('button')[1].dataset.listPage, 'Paged A');
  // each row keeps Edit and Delete on its own lesson
  const acts = d.rows[0].find('button').filter(b => b.dataset.addonPrompt || b.dataset.addonAct);
  assert.deepEqual(acts.map(b => [b.textContent, b.dataset.verb, b.dataset.addonPrompt || b.dataset.target]), [['Edit', 'edit', 'l_000846'], ['Delete', 'rm', 'l_000846']]);
});

test('"Show older" moves one page, the page stays over a refresh, and the last page has nothing older', () => {
  const blocks = view(120, 'Paged B');
  assert.equal(B.listHasOlder(blocks), true);
  assert.equal(B.listOlder(blocks), true);
  let d = drawn(blocks);
  assert.equal(d.pager.find('span', 'meta')[0].textContent, '51–100 of 120 · page 2 of 3');
  assert.equal(d.rows[0].textContent.includes('Lesson 70'), true);
  assert.deepEqual(buttons(d.pager), [['Previous page', '0', false], ['Next page', '2', false]]);
  // the view is read again (a poll, or after Delete): the same page
  d = drawn(view(119, 'Paged B'));
  assert.equal(d.pager.find('span', 'meta')[0].textContent, '51–100 of 119 · page 2 of 3');
  assert.equal(B.listGo('Paged B', 2), true);
  d = drawn(view(119, 'Paged B'));
  assert.equal(d.rows.length, 19);
  assert.deepEqual(buttons(d.pager), [['Previous page', '1', false], ['Next page', '3', true]]);
  assert.equal(B.listHasOlder(view(119, 'Paged B')), false);
  assert.equal(B.listOlder(view(119, 'Paged B')), false);
  // lessons were deleted until two pages are left: the page on screen is the last one that exists
  d = drawn(view(60, 'Paged B'));
  assert.equal(d.pager.find('span', 'meta')[0].textContent, '51–60 of 60 · page 2 of 2');
  // back to one page: a plain list with no pager
  d = drawn(view(40, 'Paged B'));
  assert.equal(d.pager, undefined);
  assert.equal(d.rows.length, 40);
});

test('lists with different titles, and a single list, are never paged', () => {
  const d = drawn([...view(30, 'First'), ...view(20, 'Second')]);
  assert.equal(d.lists.length, 2);
  assert.equal(d.pager, undefined);
  assert.equal(B.listHasOlder([...view(30, 'First'), ...view(20, 'Second')]), false);
});

// ---- the notice's button (pages/settings.js)
function settings(blocks, hash = '#addon/lessons') {
  const node = (tag, attrs = {}, children = []) => ({tag, attrs, children: children.flat(Infinity).filter(c => c != null && c !== false)});
  const c = vm.createContext({
    window: {orch: {toast() {}}}, OrchBlocks: B, localStorage: {getItem: () => null, setItem() {}},
    h: (tag, attrs, ...children) => node(tag, attrs || {}, children), fragment: (...children) => node('fragment', {}, children),
    array: v => Array.isArray(v) ? v : [], snapshot: false, clean: v => String(v ?? ''), capitalise: v => String(v), time: () => '', render() {},
    route: () => ({kind: 'addon', id: 'lessons'}), location: {hash}, setTimeout: () => 1, clearTimeout() {}, document: {getElementById: () => null}, locks: new Set(),
    state: {settings: {addons: [{name: 'lessons', active: true}]}}, addons: () => [{name: 'lessons', dashboard: {label: 'Lessons'}}], URL,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
  const notice = c.addonNotice({notice: 'The list is too long: helpers see only the newest lessons. Shorten or delete old ones. This page shows 50 at a time; 70 older are on the next pages.',
    notice_tone: 'warn', header: {link: {label: 'Show older lessons', to: 'app:addon/lessons'}}, blocks});
  return {buttons: all(notice, n => n.tag === 'button'), links: all(notice, n => n.tag === 'a')};
}

test('the warning’s one button is "Show older lessons" and stays on the page; on the last page it is gone', () => {
  const first = settings(view(120, 'Notice list'));
  assert.equal(first.links.length, 0, 'no link that leaves the page (it used to be "← Add-ons")');
  assert.equal(first.buttons.length, 1);
  assert.deepEqual(first.buttons[0].children, ['Show older lessons']);
  assert.equal(first.buttons[0].attrs['data-list-older'], '');
  assert.match(first.buttons[0].attrs.className, /\bprimary\b/);
  B.listGo('Notice list', 2);
  const last = settings(view(120, 'Notice list'));
  assert.equal(last.buttons.length + last.links.length, 0);
});

test('with a single page there is nothing older: the notice has no button', () => {
  const node = settings(view(20, 'Short list'));
  assert.equal(node.buttons.length, 0, 'nothing older: no button');
});

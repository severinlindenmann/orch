'use strict';
// Table block `compact` and `show` (ORCH-537): the first rows show, the rest sit behind one "Show N more" button that
// stays pressed across refreshes of the same page.
const test = require('node:test');
const assert = require('node:assert/strict');

class El {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.className = ''; this.dataset = {}; this.attrs = {}; this.kids = []; this.text = ''; this.hidden = false; this.style = {}; this.parent = null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  set textContent(v) { this.text = String(v); this.kids = []; }
  get textContent() { return this.text + this.kids.map(k => k.textContent).join(''); }
  set href(v) { this.attrs.href = v; } set type(v) { this.attrs.type = v; }
  append(...c) { for (const x of c) { const n = typeof x === 'string' ? Object.assign(new El('#text'), {text: x}) : x; n.parent = this; this.kids.push(n); } }
  replaceChildren(...c) { this.kids = []; this.append(...c); }
  remove() { if (this.parent) this.parent.kids = this.parent.kids.filter(k => k !== this); }
  get childNodes() { return this.kids; }
  all() { return this.kids.flatMap(k => [k, ...k.all()]); }
  find(tag, cls) { return this.all().filter(n => n.tagName === tag.toUpperCase() && (!cls || n.className.split(' ').includes(cls))); }
}
global.document = {createElement: t => new El(t), createElementNS: (_, t) => new El(t), createDocumentFragment: () => new El('#frag')};
global.location = {hash: '#addon/automation'};
global.matchMedia = () => ({matches: false});
const B = require('../src/orch_dashboard/web/blocks.js');

const rows = n => Array.from({length: n}, (_, i) => ({cells: {schedule: `Wake ${i}`, next: 'Wed 04 Nov, 10:00'}}));
const table = (title, n, extra) => ({type: 'table', title, columns: [{key: 'schedule', label: 'Ticket', type: 'text'}, {key: 'next', label: 'Starts', type: 'text'}], rows: rows(n), ...extra});
const draw = b => B.render([b], {self: 'automation'}).all().find(n => n.tagName === 'SECTION');
const body = s => s.find('tbody')[0].kids;

test('a compact table shows its first rows and one Show more button for the rest', () => {
  const s = draw(table('Once', 8, {compact: true, show: 5}));
  assert.ok(s.find('table')[0].className.split(' ').includes('compact'));
  assert.deepEqual(body(s).map(tr => tr.hidden), [false, false, false, false, false, true, true, true]);
  const [btn] = s.find('button', 'blk-show');
  assert.equal(btn.textContent, 'Show 3 more');
  btn.onclick();
  assert.ok(body(s).every(tr => !tr.hidden));
  assert.equal(s.find('button', 'blk-show').length, 0);
  // the next refresh of the page keeps every row open
  const again = draw(table('Once', 9, {compact: true, show: 5}));
  assert.ok(body(again).every(tr => !tr.hidden) && !again.find('button', 'blk-show').length);
});

test('a table that fits, or one without show, has no button and no hidden row', () => {
  for (const b of [table('Repeating', 5, {show: 5}), table('Plain', 12)]) {
    const s = draw(b);
    assert.ok(body(s).every(tr => !tr.hidden));
    assert.equal(s.find('button', 'blk-show').length, 0);
    assert.ok(!s.find('table')[0].className.split(' ').includes('compact'));
  }
});

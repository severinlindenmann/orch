'use strict';
// W-051, O-25 (owner 28 Nov): in a page area under 900 px (beside the Focus panel, or a small window) a compact table
// with buttons or a switch, and a compact list, are drawn as the master's short rows: the name, one quiet line, the
// buttons and the switch always in view. A wide page and a phone-width window keep their own forms.
const test = require('node:test');
const assert = require('node:assert/strict');

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
  remove() { if (this.parent) this.parent.kids = this.parent.kids.filter(k => k !== this); }
  get childNodes() { return this.kids; }
  all() { return this.kids.flatMap(k => [k, ...k.all()]); }
  find(tag, cls) { return this.all().filter(n => n.tagName === tag.toUpperCase() && (!cls || n.className.split(' ').includes(cls))); }
  cls(c) { return this.all().filter(n => n.className.split(' ').includes(c)); }
}
global.document = {createElement: t => new El(t), createElementNS: (_, t) => new El(t), createDocumentFragment: () => new El('#frag')};
global.location = {hash: '#addon/automation'};
global.matchMedia = () => ({matches: false});
// the window and the page area: the kit's UI.pageRoom answers for the area (widgets.js)
const room = {window: 1440, page: 1440};
global.window = {get innerWidth() { return room.window; }, UI: {pageRoom: Object.assign(() => room.page, {under: px => room.window < px || room.page < px})}};
const B = require('../src/orch_dashboard/web/blocks.js');
const at = (w, page) => { room.window = w; room.page = page ?? w; };

const act = (verb, id) => ({op: 'addon.act', args: {verb, target: id}});
const repeat = (i, name) => ({
  cells: {schedule: name, repeats: 'Every 5 minutes', next: 'Sat 28 Nov, 11:45 CET', last: 'Done · Sat 03:20'},
  link: 't_repeat000' + i, subtitle: 'Starts a helper',
  toggle: {on: i !== 2, label: name + ' on or off', text: 'Repeats', action: act('toggle', 't_repeat000' + i)},
  actions: [{label: 'Start now', action: act('run', 't_repeat000' + i)}, {label: 'Edit', action: {op: 'addon.edit', args: {target: 't_repeat000' + i}}}],
});
const LONG = 'Relay and publish: admin private-only guarantee and scheduled end-to-end checks for every workspace';
const repeating = extra => ({type: 'table', title: 'Repeating', meta: '3', compact: true, show: 5, columns: [
  {key: 'schedule', label: 'Ticket', type: 'text'}, {key: 'repeats', label: 'Plan', type: 'text'},
  {key: 'next', label: 'Next time', type: 'text'}, {key: 'last', label: 'Last time', type: 'text'}],
  rows: [repeat(1, 'Role: script roles'), repeat(2, LONG), repeat(3, 'Role: unblock stuck merges')], ...extra});
const draw = (b, o) => B.render([b], {self: 'automation', ...o}).all().find(n => n.tagName === 'SECTION');

test('W-051: beside the Focus panel each repeat is a two-line row with its buttons and its switch', () => {
  for (const [w, page] of [[1440, 617], [1440, 785], [1920, 880], [1024, 960 - 64], [768, 700]]) {
    at(w, page);
    const s = draw(repeating());
    assert.equal(s.find('table').length, 0, `no squeezed table at ${w}/${page}`);
    const rows = s.cls('short-row');
    assert.equal(rows.length, 3);
    const [, long] = rows;
    const title = long.cls('short-title')[0];
    assert.equal(title.textContent, LONG);
    assert.equal(title.attrs.href, '#ticket/t_repeat0002', 'the name opens the ticket');
    // the second line: the plan, then the next and the last time with their names; "Last time" is last, so it is what "…" drops first
    assert.equal(long.cls('short-fact')[0].textContent, 'Every 5 minutes · Next time: Sat 28 Nov, 11:45 CET · Last time: Done · Sat 03:20 · Starts a helper');
    const side = long.cls('short-side')[0];
    assert.deepEqual(side.find('button').map(x => x.textContent || x.attrs['aria-label']), ['Start now', 'Edit', LONG + ' on or off']);
    const sw = side.find('button', 'switch')[0];
    assert.equal(sw.attrs['aria-checked'], 'false');
    assert.equal(sw.dataset.verb, 'toggle');
    assert.equal(side.find('button')[1].dataset.addonEdit, 't_repeat0002', 'Edit opens the same dialog as in the table');
  }
});

test('W-051: a wide page keeps the table, and a phone-width window keeps its card form of the table', () => {
  for (const [w, page] of [[1440, 1208], [1920, 1100], [1280, 1048], [900, 900], [390, 390], [320, 320], [720, 700]]) {
    at(w, page);
    const s = draw(repeating());
    assert.equal(s.find('table').length, 1, `table at ${w}/${page}`);
    assert.equal(s.cls('short-row').length, 0);
  }
});

test('W-051: Show more works in the narrow form and stays open over a repaint; a table without buttons stays a table', () => {
  at(1440, 617);
  const many = {...repeating(), title: 'Many repeats', show: 2};
  const s = draw(many);
  assert.deepEqual(s.cls('short-row').map(r => r.hidden), [false, false, true]);
  const [btn] = s.find('button', 'blk-show');
  assert.equal(btn.textContent, 'Show 1 more');
  btn.onclick();
  assert.ok(s.cls('short-row').every(r => !r.hidden));
  assert.ok(draw(many).cls('short-row').every(r => !r.hidden));
  const plain = {type: 'table', title: 'By role', compact: true, columns: [{key: 'role', label: 'Role', type: 'text'}, {key: 'runs', label: 'Runs', type: 'text'}], rows: [{cells: {role: 'Reviewer', runs: '4'}}]};
  assert.equal(draw(plain).find('table').length, 1);
  // a table with tabs keeps its tabs (they hide table rows)
  assert.equal(draw({...repeating(), filter: 'repeats'}).find('table').length, 1);
});

const shared = {type: 'list', title: 'Shared now', meta: '1 link', compact: true, more: 0, items: [{
  title: 'ace-report', subtitle: 'No note', meta: [' ', 'Ends in 23 days'],
  actions: [{label: 'Copy link', action: {op: 'link.copy', args: {id: 'f_abc123'}}}, {label: 'Extend', action: {op: 'link.extend', args: {id: 'f_abc123'}}}, {label: 'Stop sharing', action: {op: 'link.stop', args: {id: 'f_abc123'}}}],
}, {title: 'old-plan.pdf', subtitle: '“for the board”', meta: ['MAR-1 Spring campaign'], chips: [{label: 'Ends tomorrow', tone: 'warn'}], actions: []}]};

test('O-25: beside the Focus panel a shared file is its name, one quiet line and a line of whole buttons', () => {
  for (const [w, page] of [[1440, 617], [1440, 785], [800, 736]]) {
    at(w, page);
    const s = draw(shared, {links: true});
    assert.equal(s.cls('compact-row').length, 0, 'not the four-column row, whose buttons were one letter wide');
    const rows = s.cls('short-row');
    assert.equal(rows.length, 2);
    assert.equal(rows[0].attrs.role, 'listitem');
    assert.equal(rows[0].cls('short-title')[0].textContent, 'ace-report');
    assert.equal(rows[0].cls('short-fact')[0].textContent, 'No note · Ends in 23 days');
    // the buttons sit under the text in the master's wrapping row, never beside the name
    const below = rows[0].cls('grow')[0].kids.at(-1);
    assert.equal(below.className, 'row');
    assert.deepEqual(below.find('button').map(x => x.textContent), ['Open', 'Copy link', 'Extend', 'Stop sharing']);
    assert.deepEqual(below.find('button').map(x => x.dataset.native), ['link-open', 'link-copy', 'link-extend', 'link-stop']);
    assert.equal(rows[0].cls('short-side').length, 0);
    // a link that ends soon keeps its marked pill at the right of the name
    assert.equal(rows[1].cls('short-side')[0].textContent, 'Ends tomorrow');
    assert.equal(rows[1].cls('short-fact')[0].textContent, '“for the board” · MAR-1 Spring campaign');
  }
});

test('O-25: a wide page and a phone keep the compact row; an empty list keeps its empty state at every width', () => {
  for (const [w, page] of [[1440, 1208], [1280, 1048], [390, 390], [320, 320]]) {
    at(w, page);
    const s = draw(shared, {links: true});
    assert.equal(s.cls('compact-row').length, 2);
    assert.equal(s.cls('short-row').length, 0);
  }
  at(1440, 617);
  const empty = B.render([{...shared, items: [], empty: {title: 'No shared links', text: 'Share a file to create a private link.'}}], {self: 'publish'});
  assert.equal(empty.cls('short-row').length, 0);
  assert.match(empty.textContent, /No shared links/);
});

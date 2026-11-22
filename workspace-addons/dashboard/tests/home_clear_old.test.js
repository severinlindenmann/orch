'use strict';
// Owner decision 16 Nov (fwd-home): "Clear old" dismisses the questions older than a week in one click, with Undo.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const read = f => fs.readFileSync(path.join(WEB, f), 'utf8');
const helpers = require(path.join(WEB, 'helpers.js'));
const kit = {}; vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8'), vm.createContext({window:kit}));
const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false), dataset:{}, classList:{add(){}, remove(){}}}; n.append = (...c) => n.children.push(...c); n.setAttribute = (k, v) => { n.attrs[k] = v; }; n.addEventListener = () => {}; return n; };
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
function ctx(extra = {}) {
  const toasts = [], acts = [];
  const c = {h, window:{DashHelpers:helpers, UI:kit.UI, orch:{toast:(...a) => toasts.push(a)}}, document:{addEventListener(){}, getElementById:() => null}, addEventListener(){}, array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:String,
    name:v => String(v || '').replace(/^(human|agent):/, ''), capitalise:v => v, snapshot:false, locks:new Set(), localStorage:{getItem:() => null, setItem(){}}, state:{settings:{}, runs:{}, services:[]}, setTimeout, clearTimeout,
    el:(tag, cls, t) => h(tag, {className:cls}, t), fragment:(...k) => h('fragment', {}, k), card:(key, title, suffix, kids) => h('section', {'data-key':key, className:'card'}, title, suffix, kids), emptyRow:t => h('p', {}, t),
    button:(label, cls, fn) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = fn; return b; }, heading:(t, s) => h('header', {}, t, s), href:id => '#ticket/' + id, render(){}, time:v => kit.UI.stamp(v), parse:v => new Date(v), now:() => new Date('2026-11-16T12:00:00Z'), today:() => '2026-11-16',
    act:async (op, args) => { acts.push([op, args]); return {ok:true}; }, ...extra};
  c.toasts = toasts; c.acts = acts;
  vm.createContext(c); vm.runInContext(read('pages/ticket.js'), c); vm.runInContext(read('pages/home.js'), c); return c;
}
const q = (id, since) => ({id:'n' + id, ticket:'t' + id, since, title:'Q' + id, answer:{question:'q' + id, digest:'d' + id, options:['Yes', 'No']}});
const rows = () => [q(1, '2026-11-01T09:00:00Z'), q(2, '2026-11-02T09:00:00Z'), q(3, '2026-11-14T09:00:00Z'),
  {id:'a1', source:'sync', since:'2026-10-01T09:00:00Z', title:'Sync note', answer:{options:['Ok']}}];
const make = list => { const tickets = list.filter(r => r.ticket).map(r => ({id:r.ticket, title:'T ' + r.id, status:'waiting'}));
  const c = ctx({needsList:() => list, tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id)}); vm.runInContext('ANSWER_UNDO_MS = 20', c); return c; };
const wait = ms => new Promise(r => setTimeout(r, ms));

test('the button shows only with at least one question older than a week, never in a snapshot', () => {
  assert.ok(make(rows()).clearOldButton());
  assert.equal(make(rows().slice(2)).clearOldButton(), null);
  const c = make(rows()); vm.runInContext('snapshot = true', c);
  assert.equal(c.clearOldButton(), null);
  const b = make(rows()).clearOldButton();
  assert.match(b.attrs['aria-label'], /Dismiss the 2 questions older than a week/);
});
test('click hides the old rows with an Undo toast; Undo sends nothing', async () => {
  const c = make(rows());
  assert.equal(c.needsToday().needs.length, 4);
  c.clearOldButton().onclick();
  assert.equal(c.needsToday().needs.length, 2, 'old questions leave the count at once; new and add-on rows stay');
  assert.equal(c.toasts.at(-1)[0], 'Cleared 2 old questions');
  c.toasts.at(-1)[2]();
  assert.equal(c.needsToday().needs.length, 4);
  await wait(60);
  assert.equal(c.acts.length, 0);
});
test('after the Undo window one answer per old question is sent with the fixed text', async () => {
  const c = make(rows());
  c.clearOldButton().onclick();
  await wait(80);
  assert.deepEqual(c.acts.map(a => a[0]), ['answer', 'answer']);
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts.map(a => a[1]))), [
    {ticket:'t1', question:'q1', digest:'d1', answer:'Dismissed: older than a week'},
    {ticket:'t2', question:'q2', digest:'d2', answer:'Dismissed: older than a week'}]);
});
test('a failure shows one error toast with the counts', async () => {
  const c = make(rows()); let n = 0;
  vm.runInContext('act = undefined', c);
  c.act = async () => (++n === 1 ? {ok:true} : {ok:false, status:400, text:'No'});
  c.clearOldButton().onclick();
  await wait(80);
  assert.match(String(c.toasts.at(-1)[0]), /^Cleared 1 of 2 old questions\./);
  assert.equal(c.toasts.at(-1)[1], 'error');
});

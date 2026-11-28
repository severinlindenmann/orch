'use strict';
// ORCH-2431: a parked ticket asks nothing on Home; "Not now" on a question parks its ticket, the parked line lists
// what is parked with the reason, and Bring back returns it.
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
const text = n => typeof n === 'string' || typeof n === 'number' ? String(n) : n && typeof n === 'object' ? (n.children || []).map(text).join('') : '';
function ctx(extra = {}) {
  const c = {h, window:{DashHelpers:helpers, UI:kit.UI, orch:{toast(){}}}, document:{addEventListener(){}, getElementById:() => null}, addEventListener(){}, array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:String,
    name:v => String(v || '').replace(/^(human|agent):/, ''), capitalise:v => v, snapshot:false, locks:new Set(), localStorage:{getItem:() => null, setItem(){}}, state:{settings:{}, runs:{}, services:[]}, setTimeout, clearTimeout,
    el:(tag, cls, t) => h(tag, {className:cls}, t), fragment:(...k) => h('fragment', {}, k), card:(key, title, suffix, kids) => h('section', {'data-key':key, className:'card'}, title, suffix, kids), emptyRow:t => h('p', {}, t),
    button:(label, cls, fn) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = fn; return b; }, heading:(t, s) => h('header', {}, t, s), href:id => '#ticket/' + id, render(){}, time:v => kit.UI.stamp(v), parse:v => new Date(v), now:() => new Date('2026-11-28T12:00:00Z'), today:() => '2026-11-28',
    act:async () => ({ok:true}), ...extra};
  vm.createContext(c); vm.runInContext(read('pages/ticket.js'), c); vm.runInContext(read('pages/home.js'), c); return c;
}
const row = {id:'core:q:t1:q1', source:'core', kind:'question', ticket:'t1', since:'2026-11-27T09:00:00Z', title:'Try it', text:'Did it work?', answer:{question:'q1', digest:'d1', options:['Yes', 'No']}};
const T = (id, more = {}) => ({id, key:'DM-' + id.slice(1), title:'Ticket ' + id, status:'waiting', questions:[], ...more});
function make(tickets, extra = {}, state = {}) {
  const c = ctx({needsList:() => extra.needs || [], tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id), ...extra});
  Object.assign(c.state, state);
  return c;
}

test('the question card on Home has a quiet "Not now" that asks until when for its ticket', () => {
  const asked = [], t1 = T('t1', {questions:[{id:'q1', text:'Did it work?', answer:null}]});
  const c = make([t1], {askNotNow:t => asked.push(t.id)});
  const now = nodes(c.needRow(row, row.id)).filter(n => n.tag === 'button' && text(n) === 'Not now');
  assert.equal(now.length, 1);
  assert.match(now[0].attrs.className, /quiet/);
  now[0].onclick();
  assert.deepEqual(asked, ['t1']);
  const snap = make([t1], {askNotNow() {}}); vm.runInContext('snapshot = true', snap);
  assert.equal(nodes(snap.needRow(row, row.id)).filter(n => text(n) === 'Not now' && n.tag === 'button').length, 0, 'a read-only copy offers nothing');
});

test('the parked line: one quiet row, Show lists each ticket with its reason and Bring back', () => {
  const back = [], tickets = [T('t1'), T('t2', {status:'open'})];
  const parked = [{ticket:'t1', key:'DM-1', title:'Ticket t1', kind:'external', reason:'Until you bring it back', questions:1, cli:'orch ticket wait DM-1 --clear'},
    {ticket:'t2', key:'DM-2', title:'Ticket t2', kind:'backlog', reason:'In Backlog', questions:2, cli:'orch ticket status DM-2 ready'},
    {ticket:'gone', key:'DM-9', title:'Not on this page', kind:'external', reason:'Until you bring it back', questions:0}];
  const c = make(tickets, {bringBack:t => back.push(t.id)}, {parked});
  const list = c.parkedList();
  assert.deepEqual(list.map(r => r.ticket), ['t1', 't2'], 'only tickets the page holds');
  const line = c.parkedLine(list);
  assert.equal(line.attrs['data-key'], 'needs-parked');
  assert.match(text(line), /^2 parked, they ask nothing until they come back/);
  assert.match(text(c.parkedLine(list.slice(0, 1))), /^1 parked, it asks nothing until it comes back/);
  const r1 = c.parkedRow(list[0]), r2 = c.parkedRow(list[1]);
  assert.match(text(r1), /Ticket t1/);
  assert.match(text(r1), /Until you bring it back · 1 question kept/);
  assert.match(text(r2), /In Backlog · 2 questions kept/);
  assert.equal(r1.attrs['data-counts'], '0', 'a parked row is never part of the number');
  nodes(r1).find(n => n.tag === 'button' && text(n) === 'Bring back').onclick();
  nodes(r2).find(n => n.tag === 'button' && text(n) === 'Bring back').onclick();
  assert.deepEqual(back, ['t1', 't2']);
});

test('a parked ticket gives no row of Home\'s own either (finished work to bring back)', () => {
  const change = {bring_back:{state:'waiting'}};
  const tickets = [T('t1', change), T('t2', {status:'open', ...change}), T('t3', {status:'active', ...change})];
  const c = make(tickets, {}, {parked:[{ticket:'t1', kind:'external', reason:'Until you bring it back', questions:0}]});
  assert.deepEqual(c.needsToday().changes.map(t => t.id), ['t3']);
  assert.equal(c.isParked(tickets[0]) && c.isParked(tickets[1]) && !c.isParked(tickets[2]), true);
});

// tickets.js needs the whole page around it: its two small functions are read from the file and run with a stub
function fromTickets(name, stubs) {
  const src = read('pages/tickets.js'), at = src.indexOf('function ' + name + '(');
  assert.ok(at > 0, name);
  let depth = 0, end = at;
  for (let i = src.indexOf('{', at); i < src.length; i++) { if (src[i] === '{') depth++; if (src[i] === '}' && --depth === 0) { end = i + 1; break; } }
  const c = vm.createContext({array:v => Array.isArray(v) ? v : [], ...stubs});
  vm.runInContext(src.slice(at, end), c);
  return c[name];
}

test('Bring back: Backlog goes to To do, a kept question is waited on again, else the ticket goes on', () => {
  const moves = [], bringBack = fromTickets('bringBack', {moveTicket:(...a) => { moves.push(JSON.parse(JSON.stringify(a))); }});
  bringBack({id:'t1', status:'open', questions:[{id:'q1', answer:null}]});
  bringBack({id:'t2', status:'waiting', questions:[{id:'q1', answer:'Yes'}, {id:'q2', answer:null}]});
  bringBack({id:'t3', status:'waiting', questions:[]});
  assert.deepEqual(moves, [['t1', 'ready'], ['t2', 'waiting', false, {data:{waiting_on:{kind:'question', ref:'q2'}}}], ['t3', 'active']]);
});

test('Not now parks with one click: a day, or until the person brings it back', () => {
  const moves = [], made = [];
  const el = (tag, attrs = {}, ...kids) => { const n = h(tag, attrs, ...kids); made.push(n); return n; };
  const d = {append(){}, showModal(){}};
  const at = new Date('2026-11-29T09:00:00');
  const askNotNow = fromTickets('askNotNow', {h:el, snapshot:false, NOT_NOW:'Not now', clean:String, window:{orch:{close(){}}, UI:null}, dialog:() => ({d, actions:{append(){}}}),
    waitChoices:() => [['Tomorrow', at]], utcStamp:x => x.toISOString().replace(/\.\d{3}Z$/, 'Z'),
    button:(label, cls, fn) => { const b = el('button', {className:cls}, label); b.onclick = fn; return b; }, moveTicket:(...a) => { moves.push(JSON.parse(JSON.stringify(a))); }});
  askNotNow({id:'t1', title:'Try it'});
  made.find(n => n.tag === 'button' && text(n) === 'Tomorrow').onclick();
  made.find(n => n.tag === 'button' && text(n) === 'When I bring it back').onclick();
  const until = at.toISOString().replace(/\.\d{3}Z$/, 'Z');
  assert.deepEqual(moves, [['t1', 'waiting', false, {data:{waiting_on:{kind:'time', until, ref:'Not now'}}}],
    ['t1', 'waiting', false, {data:{waiting_on:{kind:'external', ref:'Not now'}}}]]);
});

test('Review: only a ticket\'s own question card offers Not now', () => {
  const src = read('pages/review.js'), at = src.indexOf('function reviewNotNow('), end = src.indexOf('\n}\n', at) + 2;
  const asked = [], tickets = [{id:'t1'}];
  const c = vm.createContext({ticketOf:id => tickets.find(t => t.id === id), askNotNow:t => asked.push(t.id)});
  vm.runInContext(src.slice(at, end), c);
  assert.equal(c.reviewNotNow({id:'core:check:t1', ticketId:'t1'}), null, 'a result to check');
  assert.equal(c.reviewNotNow({id:'core:q:t9:q1', ticketId:'t9'}), null, 'a ticket this page does not hold');
  c.reviewNotNow({id:'core:q:t1:q1', ticketId:'t1'})();
  assert.deepEqual(asked, ['t1']);
  assert.match(src, /notNow:snapshot \? undefined : reviewNotNow/);
});

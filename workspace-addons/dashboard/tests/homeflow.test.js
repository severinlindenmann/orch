'use strict';
// Owner feedback 14 Nov (sweep d-home-answer, fb23): an answered question leaves at once with a toast "Answered · Undo"
// (the answer is sent after the Undo window), the badge counts down, and "What changed" replaces the Notes page.
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
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
function ctx(extra = {}) {
  const toasts = [], acts = [];
  const c = {h, window:{DashHelpers:helpers, UI:kit.UI, orch:{toast:(...a) => toasts.push(a)}}, document:{addEventListener(){}, getElementById:() => null}, addEventListener(){}, array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:String,
    name:v => String(v || '').replace(/^(human|agent):/, ''), capitalise:v => v, snapshot:false, locks:new Set(), localStorage:{getItem:() => null, setItem(){}}, state:{settings:{}, runs:{}, services:[]}, setTimeout, clearTimeout,
    el:(tag, cls, t) => h(tag, {className:cls}, t), fragment:(...k) => h('fragment', {}, k), card:(key, title, suffix, kids) => h('section', {'data-key':key, className:'card'}, title, suffix, kids), emptyRow:t => h('p', {}, t),
    button:(label, cls, fn) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = fn; return b; }, heading:(t, s) => h('header', {}, t, s), href:id => '#ticket/' + id, render(){}, time:v => kit.UI.stamp(v), parse:v => new Date(v), now:() => new Date('2026-11-14T12:00:00Z'), today:() => '2026-11-14',
    act:async (op, args) => { acts.push([op, args]); return {ok:true}; }, ...extra};
  c.toasts = toasts; c.acts = acts;
  vm.createContext(c); vm.runInContext(read('pages/ticket.js'), c); vm.runInContext(read('pages/home.js'), c); return c;
}
const done = (id, title, at, note, by = 'agent:claude') => ({id, title, status:'done', done_at:at, history:[{at, by, text:'Status review -> done'}],
  checklist:[{id:'c1', text:'Do it', done:true, evidence:[{type:'note', summary:note, text:'', at}]}]});
test('"What changed" lists finished tickets with their completion note, newest first, at most 5', () => {
  const tickets = [done('a', 'Order paper cups', '2026-11-12T17:10:00Z', 'Ordered 500 cups.'), done('b', 'Set up the shop email', '2026-11-13T09:02:00Z', 'Created shop@ and forwarded it.'),
    {id:'c', title:'No note', status:'done', done_at:'2026-11-13T10:00:00Z', checklist:[]}, {id:'d', title:'Still open', status:'open'},
    ...['e', 'f', 'g', 'h', 'i'].map((id, i) => done(id, 'Old ' + id, '2026-11-0' + (i + 1) + 'T10:00:00Z', 'Done ' + id))];
  const c = ctx({tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id)});
  const list = c.changedList(tickets);
  assert.equal(list.length, 5);
  assert.deepEqual(list.slice(0, 2).map(x => x.t.id), ['b', 'a']);
  assert.ok(!list.some(x => x.t.id === 'c' || x.t.id === 'd'), 'no note, no row; open tickets never');
  const card = c.whatChangedCard(list);
  assert.match(text(card), /What changed/);
  assert.match(text(card), /Set up the shop email/);
  assert.match(text(card), /Created shop@ and forwarded it\./);
  assert.match(text(card), /Helper|Claude/);
  assert.equal(c.whatChangedCard([]), null);
});
test('the Notes page is gone: old note links land on Home', () => {
  const app = read('app.js');
  assert.doesNotMatch(app, /notesPage|notePage/);
  assert.ok(!fs.existsSync(path.join(WEB, 'pages/notes.js')));
  assert.doesNotMatch(read('index.html'), /notes\.(js|css)/);
});
test('an answered question leaves at once, the count drops, the answer goes after the Undo window, Undo brings it back', async () => {
  const rows = [{id:'n1', ticket:'t1', since:'2026-11-14T09:00:00Z', title:'Which logo?', answer:{question:'q1', digest:'d', options:['Blue', 'Green']}},
    {id:'n2', ticket:'t2', since:'2026-11-14T10:00:00Z', title:'Everyone or the team?', answer:{question:'q2', digest:'e', options:['Everyone', 'Team']}}];
  const tickets = [{id:'t1', title:'Newsletter', status:'waiting', questions:[{id:'q1', text:'Which logo?'}]}, {id:'t2', title:'Survey', status:'waiting', questions:[{id:'q2', text:'Everyone or the team?'}]}];
  const c = ctx({needsList:() => rows, tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id)});
  vm.runInContext('ANSWER_UNDO_MS = 20', c);
  assert.equal(c.needsToday().count, 2);
  const host = h('div', {'data-need-row':'n1'});
  host.querySelectorAll = () => []; host.classList = {add(cls) { host.out = cls; }, remove(){}};
  const first = nodes(c.needRow(rows[0], 'n1')).find(n => /(^| )answer-option( |$)/.test(n.attrs.className || ''));
  await first.onclick({currentTarget:{closest:() => host}});
  assert.equal(host.out, 'row-out', 'the card leaves with the master row-out motion');
  assert.equal(c.needsToday().count, 1, 'the badge counts down at once');
  assert.equal(c.acts.length, 0, 'nothing is sent inside the Undo window');
  assert.match(String(c.toasts.at(-1)[0]), /^Answered · /);
  assert.equal(typeof c.toasts.at(-1)[2], 'function', 'the toast has Undo');
  c.toasts.at(-1)[2]();
  assert.equal(c.needsToday().count, 2, 'Undo brings the question back');
  await new Promise(r => setTimeout(r, 60));
  assert.equal(c.acts.length, 0, 'an undone answer is never sent');
  const second = nodes(c.needRow(rows[0], 'n1')).find(n => /(^| )answer-option( |$)/.test(n.attrs.className || ''));
  await second.onclick({currentTarget:{closest:() => host}});
  await new Promise(r => setTimeout(r, 80));
  assert.deepEqual(c.acts.map(a => a[0]), ['answer']);
  assert.equal(c.acts[0][1].answer, 'Blue');
});

test('G2: a quiet Working ticket is one "No news since" row on Home, never a need', () => {
  const at = new Date(2026, 10, 15, 9, 20), t = {id:'q', title:'Order cups', status:'active', quiet_since:at.toISOString()};
  const c = ctx({now:() => new Date(2026, 10, 15, 20, 0), tickets:() => [t], ticketOf:() => t});
  assert.match(text(c.quietRow(t)), /^No news since 09:20: Order cups$/);
  const home = read('pages/home.js');
  assert.match(home, /card\('quiet-now'/);
  assert.ok(!/quiet/.test(home.slice(home.indexOf('function needsToday'), home.indexOf('function needsYouTotal'))), 'not counted as needing you');
  for (const f of ['pages/tickets.js', 'pages/ticket.js']) assert.match(read(f), /quietWords\(t\.quiet_since/, f + ' shows No news since');
});
test('"What changed" shows at most about 3 plain lines per ticket, never commit ids, file or test names (ORCH-407)', () => {
  const c = ctx({tickets:() => [], ticketOf:() => null});
  // the summaries of report r-1118-0544 as the owner saw them
  const s384 = "Merged on green CI: 28 of 28 click-throughs, 84 of 84 features, in their own CI job; dashboard tests 706 pass. Merged by the owner's Merge click (workflow file change), merge commit 11e55282. Local: full click-through run 28/28, node dashboard tests 706/706, dashboard pytest (touched files) 171 passed.";
  const s399 = 'The report holds no contacts line (0 matches in timeline.jsonl); its window shows only CLI commands. Cause, already worked out in issue 1408: data._run_orch passes the server environment through unchanged. Relay on or off makes no difference. Fix: run the person-only reads with orch.adapters.human_environ. Check that would have caught it: a dashboard test (added in PR 1410, test_chat_data.py -k person_chat).';
  const s390 = 'Merged into develop on green CI; the clock check now runs on every pull request touching workspace or add-ons. Merged 2026-11-18 04:02 UTC as c1fdc5e9 by the owner\'s Merge click (q2; workflow file change). Last CI run 44232803104 green incl. both clock jobs. Local: factory suite 296 passed, sync test_act passed (isolated home).';
  for (const s of [s384, s399, s390]) {
    const out = c.plainChanged(s);
    assert.ok(out.length <= 201, out);
    assert.doesNotMatch(out, /11e55282|c1fdc5e9|\.jsonl|\.py|_run_orch|human_environ|-k /, out);
    assert.ok(out.length > 0);
  }
  assert.match(c.plainChanged(s390), /^Merged into develop on green CI; the clock check now runs on every pull request/);
  assert.equal(c.plainChanged(s399), 'Relay on or off makes no difference.');
  assert.equal(c.plainChanged('Ordered 500 cups.'), 'Ordered 500 cups.');
  assert.match(c.plainChanged('Fixed data._run_orch in server.py ' + 'and more words '.repeat(30)), /…$/);  // nothing plain: the first sentence, cut short
  assert.equal(c.plainChanged(''), '');
});
test('the top bar "longest wait" is the age of the same needs the number counts, never a dropped ticket\'s old question (ORCH-407)', () => {
  // report r-1118-0544: one result to check, minutes old, but "longest wait 19 h ago" from questions on dropped tickets
  const tickets = [{id:'d1', title:'Dropped long ago', status:'dropped', updated_at:'2026-11-13T17:00:00Z', questions:[{id:'q1', text:'Old?', answer:null}]},
    {id:'r1', title:'Keep develop checks running', status:'review', updated_at:'2026-11-14T11:55:00Z'}];
  const c = ctx({needsList:() => [], tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id)});
  assert.equal(c.needsToday().count, 1);
  assert.equal(c.needsOldestAt(), Date.parse('2026-11-14T11:55:00Z'));
  const rows = [{id:'n1', ticket:'w1', since:'2026-11-14T09:00:00Z', title:'Which logo?', answer:{question:'q2', digest:'d', options:['A', 'B']}}];
  const withQ = [...tickets, {id:'w1', title:'Newsletter', status:'waiting', questions:[{id:'q2', text:'Which logo?'}]}];
  const c2 = ctx({needsList:() => rows, tickets:() => withQ, ticketOf:id => withQ.find(t => t.id === id)});
  assert.equal(c2.needsOldestAt(), Date.parse('2026-11-14T09:00:00Z'));  // the question, asked first
  assert.equal(ctx({needsList:() => [], tickets:() => [], ticketOf:() => null}).needsOldestAt(), null);
  assert.match(read('app.js'), /needsOldestAt\(\)/);
});
test('"What changed" says a head the note repeats once and ends a head with a full stop (ORCH-407)', () => {
  const c = ctx({tickets:() => [], ticketOf:() => null});
  assert.equal(c.changedText({head:'Merged on green CI', detail:'Merged on green CI: 28 of 28.'}), 'Merged on green CI: 28 of 28.');
  assert.equal(c.changedText({head:'Menu written', detail:'Three dishes.'}), 'Menu written. Three dishes.');
  assert.equal(c.changedText({head:'Menu written.', detail:''}), 'Menu written.');
});

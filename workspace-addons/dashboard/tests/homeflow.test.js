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

test('G2: a quiet Working ticket is one "Quiet since" row on Home, never a need', () => {
  const at = new Date(2026, 10, 15, 9, 20), t = {id:'q', title:'Order cups', status:'active', quiet_since:at.toISOString()};
  const c = ctx({now:() => new Date(2026, 10, 15, 20, 0), tickets:() => [t], ticketOf:() => t});
  assert.match(text(c.quietRow(t)), /^Quiet since 09:20: Order cups$/);
  const home = read('pages/home.js');
  assert.match(home, /card\('quiet-now'/);
  assert.match(home, /quiet = working\.filter\(t => t\.quiet_since && !helperIds\.has\(t\.id\)\)/, 'a helper row is never also a Quiet row');
  assert.ok(!/quiet/.test(home.slice(home.indexOf('function needsToday'), home.indexOf('function needsYouTotal'))), 'not counted as needing you');
  for (const f of ['pages/tickets.js', 'pages/ticket.js']) assert.match(read(f), /quietWords\(t\.quiet_since/, f + ' shows Quiet since');
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
test('"What changed" says a head the note repeats once and ends a head with a full stop (ORCH-407)', () => {
  const c = ctx({tickets:() => [], ticketOf:() => null});
  assert.equal(c.changedText({head:'Merged on green CI', detail:'Merged on green CI: 28 of 28.'}), 'Merged on green CI: 28 of 28.');
  assert.equal(c.changedText({head:'Menu written', detail:'Three dishes.'}), 'Menu written. Three dishes.');
  assert.equal(c.changedText({head:'Menu written.', detail:''}), 'Menu written.');
});
test('wait words read right: "1 day" not "1 days", the top bar has no "ago", a time wait is "Waiting until" (ORCH-1465)', () => {
  const now = Date.parse('2026-11-22T06:00:00Z');
  assert.equal(helpers.ago('2026-11-21T06:00:00Z', now), '1 day ago');
  assert.equal(helpers.ago('2026-11-19T06:00:00Z', now), '3 days ago');
});
// ORCH-1849: Home names each finished ticket once, its result right under the title; Needs you stays first.
test('home: a ticket finished today is in Finished once with its result, never again in What changed; Needs you comes first', () => {
  const rows = [{id:'n1', ticket:'sup', since:'2026-11-14T09:00:00Z', title:'Which day?', answer:{question:'q1', digest:'d', options:['Tuesday', 'Thursday']}}];
  const sup = {id:'sup', key:'PIL-2', title:'Answer the supplier', status:'waiting', questions:[{id:'q1', text:'The supplier can deliver on Tuesday or Thursday. Which day?'}]};
  const report = {...done('rep', 'Monthly sales report', '2026-11-14T10:38:00Z', 'Sales up 8% on September.'), key:'PIL-3'};
  report.checklist[0].evidence[0].text = 'From the shop export.';
  const twin = {id:'twin', key:'PIL-7', title:'Monthly sales report', status:'done', done_at:'2026-11-14T11:00:00Z', checklist:[]};
  const old = {...done('old', 'Order paper cups', '2026-11-12T17:10:00Z', 'Ordered 500 cups.'), key:'PIL-1'};
  const tickets = [sup, report, twin, old];
  const c = ctx({needsList:() => rows, tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id), titleTag:() => null, sorted:v => v, shown:t => t, questions:t => t.questions || []});
  const page = c.home(), all = text(page);
  const fin = nodes(page).find(n => n.attrs?.['data-key'] === 'finished-today');
  assert.ok(all.indexOf('Which day?') > -1 || all.indexOf('Tuesday') > -1);
  assert.ok(all.indexOf('Tuesday') < all.indexOf(text(fin)), 'the question comes before Finished');
  assert.match(text(nodes(fin).find(n => n.attrs?.['data-key'] === 'ticket-rep')), /PIL-3.*Monthly sales report.*Sales up 8% on September\. From the shop export\..*Finished/);
  const twinRow = text(nodes(fin).find(n => n.attrs?.['data-key'] === 'ticket-twin'));
  assert.match(twinRow, /PIL-7.*No result written yet/, 'the same title on another ticket is its own row, its missing result said plainly');
  assert.doesNotMatch(twinRow, /Sales up/);
  assert.equal(all.split('Sales up 8%').length - 1, 1, 'the result is said once on Home');
  const changed = nodes(page).find(n => n.attrs?.['data-key'] === 'what-changed');
  assert.match(text(changed), /Ordered 500 cups\./, 'earlier results stay in What changed');
  assert.doesNotMatch(text(changed), /Monthly sales report/);
  assert.ok(!nodes(fin).some(n => n.attrs?.['data-key'] === 'finished-done'), 'What changed keeps the Done tickets link');
  // a result written after the ticket was finished shows on the next drawing
  twin.outcome = {changed:'Sent to the board on Friday.'};
  const later = text(nodes(c.home()).find(n => n.attrs?.['data-key'] === 'finished-today'));
  assert.match(later, /PIL-7.*Sent to the board on Friday\./); assert.doesNotMatch(later, /No result written/);
});
test('home: with every result from today Finished keeps the Done tickets link; many finished today show 5 and one link', () => {
  const at = i => new Date(Date.parse('2026-11-14T11:00:00Z') - i * 60000).toISOString();
  const many = Array.from({length:7}, (_, i) => ({...done('d' + i, 'Done ' + i, at(i), 'Result ' + i + '.'), key:'PIL-' + (10 + i)}));
  const ws = [{id:'w', title:'Plan', status:'active'}];
  const draw = list => { const c = ctx({needsList:() => [], tickets:() => list, ticketOf:id => list.find(t => t.id === id), titleTag:() => null, sorted:v => v, shown:t => t, questions:() => []}); return c.home(); };
  const one = draw([...ws, many[0]]), fin1 = nodes(one).find(n => n.attrs?.['data-key'] === 'finished-today');
  assert.ok(!nodes(one).some(n => n.attrs?.['data-key'] === 'what-changed'));
  assert.ok(nodes(fin1).some(n => n.attrs?.['data-key'] === 'finished-done' && /Done tickets/.test(text(n))));
  const lots = draw([...ws, ...many]), fin = nodes(lots).find(n => n.attrs?.['data-key'] === 'finished-today');
  assert.equal(nodes(fin).filter(n => /^finished-result-/.test(n.attrs?.['data-key'] || '')).length, 5);
  assert.match(text(fin), /All finished today \(7\)/);
  assert.ok(!nodes(lots).some(n => n.attrs?.['data-key'] === 'what-changed'), 'the 6th and 7th stay behind the link, not repeated below');
  const none = draw(ws), fin0 = text(nodes(none).find(n => n.attrs?.['data-key'] === 'finished-today'));
  assert.match(fin0, /Nothing finished yet\./); assert.doesNotMatch(fin0, /Done tickets/);
});
// ORCH-2023: Home names the agent stored on the question (asked with --by agent:copilot), never the chosen agent.
test('Needs you names who asked the question; unknown is Helper, not the chosen agent', () => {
  const settings = {agents:[{name:'claude', label:'Claude', chosen:true}]};
  const row = {id:'n1', ticket:'t1', since:'2026-11-14T09:00:00Z', title:'Which logo?', answer:{question:'q1', digest:'d', options:['Blue', 'Green']}};
  const asked = (q, runs = {}) => {
    const tickets = [{id:'t1', key:'KP-2', title:'Newsletter', status:'waiting', questions:[{id:'q1', text:'Which logo?', ...q}]}];
    const c = ctx({state:{settings, runs, services:[]}, needsList:() => [row], tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id)});
    return text(nodes(c.needRow(row, 'n1')).find(n => /question-context/.test(n.attrs.className || '')));
  };
  assert.match(asked({asked_by:'agent:copilot'}), /^Copilot asked/);
  assert.match(asked({asked_by:'agent:copilot'}, {t1:{claim:{agent:'claude'}}}), /^Copilot asked/, 'the question beats the run');
  assert.match(asked({}, {t1:{claim:{agent:'codex'}}}), /^Codex asked/, 'an older question: the agent of the run');
  assert.match(asked({}), /^Helper asked/, 'nothing known: never the chosen agent');
  assert.match(asked({asked_by:'human:anna'}), /^Helper asked/);
});

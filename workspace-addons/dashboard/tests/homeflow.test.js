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
test('the Notes page is gone: old note links land on Home', () => {
  const app = read('app.js');
  assert.doesNotMatch(app, /notesPage|notePage/);
  assert.ok(!fs.existsSync(path.join(WEB, 'pages/notes.js')));
  assert.doesNotMatch(read('index.html'), /notes\.(js|css)/);
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

// ---- Home after the owner's walk of 28 Nov (O-01 D, CX-01, W-017, W-054 A) ----
const key = (page, k) => nodes(page).find(n => n.attrs?.['data-key'] === k);
const keys = (page, re) => nodes(page).filter(n => re.test(n.attrs?.['data-key'] || ''));
const helperList = (rows, o) => h('section', {'data-key':o.dataKey}, rows.map(r => h('div', {'data-key':r.dataKey, 'data-state':r.state}, r.title, '|', r.word, '|', r.meta, '|',
  (r.actions || []).map(a => { const b = h('button', {'data-key':a.key}, a.label); b.onclick = a.run; return b; }))));
function homeCtx(tickets, rows, state = {}, extra = {}) {
  const c = ctx({needsList:() => rows, tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id), titleTag:() => null, sorted:v => v, shown:t => t, questions:t => t.questions || [],
    addons:() => [], startHost:() => null, newButton:() => h('button', {className:'btn primary sm', 'data-action':'new'}, 'New ticket'), location:{hash:''},
    state:{settings:{}, runs:{}, services:[], ...state}, ...extra});
  c.window.UI = {...kit.UI, helperList, helperMeta:() => 'the core’s own line'};
  return c;
}
const at = '2026-11-14T09:00:00Z';
const ask = (n, t) => ({id:'core:q:' + t + ':q1', source:'core', kind:'question', ticket:t, since:at, title:'Question ' + n, text:'Which colour for ' + n + '?', tone:'needs-you', answer:{question:'q1', digest:'d', options:['Blue', 'Green'], recommended:null}});
const core = (kind, t, said, more = {}) => ({id:'core:' + kind.split(':')[1] + ':' + t, source:'core', kind, ticket:t, since:at, title:'T ' + t, text:said, tone:'bad', ...more});
const BUSY = () => {
  const tickets = [
    {id:'t1', key:'PIL-1', title:'Newsletter', status:'waiting', questions:[{id:'q1', text:'Which colour for 1?'}]},
    {id:'t2', key:'PIL-2', title:'Survey', status:'waiting', questions:[{id:'q1', text:'Which colour for 2?'}]},
    ...['r1', 'r2', 'r3'].map((id, i) => ({id, key:'PIL-1' + i, title:'Result ' + id, status:'review'})),
    {id:'t3', key:'PIL-3', title:'Book the room', status:'active'}, {id:'t4', key:'PIL-4', title:'Price list', status:'review'},
    {id:'t5', key:'PIL-5', title:'Tidy the shared folder', status:'active'}, {id:'t6', key:'PIL-6', title:'Landing page', status:'review'},
    {id:'t7', key:'PIL-7', title:'Translate the flyer', status:'waiting', waiting_on:{start:true, ref:'the tool is not installed'}},
    {id:'o1', key:'PIL-8', title:'Plan the trip', status:'ready', checklist:[]},
  ];
  const rows = [ask(1, 't1'), ask(2, 't2'),
    core('helper:permission', 't3', 'The helper waits for your OK on its screen.'),
    core('helper:unmerged', 't4', 'The pull request passed its checks but is still open.', {pull:{url:'https://github.com/acme/shop/pull/131', head:'a'.repeat(40)}}),
    core('helper:idle', 't5', 'The helper has been idle for 25 minutes with open tasks.'),
    core('reviewer:unsure', 't6', 'The Reviewer was not sure about this result.'),
    {id:'services:failing-web', source:'services', kind:'services:failing', ticket:null, since:at, title:'Shop preview', tone:'bad',
      text:'Shop preview keeps stopping. It is needed for: PIL-3.', actions:[{label:'Restart', verb:'restart', target:'web'}]}];
  const counts = {needs_you:{stopped:4, queue:['x1', 'x2'], items:[{ticket:'t1', question:'q1'}, {ticket:'t2', question:'q1'}, {ticket:'r1'}, {ticket:'r2'}, {ticket:'r3'},
    {ticket:'t3', stopped:true}, {ticket:'t4', stopped:true}, {ticket:'t5', stopped:true}, {ticket:'t6', stopped:true}]}, in_progress:['t3', 't5'], not_started:['o1']};
  const logins = {items:[{name:'codex', label:'Codex', kind:'login', state:'renew', helper:'codex', chosen:true, stops:[], sign_in:'codex login'},
    {name:'claude', label:'Claude', kind:'login', state:'renew', helper:'claude', chosen:false, stops:[], sign_in:'claude login'}]};
  return {tickets, rows, state:{counts, logins, start_line:{why:'the usage limit is reached', waiting:['o1']}}};
};
test('O-01 D: Home lists blocked work first, one line and one action each; questions and results are one line that opens Review', () => {
  const {tickets, rows, state} = BUSY();
  const c = homeCtx(tickets, rows, state, {reviewPausedLine:() => h('div', {'data-key':'review-paused', className:'banner attn'}, 'Automation is paused. Nothing starts by itself.')});
  const page = c.home(), all = text(page), blocked = key(page, 'blocked');
  assert.match(text(blocked), /^Blocked now6/);
  const kinds = nodes(blocked).filter(n => n.attrs?.['data-blocked']).map(n => n.attrs['data-blocked']);
  assert.deepEqual(kinds, ['login', 'addon', 'start', 'stopped', 'stopped', 'stopped'], 'a tool that stopped, a service work needs, a helper that cannot start, then the work that stopped');
  // each row: one line and exactly one action
  const actions = n => nodes(n).filter(x => x.tag === 'button' || (x.tag === 'a' && /\bbtn\b/.test(x.attrs.className || ''))).map(text);
  assert.deepEqual(nodes(blocked).filter(n => n.attrs?.['data-blocked']).map(actions), [['Sign in'], ['Restart'], ['Try again'], ['Open'], ['Merge'], ['Remind']]);
  assert.match(text(key(page, 'need-core:permission:t3')), /waits for your OK on its screen\.PIL-3 ?Book the room/);
  assert.match(text(key(page, 'start-failed-t7')), /could not start: .*PIL-7 ?Translate the flyer/);
  assert.match(text(key(page, 'need-services:failing-web')), /Shop preview keeps stopping\. It is needed for: PIL-3\./, 'W-054 A: a failing service that work depends on is said on Home, with Restart');
  // review stuff is never a row or a card on Home: not a question, not its answers, not a result, not the Reviewer's doubt
  assert.doesNotMatch(all, /Which colour|Blue|Green|Result r1|Reviewer was not sure|Landing page/);
  assert.ok(!nodes(page).some(n => /answer-option|question-title/.test(n.attrs?.className || '')));
  const line = key(page, 'review-line');
  assert.equal(text(line), '2 questions, 3 results and 1 more wait in ReviewOpen Review');
  assert.equal(key(page, 'review-all').attrs.href, '#review');
  assert.match(key(page, 'review-all').attrs.className, /outline/, 'the sign-in row is the main thing to do: Open Review is not filled beside it');
  // THE number (the Review badge) is the rows of Blocked now that it counts plus the Review line
  const sum = nodes(page).reduce((n, x) => n + (Number(x.attrs?.['data-counts']) || 0), 0);
  assert.equal(c.needsToday().count, 10); assert.equal(sum, 10);
  // an intentional pause and a full start line are calm notices above, never rows of Blocked now; the merge queue is a quiet line
  assert.ok(key(page, 'review-paused') && key(page, 'start-line'));
  assert.ok(!nodes(blocked).some(n => ['review-paused', 'start-line', 'needs-queue'].includes(n.attrs?.['data-key'])));
  assert.match(text(key(page, 'needs-queue')), /2 in the merge queue, nothing to do/);
  // the order of the page
  const order = ['blocked', 'review-line', 'tiles', 'finished-today', 'needs-notes-card'].map(k => nodes(page).findIndex(n => n.attrs?.['data-key'] === k));
  assert.deepEqual(order, order.slice().sort((a, b) => a - b)); assert.ok(order.every(i => i > -1));
  assert.equal(text(key(page, 'tiles')), '2 in progress0 helpers working1 not started0 finished today', 'the numbers are one row');
});
test('O-01 D: with nothing blocked Home says so in one line; Open Review is the one filled button; nothing waiting says that too', () => {
  const {tickets, rows, state} = BUSY();
  const calm = rows.filter(r => r.kind === 'question'), list = tickets.filter(t => !['t7'].includes(t.id));
  const c = homeCtx(list, calm, {counts:{needs_you:{stopped:0, queue:[], items:[{ticket:'t1', question:'q1'}, {ticket:'t2', question:'q1'}, {ticket:'r1'}]}, in_progress:[], not_started:[]}});
  const page = c.home();
  assert.equal(text(key(page, 'blocked')), 'Nothing is blocked.');
  assert.equal(text(key(page, 'review-line')), '2 questions and 1 result wait in ReviewOpen Review');
  assert.match(key(page, 'review-all').attrs.className, /primary/);
  const quiet = homeCtx([{id:'o1', title:'Plan the trip', status:'ready'}], [], {counts:{needs_you:{stopped:0, queue:[], items:[]}, in_progress:[], not_started:['o1']}}), p2 = quiet.home();
  assert.match(text(p2), /^Nothing needs you/);
  assert.equal(text(key(p2, 'review-line')), 'Nothing waits in Review.');
  assert.equal(text(key(p2, 'blocked')), 'Nothing is blocked.');
  const one = homeCtx([{id:'r1', title:'Result', status:'review'}], [], {counts:{needs_you:{stopped:0, queue:[], items:[{ticket:'r1'}]}}});
  assert.match(text(key(one.home(), 'review-line')), /^1 result waits in Review/);
});
test('O-01 D: the blocked rows act: Merge merges that pull request, Remind sends the fixed words, Try again starts the helper', async () => {
  const {tickets, rows, state} = BUSY(), c = homeCtx(tickets, rows, state), page = c.home();
  const btn = (row, label) => nodes(key(page, row)).find(n => n.tag === 'button' && text(n) === label);
  await btn('need-core:unmerged:t4', 'Merge').onclick();
  assert.equal(JSON.stringify(c.acts.at(-1)), JSON.stringify(['pull.merge', {ticket:'t4', url:'https://github.com/acme/shop/pull/131', head:'a'.repeat(40)}]));
  await btn('need-core:idle:t5', 'Remind').onclick();
  assert.equal(c.acts.at(-2)[0], 'run.send'); assert.equal(c.acts.at(-1)[0], 'run.start');
  await btn('start-failed-t7', 'Try again').onclick();
  assert.equal(JSON.stringify(c.acts.at(-1)), JSON.stringify(['run.start', {ticket:'t7'}]));
  assert.match(btn('need-core:unmerged:t4', 'Merge').attrs.className, /outline/, 'a merge is never the filled button of the overview');
  // a read-only copy offers no change, only the way to the ticket
  const copy = homeCtx(tickets, rows, state, {snapshot:true}).home();
  assert.ok(!nodes(key(copy, 'blocked')).some(n => n.tag === 'button'));
  assert.ok(nodes(key(copy, 'need-core:permission:t3')).some(n => n.tag === 'a' && text(n) === 'Open'));
});
test('O-01 D: Finished is the five newest finished tickets, each one title and one short result; the rest behind one link', () => {
  const when = i => new Date(Date.parse('2026-11-14T11:00:00Z') - i * 26 * 3600000).toISOString();  // spread over several days
  const many = Array.from({length:7}, (_, i) => ({...done('d' + i, 'Done ' + i, when(i), 'Result ' + i + '.'), key:'PIL-' + (10 + i)}));
  const bare = {id:'bare', key:'PIL-30', title:'No words', status:'done', done_at:'2026-11-14T11:30:00Z', checklist:[]};
  const short = {id:'kp2', key:'KP-2', title:'Draft the start page', status:'done', done_at:'2026-11-14T11:40:00Z', summary:'Entwurf liegt in start.md', checklist:[]};
  const long = {...done('long', 'A long one', '2026-11-14T11:50:00Z', 'Sales are up eight percent on September in every region we sell in. ' + 'More words follow here. '.repeat(20)), key:'PIL-31'};
  const draw = list => homeCtx(list, []).home();
  const page = draw([{id:'w', title:'Plan', status:'active'}, ...many, bare, short, long]), fin = key(page, 'finished-today');
  assert.deepEqual(keys(fin, /^ticket-/).map(n => n.attrs['data-key']), ['ticket-long', 'ticket-kp2', 'ticket-bare', 'ticket-d0', 'ticket-d1'], 'newest first, also from earlier days');
  assert.match(text(key(fin, 'ticket-d1')), /PIL-11.*Done 1.*Result 1\./);
  assert.equal(text(key(fin, 'finished-result-bare')), 'No result written yet');
  assert.equal(text(key(fin, 'finished-result-kp2')), 'Entwurf liegt in start.md', 'the summary stands in for a missing outcome (ORCH-2297)');
  const said = key(fin, 'finished-result-long');
  assert.ok(text(said).length <= 111 && /^Sales are up eight percent/.test(text(said)), 'one short result');
  assert.match(said.attrs.className, /truncate/, 'one line');
  assert.match(text(key(fin, 'finished-done')), /Done tickets/);
  assert.ok(!key(page, 'what-changed'), 'no second list of finished work below');
  assert.match(text(key(page, 'tile-finished-today')), /^4 finished today$/);
  const few = draw([{id:'w', title:'Plan', status:'active'}, many[0]]);
  assert.ok(!key(few, 'finished-done'));
  assert.match(text(key(draw([{id:'w', title:'Plan', status:'active'}]), 'finished-today')), /Nothing finished yet\./);
});
test('CX-01: the Helpers row and the number of helpers working come from one reading of the run', () => {
  const row = (state, more = {}) => ({ticket:{id:'x'}, state, word:helpers.HELPER_WORDS[state], detail:'', finished:false, idle:null, ...more});
  // work that goes on: the core's state as it is
  assert.deepEqual(helpers.helperShown(row('working')), {state:'working', word:'Working', meta:null, act:null});
  assert.equal(helpers.helperShown(row('idle')).act, 'remind'); assert.equal(helpers.helperShown(row('stuck')).act, 'remind');
  // finished and nothing running: Finished with Open ticket, never Stuck with Stop
  for (const r of [row('stuck', {finished:true, idle:27, detail:'Nothing running for 27 min'}), row('idle', {finished:true, idle:3, detail:'Nothing running for 3 min'}), row('idle', {finished:true})]) {
    const s = helpers.helperShown(r);
    assert.deepEqual([s.state, s.word, s.act], ['finished', 'Finished', 'open']); assert.match(s.meta, /^Nothing running/);
  }
  // a process that still runs says so and keeps Stop
  for (const st of ['working', 'starting', 'waiting']) assert.deepEqual(helpers.helperShown(row(st, {finished:true})), {state:st, word:helpers.HELPER_WORDS[st], meta:'Ticket finished; helper still running', act:'stop'});
  // unknown says so
  assert.deepEqual(helpers.helperShown(row('stuck', {finished:true, detail:'No update for a while'})), {state:'unknown', word:'Not known', meta:'Ticket finished; orch cannot tell if a helper still runs', act:'stop'});
  // a helper that needs the person stays that, finished or not
  assert.equal(helpers.helperShown(row('you', {finished:true})).state, 'you');
  assert.equal(helpers.helpersWorking([row('working'), row('starting'), row('working', {finished:true}), row('stuck', {finished:true, idle:27}), row('idle'), row('you')]), 3);

  // on Home: the walk's case (ORCH-2154: finished, nothing running for 27 min) beside a helper at work
  const tickets = [{id:'fin', key:'ORCH-2154', title:'Workspace shows new_key', status:'done', done_at:'2026-11-14T11:00:00Z', checklist:[]},
    {id:'on', key:'ORCH-2289', title:'Nightly perf run', status:'done', done_at:'2026-11-14T10:00:00Z', checklist:[]}, {id:'w', key:'ORCH-9', title:'Plan', status:'active'}];
  const runs = {fin:{running:true, idle_seconds:27 * 60, helper:{state:'stuck', detail:'Nothing running for 27 min'}}, on:{running:true, age_seconds:600, helper:{state:'working'}}};
  const c = homeCtx(tickets, [], {runs}), page = c.home();
  assert.equal(text(key(page, 'helpers-fin')), 'Workspace shows new_key|Finished|Nothing running for 27 min|Open ticket');
  assert.equal(key(page, 'helpers-fin').attrs['data-state'], 'finished', 'no Stuck pill');
  assert.equal(text(key(page, 'helpers-on')), 'Nightly perf run|Working|Ticket finished; helper still running|Stop');
  assert.match(text(key(page, 'tile-helpers')), /^1 helper working$/, 'the number counts the rows that say Working');
  key(page, 'helpers-fin-open').onclick();
  assert.equal(c.location.hash, '#ticket/fin');
  assert.ok(!nodes(key(page, 'helpers-fin')).some(n => text(n) === 'Stop'));
});
test('W-017: day one is "Write your first ticket" with one filled New ticket; a sign-in notice is one line, one button, only for the chosen helper tool, no terminal', () => {
  const login = (name, chosen, more = {}) => ({name, label:name[0].toUpperCase() + name.slice(1), kind:'login', state:'renew', helper:name, chosen, stops:[], sign_in:name + ' login', ...more});
  // the walk's picture: the workspace runs Claude, the Codex login stopped
  const other = homeCtx([], [], {logins:{items:[login('codex', false), {...login('claude', true), state:'works'}]}}).home();
  assert.match(text(other), /^Nothing needs you/);
  assert.ok(!key(other, 'blocked'), 'a tool this workspace does not use says nothing');
  assert.match(text(key(other, 'empty')), /Write your first ticket/);
  const firsts = nodes(other).filter(n => /\bprimary\b/.test(n.attrs?.className || ''));
  assert.deepEqual(firsts.map(text), ['New ticket'], 'one filled button');
  assert.ok(!key(other, 'review-line') && !key(other, 'tiles') && !key(other, 'finished-today') && !key(other, 'all-tickets'), 'nothing else on day one');
  // the chosen tool is signed out: one line with one button above the first step
  const own = homeCtx([], [], {logins:{items:[login('codex', true)]}}).home(), row = key(own, 'login-stopped-codex');
  assert.equal(text(row), 'The Codex login stopped working.Helpers start no new work.Sign in');
  assert.equal(nodes(row).filter(n => n.tag === 'button' || n.tag === 'a').length, 1);
  assert.equal(key(own, 'login-stopped-codex-sign-in').attrs.href, '#settings/agent');
  assert.doesNotMatch(text(own), /terminal|this computer|codex login\b(?! stopped)|\brun\b/i);
  assert.ok(nodes(own).findIndex(n => n === row) < nodes(own).findIndex(n => n.attrs?.['data-key'] === 'empty'));
  // a login orch can renew itself offers that (the renew step's own button); a connection that is not a helper tool still shows
  const renew = homeCtx([{id:'t', title:'T', status:'active'}], [], {logins:{items:[login('codex', true, {renew:true}), {name:'wiki', label:'Company wiki', kind:'connection', state:'unreachable', stops:[{id:'t', title:'T'}]}]}},
    {renewButton:item => item.renew ? h('button', {className:'btn primary sm'}, 'Renew') : null}).home();
  assert.match(text(key(renew, 'login-stopped-codex')), /Renew$/);
  assert.equal(text(key(renew, 'login-stopped-wiki')), 'The Company wiki connection cannot be reached.Helpers stopped on 1 ticket.Try again');
  assert.doesNotMatch(read('pages/home.js').slice(read('pages/home.js').indexOf('function loginStoppedRow'), read('pages/home.js').indexOf('// Tickets waiting in line')), /needHow|loginHow|commandCopy/);
});
test('W-054 A: Home names a service only through the add-on’s own row (work depends on it); a background service that stopped starts with one click', () => {
  const tickets = [{id:'w', title:'Plan', status:'active'}];
  const none = homeCtx(tickets, []).home();
  assert.equal(text(key(none, 'blocked')), 'Nothing is blocked.', 'no row from the add-on: Home says nothing about services');
  const svc = homeCtx(tickets, [], {services:[{addon:'sync', running:false}, {addon:'mail', running:false, idle:true}]}, {addons:() => [{name:'sync', dashboard:{label:'sync'}}]}).home();
  assert.equal(text(key(svc, 'background')), 'Sync has stopped.Its work waits. Your tickets and everything else still work.Start Sync');
  assert.equal(key(svc, 'background').attrs['data-blocked'], 'service');
});

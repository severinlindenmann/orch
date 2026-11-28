// O-07 (owner chose A, 28 Nov; this reverses ORCH-777's Overview history): the Overview is one compact screen. It shows
// the last three things that happened and one button to the Activity tab, which holds the whole history. What stays of
// ORCH-777 is the rule for the files that came with the request.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');

function context(extra = {}) {
  const ctx = {array:v => Array.isArray(v) ? v : [], h:(tag, attrs, ...children) => ({tag, attrs, children}), iconEl:n => n, clean:s => String(s ?? ''),
    name:v => String(v ?? '').replace(/^(human|agent):/, ''), time:v => String(v).slice(11, 16), window:{UI:{stamp:at => String(at).slice(0, 10)}, DashHelpers:helpers, orch:{toast(){}}},
    snapshot:false, state:{}, render(){}, ...extra};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('// These three icons'), source.indexOf('function detail(t)')), ctx);
  return ctx;
}
const run = (c, code, vars) => { Object.assign(c, vars); return vm.runInContext(code, c); };
const request = (c, t, files = []) => [...run(c, 'requestFiles(t, files)', {t, files}).map(f => f.name)];
const text = node => node == null ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.children);
const find = (node, test) => { if (!node || typeof node !== 'object') return null; if (Array.isArray(node)) { for (const n of node) { const f = find(n, test); if (f) return f; } return null; } return test(node) ? node : find(node.children, test); };

const T0 = '2026-11-17T08:00:00Z';
test('files a person attached with the request (the first 2 minutes) are the request files; a later or deleted one is not', () => {
  const c = context();
  const t = {id:'t_one', created_at:T0, history:[{at:T0, by:'human:pat', text:'Created'}, {at:'2026-11-17T08:01:00Z', by:'human:pat', text:'Attached brief.png'},
    {at:'2026-11-18T08:00:00Z', by:'human:pat', via:'phone', text:'Attached phone.png'}, {at:'2026-11-18T09:00:00Z', by:'human:pat', text:'Attached gone.png'},
    {at:'2026-11-17T08:01:30Z', by:'agent:claude', text:'Attached helper.png'}]};
  assert.deepEqual(request(c, t, [{name:'brief.png', mtime:T0}, {name:'phone.png', mtime:'2026-11-18T08:00:00Z'}, {name:'helper.png'}]), ['brief.png']);
});

test('without any creation time every attached file belongs to the request', () => {
  const c = context();
  assert.deepEqual(request(c, {id:'t', history:[{by:'human:pat', text:'Attached a.png'}]}, [{name:'a.png'}]), ['a.png']);
});

test('#1812: the request files are the ones the ticket kept, whatever the time; a slow upload is still the request', () => {
  const c = context();
  const t = {id:'t', created_at:T0, request:{note:'Do it', files:['slow.png']}, history:[{at:T0, by:'human:pat', text:'Created'},
    {at:'2026-11-17T08:05:00Z', by:'human:pat', text:'Attached slow.png'}, {at:'2026-11-17T08:01:00Z', by:'human:pat', text:'Attached later.png'}]};
  assert.deepEqual(request(c, t, [{name:'slow.png'}, {name:'later.png'}]), ['slow.png']);
  assert.equal(run(c, 'timeOf(1763460000000)'), 1763460000000);
  assert.equal(run(c, 'timeOf(null)'), null);
});

test('the request block: note, the helper-written description and the request files; nothing when there is none', () => {
  const c = context();
  assert.equal(run(c, 'overviewRequest(t, null, [])', {t:{id:'t'}}), null);
  const node = run(c, 'overviewRequest(t, "NOTE", [])', {t:{id:'t', note:'NOTE', description:'What this is about', description_by:'agent:claude', created_at:T0}});
  assert.match(text(node), /What was asked.*NOTE.*What this is about.*Written by/);
  // an empty note under a helper's description is not an empty row (report r-1122-0538); with no description it stays to be filled in
  assert.doesNotMatch(text(run(c, 'overviewRequest(t, "EMPTY NOTE", [])', {t:{id:'t', description:'What this is about', created_at:T0}})), /EMPTY NOTE/);
  assert.match(text(run(c, 'overviewRequest(t, "EMPTY NOTE", [])', {t:{id:'t', created_at:T0}})), /EMPTY NOTE/);
});

test('O-07: the Overview order in detail(): the result, one tasks line, the last three events, the request last; no write box, no history', () => {
  const body = source.slice(source.indexOf('function detail(t)'), source.indexOf('// ORCH-189'));
  const at = s => { const i = body.indexOf(s); assert.ok(i > 0, s); return i; };
  assert.ok(at('ticketReviewCard(t)') < at('overviewResult(t)') && at('overviewResult(t)') < at('overviewTasksLine(t)'));
  assert.ok(at('overviewTasksLine(t)') < at('overviewLatest(t)') && at('overviewLatest(t)') < at('    request];'));
  assert.doesNotMatch(body, /ticketTalkCard|overviewHistory|ticketHelperDid|ticketProgress\(|ticketWidgetsCard/, 'the chat is on Ticket chat, the history on Activity, the tasks on Tasks');
  assert.match(body, /panel\('activity', 'Activity', \[ticketDecided\(t\), ticketHistoryPanel\(t\)\]\)/, 'the answers given in Review moved to Activity with the history');
  assert.doesNotMatch(source, /function overviewHistory|function ticketTalkCard|data-ticket-talk'/);
});

// #1781 / #1782 / #1783: what the helper said, the runs and the add-on that wrote a line, in plain words
const T1 = '2026-11-19T09:00:00Z', T2 = '2026-11-19T09:52:00Z';
const storyTicket = () => ({id:'t_said', created_at:T0, checklist:[{id:'c1', text:'Write it'}, {id:'c2', text:'Post it'}],
  history:[{at:T0, by:'human:pat', text:'Created'}, {at:'2026-11-19T09:30:00Z', by:'agent:claude', chat_message:true, id:'m_aaaaaaaaaaaaaaaa', text:'The draft is in Files.\nOne open point.'},
    {at:'2026-11-19T09:40:00Z', by:'system', addon:'automation', text:'Summary updated'}, {at:'2026-11-19T09:50:00Z', by:'system', addon:'dashboard', text:'Summary checked'}],
  runs:[{id:'r_aaaa1111', agent:'claude', started:T1, ended:T2, minutes:52, tasks:['c1', 'c2']}, {id:'r_bbbb2222', agent:'claude', started:'2026-11-20T08:00:00Z'},
    {id:'r_cccc3333', agent:'claude', started:T1, ended:T1, minutes:0}]});

test('O-07: the Overview shows the last three events, one line each, and "Show all N in Activity"', () => {
  const c = context({state:{me:'human:pat'}});
  const t = storyTicket(), node = run(c, 'overviewLatest(t)', {t});
  const lines = []; const walk = n => { if (!n || typeof n !== 'object') return; if (Array.isArray(n)) return n.forEach(walk); if (n.attrs?.className === 'history-event') lines.push(text(find(n.children, x => x.tag === 'p'))); else walk(n.children); }; walk(node);
  assert.equal(lines.length, 3);
  assert.equal(lines[0], 'Helper started working', 'newest first; a run is one line');
  const all = run(c, "activityRows(t, 'All').length", {t});
  assert.ok(all > 3);
  const jump = find(node, n => n.attrs?.['data-key'] === 'overview-all-activity');
  assert.equal(text(jump), 'Show all ' + all + ' in Activity');
  assert.deepEqual([jump.attrs['data-action'], jump.attrs['data-tab'], jump.attrs['data-ticket']], ['ticket-tab', 'activity', 't_said'], 'the page\'s own tab click opens Activity');
  assert.equal(run(c, 'ticketTabList(t)', {t}).find(x => x[0] === 'activity')[2], all, 'the tab shows the same number');
  // three or fewer: no button; nothing at all: no block
  const few = {id:'t_few', history:[{at:T0, by:'human:pat', text:'Created'}]};
  assert.equal(find(run(c, 'overviewLatest(t)', {t:few}), n => n.attrs?.['data-key'] === 'overview-all-activity'), null);
  assert.equal(run(c, 'overviewLatest(t)', {t:{id:'t_none'}}), null);
});

test('O-07: a read-only copy has no tab button; it says the rest is under Activity', () => {
  const c = context({snapshot:true, state:{me:'human:pat'}});
  const node = run(c, 'overviewLatest(t)', {t:storyTicket()});
  assert.equal(find(node, n => n.tag === 'button'), null);
  assert.match(text(node), /more under Activity\./);
});

test('the Activity tab lists the runs with the helper lines, under All and Helper, never under People', () => {
  const c = context({emptyRow:s => ({tag:'p', attrs:{}, children:[s]}), state:{me:'human:pat'}});
  const t = storyTicket();
  const panel = () => run(c, 'ticketHistoryPanel(t)', {t});
  const lines = () => { const out = []; const walk = n => { if (!n || typeof n !== 'object') return; if (Array.isArray(n)) return n.forEach(walk); if (n.attrs?.className === 'ticket-event') out.push(text(find(n.children, x => x.tag === 'p'))); else walk(n.children); }; walk(panel()); return out; };
  const all = lines();
  assert.equal(all[0], 'Helper started working');
  assert.ok(all.includes('Helper worked for 52 minutes · finished 2 tasks'));
  assert.ok(all.some(l => /Updated the summary Automation$/.test(l.replace(/\s+/g, ' '))), 'the add-on tag on its line');
  assert.match(text(find(panel(), n => n.attrs?.['data-key'] === 'history-show-Helper')), /Helper 4/, 'the count holds the runs');
  run(c, "ticketHistoryActor = 'People'");
  assert.ok(!lines().some(l => /^Helper (worked|started)/.test(l)));
  run(c, "ticketHistoryActor = 'All'");
});


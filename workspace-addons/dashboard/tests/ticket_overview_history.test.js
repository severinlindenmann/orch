// ORCH-777 (draft E part 2): the ticket Overview as one history, newest first. Every entry has one owner (answered
// questions, files a person attached, evidence and result files, story lines), so nothing shows twice or goes missing.
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
const entries = (c, t, files = []) => run(c, 'overviewEntries(t, files)', {t, files});
const kinds = r => [...r.entries.map(x => x.kind + ':' + (x.q?.id || x.entry?.text || x.files?.map(f => (f.file || f).name).join('+')))];
const text = node => node == null ? '' : typeof node !== 'object' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.children);
const find = (node, test) => { if (!node || typeof node !== 'object') return null; if (Array.isArray(node)) { for (const n of node) { const f = find(n, test); if (f) return f; } return null; } return test(node) ? node : find(node.children, test); };

const T0 = '2026-11-17T08:00:00Z';
test('an answered question shows once, as its card; its Asked and Answered lines are dropped', () => {
  const c = context();
  const t = {id:'t_one', created_at:T0, history:[{at:T0, by:'human:pat', text:'Created'}, {at:'2026-11-17T09:00:00Z', by:'agent:claude', text:'Asked q1, sent to phone'},
    {at:'2026-11-17T09:05:00Z', by:'human:pat', via:'phone', text:'Answered q1: B'}],
    questions:[{id:'q1', text:'Which layout?', answer:'B', answered_at:'2026-11-17T09:05:00Z', via:'phone'}]};
  assert.deepEqual(kinds(entries(c, t)), ['answer:q1', 'event:Created']);
});

test('a question that no longer exists keeps its history lines; an open question is on top, not in the history', () => {
  const c = context();
  const t = {id:'t_one', created_at:T0, history:[{at:'2026-11-17T09:00:00Z', by:'human:pat', text:'Answered q7: later'}, {at:'2026-11-17T10:00:00Z', by:'agent:claude', text:'Asked q2, sent to phone'}],
    questions:[{id:'q2', text:'Open one?', answer:null}]};
  assert.deepEqual(kinds(entries(c, t)), ['event:Answered q7: later']);
});

test('a taken-back question is still in the history, at its answer time', () => {
  const c = context();
  const r = entries(c, {id:'t', questions:[{id:'q1', text:'Ship?', answer:'Yes', taken_back:true, answered_at:'2026-11-18T10:00:00Z', asked_at:'2026-11-18T09:00:00Z'}]});
  assert.equal(r.entries[0].kind, 'answer');
  assert.equal(r.entries[0].at, Date.parse('2026-11-18T10:00:00Z'));
});

test('files a person attached: with the request in the first 2 minutes, a message later; the Attached line never also shows', () => {
  const c = context();
  const t = {id:'t_one', created_at:T0, history:[{at:T0, by:'human:pat', text:'Created'}, {at:'2026-11-17T08:01:00Z', by:'human:pat', text:'Attached brief.png'},
    {at:'2026-11-18T08:00:00Z', by:'human:pat', via:'phone', text:'Attached phone.png'}, {at:'2026-11-18T09:00:00Z', by:'human:pat', text:'Attached gone.png'}]};
  const r = entries(c, t, [{name:'brief.png', mtime:T0}, {name:'phone.png', mtime:'2026-11-18T08:00:00Z'}]);
  assert.deepEqual([...r.request.map(f => f.name)], ['brief.png']);
  assert.deepEqual(kinds(r), ['event:Attached gone.png', 'attached:phone.png', 'event:Created'], 'a deleted file keeps its row; the request file is not in the stream');
  assert.equal(r.entries[1].via, 'phone');
});

test('without any creation time every attached file belongs to the request', () => {
  const c = context();
  const r = entries(c, {id:'t', history:[{by:'human:pat', text:'Attached a.png'}]}, [{name:'a.png'}]);
  assert.deepEqual([...r.request.map(f => f.name)], ['a.png']);
  assert.equal(r.entries.length, 0);
});

test('evidence files sit in their task line; a result file with the same name is that evidence; other results group by 10 minutes', () => {
  const c = context();
  const ev = name => ({type:'file', ref:'.orch/tickets/t_one/evidence/' + name, at:'2026-11-18T10:00:00Z'});
  const t = {id:'t_one', created_at:T0, checklist:[{id:'c1', text:'Build it', done:true, evidence:[ev('shot.png'), ev('shot.png')]}, {id:'c2', text:'Check it', evidence:[ev('log.txt')]}],
    history:[{at:'2026-11-18T10:00:00Z', by:'agent:claude', text:'Check c1 done'}, {at:'2026-11-18T09:00:00Z', by:'agent:claude', text:'Added check c1'}]};
  const files = [{name:'shot.png', mtime:'2026-11-18T10:00:00Z'}, {name:'a.md', mtime:'2026-11-18T12:00:00Z'}, {name:'b.md', mtime:'2026-11-18T11:55:00Z'},
    {name:'c.md', mtime:'2026-11-18T11:49:00Z'}, {name:'old.md'}];
  const r = entries(c, t, files);
  assert.deepEqual(kinds(r), ['files:a.md+b.md', 'files:c.md', 'files:log.txt', 'event:Check c1 done', 'files:old.md']);
  const line = r.entries.find(x => x.kind === 'event');
  assert.deepEqual([...line.files.map(f => f.file.name)], ['shot.png'], 'one file once, inside "Finished a task"');
  assert.equal(r.entries[2].label, 'Check it', 'evidence of a task without a done line is its own message, named by the task');
  assert.ok(!kinds(r).some(k => k.includes('Added check')), 'a helper adding a task is Activity only');
});

test('story lines: helper noise stays on Activity, a person line no rule knows still shows, status moves to Check and Done show', () => {
  const c = context();
  const t = {id:'t', history:[
    {at:'2026-11-18T10:00:00Z', by:'agent:claude', text:'pull-requests refresh: 2 checks'}, {at:'2026-11-18T10:01:00Z', by:'agent:claude', text:'Set ext.automation'},
    {at:'2026-11-18T10:02:00Z', by:'orch', text:'Model picked: Opus (it mentions draft)'}, {at:'2026-11-18T10:03:00Z', by:'orch', text:'Status open -> active'},
    {at:'2026-11-18T10:04:00Z', by:'human:pat', text:'Claude started'}, {at:'2026-11-18T10:05:00Z', by:'agent:claude', text:'Status active -> review'},
    {at:'2026-11-18T10:06:00Z', by:'human:pat', text:'Edited due (was: 2026-11-20 | now: 2026-11-21)'}]};
  assert.deepEqual(kinds(entries(c, t)), ['event:Edited due (was: 2026-11-20 | now: 2026-11-21)', 'event:Status active -> review', 'event:Claude started']);
});

test('undated entries come last in the order written; a future time sorts on top; same time: answer, file, line', () => {
  const c = context();
  const t = {id:'t', history:[{by:'human:pat', text:'First undated'}, {at:'2026-11-18T10:00:00Z', by:'human:pat', text:'Dated'}, {by:'human:pat', text:'Second undated'},
    {at:'2099-01-01T00:00:00Z', by:'human:pat', text:'Future'}, {at:'2026-11-18T10:00:00Z', by:'human:pat', text:'Attached x.png'}],
    created_at:'2026-11-01T00:00:00Z', questions:[{id:'q1', text:'Q', answer:'A', answered_at:'2026-11-18T10:00:00Z'}]};
  const r = entries(c, t, [{name:'x.png'}]);
  assert.deepEqual(kinds(r), ['event:Future', 'answer:q1', 'attached:x.png', 'event:Dated', 'event:First undated', 'event:Second undated']);
  assert.equal(run(c, 'overviewDay(x)', {x:r.entries[5]}), 'Earlier');
});

test('first view shows 5 entries; Show earlier reveals one day (at most 20); Show all everything', () => {
  const c = context();
  const day = (d, n) => Array.from({length:n}, (_, i) => ({at:`2026-11-${d}T${String(10 + (i % 10)).padStart(2, '0')}:${String(i).padStart(2, '0')}:00Z`, by:'human:pat', text:'Note ' + d + '-' + i}));
  const t = {id:'t_long', history:[...day('18', 3), ...day('17', 4), ...day('16', 30)]};
  const all = entries(c, t).entries;
  assert.equal(all.length, 37);
  let more = run(c, 'overviewMore(list, 5)', {list:all});
  assert.equal(more.n, 2, 'the rest of the 17th');
  more = run(c, 'overviewMore(list, 7)', {list:all});
  assert.equal(more.n, 20, 'a day of 30 reveals 20 at a time');
  assert.equal(run(c, 'overviewMore(list, 37)', {list:all}), null);
  const node = run(c, 'overviewHistory(t, list)', {list:all});
  assert.equal(find(node, n => n.attrs?.['data-key'] === 'history-earlier') != null, true);
  assert.equal(find(node, n => n.attrs?.['data-key'] === 'history-all') != null, true);
  assert.equal(find(node, n => n.attrs?.['data-key'] === 'history-jump'), null, 'the request is right under this line: no jump link');
  assert.equal((text(node).match(/Note /g) || []).length, 5);
  run(c, 'overviewOpen.set("t_long", Infinity)');
  assert.equal((text(run(c, 'overviewHistory(t, list)', {list:all})).match(/Note /g) || []).length, 37);
  assert.equal(find(run(c, 'overviewHistory(t, list)', {list:all.slice(0, 5)}), n => n.attrs?.['data-key'] === 'history-more'), null);
});

test('a read-only copy shows 50 entries and says where the rest are; no buttons', () => {
  const c = context({snapshot:true});
  const t = {id:'t_snap', history:Array.from({length:60}, (_, i) => ({at:new Date(Date.UTC(2026, 10, 18, 0, i)).toISOString(), by:'human:pat', text:'Line ' + i}))};
  const node = run(c, 'overviewHistory(t, overviewEntries(t).entries)', {t});
  assert.match(text(node), /10 earlier entries are on the Activity tab/);
  assert.equal(find(node, n => n.attrs?.['data-key'] === 'history-earlier'), null);
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

test('the Overview order in detail(): write box, history, then the request last; the old cards are gone', () => {
  const body = source.slice(source.indexOf('function detail(t)'), source.indexOf('// ORCH-189'));
  const at = s => { const i = body.indexOf(s); assert.ok(i > 0, s); return i; };
  assert.ok(at('ticketTalkCard(t)') < at('overviewHistory(t, story.entries') && at('overviewHistory(t, story.entries') < at('    request];'));
  assert.doesNotMatch(body, /Earlier answers|'What was asked'/);
});

test('review fixes: a person file used as evidence shows once; a Done ticket keeps an unanswered question line; times as numbers', () => {
  const c = context();
  const t = {id:'t_one', status:'done', created_at:T0, history:[{at:'2026-11-18T08:00:00Z', by:'human:pat', text:'Attached plan.png'}, {at:'2026-11-18T09:00:00Z', by:'agent:claude', text:'Check c1 done'},
    {at:'2026-11-18T10:00:00Z', by:'human:pat', text:'Asked q3, by hand'}],
    checklist:[{id:'c1', text:'Use it', evidence:[{type:'file', ref:'.orch/tickets/t_one/evidence/plan.png', at:'2026-11-18T09:00:00Z'}]}], questions:[{id:'q3', text:'Still open?', answer:null}]};
  const r = entries(c, t, [{name:'plan.png', mtime:'2026-11-18T08:00:00Z'}]);
  assert.deepEqual(kinds(r), ['event:Asked q3, by hand', 'event:Check c1 done', 'attached:plan.png']);
  assert.equal(r.entries[1].files.length, 0);
  assert.equal(run(c, 'timeOf(1763460000000)'), 1763460000000);
  assert.equal(run(c, 'timeOf(null)'), null);
});

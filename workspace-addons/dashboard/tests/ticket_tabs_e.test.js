// Draft E, part 3 (ORCH-778): the Tasks, Files and Activity tabs of the ticket page.
const kitState = require('./kit_state.js');
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const startSource = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/start.js'), 'utf8');
const helpers = require('../src/orch_dashboard/web/helpers.js');

const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false), append(...more){ this.children.push(...more); },
  setAttribute(k, v){ this.attrs[k] = v; }, addEventListener(){}, focus(){}, contains(){ return false; }});
const nodes = n => typeof n === 'object' && n ? [n, ...n.children.flatMap(nodes)] : [];
const text = n => nodes(n).flatMap(x => x.children.filter(c => typeof c !== 'object')).join('');
const byKey = (tree, key) => tree.find(n => n.attrs && n.attrs['data-key'] === key);

function page(t, files = []) {
  const ctx = {repeatsAddon:() => null, window:{UI:{...kitState}, DashHelpers:helpers, orch:{toast(){}}}, document:{addEventListener(){}}, addEventListener(){}, h,
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => String(v || '').replace(/^(human|agent):/, ''), route:() => ({kind:'ticket'}), render(){},
    el:(tag, cls, txt) => h(tag, {className:cls}, txt), fragment:(...kids) => h('fragment', {}, kids), button:(label, cls) => h('button', {className:cls}, label),
    card:(key, title, suffix, kids) => h('section', {'data-key':key}, title, suffix, kids), emptyRow:txt => h('p', {}, txt),
    questions:() => [], capitalise:v => v, date:() => '', dueText:() => '', time:() => '', ticketTabs:new Map(), addons:() => [], tickets:() => [t], ticketOf:() => t,
    statusChip:() => h('span', {}, 'Working'), chip:txt => h('span', {}, txt), href:id => '#ticket/' + id, MOVE_CHOICES:[], locks:new Set()};
  vm.createContext(ctx); vm.runInContext(source, ctx); vm.runInContext(startSource, ctx);
  ctx.snapshot = false; ctx.state = {settings:{agents:[]}, runs:{}};
  ctx.files = files; ctx.tid = t.id;
  vm.runInContext("loadArtifacts = () => {}; inlineField = (t,f) => t[f]; agentBar = () => null; addTaskRow = () => h('form', {'data-key':'add-form'});" +
    "artifactData.set(tid, {at:Date.now(), data:{files}});", ctx);
  return ctx;
}

const checklist = () => [
  {id:'c1', text:'Make the cards smaller', done:true, summary:'Cards are 40% smaller on a phone', evidence:[{type:'pr', ref:'https://github.com/o/r/pull/1412', at:'2026-11-19T08:00:00Z', by:'agent:claude'}]},
  {id:'c2', text:'Check the layouts at phone width', done:false, state:'doing', evidence:[{type:'pr', ref:'https://github.com/o/r/pull/1413', at:'2026-11-19T09:00:00Z'}]},
  {id:'c3', text:'Check the board on a phone once it is in', done:false},
  {id:'c4', text:'Old idea', done:false, wont_do:true, reason:'Not needed'}];

test('Tasks: a stepped bar, "N of M tasks done" and Add a task on one line; the add box opens on click', () => {
  const t = {id:'t_tasks', title:'Tasks', status:'active', checklist:checklist()};
  const ctx = page(t);
  let tree = nodes(ctx.detail(t));
  const head = byKey(tree, 'tasks-head');
  assert.ok(head, 'the head line');
  const bar = nodes(head).find(n => n.attrs.className === 'progress-steps');
  assert.deepEqual(bar.children.map(s => s.attrs.className ?? null), ['done', 'doing', null, 'skipped'], 'one step per task');
  assert.equal(bar.attrs['aria-valuenow'], '1');
  assert.equal(bar.attrs['aria-valuemax'], '3');
  assert.match(text(head), /1 of 3 tasks done1 skipped/, 'the skipped task is named, not counted as done');
  const add = byKey(tree, 'tasks-add-t_tasks');
  assert.ok(add && nodes(head).includes(add), 'Add a task sits on the same line');
  assert.equal(byKey(tree, 'add-form'), undefined, 'the add box waits for the click');
  ctx.document.querySelector = () => null; ctx.setTimeout = () => {};
  add.onclick();
  tree = nodes(ctx.detail(t));
  assert.ok(byKey(tree, 'add-form'), 'the add box opens');
});

test('Tasks: a done task shows what came out; the task the helper is on says so; a task to do shows nothing', () => {
  const t = {id:'t_out', title:'Out', status:'active', checklist:checklist()};
  const tree = nodes(page(t).detail(t));
  const result = byKey(tree, 'task-result-c1');
  assert.match(text(result), /^Cards are 40% smaller on a phone · /, 'what came out, then when and who');
  const row = id => byKey(tree, 'task-' + id);
  assert.ok(nodes(row('c1')).some(n => n.attrs.className === 'task-proofs row'), 'the pull request opens from the done task');
  assert.match(text(row('c2')), /The helper is on it\./);
  assert.ok(nodes(row('c2')).some(n => n.attrs.className === 'task-proofs row'), 'a draft pull request opens before the task is done');
  assert.ok(!nodes(row('c3')).some(n => /task-proof/.test(n.attrs.className || '')), 'nothing under a task still to do');
  assert.doesNotMatch(text(row('c3')), /Not started yet/);
});

test('Tasks: without tasks the add box shows at once; a Done ticket has no Add', () => {
  const t = {id:'t_none', title:'None', status:'active', checklist:[]};
  let tree = nodes(page(t).detail(t));
  assert.match(text(byKey(tree, 'tasks-head')), /No tasks yet\./);
  assert.ok(byKey(tree, 'add-form'));
  assert.equal(byKey(tree, 'tasks-add-t_none'), undefined);
  const done = {id:'t_fin', title:'Fin', status:'done', checklist:checklist()};
  tree = nodes(page(done).detail(done));
  assert.equal(byKey(tree, 'tasks-add-t_fin'), undefined);
  assert.equal(byKey(tree, 'add-form'), undefined);
});

test('Files: All / Helper / You with counts when both kinds exist, and the filter narrows the list', () => {
  const t = {id:'t_files', title:'Files', status:'active', checklist:[],
    history:[{by:'human:lume', text:'Attached Screenshot 17-16.png', at:'2026-11-16T09:12:00Z'}]};
  const ctx = page(t, [{name:'Screenshot 17-16.png', size:400}, {name:'board-measurements.md', size:20}, {name:'layouts.html', size:30}]);
  let tree = nodes(ctx.detail(t));
  const who = byKey(tree, 'files-who');
  assert.ok(who, 'the filter shows');
  assert.equal(who.attrs.className, 'segmented');
  assert.deepEqual(who.children.map(b => text(b)), ['All 3', 'Helper 2', 'You 1']);
  assert.equal(byKey(tree, 'files-who-All').attrs['aria-pressed'], 'true');
  byKey(tree, 'files-who-You').onclick();
  tree = nodes(ctx.detail(t));
  const tiles = nodes(tree.find(n => n.attrs.id === 'ticket-panel-files')).filter(n => n.attrs.className === 'file-tile');
  assert.equal(tiles.length, 1);
  assert.equal(byKey(tree, 'files-who-You').attrs['aria-pressed'], 'true');
});

test('Files: one kind only needs no filter and shows every file, whatever was picked before', () => {
  const t = {id:'t_one', title:'One', status:'active', checklist:[]};
  const ctx = page(t, [{name:'a.md', size:1}, {name:'b.md', size:1}]);
  vm.runInContext("filesUI.who = 'You'", ctx);
  const tree = nodes(ctx.detail(t));
  assert.equal(byKey(tree, 'files-who'), undefined);
  assert.equal(nodes(tree.find(n => n.attrs.id === 'ticket-panel-files')).filter(n => n.attrs.className === 'file-tile').length, 2);
});

test('Activity: the master segmented filter with counts, and a Phone tag on what came from the phone', () => {
  const t = {id:'t_act', title:'Act', status:'active', checklist:[], history:[
    {by:'human:lume', text:'Created', at:'2026-11-16T09:12:00Z', via:'dashboard'},
    {by:'agent:claude', text:'Drafted the plan', at:'2026-11-16T09:31:00Z'},
    {by:'human:lume', text:'Edited title', at:'2026-11-17T08:45:00Z', via:'phone'},
    {by:'human:lume', text:'Edited due', at:'2026-11-17T08:50:00Z', via:'phone'}]};
  const ctx = page(t);
  let tree = nodes(ctx.detail(t));
  const head = byKey(tree, 'history-head');
  const seg = nodes(head).find(n => n.attrs.className === 'segmented');
  assert.ok(seg, 'the master segmented control');
  assert.deepEqual(seg.children.map(b => text(b)), ['All 4', 'People 3', 'Helper 1']);
  const tags = tree.filter(n => n.attrs.className === 'tag');
  assert.equal(tags.length, 2, 'two entries came from the phone');
  assert.ok(tags.every(n => n.attrs['data-key'] == null), 'no shared redraw key on the tags');
  assert.equal(tags[0].attrs.className, 'tag');
  assert.deepEqual(tags[0].children, ['Phone']);
  byKey(tree, 'history-show-Helper').onclick();
  tree = nodes(ctx.detail(t));
  assert.equal(byKey(tree, 'history-show-Helper').attrs['aria-pressed'], 'true');
  assert.equal(tree.filter(n => n.attrs.className === 'ticket-event').length, 1);
});

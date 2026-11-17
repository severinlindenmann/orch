'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const helpers = require(path.join(WEB, 'helpers.js'));
const ticketSrc = fs.readFileSync(path.join(WEB, 'pages/ticket.js'), 'utf8');
const listSrc = fs.readFileSync(path.join(WEB, 'pages/tickets.js'), 'utf8');
const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false), setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, dataset:{}});
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
const kitWindow = () => { const w = {}; vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8'), vm.createContext({window:w})); return w.UI; };
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];

function listCtx(extra = {}) {
  const c = {h, window:{DashHelpers:helpers, UI:{...kitWindow(), ...require('./kit_state.js')}}, array:v => Array.isArray(v) ? v : [], clean:String, questions:t => (t.questions || []).filter(q => q.answer == null),
    shown:t => t, chip:(t, cls) => h('span', {className:'chip ' + cls}, t), statusChip:t => h('span', {className:'chip'}, t.status), state:{runs:{}}, starting:new Set(),
    needsList:() => [], tickets:() => [], name:v => String(v || ''), location:{hash:'#tickets'}, snapshot:false, href:id => '#t/' + id, render(){}, localStorage:{getItem:() => null},
    button:(label, cls, fn) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = fn; return b; }, ...extra};
  vm.createContext(c); vm.runInContext(listSrc, c); return c;
}
test('Dash 21: no chip when it matches the section; Done shows the finish day; next step only with the actual question', () => {
  const c = listCtx();
  assert.equal(c.ticketAttentionChip({status:'review'}, 'review'), null);
  assert.equal(text(c.ticketAttentionChip({status:'review'}, 'active')), 'review');
  assert.equal(c.ticketAttentionChip({status:'waiting', questions:[{text:'Which?'}]}, 'waiting'), null);
  assert.match(text(c.ticketAttentionChip({status:'done', updated_at:'2026-11-12T10:00:00Z'}, 'done')), /^Finished /);
  assert.doesNotMatch(text(c.ticketNext({id:'r', status:'review'})), /Next step|Read the result/);
  assert.equal(c.ticketNext({id:'a', status:'active', checklist:[{text:'Draft it'}]}), null);
});
test('ORCH-69: board and list cards carry no Start helper or Resume button; a paused ticket keeps its Paused line', () => {
  const c = listCtx();
  const paused = c.ticketNext({id:'p', status:'open', sessions:[{id:'s1'}], updated_at:'2026-11-12T10:00:00Z'});
  assert.match(text(paused), /^Paused /);
  assert.doesNotMatch(text(paused), /Resume|Start helper/);
  assert.equal(c.ticketNext({id:'n', status:'open'}), null, 'a To do card has no button');
  assert.equal(c.ticketNext({id:'t', status:'open', checklist:[{text:'typed by me'}]}), null, 'typed tasks alone: no button');
});
test('the list takes the finish day from the done history entry, like the ticket page', () => {
  const c = listCtx();
  vm.runInContext(ticketSrc.slice(ticketSrc.indexOf('function ticketDoneEvent'), ticketSrc.indexOf('function ticketDoneLine')), c);
  const t = {status:'done', updated_at:'2026-12-20T10:00:00Z', history:[{at:'2026-11-03T10:00:00Z', text:'open -> done'}]};
  assert.equal(text(c.ticketAttentionChip(t, 'done')), 'Finished ' + c.window.UI.stamp('2026-11-03T10:00:00Z', {time:false}));
});
test('Tickets toolbar: search and a Person choice when there is more than one owner', () => {
  const c = listCtx({tickets:() => [{id:'a', owner:'anna'}, {id:'b', owner:'ben'}]});
  const parts = nodes(h('div', {}, c.ticketFilters()));
  assert.ok(parts.some(n => n.attrs.type === 'search' && n.attrs['aria-label'] === 'Search tickets'));
  assert.ok(parts.some(n => n.attrs['data-key'] === 'ticket-person'), 'a Person choice');
  assert.ok(!parts.some(n => n.attrs.className === 'btn ghost seg'), 'no All / Mine toggle');
});
test('Dash 02: rows, board cards and step names carry no ticket key', () => {
  assert.doesNotMatch(listSrc, /t\.key \+ ' '|mono key|part\.key/);
  const c = {clean:String}; vm.createContext(c);
  vm.runInContext(ticketSrc.slice(ticketSrc.indexOf('const partName'), ticketSrc.indexOf('function ticketAddStep')) + '\nthis.partName = partName;', c);
  assert.equal(c.partName({key:'PIL-54', title:'Plan'}), 'Plan');
});
test('Dash 50: a change request task reads as the change, with what you asked below', () => {
  const c = {}; vm.createContext(c);
  vm.runInContext(ticketSrc.slice(ticketSrc.indexOf('function changeTask'), ticketSrc.indexOf('function taskRows')), c);
  assert.deepEqual({...c.changeTask('Change: Please add a rain plan.')}, {title:'Add a rain plan', asked:'Please add a rain plan.'});
  assert.deepEqual({...c.changeTask('Please add a rain plan.', 'change_request')}, {title:'Add a rain plan', asked:'Please add a rain plan.'});  // new: structured origin
  assert.equal(c.changeTask('Write the report'), null);
  assert.equal(c.changeTask('Change: x', 'other')?.asked, 'x');
});
test('Dash 20/23/34/02: Tasks tab, Resume when paused, Properties without Details toggles', () => {
  const t = {id:'t1', key:'PIL-54', title:'Report', status:'open', sessions:[{id:'s1', last_used:'2026-11-12T09:00:00Z'}], checklist:[{id:'c1', text:'Change: Please add a rain plan.', done:true}], note:'Remember', created_at:'2026-11-10T09:00:00Z', updated_at:'2026-11-12T09:00:00Z'};
  const ctx = {repeatsAddon:() => null, window:{UI:{...require("./kit_state.js")}, DashHelpers:helpers}, document:{addEventListener(){}}, addEventListener(){}, h,
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => v || '', act:async () => ({ok:true}),
    el:(tag, cls, txt) => h(tag, {className:cls}, txt), fragment:(...kids) => h('fragment', {}, kids),
    card:(key, title, suffix, kids) => h('section', {'data-key':key}, title, suffix, kids), emptyRow:x => h('p', {}, x),
    questions:x => (x.questions || []).filter(q => q.answer == null), capitalise:v => v, date:() => '', time:() => '', ticketTabs:new Map([['t1', 'tasks']]), addons:() => [], tickets:() => [t], ticketOf:() => t,
    statusChip:x => h('span', {}, x.status), chip:x => h('span', {}, x), href:id => '#t/' + id, MOVE_CHOICES:[], main:{querySelector:() => null}, locks:new Set()};
  vm.createContext(ctx); vm.runInContext(ticketSrc, ctx);
  ctx.snapshot = false; ctx.state = {settings:{}, runs:{}};
  vm.runInContext('loadArtifacts = () => {}; inlineField = (t,f) => h("span", {"data-field":f}, String(t[f] || "")); addTaskRow = () => null; agentBar = () => null; sharedFolderLine = () => null; copyLine = () => null; liveSessionStrip = () => null; ticketFiles = () => null; addonRows = () => null; ticketLinks = () => null; linksCard = () => null; fieldSections = () => null; ticketHistoryPanel = () => null; artifactData.set("t1", {data:{files:[]}});', ctx);
  const tree = ctx.detail(t), all = nodes(tree), body = text(tree);
  assert.ok(all.some(n => n.attrs.id === 'ticket-tab-tasks'), 'Steps tab exists');
  assert.equal(text(all.find(n => n.attrs.id === 'ticket-tab-tasks')).replace(/\d+/g, '').trim(), 'Steps', 'owner fb: the tab says Steps, not Tasks');
  assert.ok(!/\bTasks\b/.test(body), 'no "Tasks" word on the ticket page');
  assert.deepEqual(all.filter(n => n.attrs.role === 'tab').map(n => n.attrs['data-tab']), ['overview', 'tasks', 'files', 'activity']);
  assert.equal(all.filter(n => n.attrs['data-key'] === 'parts').length, 0);
  assert.ok(all.find(n => n.attrs['data-key'] === 'ticket-resume') && /Resume/.test(body) && !/Start helper/.test(body));
  assert.ok(!all.find(n => n.attrs.id === 'ticket-panel-tasks').attrs.hidden, 'the Tasks choice opens the Tasks tab');
  assert.ok(nodes(all.find(n => n.attrs.id === 'ticket-panel-overview')).some(n => n.attrs['data-field'] === 'note'), 'Note in Overview');
  assert.match(text(all.find(n => n.attrs.className === 'side-panel properties')), /Properties.*Owner.*Due.*Done when/);
  assert.ok(!all.some(n => n.tag === 'details' && /Details/.test(text(n))) && !/Technical details|\+ Add detail/.test(body), 'no Details toggles');
  assert.equal(body.split('PIL-54').length, 2, 'the key shows once, before the title (ORCH-58); no footer line with it under Properties (linked work, 15 Nov)');
  assert.match(body, /Add a rain planYou asked: Please add a rain plan\./);
  const typed = {...t, id:'t2', sessions:[]};
  ctx.tickets = () => [typed];
  const fresh = text(ctx.detail(typed));
  assert.ok(/Start helper/.test(fresh) && !/Resume/.test(fresh), 'tasks typed before any helper ran: Start helper, not Resume');
});

test('ORCH-49: Properties shows the Model with Sonnet / Opus / Let orch pick, and a change sends ticket.model', async () => {
  const sent = [];
  const ctx = {window:{DashHelpers:helpers, orch:{toast(){}}}, document:{addEventListener(){}}, addEventListener(){}, h, array:v => Array.isArray(v) ? v : [],
    clean:v => String(v ?? ''), el:(tag, cls, txt) => h(tag, {className:cls}, txt), act:async (op, a) => { sent.push([op, a]); return {ok:true}; }};
  vm.createContext(ctx); vm.runInContext(ticketSrc, ctx); ctx.snapshot = false;
  const picked = ctx.modelField({id:'t1', model:{name:'opus', by:'orch', why:'it mentions design'}});
  assert.equal(picked.tag, 'select');
  assert.deepEqual(picked.children.map(o => o.attrs.value), ['auto', 'sonnet', 'opus']);
  assert.equal(text(picked.children[0]), 'Let orch pick (Opus)');
  assert.equal(picked.value, 'auto');
  assert.match(picked.attrs.title, /Opus \(picked by orch: it mentions design\)/);
  const mine = ctx.modelField({id:'t1', model:{name:'sonnet', by:'human:severin'}});
  assert.equal(mine.value, 'sonnet');
  mine.value = 'opus'; await mine.onchange();
  assert.equal(JSON.stringify(sent.pop()), JSON.stringify(['ticket.model', {ticket:'t1', model:'opus'}]));
  assert.equal(ctx.modelField({id:'t1', model:{name:'fable', by:'human:x'}}).value, 'auto', 'an unknown model is not shown as chosen');
  ctx.snapshot = true;
  assert.equal(text(ctx.modelField({id:'t1'})), 'orch picks it when work starts');
});
test('ORCH-62: every ticket sits in its own status group, so group counts match the rows and the filters', () => {
  const items = [
    {id:'p', status:'active', title:'Parent'},
    {id:'c1', parent:'p', status:'done'}, {id:'c2', parent:'p', status:'open'}, {id:'c3', parent:'p', status:'review'},
    {id:'w', status:'active'}, {id:'q', status:'waiting', questions:[{text:'Which?'}]},
    {id:'b', status:'waiting', waiting_on:{kind:'ticket', ref:'w'}},
  ];
  const c = listCtx({tickets:() => items});
  const groups = JSON.parse(JSON.stringify(Object.fromEntries(c.ticketGroups(items).map(g => [g.status, g.tickets.map(t => t.id)]))));
  assert.deepEqual(groups.active, ['p', 'w']);
  assert.deepEqual(groups.done, ['c1']);
  assert.deepEqual(groups.open, ['c2']);
  assert.deepEqual(groups.review, ['c3']);
  assert.deepEqual(groups.waiting, ['q'], 'only a ticket with an open question needs you');
  assert.deepEqual(groups.blocked, ['b']);
  assert.equal(c.ticketGroups(items).find(g => g.status === 'blocked').title, 'Waiting for another ticket');
  assert.equal(items.filter(t => c.inView(t, 'working')).length, groups.active.length, 'Working filter = Working group');
  assert.ok(!c.inView(items[6], 'needs-you'), 'waiting for another ticket is not Needs you');
  assert.ok(c.inView(items[5], 'needs-you'));
});
test('ORCH-62: a ticket waiting for another names it; a time wait says until when', () => {
  const items = [{id:'t_a', key:'ORCH-56', status:'active'}, {id:'b', status:'waiting', waiting_on:{kind:'ticket', ref:'t_a'}}];
  const c = listCtx({tickets:() => items});
  assert.equal(text(c.waitsLine(items[1])), 'Waits for ORCH-56');
  assert.match(text(c.waitsLine({id:'x', status:'waiting', waiting_on:{kind:'time', until:'2026-11-17T08:00:00Z'}})), /^Waits until /);
  assert.equal(c.waitsLine({id:'q', status:'waiting', questions:[{text:'Which?'}]}), null);
  assert.equal(c.ticketGroups([{id:'x', status:'waiting', waiting_on:{kind:'time', until:'2026-11-17T08:00:00Z'}}]).find(g => g.status === 'blocked').title, 'Waiting');
});
test('ORCH-62: steps read 3/4 on one line, never "3 of 4 steps" split over lines', () => {
  const c = listCtx({h:(...a) => Object.assign(h(...a), {style:{}})});
  const cell = c.stepsCell({checklist:[{done:true}, {done:true}, {done:true}, {}]}, {});
  assert.equal(nodes(cell).find(n => /steps-count/.test(n.attrs?.className || '')).children.join(''), '3/4');
  assert.equal(text(c.stepsCell({status:'waiting', questions:[{text:'Which?'}]}, {})), '–', 'no "Question for you" in the steps column');
});
test('ORCH-62: a chip only for an Idle or Stuck helper, with how long nothing ran', () => {
  const idle = {running:true, idle_seconds:18 * 60, helper:{state:'idle'}}, busy = {running:true, helper:{state:'working'}};
  const c = listCtx({state:{runs:{i:idle, w:busy, s:{state:'maybe-stale'}}}});
  const i = c.helperChip({id:'i', status:'active'});
  assert.equal(text(i.chip), 'Idle');
  assert.equal(i.line, 'Nothing running for 18 min');
  assert.equal(text(c.helperChip({id:'s', status:'active'}).chip), 'Stuck');
  assert.equal(c.helperChip({id:'w', status:'active'}), null, 'a working helper gets no chip');
  assert.equal(c.helperChip({id:'n', status:'open'}), null);
  assert.doesNotMatch(listSrc, /'Owner', 'Steps done'|'Status', 'Owner'/, 'no Status or Owner column');
});
test('ORCH-62: an open question reads "Question: ..." under the title', () => {
  const c = listCtx();
  assert.match(text(c.ticketNext({id:'q', status:'waiting', questions:[{text:'Start the run?'}]})), /^Question: /);
});

test('ORCH-156: Properties has Part of: epics first, never itself or a ticket inside it; a change sends ticket.edit with parent', async () => {
  const sent = [];
  const me = {id:'t_me', key:'WS-5', title:'Lanes', status:'active', revision:4};
  const all = [me, {id:'t_old', key:'WS-1', title:'Plain', status:'open'}, {id:'t_epic', key:'WS-2', title:'Ticket flow', status:'open', epic:true},
    {id:'t_kid', key:'WS-6', title:'Inside me', status:'open', parent:'t_me'}, {id:'t_grand', key:'WS-7', title:'Deeper', status:'open', parent:'t_kid'},
    {id:'t_closed', key:'WS-3', title:'Closed', status:'done'}];
  const ctx = {window:{DashHelpers:helpers, orch:{toast(){}}}, document:{addEventListener(){}}, addEventListener(){}, h, array:v => Array.isArray(v) ? v : [],
    clean:v => String(v ?? ''), el:(tag, cls, txt) => h(tag, {className:cls}, txt), tickets:() => all, ticketOf:id => all.find(t => t.id === id),
    act:async (op, a) => { sent.push([op, a]); return {ok:true}; }};
  vm.createContext(ctx); vm.runInContext(ticketSrc, ctx); ctx.snapshot = false;
  const select = ctx.partOfField(me, null);
  assert.equal(select.tag, 'select');
  assert.deepEqual(select.children.map(o => o.attrs.value), ['', 't_epic', 't_old']);
  assert.equal(text(select.children[1]), 'WS-2 Ticket flow (epic)');
  assert.equal(select.value, '');
  select.value = 't_epic'; await select.onchange();
  assert.equal(JSON.stringify(sent.pop()), JSON.stringify(['ticket.edit', {ticket:'t_me', parent:'t_epic', if_revision:4}]));
  const under = ctx.partOfField({...me, parent:'t_epic'}, all[2]);
  assert.equal(under.value, 't_epic');
  under.value = ''; await under.onchange();
  assert.equal(sent.pop()[1].parent, null);
});

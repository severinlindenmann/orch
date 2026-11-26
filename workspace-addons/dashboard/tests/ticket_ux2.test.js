'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const helpers = require(path.join(WEB, 'helpers.js'));
const ticketSrc = fs.readFileSync(path.join(WEB, 'pages/ticket.js'), 'utf8');
const startSrc = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/start.js'), 'utf8');  // the one Start button (ORCH-475)
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
  assert.doesNotMatch(text(paused), /Continue|Start helper/);
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
test('ORCH-2091: the toolbar is layout, filters, search, then the view chips on their own row', () => {
  const c = listCtx({URLSearchParams, iconEl:() => null, tickets:() => [{id:'a', owner:'anna'}, {id:'b', owner:'ben'}]});
  const bar = vm.runInContext('viewToggle()', c);
  assert.deepEqual(bar.children.map(n => n.attrs['data-key'] || n.attrs.className), ['view-toggle', 'ticket-person', 'grow', 'search-field', 'view-chips']);
});
test('ORCH-2091: no tickets at all shows the master empty state with one sentence and New ticket, no toolbar', () => {
  const made = [];
  const state = o => { made.push(o); const b = h('div', {className:'state'}); b.append = k => b.children.push(k); return b; };
  const c = listCtx({newButton:() => h('button', {className:'btn primary', 'data-action':'new'}, 'New ticket')});
  c.window.UI.state = state;
  const box = c.ticketsEmpty();
  assert.equal(made[0].title, 'No tickets yet');
  assert.equal(made[0].text.split(/[.!?](\s|$)/).filter(s => s && s.trim()).length, 1, 'one sentence');
  assert.equal(box.dataset.key, 'empty');
  assert.equal(text(box.children.at(-1)), 'New ticket');
  assert.match(listSrc, /tickets\(\)\.length \? viewToggle\(\) : null/);
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
  vm.createContext(ctx); vm.runInContext(ticketSrc, ctx); vm.runInContext(startSrc, ctx);
  ctx.snapshot = false; ctx.state = {settings:{}, runs:{}};
  vm.runInContext('loadArtifacts = () => {}; inlineField = (t,f) => h("span", {"data-field":f}, String(t[f] || "")); addTaskRow = () => null; agentBar = () => null; sharedFolderLine = () => null; copyLine = () => null; liveSessionStrip = () => null; ticketFiles = () => null; addonRows = () => null; ticketLinks = () => null; linksCard = () => null; fieldSections = () => null; ticketHistoryPanel = () => null; artifactData.set("t1", {data:{files:[]}});', ctx);
  const tree = ctx.detail(t), all = nodes(tree), body = text(tree);
  assert.ok(all.some(n => n.attrs.id === 'ticket-tab-tasks'), 'Tasks tab exists');
  assert.equal(text(all.find(n => n.attrs.id === 'ticket-tab-tasks')).replace(/\d+/g, '').trim(), 'Tasks', 'owner 17 Nov (ORCH-240): the to-do lines are tasks everywhere, the tab too');
  assert.ok(!/\bTasks\b/.test(body), 'no "Tasks" word on the ticket page');
  assert.deepEqual(all.filter(n => n.attrs.role === 'tab').map(n => n.attrs['data-tab']), ['overview', 'tasks', 'files', 'activity']);
  assert.equal(all.filter(n => n.attrs['data-key'] === 'parts').length, 0);
  assert.ok(all.find(n => n.attrs['data-key'] === 'ticket-start') && /Continue/.test(body) && !/Start helper/.test(body))  // ORCH-475: the one Start button says Continue;
  // ORCH-415 (UX D2): a start is outlined, never filled, with its cost in one line above it
  assert.ok(all.find(n => n.attrs['data-key'] === 'ticket-start-pick'), 'the start sits in a cost pick');
  assert.match(text(all.find(n => n.attrs['data-key'] === 'ticket-start-cost')), /paid helper time|estimate about|used so far/);
  assert.ok(!all.some(n => /\bprimary\b/.test(n.attrs.className || '') && /Continue|Start helper/.test(text(n))), 'no filled start');
  assert.equal(all.filter(n => n.tag === 'h2' && /What (was|you) asked/.test(text(n))).length, 1, 'one heading for the ask');
  assert.ok(!all.find(n => n.attrs.id === 'ticket-panel-tasks').attrs.hidden, 'the Tasks choice opens the Tasks tab');
  assert.ok(nodes(all.find(n => n.attrs.id === 'ticket-panel-overview')).some(n => n.attrs['data-field'] === 'note'), 'Note in Overview');
  assert.match(text(all.find(n => n.attrs.className === 'side-panel properties')), /Properties.*Owner.*Due.*Done when/);
  assert.ok(!all.some(n => n.tag === 'details' && /Details/.test(text(n))) && !/Technical details|\+ Add detail/.test(body), 'no Details toggles');
  assert.equal(body.split('PIL-54').length, 2, 'the key shows once, before the title (ORCH-58); no footer line with it under Properties (linked work, 15 Nov)');
  assert.match(body, /Add a rain planYou asked: Please add a rain plan\./);
  const typed = {...t, id:'t2', sessions:[]};
  ctx.tickets = () => [typed];
  const fresh = text(ctx.detail(typed));
  assert.ok(/Start helper/.test(fresh) && !/Continue/.test(fresh), 'tasks typed before any helper ran: Start helper, not Continue');
  ctx.justStarted = id => id === 't2';  // ORCH-250: Start was just pressed, the server has no session yet
  const started = text(ctx.detail(typed));
  assert.ok(!/Start helper|Not started/.test(started), 'right after Start the page never falls back to Not started / Start helper');
});

test('ORCH-49: Properties shows the Model with Sonnet / Opus / Auto, and a change sends ticket.model', async () => {
  const sent = [];
  const ctx = {window:{DashHelpers:helpers, orch:{toast(){}}}, document:{addEventListener(){}}, addEventListener(){}, h, array:v => Array.isArray(v) ? v : [],
    clean:v => String(v ?? ''), el:(tag, cls, txt) => h(tag, {className:cls}, txt), act:async (op, a) => { sent.push([op, a]); return {ok:true}; }};
  vm.createContext(ctx); vm.runInContext(ticketSrc, ctx); vm.runInContext(startSrc, ctx); ctx.snapshot = false;
  const field = ctx.modelField({id:'t1', model:{name:'opus', by:'orch', why:'it mentions design'}});
  const pick = f => f.children[0];
  const picked = pick(field);
  assert.equal(picked.tag, 'select');
  assert.deepEqual(picked.children.map(o => o.attrs.value), ['auto', 'haiku', 'sonnet', 'opus', 'fable']);
  // ORCH-300 item 31: plain choices, the model names only behind More
  assert.deepEqual(picked.children.map(text), ['Auto', 'Fastest', 'Faster', 'Stronger', 'Drafts to pick from']);
  assert.equal(picked.value, 'auto');
  const more = field.children[1];
  assert.equal(more.tag, 'details');
  assert.equal(text(more.children[0]), 'More');
  assert.match(text(more), /Opus \(picked by orch: it mentions design\)/);
  const mine = pick(ctx.modelField({id:'t1', model:{name:'sonnet', by:'human:severin'}}));
  assert.equal(mine.value, 'sonnet');
  mine.value = 'opus'; await mine.onchange();
  assert.equal(JSON.stringify(sent.pop()), JSON.stringify(['ticket.model', {ticket:'t1', model:'opus'}]));
  assert.equal(pick(ctx.modelField({id:'t1', model:{name:'fable', by:'human:x'}})).value, 'fable', 'ORCH-257: Fable is a choice');
  assert.equal(pick(ctx.modelField({id:'t1', model:{name:'haiku', by:'human:x'}})).value, 'haiku', 'ORCH-257: Haiku is a choice');
  assert.equal(pick(ctx.modelField({id:'t1', model:{name:'gpt', by:'human:x'}})).value, 'auto', 'an unknown model is not shown as chosen');
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
  vm.createContext(ctx); vm.runInContext(ticketSrc, ctx); vm.runInContext(startSrc, ctx); ctx.snapshot = false;
  const select = ctx.partOfField(me, null);
  assert.equal(select.tag, 'select');
  assert.deepEqual(select.children.map(o => o.attrs.value), ['', 't_epic', 't_old']);
  assert.equal(text(select.children[1]), 'WS-2 Ticket flow (has parts)');
  assert.equal(select.value, '');
  select.value = 't_epic'; await select.onchange();
  assert.equal(JSON.stringify(sent.pop()), JSON.stringify(['ticket.edit', {ticket:'t_me', parent:'t_epic', if_revision:4}]));
  const under = ctx.partOfField({...me, parent:'t_epic'}, all[2]);
  assert.equal(under.value, 't_epic');
  under.value = ''; await under.onchange();
  assert.equal(sent.pop()[1].parent, null);
});
test('ORCH-157: a Group choice lists the tickets that have parts, and picking one keeps only that group', () => {
  const rows = [{id:'e', title:'Epic', status:'open'}, {id:'p1', title:'Part', parent:'e', status:'open'}, {id:'x', title:'Other', status:'open'}];
  const c = listCtx({tickets:() => rows});
  const sel = nodes(h('div', {}, c.ticketFilters())).find(n => n.attrs['data-key'] === 'ticket-group');
  assert.ok(sel, 'a Part of choice');
  assert.match(JSON.stringify(sel), /Part of/); assert.match(JSON.stringify(sel), /Any ticket/);  // owner 17 Nov (ORCH-240)
  assert.doesNotMatch(JSON.stringify(sel), /All groups/);
  assert.deepEqual(c.filterTickets(rows, '', false, '', '', '', 'e').map(t => t.id), ['e', 'p1']);
  assert.equal(c.filterTickets(rows, '', false).length, 3);
});
test('ORCH-157: the Backlog view keeps only backlog tickets', () => {
  const c = listCtx();
  assert.deepEqual(c.filterTickets([{id:'a', status:'open'}, {id:'b', status:'active'}], '', false, '', '', 'backlog').map(t => t.id), ['a']);
});

test('ORCH-156: a lane keeps the person\'s order; Move up / Move down and a drop send the whole lane first to last', async () => {
  const sent = [];
  const st = {runs:{}, tickets:[
    {id:'a', title:'A', status:'ready'}, {id:'b', title:'B', status:'ready'}, {id:'c', title:'C', status:'ready'}, {id:'x', title:'X', status:'open'}]};
  const c = listCtx({state:st, sorted:l => l.slice(), locks:new Set(), changeUnavailable:() => false, changeError:r => r.text,
    act:async (op, a) => { sent.push([op, a]); return {ok:true}; }, render(){}, window:{DashHelpers:helpers, UI:{...kitWindow(), ...require('./kit_state.js')}, orch:{toast(){}}}});
  assert.deepEqual(c.laneTickets('ready').map(t => t.id), ['a', 'b', 'c']);
  await c.laneStep('c', 'ready', -1);
  assert.equal(JSON.stringify(sent.pop()), JSON.stringify(['ticket.order', {lane:'ready', tickets:['a', 'c', 'b']}]));
  assert.deepEqual(c.laneTickets('ready').map(t => t.id), ['a', 'c', 'b'], 'the cards move at once');
  await c.laneStep('a', 'ready', 1);
  assert.deepEqual(sent.pop()[1].tickets, ['c', 'a', 'b']);
  await c.orderInLane('b', 'ready', 'c');  // dropped on C: lands above it
  assert.deepEqual(sent.pop()[1].tickets, ['b', 'c', 'a']);
  await c.orderInLane('b', 'ready', 'b');  // dropped on itself: nothing is sent
  await c.laneStep('b', 'ready', -1);  // already first
  assert.equal(sent.length, 0);
  const items = [...c.laneOrderItems(st.tickets.find(t => t.id === 'b'), 'ready').map(text)];
  assert.deepEqual(items, ['Move down']);
  assert.equal(c.laneOrderItems(st.tickets.find(t => t.id === 'x'), 'open'), null, 'one card alone: no order choices');
});
test('ORCH-156: a failed save puts the cards back and says why', async () => {
  const toasts = [];
  const st = {runs:{}, tickets:[{id:'a', title:'A', status:'ready'}, {id:'b', title:'B', status:'ready'}]};
  const c = listCtx({state:st, sorted:l => l.slice(), locks:new Set(), changeUnavailable:() => false, changeError:r => r.text,
    act:async () => ({ok:false, text:'Saving did not work.'}), render(){}, window:{DashHelpers:helpers, UI:{...kitWindow(), ...require('./kit_state.js')}, orch:{toast:(...x) => toasts.push(x)}}});
  await c.laneStep('b', 'ready', -1);
  assert.deepEqual(c.laneTickets('ready').map(t => t.id), ['a', 'b']);
  assert.deepEqual(toasts[0], ['Saving did not work.', 'error']);
});

test('ORCH-250: Looks good is off while a step is open, and the page says why; wont-do steps do not count', () => {
  const hh = (...a) => Object.assign(h(...a), {append(...k) { this.children.push(...k); }});
  const c = {h:hh, document:{addEventListener(){}}, addEventListener(){}, array:v => Array.isArray(v) ? v : [], locks:new Set(), snapshot:false, render(){}, iconEl:n => n, window:{orch:{toast(){}}}, moveTicket(){},
    ticketButton:(label, cls, fn, attrs = {}) => { const b = hh('button', {className:'btn ' + cls, ...attrs}, label); return b; }};
  vm.createContext(c); vm.runInContext(ticketSrc, c); vm.runInContext(startSrc, c);
  const view = t => nodes(c.ticketChangesEditor(t));
  const open = view({id:'a', status:'review', checklist:[{done:true}, {done:false}]});
  assert.equal(open.find(n => /Looks good/.test(text(n)) && n.tag === 'button').disabled, true);
  assert.match(text(open.find(n => n.attrs['data-key'] === 'ticket-review-open-steps')), /1 step is not finished/);
  const ok = view({id:'b', status:'review', checklist:[{done:true}, {done:false, wont_do:true}]});
  assert.notEqual(ok.find(n => /Looks good/.test(text(n)) && n.tag === 'button').disabled, true);
  assert.ok(!ok.some(n => n.attrs['data-key'] === 'ticket-review-open-steps'));
});

// ---- ORCH-236 (bug hunt round 2 on the Tickets page and the ticket page)
test('ORCH-236: the Needs you view lists exactly what the Needs you number counts', () => {
  const items = [{id:'q', status:'waiting', questions:[{id:'q1', text:'Which?'}]}, {id:'r', status:'review'},
    {id:'d', status:'done', bring_back:{state:'waiting'}}, {id:'a', status:'active', bring_back:{state:'waiting'}}, {id:'w', status:'active'}];
  const c = listCtx({tickets:() => items});
  const rows = [{id:'core:q', ticket:'q', answer:{question:'q1'}}];
  const counted = helpers.needsYouCount(rows, items.filter(t => t.status === 'review'));
  assert.equal(items.filter(t => c.inView(t, 'needs-you')).length, counted, 'header number = filter rows');
});
test('ORCH-236: a key typed without its dash finds the ticket ("dem36", "dem 36"); 36 is still exact', () => {
  const c = listCtx();
  const items = [{id:'a', key:'DEM-36', title:'Big'}, {id:'b', key:'DEM-136', title:'Other'}];
  const hits = q => c.filterTickets(items, q, false).map(t => t.id).join();
  assert.equal(hits('dem36'), 'a');
  assert.equal(hits('DEM 36'), 'a');
  assert.equal(hits('dem-36'), 'a');
  assert.equal(hits('36'), 'a');
});
test('ORCH-236 (owner, 17 Nov): no saved views: only the built-in chips, no + Save view', () => {
  const c = listCtx({URLSearchParams});
  const keys = nodes(c.viewChips()).map(n => n.attrs?.['data-key']).filter(Boolean);
  assert.deepEqual(keys, ['view-chips', 'view-chip-all', 'view-chip-needs-you', 'view-chip-this-week', 'view-chip-stuck', 'view-chip-working', 'view-chip-waiting', 'view-chip-backlog', 'view-chip-done-week']);
  assert.doesNotMatch(listSrc, /Save view|orch\.tickets\.saved/);
});
test('ORCH-236: a task menu offers Rename, Move up, Move down and Remove; an empty Add says so', () => {
  assert.match(ticketSrc, /act\('check\.edit', \{ticket:t\.id, check:task\.id, text, was:task\.text\}\)/);
  assert.match(ticketSrc, /taskAct\('check\.move', \{ticket:t\.id, check:before\.id, after:task\.id\}\)/, 'up = the one above moves after this one');
  assert.match(ticketSrc, /taskAct\('check\.move', \{ticket:t\.id, check:task\.id, after:after\.id\}\)/);
  assert.match(ticketSrc, /taskAct\('check\.remove', \{ticket:t\.id, check:task\.id\}\)/);
  assert.match(ticketSrc, /if \(!text\) \{ window\.orch\.toast\('Type the task first\.', 'error'\)/);
  assert.match(ticketSrc, /\['activity', 'Activity', ticketHistoryEntries\(t, 'All'\)\.length\]/, 'the tab count is every entry, not the People/Helper choice');
});
test('ORCH-1716: the Needs you button counts tickets like its group, even when one ticket holds two questions', () => {
  const c = listCtx();
  const group = [{id:'a', status:'waiting', questions:[{text:'One?'}, {text:'Two?'}]}, {id:'b', status:'waiting', questions:[{text:'Three?'}]}];
  assert.equal(text(c.groupAction('waiting', group, false)), 'Answer all 2');
  assert.equal(text(c.groupAction('waiting', group.slice(1), false)), 'Answer 1');
  assert.equal(text(c.groupAction('review', [{id:'r', status:'review'}], false)), 'Check 1 result');
});
test('ORCH-1716: a result to check says Test results on the phone too, not the session Start', () => {
  const c = listCtx({liveFocusButton:() => h('button', {className:'btn outline sm'}, 'Start')});
  assert.equal(text(c.shortSide({id:'r', status:'review'}, {}, 'review')), 'Test results');
  assert.equal(text(c.shortSide({id:'o', status:'open'}, {}, 'open')), 'Start', 'other rows keep the session button');
  assert.equal(text(c.ticketNext({id:'r', status:'review'})), 'Test results', 'the computer row says the same');
});
test('ORCH-1716: the Person choice lists each person once; picking one keeps every spelling of them', () => {
  const rows = [{id:'a', owner:'Severin'}, {id:'b', owner:'severin'}, {id:'c', owner:'lume'}, {id:'d', owner:'owner'}, {id:'e', owner:'human:Anna'}, {id:'f', owner:'agent:claude'}];
  const name = v => String(v ?? '').replace(/^(human|agent):/, '');  // as app.js
  const c = listCtx({tickets:() => rows, name, state:{runs:{}, who:'Severin', login:'lume'}});
  assert.deepEqual(JSON.parse(JSON.stringify(c.ticketOwners(rows))), [['anna', 'Anna'], ['claude', 'claude'], ['severin', 'Severin']]);
  const sel = nodes(h('div', {}, c.ticketFilters())).find(n => n.attrs['data-key'] === 'ticket-person');
  assert.deepEqual(sel.children.map(text), ['Everyone', 'Anna', 'claude', 'Severin']);
  assert.deepEqual(c.filterTickets(rows, '', false, 'Severin', 'severin').map(t => t.id), ['a', 'b', 'c', 'd']);
  assert.equal(c.ownerKey(' Human:Severin ', 'Severin', 'lume'), 'severin');
  assert.deepEqual(c.filterTickets(rows, '', false, 'Severin', 'Severin').map(t => t.id), ['a', 'b', 'c', 'd'], 'an old link with the spelling still works');
  const solo = listCtx({tickets:() => rows, name, state:{runs:{}}});
  assert.deepEqual([...solo.ticketOwners(rows).map(([k]) => k)], ['anna', 'claude', 'lume', 'owner', 'severin'], 'nobody picked: only case counts');
});
test('ORCH-1716: the Part of choice shortens long titles with an ellipsis, never mid-word without one', () => {
  const rows = [{id:'e', title:'Add-on: subscriptions, API credits, limits and history', status:'open'}, {id:'p', title:'Part', parent:'e', status:'open'}];
  const c = listCtx({tickets:() => rows});
  const sel = nodes(h('div', {}, c.ticketFilters())).find(n => n.attrs['data-key'] === 'ticket-group');
  const label = text(sel.children[1]);
  assert.ok(label.endsWith('…') && label.length <= 40, label);
});

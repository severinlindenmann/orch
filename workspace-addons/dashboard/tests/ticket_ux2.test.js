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
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];

function listCtx(extra = {}) {
  const c = {h, window:{DashHelpers:helpers}, array:v => Array.isArray(v) ? v : [], clean:String, questions:t => (t.questions || []).filter(q => q.answer == null),
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
test('Dash 23: a ticket a helper worked on that is not running offers Resume with a Paused line', () => {
  const c = listCtx();
  assert.match(text(c.ticketNext({id:'p', status:'open', sessions:[{id:'s1'}], updated_at:'2026-11-12T10:00:00Z'})), /^Paused .*Resume$/);
  assert.equal(text(c.ticketNext({id:'n', status:'open'})), 'Start helper');
  assert.equal(text(c.ticketNext({id:'t', status:'open', checklist:[{text:'typed by me'}]})), 'Start helper', 'typed tasks alone are not paused');
});
test('the list takes the finish day from the done history entry, like the ticket page', () => {
  const c = listCtx();
  vm.runInContext(ticketSrc.slice(ticketSrc.indexOf('function ticketDoneEvent'), ticketSrc.indexOf('function ticketDoneLine')), c);
  const t = {status:'done', updated_at:'2026-12-20T10:00:00Z', history:[{at:'2026-11-03T10:00:00Z', text:'open -> done'}]};
  assert.equal(text(c.ticketAttentionChip(t, 'done')), 'Finished ' + new Date('2026-11-03T10:00:00Z').toLocaleDateString(undefined, {weekday:'short', day:'numeric', month:'short'}));
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
  const ctx = {repeatsAddon:() => null, window:{DashHelpers:helpers}, document:{addEventListener(){}}, addEventListener(){}, h,
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => v || '', act:async () => ({ok:true}),
    el:(tag, cls, txt) => h(tag, {className:cls}, txt), fragment:(...kids) => h('fragment', {}, kids),
    card:(key, title, suffix, kids) => h('section', {'data-key':key}, title, suffix, kids), emptyRow:x => h('p', {}, x),
    questions:x => (x.questions || []).filter(q => q.answer == null), capitalise:v => v, date:() => '', time:() => '', ticketTabs:new Map([['t1', 'tasks']]), addons:() => [], tickets:() => [t], ticketOf:() => t,
    statusChip:x => h('span', {}, x.status), chip:x => h('span', {}, x), href:id => '#t/' + id, MOVE_CHOICES:[], main:{querySelector:() => null}, locks:new Set()};
  vm.createContext(ctx); vm.runInContext(ticketSrc, ctx);
  ctx.snapshot = false; ctx.state = {settings:{}, runs:{}};
  vm.runInContext('loadArtifacts = () => {}; inlineField = (t,f) => h("span", {"data-field":f}, String(t[f] || "")); addTaskRow = () => null; agentBar = () => null; sharedFolderLine = () => null; copyLine = () => null; liveSessionStrip = () => null; ticketFiles = () => null; addonRows = () => null; ticketLinks = () => null; linksCard = () => null; fieldSections = () => null; ticketHistoryPanel = () => null; artifactData.set("t1", {data:{files:[]}});', ctx);
  const tree = ctx.detail(t), all = nodes(tree), body = text(tree);
  assert.ok(all.some(n => n.attrs.id === 'ticket-tab-tasks'), 'Tasks tab exists');
  assert.deepEqual(all.filter(n => n.attrs.role === 'tab').map(n => n.attrs['data-tab']), ['overview', 'tasks', 'files', 'activity']);
  assert.equal(all.filter(n => n.attrs['data-key'] === 'parts').length, 0);
  assert.ok(all.find(n => n.attrs['data-key'] === 'ticket-paused') && /Resume/.test(body) && !/Start helper/.test(body));
  assert.ok(!all.find(n => n.attrs.id === 'ticket-panel-tasks').attrs.hidden, 'the Tasks choice opens the Tasks tab');
  assert.ok(nodes(all.find(n => n.attrs.id === 'ticket-panel-overview')).some(n => n.attrs['data-field'] === 'note'), 'Note in Overview');
  assert.match(text(all.find(n => n.attrs.className === 'side-panel properties')), /Properties.*Owner.*Due.*Done when/);
  assert.ok(!all.some(n => n.tag === 'details' && /Details/.test(text(n))) && !/Technical details|\+ Add detail/.test(body), 'no Details toggles');
  assert.equal(body.split('PIL-54').length, 2, 'the key appears once, as a quiet line');
  assert.match(body, /Add a rain planYou asked: Please add a rain plan\./);
  const typed = {...t, id:'t2', sessions:[]};
  ctx.tickets = () => [typed];
  const fresh = text(ctx.detail(typed));
  assert.ok(/Start helper/.test(fresh) && !/Resume/.test(fresh), 'tasks typed before any helper ran: Start helper, not Resume');
});

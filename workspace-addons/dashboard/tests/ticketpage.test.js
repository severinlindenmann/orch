const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const helpers = require('../src/orch_dashboard/web/helpers.js');
function context(extra = {}) {
  const ctx = {array:v => Array.isArray(v) ? v : [], h:(tag, attrs, ...children) => ({tag, attrs, children}), iconEl:name => name, window:{DashHelpers:helpers, orch:{toast(){}}}, snapshot:false, changeError:r => r.text, actRetry:(op, args) => ctx.act(op, args()), ...extra};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('// These three icons'), source.indexOf('// Ticket page:')), ctx);
  vm.runInContext(source.slice(source.indexOf('// Ticket-only controls'), source.indexOf('function detail(t)')), ctx);
  return ctx;
}
test('history defaults hide technical steps and combine actor filters', () => {
  const c = context();
  const history = [{by:'human:Pat', text:'Created'}, {by:'agent:Claude', text:'Drafted the plan'}, {by:'agent:Claude', kind:'claimed', text:'Claimed'}, {by:'system', text:'Status open -> active'}, {by:'human:Pat', text:'Edited title'}, {by:'system', text:'Status review -> done'}];
  assert.equal(c.ticketHistoryEntries({history}).length, 4);
  assert.equal(c.ticketHistoryEntries({history}, 'People').length, 2);
  assert.equal(c.ticketHistoryEntries({history}, 'Agent').length, 1);
  assert.equal(c.ticketHistoryEntries({history}, 'Agent', true).length, 2);
  for (const kind of ['answer', 'review-verdict', 'created', 'done']) assert.equal(c.ticketHistoryIsTechnical({kind}), false);
  for (const kind of ['released', 'run', 'session', 'evidence-added']) assert.equal(c.ticketHistoryIsTechnical({kind}), true);
});
test('stepper maps status and who acts', () => {
  const c = context();
  for (const [status, step, who] of [['open','Plan','person'], ['ready','Plan','person'], ['active','Work','agent'], ['waiting','Work',''], ['review','Check','person'], ['done','Done','done']]) {
    assert.deepEqual(JSON.parse(JSON.stringify(c.ticketStepState({status}, {running:true}))), {step, who});
  }
  assert.equal(c.ticketStepState({status:'active', questions:[{}]}, {running:true}).who, 'person');
  assert.equal(c.ticketStepState({status:'active'}, {}).who, '');
});
test('warmth and phone are feature detected', () => {
  const c = context();
  assert.equal(c.ticketWarmth({}, {}, {}), null);
  assert.equal(c.ticketWarmth({}, {}, {seconds_left:'60'}), null);
  assert.match(JSON.stringify(c.ticketWarmth({}, {}, {seconds_left:3120})), /52 min/);
  assert.match(JSON.stringify(c.ticketWarmth({warmth:{seconds_left:-3}}, {}, {})), /0 min/);
  assert.equal(c.ticketPhone({}), null);
  assert.match(JSON.stringify(c.ticketPhone({sent_to_phone:true})), /Also sent to your phone/);
  assert.match(JSON.stringify(c.ticketPhone({delivered:true})), /Delivered to your phone/);
});
test('empty change notes send nothing; notes save before status changes', async () => {
  const calls = [], c = context({act:async (op, args) => { calls.push([op, args]); return {ok:true}; }, ticketOf:() => ({revision:3})});
  assert.equal(await c.ticketSendChanges({id:'t_one'}, '  '), false);
  assert.equal(calls.length, 0);
  assert.equal(await c.ticketSendChanges({id:'t_one'}, 'Fix the date'), true);
  assert.equal(calls[0][0], 'check.add'); assert.equal(calls[0][1].text, 'Change: Fix the date');
  assert.equal(calls[1][0], 'ticket.patch'); assert.equal(calls[1][1].data.status, 'active'); assert.equal(calls[1][1].if_revision, 3);
});
test('classic script loads before state and snapshot detail stays read-only inside its wrapper', () => {
  const h = (tag, attrs = {}, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false)});
  const ctx = {window:{DashHelpers:helpers}, document:{addEventListener(){}}, addEventListener(){}, h,
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => String(v || '').replace(/^(human|agent):/, ''),
    el:(tag, cls, text) => h(tag, {className:cls}, text), fragment:(...children) => h('fragment', {}, children),
    card:(key, title, suffix, children) => h('section', {'data-key':key}, title, suffix, children), emptyRow:text => h('p', {}, text),
    questions:t => (t.questions || []).filter(q => q.answer == null), capitalise:v => v, date:() => '', time:() => '', ticketTabs:new Map(), addons:() => [], tickets:() => [], ticketOf:() => null,
    statusChip:() => h('span', {}, 'Done'), chip:text => h('span', {}, text), href:id => '#ticket/' + id,
    fetch:() => { throw Error('snapshot fetched'); }};
  vm.createContext(ctx); vm.runInContext(source, ctx); // No state or snapshot at script load.
  ctx.snapshot = true; ctx.state = {};
  for (const status of ['open', 'active', 'waiting', 'review', 'done']) {
    const tree = ctx.detail({id:'t_test', title:'Test', status, questions:[{id:'q1', text:'Choose?', options:['Yes']}]});
    assert.equal(tree.tag, 'fragment');
    assert.equal(tree.children[0].attrs.className, 'ticket-page');
    const walk = n => { if (!n || typeof n !== 'object') return; assert.notEqual(n.tag, 'button'); for (const child of n.children || []) walk(child); };
    walk(tree);
  }
});
test('change failures stop before status; snapshot never submits notes', async () => {
  const calls = [], c = context({act:async op => { calls.push(op); return {ok:false, text:'Failed'}; }});
  assert.equal(await c.ticketSendChanges({id:'t_test'}, 'Fix this'), false);
  assert.deepEqual(calls, ['check.add']);
  c.snapshot = true;
  assert.equal(await c.ticketSendChanges({id:'t_test'}, 'Fix this'), false);
  assert.deepEqual(calls, ['check.add']);
});

test('the review buttons show whenever the status is Review, an open question first', () => {
  const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false)}; n.append = (...c) => n.children.push(...c); n.dataset = {}; n.setAttribute = () => {}; n.addEventListener = () => {}; n.classList = {add(){}, remove(){}}; return n; };
  const ctx = {window:{DashHelpers:helpers, orch:{}}, document:{addEventListener(){}}, addEventListener(){}, h, locks:new Set(),
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => String(v || '').replace(/^(human|agent):/, ''),
    el:(tag, cls, text) => h(tag, {className:cls}, text), fragment:(...children) => h('fragment', {}, children),
    card:(key, title, suffix, children) => h('section', {'data-key':key}, title, suffix, children), emptyRow:text => h('p', {}, text),
    questions:t => (t.questions || []).filter(q => q.answer == null), capitalise:v => v, date:() => '', time:() => '', ticketTabs:new Map(), addons:() => [], tickets:() => [], ticketOf:() => null,
    statusChip:() => h('span', {}, 'Ready for review'), chip:text => h('span', {}, text), href:id => '#ticket/' + id, MOVE_CHOICES:[], moveTicket(){}, button:label => h('button', {}, label), locksX:0, loadArtifacts(){}, ticketArtifactPreview:() => null, agentBar:() => null,
    surface:v => v, inlineField:() => null, ticketHistoryPanel:() => null, artifactsPanel:() => null, ticketParts:() => null, taskRows:() => null, addTaskRow:() => null, artifactCount:() => 0,
    linksCard:() => null, fieldSections:() => null, selectTicketTab(){}, ticketLinks:() => null, addonRows:() => null, ticketDoneLine:() => null, ticketStepper:() => null, mountQuestion(){}, state:{runs:{}}, snapshot:false,
    fetch:() => new Promise(() => {})};
  vm.createContext(ctx); vm.runInContext(source, ctx);
  const text = JSON.stringify(ctx.detail({id:'t_test', title:'Test', status:'review', questions:[{id:'q1', text:'Which colour?', options:[]}]}));
  assert.match(text, /Looks good/);
  assert.match(text, /Ask for changes/);
  assert.ok(text.indexOf('Which colour?') < text.indexOf('Looks good'), 'the question comes first');
  assert.match(JSON.stringify(ctx.detail({id:'t_test', title:'Test', status:'review', questions:[]})), /Looks good/);
});

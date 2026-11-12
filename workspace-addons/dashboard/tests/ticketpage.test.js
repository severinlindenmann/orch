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
  assert.equal(c.ticketHistoryEntries({history}, 'Helper').length, 1);
  assert.equal(c.ticketHistoryEntries({history}, 'Helper', true).length, 2);
  assert.equal(c.ticketHistoryWho({by:'agent:Claude'}), 'Helper', 'a person reads "Helper", never "Agent"');
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
test('empty change notes send nothing; one call sends the note and the status', async () => {
  const calls = [], c = context({act:async (op, args) => { calls.push([op, args]); return {ok:true}; }, ticketOf:() => ({revision:3})});
  assert.equal(await c.ticketSendChanges({id:'t_one'}, '  '), false);
  assert.equal(calls.length, 0);
  assert.equal(await c.ticketSendChanges({id:'t_one'}, 'Fix the date'), true);
  assert.equal(JSON.stringify(calls), JSON.stringify([['ticket.changes', {ticket:'t_one', text:'Fix the date'}]])); // no separate patch to Working
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
test('a failed change request shows a plain error; snapshot never submits notes', async () => {
  const calls = [], c = context({act:async op => { calls.push(op); return {ok:false, text:'Failed'}; }});
  assert.equal(await c.ticketSendChanges({id:'t_test'}, 'Fix this'), false);
  assert.deepEqual(calls, ['ticket.changes']);
  c.snapshot = true;
  assert.equal(await c.ticketSendChanges({id:'t_test'}, 'Fix this'), false);
  assert.deepEqual(calls, ['ticket.changes']);
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
    repeatsAddon:() => null, fetch:() => new Promise(() => {})};
  vm.createContext(ctx); vm.runInContext(source, ctx);
  const text = JSON.stringify(ctx.detail({id:'t_test', title:'Test', status:'review', questions:[{id:'q1', text:'Which colour?', options:[]}]}));
  assert.match(text, /Accept/);
  assert.match(text, /Ask for changes/);
  assert.ok(text.indexOf('Which colour?') < text.indexOf('Accept'), 'the question comes first');
  assert.match(JSON.stringify(ctx.detail({id:'t_test', title:'Test', status:'review', questions:[]})), /Accept/);
  ctx.state.settings = {agents:[{name:'claude', label:'Claude', chosen:true}]};
  vm.runInContext("artifactData.set('t_test', {at:Date.now(), data:{files:[{name:'next-steps.html', size:24576, mtime:'2026-11-09T07:30:00Z'}]}})", ctx);
  const nodes = n => n && typeof n === 'object' ? [n, ...n.children.flatMap(nodes)] : [];
  const all = nodes(ctx.detail({id:'t_test', title:'Test', status:'review', questions:[]}));
  const review = all.find(n => n.attrs.className === 'card next-step');
  const reviewText = JSON.stringify(review);
  assert.match(reviewText, /Claude finished: Next steps/);
  assert.equal((reviewText.match(/Next steps/g) || []).length, 2, 'title once, tile once, no preview box');
  assert.doesNotMatch(reviewText, /Completed\.|ticket-preview|ticket-result/);
  const tile = nodes(review).find(n => n.attrs.className === 'ticket-review-tile');
  assert.match(JSON.stringify(tile), /Next steps/);
  assert.doesNotMatch(JSON.stringify(tile), /\.html/);
  assert.match(JSON.stringify(tile), /Page · 24 KB/);
  assert.equal(nodes(tile).filter(n => n.tag === 'button').length, 1);
  assert.ok(nodes(review).some(n => n.children.some(c => typeof c === 'string' && c.startsWith('Completed '))));

});
test('Repeat (not Copy ticket) shows in the ticket menu only when the repeats add-on is on', () => {
  const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false)}; n.append = (...c) => n.children.push(...c); n.dataset = {}; n.setAttribute = () => {}; n.addEventListener = () => {}; n.classList = {add(){}, remove(){}}; return n; };
  const ctx = {window:{DashHelpers:helpers, orch:{}}, document:{addEventListener(){}}, addEventListener(){}, h, locks:new Set(),
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => String(v || '').replace(/^(human|agent):/, ''),
    el:(tag, cls, text) => h(tag, {className:cls}, text), fragment:(...children) => h('fragment', {}, children),
    card:(key, title, suffix, children) => h('section', {'data-key':key}, title, suffix, children), emptyRow:text => h('p', {}, text),
    questions:t => (t.questions || []).filter(q => q.answer == null), capitalise:v => v, date:() => '', time:() => '', ticketTabs:new Map(), addons:() => [], tickets:() => [], ticketOf:() => null,
    statusChip:() => h('span', {}, 'Ready for review'), chip:text => h('span', {}, text), href:id => '#ticket/' + id, MOVE_CHOICES:[], moveTicket(){}, button:label => h('button', {}, label), locksX:0, loadArtifacts(){}, ticketArtifactPreview:() => null, agentBar:() => null,
    surface:v => v, inlineField:() => null, ticketHistoryPanel:() => null, artifactsPanel:() => null, ticketParts:() => null, taskRows:() => null, addTaskRow:() => null, artifactCount:() => 0,
    linksCard:() => null, fieldSections:() => null, selectTicketTab(){}, ticketLinks:() => null, addonRows:() => null, ticketDoneLine:() => null, ticketStepper:() => null, mountQuestion(){}, state:{runs:{}}, snapshot:false,
    repeatsAddon:() => null, fetch:() => new Promise(() => {})};
  vm.createContext(ctx); vm.runInContext(source, ctx);
  const t = {id:'t_test', title:'Test', status:'open', questions:[]};
  assert.doesNotMatch(JSON.stringify(ctx.detail(t)), /Copy ticket|Repeat…/);
  ctx.repeatsAddon = () => 'automation';
  const on = JSON.stringify(ctx.detail(t));
  assert.doesNotMatch(on, /Copy ticket/);
  assert.match(on, /Repeat…/);
});

test('parts resolve parent fields, case-insensitive keys and legacy arrays once', () => {
  const p = {id:'t_parent', key:'PLAN-1', children:{total:2, closed:1, open:1}};
  const a = {id:'t_a', parent:p.id}, b = {id:'t_b', parent:'plan-1'};
  assert.deepEqual(helpers.childrenOf([p,a,b], p), [a,b]);
  assert.equal(helpers.parentOf([p,a,b], b), p);
  p.children = [a.id, b.id, p.id];
  assert.deepEqual(helpers.childrenOf([p,a,b,a], p), [a,b]);
  assert.equal(helpers.parentOf([p,{id:'t_a'}], {id:'t_a'}), p);
});
test('agent label uses adapter settings for missing and old claims', () => {
  const settings = {agents:[{name:'claude',label:'Claude',chosen:true}]};
  for (const claim of [undefined, {}, {agent:'claude'}, {label:'claude'}]) assert.equal(helpers.agentLabel(settings, claim), 'Claude');
  assert.equal(helpers.agentLabel(settings, {label:'Custom'}), 'Custom');
  assert.equal(helpers.agentLabel({agents:[{name:'custom',label:'Studio'}]}), 'Studio');
  assert.equal(helpers.agentLabel({}, {}), 'Helper');
  assert.equal(helpers.agentLabel(settings, {agent:'codex'}), 'Codex');
});
test('task outcomes and result cards use plain text without sizes', () => {
  const ev = {type:'file',ref:'seating-plan.md',text:'seating-plan.md · 109 B',by:'agent:claude'};
  assert.equal(helpers.outcome({done:true,evidence:[]}), 'Completed.');
  assert.equal(helpers.outcome({done:true,evidence:[ev]}), 'Seating plan');
  const c = context({clean:String, ticketActor:() => 'Claude', ticketPreviewTile:() => 'preview', ticketButton:l => l, previewFile(){}, snapshot:false, state:{}});
  vm.runInContext(source.slice(source.indexOf('const KIND_WORD'), source.indexOf('function artifactsPanel')), c);
  const card = c.ticketResultCard({id:'t_test'}, ev);
  const text = JSON.stringify(card);
  assert.match(text, /ticket-result/);
  assert.doesNotMatch(text, /109|Agent says|Completed/);
});

test('next question stays above every tab and Answer scrolls and focuses it', () => {
  const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false)});
  const t = {id:'t_parent', title:'Plan', status:'waiting', questions:[{id:'q1',text:'First?'},{id:'q2',text:'Second?'}]};
  let scrolled = false, focused = false;
  const ctx = {repeatsAddon:() => null, window:{DashHelpers:helpers}, document:{addEventListener(){}}, addEventListener(){}, h,
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => v || '',
    el:(tag, cls, text) => h(tag,{className:cls},text), fragment:(...kids) => h('fragment',{},kids),
    card:(key,title,suffix,kids) => h('section',{'data-key':key},title,suffix,kids), emptyRow:text => h('p',{},text),
    questions:t => t.questions || [], capitalise:v => v, date:() => '', time:() => '', ticketTabs:new Map(), addons:() => [], tickets:() => [t], ticketOf:() => t,
    statusChip:() => h('span',{},'Waiting'), chip:text => h('span',{},text), href:id => '#ticket/'+id, MOVE_CHOICES:[],
    main:{querySelector:() => ({scrollIntoView(){scrolled=true;},querySelector:() => ({focus(){focused=true;}})})}};
  vm.createContext(ctx); vm.runInContext(source,ctx);
  ctx.snapshot=false; ctx.state={settings:{agents:[{name:'claude',label:'Claude',chosen:true}]}};
  vm.runInContext("loadArtifacts = () => {}; inlineField = (t,f) => t[f]; addTaskRow = () => null; agentBar = () => null;",ctx);
  const nodes = n => typeof n === 'object' && n ? [n,...n.children.flatMap(nodes)] : [];
  for (const tab of ['overview','tasks','questions','artifacts','history']) {
    ctx.ticketTabs.set(t.id,tab);
    const all = nodes(ctx.detail(t));
    assert.equal(all.filter(n => n.attrs.className === 'card next-step next-question').length,1);
    assert.equal(all.filter(n => n.attrs['data-question'] === 'q1').length,1);
    assert.equal(all.filter(n => n.attrs['data-key'] === 'parts').length,1);
    assert.ok(all.some(n => n.children.includes('No parent ticket')));
    all.find(n => n.tag === 'button' && n.children.includes('Answer')).onclick();
  }
  assert.ok(scrolled && focused);
});

test('result preview tiles keep HTML static and bound text excerpts', async () => {
  const h = (tag, attrs = {}, ...children) => ({tag, attrs, children, append(...kids){this.children.push(...kids);}});
  const ctx = {h, window:{DashHelpers:helpers}, snapshot:false, route:() => ({kind:'home'}), render(){}, URL, TextDecoder, fetch:async () => new Response('line\n'.repeat(1000),{headers:{'Content-Type':'text/plain'}})};
  vm.createContext(ctx);
  vm.runInContext(source.slice(source.indexOf('const PREVIEW_EXT'),source.indexOf('function loadArtifacts')),ctx);
  vm.runInContext(source.slice(source.indexOf('const ticketPreviewText'),source.indexOf('function ticketResultCard')),ctx);
  const html = ctx.ticketPreviewTile({id:'t_test'},{name:'plan.html'});
  assert.doesNotMatch(JSON.stringify(html), /iframe|<html|src/);
  const text = ctx.ticketPreviewTile({id:'t_test'},{name:'plan.md'});
  await new Promise(resolve => setTimeout(resolve,20));
  const pre = text.children.find(n => n.tag === 'pre');
  assert.ok(pre);
  assert.ok(pre.children[0].length <= 2048);
  assert.ok(pre.children[0].split('\n').length <= 8);
});

test('task proof chips: only plain evidence files and http(s) links get a chip, and the summary is the task line', () => {
  const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false)});
  const c = context({h, snapshot:false, safeHref:u => u, array:v => Array.isArray(v) ? v : [], clean:String, previewFile(){}, proofLabel:ev => ev.ref});
  vm.runInContext(source.slice(source.indexOf('const KIND_WORD'), source.indexOf('function ticketResultCard')), c);
  vm.runInContext(source.slice(source.indexOf('// A small chip per proof'), source.indexOf('function taskRows')), c);
  vm.runInContext('globalThis.evidenceFile = evidenceFile', c);
  const t = {id:'t_a'}, base = '.orch/tickets/t_a/evidence/';
  const hostile = ['../../t_b/artifacts/x.md', 'a/../../b', '/etc/passwd', 'a\\b.txt', 'a\0b', 'C:x.txt', 'a//b', './a.txt'];
  for (const name of hostile) assert.equal(c.evidenceFile(t, {type:'file', ref:base + name}), null, name);
  assert.equal(JSON.stringify(c.evidenceFile(t, {type:'file', ref:base + 'ok/plan.md', at:'x'})), JSON.stringify({name:'ok/plan.md', mtime:'x'}));
  assert.equal(c.evidenceFile(t, {type:'file', ref:'.orch/tickets/t_b/evidence/x.md'}), null);
  const row = ev => JSON.stringify(c.taskProofChips(t, {evidence:[ev]}));
  assert.equal(row({type:'url', ref:'javascript:alert(1)'}), 'null');
  assert.equal(row({type:'url', ref:'data:text/html,x'}), 'null');
  assert.match(row({type:'url', ref:'HTTPS://example.com/x'}), /example\.com/);
  assert.equal(row({type:'file', ref:base + '../x'}), 'null');
  // the summary of the proof is the task line, even when a later proof has none
  const task = {done:true, evidence:[{type:'file', ref:base + 'a.md', summary:'Connected as Dev Team.'}, {type:'file', ref:base + 'b.png'}]};
  assert.equal(helpers.outcome(task), 'Connected as Dev Team.');
});

test('agent bar shows the hold reason as plain text and hides it when absent', () => {
  const c = context({state:{runs:{t1:{running:true, state:'alive', hold:"Waiting: clear the text in the agent's window.", claim:{agent:'claude', mode:'live'}}}, settings:null}, liveLinkFor:() => null, ticketWarmth:() => null, name:v => v, clean:v => String(v ?? '')});
  vm.runInContext(source.slice(source.indexOf('function agentBar(t)'), source.indexOf('const surface =')), c);
  const bar = JSON.stringify(c.agentBar({id:'t1', checklist:[{state:'doing', text:'Writing the plan'}]}));
  assert.match(bar, /Waiting: clear the text in the agent's window\./);
  assert.doesNotMatch(bar, /Writing the plan/);
  c.state.runs.t1.hold = undefined;
  const bare = JSON.stringify(c.agentBar({id:'t1', checklist:[{state:'doing', text:'Writing the plan'}]}));
  assert.match(bare, /Writing the plan/);
  assert.doesNotMatch(bare, /Waiting:/);
});

test("won't-do tasks render resolved, hide activity and reasons, and reopen", async () => {
  const calls = [], errors = [];
  const h = (tag, attrs = {}, ...kids) => ({tag, attrs, hidden:!!attrs.hidden, children:kids.flat(Infinity).filter(x => x != null && x !== false), setAttribute(k,v){this.attrs[k]=v;}});
  const t = {id:'t_test', checklist:[{id:'c1', text:'Skip this', done:false, wont_do:true, state:'doing', reason:'No longer needed'}]};
  const c = context({h, clean:String, ticketActor:() => '', taskProofChips:() => null, ticketTaskOutcome:helpers.outcome, state:{runs:{}}, locks:new Set(), ticketOf:() => t, render(){}, act:async (op,args) => {calls.push([op,args]); return {ok:true};}});
  c.window.orch.toast = (text) => errors.push(text);
  vm.runInContext(source.slice(source.indexOf('async function toggleTask'), source.indexOf('function localUrl')), c);
  vm.runInContext(source.slice(source.indexOf('function taskRows'), source.indexOf('// "+ Add task"')), c);
  const nodes = n => n && typeof n === 'object' ? [n,...n.children.flatMap(nodes)] : [];
  let all = c.taskRows(t).flatMap(nodes);
  assert.ok(all.some(n => n.attrs.className === 'task-wont' && n.children.includes('Skip this')));
  assert.ok(all.some(n => n.attrs.className === 'chip' && n.children.includes("Won't do")));
  assert.ok(all.some(n => n.tag === 'details' && !n.attrs.open && JSON.stringify(n).includes('No longer needed')));
  assert.doesNotMatch(JSON.stringify(all), /ticket-spinner|Not started yet|Working on this task/);
  assert.equal(t.checklist.filter(helpers.resolved).length, 1);
  assert.equal(helpers.outcome(t.checklist[0]), '');
  assert.equal(helpers.historyLine({text:"Marked c1 as won't do"}, t.checklist), "Marked as won't do: Skip this");
  assert.equal(c.ticketHistoryIsTechnical({kind:'check', text:"Marked c1 as won't do"}), false);
  await all.find(n => n.attrs['data-key'] === 'task-check-c1').onclick();
  assert.equal(JSON.stringify(calls.pop()), JSON.stringify(['check.reopen',{ticket:t.id,check:'c1'}]));
  await all.find(n => n.tag === 'form').onsubmit({preventDefault(){}});
  assert.equal(JSON.stringify(calls.pop()), JSON.stringify(['check.reopen',{ticket:t.id,check:'c1'}]));
  t.checklist[0] = {id:'c1',text:'Try this',done:false};
  all = c.taskRows(t).flatMap(nodes);
  const form = all.find(n => n.tag === 'form'), input = all.find(n => n.tag === 'input');
  assert.equal(form.hidden, true);
  all.find(n => n.attrs['aria-label'] === 'More').onclick();
  assert.equal(form.hidden, false);
  assert.equal(input.attrs.maxlength, 200);
  input.value = 'Changed plans';
  await form.onsubmit({preventDefault(){}});
  assert.equal(JSON.stringify(calls.pop()), JSON.stringify(['check.wont_do',{ticket:t.id,check:'c1',reason:'Changed plans'}]));
  c.act = async () => ({ok:false,text:'Failed'});
  await form.onsubmit({preventDefault(){}});
  assert.deepEqual(errors, ['Failed']);
  c.snapshot = true;
  t.checklist[0].wont_do = true;
  all = c.taskRows(t).flatMap(nodes);
  assert.ok(!all.some(n => n.tag === 'button' || n.tag === 'form'));
  assert.ok(all.some(n => n.children.includes('–')));
});


test('shared folder line is one quiet text line from the core, absent when none', () => {
  const c = context({state:{runs:{t1:{running:true, shared_folder:{line:'"Fix login form" is also changing this folder.'}}, t2:{running:true}}}, clean:v => String(v ?? '')});
  vm.runInContext(source.slice(source.indexOf('function sharedFolderLine(t)'), source.indexOf('const surface =')), c);
  const on = JSON.stringify(c.sharedFolderLine({id:'t1'}));
  assert.match(on, /Fix login form\\" is also changing this folder\./);
  assert.doesNotMatch(on, /banner|danger|warn/);
  assert.equal(c.sharedFolderLine({id:'t2'}), null);
  assert.equal(c.sharedFolderLine({id:'nope'}), null);
});
test('a ticket with a copy shows the quiet "Works in a separate copy" line (the ticket has no local path)', () => {
  const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false)});
  const c = context({h, clean:v => String(v ?? '')});
  vm.runInContext(source.slice(source.indexOf('function copyLine(t)'), source.indexOf('const surface =')), c);
  const on = JSON.stringify(c.copyLine({work:{folders:[{branch:'orch/t_x', base:'abc', sub:'', host:'m'}]}}));
  assert.match(on, /Works in a separate copy of your project/);
  assert.match(on, /orch\/t_x/);
  assert.equal(c.copyLine({work:{folders:[]}}), null);
  assert.equal(c.copyLine({}), null);
});
test('plan-first waiting card answers and edits only unstarted steps', async () => {
  const h = (tag, attrs = {}, ...kids) => ({tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false)});
  const t = {id:'t_parent', title:'Plan', status:'waiting', questions:[{id:'q1',text:'First?'},{id:'q2',text:'Second?'}]};
  let scrolled = false, focused = false;
  const calls = [];
  const ctx = {locks:new Set(), render(){}, refresh(){}, act:async (op,args) => { calls.push([op,args]); return {ok:true}; }, repeatsAddon:() => null, window:{DashHelpers:helpers, orch:{toast(){}}}, document:{addEventListener(){}}, addEventListener(){}, h,
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => v || '',
    el:(tag, cls, text) => h(tag,{className:cls},text), fragment:(...kids) => h('fragment',{},kids),
    card:(key,title,suffix,kids) => h('section',{'data-key':key},title,suffix,kids), emptyRow:text => h('p',{},text),
    questions:t => t.questions || [], capitalise:v => v, date:() => '', time:() => '', ticketTabs:new Map(), addons:() => [], tickets:() => [t], ticketOf:() => t,
    statusChip:() => h('span',{},'Waiting'), chip:text => h('span',{},text), href:id => '#ticket/'+id, MOVE_CHOICES:[],
    main:{querySelector:() => ({scrollIntoView(){scrolled=true;},querySelector:() => ({focus(){focused=true;}})})}};
  vm.createContext(ctx); vm.runInContext(source,ctx);
  ctx.snapshot=false; ctx.state={settings:{agents:[{name:'claude',label:'Claude',chosen:true}]}};
  vm.runInContext("loadArtifacts = () => {}; inlineField = (t,f) => t[f]; addTaskRow = () => null; agentBar = () => null;",ctx);
  const nodes = n => typeof n === 'object' && n ? [n,...n.children.flatMap(nodes)] : [];

  t.plan_first = true; t.questions[0].text = 'Plan ready: review these steps';
  const children = [
    {id:'a', parent:t.id, title:'First', status:'open', revision:1, done_when:'It works'},
    {id:'b', parent:t.id, title:'Second', status:'ready', revision:2},
    {id:'c', parent:t.id, title:'Running', status:'active'},
    {id:'d', parent:t.id, title:'Checked', status:'open', checklist:[{done:true}]},
    {id:'e', parent:t.id, title:'Finished', status:'done'},
    {id:'f', parent:t.id, title:'Removed', status:'dropped'}
  ];
  ctx.tickets = () => [t, ...children];
  const buttons = tree => nodes(tree).filter(n => n.tag === 'button');
  const find = (tree, label) => buttons(tree).find(n => n.children.includes(label));
  let tree = ctx.detail(t);
  assert.match(JSON.stringify(tree), /Waiting for you · work hasn't started/);
  assert.match(JSON.stringify(tree), /Done when It works/);
  const json = JSON.stringify(tree);
  assert.equal((json.match(/work hasn't started/g) || []).length, 1);  // the waiting state shows once
  assert.equal((json.match(/Needs you/g) || []).length, 0);
  assert.equal((json.match(/"First"/g) || []).length, 1);  // each step once
  assert.equal(nodes(tree).filter(n => n.tag === 'button' && n.children.includes('Answer')).length, 0);
  t.note = 'Build it';
  t.plan = {goal:'customers pay online', not_included:'refunds · subscriptions'};
  const withGoal = JSON.stringify(ctx.detail(t));
  assert.match(withGoal, /Goal: /); assert.match(withGoal, /customers pay online/); assert.match(withGoal, /Not included: /); assert.match(withGoal, /refunds · subscriptions/);
  assert.doesNotMatch(JSON.stringify(ctx.detail({...t, plan:undefined})), /Goal: /);
  delete t.note; delete t.plan;
  assert.ok(find(tree, 'Start work')); assert.ok(find(tree, 'Change a step'));
  assert.equal(find(tree, 'Rename'), undefined);
  find(tree, 'Change a step').onclick();
  tree = ctx.detail(t);
  assert.equal(buttons(tree).filter(n => n.children.includes('Rename')).length, 2);
  assert.equal(buttons(tree).filter(n => n.children.includes('Remove')).length, 2);
  assert.ok(find(tree, '+ Add a step')); assert.ok(find(tree, 'Done editing'));
  await find(tree, 'Remove').onclick();
  assert.equal(JSON.stringify(calls.pop()), JSON.stringify(['ticket.patch', {ticket:'a', data:{status:'dropped'}, if_revision:1}]));
  find(tree, 'Done editing').onclick();
  assert.equal(find(ctx.detail(t), 'Rename'), undefined);
  await find(tree, 'Start work').onclick();
  assert.equal(JSON.stringify(calls.pop()), JSON.stringify(['answer', {ticket:t.id, question:'q1', answer:'Start work'}]));
  for (const [plan, text, status] of [[false,'Plan ready','waiting'], [true,'Other question','waiting'], [true,'Plan ready','done']]) {
    t.plan_first = plan; t.questions[0].text = text; t.status = status;
    tree = ctx.detail(t);
    assert.equal(find(tree, 'Start work'), undefined);
    assert.equal(find(tree, 'Change a step'), undefined);
  }
});

test('plan step dialogs rename with a revision and add under the parent', async () => {
  const calls = [], dialogs = [];
  const node = (tag, attrs = {}, ...children) => ({tag, attrs, children, value:attrs.value || '',
    append(...kids) { this.children.push(...kids); }, focus() {}});
  const c = context({h:node, act:async (op,args) => { calls.push([op,args]); return {ok:true}; },
    dialog:() => { const value = {d:node('dialog'), actions:node('div')}; dialogs.push(value); return value; }});
  c.window.orch.open = () => {};
  c.window.orch.close = () => {};
  c.ticketRenameStep({id:'child', title:'Before', revision:7});
  let {d, actions} = dialogs.pop();
  d.children[0].value = 'After';
  await actions.children[0].onclick();
  assert.equal(JSON.stringify(calls.pop()), JSON.stringify(['ticket.edit', {ticket:'child', title:'After', if_revision:7}]));
  c.ticketAddStep({id:'parent'});
  ({d, actions} = dialogs.pop());
  d.children[0].value = 'New step';
  await actions.children[0].onclick();
  assert.equal(JSON.stringify(calls.pop()), JSON.stringify(['ticket.new', {title:'New step', parent:'parent'}]));
});

test('a parent lists its steps in creation order, whatever order the ticket list arrives in (every width)', () => {
  const parent = {id:'t_p', key:'WS-1', title:'Plan'};
  const mk = (id, key, title, status) => ({id, key, title, status, parent:'t_p', created_at:'2026-11-09T10:00:00Z'});
  const zebra = mk('t_z', 'WS-2', 'Zebra', 'done'), alpha = mk('t_a', 'WS-3', 'Alpha', 'active'), middle = mk('t_m', 'WS-4', 'Middle', 'open');
  const titles = list => helpers.childrenOf(list, parent).map(c => c.title).join(',');
  // the ticket list is sorted differently at different widths (by title, by status): the steps must not follow it
  for (const list of [[parent, alpha, zebra, middle], [parent, zebra, middle, alpha], [middle, alpha, parent, zebra]]) {
    assert.equal(titles(list), 'Zebra,Alpha,Middle');
  }
  const c = context({card:(key, title, suffix, kids) => ({kids}), emptyRow:x => x, statusChip:() => null, href:id => '#' + id, clean:v => String(v)});
  const shown = list => JSON.stringify(c.ticketParts(parent, helpers.childrenOf(list, parent)));
  const order = json => ['Zebra', 'Alpha', 'Middle'].map(w => json.indexOf(w));
  assert.deepEqual(order(shown([parent, alpha, zebra, middle])), order(shown([parent, middle, zebra, alpha])));
  const ordered = order(shown([parent, alpha, zebra, middle]));
  assert.ok(ordered[0] < ordered[1] && ordered[1] < ordered[2]);
});

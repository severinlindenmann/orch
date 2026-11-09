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
  assert.match(text, /Looks good/);
  assert.match(text, /Ask for changes/);
  assert.ok(text.indexOf('Which colour?') < text.indexOf('Looks good'), 'the question comes first');
  assert.match(JSON.stringify(ctx.detail({id:'t_test', title:'Test', status:'review', questions:[]})), /Looks good/);
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
test('Copy ticket and Repeat show in the ticket menu only when the repeats add-on is on', () => {
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
  assert.match(on, /Copy ticket/);
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
  assert.equal(helpers.agentLabel({}, {}), 'Agent');
  assert.equal(helpers.agentLabel(settings, {agent:'codex'}), 'Codex');
});
test('task outcomes and result cards use plain text without sizes', () => {
  const ev = {type:'file',ref:'seating-plan.md',text:'seating-plan.md · 109 B',by:'agent:claude'};
  assert.equal(helpers.outcome({done:true,evidence:[]}), 'Completed.');
  assert.equal(helpers.outcome({done:true,evidence:[ev]}), 'Seating plan');
  const c = context({clean:String});
  vm.runInContext(source.slice(source.indexOf('function ticketResultCard'), source.indexOf('function ticketArtifactPreview')), c);
  const card = c.ticketResultCard({id:'t_test'}, ev);
  const text = JSON.stringify(card);
  assert.match(text, /ticket-result/);
  assert.doesNotMatch(text, /109|\.md|Agent says/);
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
  const ctx = {h, window:{DashHelpers:helpers}, snapshot:false, URL, TextDecoder, fetch:async () => new Response('line\n'.repeat(1000),{headers:{'Content-Type':'text/plain'}})};
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

function interactiveNode(tag, attrs = {}, ...children) {
  const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false), value:'', dataset:{key:attrs['data-key']},
    append(...kids){this.children.push(...kids);}, prepend(...kids){this.children.unshift(...kids);},
    replaceChildren(...kids){this.children = kids;}, setAttribute(k,v){this.attrs[k] = v;}, focus(){},
    click(){if (!this.disabled) return this.onclick?.();}};
  return n;
}
const descendants = n => n && typeof n === 'object' ? [n, ...n.children.flatMap(descendants)] : [];
test('inline changes replace both buttons, preserve the lock, send on Enter and cancel on Escape', async () => {
  let finish, renders = 0;
  const calls = [], locks = new Set();
  const c = context({h:interactiveNode, locks, moveTicket(){}, render(){renders++;},
    act:async (op, args) => { calls.push([op,args]); return new Promise(resolve => {finish = resolve;}); }});
  const host = c.ticketChangesEditor({id:'t_test'});
  assert.equal(host.attrs['data-key'], 'ticket-changes-t_test');
  host.children[0].children[1].click();
  const nodes = descendants(host), input = nodes.find(n => n.tag === 'input');
  const send = nodes.find(n => n.children.includes('Send'));
  assert.ok(input);
  assert.equal(input.attrs.placeholder, 'What should change?');
  assert.equal(input.attrs['aria-label'], 'What should change?');
  assert.equal(nodes.filter(n => n.tag === 'textarea').length, 0);
  assert.ok(!nodes.some(n => n.children.includes('Looks good — mark Done')));
  assert.ok(send.disabled && locks.has('ticket-changes-t_test'));
  input.value = 'Fix the date'; input.oninput(); assert.equal(send.disabled, false);
  input.onkeydown({key:'Enter', preventDefault(){}});
  assert.ok(send.disabled);
  input.onkeydown({key:'Enter', preventDefault(){}});
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].text, 'Fix the date');
  finish({ok:true}); await new Promise(resolve => setImmediate(resolve));
  assert.equal(renders, 1); assert.equal(locks.size, 0);
  host.children[0].children[1].click();
  descendants(host).find(n => n.tag === 'input').onkeydown({key:'Escape', preventDefault(){}});
  assert.equal(locks.size, 0);
  assert.match(JSON.stringify(host), /Ask for changes/);
});


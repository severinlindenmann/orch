'use strict';
// The Review page of the dashboard: state.review in, one signed click out (review.answer), files through /api/file,
// the "All cards" list, "Review all" on Home and the card answers on a ticket. The kit's UI.reviewPage has its own tests.
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
const ID = 'a'.repeat(64);
const CARD = {id:'core:q:t_abcdef:q3', ticket:'t_abcdef', ticket_key:'DT-41', key:'q3', kind:'draft', card:{kind:'draft', title:'Home block'}, digest:ID, since:'2026-11-15T09:00:00Z'};
function ctx(state, extra = {}) {
  const acts = [];
  const c = {h, window:{DashHelpers:helpers, UI:kit.UI, orch:{toast(){}}}, document:{addEventListener(){}, getElementById:() => null}, addEventListener(){}, locks:new Set(), localStorage:{getItem:() => null, setItem(){}}, setTimeout, clearTimeout,
    name:v => String(v || '').replace(/^(human|agent):/, ''), capitalise:v => v, iconEl:n => n, card:(key, title, suffix, kids) => h('section', {'data-key':key}, title, suffix, kids), emptyRow:t => h('p', {}, t), button:(label, cls, fn) => h('button', {className:'btn ' + cls}, label), render(){}, time:v => kit.UI.stamp(v), parse:v => new Date(v), now:() => new Date('2026-11-15T12:00:00Z'), array:v => Array.isArray(v) ? v : [], clean:String, state, mounts:new Map(), snapshot:false,
    fragment:(...k) => h('fragment', {}, k), heading:(t, s) => h('header', {}, t, s), el:(tag, cls, t) => h(tag, {className:cls}, t),
    act:async (op, args) => { acts.push([op, args]); return {ok:true, status:200}; }, ...extra};
  c.acts = acts; vm.createContext(c); vm.runInContext(read('pages/review.js'), c); return c;
}
test('the page reads cards and decisions from state.review and counts the cards', () => {
  const c = ctx({workspace:'Demo', review:{cards:[CARD, {...CARD, id:'core:review:t_abcdef', key:'review'}], answered:[{id:'x'}]}});
  assert.equal(c.reviewCount(), 2);
  assert.match(c.reviewSubtitle(), /^2 things wait on you, most urgent first\.$/);
  const api = c.reviewApi();
  return Promise.all([api.stack(), api.answered()]).then(([s, a]) => { assert.equal(s.length, 2); assert.equal(a.length, 1); assert.equal(api.workspace, 'Demo'); });
});
test('one card and none: plain words', () => {
  assert.match(ctx({review:{cards:[CARD]}}).reviewSubtitle(), /^1 thing waits on you/);
  assert.equal(ctx({}).reviewSubtitle(), 'Nothing waits for you.');
  assert.equal(ctx({}).reviewCount(), 0);
});
test('fileUrl serves only reviewed/<sha12>/<name> through /api/file', () => {
  const f = ctx({}).reviewApi().fileUrl;
  assert.equal(f(CARD, 'reviewed/0123456789ab/after.png'), '/api/file?t=t_abcdef&k=reviewed&n=0123456789ab%2Fafter.png');
  for (const bad of ['reviewed/0123456789ab/../x.png', 'reviewed/0123456789ab/a/b.png', 'artifacts/x.png', 'reviewed/XYZ/x.png', '', null, 'https://evil/x.png']) assert.equal(f(CARD, bad), '', String(bad));
  assert.equal(f({}, 'reviewed/0123456789ab/after.png'), '');
});
test('an answer is one review.answer click: question card, check card, picked and note', async () => {
  const c = ctx({});
  const api = c.reviewApi();
  assert.deepEqual({...await api.answer({id:'core:q:t_abcdef:q3', digest:ID, verdict:'talk', picked:'C', note:{text:'x', pins:[]}})}, {ok:true});
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts[0])), ['review.answer', {ticket:'t_abcdef', key:'q3', verdict:'talk', digest:ID, picked:'C', note:{text:'x', pins:[]}}]);
  await api.answer({id:'core:review:t_abcdef', digest:ID, verdict:'ok', picked:null, note:null});
  assert.deepEqual(JSON.parse(JSON.stringify(c.acts[1])), ['review.answer', {ticket:'t_abcdef', key:'review', verdict:'ok', digest:ID}]);
  const bad = await api.answer({id:'core:q:../x:q1', digest:ID, verdict:'ok'});
  assert.equal(bad.ok, false); assert.equal(c.acts.length, 2, 'a malformed id never reaches the server');
});
test('refusals become the codes the page understands', async () => {
  const reply = r => ctx({}, {act:async () => r}).reviewApi().answer({id:CARD.id, digest:ID, verdict:'ok'});
  assert.equal((await reply({ok:false, status:403, text:'Sign in to do this: open the dashboard with a sign-in link from orch.'})).error.code, 'needs_person');
  assert.deepEqual({...(await reply({ok:false, status:422, text:JSON.stringify({ok:false, error:{code:'changed', message:'It changed.'}})})).error}, {code:'changed', message:'It changed.'});
  assert.equal((await reply({ok:false, status:400, text:'That is not a card.'})).error.code, 'refused');
  assert.equal((await reply({ok:false, status:0, text:'Could not reach orch.'})).error.code, 'error');
});
test('the All cards list: the card on screen in bold, answered ones quiet with their word', () => {
  const c = ctx({}, {iconEl:n => h('span', {}, 'ic-' + n)});
  const rows = []; const queue = {replaceChildren(...r) { rows.push(...r); }};
  const item = (id, title) => ({id, title, icon:'page', kind:'draft', okLabel:'Build it', preview:{type:'page'}});
  const deck = {items:[item('a', 'First'), item('b', 'Second'), item('c', 'Third')], index:1, answers:{a:{verdict:'ok', item:item('a', 'First'), note:null}, c:{verdict:'no', item:item('c', 'Third')}}, jump(i) { deck.index = i; }};
  c.document = {createElement: t => h(t)}; c.reviewDrawSide(queue, deck);
  assert.equal(rows.length, 1, 'one set: one section without a heading');
  assert.ok(!nodes(rows[0]).some(n => /review-group-head/.test(n.attrs?.className || '')));
  rows.splice(0, 1, ...rows[0].children);
  assert.equal(rows.length, 3);
  assert.match(rows[0].attrs.className, /is-done/); assert.match(text(rows[0]), /Build it/);
  assert.match(rows[1].attrs.className, /is-now/); assert.match(text(rows[1]), /Now/);
  assert.match(text(rows[2]), /Don't do/);
  rows[2].onclick(); assert.equal(deck.index, 2);
  assert.doesNotThrow(() => c.reviewDrawSide(null, deck));
});
test('the page keeps its host and side list out of the reconcile (mounted once), and leaving destroys the page', () => {
  const calls = [];
  const c = ctx({}, {window:{DashHelpers:helpers, UI:{reviewPage:(host, api, o) => { calls.push(o); return {destroy() { calls.push('destroy'); }, tick() {}}; }}}});
  const host = h('div'), side = h('aside'), queue = h('div');
  const main = {querySelectorAll: sel => sel === '[data-review-host]' ? [host] : sel === '[data-review-side]' ? [side] : [], querySelector: () => queue};
  c.mountReview(main); c.mountReview(main);
  assert.equal(calls.length, 1, 'mounted once'); assert.equal(calls[0].poll, 3000); assert.equal(typeof calls[0].onChange, 'function');
  assert.ok(c.mounts.has(host) && c.mounts.has(side));
  c.mounts.get(host).destroy(); assert.equal(calls.at(-1), 'destroy');
});
// ---- Home and ticket ----
function home(state, tickets = [], rows = []) {
  const c = ctx(state, {tickets:() => tickets, ticketOf:id => tickets.find(t => t.id === id), href:id => '#ticket/' + id, needsList:() => rows});
  vm.runInContext(read('pages/ticket.js'), c); vm.runInContext(read('pages/home.js'), c);
  return c;
}
test('"Review all" is a link to #review with the card count, and never changes the Home total', () => {
  const rows = [{id:'n1', ticket:'t_abcdef', since:'2026-11-15T09:00:00Z', title:'Home block', answer:{question:'q3', digest:ID, options:[]}}];
  const base = {settings:{}, runs:{}, services:[]};
  const tickets = [{id:'t_abcdef', title:'Newsletter', status:'waiting', questions:[{id:'q3', text:'Home block'}]}];
  const withCards = home({...base, review:{cards:[CARD], answered:[]}}, tickets, rows), without = home({...base}, tickets, rows);
  const a = withCards.reviewAllButton();
  assert.equal(a.tag, 'a'); assert.equal(a.attrs.href, '#review'); assert.match(text(a), /^Review all1$/);
  assert.equal(without.reviewAllButton(), null, 'no cards, no button');
  assert.equal(withCards.reviewCount(), 1);
  assert.equal(withCards.needsToday().count, without.needsToday().count, 'cards are the questions and results Home already counts');
});
test('ORCH-63: the Review subtitle, the top bar and the Review menu entry say one number: the cards (questions + results)', () => {
  const base = {settings:{}, runs:{}, services:[]};
  const t1 = {id:'t_abcdef', title:'Newsletter', status:'waiting', questions:[{id:'q3', text:'Home block'}]};
  const t2 = {id:'t_fffaaa', title:'Services', status:'waiting', questions:[{id:'q1', text:"Start 'Services'?", kind:'factory:start'}]};
  const rows = [
    {id:'core:q:t_abcdef:q3', source:'core', ticket:'t_abcdef', since:'2026-11-15T09:00:00Z', title:'Newsletter', answer:{question:'q3', digest:ID, options:['A', 'B']}},
    {id:'core:q:t_fffaaa:q1', source:'core', kind:'factory:start', ticket:'t_fffaaa', since:'2026-11-15T10:00:00Z', title:'Services', answer:{question:'q1', digest:ID, options:['Start', 'Edit', 'Not now']}}];
  const factory = {...CARD, id:'core:q:t_fffaaa:q1', ticket:'t_fffaaa', key:'q1', kind:'choice', card:{kind:'choice', title:"Start 'Services'?"}};
  const c = home({...base, review:{cards:[CARD, factory], answered:[]}}, [t1, t2], rows);
  assert.equal(c.needsToday().count, 2);
  assert.equal(c.reviewSubtitle(), '2 things wait on you, most urgent first.');
  // owner 16 Nov: the number is open questions plus results to check, so it equals the cards here. A helper idle at its
  // prompt, or a ticket that only waits for another ticket, has no card and is not counted.
  const idle = {id:'core:stuck:t_ccccdd', source:'core', kind:'stuck:idle', ticket:'t_ccccdd', since:'2026-11-15T11:00:00Z', title:'Docs', text:'The helper waits at its prompt', tone:'warn'};
  const waits = {id:'t_ddddee', title:'Later', status:'waiting', waiting_on:{kind:'ticket', ref:'t_abcdef'}, questions:[]};
  const check = {...CARD, id:'core:review:t_eeeeff', ticket:'t_eeeeff', key:'review', kind:'check', card:{kind:'check', title:'Report'}};
  const cards = [CARD, factory, check];
  const more = home({...base, review:{cards, answered:[]}}, [t1, t2, {id:'t_ccccdd', title:'Docs', status:'active', questions:[]}, waits, {id:'t_eeeeff', title:'Report', status:'review', questions:[]}], [...rows, idle]);
  assert.equal(more.needsToday().count, 3); assert.equal(more.needsToday().count, more.reviewCount());
  assert.equal(more.reviewSubtitle(), '3 things wait on you, most urgent first.');
  assert.equal(home({...base, review:{cards:[], answered:[]}}, [], []).reviewSubtitle(), 'Nothing waits for you.');
});
test('ORCH-63: the dashboard sends the one count to the shown add-on page of its own (Focus), and on request', () => {
  const src = read('app.js');
  assert.match(src, /postMessage\(\{type:'orch\.needs\.count', count:n\}, location\.origin\)/);
  assert.match(src, /menuToggle\.textContent = [^\n]+\n\s*postNeedsCount\(needCount\);/);
  assert.match(src, /e\.data\?\.orch !== 'needs-count'/);
  assert.match(src, /\.shipped\) return null;/, 'only an add-on orch ships gets the number');
});
test('"Review all" is not shown in a shared copy', () => {
  assert.ok(home({review:{cards:[CARD]}}).reviewAllButton());
  const c = home({review:{cards:[CARD]}}); c.snapshot = true; assert.equal(c.reviewAllButton(), null);
});
test('Review answers on a ticket: only those with a card answer, newest first', () => {
  const answered = (id, at, extra = {}) => ({id, text:'Q ' + id, answer:'Looks good', answered_by:'human:sev', via:'dashboard', at, card:{kind:'draft', title:'Card ' + id}, decision:{action:'approve', summary:'Looks good'}, ...extra});
  const t = {id:'t_abcdef', questions:[answered('q1', '2026-11-14T09:00:00Z'), {id:'q2', text:'open'}, answered('q3', '2026-11-15T09:00:00Z'), {id:'q4', answer:'x', at:'2026-11-15T10:00:00Z'}]};
  const c = home({review:{cards:[]}}, [t]);
  const list = vm.runInContext('ticketReviewAnswers', c)(t);
  assert.deepEqual(list.map(e => e.id), ['core:q:t_abcdef:q3', 'core:q:t_abcdef:q1'], 'an answer without a decision is not one');
  assert.equal(vm.runInContext('ticketReviewAnswers', c)({id:'t_abcdef', questions:[{id:'q4', answer:'x'}]}).length, 0);
});

test('the All cards list: one section per set (group, else ticket) with its own count (ORCH-65)', () => {
  const c = ctx({}, {iconEl:n => h('span', {}, 'ic-' + n)});
  const secs = []; const queue = {replaceChildren(...r) { secs.push(...r); }};
  const item = (id, extra) => ({id, title:'Card ' + id, icon:'page', kind:'draft', preview:{type:'page'}, ticketTitle:'Home look', ...extra});
  const deck = {items:[item('a', {group:'Phone'}), item('b', {group:'Phone'}), item('c')], index:1, answers:{a:{verdict:'ok', item:item('a'), note:null}}, jump() {}};
  c.reviewDrawSide(queue, deck);
  assert.equal(secs.length, 2);
  assert.match(text(secs[0]), /^Phone1 of 2 waiting/); assert.match(text(secs[1]), /^Home look1 of 1 waiting/);
});

test('Review opens at the card the ticket page asked for (#review?card=...)', () => {
  const calls = [];
  const c = ctx({}, {location:{hash:'#review?card=' + encodeURIComponent('core:q:t_abcdef:q2')}, window:{DashHelpers:helpers, UI:{reviewPage:(host, api, o) => { calls.push(o); return {destroy() {}, tick() {}}; }}}});
  const host = h('div'), main = {querySelectorAll: sel => sel === '[data-review-host]' ? [host] : [], querySelector: () => h('div')};
  c.mountReview(main);
  assert.equal(calls[0].startId, 'core:q:t_abcdef:q2');
});

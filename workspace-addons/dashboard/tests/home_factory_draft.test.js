'use strict';
// ORCH-479 (owner said yes on 18 Nov): a Factory draft ready for Plan the run waits for the person on Home and Review as
// on the Factory page, with the same verbs (Read draft, Plan the run, Ask for changes), and counts in the one number.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const read = f => fs.readFileSync(path.join(WEB, f), 'utf8');
const helpers = require(path.join(WEB, 'helpers.js'));
const h = (tag, attrs = {}, ...children) => {
  const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false), dataset:{}, classList:{add(){}, remove(){}}, value:''};
  n.append = (...c) => n.children.push(...c); n.setAttribute = (k, v) => { n.attrs[k] = v; }; n.querySelectorAll = () => [];
  n.listeners = {}; n.addEventListener = (k, fn) => { n.listeners[k] = fn; }; n.focus = () => {};
  return n;
};
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
const words = n => nodes(n).flatMap(x => x.children || []).filter(x => typeof x === 'string').join(' ');
const tick = () => new Promise(r => setTimeout(r, 10));
const plain = v => JSON.parse(JSON.stringify(v));  // objects made inside the vm context

const ticket = {id:'t_abc1234', key:'ORCH-23', title:'Opening hours page', status:'active', questions:[], ext:{factory:{role:'order'}}};
const draft = {id:'factory:draft:t_abc1234:v2', source:'factory', kind:'factory:draft', ticket:ticket.id, title:'Opening hours page',
  text:'Your draft is ready. Read it, then plan the run or ask for changes.', tone:'needs-you', since:'2026-11-18T09:00:00Z', draft:2};

function ctx(extra = {}) {
  const acts = [], toasts = [];
  const sendResult = extra.sendResult || {state:'none', delivered:0, id:'m1'};
  const c = {h, window:{DashHelpers:helpers, orch:{toast:(t, k) => toasts.push([t, k])}}, document:{addEventListener(){}, getElementById:() => null}, addEventListener(){},
    location:{origin:'http://127.0.0.1:8765', pathname:'/'},
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:String, capitalise:v => v, snapshot:false, locks:new Set(),
    localStorage:{getItem:() => null, setItem(){}}, state:{settings:{}, runs:{}, services:[], review:{cards:[]}}, setTimeout, clearTimeout,
    fragment:(...k) => h('fragment', {}, k), card:(key, title, suffix, kids) => h('section', {'data-key':key}, kids), emptyRow:t => h('p', {}, t),
    button:(label, cls, fn) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = fn; return b; }, heading:(t, s) => h('header', {}, t, s),
    href:id => '#ticket/' + id, render(){}, parse:v => new Date(v), now:() => new Date('2026-11-18T12:00:00Z'), today:() => '2026-11-18', age:() => '3 h ago',
    addons:() => [{name:'factory', page:true}],
    act:async (op, args) => { acts.push([op, args]); return op === 'run.send' ? {ok:true, state:{send_result:sendResult}} : {ok:true}; },
    needsList:() => [draft], tickets:() => [ticket], ticketOf:id => (id === ticket.id ? ticket : null), ...extra};
  c.acts = acts; c.toasts = toasts;
  vm.createContext(c);
  for (const f of ['pages/ticket.js', 'pages/home.js', 'pages/review.js']) vm.runInContext(read(f), c);
  return c;
}
const buttonsOf = row => nodes(row).filter(n => n.tag === 'button');

test('Home shows a ready draft as the Factory card: Read draft, Plan the run, Ask for changes', () => {
  const c = ctx(), row = c.needRow(draft, draft.id), text = words(row);
  assert.ok('data-factory-draft' in row.attrs);
  assert.match(text, /Factory draft/);
  assert.match(text, /Opening hours page/);
  assert.match(text, /Read the draft, then plan the run or ask for changes\./);
  const link = nodes(row).find(n => n.tag === 'a' && n.children.includes('Read draft'));
  assert.equal(link.attrs.href, '#addon/factory/#/order/t_abc1234/draft');
  assert.deepEqual(buttonsOf(row).map(b => b.children[0]), ['Plan the run', 'Ask for changes', 'Send', 'Cancel']);
  assert.ok(buttonsOf(row).slice(0, 2).every(b => b.attrs.className === 'btn outline sm'), 'equal weight, as the proposal buttons on Home');
});

test('Plan the run sends the Factory page words to the agent and starts one when none is on the order', async () => {
  const c = ctx(), row = c.needRow(draft, draft.id);
  await buttonsOf(row)[0].onclick();
  await tick();
  assert.deepEqual(plain(c.acts), [['run.send', {ticket:'t_abc1234', text:helpers.FACTORY_DRAFT_WORDS.plan}], ['run.start', {ticket:'t_abc1234'}]]);
  assert.match(c.toasts[0][0], /planning the run/);
  // after the click the row says what happened instead of offering the buttons again
  assert.equal(buttonsOf(c.needRow(draft, draft.id)).length, 0);
});

test('Ask for changes sends your words as a change of the draft; a live agent gets them without a second start', async () => {
  const c = ctx({sendResult:{state:'live', delivered:1}}), row = c.needRow(draft, draft.id);
  const [, change, send] = buttonsOf(row), note = nodes(row).find(n => n.tag === 'textarea');
  change.onclick();
  assert.equal(note.hidden, false);
  note.value = 'shorter, and add a map'; note.listeners.input();
  assert.equal(send.disabled, false);
  await send.onclick();
  await tick();
  assert.deepEqual(plain(c.acts), [['run.send', {ticket:'t_abc1234', text:'Change the draft: shorter, and add a map'}]]);
});

test('a snapshot shows the draft without buttons; further down the list it is one row with Read draft', () => {
  const s = ctx({snapshot:true});
  assert.equal(buttonsOf(s.needRow(draft, draft.id)).length, 0);
  const c = ctx(), row = c.needListRow(draft, 1, []), a = nodes(row).find(n => n.tag === 'a');
  assert.equal(a.children[0], 'Read draft');
  assert.equal(a.attrs.href, '#addon/factory/#/order/t_abc1234/draft');
  const bare = ctx({addons:() => []});
  assert.equal(nodes(bare.needRow(draft, draft.id)).find(n => n.tag === 'a').attrs.href, '#ticket/t_abc1234');
});

test('a ready draft is its own part of the one number, once per order, like the Factory page', () => {
  const q = {id:'core:q:t_other12:q1', source:'core', kind:'question', ticket:'t_other12', answer:{question:'q1', options:['A', 'B']}};
  assert.equal(helpers.needsYouCount([q, draft]), 1, 'the question count stays the questions; the page adds the drafts');
  assert.equal(helpers.factoryDrafts([q, draft]).length, 1);
  assert.equal(helpers.factoryDrafts([q, draft, {...draft, id:'factory:draft:t_abc1234:v1'}]).length, 1);
  assert.equal(helpers.factoryDrafts([{...draft, source:'other'}]).length, 0, 'only Factory rows of that kind');
  assert.equal(helpers.isNotice(draft), false);
});

test('Review shows the draft as a card with the same verbs and sends what you pick to the agent', async () => {
  const c = ctx(), cards = c.reviewCards();
  assert.equal(cards.length, 1);
  const [card] = cards;
  assert.equal(card.card.ok_label, 'Plan the run');
  assert.equal(card.card.no_label, 'Ask for changes');
  assert.equal(card.card.no_words, true);
  assert.deepEqual(plain(card.links), [{label:'Read draft', url:'http://127.0.0.1:8765/#addon/factory/#/order/t_abc1234/draft'}]);
  const api = c.reviewApi();
  assert.deepEqual(plain(await api.answer({id:card.id, verdict:'talk', note:{text:''}})), {ok:false, error:{code:'refused', message:'Write what should change first.'}});
  assert.deepEqual(plain(await api.answer({id:card.id, verdict:'ok'})), {ok:true});
  assert.deepEqual(plain(await api.answer({id:card.id, verdict:'talk', note:{text:'add a map'}})), {ok:true});
  assert.deepEqual(c.acts.filter(a => a[0] === 'run.send').map(a => a[1].text), [helpers.FACTORY_DRAFT_WORDS.plan, 'Change the draft: add a map']);
});

test('the kit maps the draft card: Ask for changes opens the comment sheet like a Check send back', () => {
  const kit = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/review.js'), 'utf8');
  const widgets = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.js'), 'utf8');
  assert.match(kit, /noLabel:typeof k\.no_label==='string'/);
  assert.match(kit, /noWords:k\.no_words===true/);
  assert.match(widgets, /const sendsBack=it=>!!it&&\(it\.kind==='check'\|\|it\.noWords===true\);/);
});

test('Home, Review and the Factory page send the agent one wording for Plan the run and Ask for changes', () => {
  const factory = fs.readFileSync(path.join(__dirname, '../../factory/src/orch_factory/web/factory.js'), 'utf8');
  assert.ok(factory.includes("const PLAN_TEXT = '" + helpers.FACTORY_DRAFT_WORDS.plan + "';"));
  assert.ok(factory.includes("go('Change the draft: ' + words"));
  for (const verb of ["'Read draft'", "'Plan the run'", "'Ask for changes'", "'Read proposal'"]) assert.ok(factory.includes(verb), verb);
});

test('Home counts a ready draft in the one number, with or without the core count, and it adds to its own group', () => {
  const q = {id:'core:q:t_other12:q1', source:'core', kind:'question', ticket:'t_other12', answer:{question:'q1', options:['A', 'B']}};
  for (const counts of [undefined, {needs_you:{items:[{ticket:'t_other12', question:'q1'}]}}]) {
    const c = ctx({needsList:() => [q, draft, {...draft, id:'factory:draft:t_abc1234:v1'}], laterToday:() => false, pendingAnswers:new Set(),
      loginWarnings:() => ({soon:[], stopped:[]}), isDraftRowLater:() => false});
    c.state.counts = counts;
    c.state.tickets = [ticket];
    const t = c.needsToday();
    assert.equal(t.questions, 1);
    assert.equal(t.count, 2, 'one question and one draft');
    assert.equal(t.groups.filter(g => helpers.isFactoryDraft(g.row)).length, 1);
  }
});

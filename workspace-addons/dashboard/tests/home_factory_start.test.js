'use strict';
// ORCH-60 (owner accepted the draft on 16 Nov): a Factory start question on Home is a few lines (title, goal, time and
// cost, "Read the whole proposal") with Not now, Change it, Start of the same weight, Start last; never the whole text.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const read = f => fs.readFileSync(path.join(WEB, f), 'utf8');
const helpers = require(path.join(WEB, 'helpers.js'));
const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false), dataset:{}, classList:{add(){}, remove(){}}}; n.append = (...c) => n.children.push(...c); n.setAttribute = (k, v) => { n.attrs[k] = v; }; n.addEventListener = () => {}; n.querySelectorAll = () => []; return n; };
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
const words = n => nodes(n).flatMap(x => x.children || []).filter(x => typeof x === 'string').join(' ');

// The shape render.start_text writes (workspace-addons/factory/src/orch_factory/render.py).
const TEXT = "Start 'Services: see and manage background jobs'? ~10 h · target $4 · you're needed for ~15 min. " +
  "Goal: See the workspace's background jobs in the dashboard and start, stop or restart each with one click. " +
  "Done means: The owner has seen the mockup; The Services tab lists the five examples. Stops: mockup, ship. " +
  "Steps: Mockup of the Services tab (designer); The add-on with its commands (builder). Crew: designer claude, builder claude. " +
  "Cap: 13 h active. Ship: Merges into the develop line on green checks (undo: Turn the add-on off). (Proposal 1)";

function ctx(question, extra = {}) {
  const acts = [];
  const ticket = {id:'t_abc1234', key:'ORCH-23', title:'Services: see and manage background jobs', status:'waiting', questions:[question]};
  const row = {id:'n1', ticket:ticket.id, since:'2026-11-16T09:00:00Z', title:question.text, answer:{question:question.id, digest:'d1', options:question.options}};
  const c = {h, window:{DashHelpers:helpers, orch:{toast(){}}}, document:{addEventListener(){}, getElementById:() => null}, addEventListener(){}, array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:String,
    capitalise:v => v, snapshot:false, locks:new Set(), localStorage:{getItem:() => null, setItem(){}}, state:{settings:{}, runs:{}, services:[]}, setTimeout, clearTimeout,
    fragment:(...k) => h('fragment', {}, k), card:(key, title, suffix, kids) => h('section', {'data-key':key}, kids), emptyRow:t => h('p', {}, t),
    button:(label, cls, fn) => { const b = h('button', {className:'btn ' + cls}, label); b.onclick = fn; return b; }, heading:(t, s) => h('header', {}, t, s), href:id => '#ticket/' + id, render(){},
    parse:v => new Date(v), now:() => new Date('2026-11-16T12:00:00Z'), today:() => '2026-11-16', age:() => '3 h ago',
    addons:() => [{name:'factory', page:true}], act:async (op, args) => { acts.push([op, args]); return {ok:true}; },
    needsList:() => [row], tickets:() => [ticket], ticketOf:id => (id === ticket.id ? ticket : null), ...extra};
  c.acts = acts; c.row = row;
  vm.createContext(c); vm.runInContext(read('pages/ticket.js'), c); vm.runInContext(read('pages/home.js'), c);
  vm.runInContext('ANSWER_UNDO_MS = 20', c);
  return c;
}
const factoryQ = {id:'q1', kind:'factory:start', text:TEXT, options:['Start', 'Edit', 'Not now']};

test('the proposal text reads as title, goal and one line of time and cost', () => {
  assert.deepEqual(helpers.factoryStart(TEXT), {title:'Services: see and manage background jobs',
    goal:"See the workspace's background jobs in the dashboard and start, stop or restart each with one click",
    meta:'Runs about 10 h · needs you for about 15 min · about $4 · up to 13 h of helper time'});
  assert.equal(helpers.factoryStart('Which supplier?'), null);
  assert.equal(helpers.factoryStart(''), null);
});

test('the Home card is a few lines and links to the whole proposal on the Factory page', () => {
  const c = ctx(factoryQ), row = c.needRow(c.row, 'n1'), text = words(row);
  assert.ok('data-factory-start' in row.attrs);
  assert.match(text, /Factory proposal/);
  assert.match(text, /Start “Services: see and manage background jobs”\?/);
  assert.match(text, /Runs about 10 h · needs you for about 15 min/);
  assert.doesNotMatch(text, /Done means|Crew|Steps|Ship/, 'never the whole proposal');
  const link = nodes(row).find(n => n.tag === 'a' && n.children.includes('Read the whole proposal'));
  assert.equal(link.attrs.href, '#addon/factory/#/order/t_abc1234/proposal');
});

test('the buttons are Not now, Change it, Start, all the same weight; Change it sends Edit', async () => {
  const c = ctx(factoryQ), row = c.needRow(c.row, 'n1');
  const buttons = nodes(row).filter(n => n.tag === 'button');
  assert.deepEqual(buttons.map(b => b.children[0]), ['Not now', 'Change it', 'Start']);
  assert.ok(buttons.every(b => b.attrs.className === 'btn outline sm'));
  assert.ok(!nodes(row).some(n => (n.attrs?.className || '').includes('suggested')), 'no button stands out');
  buttons[1].onclick({currentTarget:{closest:() => h('div')}});
  await new Promise(r => setTimeout(r, 60));
  assert.equal(c.acts[0][1].answer, 'Edit');
});

test('without the Factory page the link opens the ticket; a snapshot shows no buttons', () => {
  const c = ctx(factoryQ, {addons:() => []});
  const link = nodes(c.needRow(c.row, 'n1')).find(n => n.tag === 'a' && n.children.includes('Read the whole proposal'));
  assert.equal(link.attrs.href, '#ticket/t_abc1234');
  const s = ctx(factoryQ); vm.runInContext('snapshot = true', s);
  assert.equal(nodes(s.needRow(s.row, 'n1')).filter(n => n.tag === 'button').length, 0);
});

test('a Factory start question further down the list opens the proposal, not the full text', () => {
  const c = ctx(factoryQ), row = c.needListRow(c.row, 1, []);
  const a = nodes(row).find(n => n.tag === 'a');
  assert.equal(a.children[0], 'Read proposal');
  assert.equal(a.attrs.href, '#addon/factory/#/order/t_abc1234/proposal');
  assert.doesNotMatch(words(row), /Done means/);
});

test('any other question keeps its usual card', () => {
  const c = ctx({id:'q1', text:'Which supplier?', options:['A', 'B']}), row = c.needRow(c.row, 'n1');
  assert.ok(!('data-factory-start' in row.attrs));
  assert.match(words(row), /Which supplier\?/);
});

test('the dashboard opens an add-on page at its own place after a second #', () => {
  const app = read('app.js'), settings = read('pages/settings.js');
  assert.match(app, /\(\?:#\(\\\/\[A-Za-z0-9_\/-\]\*\)\)\?\$/);
  assert.match(settings, /r\.inner \? '#' \+ r\.inner : ''/);
});

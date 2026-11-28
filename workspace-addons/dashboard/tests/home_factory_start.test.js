'use strict';
// ORCH-60 (owner accepted the draft on 16 Nov): a Factory start question on Home is a few lines (title, goal, time and
// cost, "Read proposal") with Not now, Change it, Start of the same weight, Start last; never the whole text.
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
const TEXT = "Start 'Services: see and manage background jobs'? ~10 h · AI cost about $4 · you're needed for ~15 min. " +
  "Goal: See the workspace's background jobs in the dashboard and start, stop or restart each with one click. " +
  "Done means: The owner has seen the mockup; The Services tab lists the five examples. Pauses: mockup, ship. " +
  "Tasks: Mockup of the Services tab (designer); The add-on with its commands (builder). Team: designer claude, builder claude. " +
  "Time limit: 13 h active. Goes live: Merges into the develop line on green checks (undo: Turn the add-on off). (Proposal 1)";

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
    goal:"See the workspace's background jobs in the dashboard and start, stop or restart each with one click.",
    meta:'Runs about 10 h · needs you for about 15 min · about $4 · up to 13 h of helper time'});
  assert.equal(helpers.factoryStart('Which supplier?'), null);
  assert.equal(helpers.factoryStart(''), null);
});






test('the dashboard opens an add-on page at its own place after a second #', () => {
  const app = read('app.js'), settings = read('pages/settings.js');
  assert.match(app, /\(\?:#\(\[A-Za-z0-9_\/-\]\*\)\)\?\$/);
  assert.match(settings, /r\.inner \? '#' \+ r\.inner : ''/);
  assert.match(settings, /r\.inner \? '&' \+ r\.inner : ''/);  // after the frame pass (ORCH-186)
});

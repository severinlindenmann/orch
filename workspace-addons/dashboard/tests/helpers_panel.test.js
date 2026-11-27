// ORCH-61: one helper state from the core, one Helpers list on Home (and Focus), the same words everywhere.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const KIT = path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.js');

// a tiny DOM, enough for the kit widgets
function fakeDom() {
  const node = tag => ({tagName:tag, children:[], dataset:{}, className:'', textContent:'', attrs:{},
    append(...c) { this.children.push(...c); }, setAttribute(k, v) { this.attrs[k] = v; }});
  return {createElement:node, createElementNS:(ns, tag) => node(tag), createTextNode:text => ({text})};
}
function kit() {
  const c = vm.createContext({window:{}, document:fakeDom()});
  vm.runInContext(fs.readFileSync(KIT, 'utf8'), c);
  return c.window.UI;
}
const texts = n => !n || typeof n !== 'object' ? [] : [n.text ?? n.textContent ?? '', ...(n.children || []).flatMap(texts)].filter(x => String(x).trim());

test('helperState takes the core words as they are; null when no helper runs', () => {
  const run = {running:true, helper:{state:'you', word:'anything', detail:'Your answer'}};
  assert.deepEqual({...helpers.helperState(run, {})}, {state:'you', word:'Needs you', detail:'Your answer'});
  assert.equal(helpers.helperState({running:false}, {}), null);
  assert.equal(helpers.helperState(null, {}), null);
  assert.equal(helpers.helperState({running:true, helper:{state:'bogus'}}, {}).state, 'working');  // unknown: the fallback
  assert.equal(helpers.helperState({running:false, state:'maybe-stale'}, {}).word, 'Stuck');
});

test('helperState without the core field: the same words from the claim (older core)', () => {
  const live = state => ({running:true, claim:{live:{state}}});
  assert.equal(helpers.helperState(live('working'), {}).word, 'Working');
  assert.equal(helpers.helperState(live('starting'), {}).word, 'Starting');
  assert.equal(helpers.helperState(live('idle'), {}).word, 'Idle');
  assert.equal(helpers.helperState(live('attention'), {}).detail, 'Your OK on the screen');
  // ORCH-1808: the call the permission prompt waits on stands next to it
  assert.equal(helpers.helperState({running:true, claim:{live:{state:'attention', asks:'gh pr merge 105 --squash'}}}, {}).detail,
    'Your OK on the screen: gh pr merge 105 --squash');
  assert.equal(helpers.helperState(live('idle'), {questions:[{id:'q1', answer:null}]}).detail, 'Your answer');
  // the case of 16 Nov: a helper with an open question shows Needs you, never Working
  assert.equal(helpers.helperState(live('idle'), {questions:[{id:'q1', answer:null}]}).word, 'Needs you');
});

test('helperRows: one row per running helper, working first, stuck last, with step, minutes and finished', () => {
  const tickets = [
    {id:'a', key:'ORCH-1', status:'active', checklist:[{done:true}, {state:'doing'}, {}]},
    {id:'b', key:'ORCH-2', status:'review', checklist:[]},
    {id:'c', key:'ORCH-3', status:'waiting'},
    {id:'d', key:'ORCH-4', status:'active'},
  ];
  const runs = {
    a:{running:true, helper:{state:'working', detail:''}, age_seconds:3125},
    b:{running:true, helper:{state:'stuck', detail:'Nothing running for 25 min'}, idle_seconds:1500},
    c:{running:true, helper:{state:'you', detail:'Your answer'}, idle_seconds:10800},
    d:{running:false},
  };
  const rows = helpers.helperRows(tickets, runs);
  assert.deepEqual(rows.map(r => r.ticket.key), ['ORCH-1', 'ORCH-3', 'ORCH-2']);
  assert.deepEqual({...rows[0].step}, {n:2, of:3});
  assert.equal(rows[0].minutes, 52);
  // ORCH-288: a skipped task counts in the total, like the "3/4" of the Tickets list
  const skip = helpers.helperRows([{id:'e', status:'active', checklist:[{done:true}, {done:true}, {wont_do:true}, {state:'doing'}]}], {e:{running:true, helper:{state:'working'}}});
  assert.deepEqual({...skip[0].step}, {n:4, of:4});
  assert.equal(rows[2].finished, true);
});

test('kit: the meta line and the summary use the same words on every page', () => {
  const UI = kit();
  assert.equal(UI.helperMeta({state:'working', step:{n:3, of:4}, minutes:52, detail:''}), 'Step 3 of 4 · 52 min');
  assert.equal(UI.helperMeta({state:'you', idle:180, detail:'Your answer'}), 'Since 3 h · your answer');
  // ORCH-2314: a wait for an OK says that it waits, never the cut-off start of the command (it is whole on the OK card)
  const ok = 'Your OK on the screen: S=/private/tmp/claude-502/-Users-x/sq.py; cd /tmp && python3 $S "RESTORE TABLE';
  assert.equal(UI.helperWhy(ok), 'Your OK on the screen');
  assert.equal(UI.helperWhy('Your answer and your OK on the screen: rm -rf build'), 'Your answer and your OK on the screen');
  assert.equal(UI.helperWhy('Nothing running for 18 min'), 'Nothing running for 18 min');
  assert.equal(UI.helperMeta({state:'you', idle:180, detail:ok}), 'Since 3 h · your OK on the screen');
  assert.equal(UI.helperMeta({state:'idle', detail:'Nothing running for 18 min'}), 'Nothing running for 18 min');
  assert.equal(UI.helperMeta({state:'idle', finished:true, detail:'Nothing running for 5 min'}), 'Finished · Nothing running for 5 min');
  assert.equal(UI.helperSummary([{state:'working'}, {state:'working'}, {state:'you'}, {state:'idle'}]), '2 working · 1 needs you · 1 idle');
  assert.equal(UI.helperSummary([{state:'you'}, {state:'you'}]), '2 need you');
});

test('ORCH-643: a helper stopped on the usage limit shows Stopped: usage limit and when it continues, after stuck', () => {
  const run = {running:true, helper:{state:'limit', word:'Stopped: usage limit', detail:'Continues at 19:10'}};
  assert.deepEqual({...helpers.helperState(run, {})}, {state:'limit', word:'Stopped: usage limit', detail:'Continues at 19:10'});
  const rows = helpers.helperRows([{id:'l', status:'active'}, {id:'s', status:'active'}],
    {l:run, s:{running:true, helper:{state:'stuck', detail:'Nothing running for 25 min'}}});
  assert.deepEqual(rows.map(r => r.state), ['stuck', 'limit']);
  const UI = kit();
  assert.equal(UI.helperMeta({state:'limit', minutes:52, detail:'Continues at 19:10'}), 'Continues at 19:10');
  assert.equal(UI.helperSummary([{state:'working'}, {state:'limit'}, {state:'limit'}]), '1 working · 2 stopped on the usage limit');
  assert.match(UI.helperPill('limit', 'Stopped: usage limit').className, /^pill helper-pill$/);
  const s = UI.ticketState({status:'active'}, {state:'limit', word:'Stopped: usage limit', detail:'Continues at 19:10'});
  assert.equal(s.word, 'Stopped: usage limit'); assert.equal(s.pill, 'check');
});

test('ORCH-2314: a helper that waits for an OK on its screen may say so in its pill; any other word stays Needs you', () => {
  const UI = kit();
  assert.equal(UI.ticketState({status:'active'}, {state:'you', word:'Waits for your OK', detail:'Your OK on the screen: ls'}).word, 'Waits for your OK');
  assert.equal(UI.ticketState({status:'active'}, {state:'you', word:'Anything else', detail:''}).word, 'Needs you');
  assert.equal(UI.ticketState({status:'active'}, {state:'working', word:'Waits for your OK'}).word, 'Working');
});

test('kit: the Helpers list shows ORCH-n, title, the worded pill and the row buttons; an empty list says so', () => {
  const UI = kit();
  let pressed = '';
  const box = UI.helperList([{key:'ORCH-32', title:'Make the suite pass', href:'#t', state:'idle', word:'Idle', detail:'Nothing running for 18 min',
    actions:[{label:'Remind', key:'k-nudge', run:() => { pressed = 'nudge'; }}]}], {dataKey:'helpers'});
  const words = texts(box).join(' | ');
  assert.match(words, /Helpers \| 1 idle \| ORCH-32 \| Make the suite pass \| Nothing running for 18 min \| Idle \| Remind/);
  const row = box.children[1], button = row.children[1].children[1];
  assert.equal(row.dataset.state, 'idle'); assert.equal(button.dataset.key, 'k-nudge');
  button.onclick(); assert.equal(pressed, 'nudge');
  assert.match(texts(UI.helperList([], {empty:'No helper is running.'})).join(' '), /No helper is running\./);
  assert.match(UI.helperPill('stuck', 'Stuck').className, /pill helper-pill failed/);
});

test('Home: the Helpers side card replaces Working now, with Remind on idle rows and Stop on finished idle ones, none for a ticket in Review', () => {
  const items = [
    {id:'w', key:'ORCH-56', title:'Fix flaky test', status:'active', checklist:[{state:'doing'}]},
    {id:'i', key:'ORCH-32', title:'Windows suite', status:'active'},
    {id:'f', key:'ORCH-40', title:'Done but open', status:'done'},
    {id:'r', key:'ORCH-314', title:'Waits for review', status:'review'},
  ];
  const runs = {w:{running:true, helper:{state:'working'}, age_seconds:600}, i:{running:true, helper:{state:'idle', detail:'Nothing running for 8 min'}},
    f:{running:true, helper:{state:'idle', detail:'Nothing running for 3 min'}}, r:{running:true, helper:{state:'idle', detail:'Nothing running for 55 s'}}};
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const UI = kit(), seen = [];
  const c = vm.createContext({window:{DashHelpers:helpers, UI:{...UI, helperList:(rows, o) => { seen.push(...rows); return h('section', {'data-key':o.dataKey}, 'Helpers'); }}},
    localStorage:{getItem(){}}, h, fragment:(...children) => h('fragment', {}, children), array:v => Array.isArray(v) ? v : [],
    tickets:() => items, ticketOf:id => items.find(t => t.id === id), questions:() => [], shown:t => t, clean:v => v, name:() => '',
    href:id => '#ticket/' + id, snapshot:false, needsList:() => [], state:{runs, settings:{}}, starting:new Set(), sorted:v => v,
    heading:(...text) => h('h1', {}, text), now:() => new Date(), parse:() => null, capitalise:v => v, emptyRow:text => h('p', {}, text),
    card:(key, title, count, body) => h('section', {'data-key':key}, title, count, body), chip:t => t, statusChip:() => null, titleTag:() => null,
    STATUS_CHOICES:helpers.STATUS_CHOICES});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/home.js'), 'utf8'), c);
  const text = JSON.stringify(c.home());
  assert.match(text, /"data-key":"helpers"/); assert.doesNotMatch(text, /Working now/);
  assert.deepEqual(seen.map(r => [r.key, r.word, r.meta, r.actions.map(a => a.label).join()]), [
    ['ORCH-56', 'Working', 'Step 1 of 1 · 10 min', ''],
    ['ORCH-32', 'Idle', 'Nothing running for 8 min', 'Remind'],
    ['ORCH-40', 'Idle', 'Finished · Nothing running for 3 min', 'Stop'],
  ]);  // ORCH-407: ORCH-314 waits for review: it is the person's Test results, no Helpers row and no Stop
});

test('ticket page: the state pill, the last activity line and a Stop that says when the helper is idle', () => {
  const ticket = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
  assert.match(ticket, /'Last activity ' \+ window\.DashHelpers\.ago\(last\.at/);
  assert.match(ticket, /window\.UI\.helperPill\(helper\.state, helper\.word\)/);
  assert.match(ticket, /idle \? 'Stop idle helper' : 'Stop'/);
  const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
  assert.match(app, /const helper = window\.DashHelpers\.helperState\(run, t\)/);  // the ticket chip reads the same state
});

// ORCH-218: the master widget for a terminal command to copy.
test('commandCopy: the command as text, a lead line and one Copy button named for the command', () => {
  const UI = kit();
  const box = UI.commandCopy('az login', {lead: 'Open a terminal on this computer and run:', dataKey: 'k'});
  assert.equal(box.className, 'cmd-copy');
  assert.equal(box.dataset.key, 'k');
  assert.deepEqual(texts(box), ['Open a terminal on this computer and run:', 'az login', 'Copy']);
  const b = box.children[1].children[1];
  assert.equal(b.tagName, 'button');
  assert.equal(b.attrs['aria-label'], 'Copy az login');
  assert.deepEqual(texts(UI.commandCopy('gh auth login')), ['gh auth login', 'Copy']);
});

// ORCH-476: one count source. The page reads the core's numbers (state.counts from orch/counts.py) and only takes off
// what it hides for a moment; the step and the task counts are the core's too.
test('ORCH-476: the needs-you number is the core items minus the rows this page hides', () => {
  const counts = {needs_you:{count:3, questions:2, results:1, items:[{ticket:'t_a', question:'q1'}, {ticket:'t_a', question:'q2'}, {ticket:'t_r', question:null}]}};
  assert.deepEqual({...helpers.needsYouFrom(counts, [])}.count, 3);
  const hid = helpers.needsYouFrom(counts, [{ticket:'t_a', answer:{question:'q2'}}]);
  assert.equal(hid.count, 2); assert.equal(hid.questions, 1); assert.equal(hid.results, 1);
  assert.equal(helpers.needsYouFrom(null, []), null, 'an older core: the page counts as before');
});

test('ORCH-476: step and progress come from the core, with the same rule for an older core', () => {
  const t = {id:'t_d', status:'active', checklist:[{done:true}, {wont_do:true}, {done:true}, {state:'doing'}]};
  assert.deepEqual({...helpers.stepOf(null, t)}, {n:4, of:4});
  assert.deepEqual({...helpers.stepOf({tickets:{t_d:{step:{n:2, of:9}}}}, t)}, {n:2, of:9}, 'the core wins');
  const p = helpers.progressOf(null, t);
  assert.deepEqual([p.done, p.wont_do, p.doing, p.todo, p.finished, p.total], [2, 1, 1, 0, 3, 4]);
  assert.equal(helpers.stepOf(null, {...t, status:'done'}), null);
  const rows = helpers.helperRows([t], {t_d:{running:true, helper:{state:'working'}}}, {tickets:{t_d:{step:{n:3, of:4}}}});
  assert.deepEqual({...rows[0].step}, {n:3, of:4});
  assert.equal(helpers.WONT_DO, "Won't do");
});

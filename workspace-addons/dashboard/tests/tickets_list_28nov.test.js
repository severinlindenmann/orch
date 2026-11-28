'use strict';
// Owner decisions of 28 Nov on the Tickets page (walk-28nov, batch b304):
//   O-13 a group opens and closes on every click, also after a refresh and during a search;
//   O-15 C / W-022 C no button on a row or a group line: one state mark per row; under 900 px of page area the compact rows;
//   O-14 D "Top tickets only" (off at first) and the parent named across status groups;
//   O-16 C two-line Board cards with the state as an icon in the top right corner.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const helpers = require(path.join(WEB, 'helpers.js'));
const listSrc = fs.readFileSync(path.join(WEB, 'pages/tickets.js'), 'utf8');

// A node that keeps its listeners, so a test can click the button of an EARLIER draw: the page keeps a drawn button
// (reconcile, by data-key) and with it the click it got then.
function h(tag, attrs = {}, ...kids) {
  const n = {tag, attrs, children:kids.flat(Infinity).filter(x => x != null && x !== false), listeners:{}, dataset:{}, style:{setProperty() {}}, classList:{add() {}}};
  n.setAttribute = (k, v) => { n.attrs[k] = v; };
  n.addEventListener = (type, fn) => { (n.listeners[type] ||= []).push(fn); };
  n.querySelector = () => null; n.querySelectorAll = () => [];
  n.click = () => (n.listeners.click || []).forEach(fn => fn({target:{closest:() => null}}));
  return n;
}
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
const byKey = (root, key) => nodes(root).find(n => n.attrs?.['data-key'] === key);
const keys = (root, prefix) => nodes(root).map(n => n.attrs?.['data-key']).filter(k => k && k.startsWith(prefix));
const pill = word => h('span', {className:'pill'}, word);
const UI = {ticketPill:s => pill(s.word), helperPill:(state, word) => pill(word), statusIcon:name => h('svg', {className:'st ' + name}),
  shortGroup:o => h('section', {className:'card short-group', 'data-key':o.key, folded:o.folded, toggle:o.onToggle}, o.title, o.folded ? [] : o.rows.map(r => h('div', {className:'short-row', 'data-key':r.dataKey, href:r.href}, r.title, r.fact, r.side)))};

function listCtx(items, extra = {}) {
  let draws = 0;
  const c = {h, fragment:(...k) => h('frag', {}, ...k), window:{DashHelpers:helpers, UI}, array:v => Array.isArray(v) ? v : [], clean:String, URLSearchParams,
    questions:t => (t.questions || []).filter(q => q.answer == null), shown:t => t, chip:(t, cls) => h('span', {className:'chip ' + cls}, t),
    statusChip:t => h('span', {className:'chip'}, t.status), state:{runs:{}, tickets:items}, starting:new Set(), needsList:() => [], tickets:() => c.state.tickets,
    ticketOf:id => c.state.tickets.find(t => t.id === id), sorted:v => v, name:v => String(v || ''), location:{hash:'#tickets'}, history:{replaceState(_a, _b, url) { c.location.hash = url; }},
    snapshot:true, href:id => '#ticket/' + id, render() { draws++; }, iconEl:() => null, now:() => Date.now(), overdue:() => false, dueText:() => '',
    titleTag:() => null, parentLine:t => h('p', {}, 'Sub-ticket of ' + t.parent), localStorage:{getItem:() => null, setItem() {}},
    heading:(...a) => h('header', {}, a.filter(x => typeof x === 'string')), statusItems:() => null,
    button:(label, cls) => h('button', {className:'btn ' + cls}, label), ...extra};
  c.draws = () => draws;
  vm.createContext(c); vm.runInContext(listSrc, c); return c;
}
const at = n => '2026-11-2' + (n % 8) + 'T0' + (n % 9) + ':00:00Z';
const BASIC = [
  {id:'q', key:'D-1', title:'Pick a logo', status:'waiting', questions:[{id:'q1', text:'Blue or green?'}], created_at:at(1)},
  {id:'r', key:'D-2', title:'Newsletter draft', status:'review', created_at:at(2)},
  {id:'w', key:'D-3', title:'Price list', status:'active', created_at:at(3)},
  {id:'o', key:'D-4', title:'Later idea', status:'open', created_at:at(4)},
  {id:'d', key:'D-5', title:'Old thing', status:'done', done_at:at(5), created_at:at(0)},
];

test('O-13: the button of the first draw opens and closes its group three times; the rows come back each time', () => {
  for (const status of ['waiting', 'review', 'active', 'open', 'done']) {
    const c = listCtx(BASIC);
    const first = c.ticketTable(c.filteredTickets());
    const toggle = byKey(first, 'group-toggle-' + status);  // kept by the page over every later draw
    const rowsOf = () => keys(c.ticketTable(c.filteredTickets()), 'tree-').length;
    const open = rowsOf();
    for (let i = 0; i < 3; i++) {
      toggle.click();
      assert.equal(vm.runInContext('foldedGroups.has(' + JSON.stringify(status) + ')', c), true, status + ': closed after click ' + (2 * i + 1));
      assert.equal(byKey(c.ticketTable(c.filteredTickets()), 'group-toggle-' + status).attrs['aria-expanded'], 'false');
      assert.equal(rowsOf(), open - 1, status + ': its row is gone');
      toggle.click();
      assert.equal(vm.runInContext('foldedGroups.has(' + JSON.stringify(status) + ')', c), false, status + ': open again after click ' + (2 * i + 2));
      assert.equal(byKey(c.ticketTable(c.filteredTickets()), 'group-toggle-' + status).attrs['aria-expanded'], 'true');
      assert.equal(rowsOf(), open, status + ': its row is back');
    }
    assert.equal(c.draws(), 6, 'every click draws the list again');
  }
});
test('O-13: the same after the list refreshed itself, and during a search (a search has its own folds)', () => {
  const c = listCtx(BASIC);
  const toggle = byKey(c.ticketTable(c.filteredTickets()), 'group-toggle-waiting');
  toggle.click();
  c.state = {...c.state, tickets:BASIC.map(t => ({...t}))};  // a refresh: new ticket objects, the drawn button stays
  for (let i = 0; i < 3; i++) {
    toggle.click();
    assert.ok(keys(c.ticketTable(c.filteredTickets()), 'tree-').includes('tree-q'), 'open after the refresh, round ' + i);
    toggle.click();
    assert.ok(!keys(c.ticketTable(c.filteredTickets()), 'tree-').includes('tree-q'), 'closed after the refresh, round ' + i);
  }
  toggle.click();
  vm.runInContext("ticketSearch = 'logo'; searchFolds.clear()", c);
  assert.ok(keys(c.ticketTable(c.filteredTickets()), 'tree-').includes('tree-q'), 'a search shows its hit');
  for (let i = 0; i < 3; i++) {
    toggle.click();
    assert.equal(vm.runInContext("searchFolds.has('waiting') && !foldedGroups.has('waiting')", c), true, 'the fold is the search\'s own');
    assert.ok(!keys(c.ticketTable(c.filteredTickets()), 'tree-').includes('tree-q'));
    toggle.click();
    assert.ok(keys(c.ticketTable(c.filteredTickets()), 'tree-').includes('tree-q'), 'restored during the search, round ' + i);
  }
  // the compact rows use the same click
  const group = byKey(c.phoneList(c.filteredTickets()), 'short-waiting');
  for (let i = 0; i < 3; i++) {
    group.attrs.toggle();
    assert.equal(byKey(c.phoneList(c.filteredTickets()), 'short-waiting').attrs.folded, true);
    group.attrs.toggle();
    assert.equal(byKey(c.phoneList(c.filteredTickets()), 'short-waiting').attrs.folded, false);
  }
});

test('O-15 C: a row ends in one state mark in its own column, and holds no button; a group line holds only its toggle', () => {
  const c = listCtx(BASIC);  // a read-only copy: without the ⋯ Move menu, which stays the row's one control on the live page
  c.state.runs = {w:{running:true, helper:{state:'working'}}};
  const table = c.ticketTable(c.filteredTickets());
  const marks = Object.fromEntries(BASIC.map(t => [t.id, text(byKey(table, 'mark-' + t.id) || nodes(byKey(table, 'tree-' + t.id)).find(n => n.attrs?.className === 'ticket-mark nowrap'))]));
  assert.deepEqual(marks, {q:'Question', r:'Result', w:'Working', o:'Backlog', d:'Done'});
  for (const t of BASIC) {
    const row = byKey(table, 'tree-' + t.id), cells = row.children.filter(n => n.tag === 'td');
    assert.equal(cells.at(-2).attrs.className, 'ticket-mark nowrap', 'the mark has its own column');
    assert.deepEqual(nodes(row).filter(n => n.tag === 'button' || /(^| )btn( |$)/.test(n.attrs?.className || '')).map(text), [], t.id + ': no button on the row');
  }
  assert.equal(nodes(byKey(table, 'tree-q')).find(n => n.tag === 'a').attrs.href, '#ticket/q?tab=questions', 'a question row opens the ticket at its question');
  assert.equal(nodes(byKey(table, 'tree-r')).find(n => n.tag === 'a').attrs.href, '#ticket/r', 'a result row opens the ticket');
  for (const head of nodes(table).filter(n => n.attrs?.className === 'group-head')) assert.deepEqual(head.children.map(n => n.attrs.className), ['group-toggle']);
  assert.doesNotMatch(listSrc, /Answer all|tile-answer|'Test results'/);
});
test('O-15 C: the words of the mark: a stuck helper, an idle one, a failed start, a wait, paused, changes asked', () => {
  const c = listCtx([]);
  const word = (t, run) => { c.state.runs = run ? {[t.id]:run} : {}; return c.ticketMarkState(t).word; };
  assert.equal(word({id:'a', status:'active'}, {running:true, helper:{state:'stuck'}}), 'Stuck');
  assert.equal(word({id:'a', status:'active', stuck:'quiet'}), 'Stuck');
  assert.equal(word({id:'a', status:'active'}, {running:true, helper:{state:'idle'}}), 'Idle');
  assert.equal(word({id:'a', status:'active'}), 'In progress', 'Working is said only while a helper runs');
  assert.equal(word({id:'a', status:'waiting', waiting_on:{kind:'time', until:'2030-01-01T00:00:00Z'}}), 'Waiting');
  assert.equal(word({id:'a', status:'ready', sessions:[{id:'s'}]}), 'Paused');
  assert.equal(word({id:'a', status:'ready'}), 'To do');
  assert.equal(word({id:'a', status:'review', questions:[{id:'q', text:'Ok?'}]}), 'Question', 'a question comes before the result');
  assert.equal(word({id:'a', status:'dropped'}), "Won't do");
});

test('W-022 C: under 900 px of page area the list is the compact rows alone; from 900 px the table with the phone rows beside it', () => {
  const area = {clientWidth:785};
  let watched = null, fired = null;
  const c = listCtx(BASIC, {document:{getElementById:id => id === 'content' ? area : null, querySelector:() => null},
    ResizeObserver:function (fn) { fired = fn; this.observe = el => { watched = el; }; }, ticketView:'list'});
  let page = c.list();
  assert.equal(byKey(page, 'ticket-table'), undefined, 'no table beside the panel');
  const short = byKey(page, 'ticket-short');
  assert.equal(short.attrs.className, 'short-list', 'shown at every screen width, not only on a phone');
  assert.equal(text(byKey(short, 'short-q').children.at(-1)), 'Question', 'the state mark is the last thing in the row');
  assert.ok(nodes(short).every(n => n.tag !== 'button'), 'no button in view or out of view');
  assert.equal(watched, area, 'the page area is watched');
  const before = c.draws();
  fired(); assert.equal(c.draws(), before, 'a resize that stays under 900 px draws nothing');
  area.clientWidth = 1180; fired();
  assert.equal(c.draws(), before + 1, 'crossing 900 px draws the list again, once');
  page = c.list();
  assert.ok(byKey(page, 'ticket-table'), 'the table is back');
  assert.equal(byKey(page, 'ticket-short').attrs.className, 'phone-only short-list');
  fired(); assert.equal(c.draws(), before + 1, 'and nothing loops');
  area.clientWidth = 617; c.location.hash = '#home'; fired();
  assert.equal(c.draws(), before + 1, 'another page is never drawn from here');
});

// five epics with six sub-tickets each, spread over the status groups, and two tickets that stand alone
const STATUSES = ['open', 'ready', 'active', 'waiting', 'review', 'done'];
const FAMILY = [
  ...Array.from({length:5}, (_, e) => ({id:'e' + e, key:'E-' + e, title:'Epic ' + e, epic:true, status:'active', created_at:at(e)})),
  ...Array.from({length:30}, (_, i) => ({id:'s' + i, key:'S-' + i, title:'Part ' + i, parent:'e' + (i % 5), status:STATUSES[i % 6], created_at:at(i),
    ...(STATUSES[i % 6] === 'waiting' ? {questions:[{id:'q', text:'Which?'}]} : {}), ...(STATUSES[i % 6] === 'done' ? {done_at:at(i)} : {})})),
  {id:'x1', key:'X-1', title:'Alone one', status:'open', created_at:at(1)}, {id:'x2', key:'X-2', title:'Alone two', status:'review', created_at:at(2)},
];
test('O-14 D: Top tickets only is off at first; on, the list holds the epics and the tickets that stand alone, each epic with its count', () => {
  const c = listCtx(FAMILY);
  assert.equal(vm.runInContext('ticketTop', c), false, 'off until the person turns it on');
  assert.equal(c.filteredTickets().length, 37);
  const chip = nodes(h('div', {}, c.ticketFilters())).find(n => n.attrs?.['data-key'] === 'ticket-top');
  assert.equal(text(chip), 'Top tickets only');
  assert.equal(chip.attrs['aria-checked'], 'false');
  assert.equal(chip.attrs.href, '#tickets?top=1', 'the choice is a link: it has an address');
  c.location.hash = chip.attrs.href; c.syncTicketAddress();
  assert.equal(vm.runInContext('ticketTop', c), true);
  assert.deepEqual(c.filteredTickets().map(t => t.id).sort(), ['e0', 'e1', 'e2', 'e3', 'e4', 'x1', 'x2']);
  const table = c.ticketTable(c.filteredTickets());
  assert.deepEqual(keys(table, 'tree-').sort(), ['tree-e0', 'tree-e1', 'tree-e2', 'tree-e3', 'tree-e4', 'tree-x1', 'tree-x2']);
  assert.equal(text(byKey(table, 'parts-line-e0')), '6 tickets · 2 need you', 'one question and one result wait inside it');
  assert.equal(byKey(table, 'parts-line-x1'), undefined, 'a ticket that stands alone stays as it is');
  assert.equal(nodes(byKey(table, 'tree-e0')).find(n => n.tag === 'a').attrs.href, '#ticket/e0', 'the epic opens its ticket, with its sub-tickets');
  const on = nodes(h('div', {}, c.ticketFilters())).find(n => n.attrs?.['data-key'] === 'ticket-top');
  assert.equal(on.attrs['aria-checked'], 'true'); assert.equal(on.attrs.href, '#tickets', 'one more click turns it off');
});
test('O-14 D: it holds through a search, a status view and a refresh, and on the Board; a scoped Board still shows the parts', () => {
  const c = listCtx(FAMILY);
  c.location.hash = '#tickets?top=1&view=needs-you'; c.syncTicketAddress();
  assert.deepEqual(c.filteredTickets().map(t => t.id), ['x2'], 'Needs you, top tickets only: the result that stands alone');
  c.location.hash = '#tickets?top=1&q=Part'; c.syncTicketAddress();
  assert.deepEqual(c.filteredTickets().map(t => t.id), [], 'a sub-ticket is never a top ticket, also when its epic is filtered away');
  c.location.hash = '#tickets?top=1&q=Epic+3'; c.syncTicketAddress();
  assert.deepEqual(c.filteredTickets().map(t => t.id), ['e3']);
  assert.equal(c.ticketAddress(), '#tickets?q=Epic+3&top=1', 'the address keeps it');
  c.location.hash = '#tickets?top=1&layout=board'; c.syncTicketAddress();
  c.state = {...c.state, tickets:FAMILY.map(t => ({...t}))};  // a refresh
  const cards = keys(c.board(), 'card-').sort();
  assert.deepEqual(cards, ['card-e0', 'card-e1', 'card-e2', 'card-e3', 'card-e4', 'card-x1', 'card-x2'], '7 cards, not 37');
  assert.match(text(byKey(c.board(), 'card-e0')), /1\/6 done/, 'an epic card says how many of its tickets are done');
  vm.runInContext("boardScope = {root:'e0'}", c);
  assert.equal(keys(c.board(), 'card-').length, 6, 'opening an epic on the Board shows its six parts');
});
test('O-14 D: with the filter off a sub-ticket in another status group than its parent names the parent', () => {
  const c = listCtx(FAMILY);
  const table = c.ticketTable(c.filteredTickets());
  assert.equal(text(byKey(table, 'part-of-s0')), 'Part of Epic 0', 's0 is in Backlog, its epic in Working');
  assert.equal(byKey(table, 'part-of-s2'), undefined, 's2 sits under its epic in Working: indented, no second mention');
  const row = c.window.UI.shortGroup, rows = [];
  c.window.UI.shortGroup = o => { rows.push(...o.rows); return row(o); };
  c.phoneList(c.filteredTickets());
  assert.match(rows.find(r => r.dataKey === 'short-s0').fact, /Part of Epic 0$/, 'the compact row says it too');
});

test('O-16 C: a Board card is two lines: title on one line with the state icon top right, then tasks, the state word and the parent', () => {
  const items = [{id:'p', key:'B-1', title:'Website relaunch', status:'active', created_at:at(1)},
    {id:'k', key:'B-2', title:'Write the landing page text for the autumn campaign in three languages', parent:'p', status:'waiting', questions:[{id:'q1', text:'Tone?'}],
      checklist:[{done:true}, {}, {}], created_at:at(2), refs:[{url:'https://github.com/x/y/pull/1', view:{addon:'pull-requests', status:'checks failing', title:'Pull request', icon:'git'}}]},
    {id:'v', key:'B-3', title:'Check the result', status:'review', created_at:at(3)}];
  const c = listCtx(items, {snapshot:false});
  const card = c.boardCard(items[1], 'waiting');
  assert.deepEqual(card.children.map(n => n.attrs.className), ['row', 'tile-foot'], 'two lines');
  const [top, foot] = card.children;
  const title = nodes(top).find(n => n.tag === 'a');
  assert.equal(title.attrs.title, 'B-2 · Write the landing page text for the autumn campaign in three languages', 'the whole title on hover');
  assert.equal(title.attrs.href, '#ticket/k?tab=questions', 'and with a click, at its question');
  assert.equal(nodes(top).find(n => n.tag === 'h3').children[0].attrs.className, 'truncate', 'one line, cut with …');
  const icon = byKey(top, 'state-k');
  assert.equal(icon.attrs.role, 'img'); assert.equal(icon.attrs['aria-label'], 'Question'); assert.equal(icon.attrs.title, 'Question');
  const addon = byKey(top, 'addon-k');
  assert.match(nodes(addon).find(n => n.tag === 'summary').attrs['aria-label'], /Pull request: checks failing/, 'what an add-on says, with its words');
  assert.equal(top.children.at(-1), icon, 'the state icon is the last thing in the top right corner');
  assert.match(text(foot), /^1\/3 tasksQuestionPart of: Website relaunch/);
  const buttons = nodes(card).filter(n => /(^| )btn( |$)/.test(n.attrs?.className || ''));
  assert.deepEqual(buttons, [], 'no Answer or Test results button on a card');
  assert.match(text(c.boardCard(items[2], 'review')), /Result/);
  assert.equal(byKey(c.boardCard(items[2], 'review'), 'state-v').attrs['aria-label'], 'Result');
  // the card itself opens the ticket; a click on a link or ⋯ inside it keeps its own job
  card.listeners.click[0]({target:{closest:() => null}});
  assert.equal(c.location.hash, '#ticket/k?tab=questions');
  c.location.hash = '#tickets';
  card.listeners.click[0]({target:{closest:() => ({})}});
  assert.equal(c.location.hash, '#tickets');
});

// ORCH-189: the manager view in the Tickets list: Due and Time · cost columns, This week and Stuck views, the
// wider Stuck mark, a week total; and the helpers behind them.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');

const DAY = 86400000;
function context(items, hash = '#tickets', runs = {}) {
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null), addEventListener(){}, dataset:{}, classList:{add(){}}});
  const c = vm.createContext({window:{DashHelpers:helpers}, localStorage:{getItem(){}}, location:{hash}, URLSearchParams, h,
    fragment:(...children) => h('fragment', {}, children), array:v => Array.isArray(v) ? v : [],
    tickets:() => items, ticketOf:id => items.find(t => t.id === id), questions:t => (t.questions || []).filter(q => q.answer == null),
    shown:t => t, clean:v => v, name:() => '', href:id => '#ticket/' + id, snapshot:true, iconEl:() => null, parentLine:() => null,
    chip:(text, cls) => h('span', {className:'chip ' + cls}, text), statusChip:t => h('span', {}, t.status),
    needsList:() => [], state:{runs}, starting:new Set(), sorted:v => v, STATUS_CHOICES:helpers.STATUS_CHOICES,
    heading:(...text) => h('h1', {}, text), now:() => new Date(), parse:() => null, capitalise:v => v,
    overdue:t => helpers.dueLate(t.due, t.status, new Date()), dueText:t => t.due ? 'Due ' + t.due : '',
    emptyRow:text => h('p', {}, text), card:(key, title, count, body) => h('section', {}, title, count, body),
    activeTicket:() => true, ticketAttentionChip:() => null, titleTag:() => null});
  for (const file of ['home', 'tickets']) vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/' + file + '.js'), 'utf8'), c);
  return c;
}
function nodes(n, predicate) { return !n || typeof n !== 'object' ? [] : [...(predicate(n) ? [n] : []), ...(n.children || []).flatMap(c => nodes(c, predicate))]; }
const text = n => typeof n === 'string' ? n : (n?.children || []).map(text).join('');
const day = ms => new Date(ms).toLocaleDateString('sv');

test('helpers: time and money words, totals, stuck lines, this week', () => {
  assert.equal(helpers.spendWords({seconds:6000, cost:3.1}), '1 h 40 min · $3.10');
  assert.equal(helpers.spendWords({seconds:600, cost:0}), '10 min');
  assert.equal(helpers.spendWords(null), '');
  assert.deepEqual(helpers.spendTotal([{spend:{cost:1, seconds:60}}, {}, {spend:{cost:2.5, seconds:120}}]), {cost:3.5, seconds:180});
  const now = Date.parse('2026-11-18T12:00:00Z');
  assert.equal(helpers.stuckWords({stuck:'question', questions:[{sent_at:'2026-11-15T12:00:00Z'}]}, now), 'Question waits 3 days');
  assert.equal(helpers.stuckWords({stuck:'quiet', quiet_since:'2026-11-17T10:00:00Z'}, now), 'No news for 26 h');
  assert.equal(helpers.stuckWords({stuck:'overdue'}, now), 'Past its due date');
  assert.equal(helpers.stuckWords({}, now), '');
  const wed = new Date(2026, 10, 18, 12).getTime(), monday = new Date(2026, 10, 16).getTime();
  assert.equal(helpers.weekStart(wed), monday);
  assert.equal(helpers.inThisWeek({}, 'active', wed), true);
  assert.equal(helpers.inThisWeek({due:'2026-11-22'}, 'open', wed), true, 'due Sunday');
  assert.equal(helpers.inThisWeek({due:'2026-11-23'}, 'open', wed), false, 'due next Monday');
  assert.equal(helpers.inThisWeek({due:'2026-11-10'}, 'open', wed), true, 'late and still open');
  assert.equal(helpers.inThisWeek({}, 'open', wed), false);
  assert.equal(helpers.inThisWeek({done_at:new Date(2026, 10, 17).toISOString()}, 'done', wed), true);
  assert.equal(helpers.inThisWeek({done_at:new Date(2026, 10, 14).toISOString()}, 'done', wed), false);
});

test('tickets list: Due and Time · cost columns, stuck chip and line, This week and Stuck views with a total', () => {
  const today = day(Date.now()), past = day(Date.now() - 3 * DAY), later = day(Date.now() + 40 * DAY);
  const items = [
    {id:'a', key:'D-1', title:'Late one', status:'active', due:past, stuck:'overdue', spend:{cost:3.1, seconds:6000}},
    {id:'b', key:'D-2', title:'Today', status:'open', due:today},
    {id:'c', key:'D-3', title:'Later', status:'open', due:later, spend:{cost:0.3, seconds:600}},
    {id:'e', key:'D-4', title:'Helper stuck', status:'active'},
    {id:'f', key:'D-5', title:'Old done', status:'done', done_at:'2000-01-01T00:00:00Z', stuck:'overdue'},
  ];
  const runs = {e:{state:'stuck', alive:true}};
  let c = context(items, '#tickets', runs);
  if (helpers.helperState(runs.e, items[3])?.state !== 'stuck') c.state.runs = {};
  const table = c.ticketTable(c.filteredTickets());
  const heads = nodes(table, n => n.tag === 'th' && n.attrs?.scope === 'col').map(text);
  assert.deepEqual(heads.slice(1), ['Due', 'Steps', 'Time · cost', 'Last change', 'Actions']);
  const row = id => nodes(table, n => n.attrs?.['data-key'] === 'tree-' + id)[0];
  const due = id => nodes(row(id), n => n.attrs?.className === 'due-cell')[0].children[0];
  assert.equal(due('a').attrs.className, 'bad');
  assert.equal(due('b').attrs.className, 'warn');
  assert.equal(due('c').attrs.className, '');
  assert.equal(text(nodes(row('a'), n => /spend-cell/.test(n.attrs?.className || ''))[0]), '1 h 40 min · $3.10');
  assert.equal(text(nodes(row('b'), n => /spend-cell/.test(n.attrs?.className || ''))[0]), '–');
  assert.match(text(row('a')), /Stuck/);
  assert.match(text(row('a')), /Past its due date/);
  assert.doesNotMatch(text(row('c')), /Stuck/);
  const chips = nodes(c.viewChips(), n => n.attrs?.['data-key']?.startsWith('view-chip-')).map(text);
  assert.ok(chips.includes('This week'));
  const stuckIds = c.filterTickets(items, '', false, '', '', 'stuck').map(t => t.id);
  assert.ok(stuckIds.includes('a') && !stuckIds.includes('f') && !stuckIds.includes('c'));
  c = context(items, '#tickets?view=this-week', {});
  const week = c.filteredTickets().map(t => t.id);
  assert.deepEqual(week.sort(), ['a', 'b', 'e']);
  const total = nodes(c.ticketTable(c.filteredTickets()), n => n.attrs?.['data-key'] === 'week-total')[0];
  assert.match(text(total), /This week.*1 h 40 min · \$3\.10/);
});

test('ticket page: Time · cost puts the first-run estimate beside what it took so far', () => {
  assert.equal(helpers.costLine({estimate:{minutes:95, cost:3.5}, spend:{seconds:1800, cost:1.1}}),
    'Estimate: about 1 h 35 min · $3.50 — So far: 30 min · $1.10');
  assert.equal(helpers.costLine({estimate:{minutes:40}}), 'Estimate: about 40 min');
  assert.equal(helpers.costLine({spend:{seconds:600, cost:0.3}}), 'So far: 10 min · $0.30');
  assert.equal(helpers.costLine({estimate:{minutes:'x'}}), '');
  assert.equal(helpers.costLine({}), '');
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
  assert.match(src, /costValue\(t\) \? field\('Time · cost', costValue\(t\)\) : null/);
});

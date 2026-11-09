const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const web = file => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/' + file), 'utf8');
function context(items) {
  const h = (tag, attrs, ...children) => ({tag, attrs, addEventListener() {}, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({window:{DashHelpers:helpers}, h, array:v => Array.isArray(v) ? v : [], tickets:() => items,
    fragment:(...children) => h('fragment', {}, children), heading:(t, sub) => h('h1', {}, t, sub), clean:v => String(v ?? ''), href:id => '#ticket/' + id,
    render() {}});
  vm.runInContext(web('pages/ticket.js').slice(web('pages/ticket.js').indexOf('const NOTE_LABELS'), web('pages/ticket.js').indexOf('function ticketDoneLine')), c);
  vm.runInContext(web('pages/notes.js'), c);
  return c;
}
const text = n => JSON.stringify(n);
const nodes = (n, p) => !n || typeof n !== 'object' ? [] : [...(p(n) ? [n] : []), ...(n.children || []).flatMap(c => nodes(c, p))];
const done = (id, extra = {}) => ({id, title:'Ticket ' + id, status:'done', updated_at:'2026-11-0' + id.slice(-1) + 'T10:00:00Z', checklist:[], outcome:{changed:'Changed ' + id, why:'Why ' + id}, ...extra});
test('card shows the three parts on a done ticket and nothing otherwise', () => {
  const c = context([]);
  const card = c.ticketOutcomeCard(done('t_1', {outcome:{changed:'Pay button.', why:'No transfer.', not_included:'Refunds.'}}));
  const s = text(card);
  assert.match(s, /What changed and why/); assert.match(s, /Pay button\./); assert.match(s, /Not in this ticket/); assert.match(s, /Refunds\./);
  assert.equal(c.ticketOutcomeCard(done('t_1', {status:'review'})), null);
  assert.equal(c.ticketOutcomeCard(done('t_1', {outcome:undefined})), null);
  assert.equal(c.ticketOutcomeCard(done('t_1', {outcome:{}})), null);
  assert.doesNotMatch(text(c.ticketOutcomeCard(done('t_1', {outcome:{why:'Only why'}}))), /Not in this ticket|Changed/);
});
test('notes: only done tickets with an outcome, newest first', () => {
  const items = [done('t_1'), done('t_3'), done('t_2'), done('t_4', {status:'active'}), done('t_5', {outcome:undefined}), done('t_6', {outcome:{changed:'  '}})];
  const groups = context(items).notesGroups(items);
  assert.deepEqual(Array.from(groups, g => g.id), ['t_3', 't_2', 't_1']);
});
test('notes: grouped by parent, the parent is the group head and never sits under itself', () => {
  const items = [done('t_1', {title:'Parent'}), done('t_2', {parent:'t_1'}), done('t_4'), done('t_3', {parent:'t_1'}), done('t_9', {parent:'t_gone'}), done('t_8', {parent:'t_8'})];
  const groups = context(items).notesGroups(items);
  const shape = JSON.parse(JSON.stringify(groups.map(g => [g.id, g.head?.id || null, g.notes.map(n => n.id), g.parent?.id || null])));
  assert.deepEqual(shape, [['t_9', 't_9', [], null], ['t_8', 't_8', [], null], ['t_4', 't_4', [], null], ['t_1', 't_1', ['t_3', 't_2'], null]]);
});
test('notes: a parent without its own note gives its children a "Step of" header', () => {
  const items = [done('t_1', {title:'Parent', outcome:undefined}), done('t_2', {parent:'t_1'})];
  const g = context(items).notesGroups(items);
  assert.equal(g.length, 1); assert.equal(g[0].head, null); assert.equal(g[0].parent.id, 't_1'); assert.equal(g[0].notes[0].id, 't_2');
});
test('notes: order and time use when the ticket was marked done, not updated_at', () => {
  const hist = at => [{at, text:'Moved to Done', by:'human:Pat'}];
  const items = [done('t_1', {updated_at:'2026-11-09T10:00:00Z', history:hist('2026-11-01T10:00:00Z')}), done('t_2', {updated_at:'2026-11-02T10:00:00Z', history:hist('2026-11-05T10:00:00Z')}),
    done('t_3', {updated_at:'2026-11-03T10:00:00Z', done_at:'2026-11-07T10:00:00Z', history:hist('2026-11-01T10:00:00Z')})];
  const c = context(items);
  assert.deepEqual(Array.from(c.notesGroups(items), g => g.id), ['t_3', 't_2', 't_1']);
  assert.equal(c.doneAt(items[0]), '2026-11-01T10:00:00Z');
  assert.equal(c.doneAt(done('t_5')), done('t_5').updated_at);
});
test('notes: search matches title, key and the outcome text', () => {
  const items = [done('t_1', {title:'Pay button', outcome:{changed:'Receipt email'}}), done('t_2', {key:'PIL-7', outcome:{why:'VAT was mixed in'}}), done('t_3')];
  const c = context(items);
  assert.deepEqual(Array.from(c.notesGroups(items, 'receipt'), g => g.id), ['t_1']);
  assert.deepEqual(Array.from(c.notesGroups(items, ' vat '), g => g.id), ['t_2']);
  assert.deepEqual(Array.from(c.notesGroups(items, 'pil-7'), g => g.id), ['t_2']);
  assert.deepEqual(Array.from(c.notesGroups(items, 'pay'), g => g.id), ['t_1']);
  assert.equal(c.notesGroups(items, 'zzz').length, 0);
});
test('notes page: empty states and entries', () => {
  const empty = context([done('t_1', {outcome:undefined}), done('t_2', {status:'active'})]).notesPage();
  assert.match(text(empty), /Finished tickets will show what changed and why here\./);
  assert.equal(nodes(empty, n => n.attrs?.className === 'note-entry').length, 0);
  const items = [done('t_1', {title:'Pay button', checklist:[{},{},{},{}]}), done('t_2', {parent:'t_1', title:'Receipt'}), done('t_3', {parent:'t_1', title:'Pay link'})];
  const page = context(items).notesPage();
  assert.equal(nodes(page, n => n.attrs?.className === 'note-entry').length, 3);
  assert.match(text(page), /2 steps/); assert.doesNotMatch(text(page), /4 steps/); assert.doesNotMatch(text(page), /Step of /); assert.match(text(page), /Changed t_2/);
  assert.doesNotMatch(text(page), /Finished tickets will show/);
});
test('notes page is registered: route, nav, server and html', () => {
  assert.match(web('app.js'), /'#notes'/); assert.match(web('app.js'), /notesPage\(\)/);
  assert.match(web('index.html'), /pages\/notes\.js/); assert.match(web('index.html'), /pages\/notes\.css/);
  assert.match(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8'), /chat\|notes/);
});

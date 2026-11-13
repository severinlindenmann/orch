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
    fragment:(...children) => h('fragment', {}, children), name:v => String(v ?? ''), heading:(t, sub) => h('h1', {}, t, sub), clean:v => String(v ?? ''), href:id => '#ticket/' + id,
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
  assert.deepEqual(Array.from(context(items).notesList(items), t => t.id), ['t_3', 't_2', 't_1']);
});
test('notes: order and time use when the ticket was marked done, not updated_at', () => {
  const hist = at => [{at, text:'Moved to Done', by:'human:Pat'}];
  const items = [done('t_1', {updated_at:'2026-11-09T10:00:00Z', history:hist('2026-11-01T10:00:00Z')}), done('t_2', {updated_at:'2026-11-02T10:00:00Z', history:hist('2026-11-05T10:00:00Z')}),
    done('t_3', {updated_at:'2026-11-03T10:00:00Z', done_at:'2026-11-07T10:00:00Z', history:hist('2026-11-01T10:00:00Z')})];
  const c = context(items);
  assert.deepEqual(Array.from(c.notesList(items), t => t.id), ['t_3', 't_2', 't_1']);
  assert.equal(c.doneAt(items[0]), '2026-11-01T10:00:00Z');
  assert.equal(c.doneAt(done('t_5')), done('t_5').updated_at);
});
test('notes: search matches title, key and the outcome text', () => {
  const items = [done('t_1', {title:'Pay button', outcome:{changed:'Receipt email'}}), done('t_2', {key:'PIL-7', outcome:{why:'VAT was mixed in'}}), done('t_3')];
  const c = context(items), ids = q => Array.from(c.notesList(items, q), t => t.id);
  assert.deepEqual(ids('receipt'), ['t_1']);
  assert.deepEqual(ids(' vat '), ['t_2']);
  assert.deepEqual(ids('pil-7'), ['t_2']);
  assert.deepEqual(ids('pay'), ['t_1']);
  assert.equal(ids('zzz').length, 0);
});
test('notes page: empty states and rows that open the note', () => {
  const empty = context([done('t_1', {outcome:undefined}), done('t_2', {status:'active'})]).notesPage();
  assert.match(text(empty), /No notes from finished work yet/); assert.match(text(empty), /View finished tickets/);
  assert.equal(nodes(empty, n => n.attrs?.className === 'note-row').length, 0);
  const items = [done('t_1', {title:'Pay button'}), done('t_2', {parent:'t_1', title:'Receipt'})];
  const page = context(items).notesPage();
  const rows = nodes(page, n => n.attrs?.className === 'note-row');
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map(r => r.attrs.href).sort(), ['#note/t_1', '#note/t_2']);
  assert.match(text(page), /Changed t_2/); assert.match(text(page), /Step of Pay button/); assert.match(text(page), /2 notes from finished work/);
  assert.doesNotMatch(text(page), /No notes from finished work yet/);
});
test('note page: one note, and an honest page when it is gone', () => {
  const t = done('t_1', {title:'Pay button', owner:'Anna', outcome:{changed:'Pay button added', why:'No transfer', not_included:'Refunds'}});
  const c = context([t]), page = text(c.notePage(t));
  assert.match(page, /Pay button added/); assert.match(page, /No transfer/); assert.match(page, /Refunds/); assert.match(page, /Source ticket/);
  assert.match(text(c.notePage(undefined)), /This note is no longer available/);
  assert.match(text(c.notePage(done('t_2', {status:'active'}))), /This note is no longer available/);
});
test('notes page is registered: route, nav, server and html', () => {
  assert.match(web('app.js'), /'#notes'/); assert.match(web('app.js'), /notesPage\(\)/); assert.match(web('app.js'), /notePage\(ticketOf\(r\.id\)\)/);
  assert.match(web('index.html'), /pages\/notes\.js/); assert.match(web('index.html'), /pages\/notes\.css/);
  assert.match(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8'), /chat\|notes/);
});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/home.js'), 'utf8');
// O-01 D (28 Nov): a background service that stopped is a row of Blocked now (one line, one action), not a banner.
const part = src.slice(src.indexOf('function blockedRow'), src.indexOf('const ticketLink')) + src.slice(src.indexOf('function stoppedServices'), src.indexOf('// After an automatic update'));

function page(services, snapshot = false) {
  const el = (tag, props, ...kids) => ({tag, props: props || {}, kids: kids.flat().filter(k => k != null)});
  const c = vm.createContext({
    state: {services}, snapshot, h: el, array: v => Array.isArray(v) ? v : [],
    addons: () => [{name: 'sync', dashboard: {label: 'Sync'}}, {name: 'automation'}],
  });
  vm.runInContext(part + '\nthis.row = stoppedServicesRow;', c);
  return c.row();
}
const text = n => n == null ? '' : typeof n === 'string' ? n : (n.kids || []).map(text).join('');
const find = (n, pred) => !n || typeof n !== 'object' ? [] : [...(pred(n) ? [n] : []), ...(n.kids || []).flatMap(k => find(k, pred))];

test('owner feedback 14 Nov: a service that is off on purpose (Sync off) shows no "not running" row', () => {
  assert.equal(page([{addon: 'sync', running: false, idle: true}, {addon: 'dashboard', running: true}]), null);
});

test('the row names what is not running and offers Start', () => {
  const b = page([{addon: 'sync', running: false}, {addon: 'automation', running: false}, {addon: 'dashboard', running: true}]);
  // D5: the same sentence as the add-on's own page
  assert.match(text(b), /^Sync and Automation have stopped\.Their work waits\. Your tickets and everything else still work\./);
  assert.equal(b.props['data-key'], 'background'); assert.equal(b.props['data-blocked'], 'service');
  const [start] = find(b, n => n.tag === 'button');
  assert.equal(start.props['data-action'], 'start');
  assert.equal(text(start), 'Start them');
  const one = page([{addon: 'automation', running: false}]);
  assert.match(text(one), /^Automation has stopped\.Its work waits\./);
  assert.equal(text(find(one, n => n.tag === 'button')[0]), 'Start Automation');
});

test('a shared read-only copy has no Start button', () => {
  assert.equal(find(page([{addon: 'sync', running: false}], true), n => n.tag === 'button').length, 0);
});

const helpers = require('../src/orch_dashboard/web/helpers.js');
const ticket = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const openNeedSrc = ticket.slice(ticket.indexOf('async function openNeed'), ticket.indexOf('// A shipped add-on page'));

test('owner feedback 14 Nov (W11): the "not running" card is a Start button, not a dialog with only Cancel', async () => {
  assert.deepEqual({...helpers.needAction({kind: 'addon:not-running', tone: 'bad', ticket: null})}, {label: 'Start', kind: 'start'});
  const acted = [], toasts = [], dialogs = [];
  const c = vm.createContext({
    window: {DashHelpers: helpers, orch: {toast: (t, k) => toasts.push([t, k]), open: d => dialogs.push(d)}},
    act: async (op, args) => { acted.push([op, args]); return {ok: true}; },
    array: v => Array.isArray(v) ? v : [], addons: () => [], clean: x => x, dialog: () => { throw new Error('no dialog'); },
  });
  vm.runInContext(openNeedSrc + '\nthis.openNeed = openNeed;', c);
  const trigger = {disabled: false};
  await c.openNeed({id: 'core:down:sync', kind: 'addon:not-running', ticket: null, title: 'sync', text: 'sync is not running'}, trigger);
  assert.equal(JSON.stringify(acted), '[["addon.start",{}]]');
  assert.equal(trigger.disabled, false);
  assert.equal(dialogs.length, 0);
});

test('a need with no ticket, no page and no action says its text in a toast instead of a dead-end dialog', async () => {
  const toasts = [];
  const c = vm.createContext({
    window: {DashHelpers: helpers, orch: {toast: (t, k) => toasts.push(t), open: () => { throw new Error('no dialog'); }}},
    act: async () => ({ok: true}), array: v => Array.isArray(v) ? v : [], addons: () => [], clean: x => x,
    dialog: () => { throw new Error('no dialog'); },
  });
  vm.runInContext(openNeedSrc + '\nthis.openNeed = openNeed;', c);
  await c.openNeed({id: 'x', kind: 'sync-conflict', ticket: null, title: 'Conflict', text: 'Two copies changed.'}, {disabled: false});
  assert.equal(JSON.stringify(toasts), '["Two copies changed."]');
});


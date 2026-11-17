const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');

const sendBody = () => { const i = src.indexOf('async function repeatSend'); return src.slice(i, src.indexOf('\n}\n', i)); };
const dialogBody = () => { const i = src.indexOf('function repeatsDialog'); return src.slice(i, src.indexOf('async function repeatSend', i)); };

// e2e 15 Nov (item 3/4): Save closes the dialog at once; the list shows the repeat as "Saving…" until it is stored
test('Save and Delete close the dialog before the request and show the change in the list', () => {
  const body = sendBody();
  const close = body.indexOf('window.orch.close(d)'), pend = body.indexOf('pendingRepeat = pending'), call = body.indexOf("act('addon.act'");
  assert.ok(close > 0 && close < call, 'the dialog closes before the request');
  assert.ok(pend > close && pend < call, 'the pending row is set before the request');
  assert.ok(body.indexOf('pendingRepeat = null') > call, 'the pending row ends with the answer');
  const dlg = dialogBody();
  assert.match(dlg, /repeatSend\(d, \{addon:[^}]*verb:'repeat'/);
  assert.match(dlg, /repeatSend\(d, \{addon:[^}]*verb:'delete'/);
});

// "Saving…" must always end: a lost or very slow answer gives a plain message after 30 s
test('the repeat change gives up waiting after 30 s and always clears the pending row', () => {
  const body = sendBody();
  assert.match(body, /Promise\.race\(\[act\('addon\.act', args\), late\]\)/);
  assert.match(body, /30000/);
  assert.match(body, /finally \{[^}]*pendingRepeat = null;/);
  assert.ok(body.indexOf('pendingRepeat = null') < body.indexOf('loadAddon('), 'the list reloads after the pending row ends');
});

// e2e 15 Nov: the reload after Save was dropped while a poll was loading, so the new row stayed missing until the next poll
test('a reload asked while another load is under way is queued, not dropped', () => {
  const i = src.indexOf('async function loadAddon');
  const body = src.slice(i, src.indexOf('// The view of an add-on tab costs', i));
  assert.match(body, /if \(addonBusy\.has\(id\)\) \{ addonAgain\.add\(id\); return; \}/);
  assert.match(body, /if \(addonAgain\.delete\(id\)\) await loadAddon\(id\);/);
});

// owner feedback 14 Nov: choosing Custom must start on a valid value (5 minutes), so Save is never disabled at the start
test('Custom starts at 5 minutes (the lowest allowed), never below the limit', () => {
  assert.match(src, /choice\.unit = choice\.unit \|\| 'minutes'; if \(choice\.unit === 'minutes' && !\(Number\(choice\.every\) >= 5\)\) choice\.every = 5;/);
  assert.match(src, /unit\.value === 'minutes' \? Math\.max\(5, Number\(choice\.every\) \|\| 5\)/);
});

// ---- bug hunt 17 Nov (ORCH-231): run the pure parts of settings.js ----
function load() {
  const node = () => ({dataset:{}, append() {}, querySelectorAll() { return []; }, querySelector() { return null; }});
  const c = vm.createContext({
    window:{DashHelpers:{}, orch:{toast() {}}}, localStorage:{getItem() { return null; }, setItem() {}},
    h:() => node(), fragment:() => node(), el:() => node(), button:() => node(), iconEl:() => node(), array:v => Array.isArray(v) ? v : [],
    snapshot:false, clean:v => String(v ?? ''), render() {}, route:() => ({kind:'home'}), location:{hash:'#home'},
    setTimeout:() => 1, clearTimeout() {}, setInterval:() => 1, clearInterval() {}, document:{getElementById:() => null},
    locks:new Set(), state:null, addons:() => [], URL, main:node(), fetch:async () => ({ok:false}),
  });
  vm.runInContext(src, c);
  return c;
}

test('item 3: the waiting row names the ticket with its number and shows the new plan', () => {
  const c = load();
  assert.deepEqual([...c.pendingCells(4, {tid:'t_abcdef', title:'DEM-9 · Weekly sales report', plan:'Repeats every Saturday at 08:00'})],
    ['DEM-9 · Weekly sales report · Saving…', 'Repeats every Saturday at 08:00', '', '']);
  assert.deepEqual([...c.pendingCells(3, {tid:'t_abcdef', title:'DEM-9 · Weekly sales report', removing:true})],
    ['DEM-9 · Weekly sales report · Removing…', '', '']);
  assert.deepEqual([...c.pendingCells(1, {title:'DEM-9 · X', plan:'Repeats every day at 07:30'})], ['DEM-9 · X · Saving… · Repeats every day at 07:30']);
  assert.equal(c.repeatTicketName({id:'t_abcdef', key:'DEM-9', title:'Weekly sales report'}), 'DEM-9 · Weekly sales report');
  assert.equal(c.repeatTicketName({id:'t_abcdef'}), 't_abcdef');
});

test('item 3: the waiting row takes the place of the ticket\'s own row, so an edit never shows twice', () => {
  const body = src.slice(src.indexOf('function paintAddon'), src.indexOf('const addonAgain'));
  assert.match(body, /n\.dataset\.addonEdit === pendingRepeat\.tid/);
  assert.match(body, /if \(own\) own\.replaceWith\(row\); else body\.prepend\(row\);/);
});

test('item 2: a saved plan reads in plain words for the replace warning', () => {
  const c = load();
  assert.equal(c.savedRepeatWords('0 8 * * 1'), 'Repeats every Monday at 08:00');
  assert.equal(c.savedRepeatWords('30 7 * * *'), 'Repeats every day at 07:30');
  assert.equal(c.savedRepeatWords('0 */2 * * *'), 'Repeats every 2 hours');
  assert.equal(c.savedRepeatWords('0 8 1-7 * 1'), 'Repeats on a custom plan');
});

test('item 2: a new repeat for a ticket that already repeats warns and Save says Replace', () => {
  const dlg = dialogBody();
  assert.match(dlg, /repeatTicketName\(t\) \+ \(!only && repeatOf\(t\.id\) \? ' · already repeats' : ''\)/, 'the picker marks tickets that repeat');
  assert.match(dlg, /'This ticket already repeats ' \+ savedRepeatWords\(old\.cron\)/);
  assert.match(dlg, /save\.textContent = old \? 'Replace repeat' : 'Save repeat'/);
  assert.match(dlg, /ticket\.onchange = refreshReplace/);
  assert.ok(dlg.indexOf('refreshReplace();') > 0, 'checked once when the window opens (the first ticket may repeat)');
});

test('item 7: Delete asks first in the window and only the second click sends it', () => {
  const dlg = dialogBody();
  const first = dlg.slice(dlg.indexOf("const remove = button('Delete repeat'"), dlg.indexOf("const keep = button("));
  assert.doesNotMatch(first, /act\(|repeatSend/, 'the first click only asks');
  assert.match(first, /sure\.hidden = false/);
  const second = dlg.slice(dlg.indexOf("const yes = button('Delete repeat', 'danger'"), dlg.indexOf("sure.append("));
  assert.match(second, /verb:'delete'/);
  assert.match(dlg, /actions\.prepend\(remove, h\('span', \{className:'grow'/, 'Delete sits apart from Save');
});

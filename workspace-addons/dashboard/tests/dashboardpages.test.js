const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');
function context(items, extra = {}) {
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({window:{DashHelpers:helpers}, localStorage:{getItem(){}}, h,
    fragment:(...children) => h('fragment', {}, children), array:v => Array.isArray(v) ? v : [],
    tickets:() => items, ticketOf:id => items.find(t => t.id === id), questions:t => (t.questions || []).filter(q => q.answer == null),
    shown:t => t, clean:v => v, name:() => '', href:id => '#ticket/' + id, snapshot:true,
    chip:(text, cls) => h('span', {className:'chip ' + cls}, text), statusChip:t => h('span', {}, t.status),
    needsList:() => [], state:{}, starting:new Set(), sorted:v => v, STATUS_CHOICES:helpers.STATUS_CHOICES,
    heading:(...text) => h('h1', {}, text), now:() => new Date(), parse:() => null, capitalise:v => v,
    emptyRow:text => h('p', {}, text), card:(key,title,count,body) => h('section', {}, title,count,body),
    activeTicket:() => true, ticketAttentionChip:() => null, titleTag:() => null, ...extra});
  for (const file of ['home', 'tickets']) vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/' + file + '.js'), 'utf8'), c);
  return c;
}
function nodes(n, predicate) { return !n || typeof n !== 'object' ? [] : [...(predicate(n) ? [n] : []), ...(n.children || []).flatMap(c => nodes(c, predicate))]; }
test('board parts span columns, accept keys, and ignore children summaries and arrays', () => {
  const items = [{id:'p',key:'PIL-2',title:'Parent',status:'waiting',children:{total:3,closed:1,open:2}},
    {id:'a',key:'PIL-10',title:'First',parent:'p',status:'open'}, {id:'b',key:'PIL-11',title:'Second',parent:'PIL-2',status:'open'},
    {id:'c',key:'PIL-12',title:'Third',parent:'p',status:'waiting'}];
  for (const useHelpers of [false, true]) {
    const c = context(items);
    if (!useHelpers) c.window = {DashHelpers:{...helpers, childrenOf:undefined, parentOf:undefined}};
    const card = c.boardCard(items[0]);
    assert.match(JSON.stringify(card), /Steps · 0 of 3 done/);
    assert.equal(nodes(card, n => n.attrs?.className === 'board-part').length, 3);
    assert.match(JSON.stringify(c.boardCard(items[1])), /Step of Parent/);
    assert.doesNotMatch(JSON.stringify(c.boardCard(items[3], true)), /Step of Parent/);
    const rows = helpers.treeRows(c.ticketParents(items.filter(t => t.status === 'waiting')));
    assert.equal(rows[1].depth, 1);
    const board = c.board();
    const cards = nodes(board, n => n.tag === 'article');
    assert.equal(cards.length, 4);
    assert.equal(cards.filter(n => n.attrs.className.includes('board-child')).length, 1);
    const openColumn = nodes(board, n => n.attrs?.['data-status'] === 'open')[0];
    assert.equal(nodes(openColumn, n => n.tag === 'article').length, 2);
    assert.equal(nodes(openColumn, n => n.attrs?.className === 'meta board-parent').length, 2);
    assert.equal(c.boardChildren([{id:'p',children:['a']},{id:'a'}], {id:'p'}).length, 0);
  }
});
test('list groups have owner order and every ticket belongs to exactly one group', () => {
  const items = ['done','review','ready','open','active','waiting'].map(status => ({id:status,status}));
  items.push({id:'question',status:'active',questions:[{text:'Choose?'}]});
  const groups = context(items).ticketGroups(items);
  // ORCH-62: a waiting ticket without an open question is in its own group, not Needs you
  assert.deepEqual(Array.from(groups, g => g.title), ['Needs you','Working','Waiting','To do','Check','Done']);
  assert.deepEqual(Array.from(groups, g => Array.from(g.tickets, t => t.id)), [['question'],['active'],['waiting'],['ready','open'],['review'],['done']]);
});
test('home renders one need card per ticket with question count and yellow chip', () => {
  const t = {id:'p',title:'Pick a plan',status:'active',questions:[{id:'q1',text:'First?'},{id:'q2',text:'Second?'}]};
  const needs = t.questions.map(q => ({id:q.id,ticket:t.id,title:q.text,answer:{question:q.id}}));
  const c = context([t], {needsList:() => needs});
  const home = c.home(), text = JSON.stringify(home);
  assert.equal(nodes(home, n => n.attrs?.['data-need-row']).length, 1);
  assert.match(text, /2 questions/); assert.match(text, /2 things need you/); assert.match(text, /Needs you · 2/);  // one per question (ORCH-63) assert.doesNotMatch(text, /questions? for you/);
  assert.match(text, /First\?/); assert.doesNotMatch(text, /Second\?/);
  assert.equal(nodes(home, n => /chip/.test(n.attrs?.className || '')).length, 0); // the section heading already says it
  needs.shift();
  assert.match(JSON.stringify(c.home()), /Second\?/);
});
test('home: the Needs you heading shows the count (one per open question plus results to check, ORCH-63)', () => {
  const items = ['a', 'b', 'c'].map(id => ({id, title:'T ' + id, status:'active', questions:[{id:id + '1', text:'One?'}, {id:id + '2', text:'Two?'}]}));
  const needs = items.flatMap(t => t.questions.map(q => ({id:q.id, ticket:t.id, title:q.text, answer:{question:q.id}})));
  const text = JSON.stringify(context(items, {needsList:() => needs, button:label => ({tag:'button', children:[label]})}).home());
  assert.match(text, /6 things need you/);
  assert.equal(helpers.needsYouCount(needs), 6);
  assert.equal(helpers.needsYouCount([{id:'x'}, {id:'y', ticket:'a'}, {id:'z', ticket:'a', answer:{question:'q1'}}], [{id:'r'}]), 2, 'rows without a question are not counted');
  assert.equal(helpers.needsYouCount([], []), 0);
});
test('home: the badge and Menu count (needsToday) equal the Needs you heading and skip rows put off until later today', () => {
  const items = ['a', 'b', 'c'].map(id => ({id, title:'T ' + id, status:'waiting'}));
  const needs = items.flatMap(t => [1, 2].map(n => ({id:t.id + n, ticket:t.id, title:'Q?', answer:{question:t.id + n}, actions:[{later:true}]})));
  const later = {a1:'2026-11-12', a2:'2026-11-12'};
  const c = context(items, {needsList:() => needs, today:() => '2026-11-12', localStorage:{getItem:() => JSON.stringify(later)}, button:label => ({tag:'button', children:[label]})});
  const text = JSON.stringify(c.home());
  assert.equal(c.needsToday().count, 4);
  assert.match(text, /4 things need you/);
  const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
  assert.match(app, /const needCount = needsYouTotal\(\)/); assert.doesNotMatch(app, /needsList\(\)\.length/);
});
test('home: a failed start is on the page but not in the number (ORCH-63)', () => {
  const items = [{id:'a', title:'T a', status:'active'}, {id:'f', title:'T f', status:'waiting', waiting_on:{start:true, ref:'x'}}];
  const needs = [{id:'a1', ticket:'a', title:'Q?', answer:{question:'a1'}}];
  const text = JSON.stringify(context(items, {needsList:() => needs, button:label => ({tag:'button', children:[label]})}).home());
  assert.match(text, /could not start/);
  assert.match(text, /1 thing needs you/);
  const only = JSON.stringify(context([items[1]], {needsList:() => [], button:label => ({tag:'button', children:[label]})}).home());
  assert.match(only, /could not start/); assert.match(only, /Things to look at/); assert.doesNotMatch(only, /All clear/);
});

// Real /api/state shape from the test network (sanitized): `children` is a list of ids, `parent` an id.
test('ORCH-14: an epic says Epic on its board card; a ticket inside it says Part of the epic', () => {
  const items = [{id:'e',key:'ORCH-20',title:'Dashboard fixes',status:'open',epic:true}, {id:'x',key:'ORCH-21',title:'Fix the header',parent:'e',status:'done'}, {id:'y',key:'ORCH-22',title:'Larger buttons',parent:'e',status:'open'}];
  const c = context(items);
  assert.match(JSON.stringify(c.boardCard(items[0])), /Epic · 1 of 2 done/);
  assert.match(JSON.stringify(c.boardCard(items[2])), /Part of the epic Dashboard fixes/);
  assert.doesNotMatch(JSON.stringify(c.boardCard(items[2])), /Step of/);
});
test('parts on the real /api/state shape: each part sits in its OWN status group (ORCH-62), standing alone with its parent named', () => {
  const real = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/state-pilatus-parts.json'), 'utf8'));
  const items = real.tickets, [parent] = items.filter(t => t.key === 'PIL-2');
  assert.deepEqual(parent.children, ['t_1wis33', 't_fhm1w4']);
  assert.deepEqual(helpers.childrenOf(items, parent).map(t => t.key).sort(), ['PIL-10', 'PIL-11']);
  assert.equal(helpers.parentOf(items, items.find(t => t.key === 'PIL-10')).key, 'PIL-2');
  const c = context(items, {state:real});
  const groups = c.ticketGroups(c.ticketParents(items));
  const blocked = groups.find(g => g.status === 'blocked'), open = groups.find(g => g.status === 'open');
  assert.ok(blocked.tickets.some(t => t.key === 'PIL-2') && !blocked.tickets.some(t => /PIL-1[01]/.test(t.key)));
  assert.ok(['PIL-10', 'PIL-11'].every(k => open.tickets.some(t => t.key === k)), 'To do parts sit in To do');
  const rows = helpers.treeRows(open.tickets).filter(r => /PIL-1[01]/.test(r.ticket.key));
  assert.equal(rows.map(r => r.depth).join(), '0,0');
  assert.ok(rows.every(r => r.parentMissing), 'each names its parent on a Step of line');
  for (const g of groups) assert.equal(g.tickets.filter(t => c.ticketGroupOf(t) !== g.status).length, 0, 'a group holds only its own status');
});

test('Copy/Repeat capability is read from the real state.addons shape (active add-ons only, no active field)', () => {
  const real = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/state-pilatus-parts.json'), 'utf8'));
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const line = src.split('\n').find(l => l.startsWith('const repeatsAddon'));
  const c = vm.createContext({addons:() => real.addons});
  vm.runInContext(line, c);
  assert.equal(vm.runInContext('repeatsAddon()', c), 'automation');
  c.addons = () => [{name:'focus', dashboard:{panel:null}}];
  assert.equal(vm.runInContext('repeatsAddon()', c), null);
});


test('private settings card: move button, allow button, hidden when clear, no snapshot action', () => {
  const c = context([], {snapshot:false, addons:() => []});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  assert.equal(c.privateCard({}), null);
  assert.equal(c.privateCard({git_private:{count:0, lines:[], pending:[]}}), null);
  const settings = {git_private:{count:2, lines:['<b>Two files.</b>'], pending:[{name:'mine', showable:true, adapter:'generic', command:'run <x>', interactive:'live x', prompt:'stdin', key:'a'.repeat(64)}]}};
  const card = c.privateCard(settings);
  assert.deepEqual(nodes(card, n => n.textContent != null).map(n => n.textContent),
    ['Private files are in your team repo', '<b>Two files.</b>', 'Move to private',
     'This workspace asks to run a command', 'Helper: mine\nAdapter: generic\nCommand: run <x>\nLive command: live x\nPrompt: stdin', 'Allow on this computer']);
  const buttons = nodes(card, n => n.tag === 'button');
  assert.deepEqual(buttons.map(b => b.attrs['data-action']), ['private-move', 'private-allow']);
  vm.runInContext("settingsBusy.add('private')", c);
  assert.equal(nodes(c.privateCard(settings), n => n.tag === 'button')[0].attrs.disabled, true);
  c.state.settings = settings;
  const general = nodes(c.settingsPage(), n => n.attrs?.id === 'settings-panel-general')[0];
  assert.equal(general.children[0].attrs['data-key'], 'settings-private');
  c.snapshot = true;
  assert.equal(nodes(c.privateCard(settings), n => n.tag === 'button').length, 0);
  settings.git_private.count = 0;
  assert.equal(nodes(c.privateCard(settings), n => n.tag === 'h3').length, 1);
  const unsafe = n => ({name:'u' + n, showable:false});
  const text = s => nodes(c.privateCard({git_private:{count:0, lines:[], pending:s}}), n => n.textContent != null).map(n => n.textContent).join('|');
  assert.match(text([unsafe(1)]), /1 request orch can't show safely\. Not allowed\./);
  assert.match(text([unsafe(1), unsafe(2), unsafe(3)]), /3 requests orch can't show safely\. Not allowed\./);
  assert.equal(nodes(c.privateCard({git_private:{count:0, lines:[], pending:[unsafe(1), unsafe(2), unsafe(3)]}}), n => n.attrs?.className === 'card').length, 1);
});

test('Helpers at once (Settings > Helper): No limit by default, then 2 to 10, a select saved on change', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const start = src.indexOf('const LIVE_MAX_CHOICES'), end = src.indexOf('function shareCard');
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, snapshot:false, settingsBusy:new Set(), settingsText:(tag, a, t) => h(tag, a, t)});
  vm.runInContext(src.slice(start, end), c);
  const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
  const text = n => typeof n === 'string' ? n : (n.children || []).map(text).join(' ');
  const card = vm.runInContext('helpersAtOnceCard', c)({});
  const pick = all(card, n => n.attrs?.['data-key'] === 'settings-live-max')[0];
  assert.equal(pick.tag, 'select'); assert.equal(pick.value, 'none');
  assert.deepEqual(all(pick, n => n.tag === 'option').map(o => o.children[0]), ['No limit', '2', '3', '4', '5', '6', '7', '8', '9', '10']);
  assert.match(text(card), /Helpers at once/); assert.match(text(card), /Any number of helpers/);
  const four = vm.runInContext('helpersAtOnceCard', c)({live_max:4});
  assert.equal(all(four, n => n.attrs?.['data-key'] === 'settings-live-max')[0].value, '4');
  assert.match(text(four), /When 4 helpers are working, the next one waits in line/);
  assert.equal(all(vm.runInContext('helpersAtOnceCard', c)({live_max:99}), n => n.tag === 'select')[0].value, 'none');
  assert.ok(src.includes("permissionsCard(settings), helpersAtOnceCard(settings)]"), 'sits on the Helper tab');
});

test('Separate copies card: one plain row with a switch; when, cap, setup and the footnote shown plainly (no Details)', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const start = src.indexOf('const COPY_CHOICES'), end = src.indexOf('function settingsPage');
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, array:x => Array.isArray(x) ? x : [], snapshot:false, settingsBusy:new Set(), settingsText:(tag, a, t) => h(tag, a, t)});
  vm.runInContext(src.slice(start, end), c);
  const card = vm.runInContext('copiesCard', c)({copies:'always', copies_max:5, copy_setup:'npm ci'});
  const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
  const text = n => typeof n === 'string' ? n : (n.children || []).map(text).join(' ');
  // the visible part: one row, plain words, a switch; nothing technical outside Details
  assert.equal(all(card, n => n.tag === 'details').length, 0, 'no Details disclosure');
  const details = all(card, n => n.attrs?.['data-key'] === 'settings-copies-details')[0];
  const outside = text({children:all(card, n => n.tag === 'div' && n.attrs?.className === 'card')[0].children.filter(n => n !== details)});
  assert.match(outside, /Several helpers at once/);
  assert.doesNotMatch(text(vm.runInContext('copiesCard', c)({copies:'together'})), /\bgit\b|npm ci|\.env|nested repositories|warning line|e\.g\./i);
  const sw = all(card, n => n.attrs?.['data-key'] === 'settings-switch-copies')[0];
  assert.equal(sw.attrs.role, 'switch'); assert.equal(sw.attrs['aria-checked'], true); assert.equal(sw.attrs['data-mode'], 'off');
  // behind Details: when (two choices, the saved one selected), the cap, the setup and the plain footnote
  const choices = all(details, n => n.attrs?.['data-action'] === 'copies-mode');
  assert.deepEqual(choices.map(n => n.attrs['data-mode']), ['together', 'always']);
  assert.deepEqual(choices.map(n => n.attrs['aria-checked']), [false, true]);
  assert.equal(all(details, n => n.tag === 'select')[0].value, '5');
  assert.match(text(details), /Needs version history in this folder\./);
  assert.match(text(details), /Prepare a copy with/);
  // the setup field follows the page's one editing pattern: the value and Edit, then the field with Save / Cancel
  assert.match(text(details), /npm ci/);
  assert.equal(all(card, n => n.attrs?.['data-key'] === 'settings-copy-setup').length, 0);
  assert.equal(all(card, n => n.attrs?.['data-action'] === 'copies-setup-edit')[0].children[0], 'Edit');
  vm.runInContext('copySetupEditing = true', c);
  const editing = vm.runInContext('copiesCard', c)({copies:'always', copy_setup:'npm ci'});
  assert.equal(all(editing, n => n.attrs?.['data-key'] === 'settings-copy-setup')[0].attrs.value, 'npm ci');
  assert.deepEqual(all(editing, n => ['copies-setup', 'copies-setup-cancel'].includes(n.attrs?.['data-action'])).map(n => n.children[0]), ['Save', 'Cancel']);
  vm.runInContext('copySetupEditing = false', c);
  const dflt = vm.runInContext('copiesCard', c)({});
  assert.equal(all(dflt, n => n.attrs?.['data-key'] === 'settings-switch-copies')[0].attrs['aria-checked'], true);
  assert.deepEqual(all(dflt, n => n.attrs?.role === 'radio').map(n => n.attrs['aria-checked']), [true, false]);
  const off = vm.runInContext('copiesCard', c)({copies:'off'});
  const offSwitch = all(off, n => n.attrs?.['data-key'] === 'settings-switch-copies')[0];
  assert.equal(offSwitch.attrs['aria-checked'], false); assert.equal(offSwitch.attrs['data-mode'], 'together');
  });

test('Copies on this computer line: count, size, "Counting…" then a real empty state, Clean up now button', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const start = src.indexOf('const COPY_CHOICES'), end = src.indexOf('function settingsPage');
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, array:x => Array.isArray(x) ? x : [], snapshot:false, settingsBusy:new Set(), settingsText:(tag, a, t) => h(tag, a, t)});
  vm.runInContext(src.slice(start, end), c);
  const text = d => vm.runInContext('copiesDiskText', c)(d);
  assert.equal(text(null), 'Counting…');
  assert.equal(text({copies:0, bytes:0}), 'None right now · a copy is removed by itself when its ticket is done');
  assert.doesNotMatch(text({copies:0, bytes:0}), /…/);
  assert.equal(text({copies:2, bytes:1.4e9, partial:false}), '2 copies · 1.4 GB · removed by themselves when a ticket is done');
  assert.match(text({copies:1, bytes:5e6, partial:true}), /^1 copy · more than 5 MB/);
  assert.match(text({copies:1, bytes:0, orphaned:[{ws8:'aaaaaaaa', copies:2}]}), /2 copies from a moved or deleted project/);
  assert.match(text({copies:1, bytes:0, changed:1}), /1 removed copy changed after being saved/);
  assert.match(text({copies:1, bytes:0, stuck:[{ticket:'t_abc123'}]}), /a copy could not be cleaned up/);
  assert.doesNotMatch(text({copies:1, bytes:0, stuck:[{ticket:'t_abc123'}]}), /\bgit\b/);
  const card = vm.runInContext('copiesCard', c)({copies_disk:{copies:0, bytes:0, orphaned:[{ws8:'aaaaaaaa', copies:2}], stuck:[{ticket:'t_abc123'}]}});
  const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
  const btn = all(card, n => n.attrs?.['data-action'] === 'copies-clean')[0];
  assert.equal(btn.children[0], 'Clean up now');
  assert.equal(all(card, n => n.attrs?.['data-action'] === 'copies-orphaned').length, 1);
  assert.equal(all(card, n => n.attrs?.['data-action'] === 'copies-retry').length, 1);
  assert.equal(all(card, n => n.tag === 'details').length, 0);
});

test('Settings helper cards (fb10): title, one sentence and an example each; copy details only while Several helpers at once is on', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, array:x => Array.isArray(x) ? x : [], snapshot:false, settingsBusy:new Set(), settingsText:(tag, a, t) => h(tag, a, t)});
  vm.runInContext(src.slice(src.indexOf('function shareCard'), src.indexOf('function settingsPage')), c);
  const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
  const text = n => typeof n === 'string' ? n : (n.children || []).map(text).join(' ');
  const get = name => vm.runInContext(name, c);
  for (const [fn, title, key] of [['shareCard', 'Tell teammates about orch', 'settings-share'], ['workflowCard', 'Let helpers finish tickets', 'settings-workflow'], ['copiesCard', 'Several helpers at once', 'settings-copies']]) {
    for (const settings of [{share:false, agents_may_finish:false, copies:'off'}, {share:true, agents_may_finish:true, copies:'together'}]) {
      const card = get(fn)(settings), t = text(card);
      assert.ok(t.includes(title), fn + ' title');
      assert.match(t, /Example: /, fn + ' has an example');
      assert.equal(all(card, n => n.tag === 'h3').length >= 1, true);
      assert.equal(all(card, n => n.attrs?.className === 'meta' && /^Example: /.test(text(n))).length, 1, fn + ' one example line');
    }
  }
  const off = get('copiesCard')({copies:'off'}), on = get('copiesCard')({copies:'together'});
  assert.equal(all(off, n => n.attrs?.['data-key'] === 'settings-copies-details').length, 0, 'no copy details while off');
  assert.equal(all(on, n => n.attrs?.['data-key'] === 'settings-copies-details').length, 1, 'copy details while on');
  assert.doesNotMatch(text(get('workflowCard')({})), /Review/);
});

test('Settings review step: Share, the copies switch, Clean up now and "Helpers may mark tickets Done" show a plain review, then one click', async () => {
  const calls = [], focused = [];
  const c = context([], {snapshot:false, addons:() => [], render:() => {}, document:{querySelector:sel => ({focus:() => focused.push(sel)})},
    act:async (op, args) => { calls.push(JSON.stringify([op, args])); return {ok:true}; }});
  c.window.orch = {toast() {}};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  const settings = c.state.settings = {share:false, agents_may_finish:false, copies:'together', copies_max:4, copies_disk:{copies:3, bytes:0}};
  const text = n => typeof n === 'string' ? n : n.textContent != null ? String(n.textContent) : (n.children || []).map(text).join(' ');
  const panels = n => nodes(n, x => String(x.attrs?.className || '').split(' ').includes('settings-review'));
  assert.equal(panels(c.settingsPage()).length, 0, 'no review until a control is clicked');
  const cases = [
    ['share', 'shareCard', 'settings-switch-share', 'Share', /^Your team will see that this workspace uses orch\./, /AGENTS\.md/, ['share.set', {on:true}]],
    ['workflow', 'workflowCard', 'settings-switch-workflow', 'Turn on', /^Helpers will mark their finished work Done themselves\./, /waiting for your check stay there/, ['workflow.set', {on:true}]],
    ['copies-switch', 'copiesCard', 'settings-switch-copies', 'Turn off', /^Helpers will all work in your own folder/, /Your own files are not touched/, ['copies.set', {mode:'off'}]],
    ['copies-clean', 'copiesCard', 'settings-copies-clean', 'Clean up', /no helper needs any more will be removed/, /^Up to 3 copies will be removed.*Your own files are not touched\.$/, ['copies.clean', {}]],
  ];
  for (const [i, [id, cardFn, key, verb, what, affects, call]] of cases.entries()) {
    c.settingsReviewOpen(id, {disabled:false, dataset:{key}});
    assert.equal(focused.at(-1), '[data-key="settings-review-' + id + '"]', id + ': focus moves to the review');
    const shown = panels(c[cardFn](settings));
    assert.equal(shown.length, 1, id + ': one review, in its own card');
    const [panel] = shown;
    assert.equal(panel.attrs.className, 'cmd-preview settings-review', id + ': the look of the existing command review');
    assert.equal(panel.attrs.role, 'group'); assert.equal(panel.attrs.tabindex, '-1');
    assert.equal(panel.attrs['aria-labelledby'], 'settings-review-what'); assert.equal(panel.attrs['aria-describedby'], 'settings-review-affects');
    const [whatP, affectsP] = nodes(panel, n => n.tag === 'p');
    assert.match(text(whatP), what); assert.match(text(affectsP), affects);
    assert.doesNotMatch((text(whatP) + ' ' + text(affectsP)).replace('AGENTS.md', 'the file'), /\bagents?\b|relay|publish|\bgit\b|type .* to confirm/i);
    const buttons = nodes(panel, n => n.tag === 'button');
    assert.deepEqual(buttons.map(text), [verb, 'Cancel']);
    assert.deepEqual(buttons.map(b => b.attrs['data-action']), ['settings-review-ok', 'settings-review-cancel']);
    assert.equal(nodes(panel, n => n.tag === 'input').length, 0, id + ': no typed confirm word');
    assert.equal(calls.length, i, id + ': nothing is sent before the click');
    await c.settingsReviewRun();
    assert.equal(calls.at(-1), JSON.stringify(call), id + ': the confirm button runs the existing action');
    assert.equal(focused.at(-1), '[data-key="' + key + '"]', id + ': focus goes back to the control');
    assert.equal(panels(c[cardFn](settings)).length, 0);
  }
  // Cancel (and Escape, which calls the same close) sends nothing and gives focus back
  c.settingsReviewOpen('share', {disabled:false, dataset:{key:'settings-switch-share'}});
  c.settingsReviewClose();
  assert.equal(calls.length, cases.length);
  assert.equal(focused.at(-1), '[data-key="settings-switch-share"]');
  assert.equal(panels(c.shareCard(settings)).length, 0);
  // the review words follow the current state: turning things off says what stays
  Object.assign(settings, {share:true, agents_may_finish:true, copies:'off', copies_disk:{copies:0, bytes:0}});
  for (const [id, cardFn, verb, re] of [['share', 'shareCard', 'Stop sharing', /taken out of AGENTS\.md/], ['workflow', 'workflowCard', 'Turn off', /already Done stay Done/],
    ['copies-switch', 'copiesCard', 'Turn on', /At most 4 copies/], ['copies-clean', 'copiesCard', 'Clean up', /no copies right now, so nothing will be removed/]]) {
    settings.copies = id === 'copies-clean' ? 'together' : 'off';  // the copy details (Clean up now) show only while it is on
    c.settingsReviewOpen(id, {disabled:false, dataset:{key:'x'}});
    const [panel] = panels(c[cardFn](settings));
    assert.equal(text(nodes(panel, n => n.tag === 'button')[0]), verb);
    assert.match(text(panel.children[1]), re);
    c.settingsReviewClose();
  }
  // a busy action keeps its confirm button off; a disabled control or a shared copy opens nothing
  vm.runInContext("settingsBusy.add('share')", c);
  c.settingsReviewOpen('share', {disabled:false, dataset:{}});
  assert.equal(nodes(panels(c.shareCard(settings))[0], n => n.tag === 'button')[0].attrs.disabled, true);
  await c.settingsReviewRun();
  assert.equal(calls.length, cases.length, 'nothing is sent while the same change is still running');
  c.settingsReviewClose(); vm.runInContext("settingsBusy.delete('share')", c);
  c.settingsReviewOpen('share', {disabled:true, dataset:{}});
  assert.equal(panels(c.shareCard(settings)).length, 0);
  c.snapshot = true;
  c.settingsReviewOpen('share', {disabled:false, dataset:{}});
  assert.equal(panels(c.shareCard(settings)).length, 0);
});

test('app.js: the four Settings controls open the review; only the review buttons send; Escape cancels', () => {
  const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
  for (const [action, id] of [['settings-share', 'share'], ['workflow-set', 'workflow'], ['copies-switch', 'copies-switch'], ['copies-clean', 'copies-clean']]) {
    assert.ok(app.includes(`if (action === '${action}') { settingsReviewOpen('${id}', control); return; }`), action);
  }
  assert.doesNotMatch(app, /settingsSend\('(share\.set|workflow\.set|copies\.clean)'/, 'these actions are sent from the review only');
  assert.ok(app.includes("if (event.key === 'Escape' && event.target.closest('.settings-review')) { event.preventDefault(); settingsReviewClose(); return; }"));
  const css = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.css'), 'utf8');
  assert.match(css, /\.settings \.settings-review\{/);
});

test('General phone messages belong in Chat, not Home Messages', () => {
  const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/general-chat.json'), 'utf8'));
  const c = context([], {state:fixture});
  const home = JSON.stringify(c.home());
  assert.doesNotMatch(home, /What is still open this week|Make a ticket|home-message/);
  assert.equal(fixture.chat.messages[0].via, 'phone');
});


test('settings: the folder is shown plainly with Copy path and the quiet full path, no Details', () => {
  const c = context([], {snapshot:false, addons:() => []});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  const long = '/Users/someone/Documents/Projects/2026/customer-work/team-shared/pilatus-workspace';
  for (const folder of ['/Users/me/pilatus', long]) {
    c.state.settings = {folder, addons:[]};
    const page = c.settingsPage();
    const ws = nodes(page, n => n.attrs?.['data-key'] === 'settings-workspace')[0];
    const row = nodes(ws, n => n.attrs?.['data-key'] === 'settings-folder')[0];
    assert.ok(row);
    assert.equal(nodes(ws, n => n.tag === 'details').length, 0);
    assert.equal(row.attrs.title, folder);
    assert.equal(nodes(ws, n => n.attrs?.['data-key'] === 'settings-folder-name')[0].textContent, folder.split('/').pop());
    assert.equal(nodes(ws, n => n.attrs?.['data-key'] === 'settings-copy-path')[0].attrs['data-copy'], folder);
    if (folder === long) {
      assert.ok(row.textContent.length <= 48 && row.textContent.includes('…'));
      assert.ok(row.textContent.startsWith('/Users/someone') && row.textContent.endsWith('pilatus-workspace'));
    } else assert.equal(row.textContent, folder);
    assert.equal(nodes(page, n => n.tag === 'details').length, 0, 'Settings has no Details toggles');
  }
});

// Dash 02/21/43/44: no status chips on Home rows, no empty Working now, See all tickets right after.
// ORCH-58 (owner, 16 Nov): the ticket number goes before every title; a result row is titled with the ticket.
test('home rows: number before the title, no chip, no empty Working now, See all tickets (N), finish time instead of Done', () => {
  const today = new Date(); today.setHours(9, 5);
  const items = [{id:'a', key:'PIL-54', title:'Pay invoice', status:'review'}, {id:'d', key:'PIL-55', title:'Book room', status:'done', done_at:today.toISOString()}];
  const home = context(items, {parse:v => v ? new Date(v) : null, time:d => d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0')}).home(), text = JSON.stringify(home);
  assert.match(text, /\{"tag":"h3","attrs":\{\},"children":\[\{"tag":"span","attrs":\{"className":"key"\},"children":\["PIL-54"\]\}," ","Pay invoice"\]\},\{"tag":"p","attrs":\{"className":"meta"\},"children":\["Check the result"\]\}/, 'result row: number + ticket name, Check the result as the small line');
  assert.match(text, /"children":\["PIL-55"\]\}," ","Book room"/, 'finished row shows the number');
  assert.doesNotMatch(text, /"(review|done)"\]/);
  assert.doesNotMatch(text, /Working now|No tickets are being worked on/);
  assert.match(text, /Finished 9:05/);
  const left = nodes(home, n => n.attrs?.['data-key'] === 'left')[0];
  assert.ok(left); assert.match(text, /All 2 tickets →/); assert.match(text, /1 result to check/);
  assert.match(text, /Needs you · 1/); assert.match(text, /Check result/); assert.doesNotMatch(text, /Details|Technical details/);
});
// One list: a result to check is one row with ONE button; same-name results are one row ("3 versions"), newest first.
test('home results: one row and one button each, same-name stacked, newest first', () => {
  const r = (id, title, at) => ({id, title, status:'review', updated_at:'2026-11-0' + at + 'T10:00:00Z'});
  const items = [r('v1', 'Report', 1), r('v2', 'Report', 2), r('v3', 'report', 9), r('x', 'Logo', 4), r('y', 'Menu', 5), r('z', 'Flyer', 6)];
  const c = context(items, {snapshot:false, locks:new Set(), button:(label, cls, click) => ({tag:'button', attrs:{}, children:[label], click})});
  const home = c.home(), section = nodes(home, n => n.attrs?.['data-key'] === 'needs-you')[0], text = JSON.stringify(section);
  const rows = nodes(section, n => /^check-/.test(n.attrs?.['data-key'] || ''));
  assert.equal(rows.length, 4, 'every result is in the one list, none folded away');
  for (const row of rows) {
    assert.equal(nodes(row, n => n.tag === 'a' || n.tag === 'button').length, 1, 'ONE button per row');
    assert.match(JSON.stringify(row), /Check result/);
  }
  assert.doesNotMatch(text, /Show all|Mark older as done|Open result|Send back/);
  assert.match(text, /3 versions/); assert.match(text, /Needs you · 6/); // six results, one row stacks three
  assert.deepEqual(rows.map(r => nodes(r, n => n.tag === 'a')[0].attrs.href), ['#ticket/v3', '#ticket/z', '#ticket/y', '#ticket/x']);
});
test('home results: untitled results do not stack', () => {
  const items = [{id:'u1', title:'', status:'review'}, {id:'u2', title:'[E2E]', status:'review'}, {id:'u3', status:'review'}];
  const c = context(items, {snapshot:false, locks:new Set()});
  c.clean = v => String(v || '').replace(/^\[E2E\]$/, '');
  const section = nodes(c.home(), n => n.attrs?.['data-key'] === 'needs-you')[0];
  assert.equal(nodes(section, n => /^check-/.test(n.attrs?.['data-key'] || '')).length, 3);
  assert.doesNotMatch(JSON.stringify(section), /versions/);
});
// Dash 12/14: the fold shows the oldest question with its answers, then "N more questions"; identical questions stack.
test('home needs: fold shows the oldest card with answers; identical questions are answered once', async () => {
  const items = ['a', 'b', 'c', 'd', 'e'].map(id => ({id, title:'T ' + id, status:'waiting', questions:[{id:id + '1', text:id === 'd' ? 'Other?' : id === 'e' ? 'Else?' : 'Tuesday or Friday?'}]}));
  const needs = items.map((t, i) => ({id:t.id + '1', ticket:t.id, since:'2026-11-0' + (i + 1) + 'T00:00:00Z', answer:{question:t.id + '1', digest:'x', options:['Tuesday', 'Friday']}}));
  const sent = [], toasts = [];
  const button = (label, cls, click) => ({tag:'button', attrs:{}, children:[label], click, dataset:{}});
  const c = context(items, {snapshot:false, document:{getElementById:() => null}, needsList:() => needs, button, locks:new Set(), render(){}, act:async (op, args) => { sent.push(args.ticket); return {ok:true}; }});
  c.window.orch = {toast:t => toasts.push(t)}; c.setTimeout = setTimeout; c.clearTimeout = clearTimeout; vm.runInContext('ANSWER_UNDO_MS = 5', c);
  const home = c.home(), text = JSON.stringify(home);
  assert.match(text, /Asked on 3 tickets – answer once/);
  assert.doesNotMatch(text, /more question/); // no fold: the first question is the full card, d and e are one row each
  for (const id of ['d1', 'e1']) {
    const row = nodes(home, n => n.attrs?.['data-key'] === 'need-' + id)[0];
    assert.equal(nodes(row, n => n.tag === 'button').length, 1); assert.match(JSON.stringify(row), /Answer/);
  }
  const cards = nodes(home, n => n.attrs?.className === 'card-row home-need');
  assert.equal(cards.length, 1);
  const host = {querySelectorAll:() => [], classList:{add(){}}};
  await nodes(cards[0], n => n.tag === 'button')[0].onclick({currentTarget:{closest:() => host}});
  assert.deepEqual(sent, [], 'nothing is sent inside the Undo window');
  await new Promise(r => setTimeout(r, 60));
  assert.deepEqual(sent, ['a', 'b', 'c']); assert.deepEqual(toasts, ['Answered · 3 tickets']);
});
const sameNeeds = (n, act) => {
  const items = Array.from({length:n}, (_, i) => ({id:'t' + i, title:'T' + i, status:'waiting', questions:[{id:'q' + i, text:'Tuesday or Friday?'}]}));
  const needs = items.map((t, i) => ({id:'q' + i, ticket:t.id, since:'2026-11-0' + (i + 1) + 'T00:00:00Z', answer:{question:'q' + i, digest:'x', options:['Tuesday', 'Friday']}}));
  const toasts = [], button = (label, cls, click) => ({tag:'button', attrs:{}, children:[label], click, dataset:{}});
  const c = context(items, {snapshot:false, document:{getElementById:() => null}, needsList:() => needs, button, locks:new Set(), render(){}, act});
  c.window.orch = {toast:(t, kind) => toasts.push([t, kind])}; c.setTimeout = setTimeout; c.clearTimeout = clearTimeout; vm.runInContext('ANSWER_UNDO_MS = 5', c);
  return {c, toasts};
};
test('home needs: three identical questions are one row, not folded', () => {
  const {c} = sameNeeds(3, async () => ({ok:true}));
  const home = c.home(), text = JSON.stringify(home);
  assert.match(text, /Asked on 3 tickets – answer once/);
  assert.doesNotMatch(text, /more question/); assert.doesNotMatch(text, /needs-hide/);
  assert.equal(nodes(home, n => n.attrs?.className === 'card-row home-need').length, 1);
});
test('needs count: open questions + results; notices, bring-back rows and rows without a ticket question are not counted', () => {
  const q = id => ({id, source:'core', kind:'question', ticket:'t' + id, answer:{question:'q1', options:['A']}});
  const sync = id => ({id:'sync:deleted:' + id, source:'sync', kind:'sync:deleted', ticket:'s' + id, tone:'needs-you', answer:{question:'q9', options:['Leave deleted', 'OK']}, actions:[{label:'Leave deleted', verb:'x', sign:true}, {label:'OK', verb:'restored'}]});
  const warn = {id:'sync:unapplied:z', source:'sync', kind:'sync:unapplied', ticket:null, tone:'warn'};
  const back = {id:'core:bring-back:t1', source:'copies', kind:'copies:bring-back', ticket:'t1', tone:'needs-you'};
  const rows = [q('a'), q('b'), q('c'), sync('1'), sync('2'), warn, back];
  assert.equal(helpers.isNotice(sync('1')), true); assert.equal(helpers.isNotice(warn), true);
  assert.equal(helpers.isNotice(q('a')), false); assert.equal(helpers.isBringBack(back), true);
  assert.equal(helpers.needsYouCount(rows, 0), 3);
  assert.equal(helpers.needsYouCount(rows, 2), 5);
  assert.equal(helpers.needsYouCount(rows, [1, 2]), 5, 'lists count by length');
  assert.equal(helpers.needsYouCount([q('a'), {...q('a'), id:'other'}]), 1, 'the same question of a ticket counts once');
});
test('home: notices fold into one quiet line, are not counted, and Show lists them', () => {
  const items = [{id:'a', title:'T a', status:'waiting', questions:[{id:'q1', text:'Which?'}]}];
  const needs = [{id:'a1', source:'core', kind:'question', ticket:'a', since:'2026-11-01T00:00:00Z', answer:{question:'q1', digest:'x', options:['One', 'Two']}},
    ...[1, 2, 3].map(n => ({id:'sync:deleted:' + n, source:'sync', kind:'sync:deleted', ticket:null, tone:'needs-you', text:'A ticket file is missing. Restored it.', answer:{question:'q9', options:['OK']}, actions:[{label:'OK', verb:'restored'}]}))];
  const c = context(items, {needsList:() => needs, snapshot:false, button:(label, cls, click) => ({tag:'button', attrs:{className:cls}, children:[label], click}), addons:() => [{name:'sync', dashboard:{label:'Sync'}}], addonLabel:a => a.dashboard.label});
  const text = JSON.stringify(c.home());
  assert.equal(c.needsToday().count, 1);
  assert.match(text, /1 thing needs you/); assert.match(text, /3 sync notes, nothing to do/); assert.doesNotMatch(text, /Restored it/);
});
test('home (read-only copy, no run data): Working now and Finished are side cards; an empty Finished says what was last', () => {
  const t = new Date(); t.setDate(t.getDate() - 1);
  const items = [{id:'w', title:'Plan', status:'active', checklist:[{id:'c1', text:'Send a test mail'}]}, {id:'d', title:'Old sign', status:'done', done_at:t.toISOString()}];
  const home = context(items, {parse:v => v ? new Date(v) : null, state:{runs:{}, settings:{}}}).home(), text = JSON.stringify(home);
  const right = nodes(home, n => n.attrs?.['data-key'] === 'right')[0];
  assert.match(JSON.stringify(right), /Working now/); assert.match(JSON.stringify(right), /Send a test mail/);
  assert.doesNotMatch(JSON.stringify(right), /steps|segments|progressbar/);
  assert.match(text, /Nothing finished today\. Last: “Old sign”/);
});
test('home: Finished shows the 5 newest finished today and one link to all of them (report r-1116-2215-ws)', () => {
  const day = new Date(); day.setHours(12, 0, 0, 0);
  const at = m => new Date(day.getTime() - m * 60000).toISOString();
  const done = Array.from({length:12}, (_, i) => ({id:'d' + i, title:'Done ' + i, status:'done', done_at:at(i * 5)}));
  const items = [{id:'w', title:'Plan', status:'active'}, ...done.slice().reverse()];
  const c = context(items, {parse:v => v ? new Date(v) : null, now:() => day, time:d => String(d), state:{runs:{}, settings:{}}});
  const fin = nodes(c.home(), n => n.tag === 'section' && n.children?.[0] === 'Finished')[0];
  const rows = nodes(fin, n => String(n.attrs?.['data-key'] || '').startsWith('ticket-')).map(n => n.attrs['data-key']);
  assert.deepEqual(rows, ['ticket-d0', 'ticket-d1', 'ticket-d2', 'ticket-d3', 'ticket-d4'], 'newest first, five rows');
  const row = nodes(fin, n => n.attrs?.['data-key'] === 'ticket-d0')[0];
  assert.equal(row.children[1].attrs.className, 'meta', 'the time is a line under the title, not inside the title row');
  assert.doesNotMatch(JSON.stringify(row.children[0]), /Finished/);
  const link = nodes(fin, n => n.tag === 'a' && n.attrs?.href === '#tickets?view=done-today')[0];
  assert.ok(link, 'link to the finished-today view'); assert.match(JSON.stringify(link), /All finished today \(12\)/);
  const few = context(items.slice(0, 4), {parse:v => v ? new Date(v) : null, now:() => day, time:d => String(d), state:{runs:{}, settings:{}}});
  assert.doesNotMatch(JSON.stringify(few.home()), /All finished today/, 'no link when all fit');
});
test('home needs: a failed answer on stacked questions says how many were answered', async () => {
  let n = 0;
  const {c, toasts} = sameNeeds(3, async () => ++n === 2 ? {ok:false, status:409, text:'Nope'} : {ok:true});
  c.window.DashHelpers.scrubText = t => t;
  const card = nodes(c.home(), n => n.attrs?.className === 'card-row home-need')[0];
  await nodes(card, n => n.tag === 'button')[0].onclick({currentTarget:{closest:() => ({querySelectorAll:() => [], classList:{add(){}}})}});
  await new Promise(r => setTimeout(r, 60));
  assert.deepEqual(toasts, [['Answered · 3 tickets', 'ok'], ['Answered on 2 of 3 tickets. Nope', 'error']]);
});

// Dash 01: clean() drops leading test tags and trailing machine stamps, keeps a title that is only a tag.
test('clean strips leading [X] tags and trailing number/time stamps', () => {
  const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
  const c = vm.createContext({});
  vm.runInContext(app.slice(app.indexOf('let wsNames'), app.indexOf('const name =')) + ';this.clean = clean;', c);
  assert.equal(c.clean('[E2E] [smoke] Pay the invoice [1731400000]'), 'Pay the invoice');
  assert.equal(c.clean('Water plants [2026-11-12T10:00:00Z]'), 'Water plants');
  assert.equal(c.clean('Order [3] chairs'), 'Order [3] chairs');
  assert.equal(c.clean('[Draft]'), '[Draft]');
});
test('titleTag: the hidden tags show muted only when two visible tickets share a base title', () => {
  const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
  const h = (tag, attrs, ...children) => ({tag, attrs, children});
  const c = vm.createContext({h, tickets:() => [], array:v => v || []});
  vm.runInContext(app.slice(app.indexOf('let wsNames'), app.indexOf('const name =')) + ';this.titleTag = titleTag; this.hiddenTags = hiddenTags;', c);
  assert.equal(c.hiddenTags('[R] Pay the invoice [0722]'), '[R] [0722]');
  const a = {id:'a', title:'[R] Pay the invoice [0722]'}, b = {id:'b', title:'[R] Pay the invoice [0811]'}, d = {id:'d', title:'Water plants [0722]'};
  assert.equal(c.titleTag(d, [a, b, d]), null);
  assert.equal(c.titleTag(a, [a]), null);
  assert.equal(c.titleTag(a, [a, b]).children[0], ' [R] [0722]');
  assert.equal(c.titleTag(b, [a, b]).children[0], ' [R] [0811]');
});
// Dash 51/28/31: footer line only when the connection is lost; the phone switch hides while on; Ask the helper.
test('shell: quiet footer, one phone control while on, Ask the helper', () => {
  const on = {settings:{addons:[{name:'relay', active:true, detail:{connected:true}}]}};
  assert.equal(helpers.footerState(on, false), '');
  assert.equal(helpers.footerState({settings:{addons:[{name:'relay', active:true, detail:{connected:false}}]}}, false), 'Not connected');
  assert.equal(helpers.footerState({}, false), '');
  const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/' + f), 'utf8');
  assert.match(web('style.css'), /\.side-foot:has\(#workspace-mode:empty\)\{display:none\}/);
  assert.doesNotMatch(web('style.css'), /body\.mobile-mode-on \.sidebar>\.mm-toggle\{display:none\}/, 'the sidebar switch stays while on; the chip is in the top bar');
  assert.match(web('index.html'), />Ask the helper<\/button>/); assert.doesNotMatch(web('index.html') + web('app.js'), /Open helper/);
  assert.doesNotMatch(web('app.js'), /tk\?\.key/); // no ticket key in the breadcrumb
});
test('ticket saved views filter by status and the board shows Changes to add', () => {
  const items = [{id:'w',title:'W',status:'active',owner:'anna'}, {id:'r',title:'R',status:'review',owner:'ben'},
    {id:'d',title:'D',status:'done',owner:'anna',done_at:new Date().toISOString(),bring_back:{state:'waiting'}},
    {id:'o',title:'O',status:'done',owner:'ben',done_at:'2000-01-01T00:00:00Z'}];
  const c = context(items);
  const ids = (view, person = '') => c.filterTickets(items, '', false, '', person, view).map(t => t.id).join();
  assert.equal(ids('working'), 'w');
  assert.equal(ids('needs-you'), 'r,d');
  assert.equal(ids('done-week'), 'd');
  assert.equal(ids('done-today'), 'd');
  assert.equal(ids('', 'ben'), 'r,o');
  assert.match(JSON.stringify(c.boardCard(items[2])), /Changes to add/);
  assert.doesNotMatch(JSON.stringify(c.boardCard(items[3])), /Changes to add/);
});
test('home: headline and badge are one number (questions + results); changes to add are listed, not counted', () => {
  const items = [{id:'a', title:'T a', status:'active'}, {id:'r1', title:'R one', status:'review'}, {id:'r2', title:'R two', status:'review'},
    {id:'c1', title:'C one', status:'done', bring_back:{state:'waiting'}}];
  const needs = [{id:'a1', ticket:'a', title:'Q?', answer:{question:'a1'}}];
  const c = context(items, {needsList:() => needs, button:label => ({tag:'button', children:[label]})});
  const text = JSON.stringify(c.home());
  assert.equal(c.needsToday().count, 3);
  assert.match(text, /3 things need you/);
  assert.match(text, /1 question · 2 results to check · 1 change to add/);
});
test('toasts: successes leave after 5 s even under the pointer, sit bottom-right and do not centre over the page', () => {
  for (const dir of ['../../../workspace/src/orch_ui/static']) {
    const js = fs.readFileSync(path.join(__dirname, dir, 'components.js'), 'utf8'), css = fs.readFileSync(path.join(__dirname, dir, 'interaction.css'), 'utf8');
    assert.doesNotMatch(js, /if\(box\.matches\(':hover'\)\|\|/);
    assert.match(js, /undo&&box\.matches\(':hover'\)/);
    assert.match(css, /\.ui-toasts\{[^}]*right:24px/);
    assert.doesNotMatch(css, /\.ui-toasts\{[^}]*translateX\(-50%\)/);
  }
});
test('home: an add-on row without a ticket carries the add-on display name, not its id', () => {
  const needs = [{id:'n1', source:'sync', title:'sync', text:'Sync stopped', answer:{options:[]}}];
  const c = context([], {needsList:() => needs, button:label => ({tag:'button', children:[label]}), addons:() => [{name:'sync', dashboard:{label:'Sync'}}], addonLabel:a => a.dashboard.label});
  const text = JSON.stringify(c.home());
  assert.doesNotMatch(text, /"sync"/);
  assert.match(text, /Sync/);
  assert.doesNotMatch(text, /(Helper|Claude) asked/);
});
test('Watch live and Stop exist only while a helper is at work (not on a ticket waiting for its check)', () => {
  assert.equal(helpers.helperAlive({status:'active'}, {running:true}), true);
  assert.equal(helpers.helperAlive({status:'review'}, {running:true}), false);
  assert.equal(helpers.helperAlive({status:'done'}, {running:true}), false);
  assert.equal(helpers.helperAlive({status:'active'}, {running:false}), false);
  assert.equal(helpers.helperAlive({status:'active'}, null), false);
  const ticket = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
  // ORCH-70: a running helper has its Watch live in the header and Stop in the ⋯ menu; the helper bar (with its own
  // pair) shows only when the header does not hold them (a question open, a background run)
  assert.equal((ticket.match(/ticketButton\((idle \? 'Stop idle helper' : )?'Stop'/g) || []).length, 2);
  assert.match(ticket, /function ticketHelperMenuItems[\s\S]*ticketButton\(idle \? 'Stop idle helper' : 'Stop', 'menu-item'/);
  assert.match(ticket, /function ticketWorkingStrip[\s\S]*'data-key':'watch-live'\}, 'Watch live'/);
  assert.match(ticket, /working && !helperLive \? agentBar\(t\)/);
  assert.doesNotMatch(ticket, /Watch live ↗/);
  assert.doesNotMatch(ticket, /run\?\.running \? ticketButton\('Stop/);
});
test('the Automation page heading is the add-on menu name, not a second name', () => {
  const settings = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  assert.doesNotMatch(settings, /heading\('Schedules'/);
  assert.match(settings, /heading\(addonTitle\(a\), a\?\.dashboard\?\.subtitle \|\| 'Repeat work on a plan you choose\.'/);
});

test('ticket page: brief heading, Repeats in Properties, plain values with a pencil, no Edit text (UX round 5)', () => {
  const ticket = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
  assert.match(ticket, /h\('h2', \{\}, 'What you asked'\)/);
  assert.match(ticket, /field\('Done when', inlineField\(t, 'done_when'\)\), addonPropertyRows\(t\)/);
  assert.match(ticket, /'Set a due date'/);
  assert.match(ticket, /iconEl\('pencil'\)/);
  assert.doesNotMatch(ticket, /'Helper: '/);
  assert.doesNotMatch(ticket, /Works in a separate copy of your project[^\n]*shared-folder/);
  const css = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/style.css'), 'utf8');
  assert.doesNotMatch(css, /\.ticket-details \.ed:after\{content:"Edit"/);
});
test('home: a long add-on question is one short title in its row', () => {
  const long = "Start 'Loyalty card'? ~1 h 30 min · you're needed for ~10 min. Goal: " + 'Regular customers collect stamps. '.repeat(10);
  const needs = [{id:'f1', source:'factory', kind:'factory:start', ticket:'a', title:'Launch a loyalty card', since:'2026-11-01T00:00:00Z', answer:{question:'q1', digest:'x', options:[]}},
    {id:'g1', source:'core', kind:'question', ticket:'b', title:'Plain?', since:'2026-11-02T00:00:00Z', answer:{question:'q1', digest:'x', options:['A', 'B']}}];
  const items = [{id:'a', title:'Launch a loyalty card', status:'waiting', questions:[{id:'q1', text:long}]}, {id:'b', title:'T b', status:'waiting', questions:[{id:'q1', text:'Plain?'}]}];
  const row = nodes(context(items, {needsList:() => needs, snapshot:false, button:label => ({tag:'button', children:[label]})}).home(), n => n.attrs?.['data-key'] === 'need-f1')[0];
  assert.ok(row); assert.match(JSON.stringify(row), /Start 'Loyalty card'\?/); assert.doesNotMatch(JSON.stringify(row), /Regular customers/);
});

test('Settings: "Accept small finished work for me" is one switch that saves at once through reviewer.set (ORCH-77)', async () => {
  const calls = [];
  const c = context([], {snapshot:false, addons:() => [], render:() => {}, document:{querySelector:() => null},
    act:async (op, args) => { calls.push(JSON.stringify([op, args])); return {ok:true}; }});
  c.window.orch = {toast() {}};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  c.state.settings = {reviewer_on:false};
  const text = n => typeof n === 'string' ? n : n.textContent != null ? String(n.textContent) : (n.children || []).map(text).join(' ');
  const card = c.reviewerCard(c.state.settings), sw = nodes(card, n => n.attrs?.role === 'switch')[0];
  assert.equal(sw.attrs['aria-label'], 'Accept small finished work for me'); assert.equal(sw.attrs['aria-checked'], false);
  assert.equal(sw.attrs['data-action'], 'reviewer-set');
  assert.match(text(card), /Merged bug fixes with green checks and no change to looks, words or rules are marked Done for you\. You see them on Review and can send any back\./);
  await c.reviewerSwitch();
  assert.deepEqual(calls, [JSON.stringify(['reviewer.set', {on:true}])]);
  c.state.settings.reviewer_on = true;
  assert.equal(nodes(c.reviewerCard(c.state.settings), n => n.attrs?.role === 'switch')[0].attrs['aria-checked'], true);
  await c.reviewerSwitch();
  assert.equal(calls[1], JSON.stringify(['reviewer.set', {on:false}]));
});

// ORCH-58: the number goes before every title in the list and on the board; a search opens a folded group that holds a hit.
test('tickets list: number before the title, and a search hit is visible without opening its group', () => {
  const items = [{id:'o', key:'ORCH-63', title:'Open one', status:'open'}];
  for (let i = 0; i < 7; i++) items.push({id:'d' + i, key:'ORCH-' + (30 + i), title:'Done ' + i, status:'done'});
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null), addEventListener(){}, dataset:{}, classList:{add(){}}});
  const c = context(items, {h, iconEl:() => null, parentLine:() => null});
  const titles = table => nodes(table, n => n.tag === 'a' && /^#ticket\//.test(n.attrs?.href || '')).map(a => a.children.map(x => typeof x === 'string' ? x : x.children.join('')).join(''));
  let table = c.ticketTable(c.filteredTickets());
  assert.deepEqual(titles(table), ['ORCH-63 Open one'], 'the Done group starts folded (more than 5)');
  assert.equal(nodes(table, n => n.attrs?.className === 'key')[0].children[0], 'ORCH-63');
  assert.deepEqual(titles(c.boardCard(items[0])), ['ORCH-63 Open one'], 'board card shows the number');
  vm.runInContext("ticketSearch = '31'", c);
  table = c.ticketTable(c.filteredTickets());
  assert.deepEqual(titles(table), ['ORCH-31 Done 1'], 'the hit inside the folded Done group shows at once');
  assert.match(JSON.stringify(table), /1 ticket matches “31”/);
  vm.runInContext("ticketSearch = ''", c);
  assert.deepEqual(titles(c.ticketTable(c.filteredTickets())), ['ORCH-63 Open one'], 'clearing the search folds Done again');
});

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
    activeTicket:() => true, ticketAttentionChip:() => null, ...extra});
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
  assert.deepEqual(Array.from(groups, g => g.title), ['Needs you','Working','Not started','Ready for review','Done']);
  assert.deepEqual(Array.from(groups, g => Array.from(g.tickets, t => t.id)), [['waiting','question'],['active'],['ready','open'],['review'],['done']]);
});
test('home renders one need card per ticket with question count and yellow chip', () => {
  const t = {id:'p',title:'Pick a plan',status:'active',questions:[{id:'q1',text:'First?'},{id:'q2',text:'Second?'}]};
  const needs = t.questions.map(q => ({id:q.id,ticket:t.id,title:q.text,answer:{question:q.id}}));
  const c = context([t], {needsList:() => needs});
  const home = c.home(), text = JSON.stringify(home);
  assert.equal(nodes(home, n => n.attrs?.className === 'card-row home-need').length, 1);
  assert.match(text, /2 questions/); assert.match(text, /Needs you \(1\)/); assert.match(text, /2 questions for you/);
  assert.match(text, /First\?/); assert.doesNotMatch(text, /Second\?/);
  assert.equal(nodes(home, n => n.attrs?.className === 'chip attn').length, 1);
  needs.shift();
  assert.match(JSON.stringify(c.home()), /Second\?/);
});

// Real /api/state shape from the test network (sanitized): `children` is a list of ids, `parent` an id.
test('parts on the real /api/state shape: list nests parts under the parent whatever their status', () => {
  const real = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/state-pilatus-parts.json'), 'utf8'));
  const items = real.tickets, [parent] = items.filter(t => t.key === 'PIL-2');
  assert.deepEqual(parent.children, ['t_1wis33', 't_fhm1w4']);
  assert.deepEqual(helpers.childrenOf(items, parent).map(t => t.key).sort(), ['PIL-10', 'PIL-11']);
  assert.equal(helpers.parentOf(items, items.find(t => t.key === 'PIL-10')).key, 'PIL-2');
  const c = context(items, {state:real});
  const groups = c.ticketGroups(c.ticketParents(items));
  const waiting = groups.find(g => g.status === 'waiting'), open = groups.find(g => g.status === 'open');
  assert.equal([...waiting.tickets.map(t => t.key)].sort().join(), 'PIL-10,PIL-11,PIL-2');
  assert.ok(!open.tickets.some(t => t.key === 'PIL-10'));
  const rows = helpers.treeRows(waiting.tickets);
  assert.equal(rows.find(r => r.ticket.key === 'PIL-2').children, 2);
  assert.equal(rows.filter(r => /PIL-1[01]/.test(r.ticket.key)).map(r => r.depth).join(), '1,1');
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
     'This workspace asks to run a command', 'Agent: mine\nAdapter: generic\nCommand: run <x>\nLive command: live x\nPrompt: stdin', 'Allow on this computer']);
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
});

test('Separate copies card: three choices, the saved one is selected, setup and cap are controls', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const start = src.indexOf('const COPY_CHOICES'), end = src.indexOf('function settingsPage');
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, array:x => Array.isArray(x) ? x : [], snapshot:false, settingsBusy:new Set(), settingsText:(tag, a, t) => h(tag, a, t)});
  vm.runInContext(src.slice(start, end), c);
  const card = vm.runInContext('copiesCard', c)({copies:'always', copies_max:5, copy_setup:'npm ci'});
  const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
  const choices = all(card, n => n.attrs?.['data-action'] === 'copies-mode');
  assert.deepEqual(choices.map(n => n.attrs['data-mode']), ['off', 'together', 'always']);
  assert.deepEqual(choices.map(n => n.attrs['aria-checked']), [false, false, true]);
  assert.equal(all(card, n => n.attrs?.['data-key'] === 'settings-copy-setup')[0].attrs.value, 'npm ci');
  assert.equal(all(card, n => n.tag === 'select')[0].value, '5');
  const dflt = vm.runInContext('copiesCard', c)({});
  assert.deepEqual(all(dflt, n => n.attrs?.['data-action'] === 'copies-mode').map(n => n.attrs['aria-checked']), [false, true, false]);
});

test('Copies on this computer line: count, size, "..." while counting, Clean up now button', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const start = src.indexOf('const COPY_CHOICES'), end = src.indexOf('function settingsPage');
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  const c = vm.createContext({h, array:x => Array.isArray(x) ? x : [], snapshot:false, settingsBusy:new Set(), settingsText:(tag, a, t) => h(tag, a, t)});
  vm.runInContext(src.slice(start, end), c);
  const text = d => vm.runInContext('copiesDiskText', c)(d);
  assert.match(text(null), /^…/);
  assert.equal(text({copies:2, bytes:1.4e9, partial:false}), '2 copies · 1.4 GB · removed by themselves when a ticket is done');
  assert.match(text({copies:1, bytes:5e6, partial:true}), /^1 copy · more than 5 MB/);
  assert.match(text({copies:1, bytes:0, orphaned:[{ws8:'aaaaaaaa', copies:2}]}), /2 copies from a moved or deleted project/);
  assert.match(text({copies:1, bytes:0, changed:1}), /1 removed copy changed after being saved/);
  assert.match(text({copies:1, bytes:0, stuck:[{ticket:'t_abc123'}]}), /git was interrupted/);
  const card = vm.runInContext('copiesCard', c)({copies_disk:{copies:0, bytes:0, orphaned:[{ws8:'aaaaaaaa', copies:2}], stuck:[{ticket:'t_abc123'}]}});
  const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
  const btn = all(card, n => n.attrs?.['data-action'] === 'copies-clean')[0];
  assert.equal(btn.children[0], 'Clean up now');
  assert.equal(all(card, n => n.attrs?.['data-action'] === 'copies-orphaned').length, 1);
  assert.equal(all(card, n => n.attrs?.['data-action'] === 'copies-retry').length, 1);
  assert.match(JSON.stringify(card), /files git ignores/);
});

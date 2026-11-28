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
test('ORCH-576: a parent tile shows its parts as a bar, every part says Part of: <title>; keys work, summaries and arrays are ignored', () => {
  const items = [{id:'p',key:'PIL-2',title:'Parent',status:'waiting',children:{total:3,closed:1,open:2}},
    {id:'a',key:'PIL-10',title:'First',parent:'p',status:'open'}, {id:'b',key:'PIL-11',title:'Second',parent:'PIL-2',status:'open'},
    {id:'c',key:'PIL-12',title:'Third',parent:'p',status:'waiting'}];
  for (const useHelpers of [false, true]) {
    const c = context(items);
    if (!useHelpers) c.window = {DashHelpers:{...helpers, childrenOf:undefined, parentOf:undefined}};
    const card = c.boardCard(items[0], 'blocked');
    const bar = nodes(card, n => n.attrs?.className === 'parts-bar')[0];
    assert.ok(bar, 'the parent tile has a parts bar');
    assert.match(bar.attrs.title, /0 of 3 sub-tickets done/);
    assert.equal(nodes(bar, n => n.tag === 'i').length, 3, 'one block per part');
    assert.match(JSON.stringify(c.boardCard(items[1], 'open')), /Part of: Parent/);
    const board = c.board();
    const cards = nodes(board, n => n.tag === 'article');
    assert.equal(cards.length, 4, 'every ticket is its own tile; parts are never nested inside a parent');
    const openRow = nodes(board, n => n.attrs?.['data-status'] === 'open')[0];
    assert.equal(nodes(openRow, n => n.tag === 'article').length, 2);
    assert.equal(nodes(openRow, n => /tile-part-of/.test(n.attrs?.className || '')).length, 2);
    assert.equal(c.boardChildren([{id:'p',children:['a']},{id:'a'}], {id:'p'}).length, 0);
  }
});
test('list groups have owner order and every ticket belongs to exactly one group', () => {
  const items = ['done','review','ready','open','active','waiting'].map(status => ({id:status,status}));
  items.push({id:'question',status:'active',questions:[{text:'Choose?'}]});
  const groups = context(items).ticketGroups(items);
  // ORCH-62: a waiting ticket without an open question is in its own group, not Needs you
  assert.deepEqual(Array.from(groups, g => g.title), ['Needs you','Working','Waiting','To do','Backlog','Review','Done']);
  // ORCH-152: To do (ready) and Backlog (open, where new tickets land) are two groups
  assert.deepEqual(Array.from(groups, g => Array.from(g.tickets, t => t.id)), [['question'],['active'],['waiting'],['ready'],['open'],['review'],['done']]);
});
// O-01 D (28 Nov): no question or result is a row on Home; they are one line that opens Review.
test('home: questions and results are never rows; one line says how many wait in Review', () => {
  const t = {id:'p',title:'Pick a plan',status:'active',questions:[{id:'q1',text:'First?'},{id:'q2',text:'Second?'}]};
  const r = {id:'a', key:'PIL-54', title:'Pay invoice', status:'review'};
  const needs = t.questions.map(q => ({id:q.id,ticket:t.id,title:q.text,answer:{question:q.id}}));
  const c = context([t, r], {needsList:() => needs});
  const home = c.home(), text = JSON.stringify(home);
  assert.equal(nodes(home, n => n.attrs?.['data-need-row']).length, 0);
  assert.match(text, /Things to look at/); assert.doesNotMatch(text, /First\?|Second\?|Pay invoice|Test results|Result to review/);
  const line = nodes(home, n => n.attrs?.['data-key'] === 'review-line')[0];
  assert.match(JSON.stringify(line), /2 questions and 1 result wait in Review/);
  assert.equal(nodes(line, n => n.tag === 'a')[0].attrs.href, '#review');
  assert.equal(nodes(home, n => /chip/.test(n.attrs?.className || '')).length, 0);
  assert.match(text, /Nothing is blocked\./); assert.doesNotMatch(text, /Details|Technical details|Working now/);
});
// ORCH-58 (owner, 16 Nov): the ticket number goes before every title.
test('home rows: a finished row has the number before the title, no chip and its finish time; All N tickets leads on', () => {
  const today = new Date(); today.setHours(9, 5);
  const items = [{id:'a', key:'PIL-54', title:'Pay invoice', status:'active'}, {id:'d', key:'PIL-55', title:'Book room', status:'done', done_at:today.toISOString()}];
  const home = context(items, {parse:v => v ? new Date(v) : null, time:d => d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0')}).home(), text = JSON.stringify(home);
  assert.match(text, /"children":\["PIL-55"\]\}," ","Book room"/, 'finished row shows the number');
  assert.doesNotMatch(text, /"(review|done)"\]/);
  assert.match(text, /"9:05"/); assert.match(text, /All 2 tickets →/);
  assert.match(text, /No result written yet/);
});
test('home: the Needs you heading shows the count (one per open question plus results to check, ORCH-63)', () => {
  const items = ['a', 'b', 'c'].map(id => ({id, title:'T ' + id, status:'active', questions:[{id:id + '1', text:'One?'}, {id:id + '2', text:'Two?'}]}));
  const needs = items.flatMap(t => t.questions.map(q => ({id:q.id, ticket:t.id, title:q.text, answer:{question:q.id}})));
  const text = JSON.stringify(context(items, {needsList:() => needs, button:label => ({tag:'button', children:[label]})}).home());
  assert.match(text, /Things to look at/); assert.doesNotMatch(text, /\d+ things? needs? you/);
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
  assert.match(text, /Things to look at/); assert.doesNotMatch(text, /\d+ things? needs? you/);
  const app = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
  assert.match(app, /const needCount = needsYouTotal\(\)/); assert.doesNotMatch(app, /needsList\(\)\.length/);
});
test('home: a failed start is on the page and in the number, as its row carries (ORCH-1687, was ORCH-63)', () => {
  const items = [{id:'a', title:'T a', status:'active'}, {id:'f', title:'T f', status:'waiting', waiting_on:{start:true, ref:'x'}}];
  const needs = [{id:'a1', ticket:'a', title:'Q?', answer:{question:'a1'}}];
  const c = context(items, {needsList:() => needs, button:label => ({tag:'button', children:[label]})});
  const text = JSON.stringify(c.home());
  assert.match(text, /could not start/);
  // the Review badge said 2 above a Needs you list of 5 (3 failed starts): the number is what the list carries
  assert.equal(c.needsToday().count, 2);
  assert.ok(c.needsYouTicketIds().has('f'), 'the Tickets Needs you view lists it too');
  assert.match(text, /Things to look at/); assert.doesNotMatch(text, /\d+ things? needs? you/);
  const only = JSON.stringify(context([items[1]], {needsList:() => [], button:label => ({tag:'button', children:[label]})}).home());
  assert.match(only, /could not start/); assert.match(only, /Things to look at/); assert.doesNotMatch(only, /All clear/);
});

// Real /api/state shape from the test network (sanitized): `children` is a list of ids, `parent` an id.
test('ORCH-14/576: an epic tile has the Epic tag and "1/2 done"; a ticket inside it says Part of: <epic>', () => {
  const items = [{id:'e',key:'ORCH-20',title:'Dashboard fixes',status:'open',epic:true}, {id:'x',key:'ORCH-21',title:'Fix the header',parent:'e',status:'done'}, {id:'y',key:'ORCH-22',title:'Larger buttons',parent:'e',status:'open'}];
  const c = context(items);
  const epic = c.boardCard(items[0], 'open');
  assert.equal(nodes(epic, n => n.attrs?.className === 'kind-tag')[0].children[0], 'Epic');
  assert.match(JSON.stringify(epic), /1\/2 done/);
  assert.match(JSON.stringify(c.boardCard(items[2], 'open')), /Part of: Dashboard fixes/);
  assert.doesNotMatch(JSON.stringify(c.boardCard(items[2], 'open')), /Sub-ticket of/);
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
  assert.ok(rows.every(r => r.parentMissing), 'each names its parent on a Sub-ticket of line');
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
  const c = vm.createContext({h, snapshot:false, settingsBusy:new Set(), settingsPending:new Map(), settingsSaving:() => null, settingsText:(tag, a, t) => h(tag, a, t)});
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
  assert.ok(src.includes("namedSection('limits', 'Limits', helpersAtOnceCard(settings))]),"), 'sits on the Helper tab, last, under its own heading (W-059)');
});

test('ORCH-227: a Settings choice shows at once with Saving…, a second click while it saves is sent after it', async () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const h = (tag, attrs, ...children) => ({tag, attrs, children:children.flat(Infinity).filter(c => c != null)});
  let renders = 0;
  const c = vm.createContext({h, snapshot:false, render:() => { renders++; }});
  vm.runInContext(src.slice(src.indexOf('const settingsBusy'), src.indexOf('const addonOpen')), c);
  vm.runInContext(src.slice(src.indexOf('const FULL_WARNING'), src.indexOf('// What helpers need')), c);
  vm.runInContext(src.slice(src.indexOf('const LIVE_MAX_CHOICES'), src.indexOf('function shareCard')), c);
  const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
  const checked = card => all(card, n => n.tag === 'input' && n.checked)[0]?.attrs.value;
  const saving = (card, key) => all(card, n => n.attrs?.['data-key'] === 'settings-saving-' + key).length;
  const choose = vm.runInContext('settingsChoose', c), busy = vm.runInContext('settingsBusy', c);
  // the server answers slowly: the clicked choice is drawn at once, with Saving…, never the old one
  const sent = [];
  let finish;
  const send = mode => () => { busy.add('permissions'); sent.push(mode); return new Promise(done => { finish = () => { busy.delete('permissions'); done({ok:true}); }; }); };
  const first = choose('permissions', 'ask', send('ask'));
  const card = vm.runInContext('permissionsCard', c)({permissions:'auto'});
  assert.equal(checked(card), 'ask', 'the click shows at once');
  assert.equal(saving(card, 'permissions'), 1, 'with Saving…');
  assert.equal(all(card, n => n.tag === 'input' && n.attrs.disabled).length, 0, 'a second click is possible');
  // a second click while the first saves is kept and sent after it; the last click wins
  assert.equal(await choose('permissions', 'full', send('full')), null);
  assert.equal(checked(vm.runInContext('permissionsCard', c)({permissions:'auto'})), 'full');
  finish();
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(sent, ['ask', 'full']);
  finish();
  await first;
  const after = vm.runInContext('permissionsCard', c)({permissions:'full'});
  assert.equal(checked(after), 'full'); assert.equal(saving(after, 'permissions'), 0, 'no Saving… once saved');
  // a failed save falls back to what the server says
  const failed = choose('live', 4, () => Promise.resolve({ok:false}));
  await failed;
  assert.equal(all(vm.runInContext('helpersAtOnceCard', c)({live_max:null}), n => n.tag === 'select')[0].value, 'none');
  // Helpers at once shows the picked number at once too
  choose('live', 6, () => new Promise(() => {}));
  const live = vm.runInContext('helpersAtOnceCard', c)({live_max:null});
  assert.equal(all(live, n => n.tag === 'select')[0].value, '6'); assert.equal(saving(live, 'live'), 1);
  assert.ok(renders > 0);
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
  assert.match(text(details), /Needs saved earlier versions in this folder\./);
  assert.match(text(details), /Get each working copy ready with/);
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


// ORCH-1693: no raw path at first level and no fold at all: the folder name, its full path on hover, Copy path.
test('settings: the folder is shown by its name with Copy path, no raw path and no fold', () => {
  const c = context([], {snapshot:false, addons:() => []});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  const long = '/Users/someone/Documents/Projects/2026/customer-work/team-shared/pilatus-workspace';
  for (const folder of ['/Users/me/pilatus', long]) {
    c.state.settings = {folder, addons:[]};
    const page = c.settingsPage();
    const ws = nodes(page, n => n.attrs?.['data-key'] === 'settings-workspace')[0];
    const name = nodes(ws, n => n.attrs?.['data-key'] === 'settings-folder-name')[0];
    assert.equal(name.textContent, folder.split('/').pop());
    assert.equal(name.attrs.title, folder, 'the full path only on hover');
    assert.equal(nodes(ws, n => n.attrs?.['data-key'] === 'settings-copy-path')[0].attrs['data-copy'], folder);
    assert.equal(nodes(ws, n => String(n.textContent ?? '').includes('/Users/')).length, 0, 'no raw path on the page');
    assert.equal(nodes(page, n => n.tag === 'details' || n.tag === 'summary').length, 0, 'Settings has no fold (no More toggle)');
  }
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
  assert.match(text, /Things to look at/); assert.doesNotMatch(text, /\d+ things? needs? you/); assert.match(text, /3 sync notes, nothing to do/); assert.doesNotMatch(text, /Restored it/);
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
// Dash 51/28/31: footer line only when the connection is lost; the phone switch hides while on; Chat.
test('shell: quiet footer, one phone control while on, Chat', () => {
  const on = {settings:{addons:[{name:'relay', active:true, detail:{connected:true}}]}};
  assert.equal(helpers.footerState(on, false), '');
  assert.equal(helpers.footerState({settings:{addons:[{name:'relay', active:true, detail:{connected:false}}]}}, false), 'Not connected');
  assert.equal(helpers.footerState({}, false), '');
  const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/' + f), 'utf8');
  assert.match(web('style.css'), /\.side-foot:has\(#workspace-mode:empty\)\{display:none\}/);
  assert.doesNotMatch(web('style.css'), /body\.mobile-mode-on \.sidebar>\.mm-toggle\{display:none\}/, 'the sidebar switch stays while on; the chip is in the top bar');
  assert.match(web('index.html'), /aria-label="Chat"[^>]*>.*<span class="btn-word-wide">Chat<\/span><\/button>/); assert.doesNotMatch(web('index.html') + web('app.js'), /Open helper/);
  assert.doesNotMatch(web('app.js'), /tk\?\.key/); // no ticket key in the breadcrumb
});
// Report r-1117-1256-ws-2: phone width (390, 320) and 150% zoom. The rules are checked here; e2e/dash_page_health.cjs
// measures the real pages at those sizes.
test('phone and zoom layout: nothing pushes the page sideways or hides a menu item', () => {
  const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/' + f), 'utf8');
  const kit = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/components.css'), 'utf8');
  const source = web('app.js');
  const style = web('style.css'), phone = style.slice(style.indexOf('@media(max-width:720px){\n  .shell{display:flex'));
  const phoneBlock = phone.slice(0, phone.indexOf('\n}'));
  // the ticket's action row may shrink and wrap on a narrow screen (it was flex:none, 490 px wide on a 390 px phone)
  assert.match(web('pages/ticket.css'), /@media\(max-width:1099px\)\{[^\n]*\.ticket-strip \.ticket-strip-actions\{flex:0 1 auto;min-width:0;justify-content:flex-start\}/);
  // the phone top bar wraps instead of overlapping; the phone chip stays in the menu; both helpers' buttons show as icons
  assert.match(phoneBlock, /\.topbar\{flex-wrap:wrap;/);
  assert.match(phoneBlock, /\.topbar>#mm-chip\{display:none\}/);
  assert.doesNotMatch(style, /#open-agent\{display:none\}/);
  assert.match(web('index.html'), /id="report-problem"[^>]*aria-label="Report a problem"/);
  assert.match(web('index.html'), /id="open-agent"[^>]*aria-label="Chat"/);
  // ORCH-2149: on a framed add-on page the top bar keeps the room of the scrollbar the frame shows, so New ticket
  // ends at the same right edge as on Home
  // W-005: the measured room is --frame-gutter on a framed page; the top bar, the Live bar and the right panel all keep it
  assert.match(style, /@media\(min-width:721px\)\{html:has\(iframe\.embed:not\(\.embed-loading\)\)\{--frame-gutter:var\(--scrollbar-w,0px\)\}\}/);
  assert.match(style, /html:has\(iframe\.embed:not\(\.embed-loading\)\) \.topbar\{padding-right:calc\(var\(--page-gutter\) \+ var\(--frame-gutter,0px\)\)\}/);
  const kitWidgets = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8');
  assert.match(kitWidgets, /\.live-dock\{position:fixed;left:var\(--sidebar-width\);right:var\(--frame-gutter,0px\)/);
  assert.match(kitWidgets, /\.live-dock\[data-mode=right\]\{right:calc\(var\(--live-w\) \+ var\(--frame-gutter,0px\)\)\}/);
  assert.match(kitWidgets, /\.live-panel\[data-mode=right\]\{position:fixed;top:var\(--topbar-height\);right:var\(--frame-gutter,0px\)/);
  assert.match(kitWidgets, /body\[data-live-layer=right\] \.shell-body\{padding-right:calc\(var\(--live-padr,0px\) \+ var\(--frame-gutter,0px\)\)\}/);
  assert.match(source, /html\.style\.scrollbarGutter = 'stable';\s+const room = Math\.max\(0, Math\.round\(window\.innerWidth - html\.getBoundingClientRect\(\)\.width\)\);[^]*?setProperty\('--scrollbar-w', room \+ 'px'\)/);
  // ORCH-2176: on the Chat page itself the top bar has no Chat button
  assert.match(source, /getElementById\('open-agent'\)\.hidden = snapshot \|\| r\.kind === 'chat';/);
  // the open phone menu is the whole screen, with room for the bottom bar after its last row; any page change closes it
  assert.match(phoneBlock, /\.shell:has\(>\.sidebar\[data-open=true\]\)>div>\.page\{display:none\}/);
  assert.match(phoneBlock, /\.shell>\.sidebar\[data-open=true\]\{padding-bottom:calc\(var\(--touch\)/);
  assert.match(source, /addEventListener\('hashchange', async (?:\(\)|event) => \{\n  if \(document\.querySelector\('\.sidebar'\)\?\.dataset\.open === 'true'\) setMenu\(false\);/);
  assert.match(source, /closest\?\.\('#tabbar a'\)\) setMenu\(false\)/);
  // the icon rail scrolls its list only when it does not fit above the foot
  assert.match(kit, /\.sidebar:has\(\.nav-label\) \.sidebar-scroll\.cramped\{overflow-x:hidden;overflow-y:auto\}/);
  assert.match(source, /classList\.toggle\('cramped', sideScroll\.scrollHeight > sideScroll\.clientHeight \+ 1\)/);
  // a long menu on a short screen (12 items at 900 px high, report r-1118-0908-t_oxw444-2): soft edges show it scrolls, the foot gets lower rows
  assert.match(kit, /\.sidebar-scroll\{background:linear-gradient\(var\(--sidebar\) 30%,transparent\) top\/100% 24px no-repeat local/);
  assert.match(kit, /@media\(min-width:721px\) and \(max-height:960px\)\{\.side-foot \.nav-item/);
});
test('ticket saved views filter by status and the board shows Changes to add', () => {
  const items = [{id:'w',title:'W',status:'active',owner:'anna'}, {id:'r',title:'R',status:'review',owner:'ben'},
    {id:'d',title:'D',status:'done',owner:'anna',done_at:new Date().toISOString(),bring_back:{state:'waiting'}},
    {id:'o',title:'O',status:'done',owner:'ben',done_at:'2000-01-01T00:00:00Z'},
    {id:'k',title:'K',status:'waiting',owner:'ben',waiting_on:{kind:'time',until:'2030-01-01T09:00:00Z'}}];
  const c = context(items);
  const ids = (view, person = '') => c.filterTickets(items, '', false, '', person, view).map(t => t.id).join();
  assert.equal(ids('working'), 'w');
  assert.equal(ids('needs-you'), 'r', 'ORCH-236: a Done ticket with changes to put live is not counted in Needs you, so it is not in the view either');
  assert.equal(ids('done-week'), 'd');
  assert.equal(ids('done-today'), 'd');
  assert.equal(ids('waiting'), 'k', 'the Waiting chip shows what waits for a time, a ticket or the outside (ORCH-248)');
  assert.equal(ids('', 'ben'), 'r,o,k');
  assert.match(JSON.stringify(c.boardCard(items[2])), /Changes to add/);
  assert.doesNotMatch(JSON.stringify(c.boardCard(items[3])), /Changes to add/);
});
test('home: headline and badge are one number (questions + results); changes to put live are listed, not counted', () => {
  const items = [{id:'a', title:'T a', status:'active'}, {id:'r1', title:'R one', status:'review'}, {id:'r2', title:'R two', status:'review'},
    {id:'c1', title:'C one', status:'done', bring_back:{state:'waiting'}}];
  const needs = [{id:'a1', ticket:'a', title:'Q?', answer:{question:'a1'}}];
  const c = context(items, {needsList:() => needs, button:label => ({tag:'button', children:[label]})});
  const text = JSON.stringify(c.home());
  assert.equal(c.needsToday().count, 3);
  assert.match(text, /Things to look at/); assert.doesNotMatch(text, /\d+ things? needs? you/);
  assert.doesNotMatch(text, /1 question · 2 results to review/);  // ORCH-1616: the date alone under the heading
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
  // ORCH-70: a running helper has its Focus button in the header (ORCH-816: never a link to an old Focus page). ORCH-2155
  // (draft A): Stop takes Continue's place in the bar; the helper bar (with its own pair) shows only when the header does not
  assert.equal((ticket.match(/ticketButton\((idle \? 'Stop idle helper' : )?'Stop'/g) || []).length, 1);
  assert.match(ticket, /function ticketWorkingStrip[\s\S]*?ticketButton\(\[iconEl\('stop'\), idle \? 'Stop idle helper' : 'Stop'\], 'outline sm'[\s\S]*?ticketBar\(t, run, \[stop\], menu, false\)/);
  assert.match(ticket, /function ticketBar[\s\S]*?if \(live\) \{\s*first = typeof liveFocusButton === 'function' \? liveFocusButton\(t, true\)/);
  assert.match(ticket, /working && !helperLive( && [^?\n]+)? \? agentBar\(t\)/);
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
  assert.match(ticket, /h\('h2', \{\}, 'What was asked'\)/);
  assert.doesNotMatch(ticket, /'What you asked'/, 'ORCH-415: one heading for the ask');
  assert.match(ticket, /field\('Done when', doneWhenField\(t\), 'done-when', 'rail-long'\) : null,\s+costValue\(t\) \? field\('Time · cost', costValue\(t\)\) : null, addonPropertyRows\(t\)/);
  assert.match(ticket, /'Set a due date'/);
  assert.match(ticket, /iconEl\('pencil'\)/);
  assert.doesNotMatch(ticket, /'Helper: '/);
  assert.doesNotMatch(ticket, /Works in a separate copy of your project[^\n]*shared-folder/);
  const css = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/style.css'), 'utf8');
  assert.doesNotMatch(css, /\.ticket-details \.ed:after\{content:"Edit"/);
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
  assert.match(text(card), /Merged work where all tests passed and no change to looks, words or rules is marked Done for you\. You see it on Review and can send any back\./);
  await c.reviewerSwitch();
  assert.deepEqual(calls, [JSON.stringify(['reviewer.set', {on:true}])]);
  c.state.settings.reviewer_on = true;
  assert.equal(nodes(c.reviewerCard(c.state.settings), n => n.attrs?.role === 'switch')[0].attrs['aria-checked'], true);
  await c.reviewerSwitch();
  assert.equal(calls[1], JSON.stringify(['reviewer.set', {on:false}]));
});

test('Settings: the kinds accepted for me are checkboxes under the switch; Draft or design is never on (ORCH-645)', async () => {
  const calls = [];
  const c = context([], {snapshot:false, addons:() => [], render:() => {}, document:{querySelector:() => null},
    act:async (op, args) => { calls.push(JSON.stringify([op, args])); return {ok:true}; }});
  c.window.orch = {toast() {}};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  c.state.settings = {reviewer_on:false, reviewer_kinds:['bug', 'small_bug']};
  const boxes = nodes(c.reviewerCard(c.state.settings), n => n.attrs?.type === 'checkbox');
  assert.equal(boxes.length, 6);
  assert.deepEqual(boxes.filter(b => b.attrs.checked != null).map(b => b.attrs['data-kind']), ['bug', 'small_bug']);  // h() ticks any value but null
  const draft = boxes[5]; assert.equal(draft.attrs.disabled, true); assert.equal(draft.attrs.checked, undefined);
  await c.reviewerKindToggle({dataset:{kind:'small_feature'}});
  assert.deepEqual(calls, [JSON.stringify(['reviewer.kinds', {kinds:['bug', 'small_bug', 'small_feature']}])]);
});

test('Settings: "Prepare tickets when I save" is on by default and saves at once through prepare.set (ORCH-741)', async () => {
  const calls = [];
  const c = context([], {snapshot:false, addons:() => [], render:() => {}, document:{querySelector:() => null},
    act:async (op, args) => { calls.push(JSON.stringify([op, args])); return {ok:true}; }});
  c.window.orch = {toast() {}};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  c.state.settings = {prepare_daily_limit:30};  // no value yet = on (the default)
  const text = n => typeof n === 'string' ? n : n.textContent != null ? String(n.textContent) : (n.children || []).map(text).join(' ');
  const card = c.prepareCard(c.state.settings), sw = nodes(card, n => n.attrs?.role === 'switch')[0];
  assert.equal(sw.attrs['aria-label'], 'Prepare tickets when I save'); assert.equal(sw.attrs['aria-checked'], true);
  assert.equal(sw.attrs['data-action'], 'prepare-set');
  assert.match(text(card), /It does no work until you press Start\. At most 30 tickets a day\./);
  await c.prepareSwitch();
  assert.deepEqual(calls, [JSON.stringify(['prepare.set', {on:false}])]);
  c.state.settings.prepare_on_save = false;
  assert.equal(nodes(c.prepareCard(c.state.settings), n => n.attrs?.role === 'switch')[0].attrs['aria-checked'], false);
  await c.prepareSwitch();
  assert.equal(calls[1], JSON.stringify(['prepare.set', {on:true}]));
});

// ORCH-58: the number goes before every title in the list and on the board; a search opens a folded group that holds a hit.
test('Settings: "Put new versions live without my click" is one switch that saves at once through release_merge.set (ORCH-79)', async () => {
  const calls = [];
  const c = context([], {snapshot:false, addons:() => [], render:() => {}, document:{querySelector:() => null},
    act:async (op, args) => { calls.push(JSON.stringify([op, args])); return {ok:true}; }});
  c.window.orch = {toast() {}};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  c.state.settings = {release_merge_on:false};
  const text = n => typeof n === 'string' ? n : n.textContent != null ? String(n.textContent) : (n.children || []).map(text).join(' ');
  const card = c.releaseMergeCard(c.state.settings), sw = nodes(card, n => n.attrs?.role === 'switch')[0];
  assert.equal(sw.attrs['aria-label'], 'Put new versions live without my click'); assert.equal(sw.attrs['aria-checked'], false);
  assert.equal(sw.attrs['data-action'], 'release-merge-set');
  assert.match(text(card), /A release where all tests passed goes live by itself with your GitHub login\. You get the short highlights afterwards\. Off: you decide on the card\./);
  assert.doesNotMatch(text(card), /green|Merge/);
  await c.releaseMergeSwitch();
  assert.deepEqual(calls, [JSON.stringify(['release_merge.set', {on:true}])]);
  c.state.settings.release_merge_on = true;
  assert.equal(nodes(c.releaseMergeCard(c.state.settings), n => n.attrs?.role === 'switch')[0].attrs['aria-checked'], true);
  await c.releaseMergeSwitch();
  assert.equal(calls[1], JSON.stringify(['release_merge.set', {on:false}]));
});

// ORCH-971: a plain folder (no GitHub remote, no pull-requests add-on) does not see the two pull-request switches.
test('Settings: the pull-request switches show only where the workspace has pull requests, or when one is on (ORCH-971)', () => {
  const c = context([], {snapshot:false, addons:() => [], render:() => {}, document:{querySelector:() => null}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  const keys = s => [...c.prSwitchCards(s)].filter(Boolean).map(n => n.attrs['data-key']);
  assert.deepEqual(keys({}), []);
  assert.deepEqual(keys({pull_requests:false, reviewer_on:false, release_merge_on:false}), []);
  assert.deepEqual(keys({pull_requests:true}), ['settings-reviewer', 'settings-release-merge']);
  assert.deepEqual(keys({reviewer_on:true}), ['settings-reviewer']);
  assert.deepEqual(keys({release_merge_on:true}), ['settings-release-merge']);
  // #1228: with the pull-requests add-on on, the release switch is on its page, not in General; off, it stays here
  const pr = [{name:'pull-requests', label:'Pull requests', active:true}];
  assert.deepEqual(keys({pull_requests:true, addons:pr}), ['settings-reviewer']);
  assert.deepEqual(keys({release_merge_on:true, addons:pr}), []);
  assert.deepEqual(keys({pull_requests:true, addons:[{...pr[0], active:false}]}), ['settings-reviewer', 'settings-release-merge']);
});

test('Pull requests add-on page: the release switch, same words and the same release_merge.set (#1228)', async () => {
  const calls = [];
  const c = context([], {snapshot:false, addons:() => [], render:() => {}, document:{querySelector:() => null},
    act:async (op, args) => { calls.push(JSON.stringify([op, args])); return {ok:true}; }});
  c.window.orch = {toast() {}};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  const text = n => typeof n === 'string' ? n : n.textContent != null ? String(n.textContent) : (n.children || []).map(text).join(' ');
  const addon = {name:'pull-requests', label:'Pull requests', description:'Pull requests on GitHub', active:true, removable:true};
  c.state.settings = {release_merge_on:false, pull_requests:true, addons:[addon]};
  const page = c.addonDetailPage(addon);
  const row = nodes(page, n => n.attrs?.['data-key'] === 'addon-detail-release-merge-row')[0];
  assert.ok(row, 'the release row is on the add-on page');
  assert.match(text(row), /Put new versions live without my click/);
  assert.match(text(row), /Off: you decide on the card\./);
  const sw = nodes(row, n => n.attrs?.role === 'switch')[0];
  assert.equal(sw.attrs['data-action'], 'release-merge-set');
  assert.equal(sw.attrs['aria-checked'], false);
  await c.releaseMergeSwitch();
  assert.deepEqual(calls, [JSON.stringify(['release_merge.set', {on:true}])]);
  const none = page => nodes(page, n => n.attrs?.['data-key'] === 'addon-detail-release-merge-row').length;
  assert.equal(none(c.addonDetailPage({name:'publish', label:'Publish', active:true})), 0);
  assert.equal(none(c.addonDetailPage({...addon, active:false})), 0);  // off: the switch is in General
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
test('ORCH-45: a login that stopped working is never "Nothing needs you"; neither it nor one that ends soon counts in the one number (ORCH-288)', () => {
  const stop = {name:'gh', label:'GitHub', kind:'login', state:'renew', chosen:false, stops:[]};
  const soon = {name:'claude', label:'Claude Code', kind:'login', state:'soon', ends_at:'2026-11-19T08:00:00Z', chosen:true, stops:[]};
  const page = logins => { const c = context([], {snapshot:false, state:{logins}, locks:new Set(), button:label => ({tag:'button', children:[label], dataset:{}})}); return {c, text:JSON.stringify(c.home())}; };
  const stopped = page({items:[stop]});
  assert.match(stopped.text, /The GitHub login stopped working/);
  assert.match(stopped.text, /Blocked now/); assert.match(stopped.text, /Things to look at/);  // a row of Blocked now, never a second number
  assert.doesNotMatch(stopped.text, /thing needs you|All clear|Nothing needs you/);
  const runs = page({items:[soon]});
  assert.match(runs.text, /Things to look at/);
  assert.doesNotMatch(runs.text, /thing needs you|Blocked now/);
  assert.match(runs.text, /The Claude Code login ends on/);
  assert.equal(runs.c.needsYouTotal(), 0);  // the menu badges count questions and results only (as drawn)
  assert.match(page({items:[]}).text, /Write your first ticket/);  // no ticket at all: the first step (W-017)
});
test('ORCH-1699: an empty workspace shows one first step on Home and Tickets, nothing else that does not help', () => {
  const c = context([], {snapshot:false, state:{}, locks:new Set(), button:label => ({tag:'button', children:[label], dataset:{}}), URLSearchParams, location:{hash:'#tickets'}, history:{replaceState(){}}});
  const home = c.home(), text = JSON.stringify(home);
  // the one empty page (D4) names what is missing and the first step; never "All clear" or "All 0 tickets"
  const step = nodes(home, n => n.attrs?.['data-key'] === 'empty');
  assert.equal(step.length, 1, 'one first step');
  assert.match(JSON.stringify(step[0]), /Write your first ticket.*Say in one sentence what needs doing/);  // W-017
  assert.doesNotMatch(text, /All 0 tickets|all-tickets|finished-today|All clear/);
  vm.runInContext("ticketSearch = 'x'", c);
  const originalH = c.h;
  c.h = (...args) => ({...originalH(...args), dataset:{}, append(child) { this.children.push(child); }});
  c.newButton = () => c.h('button', {className:'btn primary'}, 'New ticket');
  const list = c.list(), words = JSON.stringify(list);
  assert.equal(nodes(list, n => n.dataset?.key === 'empty').length, 1);
  assert.match(words, /No tickets yet/);
  assert.doesNotMatch(words, /board-tools|How to show tickets|No tickets match|Backlog →/, 'no views, filters or search for zero tickets');
  assert.equal(nodes(list, n => n.tag === 'button' || n.tag === 'a').length, 1, 'one button: New ticket');
  const one = context([{id:'t1', title:'One', status:'open', questions:[]}], {snapshot:false, state:{}, locks:new Set(), button:label => ({tag:'button', children:[label], dataset:{}})});
  assert.match(JSON.stringify(one.home()), /All 1 ticket →/);
  assert.doesNotMatch(JSON.stringify(one.home()), /No tickets yet|Write your first ticket/);
});
test('ORCH-1699: Settings, Add-ons: a plain heading, and every switch says On or Off beside it', () => {
  const c = context([], {snapshot:false, addons:() => []});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8'), c);
  c.state.settings = {addons:[{name:'publish', label:'Shared', active:false}, {name:'relay', label:'Contacts', active:true}]};
  const panel = nodes(c.settingsPage(), n => n.attrs?.id === 'settings-panel-addons')[0];
  assert.deepEqual(nodes(panel, n => n.tag === 'h2').map(n => n.children.join('')), ['Add-ons']);
  assert.doesNotMatch(JSON.stringify(panel), /Installed add-ons/);
  assert.deepEqual(nodes(panel, n => n.attrs?.className === 'switch-text').map(n => n.children.join('')), ['Off', 'On']);
});

test('ORCH-158: the edit button has a name, and a long note opens whole', () => {
  const ticket = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
  // the spoken name starts with the words on screen, then says what the click does (label in name, #2243)
  assert.match(ticket, /node\.append\(el\('span', 'sr-only', ', change ' \+ FIELD_LABEL\[field\]\)\)/);
  assert.doesNotMatch(ticket, /setAttribute\('aria-label', 'Change ' \+ FIELD_LABEL/);
  assert.match(ticket, /Shift\+Enter new line'\s*:\s*'Click to change'/);
  assert.match(ticket, /input\.rows = 3; else/);
  assert.match(ticket, /button\('Show all', 'ghost xs'/);
  assert.match(ticket, /open \? 'Show less' : 'Show all'/);
});

test('ORCH-576: parts are their own tiles in their own rows; the parent tile says how far they are', () => {
  const items = [{id:'p', key:'PIL-2', title:'Parent', status:'open'}, {id:'a', key:'PIL-10', title:'First', parent:'p', status:'open'},
    {id:'c', key:'PIL-12', title:'Third', parent:'p', status:'waiting'}];
  const c = context(items);
  const board = c.board();
  const openRow = nodes(board, n => n.attrs?.['data-status'] === 'open')[0];
  assert.equal(nodes(openRow, n => n.tag === 'article').length, 2, 'parent and First once each, as tiles');
  assert.equal(nodes(openRow, n => n.attrs?.className === 'tile-parts').length, 0, 'the parts list is closed until clicked');
  assert.match(JSON.stringify(openRow), /0\/2/, 'the parent tile still says how far its sub-tickets are');
  assert.ok(nodes(board, n => n.tag === 'article' && n.attrs?.['data-ticket'] === 'c').length === 1, 'Third is its own tile, once');
});
test('ORCH-576: a part folded away in Done is still in its parent tile\'s parts list', () => {
  const done = [1, 2, 3, 4].map(n => ({id:'d' + n, key:'PIL-' + (20 + n), title:'Done ' + n, status:'done'}));
  const items = [{id:'p', key:'PIL-2', title:'Parent', status:'open'}, ...done, {id:'k', key:'PIL-30', title:'Kid', parent:'p', status:'done'}];
  const c = context(items);
  assert.equal(nodes(c.board(), n => n.tag === 'article' && n.attrs?.['data-ticket'] === 'k').length, 0, 'Done starts folded');
  vm.runInContext("boardPartsOpen.add('p')", c);
  const listed = nodes(c.board(), n => n.attrs?.className === 'tile-part');
  assert.equal(listed.length, 1, 'the parent tile lists it when its parts are opened');
  assert.match(JSON.stringify(listed[0]), /Kid/);
});
test('ORCH-240: empty Won\'t do and Superseded lanes take no room on the board', () => {
  const board = context([{id:'a', key:'PIL-1', title:'A', status:'open'}]).board();
  const lanes = nodes(board, n => n.attrs?.['data-status']).map(n => n.attrs['data-status']);
  assert.ok(!lanes.includes('dropped') && !lanes.includes('superseded'));
  assert.ok(lanes.includes('done') && lanes.includes('ready'), 'the other empty lanes stay as drop targets');
});
test('home: a ticket in Review that also asks a question counts once, and the title equals the rows the page counts (ORCH-184)', () => {
  const items = [{id:'a', title:'T a', status:'review'}, {id:'b', title:'T b', status:'review'}, {id:'c', title:'T c', status:'waiting'}];
  const needs = [{id:'a1', ticket:'a', title:'Q?', answer:{question:'a1'}}, {id:'c1', ticket:'c', title:'Q?', answer:{question:'c1'}}];
  const c = context(items, {needsList:() => needs, button:label => ({tag:'button', children:[label]})});
  const today = c.needsToday();
  assert.equal(today.count, today.groups.length + today.review.length, 'one question per ticket plus the results shown as result rows');
  assert.equal(today.count, 4);
  const page = JSON.stringify(c.home());
  assert.match(page, /Things to look at/); assert.doesNotMatch(page, /\d+ things? needs? you/); assert.doesNotMatch(page, /2 questions · 2 results to review/);  // ORCH-1616
});
test('ORCH-705: work that stopped is part of the one number, so Home, the top bar, Menu, the Focus bar and the wall agree', () => {
  const items = [{id:'a', title:'T a', status:'review'}, {id:'d', title:'T d', status:'review'}, {id:'b', title:'T b', status:'active'}, {id:'c', title:'T c', status:'waiting'}];
  const core = (kind, ticket) => ({id:'core:' + kind + ':' + ticket, source:'core', kind, ticket, title:'T ' + ticket, since:'2026-11-19T05:00:00Z', text:'Stopped.'});
  const needs = [{id:'c1', ticket:'c', title:'Q?', answer:{question:'c1'}}, core('helper:failing', 'b'), core('reviewer:unsure', 'a')];
  const c = context(items, {needsList:() => needs, button:label => ({tag:'button', children:[label]})});
  // 1 question + 2 results + 2 stuck rows - 1 result that is the Reviewer's unsure row = 4
  assert.equal(c.needsToday().count, 4);
  assert.equal(c.needsYouTotal(), 4, 'the number the top bar, Menu, Focus bar and wall read');
  const page = JSON.stringify(c.home());
  assert.match(page, /Things to look at/); assert.doesNotMatch(page, /\d+ things? needs? you/); assert.doesNotMatch(page, /2 stuck tickets · 1 question/);  // ORCH-1616
});
test('ORCH-184: one finish time and one wait time per ticket on every page', () => {
  const t = {id:'a', status:'done', done_at:'2026-11-15T10:24:00Z', updated_at:'2026-11-17T09:00:00Z', history:[{at:'2026-11-13T08:00:00Z', text:'Status review -> done'}]};
  assert.equal(helpers.doneAt(t), '2026-11-13T08:00:00Z', 'the history entry wins, like the ticket page');
  assert.equal(helpers.doneAt({done_at:'x', updated_at:'y'}), 'x');
  assert.equal(helpers.doneAt({updated_at:'y'}), 'y');
  const open = {id:'q', updated_at:'2026-11-17T09:00:00Z'};
  assert.equal(helpers.askedAt(open, [{ticket:'q', since:'2026-11-15T09:00:00Z'}, {ticket:'q', since:'2026-11-16T09:00:00Z'}, {ticket:'z', since:'2026-11-01T00:00:00Z'}]), '2026-11-15T09:00:00.000Z');
  assert.equal(helpers.askedAt(open, []), open.updated_at);
  const web = path.join(__dirname, '../src/orch_dashboard/web');
  for (const f of ['pages/home.js', 'pages/tickets.js', 'pages/ticket.js']) assert.doesNotMatch(fs.readFileSync(path.join(web, f), 'utf8'), /t\.done_at \|\|/, f + ' takes the finish time from DashHelpers.doneAt');
});
test('ORCH-184: a line recorded under the computer login names the person, not the login', () => {
  const st = {login:'lume', people:{me:'Severin', people:['Severin']}};
  assert.equal(helpers.personName('human:lume', st), 'Severin');
  assert.equal(helpers.personName('human:Maria', st), 'Maria', 'another person keeps their name');
  assert.equal(helpers.personName('agent:lume', st), 'lume', 'an agent is never renamed');
  assert.equal(helpers.personName('human:lume', {login:'lume'}), 'lume', 'nobody picked a name: nothing to show instead');
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
  assert.match(src, /checked by ' \+ ticketActor\(ev\.by\)/);
});

test('ORCH-158: the shared ticket word for a new ticket is Backlog, not To do', () => {
  const { ticketState } = require('./kit_state.js');
  assert.equal(ticketState({status:'open'}).word, 'Backlog');
  assert.equal(ticketState({status:'ready'}).word, 'To do');
  assert.equal(ticketState({status:'dropped'}).word, "Won't do");
});
test('ORCH-576: add-ons show ONE icon on a tile, the most important fact first, with a count and every fact behind it', () => {
  const items = [{id:'a', key:'PIL-1', title:'Ship it', status:'active',
    refs:[{url:'https://github.com/o/r/pull/12', view:{addon:'pull-requests', status:'checks failed', title:'#12', icon:'github'}}],
    ext:{automation:{recurring:'daily'}, 'pull-requests':{checks:'Failed'}}},
    {id:'b', key:'PIL-2', title:'Plain', status:'open'}];
  const addons = [{name:'automation', ticket_fields:{section:'Repeat', show_on_card:['recurring'], fields:[{key:'recurring', title:'Repeats'}]}},
    {name:'pull-requests', ticket_fields:{section:'Pull requests', show_on_card:['checks'], fields:[{key:'checks', title:'Checks'}]}}];
  const c = context(items, {addons:() => addons, iconEl:name => ({tag:'i', attrs:{}, children:[name]})});
  const facts = c.boardFacts(items[0]);
  assert.equal(facts.map(f => f.tone).join(), 'bad,info', 'failed checks first; the pull-requests field is not repeated beside its own link');
  assert.match(facts[0].text, /#12: checks failed/);
  assert.match(facts[1].text, /Repeats: daily/);
  const icon = nodes(c.boardCard(items[0], 'active'), n => n.attrs?.className === 'tile-icon' && n.attrs['data-tone'])[0];
  assert.equal(icon.attrs['data-tone'], 'bad');
  assert.match(JSON.stringify(icon), /"2"/, 'the icon says how many facts there are');
  assert.equal(nodes(c.boardCard(items[1], 'open'), n => /tile-addon/.test(n.attrs?.className || '')).length, 0, 'no add-on fact, no icon');
});
test('ORCH-415: Working only while a helper runs; In progress with none, so the pill agrees with the No helper line', () => {
  const { ticketState } = require('./kit_state.js');
  assert.equal(ticketState({status:'active'}).word, 'In progress');
  assert.equal(ticketState({status:'active'}, {state:'working'}).word, 'Working');
  assert.equal(helpers.startCostWords({estimate:{cost:1.2}, spend:{cost:0.4}}, 'Opus'), 'On Opus · estimate about $1.20, $0.40 used so far');
  assert.equal(helpers.startCostWords({}, ''), 'A start uses paid helper time');
  assert.equal(helpers.startCostWords({spend:{cost:0}}, 'Sonnet'), 'On Sonnet · a start uses paid helper time');
  // before the first start the server's range is shown; tiny amounts never print $0.00
  assert.equal(helpers.startCostWords({range:'about 20-40 min · $2.00-$4.00'}, 'Opus'), 'On Opus · about 20-40 min · $2.00-$4.00');
  assert.equal(helpers.startCostWords({spend:{cost:0.004}}, 'Opus'), 'On Opus · a start uses paid helper time');
});
test('home: a result the merge queue holds is no row and no count, only one line (ORCH-1741)', () => {
  const items = [{id:'a', title:'Queued fix', status:'review'}, {id:'b', title:'To check', status:'review'}, {id:'c', title:'Asked', status:'review'}];
  const counts = {needs_you:{count:2, questions:1, results:1, tickets:['b', 'c'], queue:['a'],
    items:[{ticket:'b', question:null}, {ticket:'c', question:'q1'}]}};
  const c = context(items, {state:{counts}, button:label => ({tag:'button', children:[label]})});
  const n = c.needsToday();
  assert.deepEqual(n.review.map(t => t.id), ['b'], 'only the ticket whose Check card shows is a result to check');
  assert.deepEqual(n.queued, ['a']);
  assert.equal(n.count, 2);
  const text = JSON.stringify(c.home());
  assert.match(text, /1 in the merge queue, nothing to do/);
  assert.doesNotMatch(text, /Queued fix/);
  assert.equal(c.queueLine([]), null, 'nothing held: no line');
});

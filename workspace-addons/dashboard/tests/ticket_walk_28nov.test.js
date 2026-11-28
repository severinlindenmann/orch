'use strict';
// The owner's decisions of 28 Nov for the ticket page (walk-28nov, batch b303): O-07 compact Overview, O-12 one task
// list, W-028 Open in Live outlined while it is your turn, W-029 Done shows the result first, W-030 which result file
// shows itself, W-033 the computed "Since then" line.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/ticket.js'), 'utf8');
const startSource = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/start.js'), 'utf8');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const kit = {}; vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/date.js'), 'utf8'), vm.createContext({window:kit}));
const h = (tag, attrs = {}, ...children) => { const n = {tag, attrs, children:children.flat(Infinity).filter(x => x != null && x !== false)}; n.append = (...c) => n.children.push(...c.flat(Infinity).filter(x => x != null && x !== false)); n.dataset = {}; n.setAttribute = (k, v) => { n.attrs[k] = v; }; n.addEventListener = () => {}; n.classList = {add(){}, remove(){}}; n.prepend = () => {}; return n; };
const nodes = n => n && typeof n === 'object' ? [n, ...(n.children || []).flatMap(nodes)] : [];
const text = n => !n ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join('');
const keyed = (all, key) => all.find(n => n.attrs?.['data-key'] === key);
const KIND = {json:'code', md:'md', png:'image', csv:'table', txt:'text', pdf:'pdf', html:'page', py:'code'};
const FileViewer = {kindOf:name => KIND[String(name).split('.').pop()] || 'other', word:k => ({code:'Code', md:'Note', image:'Picture', table:'Table'})[k] || 'File', thumb:() => null, stampOf:() => ''};
function ctx(extra = {}) {
  const moves = [];
  const c = {window:{DashHelpers:helpers, orch:{}, FileViewer, UI:{...kit.UI, ...require('./kit_state.js'), statusIcon:name => h('svg', {className:'st ' + name})}}, document:{addEventListener(){}, querySelector:() => null}, addEventListener(){}, h, locks:new Set(),
    array:v => Array.isArray(v) ? v : [], iconEl:n => n, clean:v => String(v ?? ''), name:v => String(v || '').replace(/^(human|agent):/, ''),
    el:(tag, cls, t) => h(tag, {className:cls}, t), fragment:(...children) => h('fragment', {}, children),
    card:(key, title, suffix, children) => h('section', {'data-key':key}, title, suffix, children), emptyRow:t => h('p', {}, t),
    questions:t => (t.questions || []).filter(q => q.answer == null), capitalise:v => v, date:v => String(v || ''), dueText:t => String(t.due || ''), time:v => kit.UI.stamp(v), ticketTabs:new Map(), addons:() => [], tickets:() => [], ticketOf:() => null,
    statusChip:() => h('span', {}, 'x'), chip:t => h('span', {}, t), href:id => '#ticket/' + id, MOVE_CHOICES:helpers.MOVE_CHOICES, moves,
    moveTicket:(...a) => { moves.push(['moveTicket', ...a]); }, moveToLane:(...a) => { moves.push(['moveToLane', ...a]); },
    button:label => h('button', {}, label), loadArtifacts(){}, agentBar:() => null,
    surface:v => v, inlineField:(t, f) => h('span', {}, String(t[f] ?? '')), ticketParts:() => null, addTaskRow:() => null,
    linksCard:() => null, fieldSections:() => null, selectTicketTab(id, tab) { c.ticketTabs.set(id, tab); }, ticketLinks:() => null, addonRows:() => null, mountQuestion(){}, state:{runs:{}}, snapshot:false, repeatsAddon:() => null, act:async () => ({ok:true}),
    route:() => ({kind:'ticket'}), render(){}, URL, fetch:() => new Promise(() => {}), ...extra};
  vm.createContext(c); vm.runInContext(source, c); vm.runInContext(startSource, c); return c;
}
const files = (c, id, list) => vm.runInContext("artifactData.set(" + JSON.stringify(id) + ", {at:Date.now(), data:{files:" + JSON.stringify(list) + "}})", c);
const base = {id:'t_one', title:'Update the opening hours', owner:'human:Anna', created_at:'2026-11-02T08:15:00Z', updated_at:'2026-11-14T10:32:00Z', questions:[]};
const tasks = [{id:'c1', text:'Read the page', done:true, summary:'Read all three pages', evidence:[{type:'note', ref:'ok', at:'2026-11-14T09:00:00Z'}]}, {id:'c2', text:'Change the hours', state:'doing'}, {id:'c3', text:'Old idea', wont_do:true, reason:'Not needed'}];
const panelOf = (tree, id) => nodes(tree).find(n => n.attrs?.id === 'ticket-panel-' + id);

test('O-07: the Overview is compact: In short, result files as rows, one tasks line, the last three events; no write box, no history, no task list', () => {
  const c = ctx();
  files(c, 't_one', [{name:'hours.md', size:900, mtime:'2026-11-14T09:00:00Z'}, {name:'data.json', size:120, mtime:'2026-11-14T09:01:00Z'}]);
  const history = Array.from({length:6}, (_, i) => ({at:'2026-11-14T10:0' + i + ':00Z', by:'human:Anna', text:'Edited note (was: a' + i + ' | now: b' + i + ')'}));
  const tree = c.detail({...base, status:'active', summary:'Two of three pages are changed.', checklist:tasks, history});
  const over = panelOf(tree, 'overview'), all = nodes(over);
  assert.match(text(keyed(all, 'summary')), /^In short\. Two of three pages are changed\.$/);
  const result = keyed(all, 'results');
  assert.equal(nodes(result).filter(n => /(^| )file-row( |$)/.test(n.attrs.className || '')).length, 2, 'while it is worked on: every result file is one row');
  assert.ok(!nodes(result).some(n => /result-frame|ticket-preview/.test(n.attrs.className || '')), 'no preview block while it is worked on');
  assert.equal(text(keyed(all, 'overview-tasks-t_one')), "1 of 2 tasks done1 won't doIn progress: Change the hoursOpen tasks");
  assert.equal(all.filter(n => /(^| )task-row( |$)/.test(n.attrs.className || '')).length, 0, 'O-12: the task list is on the Tasks tab only');
  const latest = keyed(all, 'overview-latest-t_one');
  assert.equal(nodes(latest).filter(n => n.attrs.className === 'history-event').length, 3);
  assert.equal(text(keyed(all, 'overview-all-activity')), 'Show all 6 in Activity');
  assert.ok(!all.some(n => /ticket-talk|history-msg|history-day/.test(n.attrs.className || '')), 'the chat is on Ticket chat, the history on Activity');
  // the routes stay: the same four tabs, each with its panel
  assert.deepEqual(nodes(tree).filter(n => n.attrs?.role === 'tab').map(n => n.attrs['data-tab']), ['overview', 'tasks', 'files', 'activity']);
  assert.equal(nodes(panelOf(tree, 'activity')).filter(n => n.attrs.className === 'ticket-event').length, 6, 'the whole history is on Activity');
});

test('O-07: an empty ticket shows no empty blocks on the Overview', () => {
  const c = ctx();
  const over = nodes(panelOf(c.detail({...base, status:'open', note:'Please update the hours'}), 'overview'));
  assert.ok(!keyed(over, 'results') && !keyed(over, 'overview-tasks-t_one') && !keyed(over, 'overview-latest-t_one') && !keyed(over, 'summary'));
  assert.ok(keyed(over, 'brief'), 'what was asked is still there');
});

test('O-12: the Tasks tab holds the one compact list: a tick, the title, one grey line, the state word, one small more button', () => {
  const c = ctx();
  const tree = c.detail({...base, status:'active', checklist:tasks});
  const list = keyed(nodes(panelOf(tree, 'tasks')), 'tasks');
  assert.equal(list.tag, 'ol');
  assert.match(list.attrs.className, /(^| )task-list( |$)/);
  const rows = list.children;
  assert.deepEqual(rows.map(r => [r.tag, r.attrs.className]), [['li', 'task-row'], ['li', 'task-row'], ['li', 'task-row skipped']]);
  assert.ok(!nodes(list).some(n => /card-row|ticket-task-row/.test(n.attrs.className || '')), 'the roomy row is gone');
  const first = nodes(rows[0]);
  assert.equal(keyed(first, 'task-check-c1').attrs['aria-checked'], 'true');
  assert.match(text(keyed(first, 'task-result-c1')), /^Read all three pages · /, 'one grey line: what came out and when');
  assert.equal(text(first.find(n => /task-word/.test(n.attrs.className || ''))), 'Done');
  const more = keyed(first, 'task-more-c1');
  assert.equal(more.attrs['aria-label'], 'More for Read the page');
  assert.match(more.attrs.className, /ghost icon xs/);
  assert.equal(first.find(n => n.tag === 'form').hidden ?? first.find(n => n.tag === 'form').attrs.hidden, true, 'its choices stay closed until asked for');
});

test('W-030 (B): a text or a picture shows itself; code or data only when it is the only result; the others are rows', () => {
  const c = ctx();
  const shown = list => { files(c, 't_one', list.map(name => ({name, size:10, mtime:'2026-11-14T09:00:00Z'}))); const r = c.resultShown({id:'t_one', status:'review'}); return [r.main?.file.name || null, r.rows.map(x => x.file.name)]; };
  assert.deepEqual(JSON.parse(JSON.stringify(shown(['sources.json']))), ['sources.json', []], 'a data file that is the only result previews');
  assert.deepEqual(JSON.parse(JSON.stringify(shown(['sources.json', 'report.md']))), ['report.md', ['sources.json']], 'the real result previews, the data file is a row');
  assert.deepEqual(JSON.parse(JSON.stringify(shown(['a.json', 'b.py']))), [null, ['a.json', 'b.py']], 'two code or data files: rows only');
  assert.deepEqual(JSON.parse(JSON.stringify(shown(['deck.pptx', 'slide-1.png', 'slide-2.png']))), ['slide-1.png', ['deck.pptx', 'slide-2.png']], 'O-09: the original is listed, first of the rows');
  // on the page: a sole JSON result shows as the preview frame in the Result card; with a note beside it, as a row
  files(c, 't_one', [{name:'sources.json', size:10, mtime:'2026-11-14T09:00:00Z'}]);
  let card = nodes(keyed(nodes(c.detail({...base, status:'review'})), 'review-card-t_one'));
  assert.ok(keyed(card, 'result-frame-sources.json'));
  files(c, 't_one', [{name:'sources.json', size:10, mtime:'2026-11-14T09:00:00Z'}, {name:'report.md', size:10, mtime:'2026-11-14T09:00:00Z'}]);
  card = nodes(keyed(nodes(c.detail({...base, status:'review'})), 'review-card-t_one'));
  assert.ok(keyed(card, 'result-frame-report.md') && !keyed(card, 'result-frame-sources.json'));
  assert.ok(keyed(card, 'file-artifacts-sources.json'), 'the extra file is one row');
});

test('O-07: more than five result rows end in one line that opens the Files tab', () => {
  const c = ctx();
  files(c, 't_one', Array.from({length:8}, (_, i) => ({name:'part-' + i + '.json', size:10, mtime:'2026-11-14T09:00:00Z'})));
  const card = nodes(keyed(nodes(c.detail({...base, status:'active'})), 'results'));
  assert.equal(card.filter(n => /(^| )file-row( |$)/.test(n.attrs.className || '')).length, 5);
  assert.match(text(keyed(card, 'result-more-t_one')), /^\+ 3 more on the Files tab Open files$/);
  assert.equal(keyed(card, 'overview-open-files').attrs['data-tab'], 'files');
});

const live = {liveFocusButton:() => h('button', {}, 'Open'), liveLayerName:() => 'Live', liveFocusOn:() => true};
test('W-028 (A): while it is your turn Open in Live is outlined; the one filled button is Looks good, under the result; the header line jumps there', () => {
  const c = ctx(live);
  c.window.LiveLayer = {open(){}};
  files(c, 't_one', [{name:'report.md', size:10, mtime:'2026-11-14T09:00:00Z'}, {name:'a.json', size:10, mtime:'2026-11-14T09:00:00Z'}]);
  const tree = c.detail({...base, status:'review', summary:'Done.', checklist:[tasks[0]]}), all = nodes(tree);
  assert.match(keyed(all, 'ticket-open-layer').attrs.className, /(^| )outline( |$)/);
  const filled = all.filter(n => (n.tag === 'button' || n.tag === 'a') && /(^| )primary( |$)/.test(n.attrs.className || ''));
  assert.deepEqual(filled.map(text), ['Looks good'], 'exactly one filled button on the page');
  const card = nodes(keyed(all, 'review-card-t_one'));
  const at = k => card.findIndex(k);
  assert.ok(at(n => n.attrs?.['data-key'] === 'result-frame-report.md') < at(n => text(n) === 'Looks good' && n.tag === 'button'), 'the buttons stay under the result');
  const jump = keyed(all, 'ticket-turn-jump');
  assert.equal(jump.tag, 'a');
  assert.equal(text(jump), 'Your turn: look at the result.');
  assert.equal(text(keyed(all, 'ticket-sentence')), 'The helper is finished. Your turn: look at the result.');
  // another state keeps Open in Live filled
  assert.match(keyed(nodes(c.detail({...base, status:'ready', sessions:[{id:'s'}]})), 'ticket-open-layer').attrs.className, /(^| )primary( |$)/);
});

test('W-029: Done from Actions and from the state word shows the result with Looks good first; no extra confirm step', () => {
  const c = ctx();
  const t = {...base, status:'active', sessions:[{id:'s'}], summary:'The hours are changed.', checklist:[tasks[0], tasks[1]]};
  for (const prefix of ['ticket-move-', 'pill-move-']) {
    c.moves.length = 0; vm.runInContext('doneAsked.clear()', c);
    const item = keyed(nodes(c.detail(t)), prefix + 'done');
    assert.ok(item, prefix + 'done is offered');
    item.onclick({});
    assert.deepEqual(c.moves, [], prefix + ': nothing is moved yet');
    assert.equal(c.ticketTabs.get('t_one'), 'overview');
    const all = nodes(c.detail(t)), card = nodes(keyed(all, 'review-card-t_one'));
    assert.match(text(keyed(card, 'ticket-done-ask')), /You chose Done\. Look at the result first/);
    assert.match(text(keyed(card, 'summary')), /The hours are changed/);
    const buttons = card.filter(n => n.tag === 'button' && /^(Looks good|Not yet|Send back)$/.test(text(n)));
    assert.deepEqual(buttons.map(text), ['Looks good', 'Not yet']);
    assert.ok(!buttons[0].disabled, 'a person who chose Done may finish with a task open');
    assert.match(text(keyed(card, 'ticket-review-open-steps')), /1 step is not finished\.$/);
    assert.ok(!nodes(c.detail(t)).some(n => n.tag === 'dialog'), 'no confirm window');
    buttons[0].onclick({});
    assert.deepEqual(JSON.parse(JSON.stringify(c.moves)), [['moveTicket', 't_one', 'done', false, {}]], 'Looks good is the one click that finishes');
    assert.ok(!keyed(nodes(c.detail(t)), 'review-card-t_one'), 'the card does not come back by itself');
  }
  // Not yet keeps the ticket where it is
  keyed(nodes(c.detail(t)), 'ticket-move-done').onclick({});
  nodes(c.detail(t)).find(n => n.tag === 'button' && text(n) === 'Not yet').onclick({});
  assert.ok(!keyed(nodes(c.detail(t)), 'review-card-t_one'));
});

test('W-029: in Review the card is there already; with "I review the result" off, or with nothing to look at, Done moves at once', () => {
  const c = ctx();
  keyed(nodes(c.detail({...base, status:'review', summary:'x'})), 'ticket-move-done').onclick({});
  assert.deepEqual(c.moves, [], 'in Review: the result with Looks good, not a silent close');
  keyed(nodes(c.detail({...base, status:'active', summary:'x', human_review:false})), 'ticket-move-done').onclick({});
  assert.deepEqual(JSON.parse(JSON.stringify(c.moves)), [['moveToLane', 't_one', 'done']]);
  c.moves.length = 0;
  keyed(nodes(c.detail({...base, status:'open'})), 'ticket-move-done').onclick({});
  assert.deepEqual(JSON.parse(JSON.stringify(c.moves)), [['moveToLane', 't_one', 'done']], 'no result yet: nothing to show');
  c.moves.length = 0;
  keyed(nodes(c.detail({...base, status:'active', summary:'x'})), 'ticket-move-dropped').onclick({});
  assert.deepEqual(JSON.parse(JSON.stringify(c.moves)), [['moveToLane', 't_one', 'dropped']], 'every other lane moves as before');
});

const pr = (n, status, title = 'Fix the hours') => ({url:'https://github.com/acme/site/pull/' + n, title, status, view:{title, status, icon:'github', label:'GitHub'}});
const refresh = (at, name, from, to, by = 'orch') => ({at, by, text:'pull-requests refresh: ' + name + ' status ' + from + ' -> ' + to});
test('W-033 (A): one computed line under the summary when a linked pull request changed after the helper last touched the ticket', () => {
  const c = ctx();
  const t = {...base, status:'review', summary:'PR #131 is not merged yet.', refs:[pr(131, 'merged')],
    history:[{at:'2026-11-17T09:00:00Z', by:'agent:claude', text:'Status active -> review'}, refresh('2026-11-27T08:00:00Z', 'Fix the hours', 'open', 'merged')]};
  assert.deepEqual(JSON.parse(JSON.stringify(c.sinceThen(t))), [{url:'https://github.com/acme/site/pull/131', number:'131', word:'merged', at:Date.parse('2026-11-27T08:00:00Z')}]);
  const line = c.sinceThenLine(t);
  assert.equal(text(line), 'Since then: pull request 131 merged on ' + kit.UI.stamp('2026-11-27T08:00:00Z', {time:false}) + '.');
  const all = nodes(c.detail(t));
  assert.equal(text(keyed(all, 'summary')), 'In short. PR #131 is not merged yet.', 'the helper\'s summary stays as written');
  assert.ok(keyed(all, 'since-then-t_one'));
  assert.equal(keyed(all, 'status-review-check') != null || /review/.test(JSON.stringify(all.find(n => /^status-review-/.test(n.attrs?.['data-key'] || ''))?.attrs)), true, 'the ticket\'s state does not change');
});

test('W-033: no line without a recorded change; never a guess', () => {
  const c = ctx();
  const helper = {at:'2026-11-17T09:00:00Z', by:'agent:claude', text:'Status active -> review'};
  const none = t => assert.deepEqual(JSON.parse(JSON.stringify(c.sinceThen(t))), []);
  none({...base, summary:'s', refs:[pr(131, 'merged')], history:[helper]});  // merged, but nothing says when: no line
  none({...base, summary:'s', refs:[pr(131, 'merged')], history:[refresh('2026-11-16T08:00:00Z', 'Fix the hours', 'open', 'merged'), helper]});  // before the helper's last line
  none({...base, summary:'s', refs:[pr(131, 'open')], history:[helper, refresh('2026-11-27T08:00:00Z', 'Fix the hours', 'open', 'merged')]});  // the reference says something else now
  none({...base, refs:[pr(131, 'merged')], history:[helper, refresh('2026-11-27T08:00:00Z', 'Fix the hours', 'open', 'merged')]});  // no summary: nothing to go stale
  none({...base, summary:'s', refs:[pr(131, 'merged')], history:[refresh('2026-11-27T08:00:00Z', 'Fix the hours', 'open', 'merged')]});  // no helper line to count from
  none({...base, summary:'s', refs:[pr(131, 'merged', 'One'), pr(132, 'merged', 'Two')], history:[helper, refresh('2026-11-27T08:00:00Z', 'Other name', 'open', 'merged')]});  // cannot be tied to one pull request
  none({...base, summary:'s', refs:[{...pr(131, 'merged'), url:'https://github.com/acme/site/issues/131'}], history:[helper, refresh('2026-11-27T08:00:00Z', 'Fix the hours', 'open', 'merged')]});  // an issue is no pull request
  // a title the same refresh changed still finds its pull request; two pull requests read as one line
  const two = {...base, summary:'s', refs:[pr(131, 'merged', 'New name'), pr(132, 'closed', 'Two')], history:[helper,
    {at:'2026-11-27T08:00:00Z', by:'orch', text:'pull-requests refresh: Old name title Old name -> New name'}, refresh('2026-11-27T08:00:00Z', 'Old name', 'open', 'merged'), refresh('2026-11-28T08:00:00Z', 'Two', 'open', 'closed')]};
  assert.match(text(c.sinceThenLine(two)), /^Since then: pull request 131 merged on .+, pull request 132 closed on .+\.$/);
});

// ---- O-08: what the click-through a-ticket-property-kinds found, as unit checks
test('O-08: a choice whose save failed goes back to what is saved now, not to the value of its first draw', async () => {
  const toasts = [], synced = [];
  let answer = {ok:true};
  const c = ctx({act:async () => answer, changeError:r => r.text});
  c.window.orch.toast = (...a) => toasts.push(a); c.window.UI.select = {sync:() => synced.push(1)};
  const sel = c.priorityField({id:'t_one', priority:'normal'});
  sel.getAttribute = k => sel.attrs[k];
  assert.equal(sel.attrs['data-value'], 'normal');
  sel.value = 'high'; await sel.onchange();
  assert.deepEqual(toasts, []);
  sel.setAttribute('data-value', 'high');  // the redraw after the save says the new value on the kept select
  answer = {ok:false, text:'That could not be saved just now. Try again.'};
  sel.value = 'low'; await sel.onchange();
  assert.equal(sel.value, 'high', 'back to the saved value (before: back to the value of the first draw, "normal")');
  assert.deepEqual(toasts, [['That could not be saved just now. Try again.', 'error']]);
  assert.equal(synced.length, 1, 'the master select is told to show it');
  for (const f of ['kindField', 'partOfField', 'modelField']) assert.match(source, new RegExp('function ' + f + '[\\s\\S]{0,1400}?propChoice\\(select, '), f + ' is the same kind of choice');
});

test('O-08: a row picked from + Add and left empty goes away again and + Add offers it again', () => {
  const c = ctx();
  const t = {...base, status:'open'};
  c.ticketOf = () => t;
  const offered = () => nodes(c.detail(t)).filter(n => /^prop-add-/.test(n.attrs?.['data-key'] || '')).map(n => n.attrs['data-key'].replace(/^prop-add-|-t_one$/g, ''));
  assert.ok(offered().includes('priority') && offered().includes('due'));
  vm.runInContext("propsAdding.set('t_one', new Set(['priority', 'due', 'links']))", c);
  assert.ok(keyed(nodes(c.detail(t)), 'prop-priority-t_one') && !offered().includes('priority'), 'picked: its row shows');
  for (const key of ['priority', 'due', 'links']) vm.runInContext("propDrop('t_one', '" + key + "')", c);
  assert.ok(!keyed(nodes(c.detail(t)), 'prop-priority-t_one') && !keyed(nodes(c.detail(t)), 'links-card'));
  assert.ok(offered().includes('priority') && offered().includes('due') && offered().includes('links'));
  // typed in place: the box closes (saved, cancelled or failed) and the hold ends; a saved value shows by itself
  assert.match(source, /if \(propsAdding\.get\(t\.id\)\?\.has\(field\)\) propDrop\(t\.id, field\); else render\(\);/);
  assert.match(source, /if \(propsAdding\.get\(t\.id\)\?\.has\('due'\)\) propDrop\(t\.id, 'due'\); else render\(\);/);
  assert.match(source, /d\.addEventListener\?\.\('close', \(\) => \{ if \(!referenceRows\(ticketOf\(t\.id\) \|\| t\)\.length\) propDrop\(t\.id, 'links'\); \}/);
});

test('O-08: + Add opens a choice at once; the box of Done when is named "Done when"', () => {
  assert.match(source, /if \(target\?\.tagName === 'SELECT'\) propChoiceOpen\(t, key, target\); else target\?\.click\(\);/);
  assert.match(source, /input\.setAttribute\('aria-label', FIELD_NAME\[field\] \|\| capitalise\(field\)\);/);
  const c = ctx();
  assert.equal(vm.runInContext('FIELD_NAME.done_when', c), 'Done when');
  // opening tries a bounded number of times while the master select wraps the new select, then gives up to plain focus
  let focused = 0, timers = 0;
  c.setTimeout = fn => { timers++; fn(); };
  vm.runInContext('propChoiceOpen', c)({id:'t_one'}, 'kind', {closest:() => null, focus() { focused++; }});
  assert.equal(timers, 10); assert.equal(focused, 1);
});

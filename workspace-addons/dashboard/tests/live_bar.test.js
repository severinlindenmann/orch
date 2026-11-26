// The live bar under every page (draft D, ORCH-337): which session lands in which group, the counts read right, it is
// loaded and served like the other page modules, it names no add-on, and its look lives in the kit.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const bar = require('../src/orch_dashboard/web/pages/livebar.js');

const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const KIT = path.join(__dirname, '../../../workspace/src/orch_ui/static');

const run = state => ({running:true, helper:{state}, claim:{agent:'agent:claude'}});  // for the ticket's session button
const t = (id, key, extra = {}) => ({id, key, title:'Title of ' + key, status:'active', questions:[], ...extra});
const sess = (id, key, status, extra = {}) => ({id, key, title:'Title of ' + key, status, word:status === 'working' ? 'Working' : '', ...extra});

test('sessions by state from the live sessions API; the Helpers menu groups them as Needs you, Working, Quiet (ORCH-2198)', () => {
  const list = [sess('t_a', 'ORCH-1', 'needs-you'), sess('t_b', 'ORCH-2', 'working'), sess('t_c', 'ORCH-3', 'in-line'),
    sess('t_d', 'ORCH-4', 'idle'), sess('t_e', 'ORCH-5', 'working'), sess('t_f', 'ORCH-6', 'closed')];
  const all = bar.liveBarModel(list, ['t_e', 't_a']);
  assert.deepEqual(all.map(o => [o.key, o.s, o.pin]), [['ORCH-1', 'wait', true], ['ORCH-5', 'run', true], ['ORCH-2', 'run', false],
    ['ORCH-3', 'queue', false], ['ORCH-4', 'idle', false]], 'a closed session (ORCH-6) is not in the bar');
  const groups = bar.liveBarGroups(all, 0);
  assert.deepEqual(groups.map(x => [x.head, x.n, x.rows.map(o => o.key)]), [['Needs you', 1, ['ORCH-1']], ['Working', 2, ['ORCH-5', 'ORCH-2']],
    ['Quiet', 2, ['ORCH-3', 'ORCH-4']]], 'needs you wins over pinned; a pinned one comes first in its group; in line and idle are Quiet');
  assert.deepEqual(bar.LIVEBAR_GROUPS.map(g => g[1]), ['Needs you', 'Working', 'Quiet'], 'the owner\'s words (option J b)');
  assert.deepEqual(bar.liveBarGroups(all.filter(o => o.s !== 'run'), 0).map(x => x.g), ['wait', 'quiet'], 'a group with nothing is not shown');
  assert.equal(all.find(o => o.key === 'ORCH-3').word, 'In line');
  assert.equal(all.find(o => o.key === 'ORCH-1').word, 'Needs you');
  assert.equal(all.find(o => o.key === 'ORCH-2').word, 'Working');
  assert.deepEqual(bar.liveBarModel(null, null), []);
  assert.deepEqual(bar.liveBarGroups(null, 0), [], 'nothing open, nothing waits: the menu says so');
});

test('the bar row is only the name, one Helpers menu and New: no chips, no counts (ORCH-2198, owner pick J b)', () => {
  const src = fs.readFileSync(path.join(WEB, 'pages/livebar.js'), 'utf8');
  assert.match(src, /h\('nav', \{className:'lbar-sw', 'aria-label':'Sessions'\}, helpersButton\(/, 'the sessions row is the one Helpers button');
  assert.doesNotMatch(src, /lbar-chip|lbar-g'|function count\(|function chip\(/, 'no chip or count of its own any more');
  assert.equal(bar.liveBarHelpersName(0), 'Helpers');
  assert.equal(bar.liveBarHelpersName(3), 'Helpers: something needs you', 'the button says it, the ◆ shows it; the number stays on the Review badge');
  assert.match(src, /'data-lbar-open':o\.id/, 'each row opens its pane');
});

test('the Helpers menu opens inside the window: above the bar at the bottom, below it at the top (full screen)', () => {
  assert.deepEqual(bar.liveBarMenuAt(720, 0), {side:'above', max:480}, 'bar at the bottom: above, at most 480 px');
  assert.deepEqual(bar.liveBarMenuAt(0, 720), {side:'below', max:480}, 'bar at the top (full screen): below');
  assert.deepEqual(bar.liveBarMenuAt(300, 10), {side:'above', max:284}, 'never taller than the room on its side');
  assert.equal(bar.liveBarMenuAt(40, 20).max, 120, 'a tiny window keeps a usable menu that scrolls');
  const css = fs.readFileSync(path.join(KIT, 'widgets.css'), 'utf8');
  assert.ok(css.includes('.lbar-pop[data-at=below]{top:calc(100% + var(--s2));bottom:auto}'), 'below the bar when it sits at the top');
  assert.ok(css.includes('.lbar-endwrap[data-at=below]'), 'Stop and End opens there too');
  const src = fs.readFileSync(path.join(WEB, 'pages/livebar.js'), 'utf8');
  assert.match(src, /liveBarMenuAt\(r\.top, window\.innerHeight - r\.bottom\)/, 'measured from the bar where it really is');
});

test('loaded before app.js, served as a page module, painted on every render, names no add-on', () => {
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  assert.ok(index.indexOf('pages/livebar.js') > 0 && index.indexOf('pages/livebar.js') < index.indexOf('src="app.js"'));
  const server = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/server.py'), 'utf8');
  assert.match(server, /\|livebar\|/);
  assert.match(fs.readFileSync(path.join(WEB, 'app.js'), 'utf8'), /window\.paintLiveBar\?\.\(\)/);
  const src = fs.readFileSync(path.join(WEB, 'pages/livebar.js'), 'utf8');
  assert.doesNotMatch(src.replace(/\.focus\(\)|focusKey/g, ''), /\b(focus|automation|factory|insights|relay)\b/i, 'found by its live_session capability, never by name');
  assert.match(src, /live_session === true/);
  assert.match(src, /querySelector\('\.shell-body \[data-keep\]'\)/, 'the bar goes into the keep place of soft page changes when it exists');
  assert.match(src, /LiveBar = \{(\s*\/\/[^\n]*\n)+\s*mount\(host/, 'another page can move the bar into its own mount point');
});

test('the look is the kit component, with the gallery entry and the thumbtack icon', () => {
  const css = fs.readFileSync(path.join(KIT, 'widgets.css'), 'utf8');
  for (const rule of ['.lbar{', '.lbar-cnt{', '.lbar-helpers{', '.lbar-gh{', '.lbar-pop{', '.lbar-row{', '.lbar-sw{display:flex;flex:1 1 0;flex-wrap:nowrap']) assert.ok(css.includes(rule), rule);
  const block = css.slice(css.indexOf('/* ---- Live bar'));
  assert.doesNotMatch(block, /#[0-9a-f]{3,8}\b|rgb\(/i, 'tokens only, no colour literals');
  assert.match(fs.readFileSync(path.join(KIT, 'gallery.html'), 'utf8'), /id="live-bar"[\s\S]*lbar-helpers[\s\S]*lbar-gh/);
  assert.match(fs.readFileSync(path.join(KIT, 'icons.js'), 'utf8'), /pinned: '/);
  for (const f of ['pages/livebar.js']) assert.doesNotMatch(fs.readFileSync(path.join(WEB, f), 'utf8'), /\bstyle="/);
});

test('plugs into the layer: a row opens its session there, open ones are marked, the layer fills the right end', () => {
  const src = fs.readFileSync(path.join(WEB, 'pages/livebar.js'), 'utf8');
  assert.match(src, /window\.LiveLayer\.open\(o\.dataset\.lbarOpen\)/, 'a chip or row opens in the layer when it is there');
  assert.match(src, /!e\.metaKey && !e\.ctrlKey && !e\.shiftKey/, 'a new-tab click stays a link');
  assert.match(src, /addEventListener\('orch:live-layer'/, 'the layer says which sessions are open');
  assert.match(src, /\(o\.members \|\| \[o\.id\]\)\.some\(id => bar\.panes\.includes\(id\)\)/, 'a row is current when its session (or one of its group, ORCH-345) is open');
  assert.match(src, /end\(fn\) \{/, 'the layer puts Open and Place at the right end');
  assert.match(src, /mount\(host, opts = \{\}\)/);
  const css = fs.readFileSync(path.join(KIT, 'widgets.css'), 'utf8');
  assert.ok(css.includes('.lbar.lbar-docked{position:relative') && css.includes('.lbar-row[aria-current=true]{'));
});

test('sessions without a ticket (ORCH-364): open ones join the bar by their title, a plain terminal is open until closed', () => {
  const sessions = [
    {id:'t_emp', kind:'empty', title:'Empty helper', open:true},
    {id:'t_chat', kind:'chat', title:'Chat helper', open:false},
    {id:'t_term', kind:'terminal', title:'Plain terminal', open:true},
    {id:'t_man', kind:'manager', title:'Manager', open:true},
    {id:'t_odd', kind:'ticket', title:'Not a kind', open:true},
  ];
  // the sessions API lists the open ones with their kind (sessions.py no_ticket): a plain terminal is idle, word Open
  const list = [sess('t_emp', '', 'working', {title:'Empty helper', kind:'empty'}), sess('t_a', 'ORCH-1', 'working'),
    sess('t_term', '', 'idle', {title:'Plain terminal', kind:'terminal', word:'Open'}), sess('t_man', '', 'idle', {title:'Manager', kind:'manager', word:'Idle'})];
  const all = bar.liveBarModel(list, ['t_emp', 't_term', 't_man']);
  assert.deepEqual(all.map(o => [o.key || o.title, o.s, o.pin, o.kind]), [['Empty helper', 'run', true, 'empty'], ['ORCH-1', 'run', false, ''],
    ['Plain terminal', 'idle', true, 'terminal'], ['Manager', 'idle', true, 'manager']]);
  assert.equal(all.find(o => o.kind === 'terminal').word, 'Open');
  assert.deepEqual(all.filter(o => o.pin).map(o => o.title), ['Empty helper', 'Plain terminal', 'Manager'], 'a new one is pinned');
  assert.deepEqual(bar.liveBarGroups(all, 0).find(x => x.g === 'quiet').rows.map(o => o.title), ['Plain terminal', 'Manager'], 'the Manager is a Quiet row of the Helpers menu: it opens its pane');
  assert.equal(bar.liveBarNewOpen(sessions, 'manager').id, 't_man');
  assert.equal(bar.liveBarNewOpen(sessions, 'chat'), null, 'a closed one starts again');
  assert.equal(bar.liveBarNewOpen(null, 'empty'), null);
  // #1531: a start that worked but is not in the state's sessions yet is found in the live sessions list
  assert.equal(bar.liveBarNewMade([], list, 'terminal').id, 't_term');
  assert.equal(bar.liveBarNewMade(sessions, [], 'manager').id, 't_man', 'the state still comes first');
  assert.equal(bar.liveBarNewMade(null, null, 'terminal'), null);
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/livebar.js'), 'utf8');
  assert.match(src, /if \(r\.ok && !made\) \{[^}]*LiveSessions\?\.refresh/, 'a start that worked reads the sessions again before it gives up');
  assert.deepEqual(bar.LIVEBAR_NEW.map(n => n.title), ['Empty helper', 'Chat helper', 'Plain terminal', 'Manager'], 'draft D words, in its order');
});

// ORCH-365: the Focus button on every ticket says what pressing it does, from the same session states as the bar.
test('the Focus button word: Answer, Watch, Open, In line, Start; none on a finished ticket without a helper', () => {
  const ask = {questions:[{id:'q1', text:'Which one?'}]};
  const verb = (tk, r) => bar.liveFocusVerb(tk, r, helpers.helperState);
  assert.equal(verb(t('t_a', 'ORCH-1'), run('you')), 'Answer');
  assert.equal(verb(t('t_b', 'ORCH-2'), run('working')), 'Watch');
  assert.equal(verb(t('t_c', 'ORCH-3'), run('idle')), 'Open');
  assert.equal(verb(t('t_d', 'ORCH-4'), {running:false, hold:'Waits for a free place'}), 'In line');
  assert.equal(verb(t('t_e', 'ORCH-5', {status:'ready'}), undefined), 'Start');
  assert.equal(verb(t('t_f', 'ORCH-6', {status:'waiting', ...ask}), undefined), 'Answer', 'an open question with no helper');
  assert.equal(verb(t('t_g', 'ORCH-7', {questions:[{id:'q1', text:'x', answer:'yes'}]}), undefined), 'Start', 'an answered question is not one');
  for (const status of ['done', 'dropped', 'superseded']) assert.equal(verb(t('t_h', 'ORCH-8', {status, ...ask}), undefined), '', status);
  assert.equal(verb(t('t_i', 'ORCH-9', {status:'done'}), run('working')), 'Watch', 'a helper still running on a done ticket can be watched');
  assert.equal(verb(null, null), '');
});

test('the ticket page and every ticket row use the one Focus button; a pane has Open ticket, also in More', () => {
  const read = f => fs.readFileSync(path.join(WEB, 'pages', f), 'utf8');
  const ticket = read('ticket.js'), list = read('tickets.js'), layer = read('live-layer.js');
  assert.equal((ticket.match(/liveFocusButton\(t, true\)/g) || []).length, 1, 'the working header (Watch in Focus)');
  // with no helper there is one start button; Focus opens from the ⋯ menu (ORCH-1466)
  assert.match(ticket, /function ticketFocusMenuItem[^]*?liveFocusButton\(t\)[^]*?'Open in ' \+ liveLayerName\(\)/);
  assert.match(ticket, /'menu-pop', role:'menu'\}, ticketFocusMenuItem\(t, run\)/);
  assert.match(list, /function ticketRowFocus/);
  assert.match(list, /ticketRowFocus\(t, nextAction\)/, 'the table row');
  assert.match(list, /function shortSide[^]*?liveFocusButton\(t\)/, 'the phone row');
  assert.match(layer, /function liveFocusButton[^]*?liveFocusOn\(\)/, 'only where Focus runs');
  assert.match(layer, /'data-key':'live-open-ticket'/);
  assert.match(layer, /'data-key':'live-more-ticket'/);
});

test('Runs on: the usual tool and model preselected, a pick sent only when it changes the start (ORCH-710, ORCH-1660)', () => {
  const agents = [{name:'claude', label:'Claude Code', models:true, chosen:true}, {name:'codex', label:'Codex', models:false}, {name:'gone', found:false}];
  const r = bar.liveBarRunsOn([], agents, {tool:'', model:''});
  assert.deepEqual(r.tools.map(t => t.name), ['claude', 'codex'], 'only the tools found on this computer');
  assert.equal(r.usual, 'claude'); assert.equal(r.tool, 'claude'); assert.equal(r.takesModel, true);
  assert.equal(r.model, bar.LIVEBAR_EMPTY_MODEL, 'none made yet: orch\'s pick'); assert.equal(r.usualModel, 'sonnet');
  const sessions = [{id:'t_emp', kind:'empty', model:'haiku'}, {id:'t_gen', kind:'chat', model:'opus'}];
  assert.equal(bar.liveBarRunsOn(sessions, agents, null).model, 'haiku', 'the Empty helper\'s own model');
  const codex = bar.liveBarRunsOn(sessions, agents, {tool:'codex', model:'opus'});
  assert.equal(codex.tool, 'codex'); assert.equal(codex.takesModel, false, 'a tool with no model choice: no model picker');
  assert.equal(bar.liveBarRunsOn([], [], null), null, 'no tool: no row');
  assert.equal(bar.liveBarRunsOn([], agents, {tool:'nope'}).tool, 'claude', 'a tool that went away: the usual one');

  const usual = bar.liveBarRunsOn(sessions, agents, null);
  assert.deepEqual(bar.liveBarNewArgs('empty', {tool:'', model:''}, usual, sessions), {kind:'empty'}, 'nothing changed: one click, the usual');
  assert.deepEqual(bar.liveBarNewArgs('empty', {tool:'', model:'sonnet'}, usual, sessions), {kind:'empty', model:'sonnet'});
  assert.deepEqual(bar.liveBarNewArgs('empty', {tool:'', model:'haiku'}, usual, sessions), {kind:'empty'}, 'its own model stays orch\'s pick');
  assert.deepEqual(bar.liveBarNewArgs('chat', {tool:'', model:'sonnet'}, usual, sessions), {kind:'chat', model:'sonnet'}, 'every helper takes the model');
  assert.deepEqual(bar.liveBarNewArgs('chat', {tool:'', model:'opus'}, usual, sessions), {kind:'chat'});
  assert.deepEqual(bar.liveBarNewArgs('manager', {tool:'', model:'haiku'}, usual, sessions), {kind:'manager', model:'haiku'}, 'not made yet: sent');
  assert.deepEqual(bar.liveBarNewArgs('chat', {tool:'codex', model:'haiku'}, codex, sessions), {kind:'chat', agent:'codex'}, 'another tool, which takes no model');
  assert.deepEqual(bar.liveBarNewArgs('empty', {tool:'claude', model:''}, usual, sessions), {kind:'empty'}, 'the usual tool is not named');
  assert.deepEqual(bar.liveBarNewArgs('terminal', {tool:'codex', model:'haiku'}, codex, sessions), {kind:'terminal'}, 'a plain terminal runs no helper');
  assert.deepEqual(bar.LIVEBAR_MODELS.map(m => m[0]), ['sonnet', 'opus', 'haiku', 'fable']);
});

test('the New menu has one Runs on row and the helper places, and no model line of its own (ORCH-1660)', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/livebar.js'), 'utf8');
  const menu = src.slice(src.indexOf('function newMenu()'), src.indexOf('function newButton('));
  assert.ok(menu.includes("runsOn('bar')") && menu.includes('placesLine()'), 'the menu shows Runs on and the helper places');
  assert.ok(!/Empty helper runs on|Empty helper: this tool/.test(src), 'no stray model line for one kind only');
  assert.ok(src.includes("runsOn: () => runsOn('wall')"), 'the wall shows the same row (ORCH-1617)');
  const wall = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/livewall.js'), 'utf8');
  assert.ok(wall.includes('window.LiveNew?.runsOn?.()'), 'the wall draws Runs on beside its counts');
});

test('the bar moves a toast that is already open above itself when it is drawn (ORCH-1594)', () => {
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/livebar.js'), 'utf8');
  assert.match(src, /document\.body\.dataset\.liveBar = '1';\n\s*place\(\);\n\s*window\.UI\?\.toastPlace\?\.\(\);/);
});

test('ORCH-1643: the Needs you count is the Review badge number (never a second one), the rest is one link to Review', () => {
  assert.equal(bar.liveBarNeedCount(4, 3), 4, 'the badge says 4: the menu says 4, not the 3 sessions');
  assert.equal(bar.liveBarNeedCount(0, 2), 2, 'never fewer than the sessions that wait');
  const all = bar.liveBarModel([sess('t_a', 'ORCH-1', 'needs-you')], []);
  assert.deepEqual(bar.liveBarGroups(all, 4).map(x => [x.g, x.n, x.rows.length]), [['wait', 4, 1]]);
  assert.deepEqual(bar.liveBarGroups([], 2).map(x => [x.g, x.n, x.rows.length]), [['wait', 2, 0]], 'waiting things that are no session here still show');
  const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/livebar.js'), 'utf8');
  assert.match(src, /'data-key':'lbar-wait-rest'/, 'the rest links to the Review page');
});

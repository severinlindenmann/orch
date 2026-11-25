// One address per add-on page: #addon/<name>[/<path>]; the old #open/<name>/<path> forwards to it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const routeSource = source.slice(source.indexOf('function route() {'), source.indexOf('function render('));
function route(hash, addons, extra = {}) {
  const ctx = {history:{replaceState(){}}, location:{hash}, snapshot:false, state:{settings:true}, addons:() => addons, decodeURIComponent, ...extra};
  vm.createContext(ctx); vm.runInContext(routeSource, ctx);
  return ctx.route();
}
const FOCUS = {name:'focus', page:{path:'/'}, dashboard:{label:'Focus'}};
const OTHER = {name:'automation', dashboard:{label:'Automation'}};
test('#addon/focus is the Focus page; #open/focus/ and #open/focus/t/<id> forward to it', () => {
  assert.deepEqual({...route('#addon/focus', [FOCUS, OTHER])}, {kind:'page', id:'focus', path:'', hash:'#addon/focus'});
  assert.deepEqual({...route('#note/t_1', [])}, {kind:'home', hash:'#home'}, 'the Notes page is gone: an old note link lands on Home');
  assert.deepEqual({...route('#open/focus/', [FOCUS])}, {kind:'page', id:'focus', path:'', hash:'#addon/focus'});
  assert.deepEqual({...route('#open/focus/t/t_abc12345', [FOCUS])}, {kind:'page', id:'focus', path:'t/t_abc12345', hash:'#addon/focus/t/t_abc12345'});
  assert.deepEqual({...route('#addon/focus/t/t_abc12345', [FOCUS])}, {kind:'page', id:'focus', path:'t/t_abc12345', hash:'#addon/focus/t/t_abc12345'});
});
// Focus (ORCH-261, the only Focus since ORCH-816): the live-session add-on's addresses show the live page (kind 'live'),
// with the same path and address; a shared copy has no live sessions. The dashboard names no add-on: the page is found
// by its live_session capability.
const LIVE = {name:'focus', page:{path:'/', live_session:true}, dashboard:{label:'Focus'}};
test('the live-session add-on\'s addresses are Focus; other pages stay as they are', () => {
  const ctxOf = on => ({liveFocusOn: () => on, livePageOf: id => [LIVE].find(a => a.name === id) || null});
  const on = ctxOf(true);
  assert.equal(route('#addon/focus', [LIVE], {...ctxOf(false), snapshot:true}).kind, 'live', 'a shared copy too: there is no old page to embed');
  assert.deepEqual({...route('#addon/focus', [LIVE, OTHER], on)}, {kind:'live', id:'focus', path:'', hash:'#addon/focus'});
  assert.deepEqual({...route('#open/focus/t/t_abc12345', [LIVE], on)}, {kind:'live', id:'focus', path:'t/t_abc12345', hash:'#addon/focus/t/t_abc12345'});
  const PAGE = {name:'factory', page:{path:'/'}, dashboard:{label:'Factory'}};
  assert.equal(route('#addon/factory', [LIVE, PAGE], on).kind, 'page', 'a page without live sessions never changes');
  assert.equal(route('#addon/automation', [LIVE, OTHER], on).kind, 'addon');
  assert.equal(route('#home', [LIVE], on).kind, 'home');
  assert.equal(route('#addon/focus/../x', [LIVE], on).kind, 'notfound');
});
const liveSource = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/live.js'), 'utf8');
test('liveFocusOn: always, with no setting, never in a shared copy', () => {
  const on = (state, snapshot = false) => { const ctx = {state, snapshot}; vm.createContext(ctx); vm.runInContext(liveSource, ctx); return ctx.liveFocusOn(); };
  for (const s of [{settings:{}}, {}, null, {settings:{focus_preview_on:false}}]) assert.equal(on(s), true, 'an old setting changes nothing');
  assert.equal(on({settings:{}}, true), false);
});
test('the live page is the wall under the add-on\'s own name, with no Preview tag and no way back', () => {
  const h = (tag, attrs = {}, ...kids) => ({tag, attrs, kids:kids.flat(Infinity).filter(Boolean)});
  const ctx = {snapshot:false, h, fragment:(...k) => h('frag', {}, ...k), heading:(t, sub, o) => h('header', {}, h('h1', {}, t), o?.actions), addonLabel:a => a?.dashboard?.label, addons:() => [LIVE], encodeURIComponent,
    window:{}, liveWall:() => h('div', {'data-key':'live-wall'})};
  vm.createContext(ctx); vm.runInContext(liveSource, ctx);
  const all = n => [n, ...(n.kids || []).flatMap(k => typeof k === 'object' ? all(k) : [])];
  const text = n => all(n).flatMap(x => (x.kids || []).filter(k => typeof k === 'string')).join(' ');
  assert.equal(ctx.livePageOf('focus'), LIVE);
  assert.equal(ctx.livePageOf('automation'), null);
  const page = ctx.liveNextPage({kind:'live', id:'focus', path:''}), key = k => all(page).find(x => x.attrs?.['data-key'] === k);
  assert.match(text(page), /^Focus/);
  assert.doesNotMatch(text(page), /Preview|today/);
  assert.equal(key('live-next-tag'), undefined);
  assert.equal(key('live-next-off'), undefined);
  assert.ok(all(key('live-next')).some(x => x.attrs?.['data-key'] === 'live-wall'), 'the wall fills the page (pages/livewall.js)');
  assert.equal(all(page).filter(x => x.tag === 'iframe').length, 0);
  ctx.snapshot = true;  // a shared copy: the name and one plain line, no wall
  const copy = ctx.liveNextPage({kind:'live', id:'focus', path:''});
  assert.match(text(copy), /^Focus Live sessions show only on the computer the helpers work on\.$/);
  assert.equal(all(copy).some(x => x.attrs?.['data-key'] === 'live-wall'), false);
});
test('an add-on without a page keeps its own tab; path tricks fall back', () => {
  assert.equal(route('#addon/automation', [FOCUS, OTHER]).kind, 'addon');
  assert.equal(route('#addon/focus/../x', [FOCUS]).kind, 'notfound');
  assert.equal(route('#open/focus/../x', [FOCUS]).kind, 'notfound');
  assert.equal(route('#open/nothing/', [FOCUS]).kind, 'notfound');
});
test('an add-on page opens at its own place after a second # (Home links to a Factory proposal, ORCH-60)', () => {
  assert.deepEqual({...route('#addon/focus/#/order/t_abc12345/proposal', [FOCUS])}, {kind:'page', id:'focus', path:'', inner:'/order/t_abc12345/proposal', hash:'#addon/focus/#/order/t_abc12345/proposal'});
  assert.equal(route('#addon/focus/t/x#results', [FOCUS]).inner, 'results');  // a place a Focus link names (ORCH-186)
  for (const hash of ['#addon/focus/#/a/../b', '#addon/focus/#a.b', '#addon/focus/#/a#/b']) assert.equal(route(hash, [FOCUS]).kind, 'notfound', hash);
});
test('unknown addresses are Page not found; empty and #home stay Home; a query keeps its route', () => {
  for (const hash of ['#nope', '#tickets/x', '#ticketsx', '#addon/missing']) assert.equal(route(hash, [FOCUS]).kind, 'notfound', hash);
  assert.equal(route('', []).kind, 'home');
  assert.equal(route('#home', []).kind, 'home');
  assert.deepEqual({...route('#tickets?view=working', [])}, {kind:'tickets', hash:'#tickets?view=working'});
  assert.equal(route('#notes?x=1', []).kind, 'home');
});
test('#review and the link `orch review link` prints (#/review) are the Review page', () => {
  assert.deepEqual({...route('#review', [])}, {kind:'review', hash:'#review'});
  assert.deepEqual({...route('#/review', [])}, {kind:'review', hash:'#review'});
  assert.equal(route('#review?x=1', []).kind, 'review');
  // ORCH-1804: the ticket beside the deck is part of Review, so opening or closing it keeps the deck where it is
  assert.equal(route('#review?ticket=t_abcdef', []).hash, '#review');
  assert.equal(route('#review?card=x&ticket=t_abcdef', []).hash, route('#review?card=x', []).hash);
  assert.equal(route('#reviews', []).kind, 'notfound');
  assert.equal(route('#/reviewx', []).kind, 'notfound');
});
const skSource = source.slice(source.indexOf('function skeletonFor('), source.indexOf('function notFoundPage('));
test('skeletonFor draws the page shape, busy, with one status text and hidden shapes', () => {
  const h = (tag, attrs = {}, ...kids) => ({tag, attrs, kids:kids.flat(Infinity).filter(Boolean)});
  const ctx = {h}; vm.createContext(ctx); vm.runInContext(skSource, ctx);
  const all = n => [n, ...(n.kids || []).flatMap(k => typeof k === 'object' ? all(k) : [])];
  const count = (n, cls) => all(n).filter(x => (x.attrs?.className || '').split(' ').includes(cls)).length;
  for (const kind of ['home', 'tickets', 'ticket', 'page', 'section']) {
    const s = ctx.skeletonFor(kind);
    assert.equal(s.attrs['aria-busy'], 'true');
    assert.equal(all(s).filter(x => x.attrs?.role === 'status').length, 1);
    assert.ok(all(s).filter(x => (x.attrs?.className || '').split(' ').includes('skeleton')).every(x => x.attrs['aria-hidden'] === 'true'));
  }
  ctx.localStorage = {getItem: () => 'board'};
  assert.equal(count(ctx.skeletonFor('tickets'), 'sk-board'), 1);  // the board is columns while loading (#694)
  assert.equal(count(ctx.skeletonFor('tickets'), 'sk-row'), 0);
  delete ctx.localStorage;
  assert.equal(count(ctx.skeletonFor('tickets'), 'sk-row'), 5);
  assert.equal(count(ctx.skeletonFor('tickets'), 'sk-toolbar'), 1);
  assert.equal(count(ctx.skeletonFor('home'), 'sk-columns'), 1);
  assert.equal(count(ctx.skeletonFor('ticket'), 'sk-side'), 1);
  assert.equal(ctx.hashKind('#ticket/t_1'), 'ticket');
  assert.equal(ctx.hashKind('#tickets?view=x'), 'tickets');
  assert.equal(ctx.hashKind('#notes'), 'home');
  assert.equal(ctx.hashKind('#note/t_1'), 'home');
});
test('the sidebar: Review has the needs badge, Settings is last in the foot', () => {
  const html = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/index.html'), 'utf8');
  const foot = html.slice(html.indexOf('<div class="side-foot person-row">'));
  assert.ok(foot.indexOf('id="mm-toggle"') < foot.indexOf('id="side-settings"'));
  assert.ok(html.indexOf('id="side-settings"') > html.indexOf('id="side-nav"') && html.indexOf('id="side-settings"') > html.indexOf('id="side-addons"'));
  // ORCH-63: the needs-you number sits on the Review entry, right after Tickets; Home has no badge
  assert.match(source, /navLink\('#home', 'Home', 'home'\), navLink\('#tickets', 'Tickets', 'tickets'\),\n\s*snapshot \? null : navLink\('#review', 'Review', 'review', needCount \? h\('span', \{className:'count'/);
  assert.doesNotMatch(source, /nav-helper/);
});
test('one needs-you count: every reader calls needsYouTotal', () => {
  const pages = ['home', 'tickets'].map(p => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/' + p + '.js'), 'utf8')).join('\n');
  const all = source + pages;
  assert.equal((all.match(/needsToday\(\)\.count/g) || []).length, 1);  // only inside needsYouTotal
  assert.match(pages, /function needsYouTotal\(\) \{ return state \? needsToday\(\)\.count : 0; \}/);
  assert.match(source, /needsYouTotal\(\)/);
  // ORCH-1616 (owner, less noise): the Tickets header no longer repeats the number; only the Review badge shows it
  assert.doesNotMatch(pages.slice(pages.indexOf('function list()'), pages.indexOf("heading('Tickets'") + 200), /needsYouTotal\(\)/);
});

test('shared words: status, steps and the updated time', () => {
  const H = require('../src/orch_dashboard/web/helpers.js');
  assert.deepEqual(['open', 'ready', 'active', 'waiting', 'review', 'done'].map(s => H.statusWord(s)), ['Backlog', 'To do', 'Working', 'Needs you', 'Check', 'Done']);
  assert.equal(H.stepsText(2, 5), '2 of 5 tasks'); assert.equal(H.stepsText(1, 1), '1 of 1 task');
  const now = Date.parse('2024-01-01T12:00:00Z');
  assert.equal(H.updatedText(now - 20000, now), 'Updated just now');
  assert.equal(H.updatedText(now - 3 * 60000, now), 'Updated 3 min ago');
});
test('#settings is General; #settings/<tab> opens that tab on the same Settings page', () => {
  assert.deepEqual({...route('#settings', [])}, {kind:'settings', hash:'#settings', tab:'general', addon:null});
  for (const tab of ['general', 'agent', 'phone', 'addons']) assert.deepEqual({...route('#settings/' + tab, [])}, {kind:'settings', hash:'#settings', tab, addon:null});
  assert.deepEqual({...route('#settings/addons/publish', [])}, {kind:'settings', hash:'#settings', tab:'addons', addon:'publish'});  // one add-on's own settings page
  // the address names the tab like its label; the old names still open the same tab
  for (const [name, tab] of [['helper', 'agent'], ['contacts', 'phone']]) assert.deepEqual({...route('#settings/' + name, [])}, {kind:'settings', hash:'#settings', tab, addon:null});
  assert.equal(route('#settings/phone/publish', []).kind, 'notfound');
  assert.equal(route('#settings/nope', []).kind, 'notfound');  // an unknown tab is an unknown address: Page not found
});
test('the phone tab is role=tab and choosing it keeps Settings open at #settings/contacts and adds a history entry', () => {
  const settingsSrc = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const nav = settingsSrc.slice(settingsSrc.indexOf("role:'tablist'"), settingsSrc.indexOf("h('div', {className:'settings-content'}"));
  assert.match(nav, /\['phone', phoneAddon\.dashboard\.label\]/);
  assert.doesNotMatch(nav, /h\('a'/);
  assert.match(nav, /role:'tab', 'aria-selected':settingsTab === id, 'aria-controls':'settings-panel-' \+ id/);
  const go = settingsSrc.slice(settingsSrc.indexOf('function settingsGo('), settingsSrc.indexOf('}', settingsSrc.indexOf('function settingsGo(')) + 1);
  const calls = [];
  const ctx = {settingsTab:'general', settingsReview:'x', location:{hash:'#settings'}, render:() => calls.push('render'),
    history:{pushState:(_s, _t, url) => { ctx.location.hash = url; calls.push('push'); }}};
  const map = settingsSrc.slice(settingsSrc.indexOf('const SETTINGS_TAB_ADDRESS'), settingsSrc.indexOf('\n', settingsSrc.indexOf('const SETTINGS_TAB_ADDRESS')));
  vm.createContext(ctx); vm.runInContext(map + '\n' + go + '; settingsGo("phone");', ctx);
  assert.equal(ctx.location.hash, '#settings/contacts');
  assert.equal(ctx.settingsTab, 'phone');
  assert.deepEqual(calls, ['push', 'render']);
  assert.equal(route(ctx.location.hash, []).kind, 'settings');
});
// ORCH-465: one ticket's address opens that ticket's session in the layer, once per address.
test('a ticket\'s address opens its session in the layer, once, and only a known ticket', () => {
  const ctx = {state:null, snapshot:false};
  vm.createContext(ctx); vm.runInContext(liveSource, ctx);
  const opened = [], layer = {open:(id, into) => opened.push([id, into])}, known = id => id === 't_abc12345';
  const r = hash => ({kind:'live', id:'focus', path:hash.replace('#addon/focus/', '').replace('#addon/focus', ''), hash});
  assert.equal(ctx.liveAddressTicket(r('#addon/focus/t/t_abc12345')), 't_abc12345');
  assert.equal(ctx.liveAddressTicket(r('#addon/focus')), null);
  assert.equal(ctx.liveAddressTicket({kind:'page', path:'t/t_abc12345'}), null, 'only a Focus address');
  assert.equal(ctx.liveOpenFromAddress(r('#addon/focus/t/t_zzz'), layer, known), false, 'not loaded yet');
  assert.equal(ctx.liveOpenFromAddress(r('#addon/focus/t/t_abc12345'), layer, known), true);
  assert.equal(ctx.liveOpenFromAddress(r('#addon/focus/t/t_abc12345'), layer, known), false, 'every later render leaves it as the person put it');
  assert.deepEqual(opened, [['t_abc12345', true]]);
  ctx.liveOpenFromAddress(r('#addon/focus'), layer, known);
  assert.equal(ctx.liveOpenFromAddress(r('#addon/focus/t/t_abc12345'), layer, known), true, 'back to the address: opens again');
  assert.match(source, /liveDockSync\(\);[^\n]*\n\s*if \(typeof liveOpenFromAddress === 'function'\) liveOpenFromAddress\(r\);/, 'render calls it after the layer');
});
// ORCH-465: the shown add-on page takes the keyboard after it loaded, unless the person types somewhere else.
test('the add-on frame takes the keyboard on load, never from a field or an open dialog', () => {
  const settings = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const fn = settings.slice(settings.indexOf('function frameTakesKeys('), settings.indexOf('function pageFrame('));
  const ctx = {}; vm.createContext(ctx); vm.runInContext(fn, ctx);
  const body = {matches:() => false};
  const frame = {isConnected:true, focused:0, focus() { this.focused++; }};
  const doc = (active, dialog = null) => ({body, activeElement:active, querySelector:() => dialog});
  assert.equal(ctx.frameTakesKeys(frame, doc(body)), true);
  assert.equal(ctx.frameTakesKeys(frame, doc({matches:s => s.includes('input')})), false, 'typing in a field');
  assert.equal(ctx.frameTakesKeys(frame, doc({matches:() => false})), true, 'a link that was clicked');
  assert.equal(ctx.frameTakesKeys(frame, doc(body, {})), false, 'a dialog is open');
  assert.equal(ctx.frameTakesKeys({...frame, isConnected:false}, doc(body)), false);
  assert.equal(frame.focused, 2);
  assert.match(settings, /frame\.addEventListener\('load', \(\) => frameTakesKeys\(frame\)\)/);
});
// ORCH-677: an address of a ticket that does not exist says so, once; the pane keeps the keyboard through a repaint.
test('an unknown ticket address says so once, once the tickets are loaded', () => {
  const ctx = {state:{tickets:[{id:'t_abc12345'}]}, snapshot:false};
  vm.createContext(ctx); vm.runInContext(liveSource, ctx);
  const said = [], say = t => said.push(t), layer = {open() {}}, known = id => id === 't_abc12345';
  const r = hash => ({kind:'live', id:'focus', path:hash.replace('#addon/focus/', ''), hash});
  assert.equal(ctx.liveOpenFromAddress(r('#addon/focus/t/t_zzz'), layer, known, say), false);
  assert.equal(ctx.liveOpenFromAddress(r('#addon/focus/t/t_zzz'), layer, known, say), false);
  assert.deepEqual(said, ['There is no ticket with this address. Find it on the Tickets page.']);
  ctx.state = {tickets:[]};
  assert.equal(ctx.liveOpenFromAddress(r('#addon/focus/t/t_yyy'), layer, known, say), false, 'tickets not loaded yet: no word');
  assert.equal(said.length, 1);
});
test('the layer puts the keyboard back into the pane after a repaint, until the person acts', () => {
  const layerSrc = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/live-layer.js'), 'utf8');
  const fn = layerSrc.slice(layerSrc.indexOf('let liveLayerWant'), layerSrc.indexOf('for (const type of'));
  const calls = [];
  const pane = {focused:0, contains:n => n === inner, querySelector:() => null, focus() { this.focused++; }}, inner = {};
  const body = {}, doc = {body, activeElement:body, querySelector:() => pane};
  const ctx = {document:doc, Date}; vm.createContext(ctx); vm.runInContext(fn + '; this.api = {take:liveLayerTake, want:v => { liveLayerWant = v; }, get w() { return liveLayerWant; }};', ctx);
  ctx.api.want({id:'t_a', until:Date.now() + 5000});
  ctx.api.take(); assert.equal(pane.focused, 1);
  doc.activeElement = inner; ctx.api.take(); assert.equal(pane.focused, 1, 'already inside');
  doc.activeElement = body; ctx.api.take(); assert.equal(pane.focused, 2, 'dropped by a repaint: back');
  ctx.api.want({id:'t_a', until:Date.now() - 1}); ctx.api.take(); assert.equal(pane.focused, 2); assert.equal(ctx.api.w, null, 'expired');
  assert.match(layerSrc, /tabindex:'-1', 'aria-label'/, 'the pane can take the keyboard');
  assert.match(layerSrc, /liveLayerPad\(\);\n  liveLayerTake\(\);/, 'every paint');
});

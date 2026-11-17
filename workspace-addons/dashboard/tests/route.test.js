// One address per add-on page: #addon/<name>[/<path>]; the old #open/<name>/<path> forwards to it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const routeSource = source.slice(source.indexOf('function route() {'), source.indexOf('function render('));
function route(hash, addons) {
  const ctx = {history:{replaceState(){}}, location:{hash}, snapshot:false, state:{settings:true}, addons:() => addons, decodeURIComponent};
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
test('an add-on without a page keeps its own tab; path tricks fall back', () => {
  assert.equal(route('#addon/automation', [FOCUS, OTHER]).kind, 'addon');
  assert.equal(route('#addon/focus/../x', [FOCUS]).kind, 'notfound');
  assert.equal(route('#open/focus/../x', [FOCUS]).kind, 'notfound');
  assert.equal(route('#open/nothing/', [FOCUS]).kind, 'notfound');
});
test('an add-on page opens at its own place after a second # (Home links to a Factory proposal, ORCH-60)', () => {
  assert.deepEqual({...route('#addon/focus/#/order/t_abc12345/proposal', [FOCUS])}, {kind:'page', id:'focus', path:'', inner:'/order/t_abc12345/proposal', hash:'#addon/focus/#/order/t_abc12345/proposal'});
  for (const hash of ['#addon/focus/#/a/../b', '#addon/focus/#x', '#addon/focus/#/a#/b']) assert.equal(route(hash, [FOCUS]).kind, 'notfound', hash);
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
  const foot = html.slice(html.indexOf('<div class="side-foot">'));
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
  for (const reader of [source, pages.split('function needsYouTotal')[1], pages.slice(pages.indexOf("heading('Tickets'") - 200)]) assert.match(reader, /needsYouTotal\(\)/);
});

test('shared words: status, steps and the updated time', () => {
  const H = require('../src/orch_dashboard/web/helpers.js');
  assert.deepEqual(['open', 'ready', 'active', 'waiting', 'review', 'done'].map(s => H.statusWord(s)), ['To do', 'To do', 'Working', 'Needs you', 'Check', 'Done']);
  assert.equal(H.stepsText(2, 5), '2 of 5 steps'); assert.equal(H.stepsText(1, 1), '1 of 1 step');
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

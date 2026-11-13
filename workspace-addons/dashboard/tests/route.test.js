// One address per add-on page: #addon/<name>[/<path>]; the old #open/<name>/<path> forwards to it.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/app.js'), 'utf8');
const routeSource = source.slice(source.indexOf('function route() {'), source.indexOf('function render('));
function route(hash, addons) {
  const ctx = {location:{hash}, snapshot:false, state:{settings:true}, addons:() => addons, decodeURIComponent};
  vm.createContext(ctx); vm.runInContext(routeSource, ctx);
  return ctx.route();
}
const FOCUS = {name:'focus', page:{path:'/'}, dashboard:{label:'Focus'}};
const OTHER = {name:'automation', dashboard:{label:'Automation'}};
test('#addon/focus is the Focus page; #open/focus/ and #open/focus/t/<id> forward to it', () => {
  assert.deepEqual({...route('#addon/focus', [FOCUS, OTHER])}, {kind:'page', id:'focus', path:'', hash:'#addon/focus'});
  assert.deepEqual({...route('#open/focus/', [FOCUS])}, {kind:'page', id:'focus', path:'', hash:'#addon/focus'});
  assert.deepEqual({...route('#open/focus/t/t_abc12345', [FOCUS])}, {kind:'page', id:'focus', path:'t/t_abc12345', hash:'#addon/focus/t/t_abc12345'});
  assert.deepEqual({...route('#addon/focus/t/t_abc12345', [FOCUS])}, {kind:'page', id:'focus', path:'t/t_abc12345', hash:'#addon/focus/t/t_abc12345'});
});
test('an add-on without a page keeps its own tab; path tricks fall back', () => {
  assert.equal(route('#addon/automation', [FOCUS, OTHER]).kind, 'addon');
  assert.equal(route('#addon/focus/../x', [FOCUS]).kind, 'home');
  assert.equal(route('#open/focus/../x', [FOCUS]).kind, 'home');
  assert.equal(route('#open/nothing/', [FOCUS]).kind, 'home');
});
test('#settings is General; #settings/<tab> opens that tab on the same Settings page', () => {
  assert.deepEqual({...route('#settings', [])}, {kind:'settings', hash:'#settings', tab:'general'});
  for (const tab of ['general', 'agent', 'phone', 'addons']) assert.deepEqual({...route('#settings/' + tab, [])}, {kind:'settings', hash:'#settings', tab});
  assert.equal(route('#settings/nope', []).kind, 'home');
});
test('the phone tab is role=tab and choosing it keeps Settings open at #settings/phone', () => {
  const settingsSrc = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
  const nav = settingsSrc.slice(settingsSrc.indexOf("role:'tablist'"), settingsSrc.indexOf("h('div', {className:'settings-content'}"));
  assert.match(nav, /\['phone', phoneAddon\.dashboard\.label\]/);
  assert.doesNotMatch(nav, /h\('a'/);
  assert.match(nav, /role:'tab', 'aria-selected':settingsTab === id, 'aria-controls':'settings-panel-' \+ id/);
  const go = settingsSrc.slice(settingsSrc.indexOf('function settingsGo('), settingsSrc.indexOf('}', settingsSrc.indexOf('function settingsGo(')) + 1);
  const calls = [];
  const ctx = {settingsTab:'general', settingsReview:'x', location:{hash:'#settings'}, render:() => calls.push('render'),
    history:{replaceState:(_s, _t, url) => { ctx.location.hash = url; calls.push('replace'); }}};
  vm.createContext(ctx); vm.runInContext(go + '; settingsGo("phone");', ctx);
  assert.equal(ctx.location.hash, '#settings/phone');
  assert.equal(ctx.settingsTab, 'phone');
  assert.deepEqual(calls, ['replace', 'render']);
  assert.equal(route(ctx.location.hash, []).kind, 'settings');
});

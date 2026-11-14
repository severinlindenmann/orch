// Owner feedback 14 Nov fb22: add-on pages are slow to open the first time. Their views are fetched in the background
// once, so the first click already has something to show; hovering a menu entry fetches it right away.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');

const PAGES = path.join(__dirname, '../src/orch_dashboard/web/pages');
function context(list) {
  const fetched = [], timers = [];
  const node = () => ({tag:'x', attrs:{}, children:[], dataset:{}, addEventListener() {}, append() {}, querySelectorAll() { return []; }, querySelector() { return null; }});
  const c = vm.createContext({
    window:{DashHelpers:helpers, orch:{toast() {}}}, localStorage:{getItem() { return null; }, setItem() {}},
    h:() => node(), fragment:() => node(), el:() => node(), button:() => node(), iconEl:() => node(), array:v => Array.isArray(v) ? v : [],
    snapshot:false, clean:v => String(v ?? ''), time:() => '', today:() => '2026-11-14', render() {}, route:() => ({kind:'home'}), location:{hash:'#home'},
    requestAnimationFrame:fn => fn(), queueMicrotask() {}, clearTimeout() {}, clearInterval() {}, setInterval:() => 1,
    setTimeout:(fn, ms) => { timers.push([fn, ms]); return timers.length; }, document:{getElementById:() => null},
    locks:new Set(), state:{settings:{addons:[{name:'sync', active:true}]}}, addons:() => list, addonLabel:a => a?.name, URL, main:node(),
    fetch:async url => { fetched.push(url); return {ok:true, json:async () => ({state:'ok', view:{blocks:[]}})}; },
  });
  vm.runInContext(fs.readFileSync(path.join(PAGES, 'settings.js'), 'utf8'), c);
  return {c, fetched, timers};
}
const LIST = [
  {name:'automation', active:true, dashboard:{label:'Automation'}},
  {name:'insights', active:true, dashboard:{label:'Insights'}, page:{path:'/'}},
  {name:'sync', active:true, dashboard:{label:'Sync'}},
  {name:'phone', active:true},
];

test('fb22: the views of the add-ons that have one are fetched once in the background, not the pages', async () => {
  const {c, fetched, timers} = context(LIST);
  c.warmAddons();
  assert.deepEqual(fetched, [], 'nothing at once: the first screen comes first');
  assert.ok(timers.length, 'a later, quiet start');
  for (const [fn] of timers.splice(0)) await fn();
  for (const [fn] of timers.splice(0)) await fn();
  assert.deepEqual(fetched, ['/api/addon/automation']);
  c.warmAddons();
  assert.equal(timers.length, 0, 'only once per visit');
});

test('fb22: hovering a menu entry fetches that view when it is not there yet, and only then', async () => {
  const {c, fetched} = context(LIST);
  await c.warmAddonView('automation');
  await c.warmAddonView('automation');
  await c.warmAddonView('insights');
  assert.deepEqual(fetched, ['/api/addon/automation']);
});

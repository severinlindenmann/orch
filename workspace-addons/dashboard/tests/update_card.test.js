// Settings > About & updates: installed + newest release, what changed, one Update button, the steps, "Updated 15 → 16".
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');
const block = src.slice(src.indexOf('// ---- About & updates'), src.indexOf('// An agent that is started with a command'));
function node(tag, attrs = {}, children = []) {
  return {tag, attrs, children:children.flat(Infinity).filter(c => c != null && c !== false), dataset:{}, listeners:{},
    addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }};
}
const text = n => n == null ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join(' ').replace(/\s+/g, ' ').trim();
const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
function context(info) {
  const posts = [], listeners = {}, store = {};
  const c = vm.createContext({
    settingsTab:'about', h:(tag, attrs, ...kids) => node(tag, attrs || {}, kids), array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''), snapshot:false,
    settingsText:(tag, attrs, v) => node(tag, attrs || {}, [v]), render() {}, route:() => ({kind:'settings'}),
    button:(t, cls, fn) => { const b = node('button', {className:'btn ' + cls}, [t]); b.listeners.click = [fn]; return b; },
    sessionStorage:{getItem:k => store[k] ?? null, setItem:(k, v) => { store[k] = v; }},
    window:{addEventListener:(name, fn) => { listeners[name] = fn; }},
    fetch:async (url, opt) => url === '/api/update-info' ? {ok:true, json:async () => info}
      : (posts.push(JSON.parse(opt.body)), {status:202, text:async () => 'Update started.'}),
  });
  vm.runInContext(block, c);
  return {c, posts, fire:detail => listeners['orch-update-state']({detail})};
}
const INFO = {installed:{label:'orch 15', release:15}, newest:{label:'orch 16', release:16}, update_available:true,
  changes:['Helpers tidy up new tickets', 'Sync shows where your copy lives'], source:'https://github.com/o/orch (main)'};

test('shows installed, newest, what changed and one Update button', async () => {
  const {c} = context(INFO);
  c.aboutPanel(); await new Promise(r => setImmediate(r));  // first call loads, second call shows
  const view = c.aboutPanel(), t = text(view);
  assert.match(t, /Installed orch 15/); assert.match(t, /orch 16 is ready to install/);
  assert.match(t, /Helpers tidy up new tickets/); assert.match(t, /Sync shows where your copy lives/);
  const buttons = all(view, n => n.tag === 'button');
  assert.deepEqual(buttons.map(b => text(b)), ['Update to 16']);
});

test('up to date: no button; unknown newest says so plainly', async () => {
  let {c} = context({...INFO, update_available:false, changes:[]});
  c.aboutPanel(); await new Promise(r => setImmediate(r));
  assert.match(text(c.aboutPanel()), /You have the newest version/);
  assert.equal(all(c.aboutPanel(), n => n.tag === 'button').length, 0);
  ({c} = context({installed:{label:'orch 15'}, newest:null, update_available:false, changes:[]}));
  c.aboutPanel(); await new Promise(r => setImmediate(r));
  assert.match(text(c.aboutPanel()), /Could not check for a newer version/);
});

test('click posts update.start once, then steps, restart and "Updated 15 → 16"', async () => {
  const {c, posts, fire} = context(INFO);
  c.aboutPanel(); await new Promise(r => setImmediate(r));
  const [btn] = all(c.aboutPanel(), n => n.tag === 'button');
  await btn.listeners.click[0]();
  assert.deepEqual(posts, [{op:'update.start', args:{}}]);
  let t = text(c.aboutPanel());
  for (const s of ['Downloading', 'Installing', 'Restarting', 'Done']) assert.match(t, new RegExp(s));
  assert.equal(all(c.aboutPanel(), n => n.tag === 'button').length, 0, 'no second click while running');
  fire({state:'unreachable'});
  assert.equal(all(c.aboutPanel(), n => n.attrs['aria-current'] === 'step').length, 1);
  assert.match(text(all(c.aboutPanel(), n => n.attrs['aria-current'] === 'step')[0]), /Restarting/);
  const after = {installed:{label:'orch 16', release:16}, newest:{label:'orch 16', release:16}, update_available:false, changes:[]};
  c.fetch = async () => ({ok:true, json:async () => after});
  vm.runInContext('fetch = async () => ({ok:true, json:async () => (' + JSON.stringify(after) + ')})', c);
  fire({state:'finished'}); await new Promise(r => setImmediate(r));
  t = text(c.aboutPanel());
  assert.match(t, /Updated 15 → 16/);
});

test('a failed update says why in plain words and offers Try again', () => {
  const {c, fire} = context(INFO);
  fire({state:'failed', reason:'The download stopped.'});
  const t = text(c.aboutPanel());
  assert.match(t, /The update did not finish: The download stopped\. orch is still the old version\./);
  assert.deepEqual(all(c.aboutPanel(), n => n.tag === 'button').map(b => text(b)), ['Try again']);
});

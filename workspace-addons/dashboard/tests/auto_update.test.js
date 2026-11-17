// Automatic update: the switch in Settings > About & updates (off at first, a development build says it follows its
// branch) and the note on Home after it ran (new version and what changed, or a plain failure note).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const web = path.join(__dirname, '../src/orch_dashboard/web');
const settings = fs.readFileSync(path.join(web, 'pages/settings.js'), 'utf8');
const home = fs.readFileSync(path.join(web, 'pages/home.js'), 'utf8');
const app = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const between = (src, a, b) => src.slice(src.indexOf(a), src.indexOf(b, src.indexOf(a)));
function node(tag, attrs = {}, children = []) { return {tag, attrs, children:children.flat(Infinity).filter(c => c != null && c !== false)}; }
const text = n => n == null ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join(' ').replace(/\s+/g, ' ').trim();
const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];
const base = () => ({h:(tag, attrs, ...kids) => node(tag, attrs || {}, kids), array:v => Array.isArray(v) ? v : [], clean:v => String(v ?? ''),
  snapshot:false, settingsText:(tag, attrs, v) => node(tag, attrs || {}, [v]), settingsBusy:new Set(), render() {}});

function settingsCard(auto) {
  const c = vm.createContext(base());
  vm.runInContext(between(settings, '// Update automatically', 'async function autoUpdateSwitch') + '\nthis.card = autoUpdateCard;', c);
  return c.card(auto === undefined ? {} : {auto});
}

test('Settings: one switch, off at first, the owner’s words', () => {
  const view = settingsCard({on:false, ref:'main', branch:false});
  assert.match(text(view), /Update automatically when a new release is out/);
  assert.match(text(view), /never while a helper is working/);
  const sw = all(view, n => n.attrs?.role === 'switch');
  assert.equal(sw.length, 1); assert.equal(sw[0].attrs['aria-checked'], false); assert.equal(sw[0].attrs['data-action'], 'auto-update-set');
  assert.doesNotMatch(text(view), /development build/);
  assert.equal(all(view, n => n.tag === 'input').length, 0);  // a click, no typed words
});

test('Settings: a development build says plainly that it follows its branch', () => {
  const dev = text(settingsCard({on:true, ref:'develop', branch:true}));
  assert.match(dev, /development build: it gets every new change as soon as it is ready/); assert.doesNotMatch(dev, /branch|develop\b/i);
});

test('Settings: no card without data from orch', () => { assert.equal(settingsCard(undefined), null); });

test('the switch sends update.auto with the new value', () => {
  assert.match(app, /action === 'auto-update-set'\) \{ await autoUpdateSwitch\(\)/);
  assert.match(settings, /settingsSend\('update\.auto', \{on\}, 'auto-update'\)/);
});

function homeNote(note) {
  const c = vm.createContext({...base(), state:{auto_update_note:note}});
  vm.runInContext(between(home, 'function autoUpdateNote', '// "What changed"') + '\nthis.note = autoUpdateNote;', c);
  return c.note();
}

test('Home: after an automatic update, the new version and what changed, with Got it', () => {
  const view = homeNote({state:'updated', from:'orch 16', to:'orch 17', changes:['Helpers tidy up a new ticket', 'Sync shows where your copy lives']});
  assert.match(text(view), /orch updated itself to 17/);
  assert.deepEqual(all(view, n => n.tag === 'li').map(text), ['Helpers tidy up a new ticket', 'Sync shows where your copy lives']);
  assert.equal(all(view, n => n.attrs?.['data-action'] === 'auto-update-note-ok').length, 1);
});

test('Home: a failed update is a plain note and says it stays on the old version', () => {
  const t = text(homeNote({state:'failed', from:'orch 16', to:'orch 17', reason:'the download did not finish.'}));
  assert.equal(t.replace(/ Got it$/, ''), 'orch could not update itself to 17: the download did not finish. It is still 16 and tries again later.');
});

test('Home: nothing when there is no note', () => { assert.equal(homeNote(null), null); });

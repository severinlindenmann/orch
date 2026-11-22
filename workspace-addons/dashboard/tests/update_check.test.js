// The card on Home after an update whose short self-check failed (ORCH-551): what does not work, one button to go
// back to the release the update came from, and "Not now".
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const web = path.join(__dirname, '../src/orch_dashboard/web');
const home = fs.readFileSync(path.join(web, 'pages/home.js'), 'utf8');
const app = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const settings = fs.readFileSync(path.join(web, 'pages/settings.js'), 'utf8');
const between = (src, a, b) => src.slice(src.indexOf(a), src.indexOf(b, src.indexOf(a)));
function node(tag, attrs = {}, children = []) { return {tag, attrs, children:children.flat(Infinity).filter(c => c != null && c !== false)}; }
const text = n => n == null ? '' : typeof n === 'string' ? n : (n.children || []).map(text).join(' ').replace(/\s+/g, ' ').trim();
const all = (n, f) => !n || typeof n !== 'object' ? [] : [...(f(n) ? [n] : []), ...(n.children || []).flatMap(x => all(x, f))];

function card(c, snapshot = false) {
  const ctx = vm.createContext({h:(tag, attrs, ...kids) => node(tag, attrs || {}, kids), array:v => Array.isArray(v) ? v : [],
    clean:v => String(v ?? ''), snapshot, state:{update_check:c}});
  vm.runInContext(between(home, 'function updateCheckCard', '// "What changed"') + '\nthis.card = updateCheckCard;', ctx);
  return ctx.card();
}

test('a failed check after an update offers going back to the release before', () => {
  const view = card({at:1, release:33, back_to:32, failed:[{name:'Factory list', why:'the Factory list does not open'}]});
  assert.match(text(view), /After the update to 33 the Factory list does not open\. Go back to release 32\?/);
  const back = all(view, n => n.attrs?.['data-action'] === 'update-check-back');
  assert.equal(back.length, 1); assert.equal(back[0].attrs['data-to'], '32'); assert.equal(text(back[0]), 'Go back to 32');
  assert.equal(text(all(view, n => n.attrs?.['data-action'] === 'update-check-ok')[0]), 'Not now');
  assert.equal(all(view, n => n.tag === 'input').length, 0);  // one click, no typed words
});

test('a fix release can be gone back to', () => {
  const view = card({at:1, release:'33.1', back_to:33, failed:[{why:'x'}]});
  assert.match(text(view), /After the update to 33\.1 x\. Go back to release 33\?/);
});

test('several problems are listed in one card', () => {
  const view = card({at:1, release:33, back_to:32, failed:[{why:'a does not answer'}, {why:'b failed.'}]});
  assert.match(text(view), /these do not work: a does not answer; b failed\./);
});

test('without a release to go back to there is only Got it', () => {
  const view = card({at:1, release:32, back_to:null, failed:[{why:'the dashboard does not answer'}]});
  assert.equal(all(view, n => n.attrs?.['data-action'] === 'update-check-back').length, 0);
  assert.equal(text(all(view, n => n.attrs?.['data-action'] === 'update-check-ok')[0]), 'Got it');
  assert.doesNotMatch(text(view), /Go back/);
});

test('no card without a failed check, and no buttons in a copy', () => {
  assert.equal(card(null), null);
  assert.equal(card({at:1, failed:[]}), null);
  const copy = card({at:1, release:33, back_to:32, failed:[{why:'x'}]}, true);
  assert.equal(all(copy, n => n.tag === 'button').length, 0);
});

test('Go back starts the normal update with that release number; Not now dismisses', () => {
  const back = between(app, "action === 'update-check-back'", "action === 'auto-update-note-ok'");
  assert.match(back, /\^\[1-9\]\[0-9\]\{0,5\}\(\\\.\[1-9\]\[0-9\]\{0,3\}\)\?\$/); assert.match(back, /updStart\(to\)/); assert.match(back, /#settings\/about/);
  assert.match(app, /action === 'update-check-ok'\) \{ const r = await act\('update\.check\.dismiss'/);
  assert.match(between(settings, 'async function updStart', 'window.addEventListener'), /\^\[1-9\]\[0-9\]\{0,5\}\(\\\.\[1-9\]\[0-9\]\{0,3\}\)\?\$/);
  assert.match(home, /backgroundBanner\(\), updateCheckCard\(\), autoUpdateNote\(\)/);
});

test('a sign-in that failed names the page and what to do, never an answer code (report r-1122-0539)', () => {
  for (const why of ['insights sign-in failed (answer 403)', 'insights sign-in failed (answer none)']) {
    const view = card({at:1, release:40, back_to:null, failed:[{name:'Insights sign-in', why}, {why:'the usage page does not answer'}]});
    assert.match(text(view), /these do not work: Insights could not sign in; the usage page does not answer\. Report a problem Got it$/);
    assert.doesNotMatch(text(view), /answer \d|answer none|403|Restart/);
    assert.equal(text(all(view, n => n.attrs?.['data-action'] === 'update-check-report')[0]), 'Report a problem');
  }
    assert.equal(all(card({at:1, failed:[{why:'the usage page does not answer'}]}), n => n.attrs?.['data-action'] === 'update-check-report').length, 0);
  assert.match(app, /action === 'update-check-report'\) \{ reportOpen\(\); return; \}/);
});

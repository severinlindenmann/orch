const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');

const saveBody = () => { const i = src.indexOf("const save = button('Save repeat'"); return src.slice(i, src.indexOf('const refreshSummary', i)); };

// e2e 15 Nov (item 3/4): Save closes the dialog at once; the list shows the repeat as "Saving…" until it is stored
test('Save repeat closes the dialog before the request and shows a "Saving…" row', () => {
  const body = saveBody();
  const close = body.indexOf('window.orch.close(d)'), pend = body.indexOf('pendingRepeat = {title}'), call = body.indexOf("act('addon.act'");
  assert.ok(close > 0 && close < call, 'the dialog closes before the request');
  assert.ok(pend > close && pend < call, 'the pending row is set before the request');
  assert.match(src, /pendingRepeat\.title \+ ' · Saving…'/);
  assert.ok(body.indexOf('pendingRepeat = null') > call, 'the pending row ends with the answer');
});

// "Saving…" must always end: a lost or very slow answer gives a plain message after 30 s
test('Save repeat gives up waiting after 30 s and always clears the pending row', () => {
  const body = saveBody();
  assert.match(body, /Promise\.race\(\[act\('addon\.act'/);
  assert.match(body, /30000/);
  assert.match(body, /finally \{[^}]*pendingRepeat = null;/);
  assert.ok(body.indexOf('pendingRepeat = null') < body.indexOf('loadAddon('), 'the list reloads after the pending row ends');
});

// e2e 15 Nov: the reload after Save was dropped while a poll was loading, so the new row stayed missing until the next poll
test('a reload asked while another load is under way is queued, not dropped', () => {
  const i = src.indexOf('async function loadAddon');
  const body = src.slice(i, src.indexOf('// The view of an add-on tab costs', i));
  assert.match(body, /if \(addonBusy\.has\(id\)\) \{ addonAgain\.add\(id\); return; \}/);
  assert.match(body, /if \(addonAgain\.delete\(id\)\) await loadAddon\(id\);/);
});

// owner feedback 14 Nov: choosing Custom must start on a valid value (5 minutes), so Save is never disabled at the start
test('Custom starts at 5 minutes (the lowest allowed), never below the limit', () => {
  assert.match(src, /choice\.unit = choice\.unit \|\| 'minutes'; if \(choice\.unit === 'minutes' && !\(Number\(choice\.every\) >= 5\)\) choice\.every = 5;/);
  assert.match(src, /unit\.value === 'minutes' \? Math\.max\(5, Number\(choice\.every\) \|\| 5\)/);
});

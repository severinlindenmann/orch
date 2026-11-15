const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');

// owner feedback 14 Nov (W8): saving a schedule takes seconds; the button must say so, not only grey out
test('Save repeat shows "Saving…" while it works and restores its label after', () => {
  const i = src.indexOf("const save = button('Save repeat'");
  const body = src.slice(i, src.indexOf('const refreshSummary', i));
  const on = body.indexOf("'Saving…'"), call = body.indexOf("act('addon.act'"), back = body.indexOf('save.textContent = label');
  assert.ok(on > 0 && on < call, 'the label changes before the request');
  assert.ok(back > call, 'the label is restored after the answer');
});

// "Saving…" must always end: a lost or very slow answer gives a plain message after 30 s, the button comes back
test('Save repeat gives up waiting after 30 s and always restores the button', () => {
  const i = src.indexOf("const save = button('Save repeat'");
  const body = src.slice(i, src.indexOf('const refreshSummary', i));
  assert.match(body, /Promise\.race\(\[act\('addon\.act'/);
  assert.match(body, /30000/);
  assert.match(body, /finally \{[^}]*save\.disabled = false; save\.textContent = label;/);
  assert.ok(body.indexOf('window.orch.close(d)') < body.indexOf('loadAddon('), 'the dialog closes before the list reloads');
});

// owner feedback 14 Nov: choosing Custom must start on a valid value (5 minutes), so Save is never disabled at the start
test('Custom starts at 5 minutes (the lowest allowed), never below the limit', () => {
  assert.match(src, /choice\.unit = choice\.unit \|\| 'minutes'; if \(choice\.unit === 'minutes' && !\(Number\(choice\.every\) >= 5\)\) choice\.every = 5;/);
  assert.match(src, /unit\.value === 'minutes' \? Math\.max\(5, Number\(choice\.every\) \|\| 5\)/);
});

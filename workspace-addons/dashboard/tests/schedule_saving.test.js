const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const src = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/settings.js'), 'utf8');

// owner feedback 14 Nov (W8): saving a schedule takes seconds; the button must say so, not only grey out
test('Save schedule shows "Saving…" while it works and restores its label after', () => {
  const i = src.indexOf("const save = button('Save schedule'");
  const body = src.slice(i, src.indexOf('const refreshSummary', i));
  const on = body.indexOf("'Saving…'"), call = body.indexOf("act('addon.act'"), back = body.indexOf('save.textContent = label');
  assert.ok(on > 0 && on < call, 'the label changes before the request');
  assert.ok(back > call, 'the label is restored after the answer');
});

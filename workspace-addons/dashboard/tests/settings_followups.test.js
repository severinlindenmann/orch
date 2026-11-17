// ORCH-242: a turned-off add-on has no link and its address says so; limited fields show their limit; the report
// dialog keeps its text on Escape and its words match its ticks.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');
const read = name => fs.readFileSync(path.join(WEB, name), 'utf8');

test('an add-on that is off: the switch drops its link at once and its address says it is off', () => {
  const app = read('app.js');
  const sw = app.slice(app.indexOf("if (action === 'settings-addon')"), app.indexOf("if (action === 'addon-remove')"));
  assert.ok(sw.includes('state.addons = array(before).filter(a => a.name !== addon.name)'), 'link goes before the restart');
  assert.ok(sw.includes('state.addons = before'), 'a refused switch brings the link back');
  const off = app.slice(app.indexOf('function offAddonName'), app.indexOf('// Sidebar icons'));
  assert.ok(off.includes("'addon-off'") && off.includes(' is turned off'));
  assert.ok(off.includes('!row.active') && off.includes('!addons().some'), 'only an installed add-on that is not active');
});

test('the report dialog keeps what was typed when it closes without a report, and every field shows its limit', () => {
  const report = read('pages/report.js');
  assert.ok(report.includes('reportUi.draft = null'), 'a made report clears the draft');
  assert.ok(report.includes('happened.value = draft.happened') && report.includes('more.value = draft.more'));
  assert.ok(report.includes("input.value.length + ' / ' + input.maxLength"), 'a counter shows used / limit');
  assert.ok(!report.includes('Nothing is sent'), 'the words do not contradict the ticked boxes');
  assert.ok(report.includes('These two boxes only decide what goes into the saved report.'));
});

test('the workspace profile names its limits: name 60, description 280, tags 4 of 24', () => {
  const look = read('look.js');
  assert.ok(look.includes('up to 60 characters') && look.includes('Up to 280 characters'));
  assert.ok(look.includes('Up to four short words') && look.includes('Each up to 24 characters'));
});

test('add-on Details use plain words, not commands and processes', () => {
  const data = fs.readFileSync(path.join(WEB, '../data.py'), 'utf8');
  assert.ok(!data.includes('Adds the command') && !data.includes('Runs a background process'));
  assert.ok(data.includes('Keeps running in the background while it is on.'));
});

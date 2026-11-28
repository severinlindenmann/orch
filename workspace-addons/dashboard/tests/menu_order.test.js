// O-34: the menu's add-on pages keep the person's order, and no menu row edits the list any more.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const helpers = require('../src/orch_dashboard/web/helpers.js');
const WEB = path.join(__dirname, '../src/orch_dashboard/web');

test('O-34: the menu shows the chosen pages in the chosen order, without add-ons that are off now', () => {
  assert.deepEqual(helpers.menuShown(['skills', 'gone', 'factory', 'skills'], ['factory', 'files', 'skills']), ['skills', 'factory']);
  assert.deepEqual(helpers.menuShown(null, ['factory']), []);
});

test('O-34: one step up or down moves a page among the pages shown and keeps the others', () => {
  const names = ['a', 'b', 'c'];
  assert.deepEqual(helpers.menuStep(['a', 'off', 'b', 'c'], names, 'c', -1), ['a', 'off', 'c', 'b']);
  assert.deepEqual(helpers.menuStep(['a', 'off', 'b', 'c'], names, 'a', 1), ['off', 'b', 'a', 'c']);
  assert.deepEqual(helpers.menuShown(helpers.menuStep(['a', 'off', 'b', 'c'], names, 'a', 1), names), ['b', 'a', 'c']);
  assert.deepEqual(helpers.menuStep(['a', 'b', 'c'], names, 'b', 1), ['a', 'c', 'b']);
  // the first cannot go up, the last cannot go down, an unknown page moves nothing
  assert.deepEqual(helpers.menuStep(['a', 'b', 'c'], names, 'a', -1), ['a', 'b', 'c']);
  assert.deepEqual(helpers.menuStep(['a', 'b', 'c'], names, 'c', 1), ['a', 'b', 'c']);
  assert.deepEqual(helpers.menuStep(['a', 'b', 'c'], names, 'x', 1), ['a', 'b', 'c']);
});

test('O-34: the menu has no "Change this list" row; Settings has the Menu section; both ways to edit can be chosen', () => {
  const app = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8');
  assert.ok(!/Change this list/.test(app) && !/nav-change/.test(app), 'the row is gone');
  assert.match(app, /'Edit menu'/);
  assert.match(app, /function menuSettingsCard\(/);
  assert.match(fs.readFileSync(path.join(WEB, 'pages/settings.js'), 'utf8'), /menuSettingsCard\(\) : null/);
  assert.match(app, /Hide from menu/);
  assert.match(app, /Show in menu/);
});

test('O-35: the Settings icon comes from the master set and is a real gear, not the old blob', () => {
  const icons = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/icons.js'), 'utf8');
  assert.match(icons, /\n\s+settings: '<path d="M12\.22 2h/);
  const old = 'm9 3-1 3-3 1-2 3 2 2-1 4 3 2 3-1 3 3 3-1 1-4 3-2-1-4-3-1-1-3z';
  for (const f of ['app.js', 'index.html']) assert.ok(!fs.readFileSync(path.join(WEB, f), 'utf8').includes(old), f);
  for (const f of ['widgets.js', 'shell.html', 'gallery.html']) assert.ok(!fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static', f), 'utf8').includes(old), f);
});

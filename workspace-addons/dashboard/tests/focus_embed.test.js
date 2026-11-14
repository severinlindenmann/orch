// fb17: the Focus page fills the dashboard frame (no page padding, no max width) and has no header of its own.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', f), 'utf8');

test('the Focus frame is marked embed-shell and fills the page', () => {
  assert.match(web('pages/settings.js'), /embed-shell/);
  assert.match(web('style.css'), /\.page:has\(>iframe\.embed-shell\)\{max-width:none;padding:0\}/);
});

test('a page tells the dashboard it is the shell by message, not by the dashboard knowing its name', () => {
  assert.match(web('pages/settings.js'), /orch === 'embed-shell'/);
  assert.match(web('pages/settings.js'), /event\.origin === location\.origin/);
  assert.match(fs.readFileSync(path.join(__dirname, '../../focus/src/orch_focus/web/ticket.js'), 'utf8'), /postMessage\(\{orch: 'embed-shell'/);
});

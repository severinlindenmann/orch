// ORCH-186: the add-on frame asks for fullscreen one way only (no console warning), and a read refused for a
// missing sign-in (401) shows the same sign-in notice as a refused click (403).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', f), 'utf8');

test('the add-on frame sets allow=fullscreen without the old allowfullscreen attribute', () => {
  const frame = /function pageFrame[\s\S]*?\n}\n/.exec(web('pages/settings.js'))[0];
  assert.match(frame, /allow:'fullscreen'/);
  assert.doesNotMatch(frame, /allowfullscreen/i);
});

test('a 401 answer shows the sign-in notice too', () => {
  assert.match(web('session.js'), /r\.status === 401 \|\| r\.status === 403\) signInNotice\(r\)/);
});

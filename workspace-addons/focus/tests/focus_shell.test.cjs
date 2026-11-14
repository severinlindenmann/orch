// fb17 (owner 14 Nov): Focus inside the dashboard has no header of its own and one three-column shell:
// tickets left, the live session in the centre, one result panel right. Source contracts, like the other cjs tests.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_focus/web', f), 'utf8');

test('embedded Focus builds the shell: no Back to Home / crumb / Help bar, tickets left, one result panel', () => {
  const src = web('ticket.js');
  assert.match(src, /INAPP \? \[\] :/, 'the picker header is only for a stand-alone page');
  assert.match(src, /fx-shell/);
  assert.match(src, /Tickets in focus/);
  assert.match(src, /Result so far/);
  assert.match(src, /'\/api\/tickets'/);
});

test('decision buttons say Looks good / Send back and show only when done', () => {
  const src = web('ticket.js'), js = web('focus.js');
  assert.match(src, /Looks good/);
  assert.match(src, /Send back/);
  assert.doesNotMatch(src, /Ask for changes/);
  assert.match(js, /reviewBarShown/);
});

test('the shell uses master widgets and its CSS is one block on tokens', () => {
  assert.match(web('index.html'), /kit\/widgets\.css/);
  const css = web('focus.css');
  assert.match(css, /\.fx\.fx-shell\s/);
  assert.match(css, /\.fx-shell \.fx-top/);
  assert.doesNotMatch(css.slice(css.indexOf('.fx-shell')), /#[0-9a-fA-F]{3,6}\b/, 'no hex colours in the shell block');
});

test('embedded Focus forces the shell layout and hides the mode, full-screen and copy-link tools', () => {
  const js = web('focus.js');
  assert.match(js, /INAPP/);
  assert.match(js, /if \(INAPP\) \{ placeHuman\(true\)/);
  assert.match(web('ticket.js'), /INAPP \? null : els\.full/);
});

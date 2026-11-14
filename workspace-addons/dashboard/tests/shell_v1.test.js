// Owner feedback 14 Nov, lane v1: the frame, the ticket views as chips, the board, one empty state, dialogs.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const web = f => fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web', f), 'utf8');
const app = web('app.js'), tickets = web('pages/tickets.js');

test('sidebar has no Notes link and no Ticket views group', () => {
  assert.doesNotMatch(app, /navLink\('#notes'/);
  assert.doesNotMatch(app, /Ticket views/);
  assert.doesNotMatch(app, /nav-views/);
});
test('Contacts replaces "Phone & workspaces" everywhere in the product', () => {
  const toml = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch/builtin/relay/orch-addon.toml'), 'utf8');
  assert.match(toml, /label = "Contacts"/);
  assert.match(toml, /title = "Contacts"/);
  assert.doesNotMatch(web('pages/chat.js'), /Phone & workspaces/);
});
test('the Tickets page shows the views as chips with a save chip', () => {
  assert.match(tickets, /function viewChips\(/);
  assert.match(tickets, /Save view/);
  assert.match(tickets, /Done this week/);
  assert.doesNotMatch(tickets, /'Working now'/);
});
test('empty board columns collapse', () => {
  assert.match(tickets, /col-collapsed/);
});
test('ticket rows open the ticket on click', () => {
  assert.match(tickets, /row-click/);
});
test('filtered-empty uses the one empty-state component', () => {
  assert.match(tickets, /UI\.state\(/);
});
test('the page h1 equals the nav label for the top-level pages', () => {
  assert.match(tickets, /heading\('Tickets'/);
  assert.match(app, /pageName = .*'Tickets'/);
});
test('waiting requests are one quiet top-bar line', () => {
  assert.match(app, /topbar-wait/);
  assert.match(web('index.html'), /id="topbar-wait"/);
});
test('dialogs have one close button: the master removes a repeated plain Close', () => {
  const o = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/overlay.js'), 'utf8');
  assert.match(o, /one close button/);
  assert.match(o, /textContent\.trim\(\)==='Close'/);
});

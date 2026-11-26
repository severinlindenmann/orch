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
test('the Tickets page shows the views as chips (no save chip since ORCH-236)', () => {
  assert.match(tickets, /function viewChips\(/);
  assert.doesNotMatch(tickets, /Save view/);
  assert.match(tickets, /Done this week/);
  assert.doesNotMatch(tickets, /'Working now'/);
});
test('empty board rows are one line (ORCH-576)', () => {
  assert.match(tickets, /'status-row' \+ \(mine\.length \? '' : ' is-empty'\)/);
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
test('the top bar and the Menu button never repeat the needs-you number: only the Review badge has it (ORCH-1616)', () => {
  assert.doesNotMatch(app, /topbar-wait/);
  assert.doesNotMatch(web('index.html'), /topbar-wait/);
  assert.doesNotMatch(app, /'Menu · '/);
});
test('dialogs have one close button: the master removes a repeated plain Close', () => {
  const o = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/overlay.js'), 'utf8');
  assert.match(o, /one close button/);
  assert.match(o, /textContent\.trim\(\)==='Close'/);
});
test('Contacts is a top-level sidebar entry, not in the Add-ons fold-out', () => {
  assert.match(app, /contactsAddon \? navLink\(/);
  assert.match(app, /a\.dashboard && a\.dashboard\.panel !== 'phone'/);  // menuPages(): Contacts is not listed again under Add-ons
});
test('the master empty state is used for add-on blocks and Insights errors', () => {
  // Chat has no Earlier screen any more (ORCH-2171): earlier days come back by scrolling up in the same chat
  assert.match(web('blocks.js'), /window\.UI\.state/);
  assert.match(fs.readFileSync(path.join(__dirname, '../../insights/src/orch_insights/web/insights.js'), 'utf8'), /window\.UI\.state\(\{kind: 'error'/);
});
test('the add-on frame shows a skeleton until it has loaded', () => {
  assert.match(web('pages/settings.js'), /embed-skeleton/);
});
test('ticket list group headers carry the group action', () => {
  assert.match(tickets, /group-action/);
});

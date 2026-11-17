const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const kit = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/components.css'), 'utf8');
const style = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/style.css'), 'utf8');

// persona tests F1-F3: look fixes that only CSS can show; the pictures are on the ticket.
test('F1: on a wide screen the top bar stays on one row and the page name gives way first', () => {
  assert.match(kit, /@media\(min-width:900px\)\{\.topbar\{flex-wrap:nowrap\}\.topbar>\*\{flex-shrink:0\}\.topbar>\.breadcrumb\{flex-shrink:1;min-width:0\}\}/);
  assert.match(style, /\.breadcrumb>#updated\{flex-shrink:20\}/);
});
test('F2: an empty row in a page adds no 24 px gap above the title', () => {
  assert.match(kit, /\.page>\.stack:empty\{display:none\}/);
});
test('F3: a wrapped button is pushed in only after a leading icon, never on a row that starts with its text', () => {
  assert.match(kit, /\.card-row:has\(>:first-child:not\(\.grow\)\)>\.btn\{margin-left:24px\}/);
  assert.doesNotMatch(kit, /\n\.card-row>\.btn\{margin-left:24px\}/);
});

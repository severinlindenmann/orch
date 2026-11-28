const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const read = p => fs.readFileSync(path.join(__dirname, p), 'utf8');
const ticket = read('../src/orch_dashboard/web/pages/ticket.js');
const css = read('../../../workspace/src/orch_ui/static/widgets.css'), kit = read('../../../workspace/src/orch_ui/static/review.js');

// ORCH-294: a Review card shows its pictures side by side, full width, readable, and long text folds.
test('card pictures fill the row side by side at a readable size', () => {
  assert.match(css, /\.decision-shown\{display:grid;grid-template-columns:repeat\(auto-fit,minmax\(min\(320px,100%\),1fr\)\)/);
  assert.match(css, /\.decision-shot \.opt-thumb\{height:clamp\(216px,24vw,360px\)/);
});
test('long card text folds behind Show more / Show less', () => {
  assert.match(kit, /UI\.moreText=/);
  assert.match(kit, /'Show more'/);
  assert.match(kit, /'Show less'/);
  assert.match(ticket, /window\.UI\.moreText\(clean\(card\.why\)\)/);
  assert.match(css, /\.more-text\.clamped>p\{display:-webkit-box;-webkit-line-clamp:3/);
});
test('tiles open large on click', () => {
  assert.match(kit, /UI\.reviewViewer\(out\.map/);
});

// ORCH-408: a check card shows its detail plainly lower down, never behind a Details toggle (owner rule).
test('the card document shows details as plain text, not a Details toggle', () => {
  const kitJs = read('../../../workspace/src/orch_ui/static/widgets.js');
  assert.match(kitJs, /el\('div','doc-details'\)/);
  assert.doesNotMatch(kitJs, /el\('details','doc-details'\)/);
  assert.doesNotMatch(kitJs, /el\('summary','','Details'\)/);
});

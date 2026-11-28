const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const review = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/review.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8');

const kit = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.js'), 'utf8');
// persona test F4: the "All cards" list cut every title to one line, so cards looked repeated. O-05 (28 Nov): the
// page draws the list (compact rows, the kit's .review-queue-row); a row shows its title up to two lines, the whole
// title on hover.
test('a list row shows the whole title on hover and wraps to two lines instead of one cut line', () => {
  assert.match(review, /review-queue-row[^\n]*title:clean\(x\.it\.title\)/);
  assert.match(kit, /r\.dataset\.item=it\.id;r\.title=it\.title;/);
  const rule = css.split('\n').find(l => l.startsWith('.review-queue-row>.review-queue-title{'));
  assert.ok(rule);
  assert.match(rule, /-webkit-line-clamp:2/);
  assert.doesNotMatch(rule, /white-space:nowrap/);
});

// ORCH-246 named the ticket key on every row; round 2 (owner sent back, 18 Nov) moves the ticket to the group header
// (its name) and the card's meta line (its key), so a row is the card's own title.
test('a list row is grouped under its ticket and the card names its key in its meta line', () => {
  assert.match(kit, /const groupOf=it=>it\.laneName\|\|it\.group\|\|it\.ticketTitle\|\|it\.ticket\|\|''/);  // a lane (Review, 25 Nov) first
  assert.match(kit, /if\(it\.ticket\)m\.append\(el\('span','swipe-key',it\.ticket\)\)/);
});

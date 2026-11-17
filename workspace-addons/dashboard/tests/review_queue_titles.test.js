const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const review = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/review.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8');

// persona test F4: the "All cards" list cut every title to one line, so cards looked repeated.
test('a queue row shows the whole title on hover and wraps to two lines instead of one cut line', () => {
  assert.match(review, /title\.title = label/);
  const rule = css.split('\n').find(l => l.startsWith('.review-queue-row>.review-queue-title'));
  assert.ok(rule);
  assert.match(rule, /-webkit-line-clamp:2/);
  assert.doesNotMatch(rule, /white-space:nowrap/);
});

// ORCH-246: every row of the list names its ticket key, and Home's card row says the key and what it asks.
test('a queue row starts with the ticket key', () => {
  assert.match(review, /\[it\.ticket, it\.title\]\.filter\(Boolean\)\.join\(' · '\)/);
});
test("Home's card row shows the ticket key and, for one card, what it asks", () => {
  const home = fs.readFileSync(path.join(__dirname, '../src/orch_dashboard/web/pages/home.js'), 'utf8');
  assert.match(home, /keyTag\(t, h\), title/);
  assert.match(home, /one\.card\?\.title \|\| shortQuestion\(one\.text\)/);
});

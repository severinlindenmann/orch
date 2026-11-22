// Review card frame (ORCH-1467, report r-1122-0539-t_e02kil): the deck's keyboard ring touched the card and the counter
// line, the cards behind a short Stuck card peeked out under it, and Merge / Start helper hung loose below the card.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const css = fs.readFileSync(path.join(__dirname, '../../../workspace/src/orch_ui/static/widgets.css'), 'utf8');
const rule = sel => { const i = css.lastIndexOf(sel + '{'); assert.ok(i >= 0, 'no rule for ' + sel); return css.slice(i, css.indexOf('}', i) + 1); };

test('the review deck has space inside its frame', () => {
  assert.match(rule('.swipe-desk'), /padding:var\(--s3\)/);
});

test('cards behind a short card are not drawn', () => {
  const r = css.split('\n').find(l => l.includes('>.swipe-card.under2{display:none}') && l.includes('.swipe-card.short'));
  assert.ok(r, 'under cards must be hidden while the top card is short');
});

test('a card\'s own answer buttons sit in a footer joined to the card', () => {
  const l = css.split('\n').find(l => l.includes('+ .swipe-actions:has(>.swipe-own:not([hidden]))'));
  assert.ok(l, 'footer rule');
  assert.match(l, /margin-top:calc\(-1 \* var\(--s4\)\)/);
  assert.match(l, /border:1px solid var\(--border\)/);
});

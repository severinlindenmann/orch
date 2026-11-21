import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../static/widgets.css', import.meta.url), 'utf8');

// ORCH-137: a long question on a Review card must be readable at 390.
// The head may only be capped when a picture preview below needs the room;
// with plain answers or no preview it takes all the space left and the answers follow it.
test('review card head is capped only above a picture preview', () => {
  assert.doesNotMatch(css, /\.swipe-head\{max-height:45%/);
  assert.match(css, /\.swipe-head:has\(\+ \.swipe-preview:not\(\.plain\)\)\{max-height:45%\}/);
  assert.match(css, /\.swipe-head\{min-height:0;overflow:auto\}/);
});

test('a cut copy of the question is not shown above the full question', () => {
  const js = readFileSync(new URL('../static/widgets.js', import.meta.url), 'utf8');
  // the title shows only when the question is not cut (ORCH-421: it also carries the whole title on hover)
  assert.match(js, /if\(!cut\)\{const t3=el\('h3','',it\.title\);t3\.title=it\.title;h\.append\(t3\)\}/);
  assert.match(js, /it\.text&&\(cut\|\|it\.text!==it\.title\)/);
});

// ORCH-329: a doc box leads with a headline, bar, chips, flow, chart or diff; long text sits behind Details.
test('doc box draws the glance formats and folds long text', () => {
  const js = readFileSync(new URL('../static/widgets.js', import.meta.url), 'utf8');
  for (const k of ['doc-headline', 'doc-progress', 'doc-chips', 'doc-flow', 'doc-chart', 'doc-diff', 'doc-details']) assert.match(js, new RegExp(k));
  assert.match(css, /\.doc-details summary/);
});

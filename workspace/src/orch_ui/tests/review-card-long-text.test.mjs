import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../static/widgets.css', import.meta.url), 'utf8');

// ORCH-137: a long question on a Review card must be readable at 390. ORCH-477 (owner pick B): the card is as tall as
// what it holds at every width, so the head is never capped and there is no fixed card frame any more.
test('review card head is never capped and the card has no fixed frame', () => {
  assert.doesNotMatch(css, /\.swipe-head[^{]*\{[^}]*max-height:45%/);
  assert.match(css, /\.swipe-head\{min-height:0\}/);
  assert.doesNotMatch(css, /--swipe-card-h/);
  assert.match(css, /\.swipe-stage>\.swipe-card\{position:relative;inset:auto;overflow:visible/);
});
test('the answers bar is pinned to the bottom of the screen and holds the "If you approve" line (ORCH-477)', () => {
  assert.match(css, /\.swipe-actions\{position:sticky;bottom:0;/);
  assert.match(css, /\.swipe-bar-then\{order:-1;flex:1 1 100%/);
  assert.match(css, /body:has\(>\.tabbar\) \.swipe-actions\{bottom:calc\(var\(--touch\) \+ env\(safe-area-inset-bottom\)\)\}/);
});
test('the All cards list stays beside the deck below 1440 px and folds away only on a phone (ORCH-477)', () => {
  assert.doesNotMatch(css, /max-width:1439px/);
  assert.match(css, /@media \(max-width:720px\)\{\.review-layout\{grid-template-columns:minmax\(0,1fr\)\}\.review-side\{display:none\}\}/);
  assert.match(css, /\.review-layout\{display:grid;grid-template-columns:var\(--panel-width\) minmax\(0,1fr\)/);
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

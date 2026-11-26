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
// ORCH-2113: one card alone leaves the All cards list empty (deck.drawList draws nothing for a lone card); the rail
// then folds away and the page is one column, as for an empty Review (ORCH-2024), not only when the deck is empty.
test('an empty All cards list with nothing else in the rail leaves no empty left column, with or without cards', () => {
  assert.match(css, /\n\.review-layout>\.review-rail:has\(>\.review-side:only-child>\.review-queue:empty\)\{display:none\}/);
  assert.match(css, /\n\.review-layout:not\(\.with-ticket\):has\(>\.review-rail>\.review-side:only-child>\.review-queue:empty\)\{grid-template-columns:minmax\(0,1fr\)\}/);
});

test('a cut copy of the question is not shown above the full question', () => {
  const js = readFileSync(new URL('../static/widgets.js', import.meta.url), 'utf8');
  // the title shows only when the question is not cut (ORCH-421: it also carries the whole title on hover)
  // round 2 (ORCH-477): title first, then the one meta line; a cut title gives its place to the whole question
  assert.match(js, /if\(!cut\)\{const t3=el\('h3','',it\.title\);t3\.title=it\.title;h\.append\(t3,m\);if\(it\.text&&it\.text!==it\.title\)/);
  assert.match(js, /else h\.append\(el\('p','swipe-text swipe-lead',it\.text\),m\)/);
});

// ORCH-329: a doc box leads with a headline, bar, chips, flow, chart or diff; long text sits behind Details.
test('doc box draws the glance formats and folds long text', () => {
  const js = readFileSync(new URL('../static/widgets.js', import.meta.url), 'utf8');
  for (const k of ['doc-headline', 'doc-progress', 'doc-chips', 'doc-flow', 'doc-chart', 'doc-diff', 'doc-details']) assert.match(js, new RegExp(k));
  assert.match(css, /\.doc-details summary/);
});

// ORCH-477 round 2 (owner sent back): where the "All cards" list shows beside the deck, the deck's own "All" button
// goes (it repeated the list); a phone keeps it. Files sit in equal boxes: 2 columns, 3 from 1600 px, 1 on a phone,
// 2 on each Compare side; a picture is contained, never stretched past its own size.
test('the All button hides where the list shows; files take 2 / 3 / 1 columns and never crop or blow up', () => {
  assert.match(css, /@media \(min-width:721px\)\{\.review-layout \.swipe-top>\.swipe-all\{display:none\}\}/);
  assert.match(css, /\.swipe-card \.swipe-files\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /@media \(min-width:1600px\)\{\.swipe:not\(\.pairing\) \.swipe-card \.swipe-files\{grid-template-columns:repeat\(3,minmax\(0,1fr\)\)\}/);
  assert.ok(css.includes('\n .swipe-card .swipe-files{grid-template-columns:minmax(0,1fr);'), 'one column on a phone');
  assert.match(css, /\.swipe-files \.swipe-file-thumb>img\{display:block;width:auto;height:auto;max-width:100%;max-height:100%;object-fit:contain\}/);
});
test('no green frame: a programmatic focus of the deck shows no ring, the current list row is tinted with a mint edge', () => {
  assert.match(css, /\.swipe\.quiet-focus:focus-visible\{box-shadow:none\}/);
  assert.match(css, /\.review-row\.is-current\{background:var\(--brand-soft\);box-shadow:inset 3px 0 0 var\(--brand\)\}/);
  assert.match(css, /prefers-reduced-motion:reduce\)\{\.review-row,\.swipe-files \.swipe-file-thumb\{transition:none\}\}/);
});

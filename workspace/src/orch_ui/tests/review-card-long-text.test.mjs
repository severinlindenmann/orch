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

// The click-through of the new Focus (e2e/focus_d, ORCH-265): every part the owner listed has a step, every step says
// what to do, what must be seen and its picture, pending steps say what they wait for, and CLICKTHROUGH.md is current.
// No browser here; the CI job page-smoke clicks the ready steps.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const DIR = path.join(__dirname, '..', '..', '..', 'e2e', 'focus_d');
const { STEPS, AREAS, SIZES, WIDGETS } = require(path.join(DIR, 'steps.cjs'));
const { markdown } = require(path.join(DIR, 'clickthrough.cjs'));

test('every part the owner listed has at least one step', () => {
  for (const area of AREAS) assert.ok(STEPS.some(s => s.area === area), `no step for ${area}`);
  for (const s of STEPS) assert.ok(AREAS.includes(s.area), `step ${s.n} has an unknown part ${s.area}`);
});

test('every draft D feature (1 to 13) is in a step, and all 16 widget kinds are named', () => {
  const seen = new Set(STEPS.flatMap(s => s.feature));
  for (let n = 1; n <= 13; n++) assert.ok(seen.has(n), `draft D feature ${n} has no step`);
  assert.equal(WIDGETS.length, 16);
  const widgetStep = STEPS.find(s => s.area === '16 widgets').see.join(' ');
  for (const w of WIDGETS) assert.ok(widgetStep.includes(w), `widget ${w} is not in the widget step`);
});

test('steps are numbered 1..n with unique picture names and four widths (1440 and 390 for the owner)', () => {
  STEPS.forEach((s, i) => assert.equal(s.n, i + 1, `step ${s.pic} is numbered ${s.n}`));
  const pics = STEPS.map(s => s.pic);
  assert.equal(new Set(pics).size, pics.length, 'picture names repeat');
  for (const k of pics) assert.match(k, /^fd-\d\d-[a-z0-9-]+$/);
  assert.deepEqual(SIZES.map(([w]) => w), [1280, 1440, 1920, 390]);
});

test('every step says what to do and what must be seen; a step is either clickable or waits for a named task', () => {
  for (const s of STEPS) {
    assert.ok(s.title && s.do.length && s.see.length, `step ${s.n} is missing words`);
    if (s.waits) assert.ok(typeof s.waits === 'string' && s.waits.length > 5, `step ${s.n} waits for nothing`);
    else assert.equal(typeof s.run, 'function', `step ${s.n} is ready but has no run`);
    if (s.area !== 'start') assert.ok(s.draft && typeof s.draft.q === 'string', `step ${s.n} has no draft D picture`);
  }
});

test('counts in the words read right ("1 session", never "1 sessions")', () => {
  const words = STEPS.flatMap(s => [s.title, ...s.do, ...s.see]).join('\n');
  assert.doesNotMatch(words, /\b1 [a-z]+s\b(?<!\b1 (?:is|was|has|does|goes|says))/);
});

test('CLICKTHROUGH.md is current (node e2e/focus_d/clickthrough.cjs --write-md)', () => {
  assert.equal(fs.readFileSync(path.join(DIR, 'CLICKTHROUGH.md'), 'utf8'), markdown() + '\n');
});

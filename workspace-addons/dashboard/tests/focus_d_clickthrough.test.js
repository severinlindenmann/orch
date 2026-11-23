// The click-through of the new Focus (e2e/focus_d, ORCH-265): every part the owner listed has a step, every step says
// what to do, what must be seen and its picture, pending steps say what they wait for, and CLICKTHROUGH.md is current.
// No browser here; the CI job page-smoke clicks the ready steps (in two parts, --shard).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const DIR = path.join(__dirname, '..', '..', '..', 'e2e', 'focus_d');
const { STEPS, AREAS, SIZES, WIDGETS } = require(path.join(DIR, 'steps.cjs'));
const { markdown, pick, args } = require(path.join(DIR, 'clickthrough.cjs'));

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

test('--shard k/n: the parts click every ready step exactly once, evenly, and only part 1 lists the pending ones (ORCH-1654)', () => {
  const ready = STEPS.filter(s => !s.waits && s.run).map(s => s.n);
  const parts = [1, 2].map(k => pick(args(['--shard', `${k}/2`])));
  assert.deepEqual(parts.flatMap(p => p.todo.map(s => s.n)).sort((a, b) => a - b), ready);
  assert.ok(Math.abs(parts[0].todo.length - parts[1].todo.length) <= 1);
  const rest = STEPS.filter(s => !ready.includes(s.n)).map(s => s.n);
  assert.deepEqual(parts[0].listed.filter(s => !ready.includes(s.n)).map(s => s.n), rest);
  assert.deepEqual(parts[1].listed.map(s => s.n), parts[1].todo.map(s => s.n));
  assert.deepEqual(pick(args([])).todo.map(s => s.n), ready);
  for (const bad of ['0/2', '3/2', '2', 'x/y']) assert.throws(() => args(['--shard', bad]), /--shard/);
});

test('CI runs every part of the page smoke, each with a time guard under its job limit (ORCH-1654)', () => {
  const smoke = fs.readFileSync(path.join(DIR, '..', 'focus_insights_smoke.cjs'), 'utf8');
  const focusParts = Number(/const FOCUS_PARTS = (\d+);/.exec(smoke)[1]);
  const want = ['pages', ...Array.from({ length: focusParts }, (_, i) => `focus-${i + 1}`)];
  for (const wf of ['addons.yml', 'ci.yml']) {
    const text = fs.readFileSync(path.join(DIR, '..', '..', '.github', 'workflows', wf), 'utf8');
    const job = text.slice(text.indexOf('\n  page-smoke:\n'), text.indexOf('\n  page-smoke:\n') + 3000);
    assert.deepEqual(/part: \[([^\]]+)\]/.exec(job)[1].split(',').map(x => x.trim()), want, wf);
    assert.match(job, /run: node e2e\/focus_insights_smoke\.cjs --part \$\{\{ matrix\.part \}\}/, wf);
    const limit = Number(/timeout-minutes: (\d+)/.exec(job)[1]) * 60;
    const budget = Number(/SMOKE_BUDGET_S: (\d+)/.exec(job)[1]);
    assert.ok(budget > 0 && budget <= limit - 90, `${wf}: SMOKE_BUDGET_S ${budget} leaves no room for the setup steps`);
  }
});

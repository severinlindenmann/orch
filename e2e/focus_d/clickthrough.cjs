#!/usr/bin/env node
// The click-through of the new Focus (draft D, ORCH-261). The steps live in e2e/focus_d/steps.cjs.
//
//   node e2e/focus_d/clickthrough.cjs [--out DIR]               ready steps in the real dashboard, pending ones listed
//   node e2e/focus_d/clickthrough.cjs --target draft [--repo P] the reference pictures of every step in the draft D mockup
//   node e2e/focus_d/clickthrough.cjs --only 1,2,9               only these step numbers
//   node e2e/focus_d/clickthrough.cjs --only 18 --video          also a recording of each step: <out>/<picture>-<width>.webm
//   node e2e/focus_d/clickthrough.cjs --list                     print the click-through, no browser
//   node e2e/focus_d/clickthrough.cjs --write-md                 write e2e/focus_d/CLICKTHROUGH.md from the steps
//   node e2e/focus_d/clickthrough.cjs --axe [axe.min.js]         also run axe-core on every step and width: a serious or
//                                                                critical finding fails the step (ORCH-1360). Found in
//                                                                AXE_CORE_JS, PW_DIR or e2e/full/web/node_modules.
//
// Dashboard target: the real dashboard server and today's Focus server, each on fake data in a throw-away home under
// ~/.orch-test, started with `env -i` (HOME, USERPROFILE and ORCH_HOME in that folder, ORCH_HOME_STRICT=1), so the
// orch of this computer is never touched. Chromium runs in a fresh context (no profile folder) with --use-mock-keychain
// --password-store=basic (no keychain window). Pictures: <out>/<step picture>-<width>.png (draft: <key>-<width>-draft.png),
// plus <out>/report.md. Exit 0 = every ready step passed at every width; pending steps never fail the run.
'use strict';
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const headless = require('../headless.cjs'); // the keychain options (ORCH-615)
const { spawn, execFileSync } = require('node:child_process');
const { STEPS, SIZES } = require('./steps.cjs');

const REPO = path.resolve(__dirname, '..', '..');
const MD = path.join(__dirname, 'CLICKTHROUGH.md');
const MOCKUP = 'workspace-addons/dashboard/mockup/focus/focus-v4d.html';
// Runs in the page: the filled buttons a person sees on the screen (UX checklist B2: one at most, as in draft D).
const FILLED = () => [...document.querySelectorAll('.btn.primary')].filter(b => {
  const r = b.getBoundingClientRect(), cs = getComputedStyle(b);
  return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
}).map(b => `"${(b.getAttribute('aria-label') || b.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40)}"`);

function args(argv) {
  const o = { target: 'dashboard', out: path.join(os.tmpdir(), 'focus-d-clickthrough'), repo: REPO, only: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--list') o.list = true;
    else if (a === '--write-md') o.writeMd = true;
    else if (a === '--target') o.target = argv[++i];
    else if (a === '--out') o.out = path.resolve(argv[++i].replace(/^~/, os.homedir()));
    else if (a === '--repo') o.repo = path.resolve(argv[++i].replace(/^~/, os.homedir()));
    else if (a === '--only') o.only = new Set(argv[++i].split(',').map(Number));
    else if (a === '--video') o.video = true;
    else if (a === '--axe') o.axe = argv[i + 1] && !argv[i + 1].startsWith('--') ? path.resolve(argv[++i]) : 'find';
    else throw new Error(`unknown option ${a}`);
  }
  if (!['dashboard', 'draft'].includes(o.target)) throw new Error(`--target is dashboard or draft, not ${o.target}`);
  return o;
}

const shot = (s, w, draft) => `${s.pic}-${w}${draft ? '-draft' : ''}.png`;

/** The click-through as Markdown: what testers read, and what --write-md keeps in the repo. */
function markdown() {
  const ready = STEPS.filter(s => !s.waits).length;
  const out = [
    '# Click-through: the new Focus (draft D)',
    '',
    'Generated from `e2e/focus_d/steps.cjs` by `node e2e/focus_d/clickthrough.cjs --write-md`; do not edit by hand.',
    `${STEPS.length} steps: ${ready} ready (the script clicks them), ${STEPS.length - ready} pending (not built yet).`,
    '',
    'For every step take one picture at each width: ' + SIZES.map(([w]) => w).join(', ') + '. The name is given per step;',
    'the runner saves them as `<name>-<width>.png`, and `--target draft` saves the draft D picture beside it as',
    '`<name>-<width>-draft.png`.',
    '',
    'How to run: see `e2e/focus_d/README.md`.',
    '',
  ];
  for (const s of STEPS) {
    out.push(`## ${s.n}. ${s.title}`, '');
    out.push(`- Part: ${s.area}${s.feature.length ? ` (draft D feature ${s.feature.join(', ')})` : ''}`);
    out.push(`- State: ${s.waits ? `pending, waits for: ${s.waits}` : 'ready, clicked by the script'}`);
    if (s.reduce) out.push('- Reduced motion on for this step.');
    out.push(`- Pictures: ${SIZES.map(([w]) => '`' + shot(s, w) + '`').join(', ')}`, '');
    out.push('Do:', '', ...s.do.map((x, i) => `${i + 1}. ${x}`), '');
    out.push('Must be seen:', '', ...s.see.map(x => `- ${x}`), '');
  }
  return out.join('\n');
}

function playwright() {
  for (const p of [process.env.PW_DIR, path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules')]) {
    if (p) try { return require(path.join(p, 'playwright')); } catch (e) { /* next */ }
  }
  try { return require('playwright'); } catch (e) { /* global */ }
  return require(path.join(execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), 'playwright'));
}

const freePort = () => new Promise((ok, no) => {
  const s = net.createServer();
  s.once('error', no);
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); });
});

/** A fixture server in its own throw-away home. Resolves { base, stop }; stop kills only this child and its folder. */
async function serve(project, script, tag) {
  const root = path.join(os.homedir(), '.orch-test');
  fs.mkdirSync(root, { recursive: true });
  const dir = fs.mkdtempSync(path.join(root, `${tag}-`));
  const port = await freePort();
  const env = { HOME: dir, USERPROFILE: dir, ORCH_HOME: path.join(dir, 'orch'), ORCH_HOME_STRICT: '1', PATH: process.env.PATH,
    UV_CACHE_DIR: process.env.UV_CACHE_DIR || path.join(os.homedir(), '.cache', 'uv') };
  const child = spawn('env', ['-i', ...Object.entries(env).map(([k, v]) => `${k}=${v}`),
    'uv', 'run', '--project', project, 'python', script, dir, String(port)], { cwd: REPO, stdio: ['ignore', 'pipe', 'pipe'] });
  let log = '';
  child.stderr.on('data', d => { log += d; });
  const stop = () => {
    try { process.kill(child.pid); } catch (e) { /* gone */ }
    if (path.dirname(dir) === root && path.basename(dir).startsWith(`${tag}-`)) fs.rmSync(dir, { recursive: true, force: true });
  };
  try {
    await new Promise((ok, no) => {
      child.stdout.on('data', d => { if (String(d).includes('ready')) ok(); });
      child.once('exit', c => no(new Error(`${tag} server exited (${c}): ${log.slice(-800)}`)));
      setTimeout(() => no(new Error(`${tag} server did not start: ${log.slice(-800)}`)), 120000);
    });
  } catch (e) { stop(); throw e; }
  return { base: `http://127.0.0.1:${port}`, stop };
}

// axe-core for --axe: the file given, AXE_CORE_JS, or the package next to Playwright / in e2e/full/web.
function axeSource(want) {
  if (want !== 'find') return fs.readFileSync(want, 'utf8');
  if (process.env.AXE_CORE_JS) return fs.readFileSync(process.env.AXE_CORE_JS, 'utf8');
  const paths = [process.env.PW_DIR, path.join(REPO, 'e2e/full/web/node_modules'), REPO].filter(Boolean);
  try { return fs.readFileSync(require.resolve('axe-core/axe.min.js', { paths }), 'utf8'); } catch (e) {
    throw new Error('--axe: axe-core not found (npm i axe-core@4.10.2 in e2e/full/web, or set AXE_CORE_JS)');
  }
}

// Serious and critical axe-core findings on the page as it is now, one line each.
async function axeProblems(page, src) {
  await page.evaluate(src);  // evaluate, not a script tag: the dashboard's content policy refuses inline scripts
  const found = await page.evaluate(async () => (await window.axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'] }))
    .violations.filter(v => v.impact === 'serious' || v.impact === 'critical')
    .map(v => `axe ${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(', ')}`));
  return found;
}

/** ORCH-1359: a toast never covers the Focus bar or a layer's message box (draft D). Returns a problem or ''. */
async function toastCovers(page) {
  return page.evaluate(() => {
    const seen = el => { const r = el.getBoundingClientRect(); return r.width && r.height && getComputedStyle(el).visibility !== 'hidden' ? r : null; };
    const meet = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    for (const t of document.querySelectorAll('#ui-toasts .ui-toast')) {
      const tr = seen(t); if (!tr) continue;
      for (const el of document.querySelectorAll('#live-bar, .live-bar, .live-msg')) {
        const r = seen(el);
        if (r && meet(tr, r)) return `a toast ("${t.textContent.slice(0, 60)}") covers ${el.matches('.live-msg') ? 'the message box' : 'the Focus bar'}`;
      }
    }
    return '';
  });
}

/** One step at one width. Returns a list of problems (empty = passed). */
async function runOne(ctx, step, [w, h], o, urls) {
  const page = await ctx.newPage();
  const problems = [];
  page.on('pageerror', e => problems.push(`page error: ${String(e.message).slice(0, 200)}`));
  // a step may name console lines it causes on purpose (okConsole: a refusal the page shows as a plain message)
  // a failed address is named, so a "Failed to load resource" console line can be traced to its request
  page.on('response', r => { if (r.status() >= 400 && !(step.okConsole && step.okConsole.test(`status of ${r.status()}`))) problems.push(`failed request: ${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, '')}`); });
  page.on('console', m => { if (m.type() === 'error' && !(step.okConsole && step.okConsole.test(m.text()))) problems.push(`console error: ${m.text().slice(0, 200)}`); });
  try {
    // The steps dress the page's state (/api/state) with their stand-in data. A poll that holds a revision gets only
    // what changed (ORCH-517), and that answer cannot be dressed: once the test server's own settings move, the page
    // would take them (Preview off) a few minutes into the run. So the page always asks for the whole state here.
    // (set on the browser, so a second tab a step opens asks the same way: see main)
    await page.setViewportSize({ width: w, height: h });
    if (step.reduce) await page.emulateMedia({ reducedMotion: 'reduce' });
    if (o.target === 'draft') {
      await page.goto(urls.draft + step.draft.q);
      await page.waitForSelector('body[data-mw-boot], #mw-page *', { state: 'attached', timeout: 10000 });
      if (step.draft.act) await step.draft.act(page);
    } else {
      await step.run({ page, dash: urls.dash, width: w });
    }
    await page.waitForTimeout(400); // let any move end before the picture
    if (o.target !== 'draft') { const hit = await toastCovers(page); if (hit) problems.push(hit); }
    // one filled button on a screen, as in draft D (UX checklist B2, ORCH-1357): built and draft alike
    const filled = await page.evaluate(FILLED);
    if (filled.length > 1) problems.push(`${filled.length} filled buttons on one screen: ${filled.join(', ')}`);
    await page.screenshot({ path: path.join(o.out, shot(step, w, o.target === 'draft')), fullPage: false });
    if (o.axeSrc) problems.push(...await axeProblems(page, o.axeSrc));
  } catch (e) {
    problems.push(String(e.message).split('\n')[0]);
  } finally {
    await page.close();
    // --video: the page's recording lands beside its picture once the page is closed
    if (o.video && page.video()) await page.video().saveAs(path.join(o.out, shot(step, w, o.target === 'draft').replace(/\.png$/, '.webm'))).catch(() => {});
  }
  return problems;
}

async function main() {
  const o = args(process.argv.slice(2));
  if (o.list) { console.log(markdown()); return 0; }
  if (o.writeMd) { fs.writeFileSync(MD, markdown() + '\n'); console.log(`wrote ${path.relative(REPO, MD)}`); return 0; }

  if (o.axe) o.axeSrc = axeSource(o.axe);
  const steps = STEPS.filter(s => !o.only || o.only.has(s.n));
  const todo = o.target === 'draft' ? steps.filter(s => s.draft) : steps.filter(s => !s.waits && s.run);
  const urls = {};
  const servers = [];
  if (o.target === 'draft') {
    const file = path.join(o.repo, MOCKUP);
    if (!fs.existsSync(file)) {
      console.log(`draft D mockup not found at ${file}: nothing to picture (pass --repo with a checkout that has it)`);
      return 0;
    }
    urls.draft = 'file://' + file;
  }
  fs.mkdirSync(o.out, { recursive: true });
  const results = [];
  let browser, chrome, profile;
  try {
    if (o.target === 'dashboard' && todo.length) {
      servers.push(await serve('workspace-addons/dashboard', 'e2e/focus_insights/dashboard_server.py', 'focus-d-dash'));
      urls.dash = servers[0].base;
    }
    const { chromium } = playwright();
    profile = fs.mkdtempSync(path.join(os.tmpdir(), 'focus-d-prof-'));
    // a fake microphone that is always allowed (step 19 speaks into the message box with it, ORCH-696)
    // launch() + newContext(), never a profile folder: with one macOS may show a keychain window (AGENTS.md, 20 Nov)
    chrome = await headless.launch(chromium, { headless: true, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
    browser = await chrome.newContext(o.video ? { recordVideo: { dir: path.join(profile, 'video'), size: { width: 1280, height: 800 } } } : {});
    if (o.target !== 'draft') await browser.addInitScript(() => {
      const f = window.fetch;
      window.fetch = (u, opts) => f(typeof u === 'string' && u.startsWith('/api/state') ? u.replace(/([?&])have=[^&]*&?/, '$1').replace(/[?&]$/, '') : u, opts);
    });
    for (const s of steps) {
      if (!todo.includes(s)) {
        const why = s.waits ? `waits for: ${s.waits}` : 'not in draft D, today\'s page only';
        results.push({ s, state: s.waits ? 'pending' : 'skipped' });
        console.log(`${s.n}. ${s.waits ? 'PENDING' : 'skipped'}  ${s.title} (${why})`);
        continue;
      }
      const per = [];
      for (const size of SIZES) per.push({ w: size[0], problems: await runOne(browser, s, size, o, urls) });
      const bad = per.filter(p => p.problems.length);
      results.push({ s, state: bad.length ? 'failed' : 'passed', per });
      console.log(`${s.n}. ${bad.length ? 'FAILED ' : 'passed '}  ${s.title}`);
      for (const b of bad) console.log(`     ${b.w}: ${[...new Set(b.problems)].join(' | ')}`);
    }
  } finally {
    if (browser) await browser.close();
    if (chrome) await chrome.close();
    servers.forEach(x => x.stop());
    if (profile) fs.rmSync(profile, { recursive: true, force: true });
  }
  const count = st => results.filter(r => r.state === st).length;
  const draft = o.target === 'draft';
  const lines = [`# Focus draft D click-through: ${draft ? 'draft pictures' : 'dashboard run'}`, '',
    `${count('passed')} passed, ${count('failed')} failed, ${count('pending')} pending.`, '',
    '| Step | State | Pictures |', '| --- | --- | --- |',
    ...results.map(r => `| ${r.s.n}. ${r.s.title} | ${r.state} | ${!r.per ? '' : SIZES.map(([w]) => shot(r.s, w, draft)).join(' ')} |`)];
  fs.writeFileSync(path.join(o.out, 'report.md'), lines.join('\n') + '\n');
  console.log(`\n${count('passed')} passed, ${count('failed')} failed, ${count('pending')} pending. Pictures and report.md in ${o.out}`);
  return count('failed') ? 1 : 0;
}

module.exports = { markdown };
if (require.main === module) main().then(c => process.exit(c), e => { console.error(e); process.exit(1); });

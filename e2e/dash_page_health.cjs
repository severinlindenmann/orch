// Page health (ORCH-80): every main dashboard page at 1280, 1920 and 390 px, on fake data, before a release.
// The same checks the daily Dashboard tester role runs on the real workspace: no page error, the page shows its
// content (the loading shape goes away), nothing scrolls sideways at phone width, no button or link is cut off at
// the right edge, no word from the never-list (docs/wording.md) on buttons, tabs, headings or labels, and no program
// value (undefined, NaN, null, [object Object]) in the page text.
// Real dashboard web files in Chromium (own browser, mock keychain), every request answered in memory.
// usage: [PW_DIR=..] [SHOTS_DIR=..] node --test e2e/dash_page_health.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-page-health');
const DASH = path.join(__dirname, '..', 'workspace-addons', 'dashboard');
const WEB = path.join(DASH, 'src', 'orch_dashboard', 'web');
const FIX = path.join(DASH, 'tests', 'fixtures', 'state-chat-settings.json');
const KIT = path.join(__dirname, '..', 'workspace', 'src', 'orch_ui', 'static');
const VIEW = path.join(__dirname, '..', 'contracts', 'examples', 'addon-view', 'valid-lessons-page.json');
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};

const WIDTHS = [{name: 'desktop', width: 1280, height: 800}, {name: 'wide', width: 1920, height: 1080}, {name: 'phone', width: 390, height: 844}];
// The parts of the never-list that are safe to look for on buttons, tabs, headings and labels.
const NEVER = ['Proof', 'Approval', 'Sign-off', 'Subtask', 'Kill switch', 'Cron', 'Scheduler', 'Re-authenticate',
  'Retry', 'Offline', 'Expired', 'NetBird', 'Tailscale', 'Over to you', 'Inbox', 'Recommended'];
const LEAK = String.raw`\b(undefined|NaN|null)\b|\[object Object\]`;

function pages(state) {
  const by = s => state.tickets.find(t => t.status === s)?.id;
  return ['#home', '#tickets', '#review', '#chat', '#settings', '#settings/agent', '#settings/about',
    '#ticket/' + by('active'), '#ticket/' + by('review'), '#ticket/' + by('waiting'), '#addon/lessons'];
}

// Runs in the page: what a person would see as broken.
function look({never, leak}) {
  const vw = window.innerWidth, out = {sideways: document.documentElement.scrollWidth - vw, cut: [], words: [], leaks: [], text: 0};
  const main = document.querySelector('main');
  out.text = main ? main.innerText.trim().length : 0;
  const shown = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const inScroller = el => { for (let q = el.parentElement; q && q !== document.body; q = q.parentElement) { const o = getComputedStyle(q).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
  for (const el of document.querySelectorAll('main button, main a, main h1, main h2, main h3, main label, main input, main [role=tab], header button, header a')) {
    if (!shown(el)) continue;
    if (el.getBoundingClientRect().right > vw + 2 && !inScroller(el)) out.cut.push((el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 40));
  }
  const chrome = [...document.querySelectorAll('button, [role=tab], nav a, h1, h2, h3, label, th')].filter(shown).map(e => (e.innerText || '').trim()).filter(Boolean);
  for (const w of never) {
    const re = new RegExp('(^|[^A-Za-z])' + w.replace(/-/g, '\\-') + '([^A-Za-z]|$)');
    const hit = chrome.find(t => re.test(t));
    if (hit) out.words.push(w + ' in "' + hit.slice(0, 60) + '"');
  }
  const re = new RegExp(leak);
  for (const line of (main ? main.innerText : '').split('\n')) if (re.test(line)) out.leaks.push(line.trim().slice(0, 80));
  return out;
}

test('page health: every main page at 1280, 1920 and 390 px', {timeout: 300_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  const view = JSON.parse(fs.readFileSync(VIEW, 'utf8'));
  const state = JSON.parse(fs.readFileSync(FIX, 'utf8'));
  delete state._note; delete state.chat_activity; delete state.act_answer;
  state.addons.push({name: 'lessons', dashboard: {label: 'Lessons', icon: 'book', order: 50, title: 'Lessons', subtitle: 'What your helpers learned.'}});
  const problems = [];
  const browser = await chromium.launch({args: ['--use-mock-keychain', '--password-store=basic']});
  try {
    for (const vp of WIDTHS) {
      const context = await browser.newContext({viewport: {width: vp.width, height: vp.height}});
      await context.route('**/*', async route => {
        const url = new URL(route.request().url());
        const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
        if (url.origin !== BASE) return route.abort();
        if (url.pathname === '/api/state') return json(state);
        if (url.pathname === '/api/addon/lessons') return json({state: 'ok', view});
        if (url.pathname === '/api/act') return json(state);
        if (url.pathname === '/api/events') return route.fulfill({status: 204, body: ''});
        if (url.pathname.startsWith('/api/')) return route.fulfill({status: 404, body: ''});
        const rel = url.pathname === '/' ? 'index.html' : path.normalize(url.pathname).replace(/^[/\\]+/, '');
        const kit = rel.startsWith('kit' + path.sep);
        const file = kit ? path.join(KIT, rel.slice(4)) : path.join(WEB, rel);
        if (!file.startsWith(kit ? KIT : WEB) || !fs.existsSync(file)) return route.fulfill({status: 404, body: ''});
        return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream',
          headers: {'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self'"}, body: fs.readFileSync(file)});
      });
      const page = await context.newPage();
      let here = '';
      page.on('pageerror', e => problems.push(`${vp.name} ${here}: page error ${String(e).slice(0, 120)}`));
      for (const hash of pages(state)) {
        here = hash;
        await page.goto('about:blank');
        await page.goto(BASE + '/' + hash);
        const ready = await page.waitForFunction(() => {
          const m = document.querySelector('main');
          return m && !m.querySelector('.skeleton-page[aria-busy="true"]') && m.innerText.trim().length > 20;
        }, null, {timeout: 15_000}).then(() => true, () => false);
        await page.waitForTimeout(300);
        await page.screenshot({path: path.join(OUT, `${vp.name}-${hash.replace(/\W+/g, '-').replace(/^-/, '')}.png`)});
        if (!ready) { problems.push(`${vp.name} ${hash}: shows nothing within 15 s`); continue; }
        const o = await page.evaluate(look, {never: NEVER, leak: LEAK});
        if (vp.name === 'phone' && o.sideways > 4) problems.push(`${vp.name} ${hash}: scrolls sideways (${o.sideways} px too wide)`);
        for (const c of o.cut) problems.push(`${vp.name} ${hash}: cut off at the right edge: ${c}`);
        for (const w of o.words) problems.push(`${vp.name} ${hash}: never-list word ${w}`);
        for (const l of o.leaks) problems.push(`${vp.name} ${hash}: program value on screen: ${l}`);
      }
      await context.close();
    }
  } finally { await browser.close(); }
  assert.deepEqual([...new Set(problems)], [], 'screenshots in ' + OUT);
});

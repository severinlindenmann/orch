// Same numbers (ORCH-309, takes the test part of ORCH-296): one count, one date, one state for the same thing, on every
// page that shows it. The test reads the numbers each page shows (Home, the side menu, the top bar, the phone bottom bar,
// Review, Tickets, one ticket page), once, from the same fake workspace, and FAILS when two pages differ.
// It is a test of agreement, not of one definition: when a page changes how it counts, every page must change with it.
//   - the needs-you number: top bar line, menu button, side-menu Review badge, phone bottom-bar badge, Home title,
//     Home "Needs you" card, Home line (questions + results), Review line, Tickets pill, Tickets lanes (Needs you + Check);
//   - the ticket count: Home "All N tickets", Tickets list header, Tickets lane counts;
//   - for the same ticket: the status word and the due date on Home, Tickets and the ticket page.
// The state is the shared fake workspace of the dashboard tests (state-chat-settings.json) with Review cards added.
// Real dashboard web files in Chromium (own browser, mock keychain), every request answered in memory.
// usage: [PW_DIR=..] [SHOTS_DIR=..] node --test e2e/dash_same_numbers.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const headless = require('./headless.cjs'); // the keychain options (ORCH-615)

const PW = process.env.PW_DIR || path.join(os.homedir(), 'orch-dev', 'e2e', 'dashboard', 'node_modules');
const OUT = process.env.SHOTS_DIR || path.join(os.tmpdir(), 'dash-same-numbers');
const ROOT = path.join(__dirname, '..');
const DASH = path.join(ROOT, 'workspace-addons', 'dashboard');
const WEB = path.join(DASH, 'src', 'orch_dashboard', 'web');
const FIX = path.join(DASH, 'tests', 'fixtures', 'state-chat-settings.json');
const KIT = path.join(ROOT, 'workspace', 'src', 'orch_ui', 'static');
const BASE = 'http://dash.test';
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json'};

// The shared fake workspace: the dashboard fixture, Review cards for every open question and result.
function makeState() {
  const s = JSON.parse(fs.readFileSync(FIX, 'utf8'));
  delete s._note; delete s.chat_activity; delete s.act_answer;
  const byId = new Map(s.tickets.map(t => [t.id, t]));
  const cards = [];
  for (const n of s.needs) {
    const t = byId.get(n.ticket);
    if (!t) continue;
    const q = n.answer && n.answer.question && (t.questions || []).find(x => x.id === n.answer.question && x.answer == null);
    if (q) cards.push({id: `core:q:${t.id}:${q.id}`, ticket: t.id, ticket_key: t.key, key: q.id, kind: 'question', text: q.text, options: q.options || [], since: t.updated_at});
    else if (t.status === 'review') cards.push({id: `core:review:${t.id}`, ticket: t.id, ticket_key: t.key, kind: 'review', text: t.title, since: t.updated_at});
  }
  s.review = {cards, answered: []};
  return s;
}

async function openContext(browser, state, size) {
  const context = await browser.newContext({viewport: {width: size[0], height: size[1]}});
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    const json = body => route.fulfill({status: 200, contentType: 'application/json', headers: {'Access-Control-Allow-Origin': '*'}, body: JSON.stringify(body)});
    if (url.origin !== BASE) return route.abort();
    const p = url.pathname;
    if (p === '/api/state' || p === '/api/act') return json(state);
    if (p === '/api/events') return route.fulfill({status: 204, body: ''});
    if (p === '/api/frame-pass') return json({pass: 'p'.repeat(24), file: 'f'.repeat(24)});
    if (p.startsWith('/api/') || p.includes('/api/')) return route.fulfill({status: 404, body: ''});
    let root = WEB, rel = p === '/' ? 'index.html' : p.replace(/^\/+/, '');
    if (rel.startsWith('kit/')) { rel = rel.slice(4); root = KIT; }
    const file = path.normalize(path.join(root, rel));
    if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) return route.fulfill({status: 404, body: ''});
    let body = fs.readFileSync(file);
    return route.fulfill({status: 200, contentType: TYPES[path.extname(file)] || 'application/octet-stream',
      headers: {'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'", 'Access-Control-Allow-Origin': '*'}, body});
  });
  return context;
}

const int = s => { const m = /\d+/.exec(s || ''); return m ? Number(m[0]) : null; };
const waitReady = page => page.waitForFunction(() => {
  const m = document.querySelector('main');
  return m && !m.querySelector('.skeleton-page[aria-busy="true"]') && m.innerText.trim().length > 20;
}, null, {timeout: 15_000});

// Runs in the page: the numbers of the always-visible chrome (top bar, menu, side menu / bottom bar).
function chrome() {
  const text = sel => { const e = document.querySelector(sel); return e ? (e.innerText || e.textContent || '').trim() : ''; };
  const bar = text('header');
  return {
    topBar: (/(\d+) needs? you|(\d+) need you/.exec(bar) || [])[0] || '',
    menuButton: document.getElementById('menu-toggle')?.getAttribute('aria-label') || '',
    sideBadge: text('.sidebar a[href="#review"] .count'),
    tabBadge: text('#tabbar [data-tab="review"] .count, #tabbar [data-tab="review"] .badge'),
  };
}

test('same numbers: every page shows the same count, date and state for the same thing', {timeout: 300_000}, async () => {
  const {chromium} = require(path.join(PW, 'playwright'));
  fs.mkdirSync(OUT, {recursive: true});
  const state = makeState();
  const browser = await headless.launch(chromium);
  const facts = [];                                   // {what, where, value}: one row per number a page shows
  const note = (what, where, value) => facts.push({what, where, value});
  try {
    const context = await openContext(browser, state, [1280, 900]);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e).slice(0, 160)));
    const visit = async hash => { await page.goto('about:blank'); await page.goto(BASE + '/' + hash); await waitReady(page); await page.waitForTimeout(400); };

    // ---- Home
    await visit('#home');
    const home = await page.evaluate(() => {
      const main = document.querySelector('main'), t = main.innerText;
      const card = document.querySelector('#needs-you');
      return {
        title: (/(\d+) things? needs? you|(\d+) things? need you/.exec(t) || [])[0] || '',
        line: (/(\d+) questions?(?: · (\d+) results? to check)?/.exec(t) || []).slice(0, 3),
        results: (/(\d+) results? to check/.exec(t) || [])[1] || '0',
        questions: (/(\d+) questions?/.exec(t) || [])[1] || '0',
        card: card ? (card.querySelector('h2') || card).innerText.split('\n')[0] : '',
        all: (/All (\d+) tickets/.exec(t) || [])[1] || '',
        rows: [...main.querySelectorAll('[data-need-row]')].length,
      };
    });
    const homeChrome = await page.evaluate(chrome);
    await page.screenshot({path: path.join(OUT, 'home.png')});
    note('needs you', 'Home title', int(home.title));
    note('needs you', 'Home "Needs you" card', int(home.card));
    note('needs you', 'Home line (questions + results)', Number(home.questions) + Number(home.results));
    note('needs you', 'top bar', int(homeChrome.topBar));
    note('needs you', 'menu button', int(homeChrome.menuButton));
    note('needs you', 'side menu Review badge', int(homeChrome.sideBadge));
    note('tickets', 'Home "All N tickets"', int(home.all));

    // ---- Review
    await visit('#review');
    const review = await page.evaluate(() => {
      const main = document.querySelector('main');
      return {line: (/(\d+) things? waits? on you|(\d+) things? wait on you/.exec(main.innerText) || [])[0] || '', chrome: null};
    });
    const reviewChrome = await page.evaluate(chrome);
    await page.screenshot({path: path.join(OUT, 'review.png')});
    note('needs you', 'Review line', int(review.line));
    note('needs you', 'top bar (on Review)', int(reviewChrome.topBar));
    note('needs you', 'side menu Review badge (on Review)', int(reviewChrome.sideBadge));

    // ---- Tickets
    await visit('#tickets');
    const tickets = await page.evaluate(() => {
      const main = document.querySelector('main'), t = main.innerText;
      const lanes = {};
      for (const g of main.querySelectorAll('table tbody, [data-lane], .lane')) {
        const label = (g.innerText || '').split('\n').map(x => x.trim()).filter(Boolean).slice(0, 4).join(' | ');
        void label;
      }
      // a lane header reads "<icon> Name" then its number on the next line
      const lines = t.split('\n').map(x => x.trim()).filter(Boolean);
      for (let i = 0; i < lines.length - 1; i++) {
        const m = /^[^\w]*\s*(Needs you|Check|Working|Waiting|Backlog|Done|Stuck)$/.exec(lines[i]);
        if (m && /^\d+$/.test(lines[i + 1]) && !(m[1] in lanes)) lanes[m[1]] = Number(lines[i + 1]);
      }
      const rows = {};                                  // key -> {lane, due}: the lane a row sits in and its Due cell
      let lane = '';
      for (const r of main.querySelectorAll('tr')) {
        const cells = [...r.children].map(c => (c.innerText || '').trim());
        const key = /(?:^|\n)\s*([A-Z]+-\d+)\b/.exec(cells[0] || '');
        const head = /^[^\w]*\s*(Needs you|Check|Working|Waiting|Backlog|Done|Stuck)\b/.exec((r.innerText || '').trim());
        if (head && !key) { lane = head[1]; continue; }
        if (key) rows[key[1]] = {lane, due: cells[1] || ''};
      }
      return {
        pill: (/(\d+) needs? you|(\d+) need you/.exec(t) || [])[0] || '',
        head: (/Ticket · (\d+)/.exec(t) || [])[1] || '',
        lanes, rows,
      };
    });
    const ticketsChrome = await page.evaluate(chrome);
    await page.screenshot({path: path.join(OUT, 'tickets.png')});
    note('needs you', 'Tickets pill', int(tickets.pill));
    note('needs you', 'Tickets lanes (Needs you + Check)', (tickets.lanes['Needs you'] || 0) + (tickets.lanes.Check || 0));
    note('needs you', 'top bar (on Tickets)', int(ticketsChrome.topBar));
    note('tickets', 'Tickets list header', int(tickets.head));
    note('tickets', 'Tickets lanes (every lane added up)', Object.entries(tickets.lanes).filter(([k]) => k !== 'Needs you' && k !== 'Check').reduce((a, [, v]) => a + v, 0) + (tickets.lanes['Needs you'] || 0) + (tickets.lanes.Check || 0));

    // ---- one ticket page: its state word and its Due, for tickets in different lanes
    // (one with a question, one with a late day, one result to check, one working, one in the backlog with a day, one without)
    const SAMPLE = {};
    for (const key of ['PIL-71', 'PIL-60', 'PIL-12', 'PIL-2', 'PIL-55', 'PIL-7']) SAMPLE[key] = state.tickets.find(t => t.key === key)?.id;
    const ticketPage = {};
    for (const [key, id] of Object.entries(SAMPLE)) {
      assert.ok(id, key + ' is missing from the shared fake workspace');
      await visit('#ticket/' + id);
      ticketPage[key] = await page.evaluate(() => {
        const main = document.querySelector('main');
        const due = [...main.querySelectorAll('*')].find(e => e.children.length === 0 && /^Due$/.test((e.innerText || '').trim()));
        return {state: main.innerText.trim().split('\n')[0].trim(), due: due ? (due.nextElementSibling || due.parentElement.nextElementSibling || {innerText: ''}).innerText.trim() : ''};
      });
      await page.screenshot({path: path.join(OUT, 'ticket-' + key + '.png')});
    }

    // tabbar (phone bottom bar) is checked at 390 below
    await context.close();

    // ---- phone width: the bottom bar and the menu button
    const phone = await openContext(browser, state, [390, 844]);
    const pp = await phone.newPage();
    await pp.goto(BASE + '/#home'); await waitReady(pp); await pp.waitForTimeout(400);
    const phoneChrome = await pp.evaluate(chrome);
    await pp.screenshot({path: path.join(OUT, 'phone-home.png')});
    note('needs you', 'phone bottom bar Review badge', int(phoneChrome.tabBadge));
    note('needs you', 'phone menu button', int(phoneChrome.menuButton));
    await phone.close();

    // ---- agree? every group of facts must hold exactly one value
    const problems = [];
    for (const what of [...new Set(facts.map(f => f.what))]) {
      const rows = facts.filter(f => f.what === what);
      const values = new Set(rows.map(f => f.value));
      if (rows.some(f => f.value === null || f.value === undefined)) problems.push(`${what}: a page shows no number: ` + rows.filter(f => f.value == null).map(f => f.where).join(', '));
      else if (values.size > 1) problems.push(`${what}: pages differ: ` + rows.map(f => `${f.where} = ${f.value}`).join('; '));
    }
    const needs = facts.find(f => f.what === 'needs you');
    assert.ok(needs && needs.value > 0, 'the fake workspace must have something that needs the person, or the test proves nothing');
    // the shared state itself: the number every page shows is the one the data has (open questions + results to check)
    const open = state.review.cards.length;
    if (needs.value !== open) problems.push(`needs you: the pages show ${needs.value}, the workspace has ${open} open questions and results`);

    // the same ticket: Tickets lane = ticket page state word; Tickets Due = ticket page Due
    const LANE_WORD = {'Needs you': 'Needs you', Check: 'Check', Working: 'Working'};
    for (const [key, row] of Object.entries(tickets.rows)) {
      const tp = ticketPage[key];
      if (!tp) continue;
      if (LANE_WORD[row.lane] && tp.state !== LANE_WORD[row.lane]) problems.push(`${key}: Tickets says "${row.lane}", the ticket page says "${tp.state}"`);
      const NONE = /^(–|-|Set a due date|)$/;           // no day: a dash in the list, the invitation on the ticket page
      if (!(NONE.test(row.due) && NONE.test(tp.due)) && row.due !== tp.due) problems.push(`${key}: Tickets shows due "${row.due}", the ticket page shows "${tp.due}"`);
    }
    for (const key of Object.keys(SAMPLE)) if (!tickets.rows[key]) problems.push(`${key}: not in the Tickets list`);
    assert.deepEqual(errors, [], 'page errors');
    assert.deepEqual(problems, [], 'screenshots in ' + OUT);
    return;
  } finally { await browser.close(); }
});

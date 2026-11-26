// Same numbers (ORCH-309, takes the test part of ORCH-296): one count, one date, one state for the same thing, on every
// page that shows it. The test reads the numbers each page shows (Home, the side menu, the top bar, the phone bottom bar,
// Review, Tickets, one ticket page), once, from the same fake workspace, and FAILS when two pages differ.
// It is a test of agreement, not of one definition: when a page changes how it counts, every page must change with it.
//   - the needs-you number: top bar line, menu button, side-menu Review badge, phone bottom-bar badge, Home title,
//     Home "Needs you" card, Home line (questions + results + work that stopped, #2385), Review line, Tickets pill, Tickets lanes (Needs you + Check, plus work that stopped, which stays in its lane);
//   - the ticket count: Home "All N tickets", Tickets list header, Tickets lane counts;
//   - for the same ticket: the status word and the due date on Home, Tickets and the ticket page.
// ORCH-476 adds the number against the ROWS it stands for, with the counts made by the real core (orch/counts.py):
//   - Home: the title equals the rows of "Needs you" added up (each row says how much of the number it carries);
//   - Review: the heading equals the Waiting tab and the cards in the "All cards" list;
//   - Helpers (Home): the summary equals the rows, a ticket marked Working with no process has no row, and the
//     step of a helper equals the core's step (a won't-do task counts) and the ticket page's tasks;
//   - the ticket page: its progress line equals its task rows, and a task that will not be done says "Won't do";
//   - Insights (its own server, the core's Stuck count): never "All good" beside "Stuck now" above 0.
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
const {execFileSync} = require('node:child_process');
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
  // ORCH-476: a helper at work on PIL-2 (the report's DEM-1: four tasks, one won't do, the fourth being done) and PIL-80
  // marked Working with no process behind it (the report's DEM-3); then the counts from the real core, as the
  // dashboard server adds them (data.load_counts)
  const pil2 = s.tickets.find(t => t.key === 'PIL-2'), pil80 = s.tickets.find(t => t.key === 'PIL-80');
  pil2.checklist = [
    {id: 'c1', text: 'Collect the new prices', done: true, evidence: []},
    {id: 'c2', text: 'Ask the supplier again', wont_do: true, reason: 'No longer needed', evidence: []},
    {id: 'c3', text: 'Update the sheet', done: true, evidence: []},
    {id: 'c4', text: 'Print the price list', state: 'doing', evidence: []},
  ];
  s.runs = {
    [pil2.id]: {ticket: pil2.id, running: true, state: 'alive', helper: {state: 'working', detail: ''}, age_seconds: 3000, idle_seconds: 5},
    [pil80.id]: {ticket: pil80.id, running: false, pending: 0},
  };
  // ORCH-1687: a ticket whose helper could not start (its run record is gone): Home lists it with Try again, so the
  // number, Review and Tickets count it too
  const failed = s.tickets.find(t => t.key === 'PIL-81');
  Object.assign(failed, {status: 'waiting', waiting_on: {kind: 'external', ref: 'Not logged in', start: true}, questions: []});
  // #2385: a step whose check failed twice in a row (stuck.py helper:failing): a row of Home's Needs you, so the core's
  // number counts it too (Focus, Insights and `orch counts` said less than Home while something was stuck)
  const failing = s.tickets.find(t => t.key === 'PIL-55');
  const run = at => ({type: 'command', ref: 'make check', exit: 1, at});
  failing.checklist = [{id: 'c1', text: 'Check the backups', evidence: [run('2026-11-13T08:00:00Z'), run('2026-11-13T08:05:00Z')]}];
  s.needs.push({id: `core:failing:${failing.id}`, source: 'core', kind: 'helper:failing', ticket: failing.id, title: failing.title,
    text: 'The check failed 2 times in a row on the step "Check the backups".', tone: 'bad', since: '2026-11-13T08:05:00Z', cli: `orch ticket show ${failing.key}`});
  s.counts = coreCounts(s.tickets, s.runs, s.needs);
  return s;
}

// The real core's count (orch/counts.py) over the same tickets and runs; the dashboard server adds the same block.
function coreCounts(tickets, runs, needs) {
  const code = 'import json, sys\nfrom orch import counts\nd = json.load(sys.stdin)\nprint(json.dumps(counts.summary(d["tickets"], d["runs"], stopped=d["needs"])))';
  const out = execFileSync('uv', ['run', '--quiet', '--project', path.join(ROOT, 'workspace'), 'python', '-c', code],
    {input: JSON.stringify({tickets, runs, needs}), encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, timeout: 240_000});
  return JSON.parse(out);
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
  const repeated = [];                                // places that must not repeat the needs-you number (ORCH-1616)
  const noise = (where, text) => { if (text) repeated.push(where + ': ' + text); };
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
        line: (/\d+ (questions?|results? to check|stuck|changes?|idle|helpers?|things?)\b/.exec(document.querySelector('main [data-key="heading"] p')?.innerText || '') || []).slice(0, 1),
        results: (/(\d+) results? to check/.exec(t) || [])[1] || '0',
        questions: (/(\d+) questions?/.exec(t) || [])[1] || '0',
        card: card ? (card.querySelector('h2') || card).innerText.split('\n')[0] : '',
        all: (/All (\d+) tickets/.exec(t) || [])[1] || '',
        rows: [...main.querySelectorAll('[data-need-row]')].length,
        // ORCH-476: every row of "Needs you" says how much of the number it carries; added up they are the title
        weights: [...(card ? card.querySelectorAll('[data-counts]') : [])].map(e => Number(e.getAttribute('data-counts'))),
        unweighed: card ? [...card.querySelectorAll('[data-need-row]')].filter(e => !e.closest('[data-counts]')).length : 0,
        helperSum: document.querySelector('.helper-list .helper-sum')?.innerText.trim() || '',
        helperRows: [...document.querySelectorAll('.helper-list .helper-row')].map(r => ({
          title: r.querySelector('.helper-title')?.getAttribute('title') || '', meta: r.querySelector('.meta')?.innerText.trim() || '', state: r.dataset.state})),
      };
    });
    const homeChrome = await page.evaluate(chrome);
    await page.screenshot({path: path.join(OUT, 'home.png')});
    // ORCH-1616 (owner, less noise): the number shows in ONE place, the Review badge; Home's heading, the top bar,
    // the menu button and the Tickets header never repeat it
    noise('Home title', home.title);
    noise('Home "Needs you" card', /\d/.test(home.card) ? home.card : '');
    noise('Home line under the heading', home.line[0] || '');  // ORCH-1616: the date alone, no counts
    noise('top bar', homeChrome.topBar);
    noise('menu button', /\d/.test(homeChrome.menuButton) ? homeChrome.menuButton : '');
    note('needs you', 'side menu Review badge', int(homeChrome.sideBadge));
    note('tickets', 'Home "All N tickets"', int(home.all));

    // ---- Review
    await visit('#review');
    await page.waitForSelector('[data-review-queue] .review-row', {timeout: 10_000}).catch(() => null);
    const review = await page.evaluate(() => {
      const main = document.querySelector('main');
      return {line: (/(\d+) things? waits? on you|(\d+) things? wait on you/.exec(main.innerText) || [])[0] || '', chrome: null,
        waiting: (document.querySelector('button[data-show="deck"] .meta')?.innerText || '').trim(),
        queue: document.querySelectorAll('[data-review-queue] .review-row:not(.is-done)').length,
        // ORCH-1616/1687: what the number counts but has no card (a helper that could not start) is listed above
        extra: document.querySelectorAll('[data-key="review-extra"] [data-what]').length};
    });
    const reviewChrome = await page.evaluate(chrome);
    await page.screenshot({path: path.join(OUT, 'review.png')});
    note('needs you', 'Review line', int(review.line));
    note('needs you', 'Review Waiting tab + rows listed above the cards', int(review.waiting) + review.extra);
    note('needs you', 'Review "All cards" rows waiting + rows listed above the cards', review.queue + review.extra);
    note('needs you', 'Home "Needs you" rows added up', home.weights.reduce((a, b) => a + b, 0));
    noise('top bar (on Review)', reviewChrome.topBar);
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
        // the pick checkbox cell (ORCH-2034) holds no text: read the cells after it
        const cells = [...r.children].filter(c => !c.classList.contains('pick-cell')).map(c => (c.innerText || '').trim());
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
    noise('Tickets header', tickets.pill);
    // #2385: work that stopped stays in its own lane (Working): it is counted beside the lanes, like Review's extra rows
    const stoppedRows = state.needs.filter(n => n.source === 'core' && /^(helper|reviewer):/.test(n.kind || '')).length;
    note('needs you', 'Tickets lanes (Needs you + Check) + work that stopped', (tickets.lanes['Needs you'] || 0) + (tickets.lanes.Check || 0) + stoppedRows);
    noise('top bar (on Tickets)', ticketsChrome.topBar);
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
        // the first word line; a ticket with a live helper starts with its number ("PIL-2 · Working · ...")
        const first = main.innerText.split('\n').map(x => x.trim()).filter(x => x && x !== '·' && !/^[A-Z]+-\d+( ·)?$/.test(x))[0] || '';
        // the words on screen only: an edit field also says ", change due date" to a screen reader (.sr-only, label in name)
        const shown = n => { if (!n) return ''; const c = n.cloneNode(true); c.querySelectorAll('.sr-only').forEach(x => x.remove()); return c.textContent.trim(); };
        return {state: first, due: due ? shown(due.nextElementSibling || due.parentElement.nextElementSibling) : ''};
      });
      await page.screenshot({path: path.join(OUT, 'ticket-' + key + '.png')});
    }

    // ---- ORCH-476: the ticket page of the working helper: its progress line against its task rows and the words
    await visit('#ticket/' + state.tickets.find(t => t.key === 'PIL-2').id);
    const tasksPage = await page.evaluate(() => {
      const card = document.querySelector('[data-key="progress"]');
      // a task row ends with its word; the task the helper is on is its own row ("Your helper is working on this task")
      const words = [...(card ? card.querySelectorAll('ol.task-list > li') : [])].map(li => li.classList.contains('current-task') ? 'Working' : (li.querySelector(':scope > .meta')?.innerText || '').trim());
      return {line: card?.querySelector('.section-head .meta')?.innerText.trim() || '', words, skipped: /skipped/i.test(document.querySelector('main').innerText)};
    });
    await page.screenshot({path: path.join(OUT, 'ticket-PIL-2-tasks.png')});
    // tabbar (phone bottom bar) is checked at 390 below
    await context.close();

    // ---- phone width: the bottom bar and the menu button
    const phone = await openContext(browser, state, [390, 844]);
    const pp = await phone.newPage();
    await pp.goto(BASE + '/#home'); await waitReady(pp); await pp.waitForTimeout(400);
    const phoneChrome = await pp.evaluate(chrome);
    await pp.screenshot({path: path.join(OUT, 'phone-home.png')});
    note('needs you', 'phone bottom bar Review badge', int(phoneChrome.tabBadge));
    noise('phone menu button', /\d/.test(phoneChrome.menuButton) ? phoneChrome.menuButton : '');
    await phone.close();

    // ---- ORCH-476: Insights on its own fixture server; "Stuck now" is the core's Stuck count (one stuck ticket)
    const {start: startFixture} = require('./focus_insights_shots.cjs');
    const ins = await startFixture('workspace-addons/insights', 'e2e/focus_insights/insights_server.py', 'insights-same');
    let insights;
    try {
      const ic = await browser.newContext({viewport: {width: 1280, height: 900}});
      const ip = await ic.newPage();
      ip.on('pageerror', e => errors.push('insights: ' + String(e).slice(0, 160)));
      await ip.goto(ins.base + '/');
      await ip.waitForFunction(() => /Stuck now/.test(document.getElementById('team-stats')?.innerText || '') && !document.getElementById('health')?.hidden, null, {timeout: 30_000});
      insights = await ip.evaluate(() => {
        const tile = [...document.querySelectorAll('#team-stats > *')].find(e => /Stuck now/.test(e.innerText));
        return {stuck: tile ? Number((/(\d+)/.exec(tile.innerText.replace('Stuck now', '')) || [])[1]) : null,
          health: document.getElementById('health').innerText.trim(), cards: document.querySelectorAll('#needs > *').length};
      });
      await ip.screenshot({path: path.join(OUT, 'insights.png')});
      await ic.close();
    } finally { ins.stop(); }

    // ---- agree? every group of facts must hold exactly one value
    const problems = [];
    for (const what of [...new Set(facts.map(f => f.what))]) {
      const rows = facts.filter(f => f.what === what);
      const values = new Set(rows.map(f => f.value));
      if (rows.some(f => f.value === null || f.value === undefined)) problems.push(`${what}: a page shows no number: ` + rows.filter(f => f.value == null).map(f => f.where).join(', '));
      else if (values.size > 1) problems.push(`${what}: pages differ: ` + rows.map(f => `${f.where} = ${f.value}`).join('; '));
    }
    for (const r of repeated) problems.push('needs you: shown again outside the Review badge: ' + r);
    const needs = facts.find(f => f.what === 'needs you');
    assert.ok(needs && needs.value > 0, 'the fake workspace must have something that needs the person, or the test proves nothing');
    // the shared state itself: the number every page shows is the one the data has (open questions + results to check
    // + helpers that could not start, ORCH-1687)
    const stopped = state.needs.filter(n => n.source === 'core' && /^(helper|reviewer):/.test(n.kind || '')).length;  // #2385
    const open = state.review.cards.length + stopped + state.tickets.filter(t => t.status === 'waiting' && t.waiting_on?.start === true && !(t.questions || []).some(q => q.answer == null)).length;
    if (needs.value !== open) problems.push(`needs you: the pages show ${needs.value}, the workspace has ${open} open questions, results and stopped work`);
    if (state.counts.needs_you.stopped !== stopped) problems.push(`needs you: the core counts ${state.counts.needs_you.stopped} stopped, Home lists ${stopped}`);

    // the same ticket: Tickets lane = ticket page state word; Tickets Due = ticket page Due
    // Working lane: the ticket page says 'Working' while a helper runs, 'In progress' when none does (ORCH-415, owner approved)
    const LANE_WORD = {'Needs you': ['Needs you'], Check: ['Check'], Working: ['Working', 'In progress']};
    for (const [key, row] of Object.entries(tickets.rows)) {
      const tp = ticketPage[key];
      if (!tp) continue;
      if (LANE_WORD[row.lane] && !LANE_WORD[row.lane].includes(tp.state)) problems.push(`${key}: Tickets says "${row.lane}", the ticket page says "${tp.state}"`);
      const NONE = /^(–|-|Set a due date|)$/;           // no day: a dash in the list, the invitation on the ticket page
      if (!(NONE.test(row.due) && NONE.test(tp.due)) && row.due !== tp.due) problems.push(`${key}: Tickets shows due "${row.due}", the ticket page shows "${tp.due}"`);
    }
    for (const key of Object.keys(SAMPLE)) if (!tickets.rows[key]) problems.push(`${key}: not in the Tickets list`);
    // ORCH-476: the number against the rows it stands for
    if (home.unweighed) problems.push(`Home: ${home.unweighed} "Needs you" rows say nothing about the number`);
    if (needs.value !== state.counts.needs_you.count) problems.push(`needs you: the pages show ${needs.value}, the core counts ${state.counts.needs_you.count}`);
    const pil2 = state.tickets.find(t => t.key === 'PIL-2'), pil80 = state.tickets.find(t => t.key === 'PIL-80');
    const step = state.counts.tickets[pil2.id].step, prog = state.counts.tickets[pil2.id].progress;
    if (!step || step.n !== 4 || step.of !== 4) problems.push(`PIL-2: the core step is ${JSON.stringify(step)}, expected 4 of 4 (a won't-do task counts)`);
    const row2 = home.helperRows.find(r => r.title.startsWith('PIL-2'));
    if (!row2) problems.push('Helpers: PIL-2 has a working helper but no row');
    else if (!row2.meta.startsWith(`Step ${step.n} of ${step.of}`)) problems.push(`Helpers: PIL-2 says "${row2.meta}", the core says Step ${step.n} of ${step.of}`);
    if (home.helperRows.some(r => r.title.startsWith('PIL-80'))) problems.push('Helpers: PIL-80 is listed as a helper but no process runs');
    if (int(home.helperSum) !== home.helperRows.length || home.helperRows.length !== state.counts.running) problems.push(`Helpers: the summary says "${home.helperSum}", ${home.helperRows.length} rows, the core counts ${state.counts.running} running`);
    const want = [prog.done && prog.done + ' done', prog.wont_do && prog.wont_do + " won't do", prog.doing && prog.doing + ' in progress', prog.todo && prog.todo + ' to do'].filter(Boolean).join(' · ');
    if (tasksPage.line !== want) problems.push(`ticket page PIL-2: progress says "${tasksPage.line}", the core says "${want}"`);
    const byWord = w => tasksPage.words.filter(x => x === w).length;
    if (byWord('Done') !== prog.done || byWord("Won't do") !== prog.wont_do || byWord('Working') !== prog.doing) problems.push(`ticket page PIL-2: task rows ${JSON.stringify(tasksPage.words)} do not match its progress "${tasksPage.line}"`);
    if (tasksPage.skipped) problems.push('ticket page PIL-2: says "skipped"; the word is "Won\'t do"');
    if (pil80.status !== 'active' || state.counts.tickets[pil80.id].helper !== null) problems.push('PIL-80: the core gives a ticket with no process a helper');
    if (insights.stuck !== 1) problems.push(`Insights: "Stuck now" says ${insights.stuck}, the core counts 1 stuck ticket`);
    if (insights.stuck && /All good/.test(insights.health)) problems.push(`Insights: "${insights.health}" beside "Stuck now ${insights.stuck}"`);
    else if (insights.stuck && int(insights.health) < insights.stuck) problems.push(`Insights: "${insights.health}" counts fewer than the ${insights.stuck} stuck`);
    assert.deepEqual(errors, [], 'page errors');
    assert.deepEqual(problems, [], 'screenshots in ' + OUT);
    return;
  } finally { await browser.close(); }
});

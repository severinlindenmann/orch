/* Focus v4 draft (ORCH-251): Focus is a bar under the whole dashboard that opens into a layer. Demo data only; picks stay in this browser. */
(function () {
  'use strict';
  /* ---------- the features: what it does, how it works in orch, size of new work, the demo state that shows it ---------- */
  var F = [
    { t: 'Start page: who needs you first', what: 'One calm screen of every helper: who needs you first, then who is working, then what is quiet.', how: 'orch run list already gives each ticket its signal (working, idle, waiting) and what it waits on. The preview is the last lines of its screen.', size: 'Medium', show: { mode: 'right', view: 'start' } },
    { t: 'One Focus button on every ticket', what: 'Each ticket has one button that fits what its helper is doing: Answer, Watch, Open or Start.', how: 'The same run signal per ticket. Start, watch and send exist as commands today.', size: 'Small', show: { page: 'tickets', mode: 'strip' } },
    { t: 'Continue or start clean', what: 'Start asks one thing: carry on the last conversation, or begin with a fresh memory.', how: 'The session id is kept on the ticket, so the next start resumes it. Only the last session is kept today: a list of older ones needs new storage.', size: 'Small', show: { page: 'tickets', mode: 'strip', ask: 4 } },
    { t: 'Chat or real terminal', what: 'Chat is plain messages. Terminal is the helper’s real screen: type, select, copy and paste as in the Mac Terminal.', how: 'Every helper already runs in its own tmux session. The terminal in the browser (xterm.js and a bridge) is new. No chat transcript exists: Chat shows helper messages and ticket events.', size: 'Large', show: { mode: 'right', view: 'session', cur: 1, term: 'terminal' } },
    { t: 'Sessions without a ticket', what: 'Open a Manager, a chat helper or a plain terminal that belongs to no ticket.', how: 'The same tmux socket with a name that is not a ticket id. Today every session belongs to a ticket and counts against the live limit.', size: 'Medium', show: { mode: 'right', view: 'session', cur: 5, menu: 'new' } },
    { t: 'Always open, on every page', what: 'Focus is a bar under the whole dashboard, not a page. It opens upward or to the side and stays as you left it while you change pages.', how: 'Today every page is a full load and there is no shared layer. Cheapest honest path: pages swap softly so the layer stays. Fallback: a pop-out window.', size: 'Large', show: { page: 'home', mode: 'bottom', view: 'session', cur: 1 } },
    { t: 'Full screen', what: 'The session takes the whole window with nothing around it. Esc brings the page back.', how: 'Layout only. No new data.', size: 'Small', show: { mode: 'full', view: 'session', cur: 1 } },
    { t: 'Live status, instant switching', what: 'Every session is a chip in the bar with its status and its latest line. One click switches, with no loading.', how: 'Run signal and last screen line, read every few seconds. Live places are limited: extra starts wait in line, idle sessions close after about an hour.', size: 'Medium', show: { page: 'home', mode: 'strip' } },
    { t: 'Side by side', what: 'Two sessions next to each other: watch one while you answer the other.', how: 'Two views on two tmux sessions. Nothing new to store; it comes with the terminal.', size: 'Small', show: { mode: 'bottom', view: 'session', cur: 1, split: true } },
    { t: 'Results as pictures', what: 'What the helper made, as small pictures: screenshots, pages, charts, pull requests. Less text to read.', how: 'The files and evidence on the ticket and its linked pull requests exist. A small picture per file type is new.', size: 'Medium', show: { mode: 'right', view: 'session', cur: 1, term: 'chat' } }
  ];
  var S = [
    { k: 'ORCH-238', t: 'Add files and notes to a ticket', s: 'wait', note: 'Keep the old file name?', step: [3, 5], q: 'A file with this name is already on the ticket. Keep the old file name?', opts: ['Keep the old name', 'Use the new name'],
      log: ['● Read the ticket and its 2 files', '● Built the upload box', '✓ 14 tests passed', '? A file with this name is already on the ticket. Keep the old file name?'], next: ['● Wrote the rename rule', '✓ 16 tests passed', '● Taking a picture of the upload box'],
      res: [['shot', 'Upload box', 'Screenshot'], ['page', 'Ticket page', 'Page']] },
    { k: 'ORCH-228', t: 'Phone width and zoom', s: 'run', note: 'Opening the pull request', step: [4, 5],
      log: ['● Checked the ticket page at 320, 390 and 1280', '● Fixed the header wrap at 320', '✓ 6 of 6 checks passed', '● Opening the pull request…'], next: ['● Pull request #1252 is open', '● Waiting for the checks', '✓ 5 checks passed, 1 running'],
      res: [['shot', 'Phone at 320', 'Screenshot'], ['page', 'Ticket page', 'Page'], ['chart', '6 of 6 checks', 'Chart'], ['pr', '#1252', 'Pull request']] },
    { k: 'ORCH-232', t: 'Insights and usage counts', s: 'run', note: 'Running tests', step: [2, 6],
      log: ['● Read the usage counts', '● Drew the weekly chart', '● Running tests…'], next: ['✓ 22 tests passed', '● Writing counts.csv', '● Checking the chart at phone width'],
      res: [['chart', 'Usage this week', 'Chart'], ['table', 'counts.csv', 'Table']] },
    { k: 'ORCH-247', t: 'Steer a helper from the dashboard', s: 'idle', note: 'Idle 18 min', step: [5, 5],
      log: ['● Merged on green checks', '✓ All 5 steps done', '● Nothing left to do. Idle.'], next: [],
      res: [['page', 'Steering notes', 'Page'], ['pr', '#1249', 'Pull request']] },
    { k: 'ORCH-189', t: 'Manager view', s: 'none', note: 'No session', step: [0, 4], log: [], next: ['● Read the ticket', '● Planning 4 steps'], res: [] },
    { k: 'Manager', t: 'No ticket', free: true, s: 'run', note: 'Looking after 4 helpers', step: null,
      log: ['● Looking after 4 helpers', '● ORCH-238 waits for an answer', '● Checking again in 5 min'], next: ['● ORCH-228 opened its pull request'], res: [] }
  ];
  var WORD = { wait: 'Needs you', run: 'Working', idle: 'Idle', none: 'No session', line: 'In line' };
  var BTN = { wait: 'Answer', run: 'Watch', idle: 'Open', none: 'Start', line: 'Open' };
  var KIND = { shot: 3, page: 4, chart: 5, pr: 0, table: 9 };
  var LIVE_MAX = 6, MAC = /Mac|iPhone|iPad/.test(navigator.platform || ''), KEY = MAC ? '⌘J' : 'Ctrl J';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function btn(text, cls, fn, fk) { var b = h('button', 'btn ' + (cls || 'sm'), text); b.type = 'button'; if (fn) b.addEventListener('click', fn); if (fk) b.dataset.fk = fk; return b; }
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  var picks = {}; try { picks = JSON.parse(store.get('fv4-picks') || '{}') || {}; } catch (e) { picks = {}; }

  /* ---------- state, also readable from the address: ?page=&mode=&view=&term=&split=&cur=&ask=&sheet=1 ---------- */
  var st = { page: 'tickets', mode: 'right', view: 'start', term: 'terminal', split: false, cur: 1, cur2: 0, ap: 0, ask: -1, sheet: false, f: 0, menu: '', peek: '', tk: 4, type: false, marks: true, back: 'right' };
  var q = new URLSearchParams(location.search);
  var OK = { page: ['home', 'tickets', 'review', 'ticket'], mode: ['right', 'bottom', 'full', 'strip'], view: ['start', 'session'], term: ['chat', 'terminal'], menu: ['new'] };
  Object.keys(OK).forEach(function (k) { if (OK[k].indexOf(q.get(k)) >= 0) st[k] = q.get(k); });
  function num(k, max) { var v = parseInt(q.get(k), 10); return v >= 0 && v <= max ? v : null; }
  if (num('cur', 5) != null) { st.cur = num('cur', 5); if (!q.get('view')) st.view = 'session'; }
  if (num('cur2', 5) != null) st.cur2 = num('cur2', 5);
  if (num('tk', 4) != null) st.tk = num('tk', 4);
  if (num('ask', 4) != null) st.ask = num('ask', 4);
  if (num('f', F.length) != null) st.f = num('f', F.length);
  if (q.get('split') === '1') { st.split = true; if (!q.get('view')) st.view = 'session'; }
  if (q.get('sheet') === '1') st.sheet = true;
  if (q.get('marks') === '0') st.marks = false;
  if (!q.get('mode') && window.matchMedia && matchMedia('(max-width:720px)').matches) st.mode = 'strip';
  if (st.cur2 === st.cur) st.cur2 = st.cur === 0 ? 1 : 0;
  if (st.mode === 'right' || st.mode === 'bottom') st.back = st.mode;
  var LIVE = q.get('live') !== '0';
  var drafts = {}, chats = {};
  S.forEach(function (s, i) { chats[i] = s.s === 'none' ? [] : [['ev', 'Step ' + (s.step ? s.step[0] + ' of ' + s.step[1] : '1') + ' started'], ['helper', s.q || s.note + '.']]; });

  function writeUrl() {
    var p = new URLSearchParams(); p.set('page', st.page); p.set('mode', st.mode); p.set('view', st.view); p.set('term', st.term); p.set('cur', st.cur);
    if (st.split) p.set('split', '1'); if (st.ask >= 0) p.set('ask', st.ask); if (st.sheet) p.set('sheet', '1'); if (st.page === 'ticket') p.set('tk', st.tk); if (!LIVE) p.set('live', '0'); if (!st.marks) p.set('marks', '0');
    try { history.replaceState(null, '', location.pathname + '?' + p.toString()); } catch (e) {}
  }
  /* redraw only the named parts: p page, l layer, b bar, s sheet, r ribbon. A page switch never redraws the layer, so its terminal stays as it was. */
  function draw(parts) {
    var a = document.activeElement, fk = a && a.dataset ? a.dataset.fk : '';
    document.body.dataset.mode = st.mode; document.body.dataset.marks = st.marks ? '1' : '0';
    if (parts.indexOf('p') >= 0) { nav(); page(); }
    if (parts.indexOf('l') >= 0) layer();
    if (parts.indexOf('b') >= 0) bar();
    if (parts.indexOf('s') >= 0) sheet();
    if (parts.indexOf('r') >= 0) ribbon();
    paintMarks(); writeUrl();
    if (fk && !document.activeElement.dataset.fk) { var n = $('[data-fk="' + fk + '"]'); if (n) n.focus(); }
  }
  function setMode(m) { if (m === 'right' || m === 'bottom') st.back = m; st.mode = m; st.menu = ''; draw('lb'); }
  function toggle() { setMode(st.mode === 'strip' ? st.back : 'strip'); }
  function openSess(i) {
    if (st.split && st.view === 'session' && st.ap === 1 && i !== st.cur) st.cur2 = i;
    else { if (st.split && i === st.cur2) st.cur2 = st.cur; st.cur = i; st.ap = 0; }
    st.view = 'session'; st.ask = -1; st.menu = ''; st.peek = ''; if (st.mode === 'strip') st.mode = st.back; draw('plb');
  }
  function openStart() { st.view = 'start'; st.menu = ''; if (st.mode === 'strip') st.mode = st.back; draw('lb'); }
  function liveCount() { return S.filter(function (s) { return s.s === 'wait' || s.s === 'run' || s.s === 'idle'; }).length; }
  function anyWait() { return S.some(function (s) { return s.s === 'wait'; }); }
  function off(i) { return S[i].s === 'none' || S[i].s === 'line'; }
  function order() { var w = { wait: 0, run: 1, idle: 2, line: 3, none: 4 }; return S.map(function (x, i) { return i; }).sort(function (a, b) { return w[S[a].s] - w[S[b].s] || a - b; }); }
  function begin(i, clean) {
    var s = S[i]; if (liveCount() >= LIVE_MAX) { s.s = 'line'; s.note = 'Waits for a free place'; openSess(i); return; }
    s.s = 'run'; s.step = s.step && [1, s.step[1]];
    s.log = clean ? ['● New session, fresh memory', '● Reading the ticket and its files'] : ['● Picked up the last conversation (yesterday 16:40)', '● Carrying on with step 1 of ' + (s.step ? s.step[1] : 1)];
    s.note = clean ? 'Reading the ticket' : 'Carrying on'; chats[i] = [['ev', clean ? 'New session started' : 'Last conversation continued'], ['helper', s.note + '.']];
    openSess(i);
  }
  function answer(i, text) {
    var s = S[i]; s.s = 'run'; s.note = 'Carrying on with step ' + (s.step[0] + 1); s.log.push('> ' + text, '● Thanks. ' + s.note + '.'); chats[i].push(['me', text], ['helper', 'Thanks. ' + s.note + '.']);
    draw('plb');
  }
  function addFree(name, first) { var full = liveCount() >= LIVE_MAX; S.push({ k: name, t: 'No ticket', free: true, s: full ? 'line' : 'run', note: full ? 'Waits for a free place' : first.slice(2), step: null, log: [first], next: [], res: [] }); chats[S.length - 1] = [['ev', 'Session started'], ['helper', first.slice(2)]]; openSess(S.length - 1); }

  /* ---------- small pieces ---------- */
  function glyph(s) { var g = h('span', 'v4-st ' + (s === 'line' ? 'none' : s), s === 'wait' ? '!' : ''); g.setAttribute('role', 'img'); g.setAttribute('aria-label', WORD[s]); return g; }
  function pill(s) { var p = h('span', 'v4-pill ' + s); p.append(glyph(s), document.createTextNode(WORD[s])); return p; }
  function mark(n) {
    var b = h('button', 'v4-n', String(n)); b.type = 'button'; b.tabIndex = -1; b.dataset.n = n; b.dataset.fk = 'n' + n;
    b.addEventListener('click', function (e) { e.stopPropagation(); st.sheet = true; st.f = n; draw('sr'); var r = $('#v4-f-' + n); if (r) { r.scrollIntoView({ block: 'center' }); r.focus(); } });
    return b;
  }
  function paintMarks() {
    $$('.v4-n').forEach(function (b) {
      var n = +b.dataset.n, p = picks[n] || ''; b.dataset.pick = p; b.classList.toggle('is-shown', st.f === n);
      if (b.tagName === 'BUTTON') b.setAttribute('aria-label', 'Feature ' + n + ': ' + F[n - 1].t + (p ? ' (your pick: ' + p + ')' : '') + '. Open in Features');
    });
  }
  function steps(s) { var w = h('span', 'v4-steps'); if (!s.step) return w; for (var i = 0; i < s.step[1]; i++) w.append(h('i', i < s.step[0] ? 'on' : '')); w.append(h('span', 'meta', 'Step ' + s.step[0] + ' of ' + s.step[1])); return w; }
  function lineEl(t) { var c = { '●': 'run', '✓': 'ok', '?': 'ask', '>': 'me', '$': 'dim' }[t.charAt(0)] || ''; return h('div', 'v4-l ' + c, t); }
  function choices(i) {
    var s = S[i], w = h('div', 'v4-choices');
    function one(cls, title, sub, clean, fk) { var b = h('button', 'v4-choice ' + cls); b.type = 'button'; b.dataset.fk = fk + i; b.append(h('b', '', title), h('span', '', sub)); b.addEventListener('click', function (e) { e.stopPropagation(); begin(i, clean); }); return b; }
    w.append(h('p', 'meta', 'Uses 1 of ' + LIVE_MAX + ' places. If all are in use it waits in line.'));
    w.append(one('', 'Continue where it stopped', 'Yesterday 16:40. The helper remembers what it did.', false, 'cont'), one('', 'Start clean', 'A fresh memory. The ticket and its files stay.', true, 'clean'));
    w.setAttribute('aria-label', 'Start ' + s.k); return w;
  }
  function thumb(kind, big) {
    var t = h('span', 'v4-th ' + kind + (big ? ' big' : '')); t.setAttribute('aria-hidden', 'true');
    if (kind === 'pr') { t.append(h('em', 'ok', '✓ 5 passed'), h('em', '', '◔ 1 running')); return t; }
    for (var i = 0; i < KIND[kind]; i++) { var x = h('i'); if (kind === 'chart') x.style.setProperty('--v', [55, 90, 40, 100, 75][i] + '%'); t.append(x); }
    return t;
  }

  /* ---------- the dashboard pages (stand-ins for the real ones) ---------- */
  var PAGES = [['home', 'Home', 'm3 10 9-7 9 7v10H3z'], ['tickets', 'Tickets', 'M3 4h18v16H3zM9 4v16m6-16v16'], ['review', 'Review', 'M3 3h18v18H3zm5 9 3 3 5-6']];
  function nav() {
    var n = $('#v4-nav'); n.textContent = '';
    PAGES.forEach(function (p) {
      var a = h('a', 'nav-item'); a.href = '?page=' + p[0]; a.dataset.fk = 'nav' + p[0]; a.setAttribute('aria-label', p[1]);
      if (st.page === p[0] || (st.page === 'ticket' && p[0] === 'tickets')) a.setAttribute('aria-current', 'page');
      var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('class', 'ic'); svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
      var pa = document.createElementNS('http://www.w3.org/2000/svg', 'path'); pa.setAttribute('d', p[2]); svg.append(pa);
      a.append(svg, h('span', 'nav-label', p[1]));
      a.addEventListener('click', function (e) { e.preventDefault(); go(p[0]); }); n.append(a);
    });
    var c = $('#v4-crumb'); c.textContent = ''; c.append(h('span', '', 'Demo'), h('span', '', '›'));
    var cur = h('span', '', st.page === 'ticket' ? S[st.tk].k : PAGES.filter(function (p) { return p[0] === st.page; })[0][1]); cur.setAttribute('aria-current', 'page'); c.append(cur);
  }
  function go(p, tk) { st.page = p; if (tk != null) st.tk = tk; st.ask = -1; draw('p'); }
  function focusBtn(i, big) {
    var s = S[i], w = h('span', 'v4-act');
    var b = btn(BTN[s.s] + (big ? ' in Focus' : ''), (big && !anyWait() ? 'primary ' : '') + (big ? '' : 'sm'), function (e) { e.stopPropagation(); if (s.s === 'none') { st.ask = st.ask === i ? -1 : i; draw('p'); } else openSess(i); }, 'act' + i);
    b.setAttribute('aria-label', BTN[s.s] + ' ' + s.k + ' in Focus'); if (s.s === 'none') b.setAttribute('aria-expanded', st.ask === i);
    w.append(b);
    if (st.ask === i) { var p = h('div', 'v4-pop'); p.setAttribute('role', 'group'); var t = h('div', 'v4-pop-t'); t.append(h('b', '', 'Start ' + s.k), mark(3)); p.append(t, choices(i)); p.addEventListener('click', function (e) { e.stopPropagation(); }); w.append(p); }
    return w;
  }
  function page() {
    var p = $('#v4-page'); p.textContent = '';
    if (st.page === 'home') {
      p.append(h('h1', '', 'Home'), h('p', 'v4-lead', 'Your pages work as before. Focus sits under all of them and stays open when you change pages.'));
      p.append(h('h2', '', 'Needs you'));
      var g = h('div', 'v4-cards'), w = S.map(function (s, i) { return i; }).filter(function (i) { return S[i].s === 'wait'; });
      w.forEach(function (i) { var s = S[i], c = h('div', 'v4-card'); c.append(pill('wait'), h('b', '', s.k + ' · ' + s.t), h('p', 'meta', 'Has a question for you. Answer it in Focus.'), focusBtn(i)); g.append(c); });
      if (!w.length) g.append(h('p', 'meta', 'Nothing needs you right now.'));
      p.append(g, h('h2', '', 'At work'));
      var l = h('div', 'v4-rows'); S.forEach(function (s, i) { if (s.s !== 'run' || s.free) return; var r = h('div', 'v4-row'); r.append(glyph(s.s), h('b', '', s.k), h('span', 'v4-rt', s.t), focusBtn(i)); l.append(r); }); p.append(l);
    } else if (st.page === 'review') {
      p.append(h('h1', '', 'Review'), h('p', 'v4-lead', 'Finished work waiting for your look.'));
      var c2 = h('div', 'v4-card'); c2.append(h('b', '', 'ORCH-247 · ' + S[3].t), h('p', '', 'All 5 steps done. Merged on green checks.'), focusBtn(3)); var g2 = h('div', 'v4-cards'); g2.append(c2); p.append(g2);
    } else if (st.page === 'ticket') {
      var s = S[st.tk], back = h('a', 'meta', '‹ Tickets'); back.href = '?page=tickets'; back.addEventListener('click', function (e) { e.preventDefault(); go('tickets'); });
      var hd = h('div', 'v4-thead'); hd.append(h('h1', '', s.t), pill(s.s)); var act = h('div', 'v4-tact'); act.append(focusBtn(st.tk, true), mark(2));
      p.append(back, hd, h('p', 'v4-lead', s.s === 'none' ? 'No helper is on this ticket. Start one and it opens in Focus.' : 'A helper is on this ticket. Focus opens beside this page.'), act, h('h2', '', 'Steps'));
      var ol = h('ol', 'v4-todo'); for (var k = 0; k < s.step[1]; k++) ol.append(h('li', k < s.step[0] ? 'on' : '', (k < s.step[0] ? '✓ ' : '○ ') + ['Read the ticket', 'Plan the work', 'Build it', 'Test it', 'Open the pull request', 'Get it merged'][k])); p.append(ol);
    } else {
      p.append(h('h1', '', 'Tickets'), h('p', 'v4-lead', 'One button per ticket. It says what you can do right now.'));
      var list = h('div', 'v4-rows');
      S.forEach(function (s, i) {
        if (s.free) return; var r = h('div', 'v4-row'), a = h('a', 'v4-rk', s.k); a.href = '?page=ticket&tk=' + i; a.dataset.fk = 'tk' + i; a.addEventListener('click', function (e) { e.preventDefault(); go('ticket', i); });
        var wd = h('span', 'meta v4-rw', WORD[s.s]); r.append(glyph(s.s), a, h('span', 'v4-rt', s.t), wd, focusBtn(i)); if (i === 0) r.append(mark(2)); list.append(r);
      });
      p.append(list);
    }
  }

  /* ---------- the Focus layer ---------- */
  function layIcon(m, label) { var b = h('button', 'btn sm v4-lay'); b.type = 'button'; b.dataset.m = m; b.dataset.fk = 'lay' + m; b.title = label; b.setAttribute('aria-label', label); b.setAttribute('aria-pressed', st.mode === m); b.append(h('span', 'v4-ico ' + m)); b.addEventListener('click', function () { setMode(m === 'full' && st.mode === 'full' ? st.back : m); }); return b; }
  function layer() {
    var L = $('#v4-layer'); L.textContent = '';
    var hd = h('header', 'v4-lh'), left = h('div', 'v4-lh-l'), right = h('div', 'v4-lh-r');
    if (st.view === 'start') { left.append(h('h2', '', 'Focus'), mark(1)); }
    else { left.append(btn('‹ All sessions', 'ghost sm', openStart, 'all')); }
    var showSeg = st.view === 'session' && !(off(st.cur) && (!st.split || off(st.cur2)));
    if (st.view === 'session') {
      var seg = h('div', 'segmented'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'Chat or Terminal');
      [['chat', 'Chat'], ['terminal', 'Terminal']].forEach(function (m) { var b = btn(m[1], 'sm', function () { st.term = m[0]; draw('l'); }, 'term' + m[0]); b.setAttribute('aria-pressed', st.term === m[0]); seg.append(b); });
      var sp = btn('Side by side', 'ghost sm v4-split', function () { st.split = !st.split; st.ap = 0; if (st.cur2 === st.cur) st.cur2 = order().filter(function (i) { return i !== st.cur && S[i].s !== 'none'; })[0]; draw('lb'); }, 'split'); sp.setAttribute('aria-pressed', st.split);
      if (showSeg) right.append(seg, mark(4)); right.append(sp, mark(9));
    }
    var lay = h('div', 'segmented v4-lays'); lay.setAttribute('role', 'group'); lay.setAttribute('aria-label', 'Where Focus sits');
    lay.append(layIcon('right', 'Dock right'), layIcon('bottom', 'Dock bottom'), layIcon('full', st.mode === 'full' ? 'Leave full screen (Esc)' : 'Full screen'));
    right.append(lay, mark(7)); hd.append(left, right); L.append(hd);
    var body = h('div', 'v4-lb');
    if (st.view === 'start') body.append(startView());
    else { if (st.split) body.dataset.split = '2'; body.append(pane(st.cur, 0)); if (st.split) body.append(pane(st.cur2, 1)); }
    L.append(body);
    $$('.v4-scroll', L).forEach(function (x) { x.scrollTop = x.scrollHeight; });
    $$('.v4-shelf', L).forEach(function (x) { var f = function () { x.classList.toggle('is-clipped', x.scrollWidth - x.clientWidth - x.scrollLeft > 4); }; x.addEventListener('scroll', f); f(); });
  }
  function startView() {
    var v = h('div', 'v4-start'), ord = order();
    var wait = ord.filter(function (i) { return S[i].s === 'wait'; }), run = ord.filter(function (i) { return S[i].s === 'run' && !S[i].free; }), quiet = ord.filter(function (i) { return (S[i].s === 'idle' || off(i)) && !S[i].free; }), free = ord.filter(function (i) { return S[i].free; });
    function sec(title, count) { var s = h('section', 'v4-sec'), t = h('h3', '', title); if (count != null) t.append(h('span', 'meta', ' ' + count)); s.append(t); v.append(s); return s; }
    var a = sec('Needs you', wait.length || null);
    if (!wait.length) a.append(h('p', 'v4-calm', '✓ Nothing needs you. Your helpers are getting on with it.'));
    wait.forEach(function (i) {
      var s = S[i], c = h('div', 'v4-hero'); var t = h('div', 'v4-hero-t'); t.append(pill('wait'), h('b', '', s.k), h('span', 'v4-rt', s.t));
      var o = h('div', 'v4-opts'); s.opts.forEach(function (x, n) { o.append(btn(x, n ? '' : 'primary', function () { answer(i, x); }, 'opt' + i + n)); }); o.append(btn('Open session', 'ghost', function () { openSess(i); }, 'open' + i));
      c.append(t, h('p', 'v4-q', s.q), o); a.append(c);
    });
    var b = sec('Working', run.length), wall = h('div', 'v4-wall');
    run.forEach(function (i) {
      var s = S[i], c = h('article', 'v4-tile'), t = h('div', 'v4-tile-t'); t.append(glyph('run'), h('b', '', s.k), h('span', 'v4-rt', s.t));
      var pv = h('div', 'v4-prev'); pv.dataset.prev = i; s.log.slice(-3).forEach(function (x) { pv.append(lineEl(x)); }); pv.setAttribute('aria-label', 'Latest lines of ' + s.k);
      var f = h('div', 'v4-tile-f'); f.append(steps(s), btn('Watch', 'sm', function () { openSess(i); }, 'w' + i)); c.append(t, pv, f); wall.append(c);
    });
    if (!run.length) wall.append(h('p', 'meta', 'No helper is working.')); b.append(wall);
    var c3 = sec('Quiet', quiet.length), rows = h('div', 'v4-rows');
    quiet.forEach(function (i) { var s = S[i], r = h('div', 'v4-row'); r.append(glyph(s.s), h('b', '', s.k), h('span', 'v4-rt', s.t), h('span', 'meta v4-rw', s.note), btn(BTN[s.s], 'sm', function () { openSess(i); }, 'q' + i)); rows.append(r); });
    c3.append(rows);
    var d = sec('Without a ticket'); d.firstChild.append(mark(5)); var fr = h('div', 'v4-rows');
    free.forEach(function (i) { var s = S[i], r = h('div', 'v4-row'); r.append(glyph(s.s), h('b', '', s.k), h('span', 'v4-rt', s.note), h('span', 'meta v4-rw', WORD[s.s]), btn('Open', 'sm', function () { openSess(i); }, 'q' + i)); fr.append(r); });
    d.append(fr, newChoices());
    v.append(h('p', 'meta v4-slots', liveCount() + ' of ' + LIVE_MAX + ' places in use (the Manager counts as one). More starts wait in line. Idle sessions close after about an hour; the conversation is kept.'));
    return v;
  }
  function newChoices() {
    var w = h('div', 'v4-new');
    [['Chat helper', '● Hello. What shall we look at?', 'Ask anything, no ticket'], ['Plain terminal', '$ ready', 'An empty terminal in this workspace']].forEach(function (x) {
      var n = S.filter(function (s) { return s.k.indexOf(x[0]) === 0; }).length, b = h('button', 'v4-choice'); b.type = 'button'; b.dataset.fk = 'new' + x[0]; b.append(h('b', '', '+ ' + x[0]), h('span', '', x[2]));
      b.addEventListener('click', function (e) { e.stopPropagation(); addFree(x[0] + (n ? ' ' + (n + 1) : ''), x[1]); }); w.append(b);
    });
    return w;
  }
  function pane(i, slot) {
    var s = S[i], d = h('section', 'v4-pane' + (st.split && st.ap === slot ? ' is-active' : '')); d.setAttribute('aria-label', s.k + ', ' + WORD[s.s]);
    if (st.split) d.addEventListener('focusin', function () { if (st.ap !== slot) { st.ap = slot; $$('.v4-pane').forEach(function (p, n) { p.classList.toggle('is-active', n === slot); }); } });
    var top = h('div', 'v4-ph'); top.append(h('b', 'v4-pk', s.k), h('span', 'v4-rt', s.t), pill(s.s));
    if (slot === 1) { var x = btn('×', 'ghost icon sm', function () { st.split = false; st.ap = 0; draw('lb'); }, 'x2'); x.setAttribute('aria-label', 'Close the second session'); top.append(x); }
    d.append(top);
    if (s.s === 'line') { var ln = h('div', 'v4-empty'); ln.append(h('b', '', s.k + ' is in line'), h('p', 'meta', 'All ' + LIVE_MAX + ' places are in use. It starts by itself when one is free.')); d.append(ln); return d; }
    if (s.s === 'none') { var e = h('div', 'v4-empty'); var et = h('div', 'v4-pop-t'); et.append(h('b', '', 'No helper is on ' + s.k + ' right now'), mark(3)); e.append(et, choices(i), h('p', 'meta', 'Older sessions: only the last one is kept today.')); d.append(e); return d; }
    if (s.s === 'wait') { var ask = h('div', 'v4-ask'), o = h('div', 'v4-opts'); s.opts.forEach(function (t, n) { o.append(btn(t, n ? 'sm' : 'primary sm', function () { answer(i, t); }, 'popt' + i + n)); }); ask.append(h('p', 'v4-q', s.q), o); d.append(ask); }
    if (s.res.length) {
      var sh = h('div', 'v4-shelf'); sh.setAttribute('aria-label', 'Results of ' + s.k);
      s.res.forEach(function (r) { var id = i + r[1], c = h('button', 'v4-rc'); c.type = 'button'; c.dataset.fk = 'rc' + id; c.setAttribute('aria-pressed', st.peek === id); c.append(thumb(r[0]), h('b', '', r[1]), h('span', 'meta', r[2])); c.addEventListener('click', function () { st.peek = st.peek === id ? '' : id; draw('l'); }); sh.append(c); });
      var shw = h('div', 'v4-shelf-w'); shw.append(sh); if (slot === 0) shw.append(mark(10)); d.append(shw);
      s.res.forEach(function (r) { if (st.peek !== i + r[1]) return; var pk = h('div', 'v4-peek'), tx = h('div', 'v4-peek-t'); tx.append(h('b', '', r[1]), h('span', 'meta', r[2] + ' on ' + s.k + '. In the product this opens the real file.'), btn('Close', 'sm', function () { st.peek = ''; draw('l'); }, 'pkx')); pk.append(thumb(r[0], true), tx); d.append(pk); });
    }
    d.append(st.term === 'terminal' ? terminal(i) : chat(i)); return d;
  }
  function terminal(i) {
    var s = S[i], t = h('div', 'v4-term'), sc = h('div', 'v4-scroll'), lines = h('div', 'v4-lines'); lines.dataset.log = i; s.log.forEach(function (x) { lines.append(lineEl(x)); });
    var pr = h('label', 'v4-prompt'); pr.append(h('span', '', '>')); var inp = h('input', 'v4-in'); inp.type = 'text'; inp.autocomplete = 'off'; inp.spellcheck = false; inp.dataset.fk = 'in' + i; inp.value = drafts['t' + i] || ''; inp.disabled = !st.type;
    inp.setAttribute('aria-label', 'Type into the terminal of ' + s.k); inp.placeholder = st.type ? 'Type here, press Enter' : 'Watching only';
    inp.addEventListener('input', function () { drafts['t' + i] = inp.value; });
    inp.addEventListener('keydown', function (e) { if (e.key !== 'Enter' || !inp.value.trim()) return; s.log.push('> ' + inp.value, '● (demo) The helper got your line.'); drafts['t' + i] = ''; draw('l'); touch(i); });
    pr.append(inp); sc.append(lines, pr); t.addEventListener('click', function (e) { if (e.target === sc || e.target === lines || e.target.classList.contains('v4-l')) { if (!String(getSelection())) inp.focus(); } });
    var tm = h('div', 'v4-tmux'); tm.append(h('span', '', '[' + s.k.toLowerCase().replace(/\s+/g, '-') + '] 0:helper*'));
    var lt = h('label', 'v4-type'), cb = h('input', 'switch'); cb.type = 'checkbox'; cb.checked = st.type; cb.dataset.fk = 'type' + i; cb.setAttribute('aria-label', 'Let me type into the terminal of ' + s.k); cb.addEventListener('change', function () { st.type = cb.checked; draw('l'); }); lt.append(cb, h('span', '', st.type ? 'I can type' : 'Watching only')); tm.append(lt);
    t.append(sc, tm); return t;
  }
  function chat(i) {
    var s = S[i], c = h('div', 'v4-chat'), sc = h('div', 'v4-scroll');
    chats[i].forEach(function (m) { if (m[0] === 'ev') { sc.append(h('p', 'v4-ev', m[1])); return; } var b = h('div', 'v4-bub' + (m[0] === 'me' ? ' me' : '')); b.append(h('span', 'meta', m[0] === 'me' ? 'You' : 'Helper'), h('p', '', m[1])); sc.append(b); });
    var f = h('form', 'v4-compose'), inp = h('input', 'input'); inp.type = 'text'; inp.autocomplete = 'off'; inp.dataset.fk = 'msg' + i; inp.placeholder = 'Message the helper'; inp.setAttribute('aria-label', 'Message the helper on ' + s.k); inp.value = drafts['c' + i] || '';
    inp.addEventListener('input', function () { drafts['c' + i] = inp.value; });
    var send = btn('Send', anyWait() ? '' : 'primary', null, 'send' + i); send.type = 'submit';
    f.addEventListener('submit', function (e) { e.preventDefault(); if (!inp.value.trim()) return; chats[i].push(['me', inp.value], ['helper', '(demo) Got it.']); s.log.push('> ' + inp.value); drafts['c' + i] = ''; draw('l'); touch(i); var n = $('[data-fk="msg' + i + '"]'); if (n) n.focus(); });
    f.append(inp, send); c.append(sc, f); return c;
  }

  /* ---------- the bar: always there ---------- */
  function lastLine(s) { return s.s === 'idle' ? s.note : WORD[s.s] + (s.step && s.s !== 'line' ? ' · Step ' + s.step[0] + '/' + s.step[1] : ''); }
  function bar() {
    var B = $('#v4-bar'); B.textContent = '';
    var open = st.mode !== 'strip', nw = S.filter(function (s) { return s.s === 'wait'; }).length;
    var home = h('button', 'v4-home'); home.type = 'button'; home.dataset.fk = 'home'; home.append(h('b', '', 'Focus')); home.setAttribute('aria-pressed', open && st.view === 'start');
    var cn = h('span', nw ? 'v4-cnt' : 'v4-cnt none'); if (nw) cn.append(h('b', '', String(nw)), h('span', 'v4-cnt-w', ' need' + (nw === 1 ? 's' : '') + ' you')); else cn.textContent = 'All calm'; home.append(cn); home.setAttribute('aria-label', 'Focus, all sessions. ' + (nw ? nw + ' waiting for you' : 'Nothing waiting'));
    home.addEventListener('click', openStart); B.append(home, mark(6));
    var chips = h('div', 'v4-chips'), shown = 0, more = 0;
    order().forEach(function (i) {
      var s = S[i]; if (s.s === 'none') return;
      if (s.s === 'run' && ++shown > 4 && i !== st.cur && !(st.split && i === st.cur2)) { more++; return; }
      var on = open && st.view === 'session' && (i === st.cur || (st.split && i === st.cur2)), c = h('button', 'v4-chip ' + s.s); c.type = 'button'; c.dataset.fk = 'chip' + i; c.dataset.chip = i;
      if (on) c.setAttribute('aria-current', 'true'); c.title = s.k + ' · ' + s.t + ' · ' + WORD[s.s] + (s.s === 'wait' ? ': ' + s.q : '');
      var kb = h('b'), kp = s.k.indexOf('ORCH-') === 0; if (kp) kb.append(h('span', 'v4-kp', 'ORCH-')); kb.append(document.createTextNode(kp ? s.k.slice(5) : s.k)); c.setAttribute('aria-label', s.k + ', ' + lastLine(s));
      c.append(glyph(s.s), kb, h('span', 'v4-last', lastLine(s))); c.addEventListener('click', function () { openSess(i); }); chips.append(c);
    });
    if (more) { var mc = h('button', 'v4-chip v4-more'); mc.type = 'button'; mc.dataset.fk = 'more'; mc.append(h('b', '', '+' + more + ' working')); mc.addEventListener('click', openStart); chips.append(mc); }
    B.append(chips, mark(8));
    var nb = btn('+ New', 'ghost sm', function (e) { e.stopPropagation(); st.menu = st.menu === 'new' ? '' : 'new'; draw('b'); }, 'newb'); nb.setAttribute('aria-expanded', st.menu === 'new'); nb.setAttribute('aria-label', 'New session without a ticket'); B.append(nb, mark(5));
    if (st.menu === 'new') { var p = h('div', 'v4-newpop'); p.addEventListener('click', function (e) { e.stopPropagation(); }); p.append(h('b', '', 'New session without a ticket'), newChoices()); B.append(p); }
    var tg = btn(open ? 'Hide' : 'Show', 'ghost sm v4-toggle', toggle, 'toggle'); tg.setAttribute('aria-expanded', open); tg.setAttribute('aria-label', (open ? 'Hide' : 'Show') + ' Focus (' + KEY + ')'); tg.append(h('kbd', '', KEY));
    if (st.mode === 'full') { var es = h('span', 'v4-esc meta'); es.append(h('kbd', '', 'Esc'), document.createTextNode(' leaves full screen')); B.append(es); } else B.append(tg);
  }
  /* a new line arrived for session i: update the places that show it, without redrawing (keeps what you type) */
  function touch(i) {
    var s = S[i];
    $$('[data-log="' + i + '"]').forEach(function (l) { while (l.children.length < s.log.length) l.append(lineEl(s.log[l.children.length])); l.parentNode.scrollTop = l.parentNode.scrollHeight; });
    $$('[data-prev="' + i + '"]').forEach(function (pv) { pv.textContent = ''; s.log.slice(-3).forEach(function (x) { pv.append(lineEl(x)); }); });
    $$('[data-chip="' + i + '"] .v4-last').forEach(function (x) { x.textContent = lastLine(s); });
  }

  /* ---------- the draft ribbon and the Features sheet ---------- */
  function ribbon() {
    var k = Object.keys(picks).filter(function (n) { return picks[n]; }).length, c = $('#v4-cap'); c.textContent = '';
    if (st.f) { var f = F[st.f - 1]; c.append(h('span', 'v4-n static', String(st.f)), h('b', '', f.t + '. '), document.createTextNode(f.what)); c.firstChild.dataset.n = st.f; }
    else c.append(document.createTextNode('Focus is the bar at the bottom. It stays while you change pages. Numbers open a feature.'));
    $('#v4-count').textContent = k + ' of ' + F.length + ' picked';
    var b = $('#v4-features'); b.setAttribute('aria-expanded', st.sheet);
  }
  function sheet() {
    var sh = $('#v4-sheet'); sh.hidden = !st.sheet; sh.textContent = ''; if (!st.sheet) return;
    var k = Object.keys(picks).filter(function (n) { return picks[n]; }).length;
    var hd = h('div', 'v4-sheet-h'), ti = h('div'); ti.append(h('h2', '', 'Features'), h('p', 'meta', k + ' of ' + F.length + ' picked. The numbers match the circles on the page.'));
    var x = btn('×', 'ghost icon sm', function () { st.sheet = false; draw('sr'); $('#v4-features').focus(); }, 'shx'); x.setAttribute('aria-label', 'Close Features'); hd.append(ti, x); sh.append(hd);
    F.forEach(function (f, ix) {
      var n = ix + 1, a = h('article', 'v4-f' + (st.f === n ? ' is-on' : '')); a.id = 'v4-f-' + n; a.tabIndex = -1;
      var t = h('div', 'v4-f-t'), nn = h('span', 'v4-n static', String(n)); nn.dataset.n = n; t.append(nn, h('h3', '', f.t), h('span', 'badge v4-size ' + f.size.toLowerCase(), f.size + ' work'));
      var how = h('p', 'meta muted'); how.append(h('b', '', 'How it works in orch: '), document.createTextNode(f.how));
      var row = h('div', 'v4-f-a'), seg = h('div', 'segmented'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'Your pick for feature ' + n);
      ['keep', 'maybe', 'drop'].forEach(function (o) { var b = btn(o.charAt(0).toUpperCase() + o.slice(1), 'sm', function () { picks[n] = picks[n] === o ? '' : o; store.set('fv4-picks', JSON.stringify(picks)); draw('sr'); }, 'pick' + n + o); b.setAttribute('aria-pressed', picks[n] === o); seg.append(b); });
      var sm = btn('Show me', 'xs v4-show', function () { showMe(n); }, 'show' + n); sm.setAttribute('aria-label', 'Show me feature ' + n + ' in the demo');
      row.append(seg, sm); a.append(t, h('p', '', f.what), how, row); sh.append(a);
    });
    var cp = btn('Copy my picks', 'primary', function () {
      var txt = 'Focus v4 picks\n' + F.map(function (f, ix) { return (ix + 1) + '. ' + f.t + ': ' + (picks[ix + 1] || 'no pick') + ' (' + f.size + ')'; }).join('\n');
      var done = function () { cp.textContent = 'Copied'; setTimeout(function () { cp.textContent = 'Copy my picks'; }, 1500); };
      var fail = function () { var ta = h('textarea', 'input v4-copy'); ta.value = txt; ta.readOnly = true; ta.rows = F.length + 1; ta.setAttribute('aria-label', 'Your picks, select and copy'); cp.after(ta); ta.select(); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(done, fail); else fail();
    }, 'copy');
    var ft = h('div', 'v4-sheet-f'); ft.append(cp); sh.append(ft);
  }
  function showMe(n) {
    var sv = F[n - 1].show; st.f = n; st.sheet = false; st.ask = -1; st.menu = ''; st.split = false; st.peek = '';
    Object.keys(sv).forEach(function (k) { st[k] = sv[k]; }); if (st.mode === 'right' || st.mode === 'bottom') st.back = st.mode;
    if (st.split && st.cur2 === st.cur) st.cur2 = 0;
    draw('plbsr'); var m = $('.v4-n.is-shown:not(.static)'); if (m) { m.scrollIntoView({ block: 'nearest', inline: 'nearest' }); m.focus(); }
  }

  /* ---------- keys, outside clicks, the live tick ---------- */
  $('#v4-features').addEventListener('click', function () { st.sheet = !st.sheet; draw('sr'); if (st.sheet) { var t = $('#v4-sheet h2'); t.tabIndex = -1; t.focus(); } });
  var mk = $('#v4-marks'); mk.checked = !st.marks; mk.addEventListener('change', function () { st.marks = !mk.checked; draw('r'); });
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'j') { e.preventDefault(); toggle(); return; }
    if (e.key !== 'Escape') return;
    if (st.sheet) { st.sheet = false; draw('sr'); $('#v4-features').focus(); }
    else if (st.menu || st.ask >= 0) { st.menu = ''; st.ask = -1; draw('pb'); }
    else if (st.peek) { st.peek = ''; draw('l'); }
    else if (st.mode === 'full') setMode(st.back);
  });
  document.addEventListener('click', function () { if (st.menu || st.ask >= 0) { st.menu = ''; st.ask = -1; draw('pb'); } });
  if (LIVE) setInterval(function () {
    S.forEach(function (s, i) { if (s.s !== 'run' || !s.next.length) return; s.log.push(s.next.shift()); s.note = s.log[s.log.length - 1].slice(2); touch(i); });
  }, 6000);
  draw('plbsr');
  if (st.f && st.sheet) { var r0 = $('#v4-f-' + st.f); if (r0) r0.scrollIntoView({ block: 'center' }); }
})();

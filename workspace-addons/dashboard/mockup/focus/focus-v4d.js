/* Focus draft D (ORCH-251): the live wall of draft B with the bar and layer of draft A. Demo data only; picks stay in this browser. */
(function () {
  'use strict';
  var KEY = 'orch-focus-v4d-picks', IMG = '../../../../workspace/src/orch_ui/static/demo-image.svg';
  var F = [
    [1, 'Live wall', 'Focus opens on every session in bands: Pinned, Needs you, Working, In line, Idle and no session. One summary line on top; each tile says in a plain sentence what its helper does and shows its last lines live.', 'orch run list gives the signal per ticket (working, idle, waiting); the sentence comes from the helper messages, the peek from the read-only screen, refreshed every few seconds.', 'Medium', 'a new page; the data exists', { page: 'focus', view: 'wall' }],
    [2, 'Needs you, answered in one row', 'A session that waits for you is one compact row: the question and its two answers. One click answers it.', 'The "waiting on" value of orch run list plus the open question on the ticket; the answer is sent into the session.', 'Small', 'one row and one send', { page: 'focus', view: 'wall', need: 'ORCH-238' }],
    [3, 'Focus button and Open ticket', 'Every ticket has one Focus button (Watch, Answer, Open or Start). Every session has Open ticket to go the other way.', 'The run signal of the ticket decides the word on the button; the session name is the ticket id.', 'Small', 'one button per ticket, one link per session', { page: 'ticket', tk: 'ORCH-189' }],
    [4, 'Continue, fresh start or an earlier session', 'Start asks one thing: continue the last conversation, make a fresh start, or reopen an earlier session from the history list.', 'The session id is kept on the ticket, so the next start resumes it. To build: orch keeps only the last session today; a history needs new storage.', 'Medium', 'history of sessions per ticket is new', { page: 'focus', view: 'zoom', cur: 'ORCH-189', need: 'ORCH-189' }],
    [5, 'Chat or real terminal', 'Chat shows plain messages with results inside. Terminal is the real screen of the helper: click it and type, select, copy and paste like in the Terminal app.', 'Every helper runs in its own tmux session. Chat is helper messages plus ticket events; no transcript exists.', 'Large', 'a terminal in the browser (xterm.js and a bridge) is new', { page: 'focus', view: 'zoom', cur: 'ORCH-228', term: true }],
    [6, 'Sessions without a ticket', 'Empty helper, Chat helper, Plain terminal and Manager are buttons at the top of Focus and in the New menu of the bar. They are pinned by default.', 'The same per-workspace tmux socket, with a name that is not a ticket id. An empty helper is a helper started with no ticket and no task.', 'Medium', 'sessions outside the ticket limit need rules', { page: 'home', mode: 'bar', menu: 'new' }],
    [7, 'Focus on every page, split in up to 3', 'A calm bar under every page opens Focus at the bottom, on the right or full screen, or closes it to a tab at the side. Inside, 1, 2 or 3 sessions sit next to each other.', 'Pages are separate full loads today. Cheapest honest path: soft page swaps that keep the layer; fallback: a pop-out window. Each pane attaches to its own tmux session.', 'Large', 'no layer survives a page change today', { page: 'home', mode: 'bottom', panes: ['ORCH-228', 'ORCH-232', 'Manager'], cur: 'ORCH-228', term: true }],
    [8, 'Zoom and full screen', 'Click a session and it grows into a large view. Full screen removes everything but a slim strip of the other sessions, and can be split too. Esc goes one step back.', 'Nothing new in orch: the same session, drawn bigger.', 'Small', 'layout only', { page: 'focus', view: 'zoom', cur: 'ORCH-232', term: true, full: true }],
    [9, 'Pin and name', 'Pin any session to keep it first on the wall and in the bar. Click its name to give it your own.', 'To build: a pinned flag and a display name per session, kept next to the session id.', 'Small', 'two small values to store', { page: 'focus', view: 'zoom', cur: 'Manager', ren: 'Manager' }],
    [10, 'Result widgets with a big preview', 'Pictures, pages, tables, charts and pull requests are small reusable widgets. A click opens a big preview on top of the page, with previous and next. Anything else is a plain link with an icon.', 'Files and evidence attached to the ticket, and the links on it. The widgets would live in the style guide.', 'Medium', 'one widget and one preview per file type, built once', { page: 'focus', view: 'zoom', cur: 'ORCH-228', term: false, ov: { src: 'ORCH-228', i: 0 } }, ['See all widget types', { page: 'widgets' }]],
    [11, 'Works with 20 to 30 sessions', 'The bar shows the sessions that need you and your pinned ones; everything else is a count such as "9 in line" that opens a list you can search. The wall bands collapse, scroll and filter.', 'The same run list, grouped by signal. Live places are limited (8 in this demo): the other tickets wait in line and start by themselves.', 'Small', 'grouping and a search box', { page: 'home', mode: 'bar', many: true, list: 'queue' }],
    [12, 'Who runs it, how long, how warm', 'Every session shows its tool (Claude CLI, Codex or a plain terminal), how long it has been open and when it closes for being idle.', 'The start time and the helper kind are known per run. Idle sessions close after about an hour; the conversation is kept and can be continued.', 'Small', 'three values on the tile', { page: 'focus', view: 'zoom', cur: 'ORCH-247' }]
  ];
  var HIST = [['Yesterday 16:40', 'step 2 of 4', 'Made the sketch, then stopped'], ['12 Nov 10:15', 'step 1 of 4', 'Read the ticket and asked about the size of the job'], ['11 Nov 09:02', 'step 1 of 4', 'First try, went off track']];
  var S = [
    { k: 'ORCH-238', t: 'Add files and notes to a ticket', kind: 'ticket', s: 'wait', tool: 'claude', up: 64, step: [3, 5], now: 'Waits for your answer.', qn: 4,
      q: { t: 'Keep the old file name when the same file is added twice?', why: 'The helper suggests keeping it: links people already shared keep working.', a: ['Keep the old name', 'Use the new name'] },
      lines: ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ adds a picture to a ticket (38 ms)', '  ⎿ ✔ adds a note below the files (12 ms)', '⏺ The upload works. One thing only you can decide:', '  Keep the old file name when the same file is added twice?', '  1. Keep the old name (suggested)', '  2. Use the new name', '  Waiting for your answer…'],
      chat: [['e', 'Step 2 done: files can be dropped on a ticket', '14:21'], ['h', 'Uploading works for pictures, pages and tables. Notes sit below the files.', '14:38', 0, 0], ['h', 'One thing I need from you before I go on: when the same file is added twice, should the old name stay?', '14:52', 1]],
      files: [['img', 'ticket-files.png', 'Picture · 14:36'], ['table', 'upload-sizes.csv', 'Table · 3 rows', [['Picture', '2.1 MB'], ['Page', '48 KB'], ['Table', '12 KB']]]] },
    { k: 'ORCH-228', t: 'Phone width and zoom', kind: 'ticket', s: 'run', tool: 'claude', up: 38, step: [4, 5], now: 'Opening the pull request.',
      lines: ['⏺ All 3 widths pass: 1280, 1920 and 390.', '⏺ Bash(git push -u origin fix/phone-width)', '  ⎿ branch fix/phone-width set up to track origin', '⏺ Writing the pull request text.', '⏺ Bash(gh pr create --base develop --draft)', '  ⎿ Creating pull request…'],
      feed: ['  ⎿ pull request 1318 opened as a draft', '⏺ Linking the pull request to the ticket.', '  ⎿ linked', '⏺ Waiting for the checks: 3 of 12 green.', '⏺ Waiting for the checks: 7 of 12 green.', '⏺ Waiting for the checks: 11 of 12 green.'],
      chat: [['e', 'Step 3 done: the page fits a phone at 390', '14:31'], ['h', 'The Home page no longer scrolls sideways on a phone. Here is the picture.', '14:40', 0, 0], ['h', 'Opening the pull request now. I will tell you when the checks are green.', '15:02', 0, 4]],
      files: [['img', 'home-390.png', 'Picture · 14:39'], ['html', 'phone-widths.html', 'Page · before and after'], ['chart', 'Width check', 'Chart · 3 widths'], ['table', 'widths.csv', 'Table · 3 rows', [['1280', 'fits'], ['1920', 'fits'], ['390', 'fits']]], ['pr', 'Pull request 1318', 'Draft · 3 of 12 checks green', [['State', 'Draft'], ['Checks', '3 of 12 green'], ['Changes', '6 files']]], ['link', 'Notes on phone widths', 'Link · team wiki']] },
    { k: 'ORCH-232', t: 'Insights and usage counts', kind: 'ticket', s: 'run', tool: 'codex', up: 22, step: [2, 6], now: 'Running the tests.',
      lines: ['⏺ Bash(node --test tests/insights.test.js)', '  ⎿ ✔ counts skills per day (41 ms)', '  ⎿ ✔ counts keys that were never used (9 ms)', '  ⎿ ✔ empty workspace shows zero, not an error (6 ms)'],
      feed: ['  ⎿ ✔ week view adds up to the day view (17 ms)', '  ⎿ ✔ a failed call counts as failed (8 ms)', '  ⎿ ℹ tests 14 · pass 14 · fail 0', '⏺ Bash(uv run python -m pytest -q tests/test_insights.py)', '  ⎿ ......................  22 passed in 3.1s', '⏺ Tests are green. Drawing the usage chart next.', '⏺ Running the tests once more after the chart.'],
      chat: [['e', 'Step 1 done: counts are collected per day', '13:58'], ['h', 'The counts are in. I am running the tests before I draw the chart.', '15:04', 0, 0]],
      files: [['chart', 'Usage by day', 'Chart · 14 days'], ['html', 'insights-preview.html', 'Page · draft'], ['link', 'usage-raw.json', 'Link · data file']] },
    { k: 'ORCH-247', t: 'Steer a helper from the dashboard', kind: 'ticket', s: 'idle', sl: 'Idle 18 min', tool: 'claude', up: 96, close: 42, step: [5, 5], now: 'Finished and merged. Ready for your review.',
      lines: ['⏺ Bash(orch ref wait ORCH-247 --merge)', '  ⎿ 12 of 12 checks green · merged', '⏺ Done. The Steer button is on the ticket page and', '  pull request 1309 is merged. Ready for your review.'],
      chat: [['e', 'Step 5 done: merged on green checks', '14:44'], ['h', 'Finished. You can try the Steer button on any working ticket.', '14:45', 0, 0]],
      files: [['pr', 'Pull request 1309', 'Merged · 12 of 12 checks green', [['State', 'Merged'], ['Checks', '12 of 12 green'], ['Changes', '9 files']]], ['img', 'steer-button.png', 'Picture · 14:30']] },
    { k: 'ORCH-189', t: 'Manager view', kind: 'ticket', s: 'none', sl: 'No session', tool: 'claude', last: 'yesterday 16:40', step: [2, 4], now: 'Stopped at step 2 of 4, yesterday 16:40.',
      lines: ['⏺ Stopped at step 2 of 4: the sketch is attached.', '  Next would be the list of helpers.', '', '  Session ended yesterday 16:40'],
      chat: [['e', 'Step 2 done: sketch of the Manager view', 'yesterday 16:31'], ['h', 'I stopped here. The sketch is on the shelf; the helper list is next.', 'yesterday 16:40', 0, 0]],
      files: [['img', 'manager-sketch.png', 'Picture · yesterday']] },
    { k: 'Manager', t: 'Looks after the helpers', kind: 'free', s: 'run', tool: 'claude', up: 185, pin: true, now: '4 helpers are live. One waits for you. Nothing is stuck.',
      lines: ['⏺ Bash(orch run list)', '  ⎿ ORCH-238  waiting   an answer from you', '    ORCH-228  working   step 4 of 5', '    ORCH-232  working   step 2 of 6', '    ORCH-247  idle      18 min', '⏺ 4 helpers are live. One waits for you. Nothing is stuck.'],
      feed: ['⏺ Checked again: no change.', '⏺ ORCH-228 opened its pull request.', '⏺ Checked again: tests on ORCH-232 are green.', '⏺ ORCH-247 is idle; it closes by itself after about an hour.'],
      chat: [['h', 'I look at every helper once a minute. One waits for you: ORCH-238.', '15:05', 0, 0]],
      files: [['table', 'helpers.csv', 'Table · 3 rows', [['ORCH-228', 'working'], ['ORCH-232', 'working'], ['ORCH-238', 'waits for you']]]] }
  ];
  var S0 = JSON.stringify(S), EXTRA = null;
  var MORE = [['201', 'Newsletter for November', 'wait'], ['214', 'Price list as a table', 'wait'], ['203', 'Welcome mail for new customers', 'run'], ['205', 'Search in the help pages', 'queue'], ['207', 'Export tickets to a table', 'queue'], ['209', 'Faster first page', 'queue'], ['211', 'Monthly report for sales', 'queue'], ['216', 'Tidy the settings page', 'queue'], ['218', 'Spelling check in mails', 'queue'], ['219', 'New logo on every page', 'queue'], ['222', 'Reminder one day before', 'queue'], ['224', 'Sort the customer list', 'queue'], ['226', 'Holiday notice', 'none'], ['229', 'Bigger text on phones', 'none'], ['231', 'Old links that end nowhere', 'none'], ['234', 'Invoice as a file', 'none'], ['236', 'Colours of the charts', 'none'], ['240', 'Support answers as drafts', 'none']];
  var QS = [{ t: 'Send the newsletter today or on Monday morning?', why: 'The helper suggests Monday: more people open it.', a: ['Send on Monday', 'Send today'] }, { t: 'Show prices with or without tax?', why: 'The helper suggests with tax: it is what customers pay.', a: ['With tax', 'Without tax'] }];
  var NOWS = ['Writing the first draft.', 'Running the tests.', 'Reading the files on the ticket.', 'Taking pictures at three widths.', 'Fixing two failed checks.', 'Waiting for the checks.'];
  var ST = { wait: ['◆', 'Needs you'], run: ['●', 'Working'], idle: ['◐', 'Idle'], none: ['○', 'No session'], queue: ['◷', 'In line'], open: ['▸', 'Open'] };
  var ORDER = { wait: 0, run: 1, open: 2, idle: 3, queue: 4, none: 5 };
  var PAGES = { focus: 'Focus', home: 'Home', tickets: 'Tickets', ticket: 'Tickets', review: 'Review', widgets: 'Widgets' };
  var TOOL = { claude: 'Claude CLI', codex: 'Codex', shell: 'Plain terminal' };
  var NEW = [['Empty helper', 'A helper with no ticket and no task yet'], ['Chat helper', 'Ask anything, no ticket'], ['Plain terminal', 'An empty terminal in this workspace'], ['Manager', 'Looks after all helpers']];
  var st = { page: 'focus', view: 'wall', cur: 'ORCH-238', term: false, mode: 'bar', last: 'bottom', full: false, ask: false, ren: '', menu: '', list: '', lq: '', f: '', col: {}, panes: ['ORCH-238'], act: 0, ov: null, many: false, sheet: false, feat: 0, marks: false, tk: 'ORCH-238' };
  var drafts = {}, picks = {}, uid = 0, feedAt = 0;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  try { picks = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { picks = {}; }

  function $(id) { return document.getElementById(id); }
  function esc(x) { return String(x).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function at(o) { var h = ''; for (var k in o) if (o[k] !== undefined && o[k] !== null && o[k] !== false) h += ' ' + k + '="' + esc(o[k]) + '"'; return h; }
  function btn(cls, act, inner, o) { return '<button class="' + cls + '" type="button" data-act="' + act + '"' + at(o || {}) + '>' + inner + '</button>'; }
  function has(k) { return S.some(function (s) { return s.k === k; }); }
  function by(k) { for (var i = 0; i < S.length; i++) if (S[i].k === k) return S[i]; return S[0]; }
  function live(s) { return s.s === 'run' || s.s === 'wait' || s.s === 'idle' || s.s === 'open'; }
  function max() { return st.many ? 8 : 6; }
  function used() { return S.filter(function (s) { return s.kind !== 'shell' && live(s); }).length; }
  function sorted() { return S.slice().sort(function (a, b) { var w = (b.s === 'wait' ? 1 : 0) - (a.s === 'wait' ? 1 : 0); return w || (b.pin ? 1 : 0) - (a.pin ? 1 : 0) || ORDER[a.s] - ORDER[b.s]; }); }
  function phone() { return window.innerWidth <= 720; }
  function nm(s) { return s.name || s.t; }
  function word(s) { return s.sl && (s.s === 'idle' || s.s === 'none') ? s.sl : ST[s.s][1]; }
  function now(s) { return s.q ? 'Waits for your answer.' : (s.now || word(s)); }
  function dur(m) { return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + (m % 60 ? (m % 60) + ' min' : ''); }
  function warm(s) {
    if (s.kind === 'shell') return 'stays open until you close it';
    if (s.s === 'idle') return 'closes in ' + (s.close || 40) + ' min if left idle';
    if (s.s === 'none') return 'closed, the conversation is kept';
    if (s.s === 'queue') return 'starts when a place is free';
    return s.s === 'wait' ? 'stays warm while it waits for you' : 'stays warm while it works';
  }
  function grp(o) { return o.s === 'run' || o.s === 'open' ? 'run' : (o.s === 'queue' ? 'queue' : 'idle'); }
  function isOpen() { var m = eff(); return (m !== 'bar' && m !== 'side') || zoomed(); }
  function shownIn(o) { return isOpen() && (zoomed() ? o.k === st.cur : st.panes.indexOf(o.k) >= 0); }
  function inChip(o) { return o.s === 'wait' || o.pin || shownIn(o); }
  function zoomed() { return st.page === 'focus' && st.view === 'zoom' && !st.full; }
  function eff() { return st.full ? 'full' : (zoomed() ? (st.mode === 'side' ? 'side' : 'bar') : (phone() && st.mode === 'right' ? 'bottom' : st.mode)); }
  function stat(s, bare) { return '<span class="mw-st" data-s="' + s.s + '"><span class="mw-sym" aria-hidden="true">' + ST[s.s][0] + '</span>' + (bare ? '<span class="sr-only">' + word(s) + '</span>' : word(s)) + '</span>'; }
  function mk(n) { if (!st.marks) return ''; return btn('mw-mk', 'feat', n, { 'data-n': n, 'data-pick': picks[n] || '', 'data-on': st.sheet && st.feat === n ? 1 : false, 'aria-label': 'Feature ' + n + ': ' + F[n - 1][1] }); }
  function ic(d) { return '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">' + d + '</svg>'; }
  var I = {
    pin: ic('<path d="M9 3h6l-1 6 4 4H6l4-4z"/><path d="M12 13v8"/>'),
    full: ic('<path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/>'),
    exit: ic('<path d="M3 8h5V3m8 0v5h5M3 16h5v5m8 0v-5h5"/>'),
    right: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M14 4v16"/>'),
    bottom: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 13h18"/>'),
    side: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M18 4v16"/><path d="m10 9 3 3-3 3"/>'),
    beside: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16M16 10v4M14 12h4"/>'),
    prev: ic('<path d="m14 6-6 6 6 6"/>'), next: ic('<path d="m10 6 6 6-6 6"/>'),
    down: ic('<path d="m6 9 6 6 6-6"/>'), up: ic('<path d="m6 15 6-6 6 6"/>'),
    back: ic('<path d="M11 5l-7 7 7 7M4 12h16"/>'), plus: ic('<path d="M12 5v14M5 12h14"/>'), minus: ic('<path d="M5 12h14"/>'),
    x: ic('<path d="M6 6l12 12M18 6 6 18"/>'), ext: ic('<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>'),
    claude: ic('<path d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9"/>'), codex: ic('<path d="m8 7-5 5 5 5m8-10 5 5-5 5"/>'), shell: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3m5 0h5"/>'),
    img: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m5 18 5-5 4 4 2-2 3 3"/>'),
    html: ic('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>'),
    table: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M10 4v16"/>'),
    chart: ic('<path d="M4 3v17h17M8 16v-4m5 4V7m5 9v-6"/>'),
    pr: ic('<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M6 8.5v7M9 6h5a4 4 0 0 1 4 4v5.5"/>'),
    link: ic('<path d="m10 14 4-4m-6 6-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 2 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/>')
  };
  var TH = {
    img: '<svg viewBox="0 0 120 72" preserveAspectRatio="xMidYMin slice" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><rect class="mw-f1" width="120" height="10" rx="4"/><rect class="mw-f1" x="6" y="16" width="24" height="50" rx="2"/><rect class="mw-f2" x="36" y="16" width="44" height="8" rx="2"/><rect class="mw-f1" x="36" y="30" width="78" height="14" rx="2"/><rect class="mw-f1" x="36" y="50" width="78" height="14" rx="2"/></svg>',
    html: '<svg viewBox="0 0 120 72" preserveAspectRatio="xMidYMin slice" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><rect class="mw-f5" width="120" height="22" rx="4"/><rect class="mw-f2" x="10" y="8" width="46" height="6" rx="2"/><rect class="mw-f1" x="10" y="30" width="100" height="5" rx="2"/><rect class="mw-f1" x="10" y="40" width="84" height="5" rx="2"/><rect class="mw-f1" x="10" y="50" width="92" height="5" rx="2"/><rect class="mw-f3" x="10" y="60" width="30" height="6" rx="2"/></svg>',
    chart: '<svg viewBox="0 0 120 72" preserveAspectRatio="xMidYMax slice" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><path class="mw-l1" d="M10 62h100"/><rect class="mw-f3" x="14" y="40" width="12" height="22" rx="2"/><rect class="mw-f3" x="32" y="30" width="12" height="32" rx="2"/><rect class="mw-f3" x="50" y="36" width="12" height="26" rx="2"/><rect class="mw-f3" x="68" y="18" width="12" height="44" rx="2"/><rect class="mw-f2" x="86" y="10" width="12" height="52" rx="2"/></svg>'
  };
  var GRP = { run: ['●', 'working', 'Working'], queue: ['◷', 'in line', 'In line'], idle: ['◐', 'idle', 'Idle'] };
  var KIND = { img: 'picture', html: 'page', table: 'table', chart: 'chart', pr: 'pull request', link: 'link' };
  function tool(s) { var t = s.kind === 'shell' ? 'shell' : (s.tool || 'claude'); return '<span class="mw-tool">' + I[t] + TOOL[t] + '</span>'; }
  function meta(s) { return '<span class="mw-meta meta">' + tool(s) + (live(s) && s.up !== undefined ? '<span>open ' + dur(s.up) + '</span>' : '') + '<span>' + warm(s) + '</span></span>'; }

  /* ---------- result widgets: one per type, a plain link for the rest (would live in the style guide) ---------- */
  function files(src) { return src === '*' ? SAMPLES : (by(src).files || []); }
  function kv(rows) { return '<span class="mw-kv">' + rows.map(function (r) { return '<span>' + esc(r[0]) + '</span><span>' + esc(r[1]) + '</span>'; }).join('') + '</span>'; }
  function widget(f, src, i, small) {
    var t = f[0];
    if (t === 'link') return '<a class="mw-wl" href="review-preview.html" target="_blank" rel="noopener" data-type="link">' + I.link + '<span class="mw-rn">' + esc(f[1]) + '</span><span class="meta">' + esc(f[2]) + ' · opens in a new tab</span>' + I.ext + '</a>';
    var body = TH[t] ? '<span class="mw-thumb">' + TH[t] + '</span>' : (f[3] && !(small && t === 'pr') ? kv(f[3].slice(0, 3)) : '');
    return btn('mw-wg', 'ov', '<span class="mw-wh2">' + I[t] + '<span class="mw-rn">' + esc(f[1]) + '</span></span>' + body + '<span class="meta">' + esc(f[2]) + '</span>', { 'data-src': src, 'data-i': i, 'data-type': t, 'data-small': small ? 1 : false, 'aria-label': 'Open a big preview of ' + KIND[t] + ' ' + f[1] });
  }
  function ovHTML() {
    if (!st.ov) return '';
    var L = files(st.ov.src), f = L[st.ov.i]; if (!f || f[0] === 'link') return '';
    var ids = L.map(function (x, i) { return i; }).filter(function (i) { return L[i][0] !== 'link'; }), at0 = ids.indexOf(st.ov.i), t = f[0], body;
    if (t === 'html') body = '<iframe class="mw-ovframe" src="review-preview.html" title="' + esc(f[1]) + '"></iframe>';
    else if (TH[t]) body = '<div class="mw-ovpic">' + TH[t] + '</div>';
    else body = '<table class="mw-rx mw-ovtable"><caption class="sr-only">' + esc(f[1]) + '</caption><tbody>' + (f[3] || []).map(function (r) { return '<tr><th scope="row">' + esc(r[0]) + '</th><td>' + esc(r[1]) + '</td></tr>'; }).join('') + '</tbody></table>' + (t === 'pr' ? '<p class="meta">A pull request is the set of changes the helper asks to add. It goes in when all checks are green.</p>' : '');
    var one = ids.length < 2;
    return '<div class="mw-ovscrim" data-act="ovclose"></div><section class="mw-ovbox" role="dialog" aria-modal="true" aria-label="Preview of ' + esc(KIND[t] + ' ' + f[1]) + '"><header class="mw-ovh">' + I[t] + '<h2>' + esc(f[1]) + '</h2><span class="meta">' + esc(f[2]) + (one ? '' : ' · ' + (at0 + 1) + ' of ' + ids.length) + '</span><span class="grow"></span>' + (one ? '' : btn('btn icon sm ghost', 'ovnav', I.prev, { 'data-d': -1, 'aria-label': 'Previous result' }) + btn('btn icon sm ghost', 'ovnav', I.next, { 'data-d': 1, 'aria-label': 'Next result' })) + btn('btn sm ghost', 'ovclose', I.x + '<span>Close</span>', { id: 'mw-ovx' }) + '</header><div class="mw-ovb" data-type="' + t + '">' + body + '</div></section>';
  }
  function ovStep(d) {
    var L = files(st.ov.src), ids = L.map(function (x, i) { return i; }).filter(function (i) { return L[i][0] !== 'link'; });
    st.ov.i = ids[(ids.indexOf(st.ov.i) + d + ids.length) % ids.length]; render(d < 0 ? '[data-act=ovnav][data-d="-1"]' : '[data-act=ovnav][data-d="1"]');
  }
  function shelf(s, withMk) {
    var h = '<aside class="mw-shelf" aria-label="Results"><div class="mw-sh"><h2>Results</h2>' + (withMk ? mk(10) : '') + '</div>';
    if (!s.files || !s.files.length) return h + '<p class="meta">Nothing yet. Pictures, pages and tables show up here.</p></aside>';
    var w = '', l = '';
    s.files.forEach(function (f, i) { if (f[0] === 'link') l += widget(f, s.k, i); else w += widget(f, s.k, i, true); });
    return h + '<div class="mw-res-list">' + w + '</div>' + (l ? '<div class="mw-links">' + l + '</div>' : '') + '</aside>';
  }

  /* ---------- pieces of a session ---------- */
  function steps(s) {
    if (!s.step) return '<span class="meta">No ticket</span>';
    var h = '<span class="mw-steps" role="img" aria-label="Step ' + s.step[0] + ' of ' + s.step[1] + '">';
    for (var i = 1; i <= s.step[1]; i++) h += '<i' + (i <= s.step[0] ? ' data-on="1"' : '') + '></i>';
    return h + '</span><span class="meta">Step ' + s.step[0] + ' of ' + s.step[1] + '</span>';
  }
  /* the question card already shows the question: its terminal lines and chat message stay out while it is open */
  function shown(s) { return s.q && s.qn ? s.lines.slice(0, -s.qn) : s.lines; }
  function screenText(s) {
    var l = shown(s).slice(), t = s.typed || '';
    if (!live(s)) return l.join('\n');
    if (s.kind === 'shell') l[l.length - 1] = l[l.length - 1] + ' ' + t; else l.push('> ' + t);
    return l.join('\n');
  }
  function peekText(s) { return shown(s).filter(function (x) { return x.trim(); }).slice(-3).join('\n'); }
  function qHTML(s, quiet) {
    return '<div class="mw-q" role="group" aria-label="Question from the helper"><p class="mw-qt">' + esc(s.q.t) + '</p><p class="meta">' + esc(s.q.why) + '</p><div class="mw-ans">' + btn('btn ' + (quiet ? 'outline' : 'primary'), 'answer', esc(s.q.a[0]), { 'data-k': s.k, 'data-a': 0 }) + btn('btn outline', 'answer', esc(s.q.a[1]), { 'data-k': s.k, 'data-a': 1 }) + '</div></div>';
  }
  function chatMsgs(s) {
    return s.chat.filter(function (m) { return !(s.q && m[3]); }).map(function (m, i) {
      if (m[0] === 'e') return '<p class="mw-ev meta"><span aria-hidden="true">✓</span> ' + esc(m[1]) + ' · ' + esc(m[2]) + '</p>';
      var f = m[4] !== undefined && s.files && s.files[m[4]] && m[1].indexOf('picture') + m[1].indexOf('pull request') > -2 ? s.files[m[4]] : null;
      return '<div class="mw-msg" data-w="' + m[0] + '"><span class="meta">' + (m[0] === 'y' ? 'You' : 'Helper') + ' · ' + esc(m[2]) + '</span><p>' + esc(m[1]) + '</p>' + (f ? '<div class="mw-inmsg">' + widget(f, s.k, m[4], true) + '</div>' : '') + '</div>';
    }).join('');
  }
  function chatHTML(s, prim) {
    var id = 'mw-i' + (++uid);
    return '<div class="mw-chat" data-chat="' + esc(s.k) + '" role="log" aria-label="Messages and ticket events">' + chatMsgs(s) + '</div><form class="mw-comp" data-k="' + esc(s.k) + '" data-f="chat"><label class="sr-only" for="' + id + '">Message to the helper on ' + esc(s.k) + '</label><input class="input" id="' + id + '" data-d="c:' + esc(s.k) + '" value="' + esc(drafts['c:' + s.k] || '') + '" placeholder="Message the helper" autocomplete="off"><button class="btn ' + (prim ? 'primary' : 'outline') + '" type="submit">Send</button></form>';
  }
  function termHTML(s) {
    return '<div class="mw-term"><div class="mw-tbar"><span class="meta">Terminal · click and type · select text to copy it</span>' + btn('btn xs ghost', 'copyterm', 'Copy', { 'data-k': s.k }) + '</div><pre class="mw-screen" data-screen="' + esc(s.k) + '" tabindex="0" role="textbox" aria-multiline="true" aria-label="Terminal of ' + esc(s.k) + '. Type here, Enter sends the line.">' + esc(screenText(s)) + '</pre></div>';
  }
  function histHTML(s) {
    return '<div class="mw-old"><h3>Earlier sessions <span class="chip">To build</span></h3><ul>' + HIST.map(function (x, i) {
      return '<li><span class="mw-hd">' + x[0] + '</span><span class="meta">reached ' + x[1] + '</span><span class="mw-hs">' + x[2] + '</span>' + btn('btn outline sm', 'reopen', 'Reopen', { 'data-k': s.k, 'data-i': i, 'aria-label': 'Reopen the session from ' + x[0] }) + '</li>';
    }).join('') + '</ul><p class="meta">Today orch keeps only the last session of a ticket. Keeping more of them, each with a date and a short summary, is new work.</p></div>';
  }
  function startHTML(s, withMk) {
    var on = live(s);
    var h = '<div class="mw-start"><h2>' + (on ? 'This session and earlier ones' : 'Start a helper on this ' + (s.kind === 'ticket' ? 'ticket' : 'session')) + (withMk ? mk(4) : '') + '</h2>';
    h += '<p class="meta">A start uses 1 of ' + max() + ' helper places. If all are in use it waits in line. Now ' + used() + ' of ' + max() + ' are in use.</p>';
    if (on) h += '<p class="mw-warn"><span aria-hidden="true">!</span> Changing the session interrupts the work in progress.</p>';
    h += '<div class="mw-choices">';
    if (on) h += '<div class="mw-choice"><h3>Keep going</h3><p class="meta">Nothing changes. The helper keeps its conversation.</p>' + btn('btn outline', 'askoff', 'Keep going') + '</div>';
    else h += '<div class="mw-choice"><h3>Continue where it stopped</h3><p class="meta">Keeps the last conversation' + (s.last ? ' from ' + esc(s.last) : '') + '. Best when the work is half done.</p>' + btn('btn outline', 'start', 'Continue', { 'data-how': 'continue', 'data-k': s.k }) + '</div>';
    h += '<div class="mw-choice"><h3>Fresh start</h3><p class="meta">The helper reads the ticket again. The earlier talk is not used. Best when it went off track.</p>' + btn('btn outline', 'start', 'Start again', { 'data-how': 'clean', 'data-k': s.k, 'aria-label': 'Fresh start on ' + s.k }) + '</div></div>';
    return h + histHTML(s) + '</div>';
  }
  function seg(term, withMk) {
    return '<span class="mw-view"><span class="segmented" role="group" aria-label="View">' + btn('btn sm', 'view', 'Chat', { 'data-v': 'chat', 'aria-pressed': String(!term) }) + btn('btn sm', 'view', 'Terminal', { 'data-v': 'term', 'aria-pressed': String(!!term) }) + '</span>' + (withMk ? mk(5) : '') + '</span>';
  }
  function pinBtn(s) { return btn('btn icon sm ghost', 'pin', I.pin, { 'data-k': s.k, 'aria-pressed': String(!!s.pin), 'aria-label': (s.pin ? 'Unpin ' : 'Pin ') + s.k }); }
  function besideBtn(s) { return live(s) ? btn('btn icon sm ghost mw-nophone', 'beside', I.beside, { 'data-k': s.k, 'aria-label': 'Open ' + s.k + ' beside what is open in Focus' }) : ''; }
  function tkLink(s) { return s.kind === 'ticket' ? btn('mw-tkl', 'ticket', 'Open ticket', { 'data-k': s.k, 'aria-label': 'Open ticket ' + s.k }) : ''; }
  function pane(k, size, o) {
    o = o || {};
    var s = by(k), asking = s.s === 'none' || (o.main && st.ask), term = s.kind === 'shell' || st.term, id = 'mw-i' + (++uid);
    var segOk = s.kind !== 'shell' && !asking && s.s !== 'queue', qOut = size === 'md' && s.q && !asking;
    var h = '<section class="mw-pane" data-size="' + size + '" data-s="' + s.s + '" data-k="' + esc(s.k) + '"' + (o.main ? ' data-on="1"' : '') + ' aria-label="' + esc(s.k + ', ' + nm(s)) + '"><header class="mw-ph">' + (o.pre || '') + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span>';
    if (o.main && st.ren === s.k) h += '<form class="mw-ren" data-f="ren" data-k="' + esc(s.k) + '"><label class="sr-only" for="' + id + '">Name of this session</label><input class="input" id="' + id + '" value="' + esc(nm(s)) + '" maxlength="60" autocomplete="off"><button class="btn outline sm" type="submit">Save name</button></form>';
    else if (o.main) h += btn('mw-pt truncate', 'ren', esc(nm(s)), { 'data-k': s.k, title: 'Click to rename', 'aria-label': 'Rename ' + nm(s) }) + (o.mk ? mk(9) : '');
    else if (o.sel) h += btn('mw-pt truncate', 'act', esc(nm(s)), { 'data-k': s.k, 'aria-label': 'Select the pane of ' + s.k });
    else h += '<span class="mw-pt truncate">' + esc(nm(s)) + '</span>';
    if (segOk && size === 'lg') h += seg(term, o.mk);
    h += (o.tools || '');
    var r2 = (segOk && size !== 'lg' ? seg(term, false) : '') + (o.tools2 || '') + (size === 'sm' ? '' : meta(s) + (o.mk ? mk(12) : '') + tkLink(s));
    if (r2) h += '<span class="mw-prow">' + r2 + '</span>';
    h += '</header><div class="mw-pb">' + (qOut ? '<div class="mw-qwrap">' + qHTML(s, o.quiet) + '</div>' : '') + '<div class="mw-pmain">';
    if (asking) h += startHTML(s, o.mk);
    else if (s.s === 'queue') h += '<div class="mw-start"><h2>In line</h2><p class="meta">All ' + max() + ' helper places are in use. This one starts by itself when a place is free. Idle helpers close after about an hour.</p></div>';
    else h += (s.q && !qOut ? qHTML(s, o.quiet) : '') + (term ? termHTML(s) : chatHTML(s, o.prim && !s.q));
    h += '</div>' + (size === 'sm' || o.noshelf ? '' : shelf(s, o.mk)) + '</div></section>';
    return h;
  }
  function histBtn(s) { return s.kind !== 'shell' ? btn('btn sm ghost', st.ask ? 'askoff' : 'ask', 'History', { 'aria-pressed': String(!!st.ask && live(s)) }) : ''; }
  function paneTools(s) { return pinBtn(s); }

  /* ---------- Focus page: the wall in bands, and zoom ---------- */
  function tileActs(s) { return '<span class="grow"></span>' + tkLink(s) + (s.s === 'none' ? btn('btn outline sm', 'zoom', 'Start', { 'data-k': s.k }) : '') + pinBtn(s) + besideBtn(s); }
  function openB(s, cls, inner) { return btn(cls, 'zoom', inner, { 'data-k': s.k, 'aria-label': 'Open ' + s.k + ', ' + nm(s) + ', ' + word(s) }); }
  function tile(s) {
    return '<article class="mw-tile mw-work" data-tile="' + esc(s.k) + '" data-s="' + s.s + '">' + openB(s, 'mw-topen', '<span class="mw-thead">' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span></span><span class="mw-tt">' + esc(nm(s)) + '</span><span class="mw-now" data-now="' + esc(s.k) + '">' + esc(now(s)) + '</span>' + (live(s) ? '<span class="mw-peek" data-peek="' + esc(s.k) + '" aria-hidden="true">' + esc(peekText(s)) + '</span>' : '')) + (s.q ? '<div class="mw-tq">' + qHTML(s, true) + '</div>' : '') + meta(s) + '<footer class="mw-tfoot">' + steps(s) + tileActs(s) + '</footer></article>';
  }
  function line(s) {
    return '<div class="mw-line" data-tile="' + esc(s.k) + '" data-s="' + s.s + '">' + openB(s, 'mw-lopen', stat(s) + '<span class="mw-key">' + esc(s.k) + '</span><span class="mw-tt">' + esc(nm(s)) + '</span><span class="mw-lnow" data-now="' + esc(s.k) + '">' + esc(now(s)) + '</span>') + '<span class="mw-lmeta meta">' + tool(s) + '<span>' + warm(s) + '</span></span>' + tkLink(s) + (s.s === 'none' ? btn('btn outline sm', 'zoom', 'Start', { 'data-k': s.k }) : '') + pinBtn(s) + '</div>';
  }
  function band(id, title, list, draw, cls, empty, extra) {
    var col = !!st.col[id];
    return '<section class="mw-band" data-band="' + id + '"><div class="mw-bh"><h2>' + btn('mw-bt', 'col', '<span class="mw-chev" aria-hidden="true">' + (col ? '▸' : '▾') + '</span>' + title + ' (' + list.length + ')', { 'data-id': id, 'aria-expanded': String(!col) }) + '</h2>' + (extra || '') + '</div>' + (col ? '' : (list.length ? '<div class="' + cls + '">' + list.map(draw).join('') + '</div>' : '<p class="meta mw-none">' + empty + '</p>')) + '</section>';
  }
  function needRow(s, i) {
    return '<article class="mw-nrow" data-tile="' + esc(s.k) + '" data-s="wait">' + openB(s, 'mw-lopen', stat(s, true) + '<span class="mw-key">' + esc(s.k) + '</span><span class="mw-tt">' + esc(nm(s)) + '</span>') + '<span class="mw-nq">' + esc(s.q.t) + '</span><span class="mw-ans">' + btn('btn sm ' + (i ? 'outline' : 'primary'), 'answer', esc(s.q.a[0]), { 'data-k': s.k, 'data-a': 0 }) + btn('btn sm outline', 'answer', esc(s.q.a[1]), { 'data-k': s.k, 'data-a': 1 }) + '</span>' + (i ? '' : mk(2)) + '</article>';
  }
  function bandsHTML() {
    var f = st.f.trim().toLowerCase(), all = sorted().filter(function (s) { return !f || (s.k + ' ' + nm(s) + ' ' + word(s)).toLowerCase().indexOf(f) >= 0; });
    var need = all.filter(function (s) { return s.s === 'wait'; }), pin = all.filter(function (s) { return s.pin && s.s !== 'wait'; }), rest = all.filter(function (s) { return !s.pin && s.s !== 'wait'; });
    var by3 = function (g) { return rest.filter(function (s) { return grp(s) === g; }); }, inl = by3('queue');
    if (f && !all.length) return '<p class="meta mw-none">No session matches "' + esc(st.f) + '".</p>';
    return (pin.length || !f ? band('pin', 'Pinned', pin, tile, 'mw-works', 'Nothing is pinned. Pin a session to keep it here.', mk(9)) : '') + band('need', 'Needs you', need, needRow, 'mw-nrows', 'Nobody needs you right now.') + band('run', 'Working', by3('run'), tile, 'mw-works', 'No helper is working on a ticket.', mk(12)) + (inl.length ? band('queue', 'In line', inl, line, 'mw-lines', '') : '') + band('idle', 'Idle and no session', by3('idle'), line, 'mw-lines', 'Every ticket has a working helper.');
  }
  function wallHTML() {
    var c = { wait: 0, run: 0, queue: 0, idle: 0 };
    S.forEach(function (s) { c[s.s === 'wait' ? 'wait' : grp(s)]++; });
    var part = function (n, g, w) { return n ? '<span class="mw-st" data-s="' + g + '"><span class="mw-sym" aria-hidden="true">' + ST[g][0] + '</span>' + n + ' ' + w + '</span>' : ''; };
    var h = '<div class="mw-wall"><header class="mw-wh"><div><div class="mw-h1"><h1>Focus</h1>' + mk(1) + '</div><p class="mw-hero" role="status">' + (c.wait ? part(c.wait, 'wait', c.wait === 1 ? 'needs you' : 'need you') : '<span class="mw-st">Nobody needs you</span>') + part(c.run, 'run', 'working') + part(c.queue, 'queue', 'in line') + part(c.idle, 'idle', 'idle') + '</p><p class="meta">' + S.length + ' sessions · ' + used() + ' of ' + max() + ' helper places in use</p></div>';
    h += '<div class="mw-new" role="group" aria-label="New session without a ticket">' + mk(6) + NEW.map(function (o) { return btn('btn outline sm', 'new', (has(o[0]) ? '' : '<span aria-hidden="true">+</span> ') + o[0], { 'data-k': o[0], title: has(o[0]) ? 'Already open: go to it' : o[1] }); }).join('') + '</div></header>';
    h += '<div class="mw-tools"><label class="sr-only" for="mw-filter">Filter sessions</label><input class="input" id="mw-filter" type="search" placeholder="Filter by name, ticket or status" value="' + esc(st.f) + '" autocomplete="off">' + mk(11) + '</div>';
    return h + '<div id="mw-bands" class="mw-bands"' + (st.many ? ' data-many="1"' : '') + '>' + bandsHTML() + '</div></div>';
  }
  function zoomHTML() {
    var s = by(st.cur);
    var tools = histBtn(s) + paneTools(s) + '<span class="mw-view">' + mk(8) + btn('btn icon sm ghost', 'full', I.full, { 'aria-label': 'Full screen' }) + '</span>';
    return '<div class="mw-zoom"><h1 class="sr-only">Focus: ' + esc(s.k) + '</h1>' + pane(s.k, 'lg', { main: true, prim: true, mk: true, pre: btn('btn sm ghost', 'back', I.back + '<span>Wall</span>'), tools: tools }) + '</div>';
  }

  /* ---------- mock pages ---------- */
  function verb(s) { return { wait: 'Answer', run: 'Watch', idle: 'Open', none: 'Start', queue: 'In line', open: 'Open' }[s.s]; }
  function fbtn(s, long) { return btn('btn outline sm', 'focus', verb(s) + (long ? ' in Focus' : ''), { 'data-k': s.k, 'aria-label': verb(s) + ' ' + s.k + ' in Focus' }); }
  function row(s) { return '<div class="mw-row">' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span>' + btn('mw-rt', 'ticket', esc(s.t), { 'data-k': s.k }) + fbtn(s) + '</div>'; }
  function tks() { return S.filter(function (s) { return s.kind === 'ticket'; }); }
  var SAMPLES = [['img', 'home-390.png', 'Picture · 14:39'], ['html', 'phone-widths.html', 'Page · before and after'], ['table', 'widths.csv', 'Table · 3 rows', [['1280', 'fits'], ['1920', 'fits'], ['390', 'fits']]], ['chart', 'Usage by day', 'Chart · 14 days'], ['pr', 'Pull request 1318', 'Draft · 3 of 12 checks green', [['State', 'Draft'], ['Checks', '3 of 12 green'], ['Changes', '6 files']]], ['link', 'Notes on phone widths', 'Link · team wiki']];
  var PG = {
    home: function () {
      var need = tks().filter(function (s) { return s.s === 'wait'; }), work = tks().filter(function (s) { return s.s === 'run'; }).slice(0, 5);
      return '<div class="mw-pg"><h1>Home</h1><p class="meta">The Focus bar stays under every page. Open a session from it, type a line, then change page: it is still there.</p><section class="card pad"><h2>Needs you</h2>' + (need.length ? need.map(row).join('') : '<p class="meta">Nothing needs you right now.</p>') + '</section><section class="card pad"><h2>Working now</h2>' + work.map(row).join('') + '</section></div>';
    },
    tickets: function () {
      return '<div class="mw-pg"><div class="mw-h1"><h1>Tickets</h1>' + mk(3) + '</div><p class="meta">Click a title to open the ticket. The button opens its helper in Focus.</p><section class="card pad" aria-label="All tickets">' + tks().map(row).join('') + '</section></div>';
    },
    ticket: function () {
      var s = by(st.tk), names = ['Read the ticket', 'Sketch the change', 'Build it', 'Test it at three widths', 'Open the pull request', 'Get it merged'];
      var h = '<div class="mw-pg"><p class="meta">' + btn('mw-tkl', 'page', '‹ All tickets', { 'data-p': 'tickets' }) + '</p><div class="mw-h1"><h1>' + esc(s.t) + '</h1>' + mk(3) + '</div><p class="mw-thead mw-tkhead">' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span>' + meta(s) + '</p><div class="mw-two"><section class="card pad"><h2>Steps</h2><ol class="mw-cl">';
      for (var i = 1; i <= s.step[1]; i++) h += '<li' + (i <= s.step[0] ? ' data-on="1"' : '') + '><span aria-hidden="true">' + (i <= s.step[0] ? '✓' : '○') + '</span> ' + names[i - 1] + (i <= s.step[0] ? '<span class="sr-only"> (done)</span>' : '') + '</li>';
      h += '</ol><div class="mw-ans">' + fbtn(s, true) + '</div></section><section class="card pad"><h2>Results</h2><p class="meta">The same widgets as in Focus.</p><div class="mw-res-list">' + (s.files || []).map(function (f, i) { return f[0] === 'link' ? '' : widget(f, s.k, i, true); }).join('') + '</div><div class="mw-links">' + (s.files || []).map(function (f, i) { return f[0] === 'link' ? widget(f, s.k, i) : ''; }).join('') + '</div></section></div><section class="card pad">' + histHTML(s) + '</section></div>';
      return h;
    },
    review: function () {
      return '<div class="mw-pg"><h1>Review</h1><p class="meta">Results that wait for your look. Focus stays open while you check them.</p><section class="card pad mw-rev"><span class="mw-thumb">' + TH.img + '</span><div><h2>Steer a helper from the dashboard</h2><p class="meta">ORCH-247 · merged on green checks · 1 picture, 1 pull request</p><div class="mw-ans">' + btn('btn outline sm', 'focus', 'Open in Focus', { 'data-k': 'ORCH-247' }) + '</div></div></section><section class="card pad mw-rev"><span class="mw-thumb">' + TH.html + '</span><div><h2>Newsletter draft</h2><p class="meta">A page to read · no helper is running</p><div class="mw-ans"><a class="btn outline sm" href="newsletter-preview.html" target="_blank" rel="noopener">Open page</a></div></div></section></div>';
    },
    widgets: function () {
      return '<div class="mw-pg"><div class="mw-h1"><h1>Widgets</h1>' + mk(10) + '</div><p class="meta">Draft: these result widgets would live in the style guide and be reusable on ticket pages too, not only in Focus. One of each type.</p><div class="mw-wgrid">' + SAMPLES.map(function (f, i) { return '<section class="card pad mw-wsample"><h2>' + KIND[f[0]].charAt(0).toUpperCase() + KIND[f[0]].slice(1) + (f[0] === 'link' ? ' (no widget)' : '') + '</h2>' + widget(f, '*', i) + '</section>'; }).join('') + '</div><p class="meta">' + btn('mw-tkl', 'page', '‹ Back to Focus', { 'data-p': 'focus' }) + '</p></div>';
    }
  };

  /* ---------- the layer: bar on every page, a panel (bottom, right, full), small windows, or closed to the side ---------- */
  function chip(o, on) {
    return btn('mw-swb', 'switch', stat(o, !on) + '<span class="mw-cn truncate">' + esc(o.name || o.k.replace('ORCH-', '')) + '</span>', { 'data-k': o.k, 'data-s': o.s, 'aria-pressed': String(on), 'aria-label': o.k + ', ' + nm(o) + ', ' + word(o), title: o.k + ' · ' + nm(o) });
  }
  function chipsHTML() {
    var h = '', c = { run: 0, queue: 0, idle: 0 };
    sorted().forEach(function (o) { if (inChip(o)) h += chip(o, shownIn(o)); else c[grp(o)]++; });
    ['run', 'queue', 'idle'].forEach(function (g) {
      if (c[g]) h += btn('mw-swb mw-grp', 'list', c[g] + ' ' + GRP[g][1] + I.up, { 'data-l': g, 'aria-expanded': String(st.list === g), 'aria-label': c[g] + ' ' + GRP[g][1] + ': show the list' });
    });
    return h + mk(11);
  }
  function listRows() {
    var q = st.lq.trim().toLowerCase(), l = sorted().filter(function (o) { return !inChip(o) && grp(o) === st.list && (!q || (o.k + ' ' + nm(o)).toLowerCase().indexOf(q) >= 0); });
    return l.length ? l.map(function (o) { return btn('mw-opt mw-lrow', 'switch', stat(o, true) + '<span class="mw-key">' + esc(o.k) + '</span><span class="mw-rn truncate">' + esc(nm(o)) + '</span><span class="meta truncate">' + esc(now(o)) + '</span>', { 'data-k': o.k }); }).join('') : '<p class="meta">No session matches.</p>';
  }
  function popHTML(mode) {
    if (st.menu === 'new') return '<div class="mw-pop" role="group" aria-label="New session without a ticket"><p class="mw-poph">New session without a ticket</p><div class="mw-plist">' + NEW.map(function (o) { return btn('mw-opt', 'new', '<strong>' + o[0] + '</strong><span class="meta">' + (has(o[0]) ? 'Already open: go to it' : o[1]) + '</span>', { 'data-k': o[0] }); }).join('') + '</div><p class="meta">' + used() + ' of ' + max() + ' helper places in use</p></div>';
    if (st.menu === 'pos') {
      var po = function (act, m, icon, label, on, cls) { return btn('mw-opt mw-posopt' + (cls || ''), act, icon + '<span>' + label + '</span>', { 'data-m': m, 'aria-pressed': String(on) }); };
      return '<div class="mw-pop" role="group" aria-label="Where Focus sits"><p class="mw-poph">Where Focus sits</p><div class="mw-plist">' + po('mode', 'bottom', I.bottom, 'At the bottom', mode === 'bottom') + po('mode', 'right', I.right, 'On the right', mode === 'right', ' mw-nophone') + po('full', '', I.full, 'Full screen', false) + po('mode', 'bar', I.down, 'Bar only', mode === 'bar') + po('mode', 'side', I.side, 'Closed to the side', false) + '</div></div>';
    }
    if (st.list) {
      var n = sorted().filter(function (o) { return !inChip(o) && grp(o) === st.list; }).length;
      return '<div class="mw-pop" role="group" aria-label="' + GRP[st.list][2] + ' sessions"><p class="mw-poph">' + GRP[st.list][2] + ' (' + n + ')</p>' + (n > 6 ? '<label class="sr-only" for="mw-lq">Search sessions</label><input class="input" id="mw-lq" type="search" placeholder="Search ' + GRP[st.list][1] + ' sessions" value="' + esc(st.lq) + '" autocomplete="off">' : '') + '<div class="mw-plist" id="mw-plist">' + listRows() + '</div></div>';
    }
    return '';
  }
  function barHTML(mode) {
    var w = S.filter(function (x) { return x.s === 'wait'; }).length, full = mode === 'full';
    var h = '<div class="mw-bar" role="group" aria-label="Focus bar">' + btn('mw-home', 'home', '<b>Focus</b><span class="mw-cnt"' + (w ? ' data-s="wait"' : '') + '>' + (w ? w + (w === 1 ? ' needs you' : ' need you') : 'All calm') + '</span>', { 'aria-label': 'Focus start page. ' + (w ? w + ' waiting for you' : 'Nothing is waiting') }) + (full ? '' : mk(7));
    h += '<nav class="mw-sw" aria-label="Sessions">' + chipsHTML() + '</nav>';
    if (full) return h + popHTML(mode) + '<span class="meta mw-hint">Esc to leave</span>' + btn('btn icon sm ghost', 'full', I.exit, { 'aria-label': 'Leave full screen' }) + '</div>';
    h += btn('btn sm ghost', 'menu', I.plus + '<span class="mw-wide">New</span>', { 'data-m': 'new', 'aria-expanded': String(st.menu === 'new'), 'aria-label': 'New session without a ticket' });
    if (!zoomed()) h += btn('btn sm ghost mw-pos', 'menu', I[mode === 'right' ? 'right' : 'bottom'] + '<span class="mw-wide">' + (mode === 'bar' ? 'Open' : (mode === 'right' ? 'Right' : 'Bottom')) + '</span>' + I.up, { 'data-m': 'pos', 'aria-expanded': String(st.menu === 'pos'), 'aria-label': 'Where Focus sits: ' + (mode === 'bar' ? 'bar only' : mode) });
    return h + popHTML(mode) + '</div>';
  }
  function layerHTML() {
    var mode = eff(), w = S.filter(function (x) { return x.s === 'wait'; }).length;
    if (mode === 'side') return btn('mw-edge', 'mode', '<span class="mw-edget">Focus</span>' + (w ? '<span class="mw-cnt" data-s="wait"><span aria-hidden="true">◆</span> ' + w + '</span>' : ''), { 'data-m': st.last, 'aria-label': 'Open Focus again. ' + (w ? w + ' waiting for you' : 'Nothing is waiting') });
    var panel = '', full = mode === 'full', n = st.panes.length;
    if (mode !== 'bar') panel = '<div class="mw-panel" data-mode="' + mode + '" data-n="' + n + '">' + st.panes.map(function (k, i) {
      var s = by(k), on = i === st.act, tools = '';
      if (on) tools += pinBtn(s) + (n < 3 ? btn('btn sm ghost mw-nophone', 'addpane', I.beside + '<span class="mw-wide">Add beside</span>', { 'aria-label': 'Add another session beside this one' }) : '');
      if (n > 1) tools += btn('btn icon sm ghost mw-nophone', 'closepane', I.x, { 'data-k': k, 'aria-label': 'Close the pane of ' + k });
      return pane(k, full ? 'lg' : 'md', { main: on, sel: !on, noshelf: n > 1 || (full && window.innerWidth < 1600), tools: tools, tools2: on ? histBtn(s) : '', quiet: st.page === 'focus' || !on });
    }).join('') + '</div>';
    return full ? barHTML(mode) + panel : panel + barHTML(mode);
  }

  /* ---------- features sheet ---------- */
  function sheetHTML() {
    var n = Object.keys(picks).filter(function (k) { return picks[k]; }).length;
    var h = '<header class="mw-shh"><div><h2>Features</h2><p class="meta" role="status">' + n + ' of ' + F.length + ' picked</p><label class="mw-marks"><input class="switch" type="checkbox" id="mw-marks"' + (st.marks ? ' checked' : '') + '><span>Show feature numbers</span></label></div>' + btn('btn icon sm ghost', 'sheet', I.x, { 'aria-label': 'Close features' }) + '</header><div class="mw-feats">';
    F.forEach(function (f) {
      h += '<article class="mw-feat" id="mw-f' + f[0] + '"' + (st.feat === f[0] ? ' data-on="1"' : '') + '><h3><span class="mw-mk" data-pick="' + (picks[f[0]] || '') + '" aria-hidden="true">' + f[0] + '</span>' + esc(f[1]) + '</h3><p>' + esc(f[2]) + '</p><p class="meta"><strong>In orch:</strong> ' + esc(f[3]) + '</p><p class="meta"><strong>New work:</strong> ' + f[4] + ', ' + esc(f[5]) + '.</p><div class="mw-frow"><span class="segmented" role="group" aria-label="Your pick for ' + esc(f[1]) + '">';
      ['Keep', 'Maybe', 'Drop'].forEach(function (p) { h += btn('btn sm', 'pick', p, { 'data-n': f[0], 'data-p': p.toLowerCase(), 'aria-pressed': String(picks[f[0]] === p.toLowerCase()) }); });
      h += '</span>' + btn('btn sm ghost', 'show', 'Show me', { 'data-n': f[0] }) + (f[7] ? btn('btn sm ghost', 'show', f[7][0], { 'data-n': f[0], 'data-more': 1 }) : '') + '</div></article>';
    });
    return h + '</div><footer class="mw-shf">' + btn('btn outline', 'copy', 'Copy my picks') + '<span class="meta" id="mw-copied" role="status"></span></footer>';
  }

  /* ---------- render ---------- */
  function syncPanes() {
    if (!has(st.cur)) st.cur = S[0].k;
    st.panes = st.panes.filter(has).filter(function (k, i, a) { return a.indexOf(k) === i; }).slice(0, 3);
    var i = st.panes.indexOf(st.cur);
    if (i >= 0) st.act = i; else { st.act = Math.max(0, Math.min(st.act, st.panes.length - 1)); st.panes[st.act] = st.cur; }
  }
  function render(focusSel) {
    uid = 0; syncPanes();
    var b = document.body, mode = eff();
    b.dataset.mwPage = st.page; b.dataset.mwView = st.page === 'focus' ? st.view : '';
    b.dataset.mwSheet = st.sheet ? '1' : ''; b.dataset.mwLayer = mode; b.dataset.mwSplit = mode === 'bar' || mode === 'side' ? '' : st.panes.length;
    $('mw-page').innerHTML = st.page === 'focus' ? (st.view === 'zoom' ? zoomHTML() : wallHTML()) : PG[st.page]();
    var L = $('mw-layer'); L.dataset.mode = mode; L.innerHTML = layerHTML();
    var sh = $('mw-sheet'); sh.innerHTML = sheetHTML(); sh.inert = !st.sheet; sh.setAttribute('aria-hidden', String(!st.sheet));
    var ov = $('mw-ov'), oh = ovHTML(); ov.innerHTML = oh; ov.hidden = !oh; if (!oh) st.ov = null;
    q1('.shell').inert = !!oh; if (oh) sh.inert = true;
    $('mw-crumb').textContent = PAGES[st.page] + (st.page === 'ticket' ? ' › ' + st.tk : '');
    $('mw-fbtn').setAttribute('aria-expanded', String(st.sheet));
    $('mw-many').checked = st.many;
    document.querySelectorAll('.sidebar .nav-item[aria-label]').forEach(function (a) { var p = a.getAttribute('aria-label').toLowerCase(); if (PAGES[p]) { if (PAGES[p] === PAGES[st.page]) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); } });
    document.querySelectorAll('.mw-screen,.mw-chat').forEach(function (x) { x.scrollTop = x.scrollHeight; });
    /* a menu or list opens right above the button that opened it */
    var pop = q1('.mw-pop'), pb = pop && q1(st.menu ? '[data-act=menu][data-m="' + st.menu + '"]' : '[data-act=list][data-l="' + st.list + '"]');
    if (pb) { var bar = pop.parentNode, x = pb.getBoundingClientRect().left - bar.getBoundingClientRect().left; pop.style.left = Math.max(8, Math.min(x, bar.clientWidth - pop.offsetWidth - 8)) + 'px'; }
    url();
    if (oh && !focusSel) focusSel = '#mw-ovx';
    if (focusSel) { var t = document.querySelector(focusSel); if (t) t.focus(); }
  }
  function url() {
    var p = ['page=' + st.page];
    if (st.page === 'focus') p.push('view=' + st.view);
    if (st.page === 'ticket') p.push('tk=' + encodeURIComponent(st.tk));
    p.push('mode=' + (st.full ? 'full' : st.mode), 'cur=' + encodeURIComponent(st.panes[0]));
    if (st.panes.length > 1) { p.push('split=' + st.panes.length, 'cur2=' + encodeURIComponent(st.panes[1])); if (st.panes[2]) p.push('cur3=' + encodeURIComponent(st.panes[2])); if (st.act) p.push('act=' + (st.act + 1)); }
    if (st.term) p.push('term=1');
    if (st.ask) p.push('ask=1');
    if (st.ren) p.push('ren=1');
    if (st.many) p.push('many=1');
    if (st.list) p.push('list=' + st.list);
    if (st.menu) p.push('menu=' + st.menu);
    if (st.f) p.push('q=' + encodeURIComponent(st.f));
    if (st.ov) p.push('res=' + encodeURIComponent(st.ov.src) + ':' + st.ov.i);
    if (st.marks) p.push('marks=1');
    if (st.sheet) p.push('sheet=' + (st.feat || 1));
    try { history.replaceState(null, '', '?' + p.join('&')); } catch (e) { /* file pages may refuse */ }
  }
  function refresh() {
    document.querySelectorAll('[data-screen]').forEach(function (el) {
      var near = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      el.textContent = screenText(by(el.dataset.screen));
      if (near) el.scrollTop = el.scrollHeight;
    });
    document.querySelectorAll('[data-now]').forEach(function (el) { el.textContent = now(by(el.dataset.now)); });
    document.querySelectorAll('[data-peek]').forEach(function (el) { el.textContent = peekText(by(el.dataset.peek)); });
  }
  function refreshChat(k) {
    document.querySelectorAll('[data-chat]').forEach(function (el) { if (el.dataset.chat === k) { el.innerHTML = chatMsgs(by(k)); el.scrollTop = el.scrollHeight; } });
  }
  function say(t) { $('mw-live').textContent = t; }
  function push(s, line) {
    s.lines.push(line); if (s.lines.length > 60) s.lines.shift();
    if (/^⏺ (?!Bash\(|Read\()/.test(line)) s.now = line.slice(2);
  }
  /* motion: a thing grows or moves from where it was to where it is now (transform and opacity only; off with reduced motion) */
  function flip(el, from) {
    if (!el || !from || reduce || !el.animate) return;
    var to = el.getBoundingClientRect(); if (!to.width || !to.height || !from.width) return;
    var cs = getComputedStyle(document.documentElement);
    el.animate([{ transformOrigin: '0 0', transform: 'translate(' + (from.left - to.left) + 'px,' + (from.top - to.top) + 'px) scale(' + from.width / to.width + ',' + from.height / to.height + ')', opacity: 0.6 }, { transformOrigin: '0 0', transform: 'none', opacity: 1 }],
      { duration: parseFloat(cs.getPropertyValue('--dur-slow')) || 240, easing: (cs.getPropertyValue('--ease-move') || 'ease-out').trim() });
  }
  function q1(sel) { return document.querySelector(sel); }
  function rectOf(sel) { var e = q1(sel); return e ? e.getBoundingClientRect() : null; }
  function sel(k) { return '[data-tile="' + k + '"]'; }
  function clip(t, done) {
    var fb = function () { var a = document.createElement('textarea'); a.value = t; a.className = 'sr-only'; document.body.appendChild(a); a.select(); try { document.execCommand('copy'); } catch (e) { /* no clipboard */ } a.remove(); done(); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done, fb); else fb();
  }

  /* ---------- actions ---------- */
  function zoom(k) {
    var from = rectOf(sel(k));
    st.cur = k; st.view = 'zoom'; st.page = 'focus'; st.full = false; st.ask = false; st.ren = ''; st.menu = ''; st.list = '';
    render('.mw-zoom [data-act=back]');
    flip(q1('.mw-zoom .mw-pane'), from);
  }
  function back() {
    var from = rectOf('.mw-zoom .mw-pane');
    st.view = 'wall'; st.full = false; st.ask = false; st.ren = '';
    render(sel(st.cur) + ' [data-act=zoom]');
    flip(q1(sel(st.cur)), from);
  }
  function openSess(k) {
    st.cur = k; st.ask = false; st.ren = ''; st.menu = ''; st.list = '';
    if (!zoomed() && (st.mode === 'bar' || st.mode === 'side')) st.mode = phone() ? 'bottom' : (st.last || 'bottom');
  }
  function answer(k, i) {
    var s = by(k); if (!s.q) return;
    var a = s.q.a[i];
    s.q = null; s.s = 'run';
    push(s, '> ' + (i + 1)); push(s, '⏺ ' + a + '. Going on with step ' + (s.step ? Math.min(s.step[1], s.step[0] + 1) : 2) + '.');
    s.chat.push(['y', a, 'now'], ['h', 'Thanks. I go on with the next step.', 'now']);
    s.feed = ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ all tests pass (22 ms)', '⏺ Writing a short note about the choice.'];
    say('Answer sent to ' + k + '. The helper is working again.');
    render(sel(k) + ' [data-act=zoom],.mw-pane[data-k="' + k + '"] input');
  }
  function begin(s, lines, ev) {
    var was = live(s);
    lines.forEach(function (l) { push(s, l); });
    s.chat.push(['e', ev, 'now']); s.q = null; s.sl = ''; s.up = 0;
    if (!was && s.kind !== 'shell' && used() >= max()) { s.s = 'queue'; s.now = 'Waits in line for a free helper place.'; say(s.k + ' waits in line for a free helper place.'); }
    else { s.s = 'run'; s.feed = ['⏺ Read(ticket notes)', '⏺ Planning the next step.', '⏺ Working on the next step.']; say('Helper started on ' + s.k + '.'); }
    st.ask = false;
    render('.mw-pane[data-k="' + s.k + '"] input');
  }
  function start(k, how) {
    var s = by(k);
    if (how === 'clean') { s.lines = []; begin(s, ['⏺ Fresh start.', '⏺ Reading the ticket and its files.'], 'Fresh start: the helper reads the ticket again'); }
    else begin(s, ['', '⏺ Resuming the last conversation.', '⏺ Picking up where it stopped.'], 'Continued the last conversation');
  }
  function create(k) {
    var T = { 'Manager': ['Looks after the helpers', 'Ready.', '⏺ Looking at every helper once a minute.'], 'Chat helper': ['Ask anything', 'Ready for your question.', '⏺ Hello. Ask me anything about this workspace.'], 'Empty helper': ['No ticket, no task yet', 'Waiting for a first task.', '⏺ Ready. Tell me what to do.'] };
    if (!has(k)) {
      if (k === 'Plain terminal') S.push({ k: k, t: 'No helper, just a terminal', kind: 'shell', s: 'open', up: 0, pin: true, now: 'An empty terminal, ready for you.', lines: ['Last login: today 15:06', 'demo@workspace ~ %'], chat: [], files: [] });
      else {
        var fullUp = used() >= max(), t = T[k] || T['Empty helper'];
        S.push({ k: k, t: t[0], kind: 'free', tool: 'claude', s: fullUp ? 'queue' : 'run', up: 0, pin: true, now: fullUp ? 'Waits in line for a free helper place.' : t[1], lines: [t[2]], chat: [['h', t[2].slice(2), 'now']], files: [] });
      }
      say(k + ' opened and pinned.');
    }
    st.menu = '';
    if (st.page === 'focus') zoom(k); else { openSess(k); render('.mw-panel input, .mw-panel pre'); }
  }
  function pin(k) {
    var s = by(k), from = rectOf(sel(k));
    s.pin = !s.pin;
    render('[data-act=pin][data-k="' + k + '"]');
    flip(q1(sel(k)), from);
    say(k + (s.pin ? ' pinned: it comes first now.' : ' unpinned.'));
  }
  function beside(k) {
    var closed = st.mode === 'bar' || st.mode === 'side';
    if (closed) { st.mode = phone() ? 'bottom' : (st.last || 'bottom'); st.panes = [k]; st.act = 0; }
    else if (st.panes.indexOf(k) < 0) { if (st.panes.length < 3) st.panes.push(k); else st.panes[2] = k; }
    st.cur = k; st.ask = false; st.ren = '';
    render('.mw-pane[data-on] .mw-pt');
    flip(q1('.mw-panel .mw-pane[data-k="' + k + '"]'), rectOf(sel(k)));
  }
  function addPane() {
    var next = sorted().filter(function (o) { return live(o) && st.panes.indexOf(o.k) < 0; })[0]; if (!next || st.panes.length > 2) return;
    st.panes.push(next.k); st.cur = next.k; st.ask = false; st.ren = '';
    render('.mw-pane[data-on] .mw-pt'); say(next.k + ' added beside. Pick another session in the bar to change it.');
  }
  function closePane(k) {
    var i = st.panes.indexOf(k); if (i < 0 || st.panes.length < 2) return;
    st.panes.splice(i, 1); st.act = Math.max(0, Math.min(st.act > i ? st.act - 1 : st.act, st.panes.length - 1)); st.cur = st.panes[st.act]; st.ask = false; st.ren = '';
    render('.mw-pane[data-on] .mw-pt');
  }
  function many(on) {
    st.many = on;
    if (on) {
      if (!EXTRA) EXTRA = MORE.map(function (m, i) {
        var s = { k: 'ORCH-' + m[0], t: m[1], kind: 'ticket', s: m[2], tool: i % 3 === 1 ? 'codex' : 'claude', up: 12 + i * 7, step: [1 + i % 4, 4 + i % 3], now: NOWS[i % NOWS.length], lines: ['⏺ Read(ticket notes)', '⏺ ' + NOWS[i % NOWS.length]], chat: [['h', NOWS[i % NOWS.length], '15:0' + (i % 10), 0, 0]], files: [] };
        if (m[2] === 'wait') { s.q = QS[i % 2]; s.now = 'Waits for your answer.'; }
        if (m[2] === 'idle') { s.sl = 'Idle ' + (9 + i * 3) + ' min'; s.close = 51 - i * 3; s.now = 'Finished its step. Nothing to do right now.'; }
        if (m[2] === 'none') { s.sl = 'No session'; s.last = 'last week'; s.now = 'Closed after an hour idle. The conversation is kept.'; }
        if (m[2] === 'queue') { s.now = 'Waits in line for a free helper place.'; s.lines = []; s.chat = []; s.step = [0, 4 + i % 3]; }
        if (m[2] === 'run' && i % 3 === 0) s.feed = ['⏺ ' + NOWS[(i + 1) % NOWS.length], '⏺ ' + NOWS[(i + 2) % NOWS.length]];
        return s;
      });
      S = S.concat(EXTRA.filter(function (e) { return !has(e.k); }));
      EXTRA.forEach(function (e) { if (e.s === 'run' && used() > max()) { e.s = 'queue'; e.now = 'Waits in line for a free helper place.'; e.feed = null; } });
    } else {
      S = S.filter(function (s) { return !EXTRA || EXTRA.indexOf(s) < 0; });
      if (!has(st.cur)) st.cur = S[0].k; if (!has(st.tk)) st.tk = S[0].k; st.list = '';
    }
  }
  function setPage(p) {
    st.page = p; st.ask = false; st.ren = ''; st.menu = ''; st.list = '';
    if (p === 'focus') st.view = 'wall';
    var sb = q1('.sidebar'); if (sb) { sb.removeAttribute('data-open'); $('mw-menu').setAttribute('aria-expanded', 'false'); }
    render();
    var m = $('content'); if (m) m.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    say(PAGES[p] + ' page. Focus stays open.');
  }
  function setMode(m) {
    if (m === 'bottom' || m === 'right') st.last = m;
    st.mode = m; st.full = false; st.menu = ''; st.list = '';
    render(m === 'side' ? '.mw-edge' : '[data-act=menu][data-m=pos]');
  }
  function need(k) {
    var o = JSON.parse(S0).filter(function (s) { return s.k === k; })[0], s = by(k);
    if (o && (s.k !== k || s.s !== o.s)) { if (s.k === k) S[S.indexOf(s)] = o; else S.push(o); }
  }
  function show(n, more) {
    var o = more ? F[n - 1][7][1] : F[n - 1][6];
    if (o.need) need(o.need);
    st.full = false; st.ask = false; st.ren = ''; st.menu = ''; st.list = ''; st.ov = null; st.f = ''; st.mode = 'bar';
    if (!!o.many !== st.many) many(!!o.many);
    Object.keys(o).forEach(function (k) { if (k !== 'need' && k !== 'many') st[k] = Array.isArray(o[k]) ? o[k].slice() : (o[k] && typeof o[k] === 'object' ? JSON.parse(JSON.stringify(o[k])) : o[k]); });
    if (!o.panes) { st.panes = [st.cur]; st.act = 0; }
    if (st.mode === 'bottom' || st.mode === 'right') st.last = st.mode;
    st.feat = n; st.marks = true; if (window.innerWidth <= 900 || o.full || o.ov) st.sheet = false;
    render();
  }
  function openSheet(n) {
    st.sheet = true; st.feat = n || st.feat; st.full = false;
    render();
    var t = n ? $('mw-f' + n) : null;
    if (t) { t.scrollIntoView({ block: 'nearest' }); var bt = t.querySelector('button'); if (bt) bt.focus(); }
    else { var c = q1('#mw-sheet button'); if (c) c.focus(); }
  }

  document.addEventListener('click', function (e) {
    var menu = e.target.closest('#mw-menu');
    if (menu) { var sb = q1('.sidebar'), on = sb.getAttribute('data-open') !== 'true'; if (on) sb.setAttribute('data-open', 'true'); else sb.removeAttribute('data-open'); menu.setAttribute('aria-expanded', String(on)); return; }
    var nav = e.target.closest('.sidebar .nav-item[aria-label], .sidebar .brand');
    if (nav) { var p = nav.classList.contains('brand') ? 'home' : nav.getAttribute('aria-label').toLowerCase(); if (PAGES[p]) { e.preventDefault(); setPage(p); return; } }
    var b = e.target.closest('[data-act]');
    if (!b) { if ((st.menu || st.list) && !e.target.closest('.mw-pop')) { st.menu = ''; st.list = ''; render(); } return; }
    var a = b.dataset.act, k = b.dataset.k, s;
    if (a === 'zoom') zoom(k);
    else if (a === 'back') back();
    else if (a === 'home') { if (st.page === 'focus' && st.view === 'zoom') back(); else setPage('focus'); }
    else if (a === 'page') setPage(b.dataset.p);
    else if (a === 'ticket') { st.tk = k; setPage('ticket'); }
    else if (a === 'switch') { openSess(k); render('.mw-bar [data-act=switch][data-k="' + k + '"]'); }
    else if (a === 'focus') { openSess(k); render('.mw-pane[data-on] .mw-pmain button, .mw-pane[data-on] .mw-pmain input, .mw-pane[data-on] pre'); }
    else if (a === 'act') { st.cur = k; st.ask = false; st.ren = ''; render('.mw-pane[data-on] .mw-pt'); }
    else if (a === 'beside') beside(k);
    else if (a === 'addpane') addPane();
    else if (a === 'closepane') closePane(k);
    else if (a === 'view') { st.term = b.dataset.v === 'term'; render('.mw-pane[data-on] [data-act=view][data-v=' + b.dataset.v + '], [data-act=view][data-v=' + b.dataset.v + ']'); }
    else if (a === 'full') { st.full = !st.full; st.menu = ''; st.list = ''; if (st.full) st.sheet = false; render('[data-act=full]'); }
    else if (a === 'mode') setMode(b.dataset.m);
    else if (a === 'menu') { st.menu = st.menu === b.dataset.m ? '' : b.dataset.m; st.list = ''; render(st.menu ? '.mw-pop .mw-opt' : '[data-act=menu][data-m=' + b.dataset.m + ']'); }
    else if (a === 'list') { st.list = st.list === b.dataset.l ? '' : b.dataset.l; st.menu = ''; st.lq = ''; render(st.list ? '#mw-lq, .mw-pop .mw-opt' : '[data-act=list][data-l=' + b.dataset.l + ']'); }
    else if (a === 'col') { st.col[b.dataset.id] = !st.col[b.dataset.id]; render('[data-act=col][data-id=' + b.dataset.id + ']'); }
    else if (a === 'pin') pin(k);
    else if (a === 'ren') { st.ren = k; render('.mw-ren input'); var ri = q1('.mw-ren input'); if (ri) ri.select(); }
    else if (a === 'answer') answer(k, +b.dataset.a);
    else if (a === 'start') start(k, b.dataset.how);
    else if (a === 'reopen') { s = by(k); begin(s, ['', '⏺ Reopened the session from ' + HIST[+b.dataset.i][0] + '.'], 'Reopened the session from ' + HIST[+b.dataset.i][0]); }
    else if (a === 'ask') { st.ask = true; render('.mw-start button'); }
    else if (a === 'askoff') { st.ask = false; render('[data-act=ask]'); }
    else if (a === 'new') create(k);
    else if (a === 'ov') { st.ov = { src: b.dataset.src, i: +b.dataset.i }; render('#mw-ovx'); }
    else if (a === 'ovnav') ovStep(+b.dataset.d);
    else if (a === 'ovclose') closeOv();
    else if (a === 'copyterm') clip(screenText(by(k)), function () { b.textContent = 'Copied'; say('Terminal text copied.'); });
    else if (a === 'feat') openSheet(+b.dataset.n);
    else if (a === 'sheet') { if (st.sheet) { st.sheet = false; render('#mw-fbtn'); } else openSheet(0); }
    else if (a === 'show') show(+b.dataset.n, b.dataset.more);
    else if (a === 'pick') { var n = b.dataset.n; picks[n] = picks[n] === b.dataset.p ? '' : b.dataset.p; try { localStorage.setItem(KEY, JSON.stringify(picks)); } catch (er) { /* private window */ } render('[data-act=pick][data-n="' + n + '"][data-p=' + b.dataset.p + ']'); }
    else if (a === 'copy') clip('Focus draft D: my picks\n' + F.map(function (f) { return f[0] + '. ' + f[1] + ': ' + (picks[f[0]] || 'not picked'); }).join('\n'), function () { var c = $('mw-copied'); if (c) c.textContent = 'Copied'; });
  });
  function closeOv() { var o = st.ov; st.ov = null; render(o ? '[data-act=ov][data-src="' + o.src + '"][data-i="' + o.i + '"]' : ''); }
  document.addEventListener('change', function (e) {
    if (e.target.id === 'mw-marks') { st.marks = e.target.checked; render('#mw-marks'); }
    if (e.target.id === 'mw-many') { many(e.target.checked); render('#mw-many'); say(e.target.checked ? 'Demo shows 24 sessions.' : 'Demo shows 6 sessions.'); }
  });
  document.addEventListener('input', function (e) {
    var t = e.target, d = t.dataset && t.dataset.d;
    if (d) drafts[d] = t.value;
    else if (t.id === 'mw-filter') { st.f = t.value; $('mw-bands').innerHTML = bandsHTML(); url(); }
    else if (t.id === 'mw-lq') { st.lq = t.value; $('mw-plist').innerHTML = listRows(); }
  });
  document.addEventListener('submit', function (e) {
    var f = e.target.closest('form[data-f]'); if (!f) return;
    e.preventDefault();
    var inp = f.querySelector('input'), v = inp.value.trim(), s = by(f.dataset.k);
    if (f.dataset.f === 'ren') { s.name = v && v !== s.t ? v : ''; st.ren = ''; render('[data-act=ren]'); say('Name saved.'); return; }
    if (!v) return;
    inp.value = ''; drafts[inp.dataset.d] = '';
    {
      s.chat.push(['y', v, 'now']); s.lines.push('> ' + v);
      setTimeout(function () { s.chat.push(['h', 'Got it. I take that into account.', 'now']); s.lines.push('⏺ Got it. I take that into account.'); refreshChat(s.k); refresh(); }, 600);
      refreshChat(s.k); refresh();
    }
  });
  function termKey(s, key) {
    var t = s.typed || '';
    if (key === 'Enter') {
      if (!t.trim()) return;
      s.typed = '';
      if (s.kind === 'shell') { s.lines[s.lines.length - 1] += ' ' + t; s.lines.push('demo terminal: nothing was run', 'demo@workspace ~ %'); }
      else { s.lines.push('> ' + t); setTimeout(function () { s.lines.push('⏺ Got it: "' + t + '". I take that into account.'); refresh(); }, 500); }
    } else if (key === 'Backspace') s.typed = t.slice(0, -1);
    else s.typed = t + key;
    refresh(); document.querySelectorAll('[data-screen]').forEach(function (x) { if (by(x.dataset.screen) === s) x.scrollTop = x.scrollHeight; });
  }
  document.addEventListener('paste', function (e) {
    var scr = e.target.closest && e.target.closest('pre[data-screen]'); if (!scr) return;
    e.preventDefault(); termKey(by(scr.dataset.screen), ((e.clipboardData && e.clipboardData.getData('text')) || '').replace(/\s+/g, ' '));
  });
  document.addEventListener('keydown', function (e) {
    var scr = e.target.closest && e.target.closest('pre[data-screen]');
    if (scr && !e.ctrlKey && !e.metaKey && !e.altKey && (e.key === 'Enter' || e.key === 'Backspace' || e.key.length === 1)) { e.preventDefault(); termKey(by(scr.dataset.screen), e.key); return; }
    if (st.ov) {
      if (e.key === 'Escape') closeOv(); else if (e.key === 'ArrowLeft') ovStep(-1); else if (e.key === 'ArrowRight') ovStep(1);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'j' || e.key === 'J')) {
      e.preventDefault();
      if (st.full) { st.full = false; render(); }
      else if (zoomed()) back();
      else setMode(st.mode === 'bar' || st.mode === 'side' ? (st.last || 'bottom') : 'bar');
      return;
    }
    if (e.key !== 'Escape') return;
    if (st.sheet) { st.sheet = false; render('#mw-fbtn'); }
    else if (st.menu || st.list) { var w = st.menu ? '[data-act=menu][data-m=' + st.menu + ']' : '[data-act=list]'; st.menu = ''; st.list = ''; render(w); }
    else if (st.ren) { st.ren = ''; render('[data-act=ren]'); }
    else if (st.full) { st.full = false; render('[data-act=menu][data-m=pos], [data-act=full]'); }
    else if (st.ask && live(by(st.cur))) { st.ask = false; render('[data-act=ask]'); }
    else if (zoomed()) back();
  });
  /* live: one working session gets its next line every few seconds */
  setInterval(function () {
    var w = S.filter(function (s) { return s.s === 'run' && s.feed && s.feed.length; }); if (!w.length) return;
    var s = w[feedAt++ % w.length]; s.fi = (s.fi || 0);
    push(s, s.feed[s.fi++ % s.feed.length]); refresh();
  }, 2400);

  /* ---------- start: read the link ---------- */
  (function () {
    var q = new URLSearchParams(location.search), v, ov = document.createElement('div');
    ov.id = 'mw-ov'; ov.className = 'mw-ov'; ov.hidden = true; document.body.appendChild(ov);
    if (q.get('many') === '1') many(true);
    if (PG[v = q.get('page')] || v === 'focus') st.page = v;
    if ((v = q.get('cur')) && has(v)) { st.cur = v; if (by(v).kind === 'ticket') st.tk = v; }
    if ((v = q.get('tk')) && has(v)) st.tk = v;
    st.panes = [st.cur];
    var n = Math.max(1, Math.min(3, +q.get('split') || 1));
    ['cur2', 'cur3'].slice(0, n - 1).forEach(function (c) { var k = q.get(c); if (k && has(k) && st.panes.indexOf(k) < 0) st.panes.push(k); });
    sorted().forEach(function (o) { if (st.panes.length < n && live(o) && st.panes.indexOf(o.k) < 0) st.panes.push(o.k); });
    v = +q.get('act'); if (v >= 1 && v <= st.panes.length) st.cur = st.panes[v - 1];
    v = q.get('mode');
    if (v === 'full') st.full = true;
    else if (/^(bar|bottom|right|side)$/.test(v || '')) { st.mode = v; if (v === 'bottom' || v === 'right') st.last = v; }
    if (q.get('view') === 'zoom' || q.get('ask') === '1' || q.get('ren') === '1') st.view = 'zoom';
    st.term = q.get('term') === '1';
    st.ask = q.get('ask') === '1' && live(by(st.cur));
    if (q.get('ren') === '1') st.ren = st.cur;
    if (/^(run|queue|idle)$/.test(v = q.get('list') || '')) st.list = v;
    if (/^(new|pos)$/.test(v = q.get('menu') || '')) st.menu = v;
    st.f = q.get('q') || '';
    if ((v = q.get('res'))) { var c = v.lastIndexOf(':'), src = v.slice(0, c), ri = +v.slice(c + 1); if ((src === '*' || has(src)) && files(src)[ri]) st.ov = { src: src, i: ri }; }
    st.marks = q.get('marks') === '1';
    if ((v = q.get('sheet'))) { st.sheet = true; st.feat = +v >= 1 && +v <= F.length ? +v : 0; }
    document.body.dataset.mwBoot = '1'; /* a page that opens with the sheet shows it at once, without the slide */
    render();
    if (st.sheet && st.feat) { var t = $('mw-f' + st.feat); if (t) { var fe = t.parentNode; fe.scrollTop = t.offsetTop - fe.offsetTop; } }
    setTimeout(function () { delete document.body.dataset.mwBoot; }, 300);
  })();
})();

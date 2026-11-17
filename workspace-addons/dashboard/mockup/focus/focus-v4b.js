/* Focus v4b draft (ORCH-251): mission control wall. Demo data only; picks stay in this browser. */
(function () {
  'use strict';
  var MAX = 6, KEY = 'orch-focus-v4b-picks';
  var F = [
    [1, 'Live wall', 'Focus opens on a wall of live tiles, one per session. Each tile shows the last lines of its helper as they happen.', 'orch run list gives the signal per ticket (working, idle, waiting); the read-only screen gives the last lines, refreshed every few seconds.', 'Medium', 'a new page; the data exists', { page: 'focus', view: 'wall' }],
    [2, 'Needs you first', 'A session that waits for you is the biggest tile and comes first. You answer on the tile with one click.', 'The "waiting on" value of orch run list plus the open question on the ticket; the answer is sent into the session.', 'Small', 'one card and one send', { page: 'focus', view: 'wall', need: 'ORCH-238' }],
    [3, 'Open Focus from a ticket', 'One button on every ticket: Watch a working one, Answer a waiting one, Start one that has no session.', 'The run signal of the ticket (working, waiting, none) decides the word on the button.', 'Small', 'one button per ticket', { page: 'tickets', tk: 'ORCH-189' }],
    [4, 'Continue or start clean', 'Start asks one thing: continue the last conversation, or begin with a new context window.', 'The session id is kept on the ticket, so the next start resumes it. Only the last session is kept today. Live places are limited; extra starts wait in line.', 'Medium', 'a list of older sessions needs new storage', { page: 'focus', view: 'zoom', cur: 'ORCH-189', need: 'ORCH-189' }],
    [5, 'Chat or real terminal', 'Chat shows plain messages. Terminal is the real screen of the helper: type, select, copy and paste like in the Terminal app.', 'Every helper runs in its own tmux session. Chat is helper messages plus ticket events; no transcript exists.', 'Large', 'a terminal in the browser (xterm.js and a bridge) is new', { page: 'focus', view: 'zoom', cur: 'ORCH-228', term: true }],
    [6, 'Sessions without a ticket', 'The plus tile opens a Manager, a Chat helper or a plain terminal that belongs to no ticket.', 'The same per-workspace tmux socket, with a name that is not a ticket id.', 'Medium', 'sessions outside the ticket limit need rules', { page: 'focus', view: 'wall', add: true }],
    [7, 'Mini window on every page', 'Leave Focus and the current session follows you as a small window. Type in it, change page, your lines are still there. It docks right or bottom.', 'Pages are separate full loads today. Cheapest honest path: soft page swaps that keep the window; fallback: a pop-out window.', 'Large', 'no layer survives a page change today', { page: 'home', mode: 'pip', cur: 'ORCH-228', term: true }],
    [8, 'Zoom and full screen', 'Click a tile and it grows into a large view. Full screen removes everything else. Esc goes one step back each time.', 'Nothing new in orch: the same session, drawn bigger.', 'Small', 'layout only', { page: 'focus', view: 'zoom', cur: 'ORCH-232', term: true, full: true }],
    [9, 'Side by side', 'Pin 1, 2 or 4 tiles to keep them large next to each other, each one typeable. Switching costs no load time because every tile is already live.', 'Each pane attaches to its own tmux session. Two viewers of one session shrink its window, so one pane per session.', 'Medium', 'several live screens at once', { page: 'focus', view: 'wall', pins: ['ORCH-228', 'ORCH-232'] }],
    [10, 'Results shelf', 'Pictures, pages, tables and pull requests sit beside the session as small previews instead of text.', 'Files and evidence attached to the ticket, and the pull request links on it.', 'Medium', 'a small preview per file type', { page: 'focus', view: 'zoom', cur: 'ORCH-228', term: false }]
  ];
  var S = [
    { k: 'ORCH-238', t: 'Add files and notes to a ticket', kind: 'ticket', s: 'wait', step: [3, 5],
      q: { t: 'Keep the old file name when the same file is added twice?', why: 'The helper suggests keeping it: links people already shared keep working.', a: ['Keep the old name', 'Use the new name'] },
      lines: ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ adds a picture to a ticket (38 ms)', '  ⎿ ✔ adds a note below the files (12 ms)', '⏺ The upload works. One thing only you can decide:', '  Keep the old file name when the same file is added twice?', '  1. Keep the old name (suggested)', '  2. Use the new name', '  Waiting for your answer…'],
      chat: [['e', 'Step 2 done: files can be dropped on a ticket', '14:21'], ['h', 'Uploading works for pictures, pages and tables. Notes sit below the files.', '14:38'], ['h', 'One thing I need from you before I go on: when the same file is added twice, should the old name stay?', '14:52']],
      files: [['img', 'ticket-files.png', 'Screenshot · 14:36'], ['csv', 'upload-sizes.csv', 'Table · 6 rows']] },
    { k: 'ORCH-228', t: 'Phone width and zoom', kind: 'ticket', s: 'run', step: [4, 5],
      lines: ['⏺ All 3 widths pass: 1280, 1920 and 390.', '⏺ Bash(git push -u origin fix/phone-width)', '  ⎿ branch fix/phone-width set up to track origin', '⏺ Writing the pull request text.', '⏺ Bash(gh pr create --base develop --draft)', '  ⎿ Creating pull request…'],
      feed: ['  ⎿ pull request 1318 opened as a draft', '⏺ Linking the pull request to the ticket.', '  ⎿ linked', '⏺ Waiting for the checks: 3 of 12 green', '⏺ Waiting for the checks: 7 of 12 green', '⏺ Waiting for the checks: 11 of 12 green'],
      chat: [['e', 'Step 3 done: the page fits a phone at 390', '14:31'], ['h', 'The Home page no longer scrolls sideways on a phone. Before and after pictures are on the shelf.', '14:40'], ['h', 'Opening the pull request now. I will tell you when the checks are green.', '15:02']],
      files: [['img', 'home-390.png', 'Screenshot · 14:39'], ['html', 'phone-widths.html', 'Page · before and after'], ['csv', 'widths.csv', 'Chart · 3 widths'], ['pr', 'Pull request 1318', 'Draft · 3 of 12 checks green']] },
    { k: 'ORCH-232', t: 'Insights and usage counts', kind: 'ticket', s: 'run', step: [2, 6],
      lines: ['⏺ Bash(node --test tests/insights.test.js)', '  ⎿ ✔ counts skills per day (41 ms)', '  ⎿ ✔ counts keys that were never used (9 ms)', '  ⎿ ✔ empty workspace shows zero, not an error (6 ms)'],
      feed: ['  ⎿ ✔ week view adds up to the day view (17 ms)', '  ⎿ ✔ a failed call counts as failed (8 ms)', '  ⎿ ℹ tests 14 · pass 14 · fail 0', '⏺ Bash(uv run python -m pytest -q tests/test_insights.py)', '  ⎿ ......................  22 passed in 3.1s', '⏺ Tests are green. Drawing the usage chart next.'],
      chat: [['e', 'Step 1 done: counts are collected per day', '13:58'], ['h', 'The counts are in. I am running the tests before I draw the chart.', '15:04']],
      files: [['csv', 'usage-by-day.csv', 'Chart · 14 days'], ['html', 'insights-preview.html', 'Page · draft']] },
    { k: 'ORCH-247', t: 'Steer a helper from the dashboard', kind: 'ticket', s: 'idle', sl: 'Idle 18 min', step: [5, 5],
      lines: ['⏺ Bash(orch ref wait ORCH-247 --merge)', '  ⎿ 12 of 12 checks green · merged', '⏺ Done. The Steer button is on the ticket page and', '  pull request 1309 is merged. Ready for your review.', '>'],
      chat: [['e', 'Step 5 done: merged on green checks', '14:44'], ['h', 'Finished. You can try the Steer button on any working ticket.', '14:45']],
      files: [['pr', 'Pull request 1309', 'Merged · 12 of 12 checks green'], ['img', 'steer-button.png', 'Screenshot · 14:30']] },
    { k: 'ORCH-189', t: 'Manager view', kind: 'ticket', s: 'none', sl: 'No session', last: 'yesterday 16:40', step: [2, 4],
      lines: ['⏺ Stopped at step 2 of 4: the sketch is attached.', '  Next would be the list of helpers.', '', '  Session ended yesterday 16:40'],
      chat: [['e', 'Step 2 done: sketch of the Manager view', 'yesterday 16:31'], ['h', 'I stopped here. The sketch is on the shelf; the helper list is next.', 'yesterday 16:40']],
      files: [['img', 'manager-sketch.png', 'Screenshot · yesterday']] },
    { k: 'Manager', t: 'No ticket · looks after the helpers', kind: 'free', s: 'run',
      lines: ['⏺ Bash(orch run list)', '  ⎿ ORCH-238  waiting   an answer from you', '    ORCH-228  working   step 4 of 5', '    ORCH-232  working   step 2 of 6', '    ORCH-247  idle      18 min', '⏺ 4 helpers are live. One waits for you. Nothing is stuck.'],
      feed: ['⏺ Checked again: no change.', '⏺ ORCH-228 opened its pull request.', '⏺ Checked again: tests on ORCH-232 are green.', '⏺ ORCH-247 has been idle for a while; it closes by itself after about an hour.'],
      chat: [['h', 'I look at every helper once a minute. One waits for you: ORCH-238.', '15:05']],
      files: [['csv', 'helpers.csv', 'Table · 4 helpers']] }
  ];
  var S0 = JSON.stringify(S);
  var ST = { wait: ['◆', 'Needs you'], run: ['●', 'Working'], idle: ['◐', 'Idle'], none: ['○', 'No session'], queue: ['◷', 'In line'], open: ['▸', 'Open'] };
  var ORDER = { wait: 0, run: 1, open: 2, idle: 3, queue: 4, none: 5 };
  var PAGES = { focus: 'Focus', home: 'Home', tickets: 'Tickets', review: 'Review' };
  var st = { page: 'focus', view: 'wall', cur: 'ORCH-238', term: false, mode: 'pip', last: 'pip', full: false, pins: [], ask: false, add: false, sheet: false, feat: 0, tk: 'ORCH-238', open: '', pos: null };
  var drafts = {}, picks = {}, uid = 0, feedAt = 0;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  try { picks = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { picks = {}; }

  function $(id) { return document.getElementById(id); }
  function esc(x) { return String(x).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function by(k) { for (var i = 0; i < S.length; i++) if (S[i].k === k) return S[i]; return S[0]; }
  function live(s) { return s.s === 'run' || s.s === 'wait' || s.s === 'idle' || s.s === 'open'; }
  function used() { return S.filter(function (s) { return s.kind !== 'shell' && live(s); }).length; }
  function sorted() { return S.slice().sort(function (a, b) { return ORDER[a.s] - ORDER[b.s]; }); }
  function word(s) { return s.sl && (s.s === 'idle' || s.s === 'none') ? s.sl : ST[s.s][1]; }
  function stat(s, bare) { return '<span class="mw-st" data-s="' + s.s + '"><span class="mw-sym" aria-hidden="true">' + ST[s.s][0] + '</span>' + (bare ? '<span class="sr-only">' + word(s) + '</span>' : word(s)) + '</span>'; }
  function mk(n) { var f = F[n - 1]; return '<button class="mw-mk" type="button" data-act="feat" data-n="' + n + '" data-pick="' + (picks[n] || '') + '"' + (st.sheet && st.feat === n ? ' data-on="1"' : '') + ' aria-label="Feature ' + n + ': ' + esc(f[1]) + '">' + n + '</button>'; }
  function ic(d) { return '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">' + d + '</svg>'; }
  var I = {
    pin: ic('<path d="M9 3h6l-1 6 4 4H6l4-4z"/><path d="M12 13v8"/>'),
    full: ic('<path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/>'),
    exit: ic('<path d="M3 8h5V3m8 0v5h5M3 16h5v5m8 0v-5h5"/>'),
    right: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M14 4v16"/>'),
    bottom: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 13h18"/>'),
    mini: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><rect x="12" y="12" width="7" height="6" rx="1"/>'),
    min: ic('<path d="M5 18h14"/>'),
    back: ic('<path d="M11 5l-7 7 7 7M4 12h16"/>'),
    plus: ic('<path d="M12 5v14M5 12h14"/>'),
    x: ic('<path d="M6 6l12 12M18 6 6 18"/>')
  };
  var TH = {
    img: '<svg viewBox="0 0 120 72" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><rect class="mw-f1" width="120" height="10" rx="4"/><rect class="mw-f1" x="6" y="16" width="24" height="50" rx="2"/><rect class="mw-f2" x="36" y="16" width="44" height="8" rx="2"/><rect class="mw-f1" x="36" y="30" width="78" height="14" rx="2"/><rect class="mw-f1" x="36" y="50" width="78" height="14" rx="2"/></svg>',
    html: '<svg viewBox="0 0 120 72" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><rect class="mw-f5" width="120" height="22" rx="4"/><rect class="mw-f2" x="10" y="8" width="46" height="6" rx="2"/><rect class="mw-f1" x="10" y="30" width="100" height="5" rx="2"/><rect class="mw-f1" x="10" y="40" width="84" height="5" rx="2"/><rect class="mw-f1" x="10" y="50" width="92" height="5" rx="2"/><rect class="mw-f3" x="10" y="60" width="30" height="6" rx="2"/></svg>',
    csv: '<svg viewBox="0 0 120 72" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><path class="mw-l1" d="M10 62h100"/><rect class="mw-f3" x="14" y="40" width="12" height="22" rx="2"/><rect class="mw-f3" x="32" y="30" width="12" height="32" rx="2"/><rect class="mw-f3" x="50" y="36" width="12" height="26" rx="2"/><rect class="mw-f3" x="68" y="18" width="12" height="44" rx="2"/><rect class="mw-f2" x="86" y="10" width="12" height="52" rx="2"/></svg>',
    pr: '<svg viewBox="0 0 120 72" aria-hidden="true"><rect class="mw-f0" width="120" height="72" rx="4"/><circle class="mw-l2" cx="30" cy="18" r="6"/><circle class="mw-l2" cx="30" cy="54" r="6"/><circle class="mw-l2" cx="66" cy="54" r="6"/><path class="mw-l2" d="M30 24v24M36 18h18a12 12 0 0 1 12 12v18"/><path class="mw-l3" d="m84 34 6 6 12-14"/></svg>'
  };
  var KIND = { img: 'Picture', html: 'Page', csv: 'Table', pr: 'Pull request' };

  /* ---------- pieces ---------- */
  function steps(s) {
    if (!s.step) return '<span class="meta">No ticket</span>';
    var h = '<span class="mw-steps" role="img" aria-label="Step ' + s.step[0] + ' of ' + s.step[1] + '">';
    for (var i = 1; i <= s.step[1]; i++) h += '<i' + (i <= s.step[0] ? ' data-on="1"' : '') + '></i>';
    return h + '</span><span class="meta">Step ' + s.step[0] + ' of ' + s.step[1] + '</span>';
  }
  function screenText(s, n) { return (n ? s.lines.slice(-n) : s.lines).join('\n'); }
  function qHTML(s) {
    return '<div class="mw-q" role="group" aria-label="Question from the helper"><p class="mw-qt">' + esc(s.q.t) + '</p><p class="meta">' + esc(s.q.why) + '</p><div class="mw-ans"><button class="btn primary" type="button" data-act="answer" data-k="' + s.k + '" data-a="0">' + esc(s.q.a[0]) + '</button><button class="btn outline" type="button" data-act="answer" data-k="' + s.k + '" data-a="1">' + esc(s.q.a[1]) + '</button></div></div>';
  }
  function chatMsgs(s) {
    return s.chat.map(function (m) {
      if (m[0] === 'e') return '<p class="mw-ev meta"><span aria-hidden="true">✓</span> ' + esc(m[1]) + ' · ' + esc(m[2]) + '</p>';
      return '<div class="mw-msg" data-w="' + m[0] + '"><span class="meta">' + (m[0] === 'y' ? 'You' : 'Helper') + ' · ' + esc(m[2]) + '</span><p>' + esc(m[1]) + '</p></div>';
    }).join('');
  }
  function chatHTML(s, prim) {
    var id = 'mw-i' + (++uid);
    return '<div class="mw-chat" data-chat="' + s.k + '" role="log" aria-label="Messages and ticket events">' + chatMsgs(s) + '</div><form class="mw-comp" data-k="' + s.k + '" data-f="chat"><label class="sr-only" for="' + id + '">Message to the helper on ' + esc(s.k) + '</label><input class="input" id="' + id + '" data-d="c:' + s.k + '" value="' + esc(drafts['c:' + s.k] || '') + '" placeholder="Message the helper" autocomplete="off"><button class="btn ' + (prim ? 'primary' : 'outline') + '" type="submit">Send</button></form>';
  }
  function termHTML(s) {
    var id = 'mw-i' + (++uid), sh = s.kind === 'shell';
    return '<div class="mw-term"><pre class="mw-screen" data-screen="' + s.k + '" data-n="0" tabindex="0" role="log" aria-label="Terminal of ' + esc(s.k) + '">' + esc(screenText(s, 0)) + '</pre><form class="mw-tin" data-k="' + s.k + '" data-f="term"><label class="sr-only" for="' + id + '">Type in the terminal of ' + esc(s.k) + '</label><span class="mw-prompt" aria-hidden="true">' + (sh ? '$' : '&gt;') + '</span><input class="mw-tinput" id="' + id + '" data-d="t:' + s.k + '" value="' + esc(drafts['t:' + s.k] || '') + '" placeholder="Type here, press Enter" autocomplete="off" autocapitalize="off" spellcheck="false"></form></div>';
  }
  function startHTML(s, withMk) {
    var on = live(s), places = used() + ' of ' + MAX + ' helper places are in use' + (used() >= MAX && !on ? ', so this start waits in line.' : '.');
    var h = '<div class="mw-start"><h2>' + (on ? 'Start this helper again?' : 'Start a helper on this ' + (s.kind === 'ticket' ? 'ticket' : 'session')) + (withMk ? mk(4) : '') + '</h2>';
    h += '<p class="meta">' + (on ? 'The helper is in the middle of its work. ' : 'Last session ended ' + esc(s.last || 'earlier') + (s.step ? ' at step ' + s.step[0] + ' of ' + s.step[1] : '') + '. ') + places + '</p><div class="mw-choices">';
    if (on) h += '<div class="mw-choice"><h3>Keep going</h3><p class="meta">Nothing changes. The helper keeps its conversation.</p><button class="btn primary" type="button" data-act="askoff">Keep going</button></div>';
    else h += '<div class="mw-choice"><h3>Continue where it stopped</h3><p class="meta">Keeps the earlier conversation. Best when the work is half done.</p><button class="btn primary" type="button" data-act="start" data-how="continue" data-k="' + s.k + '">Continue</button></div>';
    h += '<div class="mw-choice"><h3>Start clean</h3><p class="meta">A new context window: the helper reads the ticket again and forgets the old talk. Best when it went off track.</p><button class="btn outline" type="button" data-act="start" data-how="clean" data-k="' + s.k + '">Start clean</button></div></div>';
    return h + '<p class="meta">Only the last session of a ticket is kept today.</p></div>';
  }
  function shelf(s, withMk) {
    var h = '<aside class="mw-shelf" aria-label="Results"><div class="mw-sh"><h2>Results</h2>' + (withMk ? mk(10) : '') + '</div>';
    if (!s.files || !s.files.length) return h + '<p class="meta">Nothing yet. Pictures, pages and tables show up here.</p></aside>';
    h += '<div class="mw-res-list">' + s.files.map(function (f, i) {
      var id = s.k + ':' + i, open = st.open === id;
      return '<div class="mw-res" data-type="' + f[0] + '"' + (open ? ' data-open="1"' : '') + '><button class="mw-rb" type="button" data-act="res" data-id="' + id + '" aria-expanded="' + open + '" aria-label="' + KIND[f[0]] + ': ' + esc(f[1]) + ', ' + (open ? 'make smaller' : 'make bigger') + '"><span class="mw-thumb">' + TH[f[0]] + '</span><span class="mw-rn truncate">' + esc(f[1]) + '</span><span class="meta">' + esc(f[2]) + '</span></button>' + (f[0] === 'html' ? '<a class="mw-rl" href="review-preview.html" target="_blank" rel="noopener">Open page</a>' : '') + '</div>';
    }).join('');
    return h + '</div></aside>';
  }
  function seg(term, withMk) {
    return '<span class="mw-view"><span class="segmented" role="group" aria-label="View"><button class="btn sm" type="button" data-act="view" data-v="chat" aria-pressed="' + !term + '">Chat</button><button class="btn sm" type="button" data-act="view" data-v="term" aria-pressed="' + !!term + '">Terminal</button></span>' + (withMk ? mk(5) : '') + '</span>';
  }
  function pane(k, size, o) {
    o = o || {};
    var s = by(k), asking = s.s === 'none' || (o.main && st.ask), term = s.kind === 'shell' || o.term || st.term;
    var h = '<section class="mw-pane" data-size="' + size + '" data-s="' + s.s + '" data-k="' + s.k + '" aria-label="' + esc(s.k + ', ' + s.t) + '"><header class="mw-ph">' + (o.pre || '') + stat(s) + (size === 'sm' ? '' : '<span class="mw-key">' + esc(s.k) + '</span>') + '<span class="mw-pt truncate">' + esc(s.t) + '</span>';
    if (!o.term && s.kind !== 'shell' && !asking && s.s !== 'queue') h += seg(term, o.mk);
    h += (o.tools || '') + '</header><div class="mw-pb"><div class="mw-pmain">';
    if (asking) h += startHTML(s, o.mk);
    else if (s.s === 'queue') h += '<div class="mw-start"><h2>In line</h2><p class="meta">All ' + MAX + ' helper places are in use. This one starts by itself when a place is free. Idle helpers close after about an hour.</p></div>';
    else h += (s.q ? qHTML(s) : '') + (term ? termHTML(s) : chatHTML(s, o.main && !s.q));
    h += '</div>' + (size === 'sm' || o.noshelf ? '' : shelf(s, o.mk)) + '</div></section>';
    return h;
  }

  /* ---------- Focus page: wall and zoom ---------- */
  function tile(s) {
    var big = s.s === 'wait', can = live(s), pinned = st.pins.indexOf(s.k) >= 0;
    var h = '<article class="mw-tile" data-s="' + s.s + '" data-k="' + s.k + '"' + (big ? ' data-big="1"' : '') + '>';
    h += '<button class="mw-topen" type="button" data-act="zoom" data-k="' + s.k + '" aria-label="Open ' + esc(s.k + ', ' + s.t + ', ' + word(s)) + '"><span class="mw-thead">' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span></span><span class="mw-tt">' + esc(s.t) + '</span><span class="mw-screen" data-screen="' + s.k + '" data-n="' + (big ? 8 : 5) + '" aria-hidden="true">' + esc(screenText(s, big ? 8 : 5)) + '</span></button>';
    if (s.q) h += '<div class="mw-tq">' + qHTML(s) + mk(2) + '</div>';
    h += '<footer class="mw-tfoot">' + (s.s === 'none' ? '<span class="meta">Last session ' + esc(s.last || '') + '</span>' : steps(s)) + '<span class="grow"></span>';
    if (s.s === 'none') h += mk(4) + '<button class="btn outline sm" type="button" data-act="zoom" data-k="' + s.k + '" data-ask="1">Start</button>';
    if (can) h += '<button class="btn icon sm ghost" type="button" data-act="pin" data-k="' + s.k + '" aria-pressed="' + pinned + '" aria-label="Pin ' + esc(s.k) + ' side by side">' + I.pin + '</button>';
    return h + '</footer></article>';
  }
  function addTile() {
    var h = '<article class="mw-tile mw-add" data-k="add">';
    if (!st.add) return h + '<button class="mw-topen" type="button" data-act="add" aria-expanded="false"><span class="mw-plus" aria-hidden="true">' + I.plus + '</span><span class="mw-tt">New session without a ticket</span><span class="meta">A Manager, a Chat helper or a plain terminal</span></button><footer class="mw-tfoot"><span class="grow"></span>' + mk(6) + '</footer></article>';
    h += '<div class="mw-thead"><span class="mw-tt">New session without a ticket</span><span class="grow"></span><button class="btn icon sm ghost" type="button" data-act="add" aria-label="Close">' + I.x + '</button></div><div class="mw-opts">';
    [['Manager', 'Looks after all helpers'], ['Chat helper', 'Ask anything, no ticket'], ['Plain terminal', 'An empty terminal in this workspace']].forEach(function (o) {
      var ex = S.some(function (s) { return s.k === o[0]; });
      h += '<button class="mw-opt" type="button" data-act="new" data-k="' + o[0] + '"><strong>' + o[0] + '</strong><span class="meta">' + (ex ? 'Already open: go to it' : o[1]) + '</span></button>';
    });
    return h + '</div><footer class="mw-tfoot"><span class="meta">' + used() + ' of ' + MAX + ' helper places in use</span><span class="grow"></span>' + mk(6) + '</footer></article>';
  }
  function wallHTML() {
    var c = { wait: 0, run: 0, idle: 0 }, list = sorted();
    S.forEach(function (s) { if (c[s.s] !== undefined) c[s.s]++; });
    var pins = st.pins.filter(function (k) { return live(by(k)) && by(k).k === k; });
    var h = '<div class="mw-wall"><header class="mw-wh"><div><div class="mw-h1"><h1>Focus</h1>' + mk(1) + '</div><p class="meta" role="status">' + (c.wait ? c.wait + ' needs you' : 'Nobody needs you') + ' · ' + c.run + ' working · ' + c.idle + ' idle · ' + used() + ' of ' + MAX + ' helper places in use</p></div><div class="mw-pinctl">' + mk(9) + '<span class="meta">' + (pins.length ? pins.length + ' pinned side by side' : 'Pin up to 4 tiles to keep them side by side') + '</span>' + (pins.length ? '<button class="btn sm ghost" type="button" data-act="unpinall">Unpin all</button>' : '') + '</div></header>';
    if (pins.length) {
      h += '<div class="mw-pins" data-n="' + (pins.length > 2 ? 4 : pins.length) + '">' + pins.map(function (k) {
        return pane(k, 'md', { term: true, noshelf: true, tools: '<button class="btn icon sm ghost" type="button" data-act="pin" data-k="' + k + '" aria-pressed="true" aria-label="Unpin ' + esc(k) + '">' + I.pin + '</button><button class="btn sm ghost" type="button" data-act="zoom" data-k="' + k + '">Zoom in</button>' });
      }).join('') + (pins.length === 3 ? '<div class="mw-slot meta">Pin one more tile to fill this place</div>' : '') + '</div>';
    }
    h += '<div class="mw-grid">' + list.filter(function (s) { return pins.indexOf(s.k) < 0; }).map(tile).join('') + addTile() + '</div></div>';
    return h;
  }
  function zoomHTML() {
    var s = by(st.cur);
    var pre = st.full ? '' : '<button class="btn sm ghost" type="button" data-act="back">' + I.back + '<span>Wall</span></button>';
    var tools = '';
    if (!st.full && live(s) && s.kind !== 'shell' && !st.ask) tools += '<button class="btn sm ghost" type="button" data-act="ask">Start again</button>';
    tools += '<span class="mw-view">' + (st.full ? '' : mk(8)) + '<button class="btn icon sm ghost" type="button" data-act="full" aria-label="' + (st.full ? 'Leave full screen' : 'Full screen') + '">' + (st.full ? I.exit : I.full) + '</button></span>';
    var h = '<div class="mw-zoom"><h1 class="sr-only">Focus: ' + esc(s.k) + '</h1>' + pane(s.k, 'lg', { main: true, mk: !st.full, pre: pre, tools: tools, noshelf: st.full });
    h += '<nav class="mw-film" aria-label="Other sessions">' + sorted().filter(function (o) { return o.k !== s.k; }).map(function (o) {
      return '<button class="mw-fb" type="button" data-act="switch" data-k="' + o.k + '" data-s="' + o.s + '" aria-label="Switch to ' + esc(o.k + ', ' + word(o)) + '">' + stat(o, true) + '<span class="mw-key">' + esc(o.k) + '</span><span class="mw-last truncate" data-last="' + o.k + '">' + esc(lastLine(o)) + '</span></button>';
    }).join('') + '</nav></div>';
    return h;
  }
  function lastLine(s) { for (var i = s.lines.length - 1; i >= 0; i--) if (s.lines[i].trim() && s.lines[i].trim() !== '>') return s.lines[i].replace(/^[\s⏺⎿]+/, ''); return word(s); }

  /* ---------- mock pages ---------- */
  function verb(s) { return { wait: 'Answer', run: 'Watch', idle: 'Open', none: 'Start', queue: 'In line', open: 'Open' }[s.s]; }
  function fbtn(s, long) { return '<button class="btn outline sm" type="button" data-act="focus" data-k="' + s.k + '" aria-label="' + verb(s) + ' ' + esc(s.k) + ' in Focus">' + verb(s) + (long ? ' in Focus' : '') + '</button>'; }
  function row(s, pick) {
    return '<div class="mw-row"' + (pick && st.tk === s.k ? ' data-on="1"' : '') + '>' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span>' + (pick ? '<button class="mw-rt truncate" type="button" data-act="tk" data-k="' + s.k + '" aria-pressed="' + (st.tk === s.k) + '">' + esc(s.t) + '</button>' : '<span class="mw-rt truncate">' + esc(s.t) + '</span>') + fbtn(s) + '</div>';
  }
  var tk = function () { return S.filter(function (s) { return s.kind === 'ticket'; }); };
  var PG = {
    home: function () {
      var need = tk().filter(function (s) { return s.s === 'wait'; }), work = tk().filter(function (s) { return s.s === 'run'; });
      return '<div class="mw-pg"><h1>Home</h1><p class="meta">The small Focus window in the corner follows you. Type a line in it, then change page: it is still there.</p><section class="card pad"><h2>Needs you</h2>' + (need.length ? need.map(function (s) { return row(s); }).join('') : '<p class="meta">Nothing needs you right now.</p>') + '</section><section class="card pad"><h2>Working now</h2>' + work.map(function (s) { return row(s); }).join('') + '</section></div>';
    },
    tickets: function () {
      var s = by(st.tk), names = ['Read the ticket', 'Sketch the change', 'Build it', 'Test it at three widths', 'Open the pull request', 'Get it merged'];
      var h = '<div class="mw-pg"><div class="mw-h1"><h1>Tickets</h1>' + mk(3) + '</div><p class="meta">Every ticket has one Focus button. The word on it follows what the helper is doing.</p><div class="mw-two"><section class="card pad" aria-label="All tickets">' + tk().map(function (x) { return row(x, true); }).join('') + '</section>';
      h += '<section class="card pad mw-tk" aria-label="Open ticket"><p class="mw-thead">' + stat(s) + '<span class="mw-key">' + esc(s.k) + '</span></p><h2>' + esc(s.t) + '</h2><ol class="mw-cl">';
      for (var i = 1; i <= s.step[1]; i++) h += '<li' + (i <= s.step[0] ? ' data-on="1"' : '') + '><span aria-hidden="true">' + (i <= s.step[0] ? '✓' : '○') + '</span> ' + names[i - 1] + (i <= s.step[0] ? '<span class="sr-only"> (done)</span>' : '') + '</li>';
      return h + '</ol><div class="mw-ans">' + fbtn(s, true) + '</div></section></div></div>';
    },
    review: function () {
      return '<div class="mw-pg"><h1>Review</h1><p class="meta">Results that wait for your look. Focus stays open while you check them.</p><section class="card pad mw-rev"><span class="mw-thumb">' + TH.img + '</span><div><h2>Steer a helper from the dashboard</h2><p class="meta">ORCH-247 · merged on green checks · 1 picture, 1 pull request</p><div class="mw-ans"><button class="btn outline sm" type="button" data-act="focus" data-k="ORCH-247">Open in Focus</button></div></div></section><section class="card pad mw-rev"><span class="mw-thumb">' + TH.html + '</span><div><h2>Newsletter draft</h2><p class="meta">A page to read · no helper is running</p><div class="mw-ans"><a class="btn outline sm" href="newsletter-preview.html" target="_blank" rel="noopener">Open page</a></div></div></section></div>';
    }
  };

  /* ---------- floating window (every page but Focus) ---------- */
  function floatHTML() {
    if (st.page === 'focus') return '';
    var s = by(st.cur), mode = st.full ? 'full' : st.mode;
    if (mode === 'strip') {
      var w = S.filter(function (x) { return x.s === 'wait'; }).length;
      return '<button class="mw-strip" type="button" data-act="mode" data-m="' + st.last + '" data-s="' + (w ? 'wait' : s.s) + '" aria-label="Show Focus">' + stat(w ? { s: 'wait' } : s, true) + '<span>Focus</span><span class="meta">' + (w ? w + ' needs you' : esc(s.k) + ' · ' + word(s)) + '</span></button>';
    }
    var b = function (m, label, icon) { return '<button class="btn icon sm ghost" type="button" data-act="mode" data-m="' + m + '" aria-label="' + label + '">' + icon + '</button>'; };
    var tools = mode === 'full' ? '<button class="btn icon sm ghost" type="button" data-act="full" aria-label="Leave full screen">' + I.exit + '</button>'
      : (mode === 'pip' ? b('right', 'Dock on the right', I.right) : b(mode === 'right' ? 'bottom' : 'right', mode === 'right' ? 'Move to the bottom' : 'Move to the right', mode === 'right' ? I.bottom : I.right) + b('pip', 'Back to a small window', I.mini))
        + '<button class="btn icon sm ghost" type="button" data-act="full" aria-label="Full screen">' + I.full + '</button>' + b('strip', 'Hide Focus', I.min);
    var h = '<section class="mw-float" data-mode="' + mode + '" aria-label="Focus window"><header class="mw-fbar"><span class="mw-grip" aria-hidden="true">⠿</span><strong>Focus</strong>' + (mode === 'full' ? '' : mk(7)) + '<span class="grow"></span>' + tools + '</header>';
    if (mode !== 'full') h += '<nav class="mw-sw" aria-label="Sessions">' + sorted().map(function (o) {
      return '<button class="mw-swb" type="button" data-act="switch" data-k="' + o.k + '" data-s="' + o.s + '" aria-pressed="' + (o.k === s.k) + '" aria-label="' + esc(o.k + ', ' + word(o)) + '">' + stat(o, true) + '<span>' + esc(o.k.replace('ORCH-', '')) + '</span></button>';
    }).join('') + '</nav>';
    return h + pane(s.k, mode === 'pip' ? 'sm' : 'md', { main: true, noshelf: mode === 'full' }) + '</section>';
  }

  /* ---------- features sheet ---------- */
  function sheetHTML() {
    var n = Object.keys(picks).filter(function (k) { return picks[k]; }).length;
    var h = '<header class="mw-shh"><div><h2>Features</h2><p class="meta" role="status">' + n + ' of ' + F.length + ' picked</p></div><button class="btn icon sm ghost" type="button" data-act="sheet" aria-label="Close features">' + I.x + '</button></header><div class="mw-feats">';
    F.forEach(function (f) {
      h += '<article class="mw-feat" id="mw-f' + f[0] + '"' + (st.feat === f[0] ? ' data-on="1"' : '') + '><h3><span class="mw-mk" data-pick="' + (picks[f[0]] || '') + '" aria-hidden="true">' + f[0] + '</span>' + esc(f[1]) + '</h3><p>' + esc(f[2]) + '</p><p class="meta"><strong>In orch:</strong> ' + esc(f[3]) + '</p><p class="meta"><strong>New work:</strong> ' + f[4] + ', ' + esc(f[5]) + '.</p><div class="mw-frow"><span class="segmented" role="group" aria-label="Your pick for ' + esc(f[1]) + '">';
      ['Keep', 'Maybe', 'Drop'].forEach(function (p) { h += '<button class="btn sm" type="button" data-act="pick" data-n="' + f[0] + '" data-p="' + p.toLowerCase() + '" aria-pressed="' + (picks[f[0]] === p.toLowerCase()) + '">' + p + '</button>'; });
      h += '</span><button class="btn sm ghost" type="button" data-act="show" data-n="' + f[0] + '">Show me</button></div></article>';
    });
    return h + '</div><footer class="mw-shf"><button class="btn outline" type="button" data-act="copy">Copy my picks</button><span class="meta" id="mw-copied" role="status"></span></footer>';
  }

  /* ---------- render ---------- */
  function render(focusSel) {
    uid = 0;
    var b = document.body, mode = st.full ? 'full' : st.mode;
    b.dataset.mwPage = st.page; b.dataset.mwView = st.page === 'focus' ? st.view : '';
    b.dataset.mwFull = st.full ? '1' : ''; b.dataset.mwSheet = st.sheet ? '1' : '';
    b.dataset.mwDock = st.page !== 'focus' ? mode : '';
    $('mw-page').innerHTML = st.page === 'focus' ? (st.view === 'zoom' ? zoomHTML() : wallHTML()) : PG[st.page]();
    $('mw-float').innerHTML = floatHTML();
    var sh = $('mw-sheet'); sh.innerHTML = sheetHTML(); sh.inert = !st.sheet; sh.setAttribute('aria-hidden', String(!st.sheet));
    $('mw-crumb').textContent = PAGES[st.page];
    var fb = $('mw-fbtn'); fb.setAttribute('aria-expanded', String(st.sheet));
    document.querySelectorAll('.sidebar .nav-item[aria-label]').forEach(function (a) { var p = a.getAttribute('aria-label').toLowerCase(); if (PAGES[p]) { if (p === st.page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); } });
    document.querySelectorAll('#mw-pages [data-p]').forEach(function (x) { x.setAttribute('aria-pressed', String(x.dataset.p === st.page)); });
    document.querySelectorAll('.mw-screen[data-n="0"],.mw-chat').forEach(function (x) { x.scrollTop = x.scrollHeight; });
    place();
    url();
    if (focusSel) { var t = document.querySelector(focusSel); if (t) t.focus({ preventScroll: false }); }
  }
  function place() {
    var f = document.querySelector('.mw-float[data-mode=pip]');
    if (f && st.pos && window.innerWidth > 720) f.style.transform = 'translate(' + st.pos.x + 'px,' + st.pos.y + 'px)';
  }
  function url() {
    var p = ['page=' + st.page];
    if (st.page === 'focus') p.push('view=' + st.view); else p.push('mode=' + (st.full ? 'full' : st.mode));
    if (st.page === 'focus' && st.full) p.push('mode=full');
    p.push('cur=' + encodeURIComponent(st.cur));
    if (st.term) p.push('term=1');
    if (st.pins.length) p.push('split=' + st.pins.length);
    if (st.ask) p.push('ask=1');
    if (st.add) p.push('add=1');
    if (st.sheet) p.push('sheet=' + (st.feat || 1));
    try { history.replaceState(null, '', '?' + p.join('&')); } catch (e) { /* file pages may refuse */ }
  }
  function refresh() {
    document.querySelectorAll('[data-screen]').forEach(function (el) {
      var s = by(el.dataset.screen), n = +el.dataset.n, near = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      el.textContent = screenText(s, n);
      if (!n && near) el.scrollTop = el.scrollHeight;
    });
    document.querySelectorAll('[data-last]').forEach(function (el) { el.textContent = lastLine(by(el.dataset.last)); });
  }
  function refreshChat(k) {
    document.querySelectorAll('[data-chat]').forEach(function (el) { if (el.dataset.chat === k) { el.innerHTML = chatMsgs(by(k)); el.scrollTop = el.scrollHeight; } });
  }
  function say(t) { $('mw-live').textContent = t; }
  function push(s, line) { s.lines.push(line); if (s.lines.length > 60) s.lines.shift(); }
  function flip(el, from) {
    if (!el || !from || reduce || !el.animate) return;
    var to = el.getBoundingClientRect(); if (!to.width || !to.height) return;
    var cs = getComputedStyle(document.documentElement);
    el.animate([{ transformOrigin: '0 0', transform: 'translate(' + (from.left - to.left) + 'px,' + (from.top - to.top) + 'px) scale(' + from.width / to.width + ',' + from.height / to.height + ')', opacity: 0.6 }, { transformOrigin: '0 0', transform: 'none', opacity: 1 }],
      { duration: parseFloat(cs.getPropertyValue('--dur-slow')) || 240, easing: (cs.getPropertyValue('--ease-move') || 'ease-out').trim() });
  }
  function rectOf(sel) { var e = document.querySelector(sel); return e ? e.getBoundingClientRect() : null; }

  /* ---------- actions ---------- */
  function zoom(k, ask) {
    var from = rectOf('.mw-tile[data-k="' + k + '"]') || rectOf('.mw-pins .mw-pane[data-k="' + k + '"]');
    st.cur = k; st.view = 'zoom'; st.page = 'focus'; st.add = false; st.ask = !!ask && live(by(k));
    render('.mw-zoom [data-act=back]');
    flip(document.querySelector('.mw-zoom .mw-pane'), from);
  }
  function back() {
    var from = rectOf('.mw-zoom .mw-pane');
    st.view = 'wall'; st.full = false; st.ask = false;
    render('.mw-tile[data-k="' + st.cur + '"] .mw-topen');
    flip(document.querySelector('.mw-tile[data-k="' + st.cur + '"]') || document.querySelector('.mw-pins .mw-pane[data-k="' + st.cur + '"]'), from);
  }
  function answer(k, i) {
    var s = by(k); if (!s.q) return;
    var a = s.q.a[i];
    push(s, '> ' + (i + 1)); push(s, '⏺ ' + a + '. Going on with step ' + (s.step ? s.step[0] + 1 : 2) + '.');
    s.chat.push(['y', a, 'now'], ['h', 'Thanks. I go on with the next step.', 'now']);
    s.q = null; s.s = 'run'; s.feed = ['⏺ Bash(node --test tests/attach.test.js)', '  ⎿ ✔ the same file twice keeps one name (22 ms)', '⏺ Writing the note about file names into the help text.'];
    say('Answer sent to ' + k + '. The helper is working again.');
    render('[data-act=zoom][data-k="' + k + '"],.mw-pane[data-k="' + k + '"] input');
  }
  function start(k, how) {
    var s = by(k), was = live(s);
    if (how === 'clean') s.lines = ['⏺ New conversation, clean context.', '⏺ Reading the ticket and its files…'];
    else { push(s, ''); push(s, '⏺ Resuming the earlier conversation…'); push(s, '⏺ Picking up where it stopped.'); }
    s.chat.push(['e', how === 'clean' ? 'Started clean with a new context window' : 'Continued the earlier conversation', 'now']);
    s.q = null; s.sl = '';
    if (!was && s.kind !== 'shell' && used() >= MAX) { s.s = 'queue'; say(k + ' waits in line for a free helper place.'); }
    else { s.s = 'run'; s.feed = ['⏺ Read(ticket notes)', '⏺ Planning the next step.', '⏺ Working on it…']; say('Helper started on ' + k + '.'); }
    st.ask = false;
    render('.mw-pane[data-k="' + k + '"] input');
  }
  function create(k) {
    if (!S.some(function (s) { return s.k === k; })) {
      if (k === 'Plain terminal') S.push({ k: k, t: 'No ticket · no helper', kind: 'shell', s: 'open', lines: ['Last login: today 15:06', 'demo@workspace ~ %'], chat: [], files: [] });
      else {
        var full = used() >= MAX;
        S.push({ k: k, t: 'No ticket · ask anything', kind: 'free', s: full ? 'queue' : 'run', lines: ['⏺ Hello. Ask me anything about this workspace.', '>'], chat: [['h', 'Hello. Ask me anything about this workspace.', 'now']], files: [] });
      }
      say(k + ' opened.');
    }
    zoom(k);
  }
  function pin(k) {
    var i = st.pins.indexOf(k);
    if (i >= 0) st.pins.splice(i, 1); else { st.pins.push(k); if (st.pins.length > 4) st.pins.shift(); }
    render('[data-act=pin][data-k="' + k + '"]');
  }
  function setPage(p) {
    st.page = p; st.add = false;
    st.ask = false;
    if (p === 'focus') st.view = st.full ? 'zoom' : 'wall';
    render();
    var m = $('content'); if (m) m.focus({ preventScroll: true });
    say(PAGES[p] + ' page. Focus stays open.');
  }
  function focusOn(k) {
    st.cur = k; st.ask = false;
    if (st.mode === 'strip') st.mode = st.last || 'pip';
    render('.mw-float .mw-pane button, .mw-float .mw-pane input');
  }
  function setMode(m) {
    if (m !== 'strip') st.last = m;
    st.mode = m; st.full = false;
    render(m === 'strip' ? '.mw-strip' : '.mw-float [data-act=mode]');
  }
  function need(k) {
    var o = JSON.parse(S0).filter(function (s) { return s.k === k; })[0], s = by(k);
    if (o && s.s !== o.s) S[S.indexOf(s)] = o;
  }
  function show(n) {
    var o = F[n - 1][6];
    if (o.need) need(o.need);
    st.full = false; st.ask = false; st.add = false; st.pins = []; st.open = '';
    Object.keys(o).forEach(function (k) { if (k !== 'need') st[k] = o[k]; });
    if (st.mode !== 'strip') st.last = st.mode;
    st.feat = n; if (window.innerWidth <= 900 || o.full) st.sheet = false;
    render();
  }
  function openSheet(n) {
    st.sheet = true; st.feat = n || st.feat; if (st.full) st.full = false;
    render();
    var t = n ? $('mw-f' + n) : null;
    if (t) { t.scrollIntoView({ block: 'nearest' }); var bt = t.querySelector('button'); if (bt) bt.focus(); }
    else { var c = document.querySelector('#mw-sheet button'); if (c) c.focus(); }
  }
  function copy() {
    var t = 'Focus v4b (mission control wall): my picks\n' + F.map(function (f) { return f[0] + '. ' + f[1] + ': ' + (picks[f[0]] || 'not picked'); }).join('\n');
    var done = function () { var e = $('mw-copied'); if (e) e.textContent = 'Copied'; };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(t).then(done, function () { fallback(t); done(); }); else { fallback(t); done(); }
  }
  function fallback(t) { var a = document.createElement('textarea'); a.value = t; a.className = 'sr-only'; document.body.appendChild(a); a.select(); try { document.execCommand('copy'); } catch (e) { /* no clipboard */ } a.remove(); }

  document.addEventListener('click', function (e) {
    var nav = e.target.closest('.sidebar .nav-item[aria-label], .sidebar .brand');
    if (nav) { var p = nav.classList.contains('brand') ? 'home' : nav.getAttribute('aria-label').toLowerCase(); if (PAGES[p]) { e.preventDefault(); setPage(p); return; } }
    var b = e.target.closest('[data-act]'); if (!b) return;
    var a = b.dataset.act, k = b.dataset.k;
    if (a === 'page') setPage(b.dataset.p);
    else if (a === 'zoom') zoom(k, b.dataset.ask);
    else if (a === 'back') back();
    else if (a === 'switch') { st.cur = k; st.ask = false; render('[data-act=switch]' + (st.page === 'focus' ? '' : '[data-k="' + k + '"]')); }
    else if (a === 'view') { st.term = b.dataset.v === 'term'; render('[data-act=view][data-v=' + b.dataset.v + ']'); }
    else if (a === 'full') { st.full = !st.full; if (st.full) st.sheet = false; render('[data-act=full]'); }
    else if (a === 'mode') setMode(b.dataset.m);
    else if (a === 'pin') pin(k);
    else if (a === 'unpinall') { st.pins = []; render('.mw-topen'); }
    else if (a === 'answer') answer(k, +b.dataset.a);
    else if (a === 'start') start(k, b.dataset.how);
    else if (a === 'ask') { st.ask = true; render('.mw-start button'); }
    else if (a === 'askoff') { st.ask = false; render('[data-act=ask]'); }
    else if (a === 'add') { st.add = !st.add; render(st.add ? '.mw-opt' : '.mw-add .mw-topen'); }
    else if (a === 'new') create(k);
    else if (a === 'focus') focusOn(k);
    else if (a === 'tk') { st.tk = k; render('[data-act=tk][data-k="' + k + '"]'); }
    else if (a === 'res') { st.open = st.open === b.dataset.id ? '' : b.dataset.id; render('[data-act=res][data-id="' + b.dataset.id + '"]'); }
    else if (a === 'feat') openSheet(+b.dataset.n);
    else if (a === 'sheet') { if (st.sheet) { st.sheet = false; render('#mw-fbtn'); } else openSheet(0); }
    else if (a === 'show') show(+b.dataset.n);
    else if (a === 'pick') { var n = b.dataset.n; picks[n] = picks[n] === b.dataset.p ? '' : b.dataset.p; try { localStorage.setItem(KEY, JSON.stringify(picks)); } catch (er) { /* private window */ } render('[data-act=pick][data-n="' + n + '"][data-p=' + b.dataset.p + ']'); }
    else if (a === 'copy') copy();
  });
  document.addEventListener('input', function (e) { var d = e.target.dataset && e.target.dataset.d; if (d) drafts[d] = e.target.value; });
  document.addEventListener('submit', function (e) {
    var f = e.target.closest('form[data-f]'); if (!f) return;
    e.preventDefault();
    var inp = f.querySelector('input'), v = inp.value.trim(), s = by(f.dataset.k); if (!v) return;
    inp.value = ''; drafts[inp.dataset.d] = '';
    if (f.dataset.f === 'term') {
      push(s, (s.kind === 'shell' ? 'demo@workspace ~ % ' : '> ') + v);
      setTimeout(function () { push(s, s.kind === 'shell' ? 'demo terminal: nothing was run' : '⏺ Got it: "' + v + '". I take that into account.'); refresh(); }, 500);
      refresh(); document.querySelectorAll('.mw-screen[data-n="0"]').forEach(function (x) { x.scrollTop = x.scrollHeight; });
    } else {
      s.chat.push(['y', v, 'now']); push(s, '> ' + v);
      setTimeout(function () { s.chat.push(['h', 'Got it. I take that into account.', 'now']); push(s, '⏺ Got it. I take that into account.'); refreshChat(s.k); refresh(); }, 600);
      refreshChat(s.k); refresh();
    }
  });
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'j' || e.key === 'J')) {
      e.preventDefault();
      if (st.page === 'focus') { if (st.view === 'zoom') back(); else zoom(st.cur); }
      else if (st.full) { st.full = false; render(); }
      else setMode(st.mode === 'strip' ? (st.last || 'pip') : 'strip');
      return;
    }
    if (e.key !== 'Escape') return;
    if (st.sheet) { st.sheet = false; render('#mw-fbtn'); }
    else if (st.add) { st.add = false; render('.mw-add .mw-topen'); }
    else if (st.ask && live(by(st.cur))) { st.ask = false; render('[data-act=ask]'); }
    else if (st.full) { st.full = false; render('[data-act=full]'); }
    else if (st.page === 'focus' && st.view === 'zoom') back();
  });
  /* the mini window can be moved by its bar (wide screens only) */
  document.addEventListener('pointerdown', function (e) {
    var bar = e.target.closest('.mw-float[data-mode=pip] .mw-fbar'); if (!bar || e.target.closest('button') || window.innerWidth <= 720) return;
    var f = bar.parentNode, p0 = st.pos || { x: 0, y: 0 }, x0 = e.clientX, y0 = e.clientY, r = f.getBoundingClientRect();
    function mv(ev) {
      var x = p0.x + ev.clientX - x0, y = p0.y + ev.clientY - y0;
      x = Math.max(p0.x - r.left + 8, Math.min(x, p0.x + window.innerWidth - r.right - 8));
      y = Math.max(p0.y - r.top + 8, Math.min(y, p0.y + window.innerHeight - r.bottom - 8));
      st.pos = { x: x, y: y }; place();
    }
    function up() { document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); }
    document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up); e.preventDefault();
  });
  /* live lines: one working session gets its next line every few seconds */
  setInterval(function () {
    var w = S.filter(function (s) { return s.s === 'run' && s.feed && s.feed.length; }); if (!w.length) return;
    var s = w[feedAt++ % w.length]; s.fi = (s.fi || 0);
    push(s, s.feed[s.fi++ % s.feed.length]); refresh();
  }, 2400);

  /* ---------- start: read the link ---------- */
  (function () {
    var q = new URLSearchParams(location.search), v;
    if (PAGES[v = q.get('page')]) st.page = v;
    if ((v = q.get('cur')) && S.some(function (s) { return s.k === v; })) { st.cur = v; if (by(v).kind === 'ticket') st.tk = v; }
    v = q.get('mode');
    if (v === 'full') st.full = true; else if (/^(pip|right|bottom|strip)$/.test(v || '')) { st.mode = v; if (v !== 'strip') st.last = v; }
    if (q.get('view') === 'zoom' || st.full || q.get('ask') === '1') st.view = 'zoom';
    if (q.get('view') === 'wall' && !st.full) st.view = 'wall';
    st.term = q.get('term') === '1';
    st.ask = q.get('ask') === '1' && live(by(st.cur));
    st.add = q.get('add') === '1';
    v = +q.get('split');
    if (v === 1 || v === 2 || v === 4) { var l = S.filter(live).map(function (s) { return s.k; }); if (l.indexOf(st.cur) > 0) { l.splice(l.indexOf(st.cur), 1); l.unshift(st.cur); } st.pins = l.slice(0, v); }
    if ((v = q.get('sheet'))) { st.sheet = true; st.feat = +v > 1 && +v <= F.length ? +v : 0; }
    render();
    if (st.sheet && st.feat) { var t = $('mw-f' + st.feat); if (t) t.scrollIntoView({ block: 'nearest' }); }
  })();
})();

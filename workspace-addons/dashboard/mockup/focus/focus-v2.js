/* Focus v2 draft: eight features to pick from. Demo data only; picks stay in this browser. */
(function () {
  var F = [
    [1, 'Open Focus from any ticket', 'A button on every ticket: Watch (running), Answer (waiting) or Start (no session).'],
    [2, 'Reopen an old session or start fresh', 'Pick an earlier conversation, or begin with a clean context window.'],
    [3, 'Chat or real terminal', 'Chat for plain updates; Terminal is a real tmux screen with copy, paste and edit.'],
    [4, 'Sessions without a ticket', 'Open a Manager, Chat or plain terminal that belongs to no ticket.'],
    [5, 'Drawer: right or bottom', 'Focus stays on any page as a drawer you open and close.'],
    [6, 'Full screen', 'Hide everything around it. Esc brings it back.'],
    [7, 'Several tickets at once', 'Tabs with a live status dot; switching keeps each screen warm.'],
    [8, 'Results as pictures', 'Screenshots, pages, tables and pull requests as small visual cards, not text.']
  ];
  var SESS = [
    ['ORCH-228', 'Phone width and zoom', 'run', 'Working · step 5 of 5'],
    ['ORCH-230', 'Insights add-on', 'wait', 'Needs you · 1 question'],
    ['ORCH-189', 'Manager view', 'idle', 'No session'],
    ['Manager', 'No ticket', 'run', 'Working']
  ];
  var LABEL = { run: 'Working', wait: 'Needs you', idle: 'Idle' };
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function h(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  var store = { get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
  var picks = {}; try { picks = JSON.parse(store.get('fv2-picks') || '{}'); } catch (e) {}
  var st = { scene: 'right', mode: 'chat', open: 0, history: false, launcher: false };

  function mark(n) { var b = h('button', 'fv2-n', String(n)); b.type = 'button'; b.dataset.n = n; b.setAttribute('aria-label', 'Feature ' + n + ': ' + F[n - 1][1]); b.addEventListener('click', function () { var r = $('#pick-' + n); if (r) { r.scrollIntoView({ block: 'nearest' }); r.focus(); } }); return b; }
  function dot(s) { var d = h('span', 'fv2-dot ' + s); d.setAttribute('role', 'img'); d.setAttribute('aria-label', LABEL[s]); return d; }

  function picker() {
    var box = $('#fv2-picks'); box.textContent = '';
    box.append(h('h2', '', 'Your picks'), h('p', 'meta', 'Circle numbers on the page match these rows.'));
    F.forEach(function (f) {
      var row = h('div', 'fv2-pick'); row.id = 'pick-' + f[0]; row.tabIndex = -1;
      var t = h('div', 'fv2-pick-t'); t.append(h('span', 'fv2-n static', String(f[0])), h('b', '', f[1])); row.append(t, h('p', 'meta', f[2]));
      var seg = h('div', 'segmented'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'Pick for feature ' + f[0]);
      [['keep', 'Keep'], ['maybe', 'Maybe'], ['drop', 'Drop']].forEach(function (o) {
        var b = h('button', 'btn sm', o[1]); b.type = 'button'; b.setAttribute('aria-pressed', picks[f[0]] === o[0]);
        b.addEventListener('click', function () { picks[f[0]] = picks[f[0]] === o[0] ? '' : o[0]; store.set('fv2-picks', JSON.stringify(picks)); paint(); });
        seg.append(b);
      });
      row.append(seg); box.append(row);
    });
    var c = h('button', 'btn sm', 'Copy my picks'); c.type = 'button';
    c.addEventListener('click', function () {
      var txt = F.map(function (f) { return f[0] + '. ' + f[1] + ': ' + (picks[f[0]] || 'no pick'); }).join('\n');
      var done = function () { c.textContent = 'Copied'; setTimeout(function () { c.textContent = 'Copy my picks'; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(txt).then(done, function () { c.textContent = txt; }); else c.textContent = txt;
    });
    box.append(c);
  }

  function drawer() {
    var d = h('aside', 'fv2-drawer'); d.setAttribute('aria-label', 'Focus drawer');
    var top = h('div', 'fv2-d-top');
    var tabs = h('div', 'fv2-tabs'); tabs.setAttribute('role', 'tablist');
    var order = SESS.map(function (x, i) { return i; }).sort(function (x, y) { return (SESS[x][2] === 'wait' ? 0 : 1) - (SESS[y][2] === 'wait' ? 0 : 1); });
    order.forEach(function (i) {
      var s = SESS[i], b = h('button', 'fv2-tab'); b.type = 'button'; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', i === st.open);
      b.append(dot(s[2]), h('span', '', s[0]));
      if (s[2] === 'wait') b.append(h('span', 'fv2-flag', 'Needs you'));
      b.addEventListener('click', function () { st.open = i; render(); });
      tabs.append(b);
    });
    var plus = h('button', 'btn ghost icon sm', '+'); plus.type = 'button'; plus.setAttribute('aria-label', 'Open a session'); plus.addEventListener('click', function () { st.launcher = !st.launcher; st.history = false; render(); });
    var seg = h('div', 'segmented'); seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'View');
    ['chat', 'terminal'].forEach(function (m) { var b = h('button', 'btn sm', m === 'chat' ? 'Chat' : 'Terminal'); b.type = 'button'; b.setAttribute('aria-pressed', st.mode === m); b.addEventListener('click', function () { st.mode = m; render(); }); seg.append(b); });
    var more = h('button', 'btn ghost icon sm', '⋯'); more.type = 'button'; more.setAttribute('aria-label', 'Sessions and dock'); more.addEventListener('click', function () { st.history = !st.history; st.launcher = false; render(); });
    var exp = h('button', 'btn ghost icon sm', st.scene === 'full' ? '⤡' : '⤢'); exp.type = 'button'; exp.setAttribute('aria-label', st.scene === 'full' ? 'Leave full screen' : 'Full screen'); exp.addEventListener('click', function () { st.scene = st.scene === 'full' ? 'right' : 'full'; render(); });
    var close = h('button', 'btn ghost icon sm', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Close drawer'); close.addEventListener('click', function () { st.scene = 'closed'; render(); });
    tabs.append(plus, mark(7)); top.append(tabs, seg, mark(3), more, mark(2), exp, mark(6), close, mark(5));
    d.append(top);
    if (st.launcher) d.append(launcher());
    if (st.history) {
      var hp = h('div', 'fv2-pop'); hp.append(h('b', '', SESS[st.open][0] + ' sessions'));
      var nw = h('button', 'btn primary sm', 'New session, clean context'); nw.type = 'button'; hp.append(nw, h('span', 'eyebrow', 'Reopen an earlier one'));
      ['Yesterday 16:40 · fixed menu, 4 of 5 steps', 'Mon 10:12 · diagnosis only'].forEach(function (t) { var b = h('button', 'fv2-row', t); b.type = 'button'; hp.append(b); });
      hp.append(h('span', 'eyebrow', 'Dock'));
      var dk = h('div', 'segmented'); [['right', 'Right'], ['bottom', 'Bottom']].forEach(function (q) { var b = h('button', 'btn sm', q[1]); b.type = 'button'; b.setAttribute('aria-pressed', st.scene === q[0]); b.addEventListener('click', function () { st.scene = q[0]; st.history = false; render(); }); dk.append(b); });
      hp.append(dk); d.append(hp);
    }
    var s = SESS[st.open];
    var body = h('div', 'fv2-d-body');
    if (s[2] === 'idle') {
      var e = h('div', 'fv2-empty'); e.append(h('b', '', s[0] + ' has no session'), h('p', 'meta', 'Start one when you want to work on it.')); var go = h('button', 'btn primary sm', 'Start session'); go.type = 'button'; e.append(go, mark(1)); body.append(e);
    } else if (st.mode === 'terminal') {
      var t = h('pre', 'fv2-term'); t.textContent = '$ tmux attach -t orch-228\n● Bash(node --test tests/phone.test.js)\n  ⎿  12 passed\n● Opening the pull request…\n\n> ';
      t.append(h('span', 'fv2-caret', ' '));
      body.append(t, h('p', 'meta fv2-note', 'A real tmux terminal: select, copy, paste and edit exactly as in Terminal.app.'));
    } else {
      var log = h('div', 'fv2-chat');
      [['Helper', 'Step 5 of 5: opening the pull request.'], ['You', 'Also check 320 px wide.'], ['Helper', 'Done. 320 px passes.']].forEach(function (m) { var b = h('div', 'fv2-bub ' + (m[0] === 'You' ? 'me' : '')); b.append(h('span', 'meta', m[0]), h('p', '', m[1])); log.append(b); });
      var box = h('div', 'fv2-compose'); var inp = h('input', 'input'); inp.placeholder = 'Write a message…'; inp.setAttribute('aria-label', 'Message'); var snd = h('button', 'btn sm', 'Send'); snd.type = 'button'; box.append(inp, snd);
      body.append(log, box);
    }
    d.append(body);
    return d;
  }

  function launcher() {
    var p = h('div', 'fv2-pop');
    p.append(h('b', '', 'Open a session'));
    var g1 = h('div', 'fv2-grp'); g1.append(h('span', 'eyebrow', 'For a ticket'));
    SESS.slice(0, 3).forEach(function (s) { var b = h('button', 'fv2-row'); b.type = 'button'; b.append(dot(s[2]), h('span', '', s[0] + ' · ' + s[1]), h('span', 'meta', s[3])); g1.append(b); });
    var g2 = h('div', 'fv2-grp'); g2.append(h('span', 'eyebrow', 'Without a ticket'), mark(4));
    ['Manager', 'Chat helper', 'Plain terminal'].forEach(function (n) { var b = h('button', 'fv2-row'); b.type = 'button'; b.append(h('span', '', n), h('span', 'meta', 'New tmux session')); g2.append(b); });
    p.append(g1, g2); return p;
  }

  function results() {
    var r = h('section', 'fv2-res'); r.setAttribute('aria-label', 'Results');
    r.append(h('h2', '', 'Results'), mark(8));
    var g = h('div', 'fv2-cards');
    function card(kind, title, sub) { var c = h('button', 'fv2-card'); c.type = 'button'; var th = h('div', 'fv2-th ' + kind); c.append(th, h('b', '', title), h('span', 'meta', sub)); g.append(c); return th; }
    var sh = card('shot', 'Phone at 320', 'Screenshot'); sh.append(h('em', '', '≡'), h('em', '', '≡'));
    var pg = card('page', 'Ticket page', 'Open page ↗'); pg.append(h('i'), h('i'), h('i'));
    var tb = card('chart', '6 checks passed', 'Chart'); [60, 90, 45, 100, 80].forEach(function (v) { var b = h('i'); b.style.setProperty('--v', v + '%'); tb.append(b); });
    var pr = card('pr', 'Pull request #1252', 'Checks running'); pr.append(h('em', '', '✓ 5 · ◔ 1'));
    r.append(g); return r;
  }

  function stage() {
    var s = $('#fv2-stage'); s.textContent = ''; s.dataset.scene = st.scene;
    var page = h('div', 'fv2-page');
    var hd = h('header', 'fv2-ph'); var l = h('div'); l.append(h('span', 'meta', 'ORCH-228'), h('h2', '', 'Phone width and zoom'));
    var pill = h('span', 'fv2-state ' + SESS[0][2]); pill.append(dot('run'), document.createTextNode('Working · 4 of 5 steps done')); l.append(pill);
    var open = h('button', 'btn sm fv2-open', 'Watch'); open.title = 'Running: Watch · Waiting: Answer · No session: Start'; open.type = 'button'; open.addEventListener('click', function () { if (st.scene === 'closed') st.scene = 'right'; render(); });
    var bar = h('div', 'fv2-bar'); bar.append(h('i')); bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', '4 of 5 steps finished');
    var act = h('div', 'fv2-act'); act.append(open, mark(1)); hd.append(l, act); page.append(hd, bar, results());
    s.append(page);
    if (st.scene !== 'closed') s.append(drawer());
  }

  function paint() {
    $$('.fv2-pick').forEach(function (r) { var n = r.id.slice(5); $$('.segmented button', r).forEach(function (b, i) { b.setAttribute('aria-pressed', picks[n] === ['keep', 'maybe', 'drop'][i]); }); });
    $$('.fv2-n:not(.static)').forEach(function (b) { b.dataset.pick = picks[b.dataset.n] || ''; });
    var k = Object.keys(picks).filter(function (n) { return picks[n]; }).length; $('#fv2-count').textContent = k + ' of 8 picked';
  }
  function render() {
    $$('#fv2-scenes button').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.scene === st.scene || (b.dataset.scene === 'launcher' && st.launcher)); });
    document.body.classList.toggle('fv2-full', st.scene === 'full'); stage(); paint();
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && st.scene === 'full') { st.scene = 'right'; render(); } });
  $$('#fv2-scenes button').forEach(function (b) { b.addEventListener('click', function () { var s = b.dataset.scene; if (s === 'launcher') { st.scene = 'right'; st.launcher = true; } else { st.scene = s; st.launcher = false; } st.history = false; render(); }); });
  var q=new URLSearchParams(location.search);if(q.get('scene'))st.scene=q.get('scene');if(q.get('mode'))st.mode=q.get('mode');if(q.get('launcher'))st.launcher=true;if(q.get('open'))st.open=+q.get('open');
  picker(); render();
})();

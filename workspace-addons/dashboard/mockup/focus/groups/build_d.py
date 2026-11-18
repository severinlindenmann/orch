#!/usr/bin/env python3
"""Writes a-on-d.html and a-on-d.js: draft A's group (an Epic as a tree of helper sessions) on top of Focus draft D.

a-on-d.js is a COPY of ../focus-v4d.js with the changes below applied; ../focus-v4d.* are never edited.
Run again after draft D changes: python3 build_d.py. A change that no longer fits stops the build and names itself.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE.parent / "focus-v4d.js").read_text()
page = (HERE.parent / "focus-v4d.html").read_text()
bad = []


def rep(a, b, text=None):
    global src
    t = src if text is None else text
    if a not in t:
        bad.append(a[:90])
        return t
    t = t.replace(a, b)
    if text is None:
        src = t
    return t


def cut(start, end, new):
    """Replace everything from `start` up to (not including) `end`."""
    global src
    i, j = src.find(start), src.find(end)
    if i < 0 or j < i:
        bad.append(start[:90])
        return
    src = src[:i] + new + src[j:]


# ---------- the sample group: Epic "Autumn newsletter" (same data as drafts A, B, C) ----------
DATA = r"""
  /* draft 344: one Epic as a group of sessions. g = group, role main = the main helper, kind small = a small helper (watch only) */
  var GD = [
    { k: 'ORCH-301', t: 'Autumn newsletter', kind: 'ticket', g: 'G1', role: 'main', s: 'run', tool: 't1', model: 'Opus', up: 100, step: [3, 4], now: 'Checks each text as it comes in and keeps the four tickets moving.',
      lines: ['⏺ Read the plan from yesterday', '  ⎿ 3 stories, send on Tuesday 10:00', '⏺ Start helper: Write the texts', '  ⎿ Running since 09:06', '⏺ Start helper: Build the mail page', '  ⎿ Running since 09:06', '⏺ Check: the three stories', '  ⎿ Good. Subject line is 71 letters, asked for under 50', '⏺ Resting until a helper reports…'],
      chat: [['e', 'Split the work into four tickets', '09:05'], ['h', 'I started a helper for “Write the texts” and one for “Build the mail page”. The test waits for both. “Check the links” is in line for a free place.', '09:06'], ['h', 'The three stories are good. I asked for a shorter subject line.', '10:12'], ['h', '“Build the mail page” asked you a question. The texts go on meanwhile.', '10:31']], files: [] },
    { k: 'ORCH-302', t: 'Write the texts', kind: 'ticket', g: 'G1', parent: 'ORCH-301', s: 'run', tool: 't1', up: 96, step: [2, 4], now: 'Writes the intro and the three offers.',
      lines: ['⏺ Write the three stories', '  ⎿ 3 stories, 286 words', '⏺ Small helper: Draft offers', '  ⎿ Done · 3 offers, 94 words', '⏺ Small helper: Draft intro', '  ⎿ Working · 12 min', '⏺ Waiting for the intro…'],
      feed: ['⏺ Small helper: Draft intro', '  ⎿ Working · 13 min', '⏺ Reading the offers once more.'],
      chat: [['e', 'Step 1 done: the three stories are collected', '09:48'], ['h', 'Two small helpers draft the intro and the offers side by side.', '10:22'], ['h', 'The three offers are drafted. The intro is still being written.', '10:38']], files: [] },
    { k: 'Draft intro', t: 'Writes a friendly opening of about 60 words', kind: 'small', g: 'G1', parent: 'ORCH-302', s: 'run', tool: 't1', model: 'Haiku', up: 12, now: 'Second try: shorter and warmer.',
      lines: ['⏺ Read the three stories', '  ⎿ 3 stories', '⏺ Draft 1', '  ⎿ 92 words · too long', '⏺ Writing draft 2…'],
      chat: [['h', 'First try: 92 words. Too long.', '10:36'], ['h', 'Second try: shorter and warmer.', '10:40']], files: [] },
    { k: 'Draft offers', t: 'Wrote the three autumn offers', kind: 'small', g: 'G1', parent: 'ORCH-302', s: 'idle', sl: 'Done 10:38', tool: 't1', model: 'Haiku', up: 20, now: 'Handed three offers (94 words) back to its helper.',
      lines: ['⏺ Read the price list', '  ⎿ 41 products', '⏺ Write 3 offers', '  ⎿ 94 words', '  Finished 10:38'],
      chat: [['h', 'Three offers picked: pumpkin spice beans, gift box, workshop voucher.', '10:31'], ['h', 'Handed three offers (94 words) back to its helper.', '10:38']], files: [] },
    { k: 'ORCH-303', t: 'Build the mail page', kind: 'ticket', g: 'G1', parent: 'ORCH-301', s: 'wait', tool: 't1', up: 96, step: [3, 5], now: 'Waits for your answer.', qn: 2,
      q: { at: '10:31', t: 'Which header picture for the mail page?', why: 'The page is laid out. The picture at the top is the last open choice.', a: ['Autumn leaves photo', 'Shop front photo', 'No picture, only the logo'] },
      lines: ['⏺ Build the mail page', '  ⎿ 3 blocks, 600 px wide', '⏺ Check on a phone screen', '  ⎿ Fits 390 px, nothing cut', '⏺ Question for you: which header picture?', '  Waiting for your answer…'],
      chat: [['e', 'Step 2 done: the three stories have their place', '10:28'], ['h', 'The page is laid out and looks right on a phone.', '10:29'], ['h', 'One thing I need from you: which header picture should the mail page get?', '10:31', 1]], files: [] },
    { k: 'ORCH-304', t: 'Send a test to the team', kind: 'ticket', g: 'G1', parent: 'ORCH-301', s: 'queue', waits: 'Write the texts, Build the mail page', tool: 't1', step: [0, 3], now: 'Waits for: Write the texts, Build the mail page.',
      lines: [], chat: [['e', 'Planned by the main helper', '09:06']], files: [] },
    { k: 'ORCH-305', t: 'Check the links', kind: 'ticket', g: 'G1', parent: 'ORCH-301', s: 'queue', tool: 't1', step: [0, 3], now: 'In line: waiting for a free place.',
      lines: [], chat: [['e', 'Planned by the main helper', '09:06']], files: [] }
  ];
  S = GD.concat(S.filter(function (s) { return ['ORCH-228', 'ORCH-247', 'ORCH-189', 'Manager'].indexOf(s.k) >= 0; }));
"""

HELPERS = r"""
  /* ---------- draft 344: a group of sessions (an Epic or a factory order) ---------- */
  function mem(g) { return S.filter(function (s) { return s.g === g; }); }
  function ghelpers(g) { return mem(g).filter(function (s) { return s.kind !== 'small'; }).length; }  // the bar chip says the tile's helper count (ORCH-345)
  function ghead(g) { return mem(g).filter(function (s) { return s.role === 'main'; })[0]; }
  function gneed(g) { return mem(g).filter(function (s) { return s.s === 'wait' || s.s === 'stop'; }); }
  /* the state a group shows on the wall and in the bar: a child that needs you lifts the whole group */
  function es(s) { return s.role === 'main' && gneed(s.g).length ? 'wait' : s.s; }
  function tops() { return sorted().filter(function (s) { return !s.g || s.role === 'main'; }); }
  function gname(s) { return s.kind === 'small' ? s.k : nm(s); }
  function gtext(s) { return (s.role === 'main' ? mem(s.g) : [s]).map(function (x) { return x.k + ' ' + nm(x) + ' ' + word(x); }).join(' '); }
  function gsum(s) {
    var m = mem(s.g), n = gneed(s.g).length, sm = m.filter(function (x) { return x.kind === 'small'; }).length;
    return (m.length - sm) + ' helpers' + (sm ? ' · ' + sm + ' small helpers' : '') + (n ? ' · ' + n + (n === 1 ? ' needs you' : ' need you') : '');
  }
  function gsub(x) {
    var t = x.s === 'wait' ? 'Asks you' : (x.s === 'stop' ? 'Could not open the picture folder' : (x.waits ? 'Waits for: ' + x.waits : (x.s === 'queue' ? 'In line · waiting for a free place' : word(x))));
    return t + (x.step && (x.s === 'run' || x.s === 'wait') ? ' · Step ' + x.step[0] + ' of ' + x.step[1] : '') + (x.kind === 'small' ? ' · watch only' : '');
  }
  function gflag(x) { return x.s === 'wait' ? '<span class="badge needs">Needs you</span>' : (x.s === 'stop' ? '<span class="badge failed">Stopped</span>' : ''); }
  /* one row of the tree. mode: tree (zoom, full rows), sw (narrow switcher in a pane), strip (one line, phone), mini (preview on the wall tile, not clickable) */
  function grow(x, cur, mode, d) {
    var tag = x.role === 'main' ? '<span class="chip active">Main helper</span>' : (x.kind === 'small' ? '<span class="badge dashed">Small helper</span>' : '');
    var inner = mode === 'tree' ? '<span class="gd-t">' + tag + '<strong>' + esc(gname(x)) + '</strong>' + gflag(x) + '</span><span class="gd-s">' + stat(x, true) + '<span class="meta">' + esc(gsub(x)) + '</span></span>'
      : stat(x, true) + '<span class="gd-t">' + (mode === 'strip' ? '' : tag) + '<strong>' + esc(gname(x)) + '</strong></span>' + gflag(x);
    if (mode === 'mini') return '<span class="gd-rw" data-d="' + d + '"><span class="gd-row">' + inner + '</span></span>';
    return '<span class="gd-rw" data-d="' + d + '">' + btn('gd-row', 'gsel', inner, { 'data-k': x.k, 'aria-current': String(x.k === cur), 'aria-label': gname(x) + ', ' + gsub(x) }) + (mode !== 'strip' && live(x) && x.k !== cur ? besideBtn(x) : '') + '</span>';
  }
  function gtree(g, cur, mode) {
    var hd = ghead(g), h = '';
    if (mode === 'tree') h += '<div class="gd-th"><p class="eyebrow">Epic</p><h2>' + esc(nm(hd)) + '</h2><p class="meta">' + gsum(hd) + '</p><div>' + btn('btn outline sm', 'pauseall', st.gp ? 'Continue all' : 'Pause all') + '</div>' + (st.gp ? '<p class="meta" role="status">All 4 helpers pause after their current step.</p>' : '') + '</div>';
    h += grow(hd, cur, mode, 0);
    mem(g).filter(function (x) { return x.parent === hd.k; }).forEach(function (x) {
      h += grow(x, cur, mode, 1);
      mem(g).filter(function (y) { return y.parent === x.k; }).forEach(function (y) { h += grow(y, cur, mode, 2); });
    });
    if (mode === 'tree') {
      h += '<p class="eyebrow gd-e">Earlier sessions of the main helper</p><span class="gd-rw" data-d="0">' + btn('gd-row', 'ghist', '<span class="gd-t"><span class="chip outline">Earlier</span><strong>Yesterday 16:10 to 16:42</strong></span><span class="gd-s"><span class="meta">Planned the newsletter with you</span></span>', { 'data-k': hd.k }) + '</span>';
      if (by('ORCH-305').s === 'queue') h += '<p class="gd-e">' + btn('btn xs ghost', 'gstop', 'Sample: show “Check the links” stopped') + '</p>';
    }
    return '<nav class="gd-tree" data-mode="' + mode + '" aria-label="Helpers of ' + esc(nm(hd)) + '">' + h + '</nav>';
  }
  /* wall: the whole group is ONE tile, with a small tree preview; its children get no tiles of their own */
  function gtile(s) {
    var v = es(s);
    return '<article class="mw-tile mw-work gd-tile" data-tile="' + esc(s.k) + '" data-s="' + v + '">' + openB(s, 'mw-topen', '<span class="mw-thead">' + stat({ s: v }) + '<span class="mw-key">Epic · ' + esc(s.k) + '</span></span><span class="mw-tt">' + esc(nm(s)) + '</span><span class="mw-now">' + gsum(s) + '</span>' + gtree(s.g, '', 'mini')) + meta(s) + '<footer class="mw-tfoot">' + steps(s) + tileActs(s) + '</footer></article>';
  }
  function gstrip(x) {
    return '<section class="mw-q gd-strip" role="group" aria-label="Question from ' + esc(nm(x)) + '"><div class="gd-qw"><p class="meta">Needs you · “' + esc(nm(x)) + '” asked you at ' + esc(x.q.at || '') + '</p><p class="mw-qt">' + esc(x.q.t) + '</p></div><div class="mw-ans">' + x.q.a.map(function (a, i) { return btn('btn ' + (i ? 'outline' : 'primary'), 'answer', esc(a), { 'data-k': x.k, 'data-a': i }); }).join('') + '</div></section>';
  }
  /* zoom: the tree on the left, the selected session on the right; an open question of another helper is a strip on top */
  function gzoomHTML(s) {
    var hd = ghead(s.g), need = gneed(s.g).filter(function (x) { return x.q && x.k !== s.k; });
    var tools = histBtn(s) + paneTools(s) + '<span class="mw-view">' + btn('btn icon sm ghost', 'full', I.full, { 'aria-label': 'Full screen' }) + '</span>';
    return '<div class="mw-zoom gd-zoom"><h1 class="sr-only">Focus: ' + esc(nm(hd)) + ', ' + esc(gname(s)) + '</h1>' + need.map(gstrip).join('') + '<div class="gd-cols">' + gtree(s.g, s.k, phone() ? 'strip' : 'tree') + pane(s.k, 'lg', { main: true, prim: true, pre: btn('btn sm ghost', 'back', I.back + '<span>Wall</span>'), tools: tools, noshelf: !(s.files && s.files.length) }) + '</div></div>';
  }
  function gto(s) { return s.g && s.kind !== 'small' ? '<p class="meta gd-to">Message to: <b>' + esc(nm(s)) + '</b>' + (s.role === 'main' ? ', the main helper.' : '. Only this helper gets it.') + '</p>' : ''; }
  function watchHTML(s) {
    return '<div class="mw-chat" data-chat="' + esc(s.k) + '" role="log" aria-label="Messages">' + chatMsgs(s) + '</div><div class="gd-watch"><p><b>Watch only.</b> A small helper works inside the session of “' + esc(nm(by(s.parent))) + '” and reports to that helper. It cannot be messaged, stopped or asked on its own.</p>' + btn('btn outline sm', 'gsel', 'Go to its helper', { 'data-k': s.parent }) + '</div>';
  }
  function stopHTML(s) {
    return '<div class="mw-q gd-stop" role="group" aria-label="This helper stopped"><p class="mw-qt">Stopped: could not open the picture folder</p><p class="meta">Nothing is lost. It goes on from where it stopped.</p><div class="mw-ans">' + btn('btn primary', 'retry', 'Try again', { 'data-k': s.k }) + '</div></div>';
  }
  function gstop(on) {
    var s = by('ORCH-305');
    if (on) { s.s = 'stop'; s.step = [1, 3]; s.now = 'Stopped: could not open the picture folder.'; s.lines = ['⏺ Open every link in the mail page', '  ⎿ 4 of 6 links open', '⏺ Open the picture folder', '  ⎿ Could not open it', '  Stopped 10:41']; s.chat.push(['e', 'Started', '10:39'], ['h', 'I stopped: I could not open the picture folder.', '10:41']); }
    else { s.s = 'run'; s.up = 0; s.now = 'Opens every link in the mail page.'; s.feed = ['⏺ Open the picture folder', '  ⎿ 12 pictures', '⏺ Checking the last two links.']; s.chat.push(['y', 'Try again', 'now'], ['h', 'Trying again. The picture folder opens now.', 'now']); }
  }
  function gsel(k) {
    st.ask = false; st.ren = '';
    if (!zoomed() && st.panes.indexOf(k) < 0) st.panes[st.act] = k;
    st.cur = k;
    render('[data-act=gsel][data-k="' + k + '"]');
  }
"""

CLICKS = r"""    if (a === 'gsel') { gsel(k); return; }
    if (a === 'ghist') { st.cur = k; st.ask = true; render('.mw-old button'); return; }
    if (a === 'pauseall') { st.gp = !st.gp; render('[data-act=pauseall]'); say(st.gp ? 'All 4 helpers pause after their current step.' : 'All helpers work again.'); return; }
    if (a === 'gstop') { gstop(true); render('[data-act=gsel][data-k="ORCH-305"]'); say('Check the links stopped.'); return; }
    if (a === 'retry') { gstop(false); render('[data-act=gsel][data-k="ORCH-305"]'); say('Trying again.'); return; }
"""

# ---------- changes to the copy of draft D ----------
rep("IMG = '../../../../workspace/", "IMG = '../../../../../workspace/")
rep("var KEY = 'orch-focus-v4d-picks'", "var KEY = 'orch-focus-344-picks'")
rep(
    "var HIST = [['Yesterday 16:40', 'step 2 of 4', 'Made the sketch, then stopped']",
    "var HIST = [['Yesterday 16:10 to 16:42', 'step 1 of 4', 'Planned the newsletter with you, then stopped until you said go']",
)
rep(
    "  var S0 = JSON.stringify(S), EXTRA = null;",
    DATA.strip("\n") + "\n  var S0 = JSON.stringify(S), EXTRA = null;",
)
rep("none: ['○', 'No session'],", "none: ['○', 'No session'], stop: ['×', 'Stopped'],")
rep("var ORDER = { wait: 0,", "var ORDER = { stop: 0, wait: 0,")
rep("cur: 'ORCH-238', term: false", "cur: 'ORCH-301', term: false")
rep("panes: ['ORCH-238']", "panes: ['ORCH-301']")
rep("tk: 'ORCH-238' };", "tk: 'ORCH-301', gp: false };")
rep("  function live(s) {", HELPERS.strip("\n") + "\n  function live(s) {")
rep(
    "return s.kind !== 'shell' && live(s); }).length; }",
    "return s.kind !== 'shell' && s.kind !== 'small' && live(s); }).length; }",
)
rep(
    "var w = (b.s === 'wait' ? 1 : 0) - (a.s === 'wait' ? 1 : 0);",
    "var w = (es(b) === 'wait' ? 1 : 0) - (es(a) === 'wait' ? 1 : 0);",
)
rep("function word(s) { return ", "function word(s) { if (s.waits) return 'Waits for others'; return ")
rep(
    "function shownIn(o) { return isOpen() && (zoomed() || phone() ? o.k === st.cur : st.panes.indexOf(o.k) >= 0); }",
    "function shownIn(o) { return isOpen() && (o.role === 'main' ? mem(o.g) : [o]).some(function (x) { return zoomed() || phone() ? x.k === st.cur : st.panes.indexOf(x.k) >= 0; }); }",
)
rep("function inChip(o) { return o.s === 'wait' ||", "function inChip(o) { return es(o) === 'wait' ||")
rep("function inList(o, l) { var w = o.s === 'wait';", "function inList(o, l) { var w = es(o) === 'wait';")
# bar: a group is one chip with a count; a child that needs you lifts it into Needs you and the chip opens that child
cut(
    "  function chip(o) {",
    "  function cnt(l, compact) {",
    r"""  function chip(o) {
    var on = shownIn(o), g = o.role === 'main', v = g ? es(o) : o.s, n = g ? gneed(o.g) : [], k = n.length ? n[0].k : o.k;
    return btn('mw-swb', 'switch', stat(g ? { s: v } : o, true) + '<span class="mw-cn">' + esc(g ? nm(o) : (o.name || o.k)) + '</span>' + (g ? '<span class="gd-n" aria-label="' + ghelpers(o.g) + ' helpers">' + ghelpers(o.g) + '</span>' : ''), { 'data-k': k, 'data-s': v, 'aria-pressed': String(on), title: g ? nm(o) + ' · ' + gsum(o) : nm(o) });
  }
""",
)
rep(
    "var n = sorted().filter(function (o) { return inList(o, l); }).length; if (!n) return '';",
    "var n = tops().filter(function (o) { return inList(o, l); }).length; if (!n) return '';",
)
rep(
    "var all = sorted(), need = all.filter(function (o) { return o.s === 'wait'; })",
    "var all = tops(), need = all.filter(function (o) { return es(o) === 'wait'; })",
)
rep(
    "open = all.filter(function (o) { return shownIn(o) && o.s !== 'wait' && !o.pin; });",
    "open = all.filter(function (o) { return shownIn(o) && es(o) !== 'wait' && !o.pin; });",
)
rep(
    "l = sorted().filter(function (o) { return inList(o, st.list) &&",
    "l = tops().filter(function (o) { return inList(o, st.list) &&",
)
rep(
    "var n = sorted().filter(function (o) { return inList(o, st.list); }).length;",
    "var n = tops().filter(function (o) { return inList(o, st.list); }).length;",
)
# wall: only the group tile, found by the filter through its children too
rep(
    "all = sorted().filter(function (s) { return !f || (s.k + ' ' + nm(s) + ' ' + word(s)).toLowerCase().indexOf(f) >= 0; });",
    "all = tops().filter(function (s) { return !f || gtext(s).toLowerCase().indexOf(f) >= 0; });",
)
rep(
    "var act = rest.filter(function (s) { return s.s === 'wait' || grp(s) === 'run'; }), inl = rest.filter(function (s) { return s.s !== 'wait' && grp(s) === 'queue'; }), idle = rest.filter(function (s) { return s.s !== 'wait' && grp(s) === 'idle'; });",
    "var act = rest.filter(function (s) { return es(s) === 'wait' || grp(s) === 'run'; }), inl = rest.filter(function (s) { return es(s) !== 'wait' && grp(s) === 'queue'; }), idle = rest.filter(function (s) { return es(s) !== 'wait' && grp(s) === 'idle'; });",
)
rep("  function tile(s) {\n", "  function tile(s) {\n    if (s.role === 'main') return gtile(s);\n")
rep(
    "  function zoomHTML() {\n    var s = by(st.cur);\n",
    "  function zoomHTML() {\n    var s = by(st.cur);\n    if (s.g) return gzoomHTML(s);\n",
)
rep("  function back() {\n", "  function back() {\n    if (by(st.cur).g) st.cur = ghead(by(st.cur).g).k;\n")
# pane: every answer of a question, waits-for, stopped, the switcher in the layer, watch only, who gets the message
rep(
    "btn('btn ' + (quiet ? 'outline' : 'primary'), 'answer', esc(s.q.a[0]), { 'data-k': s.k, 'data-a': 0 }) + btn('btn outline', 'answer', esc(s.q.a[1]), { 'data-k': s.k, 'data-a': 1 })",
    "s.q.a.map(function (x, i) { return btn('btn ' + (i || quiet ? 'outline' : 'primary'), 'answer', esc(x), { 'data-k': s.k, 'data-a': i }); }).join('')",
)
rep(
    "else if (s.s === 'queue') h += '<div class=\"mw-start\"><h2>In line</h2><p class=\"meta\">All '",
    "else if (s.waits) h += '<div class=\"mw-start\"><h2>Waits for: ' + esc(s.waits) + '</h2><p class=\"meta\">Starts by itself when both are finished.</p></div>';\n    else if (s.s === 'queue') h += '<div class=\"mw-start\"><h2>In line</h2><p class=\"meta\">Waiting for a free place. All '",
)
rep(
    "'<div class=\"mw-pmain\">';\n    if (asking) h += startHTML(s, o.mk);",
    "(o.gsw && s.g ? '<div class=\"gd-swrap\"' + (o.narrow || phone() || eff() === 'right' ? ' data-strip=\"1\"' : '') + '>' + gtree(s.g, s.k, o.narrow || phone() || eff() === 'right' ? 'strip' : 'sw') : '') + '<div class=\"mw-pmain\">';\n    if (s.s === 'stop') h += stopHTML(s);\n    if (asking) h += startHTML(s, o.mk);",
)
rep(
    "h += '</div>' + (size === 'sm' || o.noshelf ? '' : shelf(s, o.mk)) + '</div></section>';",
    "h += '</div>' + (o.gsw && s.g ? '</div>' : '') + (size === 'sm' || o.noshelf || (s.g && !(s.files || []).length) ? '' : shelf(s, o.mk)) + '</div></section>';",
)
rep("prim: on, quiet: !on });", "prim: on, quiet: !on, gsw: on });")
rep(
    "  function chatHTML(s, prim, withMk) {\n",
    "  function chatHTML(s, prim, withMk) {\n    if (s.kind === 'small') return watchHTML(s);\n",
)
rep(
    'chatMsgs(s) + \'</div><form class="mw-comp"',
    "chatMsgs(s) + '</div>' + gto(s) + '<form class=\"mw-comp\"",
)
rep(
    '<span class="meta">Terminal · click and type · select text to copy it</span>\'',
    "<span class=\"meta\">' + (s.kind === 'small' ? 'Terminal · watch only' : 'Terminal · click and type · select text to copy it') + '</span>'",
)
rep(
    "function histBtn(s) { return s.kind !== 'shell' ?",
    "function histBtn(s) { return s.kind !== 'shell' && s.kind !== 'small' ?",
)
rep(
    "    s.feed = ['⏺ Bash(node --test tests/attach.test.js)',",
    "    s.feed = s.g ? ['⏺ Adding the header picture.', '  ⎿ Header in place', '⏺ Checking the page on a phone screen.'] : ['⏺ Bash(node --test tests/attach.test.js)',",
)
rep("    if (a === 'zoom') zoom(k);\n", CLICKS + "    if (a === 'zoom') zoom(k);\n")
rep(
    "    document.body.dataset.mwBoot = '1';",
    "    if (q.get('stopped') === '1') gstop(true);\n    if (q.get('pauseall') === '1') st.gp = true;\n    document.body.dataset.mwBoot = '1';",
)
src = src.replace(
    "/* Focus draft D (ORCH-251)",
    "/* GENERATED by groups/build_d.py from ../focus-v4d.js: do not edit, change build_d.py. */\n/* Focus draft D (ORCH-251)",
    1,
)

# ---------- the page: draft D's page, one folder deeper, plus one layout block on tokens ----------
CSS = """
/* Draft 344 on draft D: layout for the group only. Tokens only, no colours of its own. Listed in NOTES.md. */
body.mk-focus-v4d .gd-tile{grid-column:span 2}
.gd-tree{display:flex;flex-direction:column;gap:var(--s1);min-width:0}
.gd-rw{display:flex;align-items:center;gap:var(--s1);min-width:0}
.gd-rw[data-d="1"],.gd-rw[data-d="2"]{margin-left:var(--s3);padding-left:var(--s2);border-left:1px solid var(--border-strong)}
.gd-rw[data-d="2"]{padding-left:var(--s5)}
.gd-row{flex:1;display:grid;gap:var(--s1);min-width:0;padding:var(--s2);border:0;border-radius:var(--r1);background:transparent;color:var(--text-muted);font:inherit;text-align:left}
button.gd-row:hover{background:var(--surface-2)}
.gd-row[aria-current=true]{background:var(--surface-2);color:var(--text);box-shadow:inset 2px 0 0 var(--brand)}
.gd-t{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap;min-width:0;color:var(--text)}
.gd-s{display:flex;align-items:center;gap:var(--s2);min-width:0}
.gd-e{margin:var(--s3) var(--s2) 0}
.gd-th{display:grid;gap:var(--s2);padding:var(--s2);margin-bottom:var(--s2);border-bottom:1px solid var(--border)}
.gd-tree:not([data-mode=tree]) .gd-row{display:flex;align-items:center;gap:var(--s2);padding:var(--s1) var(--s2);font-size:var(--fs-meta)}
.gd-tree:not([data-mode=tree]) .gd-t{flex-wrap:nowrap;white-space:nowrap}
.gd-tree:not([data-mode=tree]) .gd-t strong{font-weight:500;overflow:hidden;text-overflow:ellipsis}
.gd-tree[data-mode=mini]{gap:0;margin-top:var(--s1);padding:var(--s2);border-radius:var(--r1);background:var(--sidebar)}
.gd-tree[data-mode=tree]{align-self:stretch;padding:var(--s3);border:1px solid var(--border);border-radius:var(--radius-card);background:var(--sidebar);overflow:auto}
.gd-tree[data-mode=strip]{flex:none;flex-direction:row;gap:var(--s2);padding:var(--s2);overflow-x:auto;border-bottom:1px solid var(--border)}
.gd-tree[data-mode=strip] .gd-rw{flex:none;margin:0;padding:0;border:0}
.gd-tree[data-mode=strip] .gd-row{min-height:var(--touch);border:1px solid var(--border)}
.gd-tree[data-mode=strip] .gd-row[aria-current=true]{border-color:var(--brand);box-shadow:none}
body.mk-focus-v4d .gd-zoom{display:flex;flex-direction:column}
.gd-cols{flex:1;display:grid;grid-template-columns:calc(var(--panel-width) + var(--s7)) minmax(0,1fr);gap:var(--s3);min-height:0}
body.mk-focus-v4d .gd-strip{display:flex;align-items:center;flex-wrap:wrap;gap:var(--s2) var(--s4)}
.gd-qw{flex:1 1 calc(var(--s9)*4);display:grid;gap:var(--s1)}
body.mk-focus-v4d .gd-stop{border-color:var(--failed);background:var(--danger-soft)}
body.mk-focus-v4d .mw-st[data-s=stop]{color:var(--failed)}
.gd-n{padding:0 var(--s1);border-radius:var(--r1);background:var(--surface-3);color:var(--text)}
.gd-to{margin:0}
.gd-watch{display:flex;align-items:center;flex-wrap:wrap;gap:var(--s3);padding:var(--s3);border:1px dashed var(--border-strong);border-radius:var(--r1)}
.gd-watch p{flex:1 1 calc(var(--s9)*4);margin:0}
.gd-swrap{flex:1 1 0;display:grid;grid-template-columns:var(--panel-width) minmax(0,1fr);min-height:0;min-width:0}
.gd-swrap>.gd-tree[data-mode=sw]{padding:var(--s2);border-right:1px solid var(--border);background:var(--sidebar);overflow:auto}
.gd-swrap[data-strip]{display:flex;flex-direction:column}
.gd-swrap>.mw-pmain{flex:1 1 0}
.gd-links{display:flex;gap:var(--s1);align-items:center}
@media(max-width:900px){.gd-cols{grid-template-columns:minmax(0,1fr)}}
@media(max-width:720px){body.mk-focus-v4d .gd-tile{grid-column:auto}.gd-cols>.gd-tree[data-mode=strip]{border:0;padding:0}}
"""
for name in (
    "home",
    "board",
    "review",
    "chat",
    "automation",
    "focus",
    "insights",
    "sync",
    "publish",
    "relay",
    "settings",
):
    page = page.replace(f'href="../{name}/', f'href="../../{name}/')
page = rep('="../../../../workspace/', '="../../../../../workspace/', page)
page = rep(
    '<script src="agents/tools.js"></script><script src="focus-v4d.js"></script>',
    '<script src="../agents/tools.js"></script><script src="a-on-d.js"></script>',
    page,
)
page = rep(
    "<title>Focus draft D · orch</title>",
    "<title>An Epic in the new Focus · draft A on draft D · orch</title>",
    page,
)
page = rep("</head>", "<style>" + CSS + "</style></head>", page)
page = rep(
    '<span class="pill">Draft D · demo data</span>',
    '<span class="pill">Draft A on draft D · sample data</span>',
    page,
)
page = rep(
    '<div class="topbar-actions"><button class="btn outline sm" type="button" id="mw-fbtn"',
    '<div class="topbar-actions"><a class="btn ghost sm" href="../focus-v4d.html">Focus without groups</a><button class="btn outline sm" type="button" id="mw-fbtn" hidden',
    page,
)

if bad:
    raise SystemExit("NOT WRITTEN. Draft D changed here, adapt build_d.py:\n  " + "\n  ".join(bad))
(HERE / "a-on-d.js").write_text(src)
(HERE / "a-on-d.html").write_text(page)
print("wrote a-on-d.html, a-on-d.js")

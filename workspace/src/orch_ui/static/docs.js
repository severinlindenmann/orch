/* The Documentation page (owner pick ORCH-735, draft A4): UI.docs(root, data, opts) draws the overview or one page.
   data = orch.docs.collect + live ({actors, groups, pages, live: {read, version, rows: {key: {label, value, tone, note}}}}).
   opts.at = '' (overview), 'g-<group>' (overview at that group) or a page id; opts.link(x) = the address of x
   ('' = the overview; default '#docs/<x>'); opts.settings = where an off add-on is turned on; opts.sel = a tile to
   preselect. The host draws it again on every change of address. Returns {destroy}. Looks: docs.css.
   The overview is a still picture of three layers with straight lines between them for what works together; a page
   has the page list at the left, its flow as lanes in one fixed order (You, orch, Helper, Outside, Server), then
   "Under the hood": live facts, the commands and where it lives. A states page is a state diagram with the main
   path big; a compare page starts with a comparison row and then shows each flow as a compact swimlane strip. */
(function () {
  'use strict';
  let railPick = null;  // the person's own choice for the page list (names or icons), kept while the page is open
  function docs(host, D, opts) {
  opts = opts || {};
  const LIVE = D.live || { rows: {} };
  const at = String(opts.at || '');
  const L = x => (opts.link ? opts.link(x) : (x ? '#docs/' + encodeURIComponent(x) : '#docs'));
  // the dashboard forbids style attributes (style-src 'self'): positions go in data-st and are set through CSSOM
  const st = el => el.querySelectorAll('[data-st]').forEach(n => { n.style.cssText = n.dataset.st; n.removeAttribute('data-st'); });
  host.classList.add('ui-docs');
  const root = document.createElement('div');  // the overview or the page; the bar stays above it
  root.className = 'docs-body';
  const BY = Object.fromEntries(D.pages.map(p => [p.id, p]));
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const f = n => Math.round(n * 10) / 10;

  /* ---------- look-only tables (no facts about how orch works) ---------- */
  const OFF = Object.fromEntries(D.pages.filter(p => p.on === false).map(p => [p.id, true]));  // an add-on that is off here
  const START = 'new-ticket';            // the one highlighted entry on the overview
  const ORDER = ['you', 'orch', 'helper', 'other', 'server'];   // the lanes, always in this order
  const LAYERS = ['builtin', 'orch', 'addon'];                  // the overview's layers, top to bottom
  // the few connections between two layers that get a line on the overview (each must be in the data's related ids)
  const PORTS = [['relay-phone', 'chat'], ['relay-shared', 'safety'], ['publish-links', 'safety'],
    ['review', 'pull-requests'], ['by-itself', 'automation'], ['addons-plug', 'dashboard']];
  const LAYER_NOTE = 'you and the outside: your phone, other workspaces, services';
  const SETTINGS = opts.settings || '#settings/addons';
  // State diagrams: the main path (big, one row) and where each side state hangs.
  const STATE_MAIN = {
    'ticket-life': { main: ['backlog', 'ready', 'working', 'review', 'done'], side: { dropped: 'backlog', waiting: 'working' } }
  };
  // The same diagram on a narrow screen: places (column, row), numbered arrows and a list below.
  const STATE_GRID = {
    'ticket-life': { dropped: [0, 0], backlog: [0, 1], waiting: [0, 2], ready: [1, 1], working: [1, 2], review: [1, 3], done: [1, 4] }
  };
  // One short line per compared flow, for the comparison row.
  const CMP_NOTE = { 'relay-w2w': ['Information only', 'Information only', 'Runs only after their Allow'] };
  const ACTOR_ICON = { you: 'user', orch: 'braces', helper: 'spark', other: 'external', server: 'server' };
  const GROUP_ICON = { orch: 'orch', builtin: 'switch', addon: 'puzzle' };
  const TONE = { muted: '', info: 'info', working: 'working', warn: 'needs', needs: 'needs', ok: 'done' };

  /* ---------- icons: the master set first, a few local paths for names it does not have ---------- */
  const ALIAS = { helper: 'spark', lock: 'shield', upload: 'up', merge: 'pull', box: 'archive' };
  const LOCAL = {
    question: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1 1-1.1 1.8M12 17h.01"/>',
    chip: '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    queue: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    chat: '<path d="M4 4h16v12H9l-5 4z"/><path d="M8 8h8m-8 4h5"/>',
    puzzle: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    bolt: '<path d="m13 2-8 12h6l-1 8 9-13h-7z"/>',
    home: '<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    server: '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    switch: '<rect x="2" y="7" width="20" height="10" rx="5"/><circle cx="16" cy="12" r="2.5"/>',
    orch: '<path d="M19 10a8 8 0 1 1-5-6"/><circle cx="11" cy="12" r="3"/><circle cx="19" cy="5" r="1.5"/>',
    arrow: '<path d="M4 12h15M13 6l6 6-6 6"/>',
    back: '<path d="M9 7 4 12l5 5M4 12h11a5 5 0 0 1 5 5v1"/>',
    book: '<path d="M12 6c-2-1.5-5-2-8-2v14c3 0 6 .5 8 2 2-1.5 5-2 8-2V4c-3 0-6 .5-8 2zM12 6v14"/>',
    prev: '<path d="m14 6-6 6 6 6"/>',
    next: '<path d="m10 6 6 6-6 6"/>'
  };
  function ic(name, size) {
    size = size || 16;
    const n = ALIAS[name] || name;
    if (LOCAL[n] || !window.icon) {
      return '<svg class="ic" width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (LOCAL[n] || '') + '</svg>';
    }
    return window.icon(n, size);
  }
  // a tile shows the page's own title; "Relay: your phone" sits under a Relay label, so it reads "Your phone"
  const short = p => { const s = p.title.indexOf(': ') > 0 ? p.title.split(': ')[1] : p.title; return s.charAt(0).toUpperCase() + s.slice(1); };
  const groupOf = id => D.groups.find(g => g.id === id);
  const narrow = () => window.matchMedia('(max-width: 1099px)').matches;
  const actorsOf = steps => steps.map(s => s.who).filter((a, i, all) => all.indexOf(a) === i);

  /* ---------- routing ---------- */
  function current() { return BY[at] ? at : ''; }
  let cleanup = [];
  function render() {
    cleanup.forEach(fn => fn()); cleanup = [];
    const p = BY[current()];
    navBar(p);
    if (!p) overview(); else page(p);
    const gsec = !p && at.indexOf('g-') === 0 ? root.querySelector('[data-group="' + at.slice(2) + '"]') : null;
    if (gsec) gsec.scrollIntoView({ block: 'start' });
  }
  function watch(el, fn) {
    if (!window.ResizeObserver) { fn(); return; }
    let w = -1;
    const ro = new ResizeObserver(() => { const n = el.clientWidth; if (n !== w) { w = n; fn(); } });
    ro.observe(el); cleanup.push(() => ro.disconnect());
  }
  // who takes part, explained once per page
  function legend(actors) {
    actors = ORDER.filter(a => actors.indexOf(a) >= 0);
    return '<p class="dp-legend"><span class="sr-only">Who does a step: </span>' + actors.map(a => {
      const A = D.actors[a];
      return '<span class="dp-lg a-' + a + '"><span class="dp-lg-ic">' + ic(ACTOR_ICON[a], 14) + '</span><strong>' + esc(A.label) + '</strong>' +
        (A.note ? '<span class="dp-lg-note">' + esc(A.note) + '</span>' : '') + '</span>';
    }).join('') + '</p>';
  }

  /* ---------- the way back: one bar that stays on top of every page ----------
     the title (= the overview), the three groups as tabs, a picker with the pages of the group, and
     previous / next. Every move is a hash change, so the browser's Back button walks the same way back. */
  const bar = document.createElement('div');
  bar.className = 'dn';
  host.replaceChildren(bar, root);
  function navBar(p) {
    const title = '<a href="' + L('') + '"' + (p ? '' : ' aria-current="page"') + '>' + ic('book', 16) + '<span>Documentation</span></a>';
    bar.innerHTML = (p ? '<p class="dn-title">' + title + '</p>' : '<h1 class="dn-title">' + title + '</h1>') +
      '<nav class="tabs dn-tabs" aria-label="Groups">' + D.groups.map(g =>
        '<a href="' + L('g-' + g.id) + '"' + ((p && p.group === g.id) || (!p && at === 'g-' + g.id) ? ' aria-current="page"' : '') + '>' + ic(GROUP_ICON[g.id], 14) + esc(g.label) + '</a>').join('') + '</nav>';
    const cur = bar.querySelector('.dn-tabs [aria-current]');
    if (cur) cur.parentNode.scrollLeft = Math.max(0, cur.offsetLeft - cur.parentNode.offsetLeft - 16);
  }

  /* ---------- live: what this workspace shows right now (the host reads it when the page opens; no AI) ---------- */
  // a row: {label, value, tone ('done' = on and working, 'off', or ''), note}; "self" is the add-on's own state
  const selfRow = p => (p.addon ? {
    label: 'This add-on',
    value: p.on === false ? 'Off' : p.background ? (p.running ? 'Running' : 'Not running') : 'On',
    tone: p.on === false ? 'off' : (p.running || !p.background) ? 'done' : ''
  } : null);
  const rowOf = (k, p) => (k === 'self' ? selfRow(p) : (LIVE.rows || {})[k] || null);
  const liveVal = (r, short) => '<span class="dh-val' + (r.tone ? ' t-' + r.tone : '') + '">' + (r.tone === 'done' ? '<span class="dh-dot" aria-hidden="true"></span>' : '') + esc(short || r.value) + '</span>';
  // the one live word a tile of a part you turn on shows on the overview: relay and publish
  const tileLive = p => {
    if (p.group !== 'builtin') return '';
    if (OFF[p.id]) return '<span class="dl-live">' + liveVal({ value: 'Off', tone: 'off' }) + '</span>';  // under the name: these tiles are narrow
    const k = ((p.tech || {}).live || []).find(x => x === 'relay' || x === 'publish'), r = k && rowOf(k, p);
    return r ? '<span class="dl-live">' + liveVal(r, r.short) + '</span>' : '';
  };
  // the strip under the overview; each fact links to the page that explains it (when that page is here)
  const STRIP = [['relay', 'relay-w2w'], ['publish', 'publish-links'], ['helper-limit', 'line'], ['reviewer', 'review'], ['addons', 'addons-plug']];
  function liveStrip() {
    const items = STRIP.filter(x => rowOf(x[0])).map(x => {
      const r = rowOf(x[0]), inner = '<span class="dlv-k">' + esc(r.label) + '</span>' + liveVal(r);
      return BY[x[1]] ? '<a class="dlv-it" href="' + L(x[1]) + '">' + inner + '</a>' : '<span class="dlv-it">' + inner + '</span>';
    });
    if (!items.length) return '';
    return '<section class="dlv" aria-label="This workspace now"><p class="dlv-head"><span class="eyebrow">This workspace now</span><span class="dm-note">' +
      esc([LIVE.version, LIVE.read ? 'read ' + LIVE.read : ''].filter(Boolean).join(' · ')) + '</span></p><div class="dlv-row">' + items.join('') + '</div></section>';
  }
  /* "Under the hood": live rows, the commands and the files; one card under the picture */
  function hood(p) {
    const t = p.tech; if (!t) return '';
    const live = (t.live || []).map(k => rowOf(k, p)).filter(Boolean).map(r => '<div class="dh-row"><dt>' + esc(r.label) + '</dt><dd>' + liveVal(r) +
      (r.note ? '<span class="dm-note">' + esc(r.note) + '</span>' : '') + '</dd></div>').join('');
    const cmds = (t.cmds || []).map(c => '<li><code>' + esc(c[0]) + '</code><button type="button" class="btn ghost sm icon dh-copy" aria-label="Copy command: ' + esc(c[0]) + '" title="Copy" data-cmd="' + esc(c[0]) + '">' + ic('copy', 14) + '</button><span class="dm-note">' + esc(c[1]) + '</span></li>').join('');
    const files = (t.files || []).map(c => '<li><code>' + esc(c[0]) + '</code><span class="dm-note">' + esc(c[1]) + '</span></li>').join('');
    if (!live && !cmds && !files) return '';
    return '<section class="card dh" aria-label="Under the hood"><header class="dh-head"><h2>' + ic('code', 16) + 'Under the hood</h2></header><div class="dh-cols">' +
      (live ? '<div class="dh-col"><p class="eyebrow">In this workspace now' + (LIVE.read ? ' <span class="dh-read">read ' + esc(LIVE.read) + '</span>' : '') + '</p><dl class="dh-live">' + live + '</dl></div>' : '') +
      (cmds ? '<div class="dh-col dh-wide"><p class="eyebrow">Commands</p><ul class="dh-cmds">' + cmds + '</ul></div>' : '') +
      (files ? '<div class="dh-col"><p class="eyebrow">Where it lives</p><ul class="dh-cmds dh-files">' + files + '</ul></div>' : '') + '</div></section>';
  }

  /* ---------- the page list: beside the page on a wide screen (folds to icons), behind "Pages" on a phone ---------- */
  function pageList(p) {
    let h = '<div class="sl-top"><details class="sl"><summary class="btn outline sm sl-toggle">' + ic('list', 16) + 'Pages</summary>' +
      '<nav class="sl-list" aria-label="Documentation pages">' +
      '<button class="sl-item sl-fold" type="button" aria-expanded="true">' + ic('list', 16) + '<span class="sl-label">Hide names</span></button>';
    D.groups.forEach(g => {
      h += '<p class="eyebrow sl-group"><span>' + esc(g.label) + '</span></p>' + D.pages.filter(x => x.group === g.id).map(x =>
        '<a class="sl-item' + (OFF[x.id] ? ' is-off' : '') + '" href="' + L(x.id) + '" title="' + esc(x.title) + '" aria-label="' + esc(x.title) + (OFF[x.id] ? ' (off)' : '') + '"' +
        (x.id === p.id ? ' aria-current="page"' : '') + '>' + ic(x.icon, 16) +
        '<span class="sl-label">' + esc(x.title) + '</span>' + (OFF[x.id] ? '<span class="sl-off">Off</span>' : '') + '</a>').join('');
    });
    return h + '</nav></details></div>';
  }

  /* ---------- overview: "Start here" first, then three still layers, top to bottom ----------
     What works together (the pages' related ids, read both ways) is shown in two quiet ways:
     - a few straight lines ("ports") between two layers, each ending on the two tiles it joins
       (wide screens only; its small label shows when you point at it or at one of its tiles);
     - a "Connected" button on a tile: press it and the tile's partners take colour and are listed as
       chips in the "Related topics" row under the layers (on a phone: under the tile). Nothing moves. */
  function overview() {
    const of = g => D.pages.filter(p => p.group === g);
    const layerOf = id => LAYERS.indexOf(BY[id].group);
    const pairs = [], seen = {};
    D.pages.forEach(p => (p.related || []).forEach(r => {
      const k = [p.id, r].sort().join('|');
      if (BY[r] && r !== p.id && !seen[k]) { seen[k] = 1; pairs.push([p.id, r]); }
    }));
    const near = id => pairs.filter(c => c.indexOf(id) >= 0).map(c => (c[0] === id ? c[1] : c[0]));
    // the ports: only connections the data has, the upper layer's tile first
    const ports = PORTS.filter(c => seen[c.slice().sort().join('|')]).map(c => (layerOf(c[0]) < layerOf(c[1]) ? { up: c[0], down: c[1] } : { up: c[1], down: c[0] }));
    // tiles that have a port stand next to the gap it crosses: first in the layer below, last in the layer above
    const rank = p => (ports.some(c => c.down === p.id) ? -1 : ports.some(c => c.up === p.id) ? 1 : 0);
    const portPos = p => { const i = ports.findIndex(c => c.down === p.id || c.up === p.id); return i < 0 ? 0 : i; };
    const ordered = g => of(g).map((p, i) => ({ p: p, i: i })).sort((a, b) => rank(a.p) - rank(b.p) || (rank(a.p) ? portPos(a.p) - portPos(b.p) : 0) || a.i - b.i).map(x => x.p);

    const tile = p => {
      const ns = near(p.id), start = p.id === START;
      return '<div class="dl-tile' + (start ? ' dl-start' : '') + (OFF[p.id] ? ' is-off' : '') + '" data-id="' + p.id + '">' +
        '<a class="dl-link" href="' + L(p.id) + '" title="' + esc(p.title) + '">' +
        (start ? '<span class="dl-start-main"><span class="badge active">Start here</span><strong>' + esc(p.title) + '</strong><span class="dm-note">' + esc(p.one) + '</span></span>'
          : '<span class="dm-ic">' + ic(p.icon, 18) + '</span><span class="dm-label">' + esc(short(p)) + tileLive(p) + '</span>' + (OFF[p.id] && p.group !== 'builtin' ? '<span class="badge dashed">Off</span>' : '')) + '</a>' +
        (ns.length ? '<button type="button" class="dl-conn-b" aria-pressed="false" aria-label="Related topics of ' + esc(p.title) + ': ' + ns.length + '">' +
          ic('link', 12) + 'Related<span class="dl-conn-n">' + ns.length + '</span></button><div class="dl-conn-in" hidden></div>' : '') + '</div>';
    };
    const head = (g, note) => '<div class="dl-head"><span class="dm-gic">' + ic(GROUP_ICON[g.id], 18) + '</span><h2>' + esc(g.label) + '</h2>' +
      '<span class="dm-note">' + esc(note) + '</span></div>';
    // "Relay: your phone" and "Publish: private links" sit under a small Relay / Publish label
    const subs = [];
    of('builtin').forEach(p => {
      const name = p.title.indexOf(':') > 0 ? p.title.split(':')[0] : '';
      let s = subs.find(x => x.name === name);
      if (!s) subs.push(s = { name: name, pages: [] });
      s.pages.push(p);
    });
    const offNote = of('addon').filter(p => OFF[p.id]).map(p => esc(p.title) + ' is off. Turn it on in Settings to use it.').join(' ');
    const go = groupOf('orch'), gb = groupOf('builtin'), ga = groupOf('addon');
    const HINT = '<span class="eyebrow">Related topics</span><span class="dm-note">Press Related on a part to see what it works with.</span>';
    root.innerHTML =
      '<p class="muted dl-lead">How orch works, in pictures. Pick a part.</p>' +
      '<div class="dl-first">' + tile(BY[START]) + '</div>' +
      '<nav class="dl" aria-label="The layers of orch">' +
      '<section class="dl-band dz-builtin" data-group="builtin">' + head(gb, LAYER_NOTE) + '<div class="dl-subs">' + subs.map(s =>
        '<div class="dl-sub" data-st="--n:' + s.pages.length + '">' + (s.name ? '<p class="dm-sub">' + esc(s.name) + '</p>' : '') +
        '<div class="dm-tiles">' + s.pages.map(tile).join('') + '</div></div>').join('') + '</div></section>' +
      '<section class="dl-band dz-orch" data-group="orch">' + head(go, D.actors.orch.note) +
      '<div class="dm-tiles">' + ordered('orch').filter(p => p.id !== START).map(tile).join('') + '</div></section>' +
      '<section class="dl-band dz-addon" data-group="addon">' + head(ga, 'each brings its own page') +
      '<div class="dl-body"><div class="dm-tiles">' + ordered('addon').map(tile).join('') + '</div>' + (offNote ? '<p class="dm-note dm-offnote">' + offNote + '</p>' : '') + '</div></section>' +
      '<svg class="dl-lines" aria-hidden="true"></svg><div class="dl-labs" aria-hidden="true"></div></nav>' +
      '<div class="dl-row" aria-live="polite">' + HINT + '</div>' + liveStrip();
    st(root);

    const map = root.querySelector('.dl'), svg = map.querySelector('.dl-lines'), labs = map.querySelector('.dl-labs'), row = root.querySelector('.dl-row');
    const tileOf = id => root.querySelector('.dl-tile[data-id="' + id + '"]');
    let sel = '', hot = '';
    // colour only: the chosen tile, its partners and their lines
    const paint = () => {
      root.querySelectorAll('.is-sel,.is-near,.is-on').forEach(e => e.classList.remove('is-sel', 'is-near', 'is-on'));
      [sel, hot].filter(Boolean).forEach(id => {
        near(id).forEach(x => { const t = tileOf(x); if (t) t.classList.add('is-near'); });
        map.querySelectorAll('[data-port]').forEach(e => { if (e.dataset.port.split(' ').indexOf(id) >= 0) e.classList.add('is-on'); });
      });
      if (sel) tileOf(sel).classList.add('is-sel');
    };
    const choose = id => {
      sel = sel === id ? '' : id;
      const chips = sel ? near(sel).map(x => '<a class="chip-btn" href="' + L(x) + '">' + ic(BY[x].icon, 14) + esc(BY[x].title) + '</a>').join('') : '';
      root.querySelectorAll('.dl-conn-b').forEach(b => {
        const on = b.parentNode.dataset.id === sel, box = b.parentNode.querySelector('.dl-conn-in');
        b.setAttribute('aria-pressed', String(on));
        box.hidden = !on; box.innerHTML = on ? chips : '';
      });
      row.innerHTML = sel ? '<span class="eyebrow">Related topics</span><strong>' + esc(BY[sel].title) + '</strong><span class="dm-note">works with</span>' + chips : HINT;
      paint();
    };
    root.querySelectorAll('.dl-tile').forEach(t => {
      const b = t.querySelector('.dl-conn-b');
      if (b) b.addEventListener('click', () => choose(t.dataset.id));
      t.addEventListener('mouseenter', () => { hot = t.dataset.id; paint(); });
      t.addEventListener('focusin', () => { hot = t.dataset.id; paint(); });
      t.addEventListener('mouseleave', () => { hot = ''; paint(); });
      t.addEventListener('focusout', () => { hot = ''; paint(); });
    });

    // the ports: straight pieces only, from the lower edge of one tile to the upper edge of the other
    const draw = () => {
      svg.innerHTML = ''; labs.innerHTML = '';
      if (narrow()) return;
      const base = map.getBoundingClientRect();
      const box = id => { const t = tileOf(id); if (!t || !map.contains(t)) return null; const r = t.getBoundingClientRect(); return { l: r.left - base.left, r: r.right - base.left, t: r.top - base.top, b: r.bottom - base.top, band: t.closest('.dl-band') }; };
      const open = (b, low) => !Array.from(b.band.querySelectorAll('.dl-tile')).some(t => {
        const r = t.getBoundingClientRect();
        return low ? r.top - base.top >= b.b - 1 : r.bottom - base.top <= b.t + 1;
      });
      // a port is drawn only when both tiles look onto the gap (nothing between them and it)
      const ok = ports.map(c => ({ c: c, a: box(c.up), b: box(c.down) })).filter(x => x.a && x.b && open(x.a, true) && open(x.b, false));
      let h = '', lh = '';
      LAYERS.slice(0, -1).forEach((g, gi) => {
        const mine = ok.filter(x => layerOf(x.c.up) === gi && layerOf(x.c.down) === gi + 1);
        if (!mine.length) return;
        // lines to the same tile share one level; every other line gets its own
        const keys = [];
        mine.forEach(x => { if (keys.indexOf(x.c.down) < 0) keys.push(x.c.down); });
        const y0 = Math.max.apply(null, mine.map(x => x.a.band.getBoundingClientRect().bottom)) - base.top;
        const y1 = Math.min.apply(null, mine.map(x => x.b.band.getBoundingClientRect().top)) - base.top;
        mine.forEach(x => {
          const lane = keys.indexOf(x.c.down), y = y0 + (y1 - y0) * (lane + 1) / (keys.length + 1);
          const xu = (x.a.l + x.a.r) / 2, xl = (x.b.l + x.b.r) / 2;
          const d = Math.abs(xu - xl) < 8 ? 'M' + f(xu) + ' ' + f(x.a.b) + 'V' + f(x.b.t) : poly([[xu, x.a.b], [xu, y], [xl, y], [xl, x.b.t]], 6);
          const xe = Math.abs(xu - xl) < 8 ? xu : xl;
          const ids = x.c.up + ' ' + x.c.down;
          h += '<g class="dl-line" data-port="' + ids + '"><path class="dl-hit" d="' + d + '"/><path class="dl-wire" d="' + d + '"/>' +
            '<circle cx="' + f(xu) + '" cy="' + f(x.a.b) + '" r="3"/><circle cx="' + f(xe) + '" cy="' + f(x.b.t) + '" r="3"/></g>';
          lh += '<span class="dl-lab" data-port="' + ids + '" data-st="left:' + f((xu + xe) / 2) + 'px;top:' + f(Math.abs(xu - xl) < 8 ? (y0 + y1) / 2 : y) + 'px">' +
            esc(short(BY[x.c.up])) + ' ↕ ' + esc(short(BY[x.c.down])) + '</span>';
        });
      });
      svg.setAttribute('width', base.width); svg.setAttribute('height', base.height);
      svg.innerHTML = h; labs.innerHTML = lh; st(labs);
      svg.querySelectorAll('.dl-line').forEach(g => {
        const lab = labs.querySelector('[data-port="' + g.dataset.port + '"]');
        g.addEventListener('mouseenter', () => { g.classList.add('is-on'); lab.classList.add('is-on'); });
        g.addEventListener('mouseleave', paint);
      });
      paint();
    };
    watch(map, draw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
    // for a picture of the chosen state: index.html?sel=<page id>
    const pre = opts.sel;
    if (pre && tileOf(pre) && tileOf(pre).querySelector('.dl-conn-b')) choose(pre);
  }

  /* ---------- one page ---------- */
  function page(p) {
    const from = p.group === 'addon'
      ? '<span class="dp-from"><span class="addon-tag" aria-hidden="true">' + ic('puzzle', 12) + '</span>From the ' + esc(p.title.split(' and ')[0]) + ' add-on</span>' : '';
    let h = '<header class="page-heading"><div><a class="dp-back" href="' + L('') + '">' + ic('prev', 14) + 'Documentation</a>' + (from || OFF[p.id] ? '<p class="dp-group">' + from + (OFF[p.id] ? '<span class="badge dashed">Off</span>' : '') + '</p>' : '') +
      '<h1>' + esc(p.title) + '</h1><p class="muted dp-one">' + esc(p.one) + '</p>' +
      (OFF[p.id] ? '<p class="dp-offline">Turn it on in <a href="' + SETTINGS + '">Settings</a> to use it.</p>' : '') + '</div></header>';
    h += '<div class="dp-body"' + (OFF[p.id] ? ' class="is-off"' : '') + '></div>';
    h += hood(p);
    if ((p.good || []).length || (p.related || []).length) {
      h += '<div class="dp-foot">';
      if ((p.good || []).length) h += '<section class="card pad dp-good"><p class="eyebrow">Good to know</p><ul>' + p.good.map(t => '<li>' + esc(t) + '</li>').join('') + '</ul></section>';
      const rel = (p.related || []).filter(r => BY[r]);
      if (rel.length) h += '<nav class="dp-rel" aria-label="Related"><span class="eyebrow">Related</span>' +
        rel.map(r => '<a class="chip-btn" href="' + L(r) + '">' + ic(BY[r].icon, 14) + esc(BY[r].title) + '</a>').join('') + '</nav>';
      h += '</div>';
    }
    root.innerHTML = '<div class="sl-wrap">' + pageList(p) + '<div class="sl-main">' + h + '</div></div>';
    st(root);
    const det = root.querySelector('.sl'), mq = window.matchMedia('(max-width: 1099px)');
    const fold = () => { det.open = !mq.matches; };
    fold();
    mq.addEventListener('change', fold); cleanup.push(() => mq.removeEventListener('change', fold));
    const wrap = root.querySelector('.sl-wrap'), foldBtn = det.querySelector('.sl-fold');
    const setRail = on => {
      wrap.classList.toggle('is-rail', on);
      foldBtn.setAttribute('aria-expanded', String(!on));
      foldBtn.querySelector('.sl-label').textContent = on ? 'Show names' : 'Hide names';
      foldBtn.setAttribute('aria-label', on ? 'Show page names' : 'Hide page names');
      foldBtn.title = on ? 'Show page names' : 'Hide page names';
    };
    setRail(railPick !== null ? railPick : false);
    foldBtn.addEventListener('click', () => { railPick = !wrap.classList.contains('is-rail'); setRail(railPick); });
    const list = det.querySelector('.sl-list'), curItem = list.querySelector('[aria-current]');
    if (curItem && list.scrollHeight > list.clientHeight) list.scrollTop = curItem.offsetTop - list.clientHeight / 2;
    // copy through the master (it falls back when the Clipboard API is not there); a tick only when it worked
    root.querySelectorAll('.dh-copy').forEach(b => b.addEventListener('click', async () => {
      const ok = window.UI && window.UI.copyText ? await window.UI.copyText(b.dataset.cmd) : false;
      if (window.UI && window.UI.toast) window.UI.toast(ok ? 'Command copied' : 'Copy is unavailable here. Select the command and copy it.');
      if (ok) { b.classList.add('is-done'); setTimeout(() => b.classList.remove('is-done'), 1200); }
    }));
    const body = root.querySelector('.dp-body');
    let mode = '';
    const draw = () => {
      // w0: too narrow for the big state diagram (its labels would wrap letter by letter), so numbered arrows
      const m = narrow() ? 'n' : body.clientWidth < 1000 ? 'w0' : body.clientWidth < 1300 ? 'w1' : 'w2';
      if (m !== mode) {
        mode = m;
        if (p.kind === 'states') body.innerHTML = statesHtml(p, m);
        else if (p.kind === 'compare') body.innerHTML = compareHtml(p, m);
        else body.innerHTML = '<section class="card">' + legend(actorsOf(p.steps)) + (m === 'n' ? timeline(p.steps) : swim(p.steps, m !== 'w2')) + '</section>';
      }
      st(body);
      body.querySelectorAll('.ds').forEach(arrows);
      body.querySelectorAll('.dst').forEach(el => {
        if (el.classList.contains('dst-wide')) statesWide(el, p, STATE_MAIN[p.id]); else statesNumbered(el, p, m === 'n' || m === 'w0');
      });
    };
    watch(body, draw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
  }

  /* what hangs under a step: its detail, then each branch as a labelled path with its result */
  function under(s) {
    if (!s.detail && !s.branch) return '';
    let h = '<div class="ds-under' + (s.branch ? ' has-b' : '') + '">';
    if (s.detail) h += '<p class="ds-detail">' + esc(s.detail) + '</p>';
    (s.branch || []).forEach(b => {
      // a branch ends the flow only when the data says so (stop: true); every other branch is an outcome
      h += '<div class="df-b"><span class="df-if">' + esc(b.if) + '</span><span class="df-out' + (b.stop ? ' is-stop' : '') + '">' +
        (b.stop ? '<span class="df-stop" aria-hidden="true"></span>' : ic('arrow', 12)) +
        '<span>' + esc(b.then) + '</span>' + (b.stop ? '<span class="sr-only"> (ends here)</span>' : '') + '</span></div>';
    });
    return h + '</div>';
  }

  /* swimlanes: the lanes always come in the same order (You, orch, Helper, Outside, Server).
     A step in the same lane goes one column to the right. A step in another lane goes straight below
     or above the step before it, in the same column, joined by one straight line with a small arrow;
     only when that place is taken it takes the next column. A box never moves back left.
     A long flow with one lane wraps once inside its lane on a smaller screen. */
  function swim(steps, mayWrap, compact) {
    const n = steps.length;
    const lanes = ORDER.filter(a => steps.some(s => s.who === a));
    const cut = mayWrap && lanes.length === 1 && n >= 6 ? Math.ceil(n / 2) : 0;
    const pos = [], used = {};
    let col = 0;
    steps.forEach((s, i) => {
      const li = lanes.indexOf(s.who);
      if (cut) { pos.push({ row: i >= cut ? 2 : 1, col: (i >= cut ? i - cut : i) + 1 }); return; }
      const pl = i ? pos[i - 1].row - 1 : li;
      let same = i > 0 && pl !== li;
      for (let l = Math.min(pl, li); same && l <= Math.max(pl, li); l++) if (l !== pl && used[l + ':' + col]) same = false;
      if (same) for (let l = Math.min(pl, li) + 1; l < Math.max(pl, li); l++) used[l + ':' + col] = 1;   // the line passes these lanes
      else col++;
      used[li + ':' + col] = 1;
      pos.push({ row: li + 1, col: col });
    });
    const ncols = Math.max.apply(null, pos.map(x => x.col));
    // a step with words under it uses the free room to its right in its lane (when the path goes on below or above it)
    const spanOf = i => {
      const s = steps[i], at = pos[i], next = pos[i + 1];
      if (cut || !(s.detail || s.branch) || (next && next.col !== at.col)) return 1;
      let k = 1;
      while (at.col + k <= ncols && !used[(at.row - 1) + ':' + (at.col + k)]) k++;
      return k;
    };
    const wt = s => Math.max(s.branch ? 2 : s.detail ? 1.3 : 1, Math.min(1.5, s.text.length / 30));
    const cols = [];
    for (let c = 1; c <= ncols; c++) cols.push('minmax(0,' + Math.max.apply(null, steps.map((s, i) => (pos[i].col === c ? wt(s) : 0))).toFixed(2) + 'fr)');
    let h = '<div class="ds' + (ncols > 5 ? ' ds-dense' : '') + (compact ? ' ds-compact' : '') + '" data-st="grid-template-columns:var(--lane-w) ' + cols.join(' ') + ' 14px">';
    lanes.forEach((a, li) => {
      const span = 'grid-row:' + (li + 1) + '/' + (li + (cut ? 3 : 2));
      h += '<div class="ds-lane" data-st="' + span + '"></div>' +
        '<div class="ds-who a-' + a + '" data-st="' + span + '"><span class="ds-who-ic">' + ic(ACTOR_ICON[a], 16) + '</span><strong>' + esc(D.actors[a].label) + '</strong></div>';
    });
    steps.forEach((s, i) => {
      const at = pos[i], prev = pos[i - 1], next = pos[i + 1];
      // a straight line leaves or reaches the bottom of this box: keep the space under its left edge free
      const chan = (next && next.col === at.col && next.row > at.row) || (prev && prev.col === at.col && prev.row > at.row);
      const sp = spanOf(i);
      h += '<div class="ds-cell a-' + s.who + (chan ? ' has-chan' : '') + (sp > 1 ? ' is-span' : '') + '" data-st="grid-row:' + at.row + ';grid-column:' + (at.col + 1) + '/span ' + sp + '">' +
        '<div class="ds-box' + (s.decision ? ' is-decision' : '') + (s.end ? ' is-end' : '') + '" data-c="' + at.col + '" data-r="' + at.row + '">' +
        '<span class="ds-head"><span class="ds-num">' + (i + 1) + '</span>' + ic(s.decision ? 'question' : ACTOR_ICON[s.who], 12) +
        '<span class="sr-only"> ' + esc(D.actors[s.who].label) + (s.decision ? ', a decision' : '') + ': </span>' +
        (s.proposed ? '<span class="badge active ds-new">New</span>' : '') + '</span>' +
        '<span class="ds-text">' + esc(s.text) + '</span></div>' + under(s) + '</div>';
    });
    return h + '<svg class="ds-arrows" aria-hidden="true"></svg></div>';
  }
  // a path of straight pieces with soft corners
  function poly(pts, r) {
    let d = 'M' + f(pts[0][0]) + ' ' + f(pts[0][1]);
    for (let i = 1; i < pts.length - 1; i++) {
      const p0 = pts[i - 1], p1 = pts[i], p2 = pts[i + 1];
      const l1 = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), l2 = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
      const rr = Math.min(r, l1 / 2, l2 / 2);
      if (rr < 1) { d += 'L' + f(p1[0]) + ' ' + f(p1[1]); continue; }
      d += 'L' + f(p1[0] - (p1[0] - p0[0]) / l1 * rr) + ' ' + f(p1[1] - (p1[1] - p0[1]) / l1 * rr) +
        'Q' + f(p1[0]) + ' ' + f(p1[1]) + ' ' + f(p1[0] + (p2[0] - p1[0]) / l2 * rr) + ' ' + f(p1[1] + (p2[1] - p1[1]) / l2 * rr);
    }
    const e = pts[pts.length - 1];
    return d + 'L' + f(e[0]) + ' ' + f(e[1]);
  }
  function arrows(ds) {
    const svg = ds.querySelector('.ds-arrows');
    const base = ds.getBoundingClientRect();
    const boxes = Array.from(ds.querySelectorAll('.ds-box')).map(b => {
      const r = b.getBoundingClientRect();
      return { l: r.left - base.left, r: r.right - base.left, t: r.top - base.top, b: r.bottom - base.top, c: b.dataset.c, row: +b.dataset.r,
        end: b.classList.contains('is-end'), dec: b.classList.contains('is-decision') };
    });
    let d = '', heads = '', dots = '';
    const ya = o => (o.dec ? (o.t + o.b) / 2 : o.t + Math.min(22, (o.b - o.t) / 2));
    for (let i = 0; i < boxes.length; i++) {
      const a = boxes[i], b = boxes[i + 1], y1 = ya(a);
      if (!b) {
        if (a.end) { d += 'M' + f(a.r) + ' ' + f(y1) + 'h8'; dots += '<circle class="ds-stop" cx="' + f(a.r + 13) + '" cy="' + f(y1) + '" r="5"/>'; }
        continue;
      }
      const y2 = ya(b);
      if (a.c === b.c && a.row !== b.row && Math.abs(a.l - b.l) < 2) {   // another lane, same column: one straight line
        const x = a.l + 22;
        if (b.t > a.b) { d += 'M' + f(x) + ' ' + f(a.b) + 'V' + f(b.t - 8); heads += 'M' + f(x) + ' ' + f(b.t - 1) + 'l-4.5 -8h9z'; }
        else { d += 'M' + f(x) + ' ' + f(a.t) + 'V' + f(b.b + 8); heads += 'M' + f(x) + ' ' + f(b.b + 1) + 'l-4.5 8h9z'; }
      } else if (b.l > a.r) {
        const x2 = b.l - 2, mx = (a.r + x2) / 2;
        d += Math.abs(y2 - y1) < 2 ? 'M' + f(a.r) + ' ' + f(y1) + 'H' + f(x2 - 5) : poly([[a.r, y1], [mx, y1], [mx, y2], [x2 - 5, y2]], 6);
        heads += 'M' + f(x2) + ' ' + f(y2) + 'l-8 -4.5v9z';
      } else { // the path wraps to the next row of its lane
        const xo = a.r + 9, ym = b.t - 8, xi = b.l - 11;
        d += poly([[a.r, y1], [xo, y1], [xo, ym], [xi, ym], [xi, y2], [b.l - 7, y2]], 6);
        heads += 'M' + f(b.l - 2) + ' ' + f(y2) + 'l-8 -4.5v9z';
      }
    }
    svg.setAttribute('width', base.width); svg.setAttribute('height', base.height);
    svg.innerHTML = '<path class="ds-line" d="' + d + '"/><path class="ds-headp" d="' + heads + '"/>' + dots;
  }

  /* the same flow as a vertical timeline (narrow screens): the actor is the coloured marker */
  function timeline(steps) {
    return '<ol class="dt">' + steps.map((s, i) =>
      '<li class="dt-step a-' + s.who + (s.decision ? ' is-decision' : '') + (s.end ? ' is-end' : '') + '">' +
      '<span class="dt-mark">' + ic(s.decision ? 'question' : ACTOR_ICON[s.who], 16) + '</span><div class="dt-main">' +
      '<span class="dt-who">' + (i + 1) + ' · ' + esc(D.actors[s.who].label) + (s.proposed ? ' <span class="badge active ds-new">New</span>' : '') + '</span>' +
      '<p class="dt-text">' + esc(s.text) + '</p>' + under(s) + '</div></li>').join('') + '</ol>';
  }

  /* ---------- compare: a comparison row, then each flow as a compact strip ---------- */
  function compareHtml(p, m) {
    const notes = CMP_NOTE[p.id] || [];
    const all = [];
    p.compare.forEach(c => actorsOf(c.steps).forEach(a => { if (all.indexOf(a) < 0) all.push(a); }));
    const tone = c => (c.tone === 'working' ? 'needs' : 'info');
    let h = '<div class="dc-sum">' + p.compare.map((c, i) => {
      const chain = c.steps.map(s => s.who).filter((a, k, arr) => a !== arr[k - 1]);
      return '<section class="card pad dc-card"><p class="dc-title"><span class="dc-n">' + (i + 1) + '</span><strong>' + esc(c.title) + '</strong></p>' +
        (notes[i] ? '<span class="badge ' + tone(c) + '">' + esc(notes[i]) + '</span>' : '') +
        '<span class="dm-chain">' + chain.map(a => '<span class="dw a-' + a + '" title="' + esc(D.actors[a].label) + '">' + ic(ACTOR_ICON[a], 14) + '<span>' + esc(D.actors[a].label) + '</span></span>').join('<span class="dm-sep" aria-hidden="true">→</span>') + '</span></section>';
    }).join('') + '</div>';
    h += '<section class="card dc-legend">' + legend(all) + '</section>';
    h += p.compare.map((c, i) => '<section class="card dc-strip"><div class="card-h"><span class="dc-n">' + (i + 1) + '</span><h2>' + esc(c.title) + '</h2>' +
      (notes[i] ? '<span class="badge ' + tone(c) + '">' + esc(notes[i]) + '</span>' : '') + '</div>' +
      (m === 'n' ? timeline(c.steps) : swim(c.steps, false, true)) + '</section>').join('');
    return h;
  }

  /* ---------- state diagram ---------- */
  function statesHtml(p, m) {
    const by = [];
    p.moves.forEach(x => { if (by.indexOf(x.by) < 0) by.push(x.by); });
    if ((m === 'w1' || m === 'w2') && STATE_MAIN[p.id]) {
      return '<section class="card">' + legend(by) + '<div class="dst dst-wide" role="img" aria-label="' + esc(p.title) + ': ' +
        esc(p.moves.map(x => label(p, x.from) + ' to ' + label(p, x.to) + ': ' + x.text + ' (' + D.actors[x.by].label + ')').join('. ')) + '"></div></section>';
    }
    const lab = id => { const s = p.states.find(x => x.id === id); return '<span class="badge ' + (TONE[s.tone] || '') + '">' + esc(s.label) + '</span>'; };
    return '<section class="card">' + legend(by) + '<div class="dst" role="img" aria-label="' + esc(p.title) + ': states and moves, listed below"></div>' +
      '<ol class="dsm">' + p.moves.map((x, i) => '<li class="a-' + x.by + '"><span class="dsm-n">' + (i + 1) + '</span>' +
        '<span class="dsm-main"><span class="dsm-ft">' + lab(x.from) + '<span aria-hidden="true">→</span>' + lab(x.to) + '</span>' +
        '<span class="dsm-text">' + esc(x.text) + '</span><span class="dsm-by">' + ic(ACTOR_ICON[x.by], 12) + esc(D.actors[x.by].label) + '</span></span></li>').join('') + '</ol></section>';
  }
  const label = (p, id) => p.states.find(s => s.id === id).label;
  // moves between the same two states share one arrow
  function grouped(p) {
    const out = [];
    p.moves.forEach((x, i) => {
      let g = out.find(o => o.from === x.from && o.to === x.to);
      if (!g) out.push(g = { from: x.from, to: x.to, moves: [] });
      g.moves.push({ by: x.by, text: x.text, n: i + 1 });
    });
    return out;
  }
  /* wide: the main path as one big row with the words on the arrows; side states smaller, below */
  function statesWide(el, p, cfg) {
    const W = el.clientWidth;
    if (!W) return;
    const mw = 100, mh = 52, sh = 36, pad = 32, n = cfg.main.length;
    const step = (W - 2 * pad - mw) / (n - 1), gap = step - mw;
    const mainY = 178, top = mainY - mh / 2, bot = mainY + mh / 2, sideY = bot + 172;
    const X = {};
    cfg.main.forEach((id, i) => { X[id] = pad + mw / 2 + i * step; });
    const idx = id => cfg.main.indexOf(id);
    const groups = grouped(p);
    const has = (a, b) => groups.some(g => g.from === a && g.to === b);
    let svg = '', labs = '';
    const lab = (ms, x, y, anchor, w) => {
      labs += '<span class="dst-labs al-' + anchor + '" data-st="left:' + f(x) + 'px;top:' + f(y) + 'px;width:max-content;max-width:' + f(w) + 'px">' +
        ms.map(x2 => '<span class="dst-lab a-' + x2.by + '">' + ic(ACTOR_ICON[x2.by], 12) + '<span>' + esc(x2.text) + '</span></span>').join('') + '</span>';
    };
    const line = (by, d, hd) => { svg += '<g class="dst-move a-' + by + '"><path class="dst-line" d="' + d + '"/><path class="dst-head" d="' + hd + '"/></g>'; };
    const head = (x, y, dir) => 'M' + f(x) + ' ' + f(y) + (dir === 'r' ? 'l-8 -4.5v9z' : dir === 'd' ? 'l-4.5 -8h9z' : 'l-4.5 8h9z');
    groups.forEach(g => {
      const a = idx(g.from), b = idx(g.to), by = g.moves[0].by;
      if (a >= 0 && b === a + 1) {                       // the next state on the main path
        const x1 = X[g.from] + mw / 2 + 3, x2 = X[g.to] - mw / 2 - 3;
        line(by, 'M' + f(x1) + ' ' + mainY + 'H' + f(x2 - 7), head(x2, mainY, 'r'));
        lab(g.moves.slice(0, 1), (x1 + x2) / 2, mainY - 7, 'b', gap - 8);
        if (g.moves.length > 1) lab(g.moves.slice(1), (x1 + x2) / 2, bot + 8, 't', step - 28);
      } else if (a >= 0 && b > a) {                      // skips a state: a shallow arc below the row
        const x1 = X[g.from] + 20, x2 = X[g.to] - 30, h = 60;
        line(by, 'M' + f(x1) + ' ' + (bot + 3) + 'C' + f(x1) + ' ' + (bot + h) + ' ' + f(x2) + ' ' + (bot + h) + ' ' + f(x2) + ' ' + (bot + 10), head(x2, bot + 3, 'u'));
        lab(g.moves, (x1 + x2) / 2, bot + 3 + 0.75 * h, 't', 150);
      } else if (a >= 0 && b >= 0) {                     // back along the path: an arc above the row
        const span = a - b, h = 40 + 110 * (span - 1);
        const x1 = X[g.from] - (span > 1 ? 0 : 18), x2 = X[g.to] + (span > 1 ? -18 : 18);
        line(by, 'M' + f(x1) + ' ' + (top - 3) + 'C' + f(x1) + ' ' + (top - h) + ' ' + f(x2) + ' ' + (top - h) + ' ' + f(x2) + ' ' + (top - 10), head(x2, top - 3, 'd'));
        lab(g.moves, (x1 + x2) / 2, top - 3 - 0.75 * h - 8, 'b', 160);
      } else if (cfg.side[g.to] === g.from || cfg.side[g.from] === g.to) {   // to or from a side state
        const down = cfg.side[g.to] === g.from, m = down ? g.from : g.to, s = down ? g.to : g.from;
        const both = has(m, s) && has(s, m);
        const x = X[m] + (both ? (down ? -12 : 12) : 0), y1 = bot + 3, y2 = sideY - sh / 2 - 3, ym = y2 - 38;
        if (down) line(by, 'M' + f(x) + ' ' + y1 + 'V' + (y2 - 7), head(x, y2, 'd'));
        else line(by, 'M' + f(x) + ' ' + y2 + 'V' + (y1 + 7), head(x, y1, 'u'));
        if (both && down) lab(g.moves, x - 8, ym, 'r', 150); else lab(g.moves, x + 8, ym, 'l', 165);
      }
    });
    const H = sideY + sh / 2 + 24;
    el.style.height = H + 'px';
    el.innerHTML = '<svg class="dst-svg" width="' + W + '" height="' + H + '" aria-hidden="true">' + svg + '</svg>' +
      p.states.map(s => {
        const main = idx(s.id) >= 0;
        if (!main && !cfg.side[s.id]) return '';
        return '<span class="dst-state ' + (main ? 'is-main' : 'is-side') + ' t-' + (s.tone || 'muted') + '" data-st="left:' + f(main ? X[s.id] : X[cfg.side[s.id]]) +
          'px;top:' + (main ? mainY : sideY) + 'px;width:' + (main ? mw : 92) + 'px">' + esc(s.label) + '</span>';
      }).join('') + labs;
    st(el);
  }
  /* narrow, or a states page without a main path: numbered arrows, the words in the list below */
  function statesNumbered(el, p, tall) {
    const W = el.clientWidth;
    if (!W) return;
    const cfg = STATE_MAIN[p.id] || { side: {} };
    const grid = STATE_GRID[p.id] || Object.fromEntries(p.states.map((s, i) => [s.id, [i, 0]]));
    const cell = id => (tall || !STATE_GRID[p.id] ? grid[id] : [grid[id][1], grid[id][0]]);
    const C = Math.max(...p.states.map(s => cell(s.id)[0])) + 1, R = Math.max(...p.states.map(s => cell(s.id)[1])) + 1;
    const nw = tall ? 108 : Math.min(150, Math.max(104, W / C - 90)), nh = 44;
    const padL = tall ? 20 : 24, padR = tall ? 56 : 24, padT = 28, padB = 28;
    const rowGap = tall ? 104 : 132;
    const stepX = C > 1 ? (W - padL - padR - nw) / (C - 1) : 0;
    const H = padT + nh + (R - 1) * rowGap + padB;
    const P = {};
    p.states.forEach(s => { const c = cell(s.id); P[s.id] = { x: padL + nw / 2 + c[0] * stepX, y: padT + nh / 2 + c[1] * rowGap }; });
    const ids = Object.keys(P);
    const mid = { x: ids.reduce((a, k) => a + P[k].x, 0) / ids.length, y: ids.reduce((a, k) => a + P[k].y, 0) / ids.length };
    const inBox = (pt, k, pd) => Math.abs(pt.x - P[k].x) < nw / 2 + pd && Math.abs(pt.y - P[k].y) < nh / 2 + pd;
    const q = (a, c, b, t) => ({ x: (1 - t) * (1 - t) * a.x + 2 * t * (1 - t) * c.x + t * t * b.x, y: (1 - t) * (1 - t) * a.y + 2 * t * (1 - t) * c.y + t * t * b.y });
    const edge = (from, to) => {
      const dx = to.x - from.x, dy = to.y - from.y;
      const t = Math.min(dx ? (nw / 2 + 3) / Math.abs(dx) : Infinity, dy ? (nh / 2 + 3) / Math.abs(dy) : Infinity);
      return { x: from.x + dx * t, y: from.y + dy * t };
    };
    const groups = grouped(p);
    let svg = '', badges = '';
    groups.forEach(g => {
      const a = P[g.from], b = P[g.to], by = g.moves[0].by;
      const len = Math.hypot(b.x - a.x, b.y - a.y), nx = -(b.y - a.y) / len, ny = (b.x - a.x) / len;
      const ctl = k => ({ x: (a.x + b.x) / 2 + nx * k, y: (a.y + b.y) / 2 + ny * k });
      const clear = k => { for (let t = 0.1; t < 0.95; t += 0.05) { const pt = q(a, ctl(k), b, t); if (ids.some(o => o !== g.from && o !== g.to && inBox(pt, o, 10))) return false; } return true; };
      let k = groups.some(o => o.from === g.to && o.to === g.from) ? 34 : 0;
      if (!clear(k)) {
        k = 0;
        for (const mag of [0.2, 0.3, 0.45, 0.6, 0.8, 1, 1.3]) {
          const far = s => Math.hypot(ctl(s * mag * len).x - mid.x, ctl(s * mag * len).y - mid.y);
          const ok = (far(1) >= far(-1) ? [1, -1] : [-1, 1]).find(s => clear(s * mag * len));
          if (ok) { k = ok * mag * len; break; }
        }
      }
      const c = ctl(k), s = edge(a, c), e = edge(b, c);
      const ang = Math.atan2(e.y - c.y, e.x - c.x), ax = Math.cos(ang), ay = Math.sin(ang);
      const back = { x: e.x - ax * 8, y: e.y - ay * 8 };
      svg += '<g class="dst-move a-' + by + '"><path class="dst-line" d="M' + f(s.x) + ' ' + f(s.y) + 'Q' + f(c.x) + ' ' + f(c.y) + ' ' + f(back.x) + ' ' + f(back.y) + '"/>' +
        '<path class="dst-head" d="M' + f(e.x) + ' ' + f(e.y) + 'L' + f(back.x - ay * 4.5) + ' ' + f(back.y + ax * 4.5) + 'L' + f(back.x + ay * 4.5) + ' ' + f(back.y - ax * 4.5) + 'z"/></g>';
      g.moves.forEach((x, j) => {
        const mp = q(s, c, e, 0.5 + (j - (g.moves.length - 1) / 2) * 0.34);
        badges += '<span class="dst-n a-' + x.by + '" data-st="left:' + f(mp.x) + 'px;top:' + f(mp.y) + 'px">' + x.n + '</span>';
      });
    });
    el.style.height = H + 'px';
    el.innerHTML = '<svg class="dst-svg" width="' + W + '" height="' + H + '" aria-hidden="true">' + svg + '</svg>' +
      p.states.map(s => '<span class="dst-state ' + (cfg.side[s.id] ? 'is-side' : 'is-main') + ' t-' + (s.tone || 'muted') + '" data-st="left:' + f(P[s.id].x) + 'px;top:' + f(P[s.id].y) +
        'px;width:' + f(cfg.side[s.id] ? nw - 20 : nw) + 'px">' + esc(s.label) + '</span>').join('') + badges;
    st(el);
  }

  render();
  return { destroy() { cleanup.forEach(fn => fn()); cleanup = []; host.replaceChildren(); host.classList.remove('ui-docs'); } };
  }
  window.UI = window.UI || {};
  window.UI.docs = docs;
})();

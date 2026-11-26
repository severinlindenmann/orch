/* ORCH-576 draft C2: status rows, improved after the owner picked C (18 Nov) and the second challenge.
   Tile = title (2 lines) + one foot line: tasks · ONE signal · ONE add-on icon · ⋯. Rows are drop targets.
   Moving: drag (desktop), ⋯ menu Move to / up / down (keyboard, phone sheet), Waiting asks until when, Undo. */
(() => {
  const D = window.D576, OPEN = '../../ticket/ticket-working.html';
  const ORDER = ['needs', 'check', 'working', 'waiting', 'todo', 'backlog', 'done', 'wontdo'];
  const st = { q: '', pill: 'all', open: {}, unfold: {}, more: {}, hl: null, only: null };
  const root = document.getElementById('d576');
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const ic = (n, s = 14) => n === 'focus'
    ? `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/><circle cx="12" cy="12" r="3"/></svg>`
    : window.icon(n, s);
  const lane = id => D.lanes.find(l => l.id === id);
  const tone = l => `var(--${l.tone})`;
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const phone = () => matchMedia('(max-width: 720px)').matches;
  const ms = v => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(v)) || 200;
  const PILL = { needs: ['needs'], working: ['working'], waiting: ['waiting'], backlog: ['backlog'], done: ['done'], stuck: ['working'] };
  const shownLane = id => st.pill === 'all' || st.pill === 'week' || (PILL[st.pill] || []).includes(id);
  const match = t => (!st.q || (t.k + ' ' + t.title).toLowerCase().includes(st.q)) && (st.pill !== 'stuck' || t.helper?.kind === 'stuck');
  const items = id => {
    const list = D.t.filter(t => t.lane === id && match(t) && (!st.only || (st.only.has(t.k) && t.k !== st.hl?.root)));
    return st.hl ? [...list.filter(t => st.hl.keys.has(t.k)), ...list.filter(t => !st.hl.keys.has(t.k))] : list;  // the family first
  };

  /* ---------- families: epic, release, sub-ticket, part of, waits for, replaced by ---------- */
  const kids = k => D.t.filter(x => x.pk === k);
  const chain = t => { const c = []; for (let p = t; p; p = p.pk ? D.t.find(x => x.k === p.pk) : null) c.unshift(p); return c; };
  const SUBLANE = { done: 'done', working: 'working', todo: 'todo', backlog: 'backlog', waiting: 'waiting' };
  const PART_ORDER = ['done', 'check', 'working', 'waiting', 'needs', 'todo', 'backlog', 'wontdo'];
  const partsOf = t => {
    const on = kids(t.k).map(x => ({ k: x.k, title: x.title, lane: x.lane, deep: kids(x.k).length + (x.subs || []).length }));
    const off = (t.subs || []).filter(s => !on.some(o => o.k === s.k)).map(s => ({ k: s.k, title: s.title, lane: SUBLANE[s.s] || 'todo', off: true }));
    return [...on, ...off].sort((a, b) => PART_ORDER.indexOf(a.lane) - PART_ORDER.indexOf(b.lane));
  };
  const familyOf = k => { const top = chain(D.t.find(x => x.k === k))[0], keys = new Set(); const walk = x => { keys.add(x.k); kids(x.k).forEach(walk); }; walk(top); return { top, keys }; };
  const KIND = { epic: 'Epic', release: 'Release' };
  const parentIc = '<svg class="ic" width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 20V10H6m0 0 4-4m-4 4 4 4"/></svg>';
  function partsBar(t, parts) {
    const done = parts.filter(p => p.lane === 'done').length;
    return `<button class="x2-parts" type="button" data-open="${t.k}" aria-expanded="${!!st.open[t.k]}" title="${done} of ${parts.length} ${t.kind ? 'tickets in this ' + t.kind : 'sub-tickets'} done. Open the list">` +
      `<span class="x2-segs" style="--n:${parts.length}">${parts.map(p => `<i style="--c:${tone(lane(p.lane))}"></i>`).join('')}</span>` +
      `<span class="x2-num">${done}/${parts.length}${t.kind ? ' done' : ''}</span></button>`;
  }

  /* ---------- one tile ---------- */
  const TONE_ORDER = ['bad', 'active', 'watch', 'info', 'good'];
  const addonsOf = t => (t.addons || []).filter(a => !(a.same === 'wait' && t.wait));
  const topAddon = t => addonsOf(t).sort((a, b) => TONE_ORDER.indexOf(a.tone) - TONE_ORDER.indexOf(b.tone))[0];
  const late = t => t.due && (t.q || t.act) ? `<span class="x2-late" title="${esc(t.due)}" aria-label="${esc(t.due)}">${ic('clock', 13)}</span>` : '';
  function signal(t) {
    if (t.q) return `<a class="btn outline xs x2-attn" href="${OPEN}">Answer</a>`;
    if (t.act) return `<a class="btn outline xs" href="${OPEN}">${esc(t.act)}</a>`;
    if (t.due) return `<span class="x2-sig x2-warn">${esc(t.due)}</span>`;
    if (t.helper) return `<span class="x2-sig ${t.helper.kind === 'stuck' ? 'x2-bad' : ''}">${esc(t.helper.text)}</span>`;
    if (t.replacedBy) { const r = D.t.find(x => x.k === t.replacedBy); return `<button class="x2-sig x2-link" type="button" data-rep="${t.k}" title="Replaced by ${esc(t.replacedBy + ' ' + (r?.title || ''))}">Replaced by: ${esc(r?.title || t.replacedBy)}</button>`; }
    if (t.lane === 'done') return '<span class="x2-sig">Finished today</span>';
    if (t.dep) { const d = D.t.find(x => x.k === t.dep); return `<button class="x2-sig x2-link" type="button" data-dep="${t.k}" title="Waits for ${esc(t.dep + ' ' + (d?.title || ''))}">Waits for: ${esc(d?.title || t.dep)}</button>`; }
    if (t.wait) return `<span class="x2-sig" title="${esc(t.wait)}">${esc(t.ws)}</span>`;
    if (t.paused) return '<span class="x2-sig">Paused</span>';
    const parts = partsOf(t);
    if (parts.length && !t.kind) return partsBar(t, parts);
    return '';
  }
  function tile(t, l) {
    const a = topAddon(t);
    const n = addonsOf(t).length, more = n > 1 ? ` and ${n - 1} more` : '';
    const addon = a ? `<button class="x2-addon ${n > 1 ? 'has-n' : ''}" type="button" data-addon="${t.k}" data-tone="${a.tone}" aria-label="${esc(a.text + more)}" title="${esc(a.text + more)}">${ic(a.icon)}${n > 1 ? `<span class="x2-addon-n">${n}</span>` : ''}</button>` : '';
    const parts = partsOf(t), p = t.pk && D.t.find(x => x.k === t.pk);
    const subs = parts.length ? `<div class="x2-expand ${st.open[t.k] ? 'open' : ''}"><div><div class="x2-subs">${parts.map(s => `<button type="button" class="x2-part" data-show="${s.k}" ${s.off ? 'disabled' : ''} title="${esc(s.k + ' ' + s.title)}"><span class="x-dot" style="--c:${tone(lane(s.lane))}" aria-hidden="true"></span><span class="key">${s.k}</span><span class="x2-tt">${esc(s.title)}${s.deep ? ` <span class="x2-deep">+${s.deep}</span>` : ''}</span><span class="x2-where">${esc(lane(s.lane).name)}</span></button>`).join('')}<button class="x2-link x2-showfam" type="button" data-fam="${t.k}">Show them on the board</button></div></div></div>` : '';
    const tasks = t.kind && parts.length ? partsBar(t, parts) : t.tasks[1] ? `<span class="x2-num">${t.tasks[0]}/${t.tasks[1]} tasks</span>` : '';
    const fam = p && !(st.hl && st.hl.root === p.k) ? `<button class="x2-fam x2-link" type="button" data-scope="${p.k}" data-focus="${t.k}" title="Part of ${esc(p.k + ' ' + p.title)}. Show all its parts">Part of: ${esc(p.title)}</button>` : '';
    const hl = st.hl && st.hl.focus === t.k ? ' x2-hl-me' : '';
    return `<article class="x2-tile${hl}" data-k="${t.k}" style="--c:${t.q ? 'var(--needs-you)' : tone(l)}" ${phone() ? '' : 'draggable="true"'}>
      <div class="x2-title">${t.kind ? `<span class="x2-kind" data-kind="${t.kind}">${KIND[t.kind]}</span>` : ''}<a class="x-t" href="${OPEN}" title="${esc(t.k + ' · ' + t.title + ' · changed ' + t.age)}"><span class="key">${t.k}</span>${esc(t.title)}</a></div>
      <div class="x2-foot">${tasks}${late(t)}${signal(t)}${fam}<span class="x-grow"></span>${addon}<button class="x2-more" type="button" data-menu="${t.k}" aria-haspopup="menu" aria-label="More for ${esc(t.k)}">${ic('more')}</button></div>${subs}
    </article>`;
  }

  /* ---------- rows ---------- */
  const cols = () => {
    const w = board.clientWidth - (phone() ? 0 : 156);
    return Math.max(1, Math.floor((w + 6) / (260 + 6)));
  };
  function row(id) {
    const l = lane(id), list = items(id);
    if (st.hl && !list.length) return '';
    const head = `<header class="x2-h"><span class="x-dot" style="--c:${tone(l)}" aria-hidden="true"></span><h2>${esc(l.name)}</h2><span class="count-n" data-count="${id}">${st.hl ? list.length : l.total}</span></header>`;
    let main;
    if (!list.length) main = `<p class="x2-none">${esc(st.only ? 'None of them here' : st.q ? 'No match here' : (l.empty || 'Nothing here'))}</p>`;
    else if (l.folded && !st.unfold[id] && !st.q && st.hl && list.some(t => st.hl.keys.has(t.k))) {
      const mine = list.filter(t => st.hl.keys.has(t.k));
      main = `<div class="x2-tiles">${mine.map(t => tile(t, l)).join('')}</div>`;
    }
    else if (l.folded && !st.unfold[id] && !st.q) main = `<button class="x2-link x2-none" type="button" data-unfold="${id}">${id === 'done' ? `Show ${l.today} finished today` : `Show ${l.total}`}</button>`;
    else {
      const cap = st.more[id] ? list.length : Math.max(cols() * 2, st.hl ? list.filter(t => st.hl.keys.has(t.k)).length : 0);
      const rest = l.total - Math.min(cap, list.length);
      let more = '';
      if (st.only) more = '';
      else if (st.more[id] && l.total > list.length && !st.q) more = `<p class="x2-note">The other ${l.total - list.length} load here as you scroll (demo).</p><button class="x2-link" type="button" data-less="${id}">Show fewer</button>`;
      else if (rest > 0 && !st.q) more = `<button class="x2-link" type="button" data-more="${id}">Show ${Math.min(rest, cols() * 2)} more</button><a class="x2-link" href="../list.html?view=${id}">All ${l.total} ${esc(l.name.toLowerCase())} in the list</a>`;
      if (l.folded && !st.only) more += ` <button class="x2-link" type="button" data-fold="${id}">Fold</button>`;
      main = `<div class="x2-tiles">${list.slice(0, cap).map(t => tile(t, l)).join('')}</div>${more ? `<div class="x2-rowfoot">${more}</div>` : ''}`;
    }
    return `<section class="x2-row ${list.length ? '' : 'is-empty'}" data-lane="${id}" aria-label="${esc(l.name)}, ${l.total}">${head}<div class="x2-main">${main}</div></section>`;
  }

  /* ---------- page ---------- */
  const PILLS = [['all', 'All'], ['needs', 'Needs you'], ['week', 'This week'], ['stuck', 'Stuck'], ['working', 'Working'], ['waiting', 'Waiting'], ['backlog', 'Backlog'], ['done', 'Done this week']];
  root.innerHTML = `<div class="d576-tools x2-tools" role="toolbar" aria-label="Show and filter tickets">
    <div class="d576-pills x2-pills" role="group" aria-label="Quick views">${PILLS.map(([v, n]) => `<button class="chip outline" type="button" data-pill="${v}" aria-pressed="${v === 'all'}">${n}</button>`).join('')}</div>
    <div class="segmented" role="group" aria-label="How to show tickets"><a class="btn" href="../list.html">List</a><button class="btn" type="button" aria-pressed="true">Board</button></div>
    <span class="x-grow"></span>
    <label class="filter">Part of <select id="x2-partof"><option value="">Any ticket</option>${D.t.filter(t => kids(t.k).length).sort((a, b) => (b.kind === 'release') - (a.kind === 'release') || (b.kind === 'epic') - (a.kind === 'epic')).map(t => `<option value="${t.k}">${esc((t.kind ? KIND[t.kind] + ': ' : '') + t.title)}</option>`).join('')}</select></label>
    <div class="search"><input type="search" id="d576q" placeholder="Search tickets" aria-label="Search tickets"></div>
  </div><div class="x2-board" id="x2b"></div><p class="sr-only" id="x2-live" aria-live="polite"></p>`;
  const board = document.getElementById('x2b'), live = document.getElementById('x2-live'), partOf = document.getElementById('x2-partof');
  partOf.addEventListener('change', () => { if (!partOf.value) return clearHl(); showParts(partOf.value); });
  const jump = () => `<div class="x2-jump" role="group" aria-label="Jump to a row">${ORDER.filter(shownLane).map(id => `<button class="chip outline" type="button" data-jump="${id}">${esc(lane(id).name)} <span class="x2-num">${lane(id).total}</span></button>`).join('')}</div>`;
  function banner() {
    if (!st.hl) return '';
    const n = [...st.hl.keys].filter(k => k !== st.hl.root).map(k => D.t.find(x => x.k === k)).filter(Boolean);
    const where = ORDER.map(id => [id, n.filter(t => t.lane === id).length]).filter(([, c]) => c).map(([id, c]) => `${c} ${esc(lane(id).name.toLowerCase())}`).join(' · ');
    return `<div class="x2-banner" role="status"><div class="x2-banner-t">${st.hl.up || ''}<span class="x2-crumbs">${st.hl.html}</span><span class="x2-where">${st.hl.count ? st.hl.count(n.length) + ' · ' : ''}${where}</span></div>` +
      `<button class="btn outline sm" type="button" data-clear>Back to all tickets</button></div>`;
  }
  const draw = () => { board.innerHTML = jump() + banner() + ORDER.filter(shownLane).map(row).join(''); };
  const short = (s, n) => s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s;
  const crumbs = t => chain(t).map((x, i, all) => `${x.kind ? KIND[x.kind] + ' ' : ''}<b>${x.k}</b> ${esc(i === all.length - 1 ? x.title : short(x.title, 28))}`).join('<span class="x2-sep">›</span>');
  // One click on "Part of: X" opens X and everything inside it (all levels). Higher levels are links to widen.
  function showParts(pk, focus) {
    const P = D.t.find(x => x.k === pk), keys = new Set(); const walk = x => { keys.add(x.k); kids(x.k).forEach(walk); }; walk(P);
    const ups = chain(P).slice(0, -1);
    const up = ups.length ? `<span class="x2-up">In ${ups.map(x => `<button class="x2-link" type="button" data-scope="${x.k}">${x.kind && !x.title.startsWith(KIND[x.kind]) ? KIND[x.kind] + ' ' : ''}${esc(short(x.title, 32))}</button>`).join('<span class="x2-sep">›</span>')}</span>` : '';
    const parts = partsOf(P);
    const html = `Parts of ${P.kind ? KIND[P.kind].toLowerCase() + ' ' : ''}<b>${P.k}</b> ${esc(P.title)} <span class="x2-pstate">${esc(lane(P.lane).name)}</span>${parts.length ? ' ' + partsBar(P, parts) : ''}`;
    highlight({ keys, root: P.k, focus, up, html, count: n => `${n} ticket${n === 1 ? '' : 's'}, all levels` });
  }
  function highlight(h) {
    flip(() => { st.hl = h; st.only = h ? h.keys : null; });
    const el = board.querySelector('.x2-hl-me') || board.querySelector('.x2-hl');
    el?.scrollIntoView({ block: 'nearest', behavior: reduce() ? 'auto' : 'smooth' });
    live.textContent = h ? board.querySelector('.x2-banner')?.textContent || '' : 'Showing every ticket';
  }
  const clearHl = () => { partOf.value = ''; highlight(null); };

  // FLIP: tiles glide from where they were to where they are now; new tiles fade in. Nothing moves with reduced motion.
  function flip(mutate, landed) {
    const before = new Map([...board.querySelectorAll('.x2-tile')].map(el => [el.dataset.k, el.getBoundingClientRect()]));
    mutate(); draw();
    if (reduce()) return;
    const dur = ms('--dur-settle');
    board.querySelectorAll('.x2-tile').forEach(el => {
      const b = before.get(el.dataset.k);
      if (!b) { el.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: dur, easing: 'cubic-bezier(0, 0.4, 0, 1)' }); return; }
      const a = el.getBoundingClientRect(), dx = b.left - a.left, dy = b.top - a.top;
      if (dx || dy) el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: dur, easing: 'cubic-bezier(0.4, 0, 0, 1)' });
    });
    if (landed) board.querySelector(`.x2-tile[data-k="${landed}"]`)?.classList.add('x2-landed');
  }
  const bump = ids => ids.forEach(id => { const c = board.querySelector(`[data-count="${id}"]`); if (c) { c.classList.remove('x2-bump'); void c.offsetWidth; c.classList.add('x2-bump'); } });

  /* ---------- moving ---------- */
  const find = k => D.t.find(t => t.k === k);
  function place(t, to, beforeK) {
    D.t.splice(D.t.indexOf(t), 1);
    if (beforeK === 'END') { const last = D.t.map(x => x.lane).lastIndexOf(to); D.t.splice(last + 1, 0, t); return; }
    const i = beforeK ? D.t.findIndex(x => x.k === beforeK) : -1;
    if (i >= 0) D.t.splice(i, 0, t);
    else { const first = D.t.findIndex(x => x.lane === to); D.t.splice(first < 0 ? D.t.length : first, 0, t); }  // a card that arrives goes on top of its row (as in the product)
  }
  function move(k, to, beforeK, opt = {}) {
    const t = find(k), from = t.lane;
    if (to === 'waiting' && from !== 'waiting' && !opt.when) return askWhen(k, beforeK);
    const snap = { lane: from, wait: t.wait, ws: t.ws, idx: D.t.indexOf(t) };
    flip(() => {
      if (from !== to) { lane(from).total--; lane(to).total++; }
      t.lane = to;
      if (to === 'waiting' && opt.when) { t.wait = 'Until ' + opt.when; t.ws = t.wait; }
      if (to !== 'waiting') { delete t.wait; delete t.ws; }
      place(t, to, beforeK);
      if (lane(to).folded && from !== to) st.unfold[to] = st.unfold[to] || false;
    }, k);
    bump(from === to ? [] : [from, to]);
    const where = lane(to).name;
    live.textContent = `${k} moved to ${where}`;
    if (from !== to) window.UI?.toast?.(`${k} moved to ${where}`, () => {
      flip(() => {
        if (t.lane !== snap.lane) { lane(t.lane).total--; lane(snap.lane).total++; }
        t.lane = snap.lane; t.wait = snap.wait; t.ws = snap.ws;
        if (!t.wait) { delete t.wait; delete t.ws; }
        D.t.splice(D.t.indexOf(t), 1); D.t.splice(snap.idx, 0, t);
      }, k);
      bump([to, snap.lane]);
    });
    if (opt.focus) board.querySelector(`[data-menu="${k}"]`)?.focus();
  }
  function step(k, dir) {
    const t = find(k), same = D.t.filter(x => x.lane === t.lane), i = same.indexOf(t), j = i + dir;
    if (j < 0 || j >= same.length) return;
    flip(() => { D.t.splice(D.t.indexOf(t), 1); const other = same[j]; const at = D.t.indexOf(other); D.t.splice(dir < 0 ? at : at + 1, 0, t); }, k);
    board.querySelector(`[data-menu="${k}"]`)?.focus();
  }

  // Waiting asks until when (as the product does), Cancel leaves the ticket where it was.
  const wait = document.createElement('dialog');
  wait.className = 'dialog x2-wait';
  wait.innerHTML = `<form method="dialog"><h2>Wait until when?</h2><p class="meta">The ticket comes back by itself at that time.</p>
    <div class="x2-when" role="group" aria-label="Quick times"><button class="btn outline sm" value="today 21:00">Tonight, 21:00</button><button class="btn outline sm" value="Thu 19 Nov 09:00">Thu 19 Nov, 09:00</button><button class="btn outline sm" value="Mon 23 Nov 09:00">Mon 23 Nov, 09:00</button></div>
    <label class="field x2-pick">Or pick a day and time<input type="datetime-local" min="2026-11-18T18:00"></label>
    <div class="actions"><button class="btn ghost" value="">Cancel</button><button class="btn primary" value="pick" disabled>Wait</button></div></form>`;
  document.body.appendChild(wait);
  let pending = null;
  function askWhen(k, beforeK) { pending = { k, beforeK }; wait.returnValue = ''; wait.showModal(); wait.querySelector('.x2-when button').focus(); }
  const pickIn = wait.querySelector('.x2-pick input'), pickBtn = wait.querySelector('[value="pick"]');
  pickIn.addEventListener('input', () => { pickBtn.disabled = !pickIn.value; });
  const fmt = v => { const d = new Date(v); return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '') + ', ' + d.toTimeString().slice(0, 5); };
  wait.addEventListener('close', () => { let v = wait.returnValue; if (v === 'pick') v = pickIn.value ? fmt(pickIn.value) : ''; pickIn.value = ''; pickBtn.disabled = true; if (pending && v) move(pending.k, 'waiting', pending.beforeK, { when: v, focus: true }); pending = null; });

  // ⋯ menu: a small menu on the desktop, a sheet from the bottom on the phone.
  const pop = document.createElement('div');
  pop.className = 'menu-pop x2-menu'; pop.setAttribute('role', 'menu'); pop.hidden = true;
  document.body.appendChild(pop);
  const sheet = document.createElement('dialog');
  sheet.className = 'sheet x2-sheet';
  document.body.appendChild(sheet);
  let menuFor = null;
  function menuHtml(k) {
    const t = find(k), same = D.t.filter(x => x.lane === t.lane), i = same.indexOf(t);
    return `<a class="menu-item" role="menuitem" href="${OPEN}">Open ticket</a><div class="sep"></div><p class="eyebrow pad">Move to</p>` +
      ORDER.filter(id => id !== 'needs').map(id => `<button class="menu-item" type="button" role="menuitemradio" aria-checked="${t.lane === id}" data-to="${id}" ${t.lane === id ? 'disabled' : ''}>${esc(lane(id).name)}${t.lane === id ? ' <span class="x-grow"></span>✓' : ''}</button>`).join('') +
      `<div class="sep"></div>` + (i > 0 ? `<button class="menu-item" type="button" role="menuitem" data-step="-1">Move up</button>` : '') + (i < same.length - 1 ? `<button class="menu-item" type="button" role="menuitem" data-step="1">Move down</button>` : '');
  }
  function openMenu(btn) {
    menuFor = btn.dataset.menu;
    if (phone()) { sheet.innerHTML = `<div class="x2-sheet-h"><strong>${esc(menuFor)}</strong><button class="btn ghost sm" type="button" data-close>Close</button></div><div role="menu">${menuHtml(menuFor)}</div>`; sheet.showModal(); return; }
    pop.innerHTML = menuHtml(menuFor); pop.hidden = false;
    const r = btn.getBoundingClientRect(), h = pop.offsetHeight;
    pop.style.top = `${Math.min(r.bottom + 4, innerHeight - h - 8)}px`;
    pop.style.left = `${Math.max(8, r.right - pop.offsetWidth)}px`;
    btn.setAttribute('aria-expanded', 'true');
    pop.querySelector('button:not([disabled]), a')?.focus();
  }
  function closeMenu(back) {
    if (!pop.hidden) { pop.hidden = true; const b = board.querySelector(`[data-menu="${menuFor}"]`); b?.setAttribute('aria-expanded', 'false'); if (back) b?.focus(); }
    if (sheet.open) sheet.close();
  }
  const onMenu = e => {
    const b = e.target.closest('[data-to],[data-step],[data-close]'); if (!b) return;
    const k = menuFor; closeMenu(false);
    if (b.dataset.to) move(k, b.dataset.to, null, { focus: true });
    if (b.dataset.step) step(k, +b.dataset.step);
  };
  pop.addEventListener('click', onMenu); sheet.addEventListener('click', onMenu);
  pop.addEventListener('keydown', e => {
    const list = [...pop.querySelectorAll('.menu-item:not([disabled])')], i = list.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); list[(i + (e.key === 'ArrowDown' ? 1 : -1) + list.length) % list.length]?.focus(); }
  });
  document.addEventListener('click', e => { if (!pop.hidden && !pop.contains(e.target) && !e.target.closest('[data-menu]')) closeMenu(false); if (!tip.hidden && !tip.contains(e.target) && !e.target.closest('[data-addon]')) tip.hidden = true; });

  // Add-on icon: the full words on hover and focus (title), and on click or tap a small card with every add-on fact.
  const tip = document.createElement('div');
  tip.className = 'menu-pop x2-tip'; tip.setAttribute('role', 'dialog'); tip.setAttribute('aria-label', 'What add-ons say'); tip.hidden = true;
  document.body.appendChild(tip);
  function openTip(btn) {
    const t = find(btn.dataset.addon);
    tip.innerHTML = addonsOf(t).sort((a, b) => TONE_ORDER.indexOf(a.tone) - TONE_ORDER.indexOf(b.tone)).map(a => `<div class="x2-fact" data-tone="${a.tone}">${ic(a.icon)}<div><p>${esc(a.text)}</p>${a.link ? `<a href="${OPEN}">${esc(a.link)}</a>` : ''}</div></div>`).join('');
    tip.hidden = false;
    const r = btn.getBoundingClientRect();
    tip.style.top = `${Math.min(r.bottom + 6, innerHeight - tip.offsetHeight - 8)}px`;
    tip.style.left = `${Math.max(8, Math.min(r.right - tip.offsetWidth, innerWidth - tip.offsetWidth - 8))}px`;
  }

  /* ---------- dragging (desktop) ---------- */
  let drag = null;
  board.addEventListener('dragstart', e => {
    const el = e.target.closest('.x2-tile'); if (!el) return;
    drag = el.dataset.k; e.dataTransfer.setData('text/plain', drag); e.dataTransfer.effectAllowed = 'move';
    requestAnimationFrame(() => { el.classList.add('x2-dragging'); board.classList.add('x2-drag-on'); });
  });
  const clearMarks = () => { board.querySelectorAll('.x2-target').forEach(n => n.classList.remove('x2-target')); board.querySelectorAll('.x2-before').forEach(n => n.classList.remove('x2-before')); };
  board.addEventListener('dragover', e => {
    const r = e.target.closest('.x2-row'); if (!drag || !r) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    if (!r.classList.contains('x2-target')) { clearMarks(); r.classList.add('x2-target'); r.dataset.say = `Move to ${lane(r.dataset.lane).name}`; }
    board.querySelectorAll('.x2-before').forEach(n => n.classList.remove('x2-before'));
    const next = [...r.querySelectorAll('.x2-tile:not(.x2-dragging)')].find(el => { const b = el.getBoundingClientRect(); return e.clientY < b.top || (e.clientY < b.bottom && e.clientX < b.left + b.width / 2); });
    next?.classList.add('x2-before');
  });
  board.addEventListener('drop', e => {
    const r = e.target.closest('.x2-row'); if (!drag || !r) return;
    e.preventDefault();
    const inTiles = e.target.closest('.x2-tiles'), k = drag;
    const before = r.querySelector('.x2-before')?.dataset.k || (inTiles ? 'END' : null);
    end(); move(k, r.dataset.lane, before);
  });
  const end = () => { drag = null; clearMarks(); board.classList.remove('x2-drag-on'); board.querySelectorAll('.x2-dragging').forEach(n => n.classList.remove('x2-dragging')); };
  board.addEventListener('dragend', end);

  /* ---------- clicks ---------- */
  root.addEventListener('click', e => {
    const b = e.target.closest('[data-open],[data-unfold],[data-fold],[data-more],[data-less],[data-pill],[data-menu],[data-addon],[data-jump],[data-scope],[data-fam],[data-dep],[data-rep],[data-show],[data-clear]');
    if (!b) return;
    if (b.dataset.scope) { showParts(b.dataset.scope, b.dataset.focus); return; }
    if (b.dataset.fam) { showParts(b.dataset.fam); return; }
    if (b.dataset.dep) { const t = D.t.find(x => x.k === b.dataset.dep), d = D.t.find(x => x.k === t.dep); highlight({ keys: new Set([t.k, d.k]), focus: d.k, html: `<b>${t.k}</b> ${esc(t.title)} <span class="x2-sep">waits for</span> <b>${d.k}</b> ${esc(d.title)}` }); return; }
    if (b.dataset.rep) { const t = D.t.find(x => x.k === b.dataset.rep), r = D.t.find(x => x.k === t.replacedBy); highlight({ keys: new Set([t.k, r.k]), focus: r.k, html: `<b>${t.k}</b> ${esc(t.title)} <span class="x2-sep">is replaced by</span> <b>${r.k}</b> ${esc(r.title)}` }); return; }
    if (b.dataset.show) { const t = D.t.find(x => x.k === b.dataset.show); if (t) highlight({ keys: new Set([t.k]), focus: t.k, html: crumbs(t) }); return; }
    if (b.hasAttribute('data-clear')) { clearHl(); return; }
    if (b.dataset.jump) { board.querySelector(`.x2-row[data-lane="${b.dataset.jump}"]`)?.scrollIntoView({ block: 'start', behavior: reduce() ? 'auto' : 'smooth' }); return; }
    if (b.dataset.menu) { e.stopPropagation(); if (!pop.hidden && menuFor === b.dataset.menu) closeMenu(true); else openMenu(b); return; }
    if (b.dataset.addon) { if (!tip.hidden) tip.hidden = true; else openTip(b); return; }
    if (b.dataset.open) { // expand in place, no redraw, so the height animates
      if (!b.closest('.x2-tile')) return;  // the bar in the top line only shows, the rows below are the parts
      const k = b.dataset.open; st.open[k] = !st.open[k];
      b.setAttribute('aria-expanded', st.open[k]); b.closest('.x2-tile').querySelector('.x2-expand').classList.toggle('open', st.open[k]); return;
    }
    flip(() => {
      if (b.dataset.unfold) st.unfold[b.dataset.unfold] = true;
      if (b.dataset.fold) st.unfold[b.dataset.fold] = false;
      if (b.dataset.more) st.more[b.dataset.more] = true;
      if (b.dataset.less) st.more[b.dataset.less] = false;
      if (b.dataset.pill) { st.pill = b.dataset.pill; root.querySelectorAll('[data-pill]').forEach(p => p.setAttribute('aria-pressed', p === b)); }
    });
  });
  document.getElementById('d576q').addEventListener('input', e => { flip(() => { st.q = e.target.value.trim().toLowerCase(); }); });
  addEventListener('keydown', e => { if (e.key === 'Escape') { tip.hidden = true; if (st.hl && pop.hidden && !document.querySelector('dialog[open]')) clearHl(); } });
  let lastCols = 0;
  addEventListener('resize', () => { const c = cols(); if (c !== lastCols) { lastCols = c; draw(); } });

  /* ---------- preview controls (mockup only): live changes to see the motion ---------- */
  const pc = document.createElement('nav');
  pc.className = 'pc'; pc.setAttribute('aria-label', 'Preview controls');
  pc.innerHTML = '<span>Preview</span><a href="#" data-sim="finish">Helper finishes ORCH-547</a><a href="#" data-sim="green">Checks pass on #1611</a><a href="#" data-sim="answer">You answer ORCH-580</a><a href="c2-status-rows.html">Reset</a><a href="c-status-rows.html">First C</a>';
  document.body.appendChild(pc);
  pc.addEventListener('click', e => {
    const s = e.target.closest('[data-sim]')?.dataset.sim; if (!s) return; e.preventDefault();
    if (s === 'finish') { const t = find('ORCH-547'); if (t.lane !== 'working') return; delete t.helper; t.tasks = [6, 6]; t.act = 'Test results'; move('ORCH-547', 'check', null); }
    if (s === 'green') {
      const a = find('ORCH-545').addons[0]; if (a.tone === 'good') return;
      Object.assign(a, { tone: 'good', text: 'Pull request #1611: every check passed. It is in the merge queue.' });
      const btn = board.querySelector('[data-addon="ORCH-545"]');
      if (btn) { btn.dataset.tone = 'good'; btn.title = a.text; btn.setAttribute('aria-label', a.text); btn.classList.remove('x2-swap'); void btn.offsetWidth; btn.classList.add('x2-swap'); }
    }
    if (s === 'answer') { const t = find('ORCH-580'); if (t.lane !== 'needs') return; delete t.q; t.age = 'just now'; move('ORCH-580', 'working', null); }
  });

  draw(); lastCols = cols();
  if (!reduce()) board.querySelectorAll('.x2-row').forEach((r, i) => r.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: ms('--dur-slow'), delay: i * 30, easing: 'cubic-bezier(0, 0.4, 0, 1)', fill: 'backwards' }));
})();

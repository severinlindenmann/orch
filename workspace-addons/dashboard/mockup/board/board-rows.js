/* ORCH-576 board mockup: status rows (owner picked draft C, 18 Nov). Renders with the KIT classes only
   (.status-rows, .status-row, .ticket-tile, .parts-bar, .scope-bar, .kind-tag in widgets.css); no page stylesheet.
   Tile (O-16 C, 28 Nov) = two lines: the title on one line with the add-on icon and the state icon top right, then one foot
   line: tasks, ONE signal word, part of, the ⋯ menu. No button on a card; the card opens the ticket.
   Moving: drag, ⋯ menu Move to / up / down, Waiting asks "Wait until when?", Undo toast. */
(() => {
  const D = window.D576, OPEN = '../ticket/ticket-working.html';
  const ORDER = ['needs', 'check', 'working', 'waiting', 'todo', 'backlog', 'done', 'wontdo'];
  // The product's row ids (data-status) for the mockup's lanes.
  const STATUS = { needs: 'waiting', check: 'review', working: 'active', waiting: 'blocked', todo: 'ready', backlog: 'open', done: 'done', wontdo: 'dropped' };
  // O-14 D (28 Nov): Top tickets only (off at first, top=1 in the address): tickets that are part of no other ticket
  const st = { q: '', open: {}, unfold: {}, more: {}, hl: null, only: null, top: new URLSearchParams(location.search).get('top') === '1' };
  const root = document.getElementById('rows');
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const ic = (n, s = 14) => n === 'focus'
    ? `<svg class="ic" width="${s}" height="${s}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/><circle cx="12" cy="12" r="3"/></svg>`
    : window.icon(n, s);
  const lane = id => D.lanes.find(l => l.id === id);
  const tone = l => `var(--${l.tone})`;
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const phone = () => matchMedia('(max-width: 720px)').matches;
  const ms = v => parseFloat(getComputedStyle(document.documentElement).getPropertyValue(v)) || 200;
  const match = t => !st.q || (t.k + ' ' + t.title).toLowerCase().includes(st.q);
  const items = id => {
    const list = D.t.filter(t => t.lane === id && match(t) && (!st.only || (st.only.has(t.k) && t.k !== st.hl?.root)) && (!st.top || st.hl || !t.pk));
    return st.hl ? [...list.filter(t => st.hl.keys.has(t.k)), ...list.filter(t => !st.hl.keys.has(t.k))] : list;
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
  const KIND = { epic: 'Epic', release: 'Release' };
  const dot = l => `<span class="sdot" style="--c:${tone(l)}" aria-hidden="true"></span>`;
  function partsBar(t, parts, open) {
    const done = parts.filter(p => p.lane === 'done').length;
    const words = `${done} of ${parts.length} ${t.kind ? 'tickets in this ' + t.kind : 'sub-tickets'} done`;
    return `<button class="parts-bar" type="button" data-open="${t.k}" aria-expanded="${!!open}" title="${words}" aria-label="${words}">` +
      `<span class="parts-segs" style="--n:${parts.length}">${parts.map(p => `<i style="--c:${tone(lane(p.lane))}"></i>`).join('')}</span>` +
      `<span class="tile-num">${done}/${parts.length}${t.kind ? ' done' : ''}</span></button>`;
  }

  /* ---------- one tile ---------- */
  const TONE_ORDER = ['bad', 'active', 'watch', 'info', 'good'];
  const addonsOf = t => (t.addons || []).filter(a => !(a.same === 'wait' && t.wait)).sort((a, b) => TONE_ORDER.indexOf(a.tone) - TONE_ORDER.indexOf(b.tone));
  const late = t => t.due && (t.q || t.act) ? `<span class="tile-late" title="${esc(t.due)}" aria-label="${esc(t.due)}">${ic('clock', 13)}</span>` : '';
  function signal(t) {
    // O-15 C / O-16 C (28 Nov): no button on a card; the state is one word here and the icon top right
    if (t.q) return '<span class="tile-sig warn">Question</span>';
    if (t.act) return '<span class="tile-sig">Result</span>';
    if (t.due) return `<span class="tile-sig warn">${esc(t.due)}</span>`;
    if (t.helper) return `<span class="tile-sig${t.helper.kind === 'stuck' ? ' bad' : ''}">${esc(t.helper.text)}</span>`;
    if (t.replacedBy) { const r = D.t.find(x => x.k === t.replacedBy); return `<button class="tile-sig tile-link" type="button" data-rep="${t.k}" title="Replaced by ${esc(t.replacedBy + ' ' + (r?.title || ''))}">Replaced by: ${esc(r?.title || t.replacedBy)}</button>`; }
    if (t.lane === 'done') return '<span class="tile-sig">Finished today</span>';
    if (t.dep) { const d = D.t.find(x => x.k === t.dep); return `<button class="tile-sig tile-link" type="button" data-dep="${t.k}" title="Waits for ${esc(t.dep + ' ' + (d?.title || ''))}">Waits for: ${esc(d?.title || t.dep)}</button>`; }
    if (t.wait) return `<span class="tile-sig" title="${esc(t.wait)}">${esc(t.ws)}</span>`;
    if (t.paused) return '<span class="tile-sig">Paused</span>';
    const parts = partsOf(t);
    if (parts.length && !t.kind) return partsBar(t, parts, st.open[t.k]);
    return '';
  }
  // O-16 C: the card's state as an icon in its top right corner, with its word for a screen reader and on hover
  const STATE = { needs: ['needs', 'Question'], check: ['check', 'Result'], working: ['working', 'Working'], waiting: ['todo', 'Waiting'], todo: ['todo', 'To do'], backlog: ['todo', 'Backlog'], done: ['done', 'Done'], wontdo: ['todo', "Won't do"] };
  function stateIcon(t) {
    const [look, word] = t.helper?.kind === 'stuck' ? ['needs', 'Stuck'] : t.q ? STATE.needs : STATE[t.lane] || STATE.todo;
    const svg = window.UI?.statusIcon ? window.UI.statusIcon(look).outerHTML : '';
    return `<span class="nowrap" role="img" title="${word}" aria-label="${word}" data-state="${look}">${svg}</span>`;
  }
  function menuItems(t) {
    const same = D.t.filter(x => x.lane === t.lane), i = same.indexOf(t);
    return `<a class="menu-item" role="menuitem" href="${OPEN}">Open ticket</a><div class="sep"></div><p class="eyebrow">Move to</p>` +
      ORDER.filter(id => id !== 'needs').map(id => `<button class="menu-item" type="button" role="menuitemradio" aria-checked="${t.lane === id}" data-to="${id}" ${t.lane === id ? 'disabled' : ''}>${esc(lane(id).name)}${t.lane === id ? ' ✓' : ''}</button>`).join('') +
      `<div class="sep"></div>` + (i > 0 ? `<button class="menu-item" type="button" role="menuitem" data-step="-1">Move up</button>` : '') + (i < same.length - 1 ? `<button class="menu-item" type="button" role="menuitem" data-step="1">Move down</button>` : '');
  }
  function tile(t, l) {
    const facts = addonsOf(t), a = facts[0], n = facts.length, words = a ? facts.map(f => f.text).join(' · ') : '';
    const addon = a ? `<details class="menu tile-addon"><summary class="tile-icon" data-tone="${a.tone}" title="${esc(words)}" aria-label="${esc(words)}">${ic(a.icon)}${n > 1 ? `<span class="tile-num">${n}</span>` : ''}</summary>` +
      `<div class="menu-pop tile-facts" role="dialog" aria-label="What add-ons say">${facts.map(f => `<div class="tile-fact" data-tone="${f.tone}"><span class="ic-wrap">${ic(f.icon)}</span><div><p>${esc(f.text)}</p>${f.link ? `<a href="${OPEN}">${esc(f.link)}</a>` : ''}</div></div>`).join('')}</div></details>` : '';
    const parts = partsOf(t), p = t.pk && D.t.find(x => x.k === t.pk), open = st.open[t.k] && parts.length;
    const subs = open ? `<div class="tile-parts">${parts.map(s => `<a class="tile-part" href="${OPEN}" title="${esc(s.k + ' ' + s.title)}">${dot(lane(s.lane))}<span class="key">${s.k}</span><span class="grow tile-part-title">${esc(s.title)}${s.deep ? ` <span class="meta">+${s.deep}</span>` : ''}</span><span class="meta">${esc(lane(s.lane).name)}</span></a>`).join('')}<button class="tile-link" type="button" data-fam="${t.k}">Show them on the board</button></div>` : '';
    const tasks = t.kind && parts.length ? partsBar(t, parts, open) : t.tasks[1] ? `<span class="tile-num">${t.tasks[0]}/${t.tasks[1]} tasks</span>` : '';
    const fam = p && !(st.hl && st.hl.root === p.k) ? `<button class="tile-part-of tile-link" type="button" data-scope="${p.k}" data-focus="${t.k}" title="Part of ${esc(p.k + ' ' + p.title)}. Show all its parts">Part of: ${esc(p.title)}</button>` : '';
    return `<article class="ticket-tile${st.hl && st.hl.focus === t.k ? ' tile-mark' : ''}" data-ticket="${t.k}" style="--c:${t.q ? 'var(--needs-you)' : tone(l)}" ${phone() ? '' : 'draggable="true"'}>
      <div class="row"><h3 class="tile-title grow"><span class="truncate">${t.kind ? `<span class="kind-tag" data-kind="${t.kind}">${KIND[t.kind]}</span>` : ''}<a href="${OPEN}" title="${esc(t.k + ' · ' + t.title + ' · changed ' + t.age)}"><span class="key">${t.k}</span>${esc(t.title)}</a></span></h3>${addon}${stateIcon(t)}</div>
      <div class="tile-foot">${tasks}${late(t)}${signal(t)}${fam}<span class="grow"></span><details class="menu" data-menu="${t.k}"><summary class="tile-icon move-button" aria-label="Move ${esc(t.k)} to another row">${ic('more')}</summary><div class="menu-pop" role="menu">${menuItems(t)}</div></details></div>${subs}
    </article>`;
  }

  root.addEventListener('click', e => { const card = e.target.closest('.ticket-tile'); if (card && !e.target.closest('a,button,summary,details,[role="menu"],[role="dialog"]')) location.href = OPEN; });

  /* ---------- rows ---------- */
  const cols = () => Math.max(1, Math.floor(((root.clientWidth - (phone() ? 0 : 156)) + 6) / 266));
  function row(id) {
    const l = lane(id), list = items(id);
    if (st.hl && !list.length) return '';
    const head = `<div class="status-row-h">${dot(l)}<h2>${esc(l.name)}</h2><span class="status-count count-n" data-count="${id}">${st.hl ? list.length : l.total}</span></div>`;
    let main;
    if (!list.length) main = `<p class="meta status-row-none">${esc(st.only ? 'None of them here' : st.q ? 'No match here' : (l.empty || 'Nothing here'))}</p>`;
    else if (l.folded && !st.unfold[id] && !st.q && st.hl && list.some(t => st.hl.keys.has(t.k))) main = `<div class="tile-grid">${list.filter(t => st.hl.keys.has(t.k)).map(t => tile(t, l)).join('')}</div>`;
    else if (l.folded && !st.unfold[id] && !st.q) main = `<button class="tile-link status-row-none" type="button" data-unfold="${id}">${id === 'done' ? `Show ${l.today} finished today` : `Show ${l.total}`}</button>`;
    else {
      const cap = st.more[id] ? list.length : Math.max(cols() * 2, st.hl ? list.filter(t => st.hl.keys.has(t.k)).length : 0);
      const rest = l.total - Math.min(cap, list.length);
      let more = '';
      if (st.only) more = '';
      else if (st.more[id] && l.total > list.length && !st.q) more = `<p class="meta">The other ${l.total - list.length} load here as you scroll (demo).</p><button class="btn ghost sm" type="button" data-less="${id}">Show fewer</button>`;
      else if (rest > 0 && !st.q) more = `<button class="btn ghost sm" type="button" data-more="${id}">Show ${Math.min(rest, cols() * 2)} more</button><a class="btn ghost sm" href="list.html?view=${id}">All ${l.total} ${esc(l.name.toLowerCase())} in the list</a>`;
      if (l.folded && !st.only) more += ` <button class="btn ghost sm" type="button" data-fold="${id}">Fold</button>`;
      main = `<div class="tile-grid">${list.slice(0, cap).map(t => tile(t, l)).join('')}</div>${more ? `<div class="row status-row-foot">${more}</div>` : ''}`;
    }
    return `<section class="status-row${list.length ? '' : ' is-empty'}" data-status="${STATUS[id]}" data-lane="${id}" aria-label="${esc(l.name)}, ${l.total}">${head}<div class="status-row-main">${main}</div></section>`;
  }

  /* ---------- page ---------- */
  const partOf = document.getElementById('group'), live = document.createElement('p');
  live.className = 'sr-only'; live.setAttribute('aria-live', 'polite'); root.after(live);
  partOf.innerHTML = '<option value="">Any ticket</option>' + D.t.filter(t => kids(t.k).length).sort((a, b) => (b.kind === 'release') - (a.kind === 'release') || (b.kind === 'epic') - (a.kind === 'epic')).map(t => `<option value="${t.k}">${esc((t.kind ? KIND[t.kind] + ': ' : '') + t.title)}</option>`).join('');
  partOf.addEventListener('change', () => { if (!partOf.value) return clearHl(); showParts(partOf.value); });
  { const chip = document.querySelector('[data-top]'); if (chip) { chip.setAttribute('aria-checked', String(st.top)); chip.classList.toggle('active', st.top); chip.href = st.top ? 'board.html' : 'board.html?top=1'; } }
  document.getElementById('q').addEventListener('input', e => flip(() => { st.q = e.target.value.trim().toLowerCase(); }));
  const jump = () => phone() ? `<div class="row wrap" role="group" aria-label="Jump to a row">${ORDER.map(id => `<button class="chip outline" type="button" data-jump="${id}">${esc(lane(id).name)} <span class="tile-num">${lane(id).total}</span></button>`).join('')}</div>` : '';
  function banner() {
    if (!st.hl) return '';
    const n = [...st.hl.keys].filter(k => k !== st.hl.root).map(k => D.t.find(x => x.k === k)).filter(Boolean);
    const where = ORDER.map(id => [id, n.filter(t => t.lane === id).length]).filter(([, c]) => c).map(([id, c]) => `${c} ${esc(lane(id).name.toLowerCase())}`).join(' · ');
    return `<div class="scope-bar" role="status"><div class="grow">${st.hl.up || ''}<p class="scope-title">${st.hl.html}</p><p class="meta">${st.hl.count ? st.hl.count(n.length) + ' · ' : ''}${where}</p></div>` +
      `<button class="btn outline sm" type="button" data-clear>Back to all tickets</button></div>`;
  }
  const draw = () => { root.innerHTML = banner() + `<div class="status-rows-track" title="Drag a tile to another row, or use its ⋯ menu">${ORDER.map(row).join('')}</div>`; };
  const short = (s, n) => s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s;
  const tag = x => `<span class="key">${x.k}</span>`;
  const crumbs = t => chain(t).map((x, i, all) => `${x.kind ? KIND[x.kind] + ' ' : ''}${tag(x)}${esc(i === all.length - 1 ? x.title : short(x.title, 28))}`).join(' › ');
  function showParts(pk, focus) {
    const P = D.t.find(x => x.k === pk), keys = new Set(); const walk = x => { keys.add(x.k); kids(x.k).forEach(walk); }; walk(P);
    const ups = chain(P).slice(0, -1);
    const up = ups.length ? `<p class="scope-up meta">In ${ups.map(x => `<button class="tile-link" type="button" data-scope="${x.k}">${x.kind && !x.title.startsWith(KIND[x.kind]) ? KIND[x.kind] + ' ' : ''}${esc(short(x.title, 32))}</button>`).join(' › ')}</p>` : '';
    const parts = partsOf(P);
    const html = `Parts of ${P.kind ? KIND[P.kind].toLowerCase() + ' ' : ''}${tag(P)}${esc(P.title)} <span class="chip outline sm">${esc(lane(P.lane).name)}</span>${parts.length ? ' ' + partsBar(P, parts, false) : ''}`;
    highlight({ keys, root: P.k, focus, up, html, count: n => `${n} ticket${n === 1 ? '' : 's'}, all levels` });
  }
  function highlight(h) {
    flip(() => { st.hl = h; st.only = h ? h.keys : null; });
    root.querySelector('.tile-mark')?.scrollIntoView({ block: 'nearest', behavior: reduce() ? 'auto' : 'smooth' });
    live.textContent = h ? root.querySelector('.scope-bar')?.textContent || '' : 'Showing every ticket';
  }
  const clearHl = () => { partOf.value = ''; highlight(null); };

  // Tiles glide from where they were to where they are now; new tiles fade in. Nothing moves with reduced motion.
  function flip(mutate, landed) {
    const before = new Map([...root.querySelectorAll('.ticket-tile')].map(el => [el.dataset.ticket, el.getBoundingClientRect()]));
    mutate(); draw();
    if (reduce()) return;
    const dur = ms('--dur-settle');
    root.querySelectorAll('.ticket-tile').forEach(el => {
      const b = before.get(el.dataset.ticket);
      if (!b) { el.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: dur, easing: 'cubic-bezier(0, 0.4, 0, 1)' }); return; }
      const a = el.getBoundingClientRect(), dx = b.left - a.left, dy = b.top - a.top;
      if (dx || dy) el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: dur, easing: 'cubic-bezier(0.4, 0, 0, 1)' });
    });
  }

  /* ---------- moving ---------- */
  const find = k => D.t.find(t => t.k === k);
  function place(t, to, beforeK) {
    D.t.splice(D.t.indexOf(t), 1);
    if (beforeK === 'END') { const last = D.t.map(x => x.lane).lastIndexOf(to); D.t.splice(last + 1, 0, t); return; }
    const i = beforeK ? D.t.findIndex(x => x.k === beforeK) : -1;
    if (i >= 0) D.t.splice(i, 0, t);
    else { const first = D.t.findIndex(x => x.lane === to); D.t.splice(first < 0 ? D.t.length : first, 0, t); }
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
    }, k);
    const where = lane(to).name;
    live.textContent = `${k} moved to ${where}`;
    if (from !== to) window.UI?.toast?.(`${k} moved to ${where}`, () => {
      flip(() => {
        if (t.lane !== snap.lane) { lane(t.lane).total--; lane(snap.lane).total++; }
        t.lane = snap.lane; t.wait = snap.wait; t.ws = snap.ws;
        if (!t.wait) { delete t.wait; delete t.ws; }
        D.t.splice(D.t.indexOf(t), 1); D.t.splice(snap.idx, 0, t);
      }, k);
    });
    if (opt.focus) root.querySelector(`[data-menu="${k}"] summary`)?.focus();
  }
  function step(k, dir) {
    const t = find(k), same = D.t.filter(x => x.lane === t.lane), i = same.indexOf(t), j = i + dir;
    if (j < 0 || j >= same.length) return;
    flip(() => { D.t.splice(D.t.indexOf(t), 1); const other = same[j]; const at = D.t.indexOf(other); D.t.splice(dir < 0 ? at : at + 1, 0, t); }, k);
    root.querySelector(`[data-menu="${k}"] summary`)?.focus();
  }

  // Waiting asks until when (as the product does); Cancel leaves the ticket where it was.
  const wait = document.createElement('dialog');
  wait.className = 'dialog';
  wait.innerHTML = `<form method="dialog"><h2>Wait until when?</h2><p class="meta">The ticket comes back by itself at that time.</p>
    <div class="row wrap" role="group" aria-label="Quick times"><button class="btn outline sm" value="today 21:00">Tonight, 21:00</button><button class="btn outline sm" value="Thu 19 Nov 09:00">Thu 19 Nov, 09:00</button><button class="btn outline sm" value="Mon 23 Nov 09:00">Mon 23 Nov, 09:00</button></div>
    <label class="field">Or pick a day and time<input class="input" type="datetime-local" min="2026-11-18T18:00"></label>
    <div class="actions"><button class="btn ghost" value="">Cancel</button><button class="btn primary" value="pick" disabled>Wait</button></div></form>`;
  document.body.appendChild(wait);
  let pending = null;
  function askWhen(k, beforeK) { pending = { k, beforeK }; wait.returnValue = ''; wait.showModal(); wait.querySelector('.row button').focus(); }
  const pickIn = wait.querySelector('input'), pickBtn = wait.querySelector('[value="pick"]');
  pickIn.addEventListener('input', () => { pickBtn.disabled = !pickIn.value; });
  const fmt = v => { const d = new Date(v); return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace(',', '') + ', ' + d.toTimeString().slice(0, 5); };
  wait.addEventListener('close', () => { let v = wait.returnValue; if (v === 'pick') v = pickIn.value ? fmt(pickIn.value) : ''; pickIn.value = ''; pickBtn.disabled = true; if (pending && v) move(pending.k, 'waiting', pending.beforeK, { when: v, focus: true }); pending = null; });

  /* ---------- dragging (desktop) ---------- */
  let drag = null;
  root.addEventListener('dragstart', e => {
    const el = e.target.closest('.ticket-tile'); if (!el) return;
    drag = el.dataset.ticket; e.dataTransfer.setData('text/plain', drag); e.dataTransfer.effectAllowed = 'move';
    requestAnimationFrame(() => { el.classList.add('dragging'); root.classList.add('is-dragging'); });
  });
  const clearMarks = () => { root.querySelectorAll('.drop-target').forEach(n => n.classList.remove('drop-target')); root.querySelectorAll('.drop-before').forEach(n => n.classList.remove('drop-before')); };
  root.addEventListener('dragover', e => {
    const r = e.target.closest('.status-row'); if (!drag || !r) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    if (!r.classList.contains('drop-target')) { clearMarks(); r.classList.add('drop-target'); r.dataset.say = `Move to ${lane(r.dataset.lane).name}`; }
    root.querySelectorAll('.drop-before').forEach(n => n.classList.remove('drop-before'));
    const next = [...r.querySelectorAll('.ticket-tile:not(.dragging)')].find(el => { const b = el.getBoundingClientRect(); return e.clientY < b.top || (e.clientY < b.bottom && e.clientX < b.left + b.width / 2); });
    next?.classList.add('drop-before');
  });
  root.addEventListener('drop', e => {
    const r = e.target.closest('.status-row'); if (!drag || !r) return;
    e.preventDefault();
    const inTiles = e.target.closest('.tile-grid'), k = drag;
    const before = r.querySelector('.drop-before')?.dataset.ticket || (inTiles ? 'END' : null);
    end(); move(k, r.dataset.lane, before);
  });
  const end = () => { drag = null; clearMarks(); root.classList.remove('is-dragging'); root.querySelectorAll('.dragging').forEach(n => n.classList.remove('dragging')); };
  root.addEventListener('dragend', end);

  /* ---------- clicks ---------- */
  root.addEventListener('click', e => {
    const to = e.target.closest('[data-menu] [data-to],[data-menu] [data-step]');
    if (to) {
      const k = to.closest('[data-menu]').dataset.menu; to.closest('details').open = false;
      if (to.dataset.to) move(k, to.dataset.to, null, { focus: true }); else step(k, +to.dataset.step);
      return;
    }
    const b = e.target.closest('[data-open],[data-unfold],[data-fold],[data-more],[data-less],[data-jump],[data-scope],[data-fam],[data-dep],[data-rep],[data-clear]');
    if (!b) return;
    if (b.dataset.scope) { showParts(b.dataset.scope, b.dataset.focus); return; }
    if (b.dataset.fam) { showParts(b.dataset.fam); return; }
    if (b.dataset.dep) { const t = find(b.dataset.dep), d = find(t.dep); highlight({ keys: new Set([t.k, d.k]), focus: d.k, html: `${tag(t)}${esc(t.title)} <span class="meta">waits for</span> ${tag(d)}${esc(d.title)}` }); return; }
    if (b.dataset.rep) { const t = find(b.dataset.rep), r = find(t.replacedBy); highlight({ keys: new Set([t.k, r.k]), focus: r.k, html: `${tag(t)}${esc(t.title)} <span class="meta">is replaced by</span> ${tag(r)}${esc(r.title)}` }); return; }
    if (b.hasAttribute('data-clear')) { clearHl(); return; }
    if (b.dataset.jump) { root.querySelector(`.status-row[data-lane="${b.dataset.jump}"]`)?.scrollIntoView({ block: 'start', behavior: reduce() ? 'auto' : 'smooth' }); return; }
    if (b.dataset.open) { if (!b.closest('.ticket-tile')) return; st.open[b.dataset.open] = !st.open[b.dataset.open]; draw(); return; }
    flip(() => {
      if (b.dataset.unfold) st.unfold[b.dataset.unfold] = true;
      if (b.dataset.fold) st.unfold[b.dataset.fold] = false;
      if (b.dataset.more) st.more[b.dataset.more] = true;
      if (b.dataset.less) st.more[b.dataset.less] = false;
    });
  });
  // One open popover at a time; a click elsewhere or Escape closes it.
  document.addEventListener('click', e => { root.querySelectorAll('details[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; }); });
  addEventListener('keydown', e => { if (e.key === 'Escape') { const o = root.querySelector('details[open]'); if (o) { o.open = false; o.querySelector('summary')?.focus(); } else if (st.hl && !document.querySelector('dialog[open]')) clearHl(); } });
  let lastCols = 0, lastPhone = phone();
  addEventListener('resize', () => { const c = cols(); if (c !== lastCols || lastPhone !== phone()) { lastCols = c; lastPhone = phone(); draw(); } });

  draw(); lastCols = cols();
  if (!reduce()) root.querySelectorAll('.status-row').forEach((r, i) => r.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: ms('--dur-slow'), delay: i * 30, easing: 'cubic-bezier(0, 0.4, 0, 1)', fill: 'backwards' }));
})();

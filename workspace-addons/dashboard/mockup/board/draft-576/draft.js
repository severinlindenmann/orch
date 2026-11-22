/* ORCH-576 compact board drafts. One renderer, three looks: body[data-draft=A|B|C]. */
(() => {
  const D = window.D576, draft = document.body.dataset.draft;
  const OPEN = '../../ticket/ticket-working.html';
  const st = { q: '', pill: 'all', open: {}, unfold: {}, more: {} };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const lane = id => D.lanes.find(l => l.id === id);
  const tone = l => `var(--${l.tone})`;
  const PILL = { needs: ['needs'], working: ['working'], waiting: ['waiting'], backlog: ['backlog'], done: ['done'], stuck: [] };
  const shownLane = id => st.pill === 'all' || st.pill === 'week' || (PILL[st.pill] || []).includes(id);
  const items = id => D.t.filter(t => t.lane === id && (!st.q || (t.k + ' ' + t.title).toLowerCase().includes(st.q)));
  const pct = t => Math.round(100 * t.tasks[0] / Math.max(1, t.tasks[1]));
  const prog = (t, c) => t.tasks[1] ? `<span class="x-mini" style="--v:${pct(t)}%;--c:${c}"><i></i></span><span class="x-num">${t.tasks[0]}/${t.tasks[1]}${draft === 'C' ? ' tasks' : ''}</span>` : '';
  const extra = t => t.due ? `<span class="x-faint x-warn">${esc(t.due)}</span>` : t.wait ? `<span class="x-faint" title="${esc(t.wait)}">${esc(t.ws || t.wait)}</span>` : t.paused ? '<span class="x-faint">Paused</span>' : '';
  const subsDone = t => t.subs.filter(s => s.s === 'done').length;
  const subList = t => `<div class="x-subs">${t.subs.map(s => `<div><span class="${s.s === 'done' ? 'x-ok' : 'x-faint'}">${s.s === 'done' ? '✓' : '○'}</span><span class="key">${s.k}</span><span class="x-tt" title="${esc(s.title)}">${esc(s.title)}</span></div>`).join('')}</div>`;
  const title = t => `<div class="x-title"><a class="x-t" href="${OPEN}" title="${esc(t.k + ' ' + t.title)}"><span class="key">${t.k}</span>${esc(t.title)}</a></div>`;
  const moreBtn = (l, shown) => {
    const rest = l.total - shown;
    if (rest <= 0 || st.q) return '';
    return st.more[l.id] ? `<p class="x-faint x-more">All ${l.total} would load here (demo)</p>` : `<button class="x-linkish x-more" data-more="${l.id}">Show ${rest} more</button>`;
  };

  /* ---------- A: slim cards ---------- */
  function cardA(t, l) {
    let sub = '';
    if (t.subs) {
      const o = st.open[t.k];
      sub = `<button class="x-linkish" data-open="${t.k}" aria-expanded="${!!o}">${o ? '▾' : '▸'} ${t.subs.length} sub-tickets · ${subsDone(t)} done</button>${o ? subList(t) : ''}`;
    } else if (t.parent) sub = `<div class="x-sub-line" title="Part of ${esc(t.parent)}">↳ ${esc(t.parent)}</div>`;
    const right = t.act ? `<a class="btn outline xs" href="${OPEN}">${esc(t.act)}</a>` : extra(t) ? '' : `<span class="x-faint">${esc(t.age)}</span>`;
    return `<article class="x-card">${title(t)}${sub}<div class="x-foot">${prog(t, tone(l))}${extra(t)}<span class="x-grow"></span>${right}</div></article>`;
  }
  function A() {
    return `<div class="dA">${D.boardOrder.filter(shownLane).map(id => {
      const l = lane(id), list = items(id);
      const folded = (l.folded && !st.unfold[id] && !st.q) || (!list.length && !st.q && l.total === 0);
      if (folded) return `<section data-lane="${id}" class="x-lane x-rail" style="--c:${tone(l)}" data-unfold="${id}" role="button" tabindex="0" title="${l.total ? 'Show ' + esc(l.name) : esc(l.empty)}"><span class="count-n">${l.total}</span><span class="x-v">${esc(l.name)}</span></section>`;
      const shown = id === 'done' ? list.slice(0, 6) : list;
      return `<section data-lane="${id}" class="x-lane" style="--c:${tone(l)}"><header class="x-lane-h"><span class="x-dot"></span>${esc(l.name)}<span class="count-n">${l.total}</span>${l.folded ? `<button class="btn ghost icon xs" data-fold="${id}" aria-label="Fold ${esc(l.name)}">‹</button>` : ''}</header><div class="x-body">${shown.map(t => cardA(t, l)).join('') || `<p class="x-faint x-more">${esc(l.empty)}</p>`}${moreBtn(l, shown.length)}</div></section>`;
    }).join('')}</div>`;
  }

  /* ---------- B: one-line rows ---------- */
  function rowB(t, l) {
    const right = t.lane === 'waiting' ? `<span class="x-faint" title="${esc(t.wait || '')}">${esc(t.ws || '')}</span>`
      : t.act ? `<a class="btn outline xs" href="${OPEN}">${esc(t.act)}</a>`
      : t.tasks[1] && t.lane !== 'done' ? `<span class="x-num">${t.tasks[0]}/${t.tasks[1]}</span>` : `<span class="x-faint">${esc(t.age)}</span>`;
    const tw = t.subs ? `<button class="x-tw" data-open="${t.k}" aria-expanded="${!!st.open[t.k]}" aria-label="Sub-tickets">${st.open[t.k] ? '▾' : '▸'}</button>` : (t.due ? `<span class="x-dot" style="--c:var(--warning)" title="${esc(t.due)}"></span>` : '<span></span>');
    let html = `<div class="x-row">${tw}<a class="x-t" href="${OPEN}" title="${esc(t.k + ' ' + t.title)}">${esc(t.title)}</a>${right}</div>`;
    if (t.subs && st.open[t.k]) html += t.subs.map(s => `<div class="x-row x-child"><span class="${s.s === 'done' ? 'x-ok' : 'x-faint'}" style="font-size:11px">${s.s === 'done' ? '✓' : '○'}</span><a class="x-t" href="${OPEN}" title="${esc(s.k + ' ' + s.title)}"><span class="key">${s.k}</span>${esc(s.title)}</a><span class="x-faint">${s.when || ''}</span></div>`).join('');
    return html;
  }
  function B() {
    return `<div class="dB">${D.boardOrder.filter(shownLane).map(id => {
      const l = lane(id), list = items(id);
      const thin = (l.folded && !st.unfold[id] && !st.q) || (!list.length && l.total === 0);
      if (thin) return `<section data-lane="${id}" class="x-lane x-thin" style="--c:${tone(l)}"><header class="x-lane-h"><span class="x-dot"></span>${esc(l.name)}<span class="count-n">${l.total}</span></header><div class="x-body">${l.total ? `<button class="x-linkish x-empty" data-unfold="${id}">Show ${l.total}</button>` : `<p class="x-empty">${esc(l.empty)}</p>`}</div></section>`;
      let body;
      if (id === 'done') body = `<p class="x-grp">Today · ${l.today}</p>${list.map(t => rowB(t, l)).join('')}`;
      else body = list.map(t => rowB(t, l)).join('');
      return `<section data-lane="${id}" class="x-lane" style="--c:${tone(l)}"><header class="x-lane-h"><span class="x-dot"></span>${esc(l.name)}<span class="count-n">${l.total}</span></header><div class="x-body">${body || `<p class="x-empty">${esc(l.empty)}</p>`}${moreBtn(l, list.length)}</div></section>`;
    }).join('')}</div>`;
  }

  /* ---------- C: status rows ---------- */
  const SAY = { needs: 'waits on you', check: 'finished, look at it', working: 'a helper is on it', waiting: 'on a time or another ticket', todo: 'picked to do next', backlog: 'not picked yet', done: '', wontdo: '' };
  function tileC(t, l) {
    let sub = '';
    if (t.subs) { const o = st.open[t.k]; sub = `<button class="x-linkish" data-open="${t.k}" aria-expanded="${!!o}">${o ? '▾' : '▸'} ${t.subs.length} sub-tickets · ${subsDone(t)} done</button>${o ? subList(t) : ''}`; }
    const right = t.act ? `<a class="btn outline xs" href="${OPEN}">${esc(t.act)}</a>` : `<span class="x-faint">${esc(t.age)}</span>`;
    return `<article class="x-tile" style="--c:${t.due ? 'var(--warning)' : tone(l)}">${title(t)}${sub}<div class="x-foot">${prog(t, tone(l))}${extra(t)}<span class="x-grow"></span>${right}</div></article>`;
  }
  function C() {
    const order = ['needs', 'check', 'working', 'waiting', 'todo', 'backlog', 'done', 'wontdo'];
    return `<div class="dC">${order.filter(shownLane).map(id => {
      const l = lane(id), list = items(id);
      const cap = st.more[id] ? list.length : (id === 'done' ? 4 : 8);
      const say = id === 'done' ? `${l.today} today` : SAY[id];
      const head = `<header><span class="x-lane-h"><span class="x-dot" style="--c:${tone(l)}"></span>${esc(l.name)}<span class="count-n">${l.total}</span></span>${say ? `<span class="x-faint">${esc(say)}</span>` : ''}</header>`;
      if (!list.length) return `<section class="x-srow x-empty x-quiet">${head}<div class="x-tiles">${esc(l.empty || 'Nothing here')}</div></section>`;
      if (l.folded && !st.unfold[id] && !st.q) return `<section class="x-srow x-empty x-quiet">${head}<div class="x-tiles"><button class="x-linkish" data-unfold="${id}">Show ${id === 'done' ? l.today + ' finished today' : 'all ' + l.total}</button></div></section>`;
      return `<section class="x-srow">${head}<div><div class="x-tiles">${list.slice(0, cap).map(t => tileC(t, l)).join('')}</div>${moreBtn(l, Math.min(cap, list.length))}</div></section>`;
    }).join('')}</div>`;
  }

  /* ---------- page ---------- */
  const PILLS = [['all', 'All'], ['needs', 'Needs you'], ['week', 'This week'], ['stuck', 'Stuck'], ['working', 'Working'], ['waiting', 'Waiting'], ['backlog', 'Backlog'], ['done', 'Done this week']];
  const root = document.getElementById('d576');
  root.innerHTML = `<div class="d576-tools" role="toolbar" aria-label="Show and filter tickets">
    <div class="d576-pills" role="group" aria-label="Quick views">${PILLS.map(([v, n]) => `<button class="chip outline" type="button" data-pill="${v}" aria-pressed="${v === 'all'}">${n}</button>`).join('')}</div>
    <div class="segmented" role="group" aria-label="How to show tickets"><a class="btn" href="../list.html">List</a><button class="btn" type="button" aria-pressed="true">Board</button></div>
    <span class="x-grow"></span>
    <label class="filter">Part of <select><option>Any ticket</option><option>Stress test</option><option>Dev workspace: light checks</option></select></label>
    <div class="search"><input type="search" id="d576q" placeholder="Search tickets" aria-label="Search tickets"></div>
  </div><div id="d576b"></div>`;
  const board = document.getElementById('d576b');
  const picker = () => draft === 'C' ? '' : `<div class="x-picker" role="group" aria-label="Go to lane">${D.boardOrder.filter(shownLane).map(id => { const l = lane(id); return `<button class="chip outline" type="button" data-jump="${id}">${esc(l.name)} <span class="x-num">${l.total}</span></button>`; }).join('')}</div>`;
  const draw = () => { board.innerHTML = picker() + { A, B, C }[draft](); };
  draw();
  document.getElementById('d576q').addEventListener('input', e => { st.q = e.target.value.trim().toLowerCase(); draw(); });
  root.addEventListener('click', e => {
    const b = e.target.closest('[data-open],[data-unfold],[data-fold],[data-more],[data-pill],[data-jump]');
    if (!b) return;
    if (b.dataset.jump) { const s = board.querySelector(`[data-lane="${b.dataset.jump}"]`); if (s) s.scrollIntoView({ inline: 'start', block: 'nearest', behavior: 'smooth' }); return; }
    if (b.dataset.open) st.open[b.dataset.open] = !st.open[b.dataset.open];
    if (b.dataset.unfold) st.unfold[b.dataset.unfold] = true;
    if (b.dataset.fold) st.unfold[b.dataset.fold] = false;
    if (b.dataset.more) st.more[b.dataset.more] = true;
    if (b.dataset.pill) { st.pill = b.dataset.pill; root.querySelectorAll('[data-pill]').forEach(p => p.setAttribute('aria-pressed', p === b)); }
    draw();
  });
  root.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.dataset.unfold) { e.preventDefault(); e.target.click(); } });
  const sw = document.createElement('nav');
  sw.className = 'd576-switch'; sw.setAttribute('aria-label', 'Drafts');
  sw.innerHTML = '<span class="x-faint">Draft</span>' + [['A', 'Slim cards', 'a-slim-cards.html'], ['B', 'One-line rows', 'b-rows.html'], ['C', 'Status rows', 'c-status-rows.html']]
    .map(([k, n, f]) => `<a href="${f}" ${k === draft ? 'aria-current="page"' : ''} title="${n}">${k}<span class="x-n"> · ${n}</span></a>`).join('');
  document.body.appendChild(sw);
})();

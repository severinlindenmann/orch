'use strict';
// The live bar (draft D, ORCH-337): one calm row under every page while the Preview switch is on. Needs-you chips
// (orange) and pinned chips first, then quiet counts (working, in line, idle) that open a list with search. It never
// wraps: when the row is too narrow it folds step by step into counts (kit .lbar, data-fold). The dashboard names no
// add-on: the live page is found by its live_session capability (pages/live.js).
//
// Data: the live sessions API (pages/livesessions.js, window.LiveSessions; ORCH-359). Pinning is not stored by orch
// yet (the wall builds it): until then the pinned ids are read from this browser only (LIVEBAR_PINS).
//
// Mount: the bar is one element (#live-bar). It goes into the dashboard's keep place ([data-keep], the mount point that
// outlives page changes) when there is one, else at the end of .shell-body; LiveBar.mount(host) moves it anywhere else
// and it stays the same element (its open list included). With the layer (window.LiveLayer.open) a chip opens its
// session there; the layer's orch:live-layer event marks the open ones; LiveBar.end(fn) fills the right end.
const LIVEBAR_PINS = 'orch.live.pins';
const LIVEBAR_LISTS = {
  wait: {sym:'◆', word:'need you', head:'Needs you'},
  pin: {sym:'', word:'pinned', head:'Pinned'},
  run: {sym:'●', word:'working', head:'Working'},
  queue: {sym:'◷', word:'in line', head:'In line'},
  idle: {sym:'◐', word:'idle', head:'Idle'},
  more: {sym:'', word:'more', head:'More sessions'},
};
const LIVEBAR_SEARCH_FROM = 9;  // a list this long gets a search box (draft D)

// The New menu (draft D): sessions without a ticket, in its order; the core starts them (`orch session new <kind>`).
const LIVEBAR_NEW = [
  {kind:'empty', title:'Empty helper', what:'A helper with no ticket and no task yet'},
  {kind:'chat', title:'Chat helper', what:'Ask anything, no ticket'},
  {kind:'terminal', title:'Plain terminal', what:'An empty terminal in this workspace'},
  {kind:'manager', title:'Manager', what:'Looks after all helpers'},
];

// One row per live session: {id, key, title, s: wait|run|queue|idle, word, pin}, from the live sessions API
// (pages/livesessions.js, ORCH-359): the same list the panes and the wall read.
const liveBarModel = typeof liveBarRows === 'function' ? liveBarRows : require('./livesessions.js').liveBarRows;
// One ticket's session from the dashboard's own state (helpers.js), for the ticket's session button: it shows without
// the Preview switch, so it does not wait for the live sessions API. Same states as the bar: wait, run, queue, idle.
function liveTicketSession(t, run, helperState) {
  if (!t || !t.id || t.status === 'dropped' || !run) return null;
  const hs = helperState(run, t);
  if (hs) return {s:hs.state === 'you' ? 'wait' : hs.state === 'idle' ? 'idle' : hs.state === 'waiting' ? 'queue' : 'run'};
  return run.hold ? {s:'queue'} : null;
}
// The word on a ticket's session button (draft D feature 3, "the button on every ticket"): Answer when it needs you, Watch while its helper works, Open
// when the helper sits idle, In line while it waits for a free place, Start when no helper runs. A finished ticket with
// no helper gets no button (''). The same session states as the bar, so the button and the bar never disagree.
function liveFocusVerb(t, run, helperState) {
  if (!t || !t.id) return '';
  const o = liveTicketSession(t, run, helperState);
  const asks = Array.isArray(t.questions) && t.questions.some(q => q && q.answer == null);
  if (o?.s === 'wait' || (asks && !['done', 'dropped', 'superseded'].includes(t.status) && o?.s !== 'run')) return 'Answer';
  if (o) return {run:'Watch', idle:'Open', queue:'In line'}[o.s];
  return ['done', 'dropped', 'superseded'].includes(t.status) ? '' : 'Start';
}
// Which sessions a list (or a chip group) holds. Needs you wins over pinned; pinned is taken out of the counts.
function liveBarIn(o, l) {
  const w = o.s === 'wait';
  return l === 'wait' ? w : l === 'pin' ? o.pin && !w : !w && !o.pin && (l === 'more' || o.s === l);
}
// The open session without a ticket of a kind (state.sessions), or null: New goes to it instead of a second one.
function liveBarNewOpen(sessions, kind) {
  return (Array.isArray(sessions) ? sessions : []).find(x => x && x.kind === kind && x.open === true) || null;
}
// "1 session", "2 sessions"
function liveBarSessions(n) { return n + (n === 1 ? ' session' : ' sessions'); }
// The words of a count at a fold: "3 working", "Pinned (1)", "More (20)"; compact: the number alone.
function liveBarCountText(l, n, compact) {
  if (compact) return String(n);
  return l === 'pin' ? 'Pinned (' + n + ')' : l === 'more' ? 'More (' + n + ')' : n + ' ' + LIVEBAR_LISTS[l].word;
}

// The words of the "needs you" end of the bar: what is true for the person, not only for the live sessions. `total` is
// the one number of things waiting on them (Review badge: questions, results, changes), `sessions` those of it that
// are a live session. All calm only when nothing waits (ORCH-464).
function liveBarNeedText(total, sessions) {
  const n = Math.max(Number(total) || 0, Number(sessions) || 0);
  if (!n) return 'All calm';
  return n + (n === 1 ? ' needs you' : ' need you');
}

if (typeof module === 'object' && module.exports) {
  module.exports = {liveBarNeedText, liveBarModel, liveFocusVerb, liveBarIn, liveBarSessions, liveBarCountText, liveBarNewOpen, LIVEBAR_LISTS, LIVEBAR_NEW};
} else {
  (() => {
    const bar = {el:null, host:null, docked:false, end:null, panes:[], list:'', q:'', sig:'', fold:0, menu:false, busy:''};
    const liveAddon = () => array(state?.addons).find(a => a.page?.live_session === true) || null;
    const sessions = () => window.LiveSessions?.list || [];
    const groups = () => window.LiveSessions?.groups || [];
    const pins = () => { try { return JSON.parse(localStorage.getItem(LIVEBAR_PINS) || '[]'); } catch (e) { return []; } };
    const phone = () => window.matchMedia('(max-width: 720px)').matches;
    const link = (a, o) => '#addon/' + encodeURIComponent(a.name) + '/t/' + encodeURIComponent(o.id);
    const label = o => o.key || o.title;
    const needTotal = () => { try { return typeof needsYouTotal === 'function' ? needsYouTotal() : 0; } catch (e) { return 0; } };
    const sym = (s, text) => h('span', {className:'lbar-sym', 'data-s':s, 'aria-hidden':'true'}, text);

    function chip(a, o) {
      const open = (o.members || [o.id]).some(id => bar.panes.includes(id));
      return h('a', {className:'lbar-chip', href:link(a, o), 'data-s':o.s, 'data-key':'lbar-chip-' + (o.group || o.id), 'data-lbar-open':o.id,
        'aria-current':open ? 'true' : null, title:o.title + ' · ' + (o.group ? o.line : o.word)},
        sym(o.s, LIVEBAR_LISTS[o.s].sym), h('span', {}, label(o)), o.group ? h('span', {className:'lbar-n', 'aria-label':o.line}, String(o.n)) : null);
    }
    function count(all, l, compact) {
      const n = all.filter(o => liveBarIn(o, l)).length;
      if (!n) return null;
      const head = l === 'pin' ? iconEl('pinned') : l === 'more' ? null : sym(l, LIVEBAR_LISTS[l].sym);
      return h('button', {type:'button', className:'lbar-cnt', 'data-lbar-list':l, 'data-key':'lbar-cnt-' + l, 'aria-expanded':String(bar.list === l),
        'aria-haspopup':'true', 'aria-label':compact || l === 'pin' || l === 'more' ? LIVEBAR_LISTS[l].head + ': ' + liveBarSessions(n) : null},
        compact && l === 'more' ? iconEl('more') : head, h('span', {}, liveBarCountText(l, n, compact)), compact ? null : iconEl('up'));
    }
    function group(a, g, text, list) {
      return h('span', {className:'lbar-g', 'data-g':g, role:'group', 'aria-label':g === 'pin' ? 'Pinned' : text},
        h('span', {className:'lbar-l'}, g === 'pin' ? iconEl('pinned') : text), list.map(o => chip(a, o)));
    }
    function sessionsRow(a, all, fold) {
      if (fold >= 3) {
        const lists = fold >= 4 ? ['wait', 'more'] : ['wait', 'pin', 'run', 'queue', 'idle'];
        const counts = lists.map(l => count(all, l, true)).filter(Boolean);
        const total = needTotal(), seen = all.filter(o => liveBarIn(o, 'wait')).length;
        // things waiting on the person that are no live session: one orange count to Review, so the phone bar never reads calm
        if (total > seen) counts.unshift(h('a', {className:'lbar-cnt', href:'#review', 'data-s':'wait', 'data-key':'lbar-cnt-need', 'aria-label':liveBarNeedText(total, seen)},
          sym('wait', LIVEBAR_LISTS.wait.sym), h('span', {}, String(total))));
        return counts.length ? counts : [h('span', {className:'lbar-l'}, 'All calm')];
      }
      const need = all.filter(o => liveBarIn(o, 'wait')), pin = all.filter(o => liveBarIn(o, 'pin'));
      return [group(a, 'wait', liveBarNeedText(needTotal(), need.length), need),
        pin.length ? (fold >= 1 ? count(all, 'pin') : group(a, 'pin', '', pin)) : null,
        ...(fold >= 2 ? [count(all, 'more')] : ['run', 'queue', 'idle'].map(l => count(all, l)))].filter(Boolean);
    }
    function rows(a, all) {
      const q = bar.q.trim().toLowerCase();
      const list = all.filter(o => liveBarIn(o, bar.list) && (!q || (o.key + ' ' + o.title).toLowerCase().includes(q)));
      return list.length ? list.map(o => h('a', {className:'lbar-row', href:link(a, o), 'data-key':'lbar-row-' + o.id, 'data-lbar-open':o.id},
        h('span', {className:'lbar-st', 'data-s':o.s}, h('span', {className:'lbar-sym', 'aria-hidden':'true'}, LIVEBAR_LISTS[o.s].sym), o.word),
        h('span', {className:'lbar-key'}, o.key), h('span', {className:'lbar-rn'}, o.group ? o.title + ' · ' + o.line : o.title)))
        : [h('p', {className:'meta'}, 'No session matches.')];
    }
    function pop(a, all) {
      if (!bar.list) return null;
      const n = all.filter(o => liveBarIn(o, bar.list)).length;
      if (!n) { bar.list = ''; bar.q = ''; return null; }
      const head = LIVEBAR_LISTS[bar.list].head;
      return h('div', {className:'lbar-pop', role:'dialog', 'aria-label':head, 'data-key':'lbar-pop'},
        h('p', {className:'lbar-pop-h'}, head + ' (' + n + ')'),
        n >= LIVEBAR_SEARCH_FROM ? h('input', {className:'input', type:'search', placeholder:'Search these sessions', 'aria-label':'Search these sessions',
          autocomplete:'off', value:bar.q, 'data-lbar-q':'1'}) : null,
        h('div', {className:'lbar-list', 'data-lbar-rows':'1'}, rows(a, all)));
    }
    // New (draft D): a session without a ticket. One that is open already is offered as "go to it".
    function newMenu() {
      return h('div', {className:'live-pop', role:'group', 'aria-label':'New session without a ticket', 'data-key':'lbar-new-menu'},
        h('p', {className:'live-pop-h'}, 'New session without a ticket'),
        LIVEBAR_NEW.map(n => {
          const open = liveBarNewOpen(state.sessions, n.kind);
          return h('button', {type:'button', className:'live-opt', 'data-lbar-kind':n.kind, 'data-key':'lbar-new-' + n.kind,
            'aria-busy':bar.busy === n.kind ? 'true' : null, disabled:!!bar.busy},
          h('span', {className:'live-opt-t'}, h('strong', {}, n.title), h('span', {className:'meta'}, open ? 'Already open: go to it' : n.what)));
        }));
    }
    function newButton(fold) {
      const tiny = fold >= 3;
      return h('span', {className:'live-end', 'data-key':'lbar-new-wrap'},
        h('button', {type:'button', className:'btn sm ghost', 'data-lbar-new':'1', 'data-key':'lbar-new', 'aria-expanded':String(bar.menu),
          'aria-haspopup':'true', 'aria-label':tiny ? 'New session without a ticket' : null, title:'New session without a ticket'},
        iconEl('plus'), tiny ? null : h('span', {className:'live-word'}, 'New')),
        bar.menu ? newMenu() : null);
    }
    function build(a, all, fold) {
      return h('div', {id:'live-bar', className:bar.docked ? 'lbar lbar-docked' : 'lbar', role:'group', 'aria-label':addonLabel(a) + ' bar', 'data-fold':String(fold)},
        h('a', {className:'lbar-home', href:'#addon/' + encodeURIComponent(a.name), 'data-key':'lbar-home', title:addonLabel(a) + ' start page'}, addonLabel(a)),
        h('nav', {className:'lbar-sw', 'aria-label':'Sessions'}, sessionsRow(a, all, fold)),
        h('span', {className:'lbar-end'}, newButton(fold), typeof bar.end === 'function' ? bar.end() : null),
        pop(a, all));
    }
    // Opens the session in the layer when there is one, else its page (a chip's link).
    function openSession(a, id) {
      if (typeof window.LiveLayer?.open === 'function') window.LiveLayer.open(id);
      else location.hash = link(a, {id});
    }
    // The one start path (core `orch session new`); the new one is pinned (pins stay in this browser until orch keeps
    // them) and opens in the layer. One already open is only opened.
    async function startNew(kind) {
      const a = liveAddon();
      if (!a || bar.busy) return;
      const open = liveBarNewOpen(state.sessions, kind);
      if (open) { bar.menu = false; paint(true); openSession(a, open.id); return; }
      bar.busy = kind; paint(true);
      const r = await act('session.new', {kind});
      bar.busy = '';
      const made = r.ok ? liveBarNewOpen(state.sessions, kind) : null;
      bar.menu = !made && !r.ok;
      if (made) {
        try { const p = pins(); if (!p.includes(made.id)) localStorage.setItem(LIVEBAR_PINS, JSON.stringify([...p, made.id])); } catch (e) { /* private window */ }
        window.dispatchEvent(new CustomEvent('orch:live-pins', {detail:{key:made.id, pinned:true}}));
        await window.LiveSessions?.refresh?.();  // the bar and the panes read the sessions API: show it now
      }
      paint(true);
      if (made) openSession(a, made.id);
      else window.orch?.toast?.(r.ok ? 'It did not start. Try again.' : (r.text || 'It did not start.'), 'error');
    }
    window.LiveNew = {start: startNew, kinds: LIVEBAR_NEW};
    function place() {
      const el = bar.el; if (!el) return;
      const tab = document.getElementById('tabbar');
      el.style.setProperty('--lbar-bottom', tab && tab.offsetHeight ? tab.offsetHeight + 'px' : '0px');
      const p = el.querySelector('.lbar-pop'), b = bar.list && el.querySelector('[data-lbar-list="' + bar.list + '"]');
      if (p && b) {
        const x = b.getBoundingClientRect().left - el.getBoundingClientRect().left;
        p.style.left = Math.max(8, Math.min(x, el.clientWidth - p.offsetWidth - 8)) + 'px';
      }
    }
    function paint(force) {
      const a = liveAddon(), on = typeof livePreviewOn === 'function' && livePreviewOn() && !!a;
      // the place that outlives a page change when the dashboard has one ([data-keep]), else the end of .shell-body
      const host = bar.host?.isConnected ? bar.host : document.querySelector('.shell-body [data-keep]') || document.querySelector('.shell-body');
      if (!on || !host) {
        if (bar.el) { bar.el.remove(); bar.el = null; bar.sig = ''; }
        delete document.body.dataset.liveBar;
        return;
      }
      window.LiveSessions?.sync();
      if (!window.LiveSessions?.ready && !bar.el) return;  // no "All calm" flash before the first answer
      const all = liveBarModel(sessions(), pins(), groups());
      const sig = JSON.stringify([a.name, addonLabel(a), all, state.sessions, bar.list, bar.menu, bar.busy, bar.panes, bar.docked, phone(), window.innerWidth, needTotal()]);
      if (!force && sig === bar.sig && bar.el?.parentNode === host) return;
      bar.sig = sig;
      const active = document.activeElement, focusKey = bar.el?.contains(active) ? (active.dataset.key || (active.dataset.lbarQ ? 'q' : '')) : '';
      const caret = focusKey === 'q' ? active.selectionStart : null;
      let fold = phone() ? 3 : 0, el = build(a, all, fold);
      if (bar.el) bar.el.replaceWith(el); else host.append(el);
      if (el.parentNode !== host) host.append(el);
      bar.el = el;
      for (let sw = el.querySelector('.lbar-sw'); fold < 4 && sw.scrollWidth > sw.clientWidth + 1; sw = el.querySelector('.lbar-sw')) {
        const next = build(a, all, ++fold); el.replaceWith(next); el = bar.el = next;
      }
      bar.fold = fold;
      document.body.dataset.liveBar = '1';
      place();
      if (focusKey) {
        const t = focusKey === 'q' ? el.querySelector('[data-lbar-q]') : el.querySelector('[data-key="' + focusKey + '"]');
        if (t) { t.focus(); if (caret != null) t.setSelectionRange(caret, caret); }
      }
    }
    function toggle(l) {
      bar.list = bar.list === l ? '' : l; bar.q = '';
      paint(true);
      const q = bar.el?.querySelector('[data-lbar-q]');
      if (q) q.focus(); else bar.el?.querySelector('.lbar-row')?.focus();
    }
    function close(back) {
      if (!bar.list) return;
      const l = bar.list; bar.list = ''; bar.q = ''; paint(true);
      if (back) bar.el?.querySelector('[data-lbar-list="' + l + '"]')?.focus();
    }
    document.addEventListener('click', e => {
      const nb = e.target.closest?.('[data-lbar-new]');
      if (nb && bar.el?.contains(nb)) {
        bar.menu = !bar.menu; bar.list = ''; bar.q = ''; paint(true);
        if (bar.menu) bar.el?.querySelector('[data-lbar-kind]')?.focus();
        return;
      }
      const k = e.target.closest?.('[data-lbar-kind]');
      if (k && bar.el?.contains(k)) { startNew(k.dataset.lbarKind); return; }
      if (bar.menu && !bar.el?.querySelector('[data-key="lbar-new-wrap"]')?.contains(e.target)) { bar.menu = false; paint(true); }
      const b = e.target.closest?.('[data-lbar-list]');
      if (b && bar.el?.contains(b)) { toggle(b.dataset.lbarList); return; }
      // with the layer there, a chip or row opens its session in the layer instead of changing page
      const o = e.target.closest?.('[data-lbar-open]');
      if (o && bar.el?.contains(o) && typeof window.LiveLayer?.open === 'function' && !e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) {
        e.preventDefault(); close(false); window.LiveLayer.open(o.dataset.lbarOpen); return;
      }
      if (bar.list && (!bar.el?.contains(e.target) || e.target.closest('a'))) close(false);
    });
    document.addEventListener('input', e => {
      if (!e.target.matches?.('[data-lbar-q]') || !bar.el?.contains(e.target)) return;
      bar.q = e.target.value;
      const a = liveAddon(), box = bar.el.querySelector('[data-lbar-rows]');
      if (a && box) box.replaceChildren(...rows(a, liveBarModel(sessions(), pins(), groups())));
    });
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape' || !bar.el?.contains(document.activeElement)) return;
      if (bar.menu) { e.stopPropagation(); bar.menu = false; paint(true); bar.el?.querySelector('[data-lbar-new]')?.focus(); }
      else if (bar.list) { e.stopPropagation(); close(true); }
    }, true);
    // the layer says which sessions are open ({mode, panes: ticket ids}); their chips are marked current
    window.addEventListener('orch:live-sessions', () => paint());
    window.addEventListener('orch:live-layer', e => { const p = e.detail?.panes; bar.panes = Array.isArray(p) ? p.map(String) : []; paint(); });
    let frame = 0;
    window.addEventListener('resize', () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => paint(true)); });
    window.paintLiveBar = paint;
    window.LiveBar = {
      // Move the bar into another host (a mount point that survives page changes); it stays the same element.
      // docked: the host places it (the layer's dock), so it is not fixed to the bottom of the window.
      mount(host, opts = {}) { bar.host = host || null; bar.docked = !!(host && opts.docked); if (bar.el && host) host.append(bar.el); paint(true); },
      // The buttons at the right end (the layer's Open and Place): fn returns nodes, called on every repaint.
      end(fn) { bar.end = typeof fn === 'function' ? fn : null; paint(true); },
      repaint() { paint(true); },
      model: liveBarModel,
    };
  })();
}

'use strict';
// The new live page (draft D, ORCH-261), behind the Preview switch on the settings page of the add-on whose page has
// live sessions (one setting in the core config). Off, the default: that add-on's addresses show its own page,
// exactly as before. On: the same addresses show this page: the wall of every session (pages/livewall.js), with the
// bar and the layer under every page. The dashboard names no add-on: the page is found by its live_session capability.
function livePreviewOn() {
  return !snapshot && state?.settings?.focus_preview_on === true;
}
function livePageOf(id) {
  return addons().find(a => a.name === id && a.page?.live_session === true) || null;
}
// Sessions without a ticket (ORCH-364): the four New buttons at the top (the bar's New menu does the same,
// pages/livebar.js window.LiveNew) and the open ones, pinned first, until the wall shows them as tiles.
const liveWin = () => (typeof window === 'object' ? window : {});
const liveSessions = () => (typeof state === 'object' && state && Array.isArray(state.sessions) ? state.sessions : []);
function liveNewButtons() {
  const kinds = liveWin().LiveNew?.kinds || [];
  if (!kinds.length) return null;
  return h('div', {className:'actions', role:'group', 'aria-label':'New session without a ticket', 'data-key':'live-new'},
    kinds.map(n => {
      const open = typeof liveBarNewOpen === 'function' && liveBarNewOpen(liveSessions(), n.kind);
      return h('button', {type:'button', className:'btn outline sm', 'data-live-new':n.kind, 'data-key':'live-new-' + n.kind,
        title:open ? 'Already open: go to it' : n.what}, open ? null : iconEl('plus'), h('span', {}, n.title));
    }));
}
function liveNoTicketList(addon) {
  const open = liveSessions().filter(x => x && x.open === true);
  if (!open.length) return null;
  const all = typeof liveBarModel === 'function' ? liveBarModel(liveWin().LiveSessions?.list, []).filter(o => o.kind) : [];
  return h('section', {className:'card pad stack-sm', 'data-key':'live-no-ticket', 'aria-label':'Sessions without a ticket'},
    h('h2', {}, 'Sessions without a ticket (' + open.length + ')'),
    h('div', {className:'lbar-list'}, all.map(o => h('a', {className:'lbar-row', href:'#addon/' + encodeURIComponent(addon) + '/t/' + encodeURIComponent(o.id), 'data-live-open':o.id, 'data-key':'live-nt-' + o.id},
      h('span', {className:'lbar-st', 'data-s':o.s}, h('span', {className:'lbar-sym', 'aria-hidden':'true'}, typeof LIVEBAR_LISTS === 'object' ? LIVEBAR_LISTS[o.s]?.sym || '' : ''), o.word),
      h('span', {className:'lbar-key'}, ''), h('span', {className:'lbar-rn'}, o.title)))));
}
function liveNextPage(r) {
  const label = addonLabel(livePageOf(r.id));
  window.LiveSessions?.sync();
  return fragment(heading(label, '', {actions:h('span', {className:'badge info', 'data-key':'live-next-tag'}, 'Preview')}),
    liveNewButtons(),
    liveNoTicketList(r.id),
    h('section', {'data-key':'live-next', 'data-path':r.path || '', 'aria-label':'Sessions'}, liveWall()),
    h('p', {className:'meta'}, h('a', {href:'#settings/addons/' + encodeURIComponent(r.id), 'data-key':'live-next-off'}, 'Back to today’s ' + label)));
}
if (typeof document === 'object') document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-live-new]');
  if (b && typeof window.LiveNew?.start === 'function') { window.LiveNew.start(b.dataset.liveNew); return; }
  const o = e.target.closest?.('[data-live-open]');
  if (o && typeof window.LiveLayer?.open === 'function' && !e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) {
    e.preventDefault(); window.LiveLayer.open(o.dataset.liveOpen);
  }
});

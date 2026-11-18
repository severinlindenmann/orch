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
// pages/livebar.js window.LiveNew); the open ones show on the wall, pinned until unpinned (ORCH-361).
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
function liveNextPage(r) {
  const label = addonLabel(livePageOf(r.id));
  window.LiveSessions?.sync();
  return fragment(heading(label, '', {actions:h('span', {className:'badge info', 'data-key':'live-next-tag'}, 'Preview')}),
    liveNewButtons(),
    h('section', {'data-key':'live-next', 'data-path':r.path || '', 'aria-label':'Sessions'}, liveWall()),
    h('p', {className:'meta'}, h('a', {href:'#settings/addons/' + encodeURIComponent(r.id), 'data-key':'live-next-off'}, 'Back to today’s ' + label)));
}
// One ticket's address (#addon/<page>/t/<ticket>, as Home, a ticket page or an old link names it) with Preview on:
// the new page underneath and that ticket's session opened in the layer with the keyboard in it, so the address never
// shows less than today's page did (ORCH-465). Once per address: closed again, it stays closed until the address changes.
function liveAddressTicket(r) {
  const m = r && r.kind === 'live' ? /^t\/([A-Za-z0-9_-]{1,64})$/.exec(r.path || '') : null;
  return m ? m[1] : null;
}
let liveAddressOpened = '';
function liveOpenFromAddress(r, layer = liveWin().LiveLayer, known = typeof liveLayerSession === 'function' ? liveLayerSession : null) {
  const id = liveAddressTicket(r);
  if (!id) { liveAddressOpened = ''; return false; }
  if (liveAddressOpened === r.hash || typeof layer?.open !== 'function' || !known?.(id)) return false;  // not loaded yet: the next render tries again
  liveAddressOpened = r.hash;
  layer.open(id, true);
  return true;
}
if (typeof document === 'object') document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-live-new]');
  if (b && typeof window.LiveNew?.start === 'function') { window.LiveNew.start(b.dataset.liveNew); return; }
  const o = e.target.closest?.('[data-live-open]');
  if (o && typeof window.LiveLayer?.open === 'function' && !e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) {
    e.preventDefault(); window.LiveLayer.open(o.dataset.liveOpen);
  }
});

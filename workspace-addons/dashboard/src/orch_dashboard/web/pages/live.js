'use strict';
// The live page (draft D, ORCH-261; the only one since ORCH-816): the addresses of the add-on whose page has live sessions
// show this page: the wall of every session (pages/livewall.js), with the bar and the layer under every page. In
// a shared copy only its name and one line (it has no live sessions). The dashboard names no add-on: the page is found by its live_session capability.
function liveFocusOn() {
  return !snapshot;
}
function livePageOf(id) {
  return addons().find(a => a.name === id && a.page?.live_session === true) || null;
}
// Sessions without a ticket (ORCH-364): the four New buttons right of the wall's counts (livewall.js, ORCH-1568) (the bar's New menu does the same,
// pages/livebar.js window.LiveNew), on the tool and model of the Runs on row under them (ORCH-1617); the open ones show
// on the wall, pinned until unpinned (ORCH-361).
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
  const a = livePageOf(r.id), label = addonLabel(a);
  // One top (D1) with its one sentence and the add-on's Settings button (D6).
  const top = () => heading(label, a?.dashboard?.subtitle || '', {settings:typeof addonSettingsHref === 'function' ? addonSettingsHref(a?.name) : null});
  if (!liveFocusOn()) return fragment(top(), h('p', {className:'meta', 'data-key':'live-next-copy'}, 'Live sessions show only on the computer the helpers work on.'));
  window.LiveSessions?.sync();
  return fragment(top(),
    h('section', {'data-key':'live-next', 'data-path':r.path || '', 'aria-label':'Sessions'}, liveWall()));
}
// One ticket's address (#addon/<page>/t/<ticket>, as Home, a ticket page or an old link names it): the page
// underneath and that ticket's session opened in the layer with the keyboard in it (ORCH-465). Once per address: closed again, it stays closed until the address changes.
function liveAddressTicket(r) {
  const m = r && r.kind === 'live' ? /^t\/([A-Za-z0-9_-]{1,64})$/.exec(r.path || '') : null;
  return m ? m[1] : null;
}
let liveAddressOpened = '';
function liveOpenFromAddress(r, layer = liveWin().LiveLayer, known = typeof liveLayerSession === 'function' ? liveLayerSession : null, say = text => { const go = () => { location.hash = '#tickets'; }; go.label = 'Open Tickets'; liveWin().orch?.toast?.(text, 'error', go); }) {
  const id = liveAddressTicket(r);
  if (!id) { liveAddressOpened = ''; return false; }
  if (liveAddressOpened === r.hash || typeof layer?.open !== 'function') return false;
  if (!known?.(id)) {  // the tickets are loaded and this one is not among them: say so once (ORCH-677); else the next render tries again
    if (typeof state === 'object' && Array.isArray(state?.tickets) && state.tickets.length) { liveAddressOpened = r.hash; say('There is no ticket with this address. Find it on the Tickets page.'); }
    return false;
  }
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

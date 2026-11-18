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
function liveNextPage(r) {
  const label = addonLabel(livePageOf(r.id));
  window.LiveSessions?.sync();
  return fragment(heading(label, '', {actions:h('span', {className:'badge info', 'data-key':'live-next-tag'}, 'Preview')}),
    h('section', {'data-key':'live-next', 'data-path':r.path || '', 'aria-label':'Sessions'}, liveWall()),
    h('p', {className:'meta'}, h('a', {href:'#settings/addons/' + encodeURIComponent(r.id), 'data-key':'live-next-off'}, 'Back to today’s ' + label)));
}

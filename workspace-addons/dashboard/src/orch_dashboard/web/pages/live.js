'use strict';
// The new live page (draft D, ORCH-261), behind the Preview switch on the settings page of the add-on whose page has
// live sessions (one setting in the core config). Off, the default: that add-on's addresses show its own page,
// exactly as before. On: the same addresses show this page. It is an empty shell for now; the wall, the bar and the
// layer fill it in later tasks. The dashboard names no add-on: the page is found by its live_session capability.
function livePreviewOn() {
  return !snapshot && state?.settings?.focus_preview_on === true;
}
function livePageOf(id) {
  return addons().find(a => a.name === id && a.page?.live_session === true) || null;
}
function liveNextPage(r) {
  const label = addonLabel(livePageOf(r.id));
  return fragment(heading(label, '', {actions:h('span', {className:'badge info', 'data-key':'live-next-tag'}, 'Preview')}),
    h('section', {className:'card', 'data-key':'live-next', 'data-path':r.path || ''},
      h('div', {className:'empty'},
        h('p', {}, 'The new ' + label + ' is being built; your helpers’ sessions will show here.'),
        h('a', {className:'btn ghost sm', href:'#settings/addons/' + encodeURIComponent(r.id), 'data-key':'live-next-off'}, 'Back to today’s ' + label))));
}

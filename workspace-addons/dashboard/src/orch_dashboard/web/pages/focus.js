'use strict';
// The new Focus (draft D, ORCH-261), behind the Preview switch (Settings > Add-ons > Focus > Preview, `orch config
// set focus.preview on`). Off, the default: #addon/focus shows today's Focus page, exactly as before. On: the same
// addresses show this page. It is an empty shell for now; the wall, the bar and the layer fill it in later tasks.
function focusPreviewOn() {
  return !snapshot && state?.settings?.focus_preview_on === true;
}
function focusNextPage(r) {
  const label = addonLabel(addons().find(a => a.name === r.id)) || 'Focus';
  return fragment(heading(label, '', {actions:h('span', {className:'badge info', 'data-key':'focus-next-tag'}, 'Preview')}),
    h('section', {className:'card', 'data-key':'focus-next', 'data-path':r.path || ''},
      h('div', {className:'empty'},
        h('p', {}, 'The new ' + label + ' is being built. Your helpers’ sessions will show here.'),
        h('a', {className:'btn ghost sm', href:'#settings/addons/' + encodeURIComponent(r.id), 'data-key':'focus-next-off'}, 'Back to today’s ' + label))));
}

'use strict';
// Mockup of the workspace switcher (ORCH-1273): the page runs the product switcher (switcher.js, places.js) and hands
// it demo data the way the dashboard does (an orch:state event). ?state= picks what shows: menu (default), keep
// (places arrived in a link), empty (a fresh browser), add, share. Nothing leaves this page.
(() => {
  const state = new URLSearchParams(location.search).get('state') || 'menu';
  const P = window.OrchPlaces, t = Date.now(), day = 864e5;
  const demo = [
    {id: 'notebook0001', url: 'http://127.0.0.1:64381', kind: 'workspace', name: 'Notebook', color: 'blue', changed: t, opened: t - day},
    {id: 'fernscout001', url: 'https://fs.office.example.ch', kind: 'workspace', name: 'Fernscout', color: 'teal', changed: t, opened: t - 3 * day},
    {id: 'kunden000001', url: 'http://10.20.0.14:8790', kind: 'workspace', name: 'Kunden-Support', color: 'amber', changed: t},
    {id: 'relay0000001', url: 'https://relay.example.ch/admin', kind: 'relay', name: 'Relay', changed: t, opened: t - day},
    {id: 'publish00001', url: 'https://publish.example.ch/admin', kind: 'publish', name: 'Publish', changed: t, opened: t - 14 * day},
  ];
  try { localStorage.removeItem(P.KEY); sessionStorage.removeItem(P.INCOMING); } catch (_) { /* a preview without storage */ }
  if (state !== 'empty') P.save(null, P.tidy(demo, t), t);
  if (state === 'keep') {
    try {
      sessionStorage.setItem(P.INCOMING, P.pack([
        {id: 'pilatus00001', url: 'https://pilatus.example.ch', kind: 'workspace', name: 'Pilatus', color: 'orange', changed: t},
        {id: 'lab000000001', url: 'https://lab.internal.example.ch', kind: 'workspace', name: 'Lab', color: 'violet', changed: t}], t));
    } catch (_) { /* a preview without storage */ }
  }
  window.dispatchEvent(new CustomEvent('orch:state', {detail: {workspace: 'Orch development', look: {
    icon: null, color: 'teal', place_id: 'ws_' + 'a1b2c3d4e5f6a7b8c9d0e1f2',
    workspaces: [
      {name: 'Orch development', here: true, needs: 2, url: 'http://127.0.0.1:8786/'},
      {name: 'Marketing', needs: 0, url: null},
    ]}}}));
  // links in the menu stay on this page
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('.sw-menu a');
    if (a) { e.preventDefault(); e.stopImmediatePropagation(); window.UI && UI.toast('Opens ' + a.getAttribute('href')); }
  }, true);
  // on a phone the switcher sits in the side menu (More): show it open, as after a tap on More
  if (matchMedia('(max-width:720px)').matches) document.querySelector('.sidebar')?.setAttribute('data-open', 'true');
  const open = () => document.querySelector('.workspace.ws-switch').click();
  open();
  if (state === 'add') document.querySelector('[data-testid=ws-add]')?.click();
  if (state === 'share') document.querySelector('[data-testid=ws-share]')?.click();

  const bar = document.createElement('div');
  bar.className = 'preview-controls';
  bar.setAttribute('aria-label', 'Preview controls');
  const label = document.createElement('span');
  label.textContent = 'Preview controls';
  bar.append(label);
  for (const [key, text] of [['menu', 'Menu'], ['keep', 'From a link'], ['add', 'Add place'], ['share', 'Share'], ['empty', 'Empty']]) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = text;
    if (key === state) b.setAttribute('aria-pressed', 'true');
    b.onclick = () => { location.search = '?state=' + key; };
    bar.append(b);
  }
  document.body.append(bar);
})();

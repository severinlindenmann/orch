/* ORCH-1494 mockup: draws a sample partner-directory page as the helper's screen picture and fills the kit's live
   preview (UI.browserPeek) and live view (UI.browserView) hosts of these pages. Hosts: [data-mk-peek="live|open|wide|ended"],
   [data-mk-view]. The real pages get the pictures from the browser add-on's stream. */
(() => {
  const UI = window.UI;
  if (!UI || !UI.browserView) return;
  function picture() {
    const c = document.createElement('canvas'); c.width = 1280; c.height = 800;
    const g = c.getContext('2d');
    const css = getComputedStyle(document.documentElement), tok = n => css.getPropertyValue(n).trim();
    const paper = tok('--paper'), ink = tok('--ink'), line = tok('--border-strong'), soft = tok('--success-soft'), good = tok('--success');
    g.fillStyle = paper; g.fillRect(0, 0, 1280, 800);
    g.fillStyle = ink; g.font = '600 26px sans-serif'; g.fillText('Office Partners Directory', 64, 56);
    g.fillStyle = ink; g.font = '19px sans-serif'; ['Find a partner', 'About', 'Contact'].forEach((t, i) => g.fillText(t, 820 + i * 150, 56));
    g.fillStyle = line; g.fillRect(0, 90, 1280, 1);
    g.fillStyle = ink; g.font = '600 40px sans-serif'; g.fillText('Find a partner', 64, 170);
    g.fillStyle = ink; g.font = '21px sans-serif'; g.fillText('Small offices near you, checked by us every year.', 64, 215);
    g.strokeStyle = line; g.strokeRect(64, 245, 480, 50); g.fillStyle = ink; g.fillText('Weber & Frei', 80, 278);
    const rows = [['Weber & Frei', 'Bookkeeping', 'Bahnhofstrasse 12, Zurich'], ['Brunner Office Supply', 'Paper, toner, furniture', 'Seestrasse 4, Thalwil'], ['Keller IT', 'Computers and networks', 'Marktgasse 9, Bern']];
    g.fillStyle = ink; g.font = '600 19px sans-serif'; ['Name', 'What they do', 'Address'].forEach((t, i) => g.fillText(t, 76 + i * 380, 360));
    rows.forEach((r, j) => { g.fillStyle = line; g.fillRect(64, 380 + j * 64, 1152, 1); g.fillStyle = ink; g.font = '19px sans-serif'; r.forEach((t, i) => g.fillText(t, 76 + i * 380, 420 + j * 64)); g.fillStyle = soft; g.fillRect(1110, 398 + j * 64, 80, 30); g.fillStyle = good; g.font = '16px sans-serif'; g.fillText('Listed', 1126, 419 + j * 64); });
    return c.toDataURL('image/jpeg', 0.7).split(',')[1];
  }
  // ?pic=<a JPEG next to this page>: a real picture from the broker instead of the drawn one (for screenshots)
  const pic = new URLSearchParams(location.search).get('pic');
  if (pic && /^[\w./-]+\.jpg$/.test(pic) && !pic.includes('..')) {
    fetch(pic).then(r => r.arrayBuffer()).then(b => show(btoa(String.fromCharCode(...new Uint8Array(b))))).catch(() => show(picture()));
  } else show(picture());
  function show(jpeg) {
  const at = Date.now() / 1000 - 4;
  const tabs = [{title: 'Find a partner · Office Partners', url: 'https://office-partners.example/', current: true}];
  document.querySelectorAll('[data-mk-peek]').forEach(host => {
    const kind = host.dataset.mkPeek, p = UI.browserPeek({wide: kind === 'wide', onOpen() { const v = document.querySelector('[data-mk-open]'); if (v) location.href = v.dataset.mkOpen; }});
    host.append(p.el);
    if (kind === 'ended') { p.end({why: 'closed'}, Date.now() / 1000 - 1800); return; }
    p.hello({}); p.tabs(tabs); p.frame({jpeg, w: 1280, h: 800, at}); if (kind === 'open') p.open(true);
    p.el.__peek = p;
  });
  // ORCH-1495 take over: ?state=asks | finishing | you | back | paused (the owner states of the live view and preview)
  const mk = new URLSearchParams(location.search).get('state') || '';
  const CTL = {asks: {state: 'helper', asking: 'Please sign in to the partner site, then give it back.'}, finishing: {state: 'finishing', mine: true},
    you: {state: 'person', mine: true, sites: ['partner.example']}, back: {state: 'person', mine: true, sites: ['partner.example'], send_site: 'partner.example'}, paused: {state: 'paused'}}[mk] || {state: 'helper'};
  let view = null;
  const ok = async () => ({ok: true});
  const control = {take: async () => { if (view) view.control({state: 'finishing', mine: true}); setTimeout(() => view && view.control({state: 'person', mine: true, sites: ['partner.example']}), 1500); return {ok: true}; },
    give: async () => { if (view) view.control({state: 'helper'}); return {ok: true, text: 'Given back to the helper.'}; }, cancel: ok, send: ok,
    allowSends: async site => { if (view) view.control({state: 'person', mine: true, sites: ['partner.example'], send_site: site || undefined}); return {ok: true}; }};
  document.querySelectorAll('[data-mk-peek]').forEach(host => { const p = host.lastChild && host.lastChild.__peek; if (p) p.control(CTL); });
  document.querySelectorAll('[data-mk-view]').forEach(host => {
    const v = UI.browserView({label: 'The helper’s browser', onStop: async () => ({ok: true}), onHide() { history.back(); }, control});
    view = v;
    host.append(v.el); v.hello({generation: '0123456789abcdef'}); v.tabs(tabs); v.frame({jpeg, w: 1280, h: 800, at});
    v.control(CTL);
    if (mk === 'back') { const b = [...v.el.querySelectorAll('.bview-ctl-acts .btn')].find(x => x.textContent === 'Back to the ticket'); if (b) b.click(); }
  });
  }
})();

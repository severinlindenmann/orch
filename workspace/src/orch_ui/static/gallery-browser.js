// Gallery: the helper's browser, live (UI.browserView, browser.js, ORCH-1493). A drawn sample page stands in for the
// broker's screen pictures.
(() => {
  'use strict';
  const UI = window.UI;
  if (!UI || !UI.browserView) return;
  function samplePicture(title) {
    const c = document.createElement('canvas');
    c.width = 1280; c.height = 800;
    const g = c.getContext('2d');
    const css = getComputedStyle(document.documentElement);
    g.fillStyle = css.getPropertyValue('--surface').trim() || '#fff'; g.fillRect(0, 0, 1280, 800);
    g.fillStyle = css.getPropertyValue('--text').trim() || '#111'; g.font = '600 48px sans-serif';
    g.fillText(title, 80, 140);
    g.font = '28px sans-serif'; g.fillText('Monday to Friday, 9 to 17. Saturday 9 to 13.', 80, 220);
    return c.toDataURL('image/jpeg', 0.6).split(',')[1];
  }
  const now = () => Date.now() / 1000;
  const put = (id, setup) => { const host = document.getElementById(id); if (!host) return; const v = UI.browserView({label: 'The helper’s browser', onStop: async () => ({ok: true})}); host.append(v.el); setup(v); };
  const tabs = [{title: 'Opening hours · Café Linde', url: 'https://cafe-linde.example/hours', current: true}, {title: 'Menu', url: 'https://cafe-linde.example/menu'}];
  put('bview-live', v => { v.hello({generation: '0123456789abcdef'}); v.tabs(tabs); v.frame({jpeg: samplePicture('Opening hours'), w: 1280, h: 800, at: now()}); });
  put('bview-event', v => { v.hello({generation: '0123456789abcdef'}); v.tabs(tabs.slice(0, 1)); v.event({text: 'The page showed a message and it was closed. The message:', site_text: 'Accept cookies?'}); v.frame({jpeg: samplePicture('Menu'), w: 1280, h: 800, at: now() - 45}); });
  put('bview-lost', v => { v.hello({generation: '0123456789abcdef'}); v.frame({jpeg: samplePicture('Opening hours'), w: 1280, h: 800, at: now()}); v.show('lost'); });
  put('bview-ended', v => { v.end({why: 'Closed after 15 minutes without a command.', final: true}); });
  put('bview-none', v => { v.end({why: 'No browser is open for this ticket.', final: false}); });
  // ORCH-1494: the small live preview and the view next to the steps
  const site = [{title: 'Find a partner', url: 'https://office-partners.example/find', current: true}];
  const peek = (id, setup, wide, compact) => { const host = document.getElementById(id); if (!host || !UI.browserPeek) return; const p = UI.browserPeek({onOpen() {}, wide, compact}); host.append(p.el); setup(p); };
  peek('bpeek-live', p => { p.hello({}); p.tabs(site); p.frame({jpeg: samplePicture('Find a partner'), w: 1280, h: 800, at: now()}); });
  peek('bpeek-open', p => { p.hello({}); p.tabs(site); p.frame({jpeg: samplePicture('Find a partner'), w: 1280, h: 800, at: now()}); p.open(true); });
  peek('bpeek-wide', p => { p.hello({}); p.tabs(site); p.frame({jpeg: samplePicture('Find a partner'), w: 1280, h: 800, at: now()}); }, true);
  peek('bpeek-compact', p => { p.hello({}); p.tabs(site); p.frame({jpeg: samplePicture('Find a partner'), w: 1280, h: 800, at: now()}); }, false, true);
  peek('bpeek-ended', p => { p.end({why: 'closed'}, now() - 600); });
  // ORCH-1495: take over and give back. The calls answer at once here; a real page posts to /api/browse/*.
  const ctl = {take: async () => ({ok: true}), give: async () => ({ok: true, text: 'Given back to the helper.'}), cancel: async () => ({ok: true}), send: async () => ({ok: true})};
  const signin = [{title: 'Sign in · Supplier portal', url: 'https://portal.supplier.example/sign-in', current: true}];
  const take = (id, state) => { const host = document.getElementById(id); if (!host) return null; const v = UI.browserView({label: 'The helper’s browser', onStop: async () => ({ok: true}), control: ctl}); host.append(v.el); v.hello({generation: '0123456789abcdef'}); v.tabs(signin); v.frame({jpeg: samplePicture('Sign in to the customer portal'), w: 1280, h: 800, at: now()}); v.control(state); return v; };
  take('bview-take', {state: 'helper', epoch: 1, mine: false});
  take('bview-asks', {state: 'helper', epoch: 1, mine: false, asking: 'Please sign in to the supplier portal, then give it back.'});
  take('bview-finishing', {state: 'finishing', epoch: 2, mine: true});
  const you = take('bview-you', {state: 'person', epoch: 3, mine: true});
  if (you) { const back = [...you.el.querySelectorAll('.bview-ctl-acts .btn')].find(b => b.textContent === 'Back to the ticket'); if (back) back.click(); }  // the gallery shows it in place, not over the page
  take('bview-paused', {state: 'paused', epoch: 4, mine: false});
  take('bview-other', {state: 'person', epoch: 5, mine: false});
  peek('bpeek-asks', p => { p.hello({}); p.tabs(signin); p.frame({jpeg: samplePicture('Sign in'), w: 1280, h: 800, at: now()}); p.control({state: 'helper', asking: 'Please sign in to the supplier portal'}); });
  const beside = document.getElementById('bview-beside');
  if (beside) { const v = UI.browserView({label: 'The helper’s browser', onStop: async () => ({ok: true}), onHide() {}}); beside.append(v.el); v.hello({generation: '0123456789abcdef'}); v.tabs(site); v.frame({jpeg: samplePicture('Find a partner'), w: 1280, h: 800, at: now()}); }
})();

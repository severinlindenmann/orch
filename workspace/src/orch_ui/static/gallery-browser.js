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
})();

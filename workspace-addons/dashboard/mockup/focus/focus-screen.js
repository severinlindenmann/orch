// Focus mockup: the helper's screen as a strip above the message box and as a "Screen" tab (#692). Demo only.
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const dock = $('#mk-dock'), terminal = $('#terminal'), screen = $('#mk-screen'), tabs = [...document.querySelectorAll('[data-mk-tab]')];
  if (!dock || !terminal || !screen) return;
  const setOpen = open => { dock.classList.toggle('peek', !open); dock.querySelector('[data-mk-toggle]').setAttribute('aria-expanded', String(open)); try { localStorage.setItem('focus-mock-screen', open ? 'open' : 'peek'); } catch (e) { /* not kept */ } };
  let saved = ''; try { saved = localStorage.getItem('focus-mock-screen') || ''; } catch (e) { /* none */ }
  setOpen(saved === 'open');
  const pick = name => { tabs.forEach(t => t.setAttribute('aria-selected', String(t.dataset.mkTab === name))); terminal.hidden = name === 'screen'; screen.hidden = name !== 'screen'; dock.hidden = name === 'screen'; };
  tabs.forEach(t => t.addEventListener('click', () => pick(t.dataset.mkTab)));
  dock.querySelector('.session-dock-h').addEventListener('click', e => { if (!e.target.closest('button,label,input')) setOpen(dock.classList.contains('peek')); });
  dock.querySelector('[data-mk-toggle]').addEventListener('click', e => { e.stopPropagation(); setOpen(dock.classList.contains('peek')); });
  dock.querySelector('[data-mk-whole]').addEventListener('click', e => { e.stopPropagation(); pick('screen'); });
  document.addEventListener('keydown', e => { if (e.ctrlKey && e.key === '`' && !dock.hidden) { e.preventDefault(); setOpen(dock.classList.contains('peek')); } });
})();

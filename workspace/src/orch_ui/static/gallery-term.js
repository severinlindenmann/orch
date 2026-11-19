/* gallery.html: the terminal section (term.js, UI.term). Demo screens only, nothing here is product data and no key
   leaves the page: typing into the demo writes the keys under it. States: watching, typing, loading, typing off by
   setting, closed. */
(() => {
  'use strict';
  const q = s => document.querySelector(s);
  const E = '\x1b[';
  const SCREEN = [
    E + '1m⏺ ' + E + '0mI ran the tests for the export.',
    '  ' + E + '32m✔' + E + '0m counts skills per day ' + E + '2m(41 ms)' + E + '0m',
    '  ' + E + '32m✔' + E + '0m empty workspace shows zero ' + E + '2m(6 ms)' + E + '0m',
    '  ' + E + '31m✖' + E + '0m week view adds up to the day view',
    '',
    E + '33m⏺ ' + E + '0mFixing the week total next.',
    '',
    E + '7m> ' + E + '0m'
  ].join('\n');
  const live = (more) => Object.assign({state: 'live', screen: SCREEN, cx: 2, cy: 7, cols: 80, rows: 24, cursor: true, typing_allowed: true}, more || {});
  function demo(where, snap, after) {
    const host = q(where);
    if (!host || !window.UI || !window.UI.term) return;
    const said = document.createElement('p');
    said.className = 'meta';
    const ui = window.UI.term({label: 'ORCH-228', onKeys: async items => { said.textContent = 'Would send: ' + JSON.stringify(items); return {ok: true}; }, onSize: () => {}});
    host.append(ui.el, said);
    if (snap) ui.update(snap); else ui.show('loading');
    if (after) after(ui);
  }
  document.addEventListener('DOMContentLoaded', () => {
    demo('#term-watch', live());
    demo('#term-typing', live(), ui => ui.setTyping(true));
    demo('#term-loading', null);
    demo('#term-off', live({typing_allowed: false}));
    demo('#term-closed', live(), ui => ui.update({state: 'none'}));
  });
})();

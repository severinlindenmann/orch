/* gallery.html: the terminal section (term.js, UI.term). Demo screens only, nothing here is product data and no key
   leaves the page: typing into the demo shows what would be sent under it. States: watching, typing, loading, typing
   off by setting, closed. */
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
  ].join('\r\n');
  const b64 = s => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
  function demo(where, allowed, after) {
    const host = q(where);
    if (!host || !window.UI || !window.UI.term) return;
    const said = document.createElement('p');
    said.className = 'meta';
    const ui = window.UI.term({label: 'ORCH-228', onInput: async data => { said.textContent = 'Would send: ' + JSON.stringify(data); return {ok: true}; }, onSize: () => {}});
    host.append(ui.el, said);
    if (allowed === null) { ui.show('loading'); return; }
    ui.hello({typing_allowed: allowed});
    ui.screen({cols: 64, rows: 9, data: b64(SCREEN)});
    if (after) after(ui);
  }
  document.addEventListener('DOMContentLoaded', () => {
    demo('#term-watch', true);
    demo('#term-typing', true, ui => ui.setTyping(true));
    demo('#term-loading', null);
    demo('#term-off', false);
    demo('#term-closed', true, ui => ui.end('none'));
  });
})();

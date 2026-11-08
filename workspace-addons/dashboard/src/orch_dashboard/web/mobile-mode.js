'use strict';
// Mobile mode: the switch in the top bar, the first-click question, the bar on every page, the Settings choice.
// All data comes from state.mobile_mode (the relay add-on, via the server); null = the add-on is off, nothing shows.
// app.js hands over each new state (event "orch:state") and the act function (window.orchAct).
(() => {
  const ASK_OFF_KEY = 'orch.mobileMode.dontAsk';
  const HOURS = [4, 8, 12, 24];
  let mm = null, busy = false, asking = false;
  const bar = document.getElementById('mm-bar');
  const toggle = document.getElementById('mm-toggle');
  const store = {
    get: () => { try { return localStorage.getItem(ASK_OFF_KEY) === '1'; } catch (_) { return false; } },
    set: on => { try { on ? localStorage.setItem(ASK_OFF_KEY, '1') : localStorage.removeItem(ASK_OFF_KEY); } catch (_) { /* no storage: ask every time */ } },
  };
  const hm = iso => {
    const d = iso ? new Date(iso) : null;
    return d && !Number.isNaN(d.getTime()) ? d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'}) : '';
  };
  const node = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'className') n.className = v;
      else n.setAttribute(k, v === true ? '' : String(v));
    }
    n.append(...kids.flat().filter(x => x != null && x !== false));
    return n;
  };
  const btn = (text, cls, action, testid, extra = {}) =>
    node('button', {type: 'button', className: 'btn ' + cls, 'data-mm': action, 'data-testid': testid, disabled: busy, ...extra}, text);

  function paintBar() {
    bar.replaceChildren();
    if (!mm) { bar.hidden = true; return; }
    if (mm.on) {
      const warn = mm.awake === 'could_not_keep_awake';
      const parts = warn
        ? [node('b', {}, 'Mobile mode is on.'), ' Could not keep this computer awake. Mobile mode may stop when it sleeps.']
        : [node('b', {}, 'Mobile mode is on'), node('span', {className: 'meta mm-desc'}, ' · questions also go to your phone · computer stays awake'),
            node('span', {className: 'meta mm-when'}, (mm.since ? ' · since ' + hm(mm.since) : '') + (mm.ends_at ? ' · ends at ' + hm(mm.ends_at) : ''))];
      bar.className = 'mm-bar banner live' + (warn ? ' attn' : '');
      bar.setAttribute('data-testid', 'mobile-mode-bar');
      bar.append(node('span', {className: 'mm-pulse', 'aria-hidden': 'true'}), node('div', {className: 'grow'}, ...parts),
        btn('Turn off', 'outline sm', 'off', 'mobile-mode-bar-off'));
      bar.hidden = false;
    } else if (asking) {
      bar.className = 'mm-bar banner';
      bar.setAttribute('data-testid', 'mobile-mode-ask');
      const dont = node('input', {type: 'checkbox', id: 'mm-dont', 'data-testid': 'mobile-mode-dont-ask'});
      bar.append(node('div', {className: 'grow'},
        node('h3', {}, 'Turn on Mobile mode?'),
        node('p', {className: 'meta'}, 'Questions from your agents also go to your phone, and this computer stays awake until you turn it off. Closing the lid of a laptop still puts it to sleep.'),
        node('div', {className: 'mm-actions'}, btn('Turn on', 'primary sm', 'confirm', 'mobile-mode-confirm'), btn('Cancel', 'ghost sm', 'cancel', 'mobile-mode-cancel'),
          node('label', {className: 'mm-chk', for: 'mm-dont'}, dont, "Don't ask again"))));
      bar.hidden = false;
    } else if (mm.ended && mm.ended.text) {
      bar.className = 'mm-bar banner';
      bar.setAttribute('data-testid', 'mobile-mode-ended');
      bar.append(node('div', {className: 'grow'}, mm.ended.text), btn('OK', 'outline sm', 'ack', 'mobile-mode-ended-ok'));
      bar.hidden = false;
    } else bar.hidden = true;
    toggle.hidden = false;
    toggle.setAttribute('aria-checked', mm.on ? 'true' : 'false');
    toggle.disabled = busy;
  }

  function paint() {
    if (!mm) { toggle.hidden = true; bar.hidden = true; return; }
    paintBar();
  }

  async function call(op, args) {
    if (busy || typeof window.orchAct !== 'function') return;
    busy = true; paint();
    const r = await window.orchAct(op, args);
    busy = false;
    if (!r.ok) window.orch?.toast(r.text || 'That did not work.', 'error');
    paint();
    return r;
  }

  async function turnOn() { asking = false; await call('mobile.set', {on: true}); }

  document.addEventListener('click', async event => {
    const t = event.target.closest('#mm-toggle,[data-mm],[data-mm-hours]');
    if (!t || !mm) return;
    if (t.id === 'mm-toggle') {
      if (mm.on) await call('mobile.set', {on: false});
      else if (store.get()) await turnOn();
      else { asking = !asking; paint(); }
      return;
    }
    if (t.dataset.mmHours) { await call('mobile.hours', {hours: Number(t.dataset.mmHours)}); return; }
    switch (t.dataset.mm) {
      case 'confirm': store.set(!!document.getElementById('mm-dont')?.checked); await turnOn(); break;
      case 'cancel': asking = false; paint(); break;
      case 'off': await call('mobile.set', {on: false}); break;
      case 'ack': await call('mobile.ack', {}); break;
    }
  });

  window.addEventListener('orch:state', event => {
    mm = event.detail?.mobile_mode || null;
    if (mm?.on) asking = false;
    paint();
  });

  // The Settings > General block. app.js passes its own element builder `h`; the buttons are handled above.
  window.OrchMobileMode = {
    settingsSection(h) {
      if (!mm) return null;
      const choices = mm.hours_choices?.length ? mm.hours_choices : HOURS;
      return h('div', {className: 'stack', 'data-key': 'settings-mobile-mode'},
        h('h2', {className: 'set-sub'}, 'Mobile mode'),
        h('div', {className: 'card'}, h('div', {className: 'card-row'},
          h('div', {className: 'grow'}, h('p', {}, 'Switch off by itself after'),
            h('p', {className: 'meta'}, 'Mobile mode sends questions to your phone and keeps this computer awake.')),
          h('div', {className: 'mm-hours', role: 'radiogroup', 'aria-label': 'Mobile mode switches off after', 'data-testid': 'mobile-mode-hours'},
            choices.map(n => h('button', {type: 'button', className: 'btn sm ' + (n === mm.default_hours ? 'primary' : 'ghost'), role: 'radio',
              'aria-checked': n === mm.default_hours ? 'true' : 'false', 'data-mm-hours': n, 'data-key': 'mm-hours-' + n,
              'data-testid': 'mobile-mode-hours-' + n}, n + ' h'))))));
    },
  };
})();

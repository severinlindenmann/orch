'use strict';
// Mobile mode ("Send questions to my phone"): the switch in the menu, the first-click question, the bar on every page, the Settings choice.
// All data comes from state.mobile_mode (the relay add-on, via the server); null = the add-on is off, nothing shows.
// app.js hands over each new state (event "orch:state") and the act function (window.orchAct).
(() => {
  const ASK_OFF_KEY = 'orch.mobileMode.dontAsk';
  const HOURS = [4, 8, 12, 24];
  const NO_PHONE = 'Pair a phone first';
  let mm = null, busy = false, asking = false;
  const needsPhone = () => !!mm && !mm.on && mm.phones === 0;
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
      const ends = hm(mm.ends_at);
      const parts = [node('b', {}, 'Questions go to your phone' + (ends ? ' until ' + ends : '')),
        node('span', {className: 'mm-desc'}, warn
          ? 'Could not keep this computer awake. Questions may stop reaching your phone when it sleeps.'
          : 'This computer stays awake.')];
      bar.className = 'mm-bar banner live' + (warn ? ' attn' : '');
      bar.setAttribute('data-testid', 'mobile-mode-bar');
      bar.append(node('span', {className: 'mm-phone', 'aria-hidden': 'true'}), node('div', {className: 'grow'}, ...parts),
        btn('Turn off', 'outline sm', 'off', 'mobile-mode-bar-off'));
      bar.hidden = false;
    } else if (asking) {
      bar.className = 'mm-bar banner';
      bar.setAttribute('data-testid', 'mobile-mode-ask');
      const dont = node('input', {type: 'checkbox', id: 'mm-dont', 'data-testid': 'mobile-mode-dont-ask'});
      bar.append(node('div', {className: 'grow'},
        node('h3', {}, 'Send questions to your phone?'),
        node('p', {className: 'meta'}, 'Questions from your helpers also go to your phone, and this computer stays awake until you turn it off. Closing the lid of a laptop still puts it to sleep.'),
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
    // No phone paired yet: nothing to send to, so the switch cannot be turned on (it can always be turned off).
    const noPhone = needsPhone();
    toggle.disabled = busy || noPhone;
    toggle.title = noPhone ? NO_PHONE : '';
    const label = toggle.querySelector('.mm-label');
    if (label) label.textContent = noPhone ? NO_PHONE : 'Send questions to my phone';
  }

  function paint() {
    document.body.classList.toggle('mobile-mode-on', !!mm?.on);
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
    if (needsPhone() && (t.id === 'mm-toggle' || t.dataset.mm === 'switch')) return;
    if (t.id === 'mm-toggle' || t.dataset.mm === 'switch') {
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

  // The Settings > Phone & workspaces rows (pairing card): the delivery switch and the automatic switch-off.
  // app.js passes its own element builder `h`; the buttons are handled above.
  window.OrchMobileMode = {
    settingsSection(h) {
      if (!mm) return null;
      const choices = mm.hours_choices?.length ? mm.hours_choices : HOURS;
      return h('div', {'data-key': 'settings-mobile-mode'},
        h('div', {className: 'card-row name-row'}, h('span', {className: 'set-label'}, 'Send questions'),
          h('div', {className: 'grow set-ctl'}, h('p', {}, 'Questions also go to your phone'),
            h('p', {className: 'meta'}, needsPhone() ? NO_PHONE : 'This computer stays awake while this is on. Closing the lid still puts it to sleep.')),
          h('button', {type: 'button', className: 'switch', role: 'switch', 'aria-checked': mm.on ? 'true' : 'false', 'aria-label': 'Send questions to my phone',
            'data-mm': 'switch', 'data-key': 'mm-switch', 'data-testid': 'mobile-mode-switch', disabled: busy || needsPhone()}, mm.on ? 'On' : 'Off')),
        h('div', {className: 'card-row name-row'}, h('span', {className: 'set-label'}, 'Switch off after'),
          h('div', {className: 'grow set-ctl mm-hours', role: 'radiogroup', 'aria-label': 'Switch off by itself after', 'data-testid': 'mobile-mode-hours'},
            choices.map(n => h('button', {type: 'button', className: 'btn sm ' + (n === mm.default_hours ? 'primary' : 'ghost'), role: 'radio',
              'aria-checked': n === mm.default_hours ? 'true' : 'false', 'data-mm-hours': n, 'data-key': 'mm-hours-' + n,
              'data-testid': 'mobile-mode-hours-' + n}, n + ' h')))));
    },
  };
})();

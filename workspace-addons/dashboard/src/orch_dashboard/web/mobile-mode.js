'use strict';
// Mobile mode ("Send questions to my phone"): the switch in the menu, the first-click question, the bar on every page, the Settings choice.
// All data comes from state.mobile_mode (the relay add-on, via the server); null = the add-on is off, nothing shows.
// app.js hands over each new state (event "orch:state") and the act function (window.orchAct).
(() => {
  const ASK_OFF_KEY = 'orch.mobileMode.dontAsk';
  const HOURS = [4, 8, 12, 24];
  let mm = null, busy = false, asking = false, toastedEnd = '';
  const needsPhone = () => !!mm && !mm.on && mm.phones === 0;
  const bar = document.getElementById('mm-bar');
  const toggle = document.getElementById('mm-toggle');
  const chip = document.getElementById('mm-chip');
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

  // While it is on, the top-bar chip says so (click: a small menu). The banner is only for the first-click ask and the
  // last five minutes ("ended" is a one-time toast).
  const SOON_MS = 5 * 60 * 1000;
  const endsSoon = () => {
    const t = mm?.ends_at ? new Date(mm.ends_at).getTime() : NaN;
    return Number.isFinite(t) && t - Date.now() <= SOON_MS && t - Date.now() > 0;
  };
  // "Keep on longer" reuses the existing hours choice: the smallest one that ends later than the current end.
  const longer = () => {
    const t = mm?.ends_at ? new Date(mm.ends_at).getTime() : NaN;
    const choices = mm?.hours_choices?.length ? mm.hours_choices : HOURS;
    return choices.find(n => !Number.isFinite(t) || Date.now() + n * 3600000 > t + 1800000) || null;
  };
  const phoneIcon = () => {
    const s = node('span', {className: 'chip-ic', 'aria-hidden': 'true'});
    try { if (typeof window.icon === 'function') s.innerHTML = window.icon('phone', 14); } catch (_) { /* no icon: the words are enough */ }
    return s;
  };
  function paintChip() {
    if (!chip) return;
    if (!mm || !mm.on) { chip.hidden = true; return; }
    const warn = mm.awake === 'could_not_keep_awake';
    const ends = hm(mm.ends_at);
    chip.hidden = false;
    chip.setAttribute('data-testid', 'mobile-mode-bar');
    chip.classList.toggle('attn', warn);
    const more = longer();
    chip.replaceChildren(
      node('summary', {className: 'chip outline' + (warn ? ' attn' : ''), 'data-testid': 'mobile-mode-chip', 'aria-label': 'Phone mode is on'}, phoneIcon(), 'Phone' + (ends ? ' until ' + ends : ' on')),
      node('div', {className: 'menu-pop'},
        node('p', {className: 'menu-title'}, 'Questions go to your phone' + (ends ? ' until ' + ends : '')),
        node('p', {className: 'meta mm-desc'}, warn ? 'Could not keep this computer awake. Questions may stop reaching your phone when it sleeps.' : 'This computer stays awake meanwhile.'),
        more ? btn('Keep on for ' + more + (more === 1 ? ' hour' : ' hours'), 'menu-item', 'extend', 'mobile-mode-extend', {'data-hours': more}) : null,
        btn('Turn off', 'menu-item', 'off', 'mobile-mode-bar-off')));
  }

  function paintBar() {
    bar.replaceChildren();
    if (!mm) { bar.hidden = true; return; }
    if (mm.on) {
      // Only the last five minutes bring the banner back; otherwise the chip is all there is.
      if (endsSoon()) {
        bar.className = 'mm-bar banner live attn center';
        bar.setAttribute('data-testid', 'mobile-mode-soon');
        const more = longer();
        bar.append(node('div', {className: 'grow'}, node('b', {}, 'Phone mode ends in 5 minutes'), node('span', {className: 'mm-desc'}, 'Questions then stay on this computer.')),
          more ? btn('Keep on for ' + more + (more === 1 ? ' hour' : ' hours'), 'outline sm', 'extend', 'mobile-mode-soon-extend', {'data-hours': more}) : null);
        bar.hidden = false;
      } else bar.hidden = true;
    } else if (asking) {
      bar.className = 'mm-bar banner center';
      bar.setAttribute('data-testid', 'mobile-mode-ask');
      const dont = node('input', {type: 'checkbox', id: 'mm-dont', 'data-testid': 'mobile-mode-dont-ask'});
      bar.append(node('div', {className: 'grow'},
        node('h3', {}, 'Send questions to your phone?'),
        node('p', {className: 'meta'}, 'Questions from your helpers also go to your phone, and this computer stays awake until you turn it off. Closing the lid of a laptop still puts it to sleep.'),
        node('div', {className: 'mm-actions actions'}, btn('Turn on', 'primary sm', 'confirm', 'mobile-mode-confirm'), btn('Cancel', 'ghost sm', 'cancel', 'mobile-mode-cancel'),
          node('label', {className: 'mm-chk', for: 'mm-dont'}, dont, "Don't ask again"))));
      bar.hidden = false;
    } else bar.hidden = true;
    paintChip();
    // No phone paired: nothing to send to, so the switch is not shown at all (an On switch always stays, to turn it off).
    toggle.hidden = needsPhone();
    toggle.setAttribute('aria-checked', mm.on ? 'true' : 'false');
    toggle.disabled = busy;
    toggle.title = '';
    const label = toggle.querySelector('.mm-label');
    if (label) label.textContent = mm.on ? 'Phone' + (hm(mm.ends_at) ? ' · until ' + hm(mm.ends_at) : '') : 'Phone';
  }

  // A mode whose end time has passed is over, whatever the last state said: the chip, the switch and the bar all go quiet
  // at the end time (the server ends it at its next read), so nothing says "until 08:46" at 10:10 (ORCH-184).
  const settleLocal = () => {
    const end = mm?.on && mm.ends_at ? Date.parse(mm.ends_at) : NaN;
    if (Number.isFinite(end) && end <= Date.now()) mm = {...mm, on: false, ends_at: null, since: null, awake: null};
  };
  function paint() {
    settleLocal();
    document.body.classList.toggle('mobile-mode-on', !!mm?.on);
    if (!mm) { toggle.hidden = true; bar.hidden = true; if (chip) chip.hidden = true; return; }
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

  const closeChip = () => { if (chip) chip.open = false; };
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
      case 'off': closeChip(); await call('mobile.set', {on: false}); break;
      case 'extend': closeChip(); await call('mobile.set', {on: true, hours: Number(t.dataset.hours)}); break;
      case 'ack': await call('mobile.ack', {}); break;
    }
  });

  if (typeof setInterval === 'function') setInterval(() => { if (mm?.on) paint(); }, 30000);  // the end time can pass between two states
  window.addEventListener('orch:state', event => {
    mm = event.detail?.mobile_mode || null;
    if (mm?.on) asking = false;
    // The "ended" notice is one toast, shown once, then marked seen (no banner that stays until OK).
    const endedText = !mm?.on && mm?.ended?.text ? mm.ended.text : '';
    if (endedText && toastedEnd !== endedText) {
      toastedEnd = endedText;
      window.orch?.toast(endedText, 'ok');
      if (typeof window.orchAct === 'function') window.orchAct('mobile.ack', {});
    } else if (!endedText) toastedEnd = '';
    paint();
  });

  // The Settings > Phone & workspaces rows (pairing card): the delivery switch and the automatic switch-off.
  // app.js passes its own element builder `h`; the buttons are handled above.
  window.OrchMobileMode = {
    settingsSection(h) {
      if (!mm || needsPhone()) return null;
      const choices = mm.hours_choices?.length ? mm.hours_choices : HOURS;
      return h('div', {'data-key': 'settings-mobile-mode'},
        h('div', {className: 'card-row name-row'}, h('span', {className: 'set-label'}, 'Send questions'),
          h('div', {className: 'grow set-ctl'}, h('p', {}, 'Questions also go to your phone'),
            h('p', {className: 'meta'}, 'This computer stays awake while this is on. Closing the lid still puts it to sleep.')),
          h('button', {type: 'button', className: 'switch', role: 'switch', 'aria-checked': mm.on ? 'true' : 'false', 'aria-label': 'Send questions to my phone',
            'data-mm': 'switch', 'data-key': 'mm-switch', 'data-testid': 'mobile-mode-switch', disabled: busy}, mm.on ? 'On' : 'Off')),
        h('div', {className: 'card-row name-row'}, h('span', {className: 'set-label'}, 'Switch off after'),
          h('div', {className: 'grow set-ctl mm-hours', role: 'radiogroup', 'aria-label': 'Switch off by itself after', 'data-testid': 'mobile-mode-hours'},
            choices.map(n => h('button', {type: 'button', className: 'btn sm ' + (n === mm.default_hours ? 'primary' : 'ghost'), role: 'radio',
              'aria-checked': n === mm.default_hours ? 'true' : 'false', 'data-mm-hours': n, 'data-key': 'mm-hours-' + n,
              'data-testid': 'mobile-mode-hours-' + n}, n + ' h')))));
    },
  };
})();

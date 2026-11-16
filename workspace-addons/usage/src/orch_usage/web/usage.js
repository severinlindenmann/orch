// The Usage page (stage 1): accounts with their use, resets and rule; switching by itself; the history.
// It only reads from its own server (GET api/page). Every change is a click the dashboard runs as the person:
// the page names a verb and a target (postMessage `orch.act`), the dashboard runs `orch usage act` and answers.
// All text is set with textContent; the look is the master kit only (no page sheet).
(() => {
  'use strict';
  const P = document.documentElement.dataset.prefix || '';
  const $ = id => document.getElementById(id);
  const embedded = window.parent !== window;
  const PERIOD = {'5h': 'per 5 hours', week: 'per week', month: 'per month', until: 'until a date'};
  const TYPE = {subscription: 'Subscription', 'api-key': 'API key', 'helper-tool': 'Helper tool'};
  const STATE = {'in-use': ['In use now', 'pill done'], ready: ['Ready', 'pill'], off: ['Off', 'pill'], missing: ['Not found', 'pill needs']};
  let model = null, busy = false;
  // The toast names what was saved: the account's name and the kind of change.
  const nameOf = target => model?.accounts.find(a => a.id === target.split(':')[0])?.label || 'Account';
  const WHAT = {limit: t => nameOf(t) + ': limit', period: t => nameOf(t) + ': what the limit counts', order: t => nameOf(t) + ': order',
    on: t => nameOf(t) + ': on', off: t => nameOf(t) + ': off', end: t => nameOf(t) + ': end', switching: () => 'Switching by itself'};

  function h(tag, props, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v == null || v === false) continue;
      if (k === 'className') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    n.append(...kids.flat().filter(x => x != null && x !== false));
    return n;
  }

  // ---- words for times: the kit's one date format (UI.stamp / UI.clock, this computer's time) ----
  const stamp = (v, o) => window.UI.stamp(v, o || {});
  function resetWords(iso, used) {
    if (!iso) return used ? '' : 'resets when used';
    const ms = new Date(iso) - Date.now();
    if (!(ms > 0)) return 'resets soon';
    if (ms < 86400000) {
      const m = Math.round(ms / 60000), hh = Math.floor(m / 60);
      return 'resets in ' + (hh ? hh + ' h ' : '') + (m % 60) + ' min';
    }
    return 'resets ' + stamp(iso);
  }
  const whenWords = iso => stamp(iso);
  const dateWords = iso => stamp(iso, {time: false});
  // A date choice with the kit's calendar (UI.date): a button that opens it, the value in a hidden field.
  function datePick(label, value, onPick) {
    const field = h('input', {type: 'hidden', value: value || ''});
    const toggle = h('button', {type: 'button', className: 'btn outline sm', 'aria-label': label});
    field.addEventListener('change', () => { if (field.value) onPick(field.value.slice(0, 10)); });
    queueMicrotask(() => window.UI.date(field, toggle, null));
    return {field, toggle, node: h('span', {className: 'row'}, field, toggle)};
  }
  const num = v => (Math.round(v * 100) / 100).toString();
  const amount = (v, unit) => unit === '$' ? '$' + num(v) : num(v) + '%';
  const day = iso => iso ? iso.slice(0, 10) : '';

  // ---- talking to the dashboard ----
  const asked = new Map();
  addEventListener('message', e => {
    const d = e.data;
    if (e.origin !== location.origin || e.source !== window.parent || !d || typeof d !== 'object' || !asked.has(d.id)) return;
    if (d.type === 'orch.act.done') asked.get(d.id)({ok: true, answer: d.answer});
    else if (d.type === 'orch.act.failed') asked.get(d.id)({ok: false, error: typeof d.error === 'string' ? d.error.slice(0, 300) : ''});
  });
  function askDashboard(verb, target) {
    return new Promise(resolve => {
      const id = Array.from(crypto.getRandomValues(new Uint8Array(12)), b => (b % 36).toString(36)).join('');
      const timer = setTimeout(() => finish({ok: false, error: 'The dashboard did not answer. Reload the page and try again.'}), 30000);
      function finish(r) { clearTimeout(timer); asked.delete(id); resolve(r); }
      asked.set(id, finish);
      window.parent.postMessage({type: 'orch.act', id, verb, target}, location.origin);
    });
  }
  function say(text, kind) {
    const live = $('local-feedback');
    live.textContent = text;
    if (window.UI?.toast) window.UI.toast(text, null, kind);
  }
  async function act(verb, target, control) {
    if (!embedded) { say('Open Usage from the dashboard to change it.', 'error'); return load(); }
    if (busy) return;
    busy = true;
    if (control) control.disabled = true;
    const r = await askDashboard(verb, target);
    busy = false;
    const what = WHAT[verb] ? WHAT[verb](target) : 'Change';
    if (r.ok) say(r.answer?.changed === false ? what + ': already like that.' : what + ' saved');
    else say(r.error || 'That could not be saved. Nothing was changed.', 'error');
    await load(true);
  }

  // ---- drawing ----
  function bar(b) {
    const used = typeof b.used === 'number' ? b.used : null;
    let pct = 0;
    if (used != null) pct = b.unit === '%' ? used : (b.limit ? used / b.limit * 100 : 0);
    pct = Math.max(0, Math.min(100, pct));
    const head = used == null ? 'not read yet' : amount(used, b.unit) + (b.estimated ? ' (estimated)' : '');
    const right = b.unit === '%' ? resetWords(b.resets_at, used) : (b.until ? 'ends ' + dateWords(b.until) : '');
    const fill = h('span');
    fill.style.setProperty('--value', pct + '%');
    return h('div', {className: 'progress-labeled'},
      h('div', {className: 'progress-text'},
        h('span', {}, b.label + ' · ' + head + ' ', b.limit != null ? h('span', {className: 'meta', text: 'of ' + amount(b.limit, b.limit_unit)}) : null),
        h('span', {text: right})),
      h('div', {className: 'progress', role: 'progressbar', 'aria-label': b.label, 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(pct))}, fill));
  }

  function limitRow(a, lim, isNew) {
    const period = lim ? lim.period : a.periods.find(p => !a.limits.some(l => l.period === p));
    const value = h('input', {className: 'input', inputmode: 'decimal', size: '6', value: lim ? num(lim.value) : '', placeholder: 'none', 'aria-label': 'Limit for ' + a.label + ', ' + PERIOD[period]});
    const until = datePick('Counts until, ' + a.label, lim?.until ? day(lim.until) : '', () => untilPicked());
    const untilField = h('div', {className: 'field meta', hidden: period !== 'until'}, 'Until', until.node);
    const select = h('select', {'aria-label': 'Counts for ' + a.label}, a.periods.map(p => h('option', {value: p, selected: p === period, disabled: p !== period && a.limits.some(l => l.period === p), text: PERIOD[p]})));
    const saveValue = () => {
      const v = value.value.trim().replace(/\s+/g, '').replace(/[%$]/g, '');
      if (!v && (isNew || !lim)) return;
      if (v && !/^\d{1,7}(\.\d{1,4})?$/.test(v)) { value.setAttribute('aria-invalid', 'true'); return say('Write a number, like 90, or leave it empty for no limit.', 'error'); }
      value.removeAttribute('aria-invalid');
      const p = select.value;
      if (p === 'until' && !until.field.value) return say('Pick the date it counts until.', 'error');
      if (lim && v && Number(v) === lim.value && p === lim.period) return;
      act('limit', a.id + ':' + p + ':' + (v ? v + a.unit : 'none') + (p === 'until' ? ':' + day(until.field.value) : ''), value);
    };
    value.addEventListener('change', saveValue);
    select.addEventListener('change', () => {
      untilField.hidden = select.value !== 'until';
      if (select.value === 'until' && !until.field.value) return until.toggle.focus();
      if (!lim) return saveValue();
      act('period', a.id + ':' + lim.period + ':' + select.value + (select.value === 'until' ? ':' + day(until.field.value) : ''), select);
    });
    function untilPicked() {
      const d = day(until.field.value);
      if (!lim) return saveValue();
      act(lim.period === 'until' ? 'limit' : 'period', lim.period === 'until'
        ? a.id + ':until:' + num(lim.value) + a.unit + ':' + d
        : a.id + ':' + lim.period + ':until:' + d, until.toggle);
    }
    return h('div', {className: 'row'},
      h('label', {className: 'field meta'}, 'Limit in ' + a.unit, value),
      h('label', {className: 'field meta'}, 'Counts', select),
      untilField);
  }

  function endRow(a) {
    if (a.ends) {
      return h('div', {className: 'row'},
        h('span', {className: 'pill', text: 'Ends ' + dateWords(a.ends)}),
        h('span', {className: 'meta', text: a.falls_back ? 'Then the rule before it again.' : 'Then no limit.'}),
        h('button', {type: 'button', className: 'btn ghost sm', onclick: e => act('end', a.id + ':none', e.currentTarget)}, 'Keep it, no end'));
    }
    // "Add an end" opens the kit's calendar at once; the picked day is saved (the rule ends at the end of that day).
    const pick = datePick('End date for ' + a.label, '', d => act('end', a.id + ':' + d, pick.toggle));
    pick.node.hidden = true;
    const add = h('button', {type: 'button', className: 'btn ghost sm', disabled: !a.limits.length || null,
      onclick: () => pick.toggle.click()}, 'Add an end');
    return h('div', {className: 'row'}, add, pick.node,
      a.limits.length ? null : h('span', {className: 'meta', text: 'Set a limit first.'}));
  }

  function card(a, i, list) {
    const [stateText, stateClass] = STATE[a.state] || STATE.ready;
    const move = (way, to) => h('button', {type: 'button', className: 'btn ghost sm', disabled: !to || null,
      'aria-label': (way === 'up' ? 'Use ' + a.label + ' earlier' : 'Use ' + a.label + ' later'),
      onclick: e => act('order', a.id + ':' + to.order, e.currentTarget)}, way === 'up' ? '↑' : '↓');
    const on = h('input', {className: 'switch', type: 'checkbox', checked: a.on || null, 'aria-label': 'Use ' + a.label});
    on.addEventListener('change', () => act(on.checked ? 'on' : 'off', a.id, on));
    const rows = a.limits.map(l => limitRow(a, l, false));
    if (!a.limits.length) rows.push(limitRow(a, null, true));
    const room = a.limits.length && a.limits.length < 2 && a.periods.some(p => !a.limits.some(l => l.period === p));
    let addLimit = null;
    if (room) {
      addLimit = h('button', {type: 'button', className: 'btn ghost sm', onclick: () => { addLimit.replaceWith(limitRow(a, null, true)); }}, 'Add a second limit');
    }
    return h('div', {className: 'card pad stack', role: 'listitem', 'data-acc': a.id},
      h('div', {className: 'row between'},
        h('div', {className: 'row'}, h('span', {className: 'badge', text: String(i + 1)}), h('h3', {text: a.label}), h('span', {className: 'meta', text: TYPE[a.type] || ''}), h('span', {className: stateClass, text: stateText})),
        list.length > 1 ? h('div', {className: 'row'}, move('up', list[i - 1]), move('down', list[i + 1])) : null),
      a.bars.length ? a.bars.map(bar) : h('p', {className: 'meta', text: 'No use read yet.'}),
      h('div', {className: 'row between'}, h('div', {className: 'row'}, rows, addLimit),
        h('label', {className: 'row'}, h('span', {className: 'meta', text: 'On'}), on)),
      endRow(a));
  }

  function section(title, note, list) {
    return h('section', {className: 'stack'},
      h('div', {className: 'row between'}, h('h2', {text: title}), h('span', {className: 'meta', text: note})),
      h('div', {className: 'stack', role: 'list'}, list.map((a, i) => card(a, i, list))));
  }

  function history(rows) {
    return h('section', {className: 'card'},
      h('div', {className: 'card-h'}, h('h2', {text: 'History'}), h('span', {className: 'meta', text: 'Last 30 days'})),
      rows.length ? rows.map(r => h('div', {className: 'list-row'}, h('span', {className: 'meta', text: whenWords(r.at)}),
        h('span', {className: 'grow', text: (r.who === 'Usage' ? '' : r.who + ': ') + r.text})))
        : h('div', {className: 'list-row'}, h('span', {className: 'meta', text: 'No changes yet.'})));
  }

  function draw(m) {
    const auto = $('auto'), note = $('auto-note');
    auto.checked = !!m.switching;
    auto.disabled = !embedded || !m.switcher || m.one_account;
    // one account: the empty card below says why switching is off; no second sentence up here
    note.hidden = m.switcher || !embedded;
    note.textContent = m.switcher ? '' : 'Switching needs the account switcher on this computer. Usage shows and warns.';
    const subs = m.accounts.filter(a => a.type === 'subscription'), other = m.accounts.filter(a => a.type !== 'subscription');
    const parts = [];
    if (m.all_at_limit) {
      parts.push(h('div', {className: 'banner attn', role: 'alert'}, h('div', {className: 'grow'},
        h('h3', {text: 'Every account is at or near its limit'}),
        h('p', {text: 'Helpers wait when the last one reaches its limit. Raise a limit or turn an account on.'}))));
    }
    for (const w of m.warnings || []) if (w && !/switcher is not installed/.test(w)) parts.push(h('div', {className: 'banner info', role: 'status'}, h('p', {className: 'grow', text: w})));
    if (!m.accounts.length) {
      parts.push(h('section', {className: 'card empty state-empty'}, h('span', {className: 'file-type', 'aria-hidden': 'true', text: '—'}),
        h('h2', {text: 'No account found yet'}), h('p', {text: 'Usage adds the subscriptions it finds on this computer and shows their use here.'})));
    } else if (m.one_account && subs.length === 1) {
      parts.push(h('section', {className: 'card empty state-empty'}, h('span', {className: 'file-type', 'aria-hidden': 'true', text: '—'}),
        h('h2', {text: 'One account found'}), h('p', {text: 'Usage shows its use and warns before it runs out. Switching needs a second account.'})));
    }
    const subsNote = m.one_account || !m.switcher ? '' : m.switching ? 'Switched early, before a limit is reached.' : 'Switching by itself is off: Usage only shows and warns.';
    if (subs.length) parts.push(section('Subscriptions', subsNote, subs));
    if (other.length) parts.push(section('API keys and helper tools', 'Each one stops at its limit.', other));
    parts.push(history(m.history || []));
    parts.push(h('p', {className: 'meta', text: 'Logins and keys are never shown or kept here.'}));
    const keep = document.activeElement?.getAttribute('aria-label');
    $('loaded').replaceChildren(...parts);
    if (keep) document.querySelector('#loaded [aria-label="' + CSS.escape(keep) + '"]')?.focus();
  }

  function show(which) {
    for (const id of ['loading', 'error', 'loaded']) $(id).hidden = id !== which;
    $('view-region').setAttribute('aria-busy', String(which === 'loading'));
  }
  async function load(fresh) {
    try {
      const r = await fetch(P + '/api/page' + (fresh ? '?fresh=1' : ''), {cache: 'no-store'});
      if (!r.ok) throw new Error((await r.text()).slice(0, 300) || 'No answer.');
      model = await r.json();
      draw(model);
      show('loaded');
    } catch (e) {
      if (model) return;  // keep the last good page; the next look tries again
      $('error-text').textContent = e.message || 'No answer.';
      show('error');
    }
  }

  $('auto').addEventListener('change', e => act('switching', e.currentTarget.checked ? 'on' : 'off', e.currentTarget));
  $('retry').addEventListener('click', () => { show('loading'); load(true); });
  load(false);
  setInterval(() => { if (!busy && !document.hidden && !document.activeElement?.matches?.('input,select')) load(false); }, 30000);
})();

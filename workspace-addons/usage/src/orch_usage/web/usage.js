// The Usage page: accounts with their use, resets and rule; one limit over all accounts of a provider; adding an API
// credit or helper tool; switching by itself; the history.
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
    on: t => nameOf(t) + ': on', off: t => nameOf(t) + ': off', end: t => nameOf(t) + ': end', switching: () => 'Switching by itself',
    for: t => nameOf(t) + ': kinds of work', model: t => nameOf(t) + ': model', remove: t => nameOf(t) + ' removed',
    together: t => 'All ' + providerWord(t.split(':')[0]) + ' accounts together: limit', add: t => t.split(':').slice(6).join(':') + ' added',
    left: t => nameOf(t) + ': left now', restore: t => removedName(t) + ' is back'};
  const removedName = id => model?.removed?.find(r => r.id === id)?.label || 'It';
  const providerWord = id => model?.providers?.find(p => p.id === id)?.label || id;

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
  // dollars as the provider shows them: $73.40, $0.00; a spend under a cent keeps its digits ($0.0042)
  const usd = v => typeof v !== 'number' ? '?' : v > 0 && v < 0.01 ? '$' + v.toFixed(4) : '$' + v.toFixed(2);

  // ---- talking to the dashboard ----
  const asked = new Map();
  addEventListener('message', e => {
    const d = e.data;
    if ((e.origin !== location.origin && !(window.OrchFrame || {}).on) || e.source !== window.parent || !d || typeof d !== 'object' || !asked.has(d.id)) return;
    if (d.type === 'orch.act.done') asked.get(d.id)({ok: true, answer: d.answer});
    else if (d.type === 'orch.act.failed') asked.get(d.id)({ok: false, error: typeof d.error === 'string' ? d.error.slice(0, 300) : ''});
  });
  function askDashboard(verb, target) {
    return new Promise(resolve => {
      const id = Array.from(crypto.getRandomValues(new Uint8Array(12)), b => (b % 36).toString(36)).join('');
      const timer = setTimeout(() => finish({ok: false, error: 'The dashboard did not answer. Reload the page and try again.'}), 30000);
      function finish(r) { clearTimeout(timer); asked.delete(id); resolve(r); }
      asked.set(id, finish);
      // sandboxed frame: its own origin is opaque (location.origin is still the dashboard's address), so the dashboard checks this frame and its code (kit/frame.js), not an origin
      window.parent.postMessage({type: 'orch.act', id, verb, target, chan: (window.OrchFrame || {}).chan}, location.origin);
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
    const right = b.unit === '%' ? resetWords(b.resets_at, used) : (b.until ? 'ends ' + dateWords(b.until) : b.resets_at ? resetWords(b.resets_at, true) : '');
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

  const KINDS = [['lead', 'Lead'], ['code', 'Code'], ['reviews', 'Reviews'], ['builds', 'Builds'], ['scripts', 'Scripts'], ['helpers', 'Helpers']];

  function kindsRow(a) {
    // no kind picked = every kind of work may use it (as before kinds of work existed)
    const picked = new Set(a.for || []);
    const chips = KINDS.map(([k, word]) => h('button', {type: 'button', className: 'chip-btn' + (picked.has(k) ? ' sel' : ''),
      'aria-pressed': picked.has(k) ? 'true' : 'false', 'data-kind': k,
      onclick: e => {
        const next = new Set(picked);
        if (next.has(k)) next.delete(k); else next.add(k);
        const list = KINDS.map(x => x[0]).filter(x => next.has(x));
        act('for', a.id + ':' + (list.length ? list.join(',') : 'any'), e.currentTarget);
      }}, word));
    return h('div', {className: 'row'}, h('span', {className: 'meta', text: 'For'}), chips,
      picked.size ? null : h('span', {className: 'meta', text: 'every kind of work'}));
  }

  // Which model the kinds of work on this account may use: never more than orch's own pick; a person's choice wins.
  const MODELS = [['any', 'Any'], ['first', 'Small first'], ['small', 'Small only']];
  function modelRow(a) {
    const cur = a.model || 'any';
    return h('div', {className: 'row'}, h('span', {className: 'meta', text: 'Model'}),
      MODELS.map(([m, word]) => h('button', {type: 'button', className: 'chip-btn' + (m === cur ? ' sel' : ''),
        'aria-pressed': m === cur ? 'true' : 'false', 'data-model': m,
        onclick: e => { if (m !== cur) act('model', a.id + ':' + m, e.currentTarget); }}, word)));
  }

  function useText(a) {
    if (a.state === 'missing' || a.missing) return 'No longer in the account switcher.';  // off ones too
    return 'No use read yet.';
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
      // the order arrows stay on the name line at phone width; the type and state go on the line below
      h('div', {className: 'row between'},
        h('div', {className: 'row'}, h('span', {className: 'badge', text: String(i + 1)}), h('h3', {text: a.label})),
        list.length > 1 ? h('div', {className: 'row'}, move('up', list[i - 1]), move('down', list[i + 1])) : null),
      h('div', {className: 'row'}, a.type === 'subscription' ? null : h('span', {className: 'meta', text: TYPE[a.type] || ''}), h('span', {className: stateClass, text: stateText})),
      a.bars.length ? a.bars.map(bar) : h('p', {className: 'meta', text: useText(a)}),
      h('div', {className: 'row between'}, h('div', {className: 'row'}, rows, addLimit),
        h('label', {className: 'row'}, h('span', {className: 'meta', text: 'On'}), on)),
      kindsRow(a),
      modelRow(a),
      h('div', {className: 'row between'}, endRow(a),
        a.removable ? h('button', {type: 'button', className: 'btn ghost sm', 'aria-label': 'Remove ' + a.label,
          onclick: e => act('remove', a.id, e.currentTarget)}, 'Remove') : null));
  }

  // One money limit over every API credit and helper tool of a provider: spending on any of them counts.
  function togetherCard(t) {
    const value = h('input', {className: 'input', inputmode: 'decimal', size: '6', value: t.limit != null ? num(t.limit) : '', placeholder: 'none',
      'aria-label': 'Limit for ' + t.label});
    value.addEventListener('change', () => {
      const v = value.value.trim().replace(/[\s$]/g, '');
      if (v && !/^\d{1,7}(\.\d{1,4})?$/.test(v)) { value.setAttribute('aria-invalid', 'true'); return say('Write a number, like 100, or leave it empty for no limit.', 'error'); }
      value.removeAttribute('aria-invalid');
      if ((v ? Number(v) : null) === t.limit) return;
      act('together', t.provider + ':' + (v ? '$' + v : 'none'), value);
    });
    const b = t.limit != null ? bar({label: 'This month', unit: '$', used: t.spent, limit: t.limit, limit_unit: '$', resets_at: t.resets_at}) : null;
    return h('div', {className: 'card pad stack', 'data-together': t.provider},
      h('div', {className: 'row'}, h('h3', {text: t.label})),
      h('p', {className: 'meta', text: t.accounts.join(', ')}),
      b,
      h('div', {className: 'row'}, h('label', {className: 'field meta'}, 'Limit in $ per month', value)));
  }

  // Add an API credit or helper tool: its name here, the provider, the name the credit skill already uses to find
  // its key (never the key), the kinds of work, a monthly limit and the day the month starts again.
  function addCard(providers) {
    const box = h('div', {className: 'card pad stack', 'data-add': ''});
    const open = h('button', {type: 'button', className: 'btn outline sm', onclick: () => { box.replaceChildren(...form()); box.querySelector('input')?.focus(); }}, 'Add a helper tool');
    box.append(h('div', {className: 'row'}, open));
    function form() {
      const label = h('input', {className: 'input', autocomplete: 'off', maxlength: '64', 'aria-label': 'Name shown here'});
      const name = h('input', {className: 'input', autocomplete: 'off', maxlength: '32', size: '10', 'aria-label': 'Name the credit skill uses'});
      const provider = h('select', {'aria-label': 'Provider'}, providers.map((p, j) => h('option', {value: p.id, selected: j === 0 || null, text: p.label})));
      const type = h('select', {'aria-label': 'Type'}, h('option', {value: 'helper-tool', text: 'Helper tool'}), h('option', {value: 'api-key', text: 'API credit'}));
      const limit = h('input', {className: 'input', inputmode: 'decimal', size: '6', placeholder: 'none', 'aria-label': 'Limit in $ per month'});
      const resets = datePick('Month starts again on', '', () => {});
      const kinds = new Set();
      const chips = KINDS.map(([k, word]) => h('button', {type: 'button', className: 'chip-btn', 'aria-pressed': 'false', 'data-kind': k,
        onclick: e => { const on = !kinds.has(k); if (on) kinds.add(k); else kinds.delete(k); e.currentTarget.classList.toggle('sel', on); e.currentTarget.setAttribute('aria-pressed', String(on)); }}, word));
      const add = h('button', {type: 'button', className: 'btn outline sm', onclick: e => {
        const l = label.value.trim(), n = name.value.trim(), v = limit.value.trim().replace(/[\s$]/g, '');
        if (!/^[A-Za-z0-9][A-Za-z0-9 /._()&+-]{0,63}$/.test(l)) { label.setAttribute('aria-invalid', 'true'); return say('Give it a short name with letters and numbers.', 'error'); }
        if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$/.test(n)) { name.setAttribute('aria-invalid', 'true'); return say('Write the name the credit skill uses for it, like main. Never the key.', 'error'); }
        if (v && !/^\d{1,7}(\.\d{1,4})?$/.test(v)) { limit.setAttribute('aria-invalid', 'true'); return say('Write a number, like 100, or leave it empty for no limit.', 'error'); }
        const list = KINDS.map(x => x[0]).filter(x => kinds.has(x));
        act('add', [provider.value, type.value, n, list.length ? list.join(',') : 'any', v ? '$' + v : 'none',
          resets.field.value ? day(resets.field.value) : '-', l].join(':'), e.currentTarget);
      }}, 'Add');
      return [
        h('h3', {text: 'Add a helper tool'}),
        h('div', {className: 'row'}, h('label', {className: 'field meta'}, 'Name shown here', label),
          h('label', {className: 'field meta'}, 'Provider', provider), h('label', {className: 'field meta'}, 'Type', type)),
        h('div', {className: 'row'}, h('label', {className: 'field meta'}, 'Name the credit skill uses', name),
          h('label', {className: 'field meta'}, 'Limit in $ per month', limit), h('div', {className: 'field meta'}, 'Month starts again on', resets.node)),
        h('div', {className: 'row'}, h('span', {className: 'meta', text: 'For'}), chips),
        h('p', {className: 'meta', text: 'Only the name the credit skill already uses to find its key. Never the key itself.'}),
        h('div', {className: 'row'}, h('button', {type: 'button', className: 'btn ghost sm', onclick: () => { box.replaceChildren(h('div', {className: 'row'}, open)); }}, 'Cancel'), add)];
    }
    return box;
  }

  // An API credit (ORCH-628): what is left (the owner's figure minus the spend since), spent today and this month,
  // the field 'Left now', On, the kinds of work, an end, order and Remove. Never a key: only names and numbers.
  function creditLines(a) {
    const c = a.credit || {};
    if (c.left == null) {
      return [h('p', {}, h('strong', {text: 'Left: not set yet'})),
        h('p', {className: 'meta', text: 'Type what the provider shows as left. Until then calls go ahead and are counted.'})];
    }
    const at = whenWords(c.set_at);
    let since = 'Set to ' + usd(c.set) + (/^\d/.test(at) ? ' on ' : ' ') + at;
    if (c.left === 0 && !c.over && !c.spent_since) since += '. Calls are refused until you set more.';
    else since += ', minus ' + usd(c.spent_since || 0) + ' spent since' + (c.over ? ', ' + usd(c.over) + ' over' : '');
    return [h('p', {}, h('strong', {text: 'Left: ' + usd(c.left)})), h('p', {className: 'meta', text: since})];
  }

  // An end at the end of a day is kept as the next day 00:00: say the day itself, 23:59, like the draft.
  function endWords(iso) {
    const d = new Date(iso);
    if (d.getHours() === 0 && d.getMinutes() === 0) d.setMinutes(-1);
    return whenWords(d.toISOString());
  }

  function creditEnd(a) {
    const ends = a.credit?.ends;
    const pick = datePick('End date for ' + a.label, '', d => act('end', a.id + ':' + d, pick.toggle));
    pick.node.hidden = true;
    if (ends) {
      return h('div', {className: 'row'}, h('span', {className: 'pill', text: 'Ends ' + endWords(ends)}),
        h('button', {type: 'button', className: 'btn ghost sm', onclick: e => act('end', a.id + ':none', e.currentTarget)}, 'Keep it, no end'));
    }
    return h('div', {className: 'row'}, h('button', {type: 'button', className: 'btn ghost sm', onclick: () => pick.toggle.click()}, 'Add an end'), pick.node);
  }

  function creditCard(a, i, list) {
    const c = a.credit || {};
    let [stateText, stateClass] = STATE[a.state] || STATE.ready;
    if (a.on && c.left == null) [stateText, stateClass] = ['Not set yet', 'pill attn'];
    if (c.ends && new Date(c.ends) <= new Date()) [stateText, stateClass] = ['Ended', 'pill'];
    const move = (way, to) => h('button', {type: 'button', className: 'btn ghost sm', disabled: !to || null,
      'aria-label': (way === 'up' ? 'Use ' + a.label + ' earlier' : 'Use ' + a.label + ' later'),
      onclick: e => act('order', a.id + ':' + to.order, e.currentTarget)}, way === 'up' ? '↑' : '↓');
    const on = h('input', {className: 'switch', type: 'checkbox', checked: a.on || null, 'aria-label': 'Use ' + a.label});
    on.addEventListener('change', () => act(on.checked ? 'on' : 'off', a.id, on));
    const value = h('input', {className: 'input amount', inputmode: 'decimal', autocomplete: 'off',
      placeholder: c.left != null ? c.left.toFixed(2) : 'e.g. 50', 'aria-label': 'Left now for ' + a.label});
    const set = h('button', {type: 'button', className: 'btn outline sm'}, 'Set');
    const save = () => {
      let v = value.value.trim().replace(/[\s$]/g, '');
      if (/^\d+,\d{1,2}$/.test(v)) v = v.replace(',', '.');  // 73,40 is 73.40 (a decimal comma), never 7340
      if (!v) { value.setAttribute('aria-invalid', 'true'); return say('Type what the provider shows as left, like 50, or 0.', 'error'); }
      if (!/^\d{1,7}(\.\d{1,4})?$/.test(v)) { value.setAttribute('aria-invalid', 'true'); return say('Write an amount, like 73.40, or 0.', 'error'); }
      value.removeAttribute('aria-invalid');
      act('left', a.id + ':' + v, set);
    };
    set.addEventListener('click', save);
    value.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
    const from = [a.provider_label, c.skill ? 'from the skill ' + c.skill : ''].filter(Boolean).join(' · ');
    return h('div', {className: 'card pad stack', role: 'listitem', 'data-acc': a.id, 'data-credit': ''},
      h('div', {className: 'row between'},
        h('div', {className: 'row'}, h('span', {className: 'badge', text: String(i + 1)}), h('h3', {text: a.label})),
        list.length > 1 ? h('div', {className: 'row'}, move('up', list[i - 1]), move('down', list[i + 1])) : null),
      h('div', {className: 'row'}, from ? h('span', {className: 'meta', text: from}) : null, h('span', {className: stateClass, text: stateText})),
      creditLines(a),
      h('p', {className: 'meta', text: 'Spent today ' + usd(c.spent_today || 0) + ' · this month ' + usd(c.spent_month || 0)}),
      // a $ limit the credit already has (from its skill or set earlier) stays changeable; new credits have none
      a.limits.length ? h('div', {className: 'row'}, h('span', {className: 'meta', text: 'Also stops at'}), a.limits.map(l => limitRow(a, l, false))) : null,
      h('div', {className: 'row between'},
        h('div', {className: 'field meta'}, h('span', {text: 'Left now in $', 'aria-hidden': 'true'}), h('div', {className: 'row'}, value, set)),
        h('label', {className: 'row'}, h('span', {className: 'meta', text: 'On'}), on)),
      kindsRow(a),
      h('div', {className: 'row between'}, creditEnd(a),
        h('button', {type: 'button', className: 'btn ghost sm', 'aria-label': 'Remove ' + a.label,
          onclick: e => act('remove', a.id, e.currentTarget)}, 'Remove')));
  }

  // Removed credits and helper tools stay with their history; one click brings one back (rule and amount left kept).
  function removedRow(list, what) {
    if (!list.length) return null;
    const head = list.length === 1 ? '1 removed ' + what : list.length + ' removed ' + what + 's';
    return h('div', {className: 'stack'}, h('span', {className: 'meta', text: head}),
      list.map(r => h('div', {className: 'row'}, h('span', {className: 'meta', text: r.label}),
        h('button', {type: 'button', className: 'btn ghost sm', 'aria-label': 'Bring back ' + r.label,
          onclick: e => act('restore', r.id, e.currentTarget)}, 'Bring back'))));
  }

  function section(title, note, list, draw) {
    return h('section', {className: 'stack'},
      h('div', {className: 'row between'}, h('h2', {text: title}), h('span', {className: 'meta', text: note})),
      h('div', {className: 'stack', role: 'list'}, list.map((a, i) => (draw || card)(a, i, list))));
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
    const subs = m.accounts.filter(a => a.type === 'subscription'), credits = m.accounts.filter(a => a.type === 'api-key'),
      tools = m.accounts.filter(a => a.type === 'helper-tool');
    const parts = [];
    if (m.all_at_limit) {
      parts.push(h('div', {className: 'banner attn', role: 'alert'}, h('div', {className: 'grow'},
        h('h3', {text: 'Every account is at or near its limit'}),
        h('p', {text: 'Helpers wait when the last one reaches its limit. Raise a limit or turn an account on.'}))));
    }
    for (const w of m.waiting || []) {
      parts.push(h('div', {className: 'banner attn', role: 'alert'}, h('div', {className: 'grow'},
        h('h3', {text: 'Work for ' + w.kind + ' waits'}),
        h('p', {text: w.why + ' Raise a limit or allow another account for ' + w.kind + ' below.'}))));
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
    // API credits: each its own account, never added together per provider (owner, ORCH-624)
    const gone = m.removed || [];
    if (credits.length || gone.some(r => r.type === 'api-key')) {
      const creditSection = section('API credits', 'Type what the provider shows as left; orch counts down from it. At 0, off or ended, calls are refused.', credits, creditCard);
      const back = removedRow(gone.filter(r => r.type === 'api-key'), 'credit');
      if (back) creditSection.append(back);
      parts.push(creditSection);
    }
    const toolSection = section('Helper tools', 'Helpers ask here which one to use and stop at the limit.', tools);
    // a limit over all accounts of a provider is not offered any more (owner, ORCH-624); one saved earlier still
    // counts, so it shows here until it is cleared
    for (const t of m.together || []) if (t.limit != null) toolSection.append(togetherCard(t));
    const toolsBack = removedRow(gone.filter(r => r.type === 'helper-tool'), 'helper tool');
    if (toolsBack) toolSection.append(toolsBack);
    toolSection.append(addCard(m.providers || []));
    parts.push(toolSection);
    parts.push(history(m.history || []));
    parts.push(h('p', {className: 'meta', text: 'Logins and keys are never shown or kept here.'}));
    if (!embedded) {
      // opened outside the dashboard: a read-only page, so nothing may look clickable (ORCH-93 finding 5)
      parts.unshift(h('div', {className: 'banner info', role: 'status'}, h('p', {className: 'grow', text: 'Open Usage from the dashboard to change it.'})));
      for (const el of parts) el.querySelectorAll?.('input,select,button').forEach(c => { c.disabled = true; });
    }
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

// The Skills page (ORCH-834, draft A): tabs for skills, instructions, connected services and logins; a filter, a
// search, one list with an on/off switch per row; a click opens the side panel with what helpers see.
// It only reads from its own server (GET api/page). Turn off / Turn on is a click the dashboard runs as the person:
// the page names a verb and an item id (postMessage `orch.act`), the dashboard runs `orch skills act` and answers.
// The same click path deletes a skill into the Bin (`delete`), puts a Bin entry back (`restore`, never over a skill of
// that name) and makes a draft skill (`new`, target skill:workspace:<name>) (ORCH-841).
// All text is set with textContent; the look is the master kit only (no page sheet).
(() => {
  'use strict';
  const P = document.documentElement.dataset.prefix || '';
  const $ = id => document.getElementById(id);
  const embedded = window.parent !== window;
  const TABS = [['skills', 'Skills'], ['instructions', 'Instructions'], ['services', 'Connected services'], ['logins', 'Logins'], ['bin', 'Bin']];
  const WHERE = {orch: 'Comes with orch', workspace: 'This workspace', admin: 'Shared by your admin', mine: 'Your computer'};
  const RANK = {workspace: 0, admin: 1, mine: 2, orch: 3};
  const FIELDS = [['version', 'Version'], ['owner', 'Owner'], ['status', 'State'], ['platforms', 'Runs on'], ['requires', 'Needs'],
    ['requires-logins', 'Needs logins'], ['review-by', 'Look again on'], ['replaced-by', 'Use instead'], ['tags', 'Tags']];
  const STATUS = {active: 'In use', draft: 'Draft', deprecated: 'Old', retired: 'Retired'};
  const PLATFORM = {macos: 'Mac', windows: 'Windows', linux: 'Linux'};
  const NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
  let model = null, busy = false;
  const params = new URLSearchParams(location.search);
  const FILTERS = ['all', 'on', 'off', 'needs'];
  let tab = TABS.some(t => t[0] === params.get('tab')) ? params.get('tab') : 'skills';
  let filter = FILTERS.includes(params.get('show')) ? params.get('show') : 'all', query = '';

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
      window.parent.postMessage({type: 'orch.act', id, verb, target, chan: (window.OrchFrame || {}).chan}, location.origin);
    });
  }
  function say(text, kind, undo) {
    $('local-feedback').textContent = text;
    if (window.UI?.toast) window.UI.toast(text, undo || null, kind);
  }
  async function turn(it, on, control) {
    if (!embedded) { say('Open Skills from the dashboard to change it.', 'error'); return load(); }
    if (busy) return;
    busy = true;
    if (control) control.disabled = true;
    const r = await askDashboard(on ? 'on' : 'off', it.id);
    busy = false;
    if (r.ok && r.answer?.changed === false) say(it.name + ' was already ' + (on ? 'on' : 'off') + '.');
    else if (r.ok) say((on ? 'Turned on: ' : 'Turned off: ') + it.name + (on ? '' : '. Helpers no longer see it here.'), null, () => turn(it, !on));
    else say(r.error || 'That could not be saved. Nothing was changed.', 'error');
    await load(true);
  }

  async function change(verb, target, done, control) {
    if (!embedded) { say('Open Skills from the dashboard to change it.', 'error'); return false; }
    if (busy) return false;
    busy = true;
    if (control) control.disabled = true;
    const r = await askDashboard(verb, target);
    busy = false;
    if (!r.ok) { if (control) control.disabled = false; say(r.error || 'That could not be saved. Nothing was changed.', 'error'); }
    await load(true);
    if (r.ok) done();
    return r.ok;
  }
  function binRowOf(it) {
    return items('bin').filter(b => b.name === it.name && b.where === it.where && b.can_restore)
      .sort((a, b) => String(b.at).localeCompare(String(a.at)))[0];
  }
  function remove(it, control) {
    return change('delete', it.id, () => {
      const row = binRowOf(it);
      say('Moved to the Bin: ' + it.name + '. Helpers no longer see it.', null, row ? () => restore(row) : null);
    }, control);
  }
  function restore(row, control) {
    return change('restore', row.id, () => say('Restored: ' + row.name + '. It is back where it was.'), control);
  }

  // ---- drawing ----
  const items = k => (model && model[k]) || [];
  const needs = it => (it.problems || []).length > 0;
  function badge(it) {
    if (needs(it)) return h('span', {className: 'badge needs', text: 'Needs a look'});
    if (!it.on) return h('span', {className: 'badge paused', text: 'Off'});
    const st = it.fields?.status;
    if (st === 'draft') return h('span', {className: 'badge dashed', text: 'Draft'});
    if (st === 'retired' || st === 'deprecated') return h('span', {className: 'badge paused', text: STATUS[st]});
    return h('span', {className: 'badge done', text: 'On'});
  }
  function control(it) {
    if (!it.can_off) return it.locked && it.on && it.kind === 'skill' ? h('span', {className: 'chip outline', title: it.locked, text: 'Always on'}) : null;
    const s = h('input', {className: 'switch', type: 'checkbox', role: 'switch', 'aria-label': (it.on ? 'Turn off ' : 'Turn on ') + it.name});
    s.checked = it.on;
    s.addEventListener('click', e => { e.stopPropagation(); turn(it, s.checked, s); });
    return s;
  }
  function line(it) {
    if (needs(it)) return it.problems.join(' · ');
    if (it.note) return it.note;
    return it.description || '';
  }
  function rows() {
    return items(tab).slice()
      .sort((a, b) => (needs(b) - needs(a)) || (RANK[a.where] - RANK[b.where]) || a.name.localeCompare(b.name))
      .filter(it => filter === 'all' || (filter === 'on' && it.on) || (filter === 'off' && !it.on) || (filter === 'needs' && needs(it)))
      .filter(it => !query || (it.name + ' ' + (it.description || '')).toLowerCase().includes(query));
  }

  function drawTabs() {
    return h('div', {className: 'tabs', role: 'tablist', 'aria-label': 'What helpers get'}, TABS.map(([k, t]) => {
      const n = items(k).filter(needs).length;
      return h('button', {role: 'tab', type: 'button', 'aria-selected': String(k === tab), onclick: () => { tab = k; filter = 'all'; draw(); }},
        t + ' ', h('span', {className: 'meta', text: String(items(k).length)}), n ? h('sup', {className: 'count', 'aria-label': n + ' need a look', text: String(n)}) : null);
    }));
  }
  function drawTools() {
    const seg = h('div', {className: 'segmented', role: 'group', 'aria-label': 'Show'},
      [['all', 'All'], ['on', 'On'], ['off', 'Off'], ['needs', 'Needs a look']].map(([k, t]) =>
        h('button', {className: 'btn', type: 'button', 'aria-pressed': String(filter === k), text: t, onclick: () => { filter = k; draw(); }})));
    const search = h('input', {className: 'input', type: 'search', placeholder: 'Find by name or words', 'aria-label': 'Find', value: query});
    search.addEventListener('input', () => { query = search.value.toLowerCase(); $('list').replaceWith(drawList()); });
    const make = tab === 'skills' ? h('button', {className: 'btn outline', type: 'button', text: 'New skill', onclick: newSkill}) : null;
    return h('div', {className: 'list-tools'}, tab === 'bin' ? null : seg, search, make);
  }
  function binRows() {
    return items('bin').filter(b => !query || (b.name + ' ' + b.from).toLowerCase().includes(query));
  }
  const when = at => (window.UI?.stamp ? window.UI.stamp(at) : at) || '';
  function drawBin() {
    const list = binRows();
    if (!list.length) {
      return h('div', {id: 'list', className: 'empty-state'}, h('h3', {text: query ? 'Nothing here' : 'The Bin is empty'}),
        h('p', {className: 'muted', text: query ? 'No name matches “' + query + '”.' : 'Deleted skills wait here until you restore them. Nothing is removed by itself.'}));
    }
    return h('div', {id: 'list', className: 'table-wrap'}, h('table', {className: 'blk-table data-table'},
      h('caption', {className: 'sr-only', text: 'Bin'}),
      h('thead', {}, h('tr', {}, h('th', {scope: 'col', text: 'Name'}), h('th', {scope: 'col', text: 'From'}),
        h('th', {scope: 'col', text: 'Deleted'}), h('th', {scope: 'col'}, h('span', {className: 'sr-only', text: 'Restore'})))),
      h('tbody', {}, list.map(b => h('tr', {},
        h('td', {}, h('strong', {text: b.name}), b.note ? h('div', {className: 'meta', text: b.note}) : null),
        h('td', {'data-label': 'From', text: WHERE[b.where] || ''}),
        h('td', {'data-label': 'Deleted', text: when(b.at) + (b.by ? ' · ' + b.by : '')}),
        h('td', {className: 'cell-actions'}, h('div', {className: 'stack'},
          h('div', {className: 'row'}, h('button', {className: 'btn outline sm', type: 'button', text: 'Restore', disabled: !b.can_restore,
            'aria-describedby': b.why ? 'why-' + b.id : null, 'aria-label': 'Restore ' + b.name, onclick: e => restore(b, e.currentTarget)})),
          b.why ? h('p', {className: 'meta', id: 'why-' + b.id, text: b.why + '.'}) : null)))))));
  }
  function drawList() {
    if (tab === 'bin') return drawBin();
    const list = rows();
    if (!list.length) {
      return h('div', {id: 'list', className: 'empty-state'}, h('h3', {text: filter === 'needs' ? 'Nothing needs a look' : 'Nothing here'}),
        h('p', {className: 'muted', text: query ? 'No name or words match “' + query + '”.' : (filter === 'all' ? 'Helpers get nothing of this kind here.' : 'Show All to see everything.')}));
    }
    return h('div', {id: 'list', className: 'table-wrap'}, h('table', {className: 'data-table switch-table'},
      h('caption', {className: 'sr-only', text: TABS.find(t => t[0] === tab)[1]}),
      h('thead', {}, h('tr', {}, h('th', {scope: 'col'}, h('span', {className: 'sr-only', text: 'On'})), h('th', {scope: 'col', text: 'Name'}),
        h('th', {scope: 'col', text: 'From'}), h('th', {scope: 'col', text: 'State'}))),
      h('tbody', {}, list.map(it => h('tr', {tabindex: '0', 'aria-label': it.name, onclick: () => open(it), onkeydown: e => { if (e.key === 'Enter') open(it); }},
        h('td', {}, control(it)),
        h('td', {}, h('strong', {text: it.name}), h('div', {className: 'meta truncate', text: line(it)})),
        h('td', {className: 'nowrap', text: WHERE[it.where] || ''}),
        h('td', {}, badge(it)))))));
  }

  function facts(list) {
    return h('dl', {className: 'facts'}, list.filter(([, v]) => v).map(([k, v]) => [h('dt', {text: k}), h('dd', {text: v})]).flat());
  }
  function open(it) {
    const tools = Object.entries(it.tools || {});
    const f = it.fields || {};
    const sees = it.on ? h('div', {className: 'doc-box'}, h('strong', {text: it.name}), h('p', {className: 'meta', text: it.description || ''}))
      : h('p', {className: 'muted', text: it.note ? 'Off here. ' + it.note + '.' : 'Nothing: it is off here.'});
    const box = h('div', {className: 'stack'},
      h('div', {className: 'row'}, badge(it), h('span', {className: 'meta', text: WHERE[it.where] || ''})),
      needs(it) ? h('div', {className: 'banner warn', role: 'status'}, it.problems.map(p => h('p', {text: p}))) : null,
      it.kind === 'login' ? null : [h('p', {className: 'eyebrow', text: 'What helpers see'}), sees],
      facts([['File', it.file], ['Words', it.words ? String(it.words) : ''],
        ...tools.map(([t, s]) => [t, s === 'on' ? 'Sees it' : 'Off here']),
        ...FIELDS.map(([k, label]) => [label, k === 'status' ? (STATUS[f[k]] || f[k]) : k === 'platforms' && f[k] ? f[k].split(',').map(x => PLATFORM[x.trim()] || x.trim()).join(', ') : f[k]]),
        ...Object.entries(f).filter(([k]) => !FIELDS.some(x => x[0] === k))]),
      h('div', {className: 'row'}, it.can_off ? h('button', {className: 'btn outline', type: 'button', text: it.on ? 'Turn off' : 'Turn on',
        onclick: e => { d.close(); turn(it, !it.on, e.currentTarget); }}) : null),
      it.locked ? h('p', {className: 'meta', text: it.locked + '.'}) : null,
      it.can_delete ? h('section', {className: 'stack', 'aria-label': 'Delete'},  // apart from Turn off: the one destructive action, last
        h('p', {className: 'eyebrow', text: 'Delete'}),
        h('p', {className: 'meta', text: it.where === 'mine'
          ? 'Delete takes it away from every workspace on this computer. A copy stays in the Bin; you can restore it.'
          : 'Delete moves it to the Bin; you can restore it.'}),
        h('div', {className: 'row'}, h('button', {className: 'btn danger', type: 'button', text: 'Delete', onclick: e => { d.close(); remove(it, e.currentTarget); }}))) : null);
    const d = h('dialog', {className: 'sheet', 'aria-label': it.name}, h('div', {className: 'sheet-h'}, h('h2', {text: it.name})), box);
    d.addEventListener('close', () => d.remove(), {once: true});
    document.body.append(d);
    d.showModal();
  }

  function newSkill() {
    const input = h('input', {className: 'input', type: 'text', id: 'new-name', autocomplete: 'off', spellcheck: 'false', maxlength: '64',
      placeholder: 'weekly-report', 'aria-describedby': 'new-hint'});
    const hint = h('p', {className: 'meta', id: 'new-hint', text: 'Small letters, digits and dashes. It starts as a draft in this workspace; you fill in what it does.'});
    const make = h('button', {className: 'btn primary', type: 'submit', text: 'Make skill'});
    const taken = new Set(items('skills').map(i => i.name));
    const problem = v => !v ? 'Give the skill a name.' : !NAME.test(v) ? 'Use small letters, digits and single dashes, like weekly-report.'
      : taken.has(v) ? 'A skill with this name is already here. Pick another name.' : '';
    const form = h('form', {className: 'stack', novalidate: true},
      h('label', {className: 'field', for: 'new-name'}, 'Name', input), hint,
      h('div', {className: 'actions'}, h('button', {className: 'btn outline', type: 'button', text: 'Cancel', onclick: () => d.close()}), make));
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const name = input.value.trim();
      const bad = problem(name);  // checked when the person presses Make, said next to the field
      input.setAttribute('aria-invalid', String(!!bad));
      hint.className = bad ? 'meta err' : 'meta';
      if (bad) { hint.textContent = bad; input.focus(); return; }
      const ok = await change('new', 'skill:workspace:' + name, () => say('Made the draft skill ' + name + '.'), make);
      if (ok) d.close();
    });
    const d = h('dialog', {className: 'dialog', 'aria-label': 'New skill'}, h('h2', {text: 'New skill'}), form);
    d.addEventListener('close', () => d.remove(), {once: true});
    document.body.append(d);
    d.showModal();
    input.focus();
  }

  function draw() {
    try {  // the dashboard's sandboxed frame may refuse; its own history state (the frame channel) is kept
      const u = new URL(location.href);
      u.searchParams.set('tab', tab);
      if (filter === 'all') u.searchParams.delete('show'); else u.searchParams.set('show', filter);
      history.replaceState(history.state, '', u);
    } catch (_) { /* the view still draws; only the address does not follow */ }
    $('loaded').replaceChildren(drawTabs(), drawTools(), drawList());
  }
  function show(which) {
    for (const id of ['loading', 'error', 'loaded']) $(id).hidden = id !== which;
    $('view-region').setAttribute('aria-busy', String(which === 'loading'));
  }
  async function load(fresh) {
    try {
      const r = await fetch(P + '/api/page' + (fresh ? '?fresh=1' : ''), {cache: 'no-store'});
      if (!r.ok) throw new Error((await r.text()).slice(0, 200) || 'No answer.');
      model = await r.json();
      show('loaded');
      draw();
    } catch (e) {
      $('error-text').textContent = e.message || 'No answer.';
      show('error');
    }
  }
  $('retry').addEventListener('click', () => { show('loading'); load(true); });
  load();
})();

// The Skills page (ORCH-834, draft A): tabs for skills, instructions, connected services and logins; a filter, a
// search, one list with an on/off switch per row; a click opens the side panel with what helpers see.
// It only reads from its own server (GET api/page, api/item). Turn off / Turn on is a click the dashboard runs as the
// person: the page names a verb and an item id (postMessage `orch.act`), the dashboard runs `orch skills act` and answers.
// Edit (ORCH-840): the panel's form; Save is `orch.save` with the opaque edit id, the loaded revision and the text.
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
  const RANK = {workspace: 0, admin: 1, mine: 2, orch: 3, account: 4};
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
    else if (d.type === 'orch.save.done') asked.get(d.id)({ok: true, revision: String(d.revision || ''), changed: d.changed !== false});
    else if (d.type === 'orch.save.failed') asked.get(d.id)({ok: false, stale: d.stale === true, error: typeof d.error === 'string' ? d.error.slice(0, 300) : ''});
  });
  // Save in the editor: the page names the item's opaque edit id, the revision it loaded and the text; the dashboard
  // runs `orch skills act save` as the person, only right after this Save click.
  function askSave(target, revision, text) {
    return new Promise(resolve => {
      const id = Array.from(crypto.getRandomValues(new Uint8Array(12)), b => (b % 36).toString(36)).join('');
      const timer = setTimeout(() => finish({ok: false, error: 'The dashboard did not answer. Reload the page and look whether it was saved.'}), 60000);
      function finish(r) { clearTimeout(timer); asked.delete(id); resolve(r); }
      asked.set(id, finish);
      window.parent.postMessage({type: 'orch.save', id, target, revision, text, chan: (window.OrchFrame || {}).chan}, location.origin);
    });
  }
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
    if (r.ok && r.answer?.changed === false) say(plain(it.name) + ' was already ' + (on ? 'on' : 'off') + '.');
    else if (r.ok) say((on ? 'Turned on: ' : 'Turned off: ') + plain(it.name) + (on ? '' : '. Helpers no longer see it here.'), null, () => turn(it, !on));
    else say(r.error || 'That could not be saved. Nothing was changed.', 'error');
    await load(true);
  }
  const ACT = {remove: 'Remove from here', restore: 'Get it back', check: 'Check sign-in'};
  async function other(it, verb, control) {
    if (!embedded) { say('Open Skills from the dashboard to change it.', 'error'); return load(); }
    if (busy) return;
    busy = true;
    if (control) { control.disabled = true; control.textContent = verb === 'check' ? 'Checking…' : control.textContent; }
    const r = await askDashboard(verb, it.id);
    busy = false;
    if (r.ok) say(r.answer?.next || 'Done.');
    else say(r.error || 'That did not work. Nothing was changed.', 'error');
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
      say('Moved to the Bin: ' + plain(it.name) + '. Helpers no longer see it.', null, row ? () => restore(row) : null);
    }, control);
  }
  function restore(row, control) {
    return change('restore', row.id, () => say('Restored: ' + row.name + '. It is back where it was.'), control);
  }

  // ---- drawing ----
  const items = k => (model && model[k]) || [];
  const needs = it => (it.problems || []).length > 0;
  // ORCH-1692: a name in plain words ("release-check" -> "Release check"); the file name stays in the panel
  // report r-1127-0540-ws: words that have their own spelling ("github-links" -> "GitHub links", not "Github links")
  const WORDS = {github: 'GitHub', gitlab: 'GitLab', openai: 'OpenAI', api: 'API', ui: 'UI', ux: 'UX', cli: 'CLI', mcp: 'MCP',
    ai: 'AI', pdf: 'PDF', url: 'URL', vps: 'VPS', ssh: 'SSH', css: 'CSS', html: 'HTML', json: 'JSON', e2e: 'E2E', ios: 'iOS',
    macos: 'macOS', vm: 'VM', pr: 'PR', crm: 'CRM', sql: 'SQL', orch: 'orch'};
  const word = x => (Object.hasOwn(WORDS, x.toLowerCase()) ? WORDS[x.toLowerCase()] : null);  // "constructor" is a word too
  const plain = name => {
    const w = String(name || '').replace(/[-_]+/g, ' ').trim().split(/\s+/).filter(Boolean).map(x => word(x) || x);
    if (!w.length) return '';
    if (!word(w[0])) w[0] = w[0][0].toUpperCase() + w[0].slice(1);
    return w.join(' ');
  };
  // a skill's own description is written for helpers: the list shows its first sentence in plain words, without
  // brackets ("(tool:fix-it, /tool:review)", "(Workspace copy of ...)"), shouting ("ANY") or the "Use when" lead
  const plainLine = text => {
    let s = String(text || '').replace(/\s*\([^()]*(?:\)|$)/g, '').replace(/\s+/g, ' ').trim();
    const end = s.search(/[.!?](\s|$)/);
    if (end > 0) s = s.slice(0, end + 1);
    s = s.replace(/\b([A-Z]{3,})\b/g, (m, x) => (word(x) ? m : x.toLowerCase()))
      .replace(/^Use (?:this )?(?:skill )?(when|for|before|after|while|if) /i, (m, x) => x[0].toUpperCase() + x.slice(1) + ' ')
      .replace(/\s+([,.;:])/g, '$1');
    return s;
  };
  function badge(it) {
    if (needs(it)) return h('span', {className: 'badge needs', text: 'Needs a look'});
    if (it.removed) return h('span', {className: 'badge paused', text: it.newer ? 'Newer version' : 'Removed'});
    if (!it.on) return h('span', {className: 'badge paused', text: 'Off'});
    const st = it.fields?.status;
    if (st === 'draft') return h('span', {className: 'badge dashed', text: 'Draft'});
    if (st === 'retired' || st === 'deprecated') return h('span', {className: 'badge paused', text: STATUS[st]});
    return h('span', {className: 'badge done', text: 'On'});
  }
  const from = it => it.from || WHERE[it.where] || '';
  function control(it) {
    if (needs(it)) return null;  // ORCH-1692: a skill that needs a look never shows a green switch; Turn off is in its panel
    if (it.manage_in) return h('span', {className: 'chip outline', title: 'Turn it on or off in ' + it.manage_in, text: 'Manage in ' + it.manage_in});
    if (!it.can_off) return it.locked && it.on && it.kind === 'skill' ? h('span', {className: 'chip outline', title: it.locked, text: 'Always on'}) : null;
    const s = h('input', {className: 'switch', type: 'checkbox', role: 'switch', 'aria-label': (it.on ? 'Turn off ' : 'Turn on ') + plain(it.name)});
    s.checked = it.on;
    s.addEventListener('click', e => { e.stopPropagation(); turn(it, s.checked, s); });
    return s;
  }
  function line(it) {
    if (needs(it)) return it.problems.join(' · ');
    if (it.newer) return it.newer;
    if (it.note) return it.note;
    if (it.kind === 'service' && it.signin_state) return it.signin;
    return plainLine(it.description);
  }
  function rows() {
    return items(tab).slice()
      .sort((a, b) => (needs(b) - needs(a)) || (RANK[a.where] - RANK[b.where]) || a.name.localeCompare(b.name))
      .filter(it => filter === 'all' || (filter === 'on' && it.on) || (filter === 'off' && !it.on) || (filter === 'needs' && needs(it)))
      .filter(it => !query || (it.name + ' ' + plain(it.name) + ' ' + (it.description || '')).toLowerCase().includes(query));
  }

  function drawTabs() {
    return h('div', {className: 'tabs', role: 'tablist', 'aria-label': 'What helpers get'}, TABS.map(([k, t]) => {
      // ORCH-1692: one count per tab ("Skills 30 3" said two numbers); how many need a look is on the filter
      return h('button', {role: 'tab', type: 'button', 'aria-selected': String(k === tab), onclick: () => { tab = k; filter = 'all'; draw(); }},
        t + ' ', h('span', {className: 'meta', text: String(items(k).length)}));
    }));
  }
  function drawTools() {
    const seg = h('div', {className: 'segmented', role: 'group', 'aria-label': 'Show'},
      [['all', 'All'], ['on', 'On'], ['off', 'Off'], ['needs', 'Needs a look' + (items(tab).some(needs) ? ' (' + items(tab).filter(needs).length + ')' : '')]].map(([k, t]) =>
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
  const checked = () => model?.services_checked_at ? ' Last checked ' + when(model.services_checked_at) + '.' : '';
  // One master empty state (UI.state) per case, each with its one next step (SX-10, R7.2).
  const NONE = {
    skills: {title: 'No skills yet', text: 'A skill teaches your helpers one job, step by step.', action: {label: 'New skill', onClick: () => newSkill()}},
    instructions: {title: 'No instruction files yet', text: 'Helpers read files such as AGENTS.md here when they start. Add one in your workspace folder.', action: {label: 'Look again', onClick: () => load(true)}},
    services: {title: 'No connected services yet', text: 'Services you connect in your helper tool show up here.', action: {label: 'Look again', onClick: () => load(true)}},
    logins: {title: 'No logins yet', text: 'Keys you keep with orch (orch secret add in your terminal) show up here.', action: {label: 'Look again', onClick: () => load(true)}},
  };
  function emptyList(o) { const d = h('div', {id: 'list'}); d.append(window.UI.state(Object.assign({kind: 'empty'}, o))); return d; }
  function clearSearch() { query = ''; draw(); document.querySelector('.list-tools input[type=search]')?.focus(); }
  function drawBin() {
    const list = binRows();
    if (!list.length) {
      return emptyList(query ? {title: 'Nothing matches “' + query + '”', text: 'Try another name.', action: {label: 'Clear search', onClick: clearSearch}}
        : {title: 'The Bin is empty', text: 'Deleted skills wait here until you restore them. Nothing is removed by itself.', action: {label: 'Show skills', onClick: () => { tab = 'skills'; filter = 'all'; draw(); }}});
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
      if (query) return emptyList({title: 'Nothing matches “' + query + '”', text: 'Try another name or word.', action: {label: 'Clear search', onClick: clearSearch}});
      if (filter !== 'all') return emptyList({title: filter === 'needs' ? 'Nothing needs a look' : filter === 'on' ? 'Nothing is on' : 'Nothing is off',
        text: 'The whole list is under All.', action: {label: 'Show all', onClick: () => { filter = 'all'; draw(); }}});
      return emptyList(NONE[tab]);
    }
    // O-29 (owner 28 Nov): in a page area under 900 px (beside the Focus panel) the From column moves under the name as
    // grey text, State keeps its full width and the description gets two lines instead of ending in "…" after a few
    // words. The page is a frame, so its own width is the page area. Up to 720 px the kit's card form hides the third
    // cell (From) and puts State under the name: that cell stays in the row there, only its words also sit under the name.
    const narrow = roomNarrow(), cards = narrow && roomCards(), cols = !narrow || cards;
    drawnForm = formNow();
    return h('div', {id: 'list', className: 'table-wrap'}, h('table', {className: 'data-table switch-table'},
      h('caption', {className: 'sr-only', text: TABS.find(t => t[0] === tab)[1]}),
      h('thead', {}, h('tr', {}, h('th', {scope: 'col'}, h('span', {className: 'sr-only', text: 'On'})), h('th', {scope: 'col', text: 'Name'}),
        cols ? h('th', {scope: 'col', text: 'From'}) : null, h('th', {scope: 'col', text: 'State'}))),
      h('tbody', {}, list.map(it => h('tr', {tabindex: '0', 'aria-label': plain(it.name), onclick: () => open(it), onkeydown: e => { if (e.key === 'Enter') open(it); }},
        h('td', {}, control(it)),
        narrow ? h('td', {}, h('strong', {text: plain(it.name)}),
          from(it) ? h('div', {className: 'meta', 'data-from': '', text: from(it)}) : null,
          h('div', {className: 'meta', title: line(it), text: twoLines(line(it))}),
          it.copy ? h('div', {className: 'meta', text: it.copy}) : null)
          : h('td', {}, h('strong', {text: plain(it.name)}), h('div', {className: 'meta truncate', text: line(it)}),
            it.copy ? h('div', {className: 'meta truncate', text: it.copy}) : null),  // in the name cell: From is hidden on a phone
        cols ? h('td', {className: 'nowrap', 'aria-hidden': narrow ? 'true' : null, text: from(it)}) : null,
        h('td', {className: narrow ? 'nowrap' : null}, badge(it)))))));
  }
  let drawnForm = 'wide';
  const roomNarrow = () => { const w = Number(window.innerWidth) || 0; return w > 0 && w < 900; };
  const roomCards = () => (Number(window.innerWidth) || 0) <= 720;
  const formNow = () => (!roomNarrow() ? 'wide' : roomCards() ? 'cards' : 'narrow');
  // Two lines of the text column: what fits beside the switch and the State pill at this width, cut at a word.
  function twoLines(text) {
    const w = Number(window.innerWidth) || 800, beside = w <= 720 ? 130 : 300;  // the switch, and from 721 px the State column too
    const t = String(text || ''), room = Math.max(40, Math.floor((w - beside) / 6.5) * 2 - 4);
    return t.length <= room ? t : t.slice(0, room).replace(/\s+\S*$/, '') + '…';
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
      h('div', {className: 'row'}, badge(it), h('span', {className: 'meta', text: from(it)})),
      needs(it) ? h('div', {className: 'banner warn', role: 'status'}, it.problems.map(p => h('p', {text: p}))) : null,
      it.newer ? h('div', {className: 'banner info', role: 'status'}, h('p', {text: it.newer + '.'})) : null,
      it.kind === 'login' ? (it.switch ? h('div', {className: 'stack'},
        h('p', {text: it.on ? it.on_means + '.' : it.off_means + '.'}),
        h('p', {className: 'meta', text: (it.on ? it.off_means : it.on_means) + '.'}),
        h('p', {className: 'meta', text: it.scope + '.'})) : null)
        : it.removed ? null : [h('p', {className: 'eyebrow', text: 'What helpers see'}), sees],
      facts([['File', it.file], ['Words', it.words ? String(it.words) : ''], ['Sign-in', it.signin],
        ...tools.map(([t, s]) => [t, s === 'on' ? 'Sees it' : 'Off here']),
        ...FIELDS.map(([k, label]) => [label, k === 'status' ? (STATUS[f[k]] || f[k]) : k === 'platforms' && f[k] ? f[k].split(',').map(x => PLATFORM[x.trim()] || x.trim()).join(', ') : f[k]]),
        ...Object.entries(f).filter(([k]) => !FIELDS.some(x => x[0] === k))]),
      h('div', {className: 'row'},
        it.edit ? h('button', {className: 'btn primary', type: 'button', text: 'Edit', onclick: () => edit(it, d)}) : null,
        it.can_off ? h('button', {className: 'btn outline', type: 'button', text: it.on ? 'Turn off' : 'Turn on',
          onclick: e => { d.close(); turn(it, !it.on, e.currentTarget); }}) : null,
        (it.actions || []).map(v => h('button', {className: v === 'remove' ? 'btn danger' : 'btn outline', type: 'button', text: ACT[v],
          onclick: e => { d.close(); other(it, v, e.currentTarget); }}))),
      (it.actions || []).includes('check') && it.check_hint ? h('p', {className: 'meta', text: it.check_hint + '.' + checked()}) : null,
      it.manage_in ? h('p', {className: 'meta', text: 'Manage in ' + it.manage_in + ': it is turned on or off there, not here.'}) : null,
      it.copy ? h('p', {className: 'meta', text: it.copy + '. ' + (it.copy_hint || '')}) : null,
      it.tool_limit ? h('p', {className: 'meta', text: it.tool_limit + '.'}) : null,
      it.locked ? h('p', {className: 'meta', text: it.locked + '.'}) : null,
      !it.edit && it.edit_why ? h('p', {className: 'meta', text: 'Edit: ' + it.edit_why + '.'}) : null,
      it.can_delete ? h('section', {className: 'stack', 'aria-label': 'Delete'},  // apart from Turn off: the one destructive action, last
        h('p', {className: 'eyebrow', text: 'Delete'}),
        h('p', {className: 'meta', text: it.where === 'mine'
          ? 'Delete takes it away from every workspace on this computer. A copy stays in the Bin; you can restore it.'
          : 'Delete moves it to the Bin; you can restore it.'}),
        h('div', {className: 'row'}, h('button', {className: 'btn danger', type: 'button', text: 'Delete', onclick: e => { d.close(); remove(it, e.currentTarget); }}))) : null);
    const d = h('dialog', {className: 'sheet', 'aria-label': plain(it.name)}, h('div', {className: 'sheet-h'}, h('h2', {text: plain(it.name)})), box);
    d.addEventListener('close', () => d.remove(), {once: true});
    // × Close, Esc and a click outside all close through d.close(): with unsaved changes the panel stays and says so
    d.close = value => {
      if (d.dataset.dirty === '1') {
        const u = d.querySelector('[data-unsaved]');
        if (u) { u.hidden = false; u.scrollIntoView?.({block: 'nearest'}); }
        return;
      }
      HTMLDialogElement.prototype.close.call(d, value);
    };
    document.body.append(d);
    d.showModal();
  }

  // ---- the editor (ORCH-840) ----
  // Everything from the file is put into form fields as their value (never as HTML), so a skill's text cannot run.
  const STATE_WORDS = [['', 'Not set'], ['active', 'In use'], ['draft', 'Draft'], ['deprecated', 'Old'], ['retired', 'Retired']];
  const FORM = [['owner', 'Owner', ''], ['requires', 'Needs these programs', 'for example node, uv'], ['requires-logins', 'Needs these logins', 'for example github'],
    ['version', 'Version', ''], ['tags', 'Tags', 'for example ui, design'], ['replaced-by', 'Use instead', 'name of the newer skill']];
  function field(label, control, hint) {
    return h('label', {className: 'field'}, label, control, hint ? h('span', {className: 'meta', text: hint}) : null);
  }
  function input(value, extra) { const i = h('input', {className: 'input', type: 'text', ...extra}); i.value = value || ''; return i; }
  function area(value, extra) { const t = h('textarea', {className: 'input', spellcheck: 'false', ...extra}); t.value = value || ''; return t; }
  async function edit(it, d) {
    const box = d.querySelector('.stack');
    box.replaceChildren(h('p', {className: 'muted', text: 'Loading…'}));
    let item;
    try {
      const r = await fetch(P + '/api/item/' + encodeURIComponent(it.edit.id), {cache: 'no-store'});
      if (!r.ok) throw new Error((await r.text()).slice(0, 300) || 'No answer.');
      item = await r.json();
    } catch (e) {
      box.replaceChildren(h('div', {className: 'banner error', role: 'alert'}, h('p', {text: e.message || 'It could not be opened.'})));
      return;
    }
    d.querySelector('.sheet-h h2').textContent = 'Edit ' + item.name;
    const banner = h('div', {className: 'banner error', role: 'alert', hidden: true});
    const unsaved = h('div', {className: 'banner attn', role: 'status', hidden: true, 'data-unsaved': ''},
      h('p', {text: 'Your changes are not saved yet. Save them, or press Cancel to drop them.'}));
    const ctl = {};
    let parts;
    if (item.mode === 'skill') {
      const f = item.fields || {};
      ctl.description = area(f.description, {rows: '4', maxlength: '1024'});
      ctl.status = h('select', {}, STATE_WORDS.concat(STATE_WORDS.some(([k]) => k === f.status) ? [] : [[f.status, f.status]]).map(([k, t]) => h('option', {value: k, text: t})));
      ctl.status.value = f.status || '';
      const known = (f.platforms || '').split(',').map(x => x.trim()).filter(Boolean);
      const plain = known.every(x => PLATFORM[x]);
      if (plain) {
        ctl.platforms = h('div', {className: 'row', role: 'group', 'aria-label': 'Runs on'}, Object.entries(PLATFORM).map(([k, t]) => {
          const c = h('input', {type: 'checkbox', value: k}); c.checked = known.includes(k);
          return h('label', {className: 'check-label'}, c, t);
        }));
        ctl.platforms.read = () => Array.from(ctl.platforms.querySelectorAll('input:checked'), c => c.value).join(', ');
      } else {
        const i = input(f.platforms); ctl.platforms = i; i.read = () => i.value;
      }
      ctl['review-by'] = input(f['review-by'], {type: 'date'});
      for (const [k] of FORM) ctl[k] = input(f[k], {placeholder: FORM.find(x => x[0] === k)[2] || null});
      ctl.body = area(item.body, {rows: '16', className: 'input mono', 'aria-label': 'Steps for the helper'});
      parts = [
        field('What it does and when to use it', ctl.description, 'Helpers read this in every session, so keep it short.'),
        h('div', {className: 'grid-2'}, field('State', ctl.status), field('Owner', ctl.owner)),
        h('div', {className: 'field'}, h('span', {text: 'Runs on'}), ctl.platforms),
        h('div', {className: 'grid-2'}, field('Needs these programs', ctl.requires), field('Needs these logins', ctl['requires-logins'])),
        h('div', {className: 'grid-2'}, field('Look at it again on', ctl['review-by']), field('Version', ctl.version)),
        h('div', {className: 'grid-2'}, field('Tags', ctl.tags), field('Use instead', ctl['replaced-by'])),
        field('Steps for the helper', ctl.body),
      ];
    } else {
      ctl.text = area(item.text, {rows: '22', className: 'input mono', 'aria-label': 'What helpers read'});
      parts = [field(it.kind === 'skill' ? 'The whole skill file' : 'What helpers read', ctl.text,
        it.kind === 'skill' ? 'Its header could not be shown as a form, so it is edited as text.' : 'Helpers in this workspace read this file at every start.')];
    }
    const payload = () => {
      if (item.mode !== 'skill') return {text: ctl.text.value};
      const fields = {description: ctl.description.value, status: ctl.status.value, platforms: ctl.platforms.read()};
      for (const k of ['review-by', ...FORM.map(x => x[0])]) fields[k] = ctl[k].value;
      return {fields, body: ctl.body.value};
    };
    const first = JSON.stringify(payload());
    const dirty = () => JSON.stringify(payload()) !== first;
    box.oninput = box.onchange = () => { d.dataset.dirty = dirty() ? '1' : ''; if (!dirty()) unsaved.hidden = true; };
    const save = h('button', {className: 'btn primary', type: 'button', text: 'Save'});
    const cancel = h('button', {className: 'btn ghost', type: 'button', text: 'Cancel', onclick: () => { d.dataset.dirty = ''; d.close(); }});
    save.addEventListener('click', async () => {
      if (busy) return;
      if (!dirty()) { say('Nothing changed.'); d.dataset.dirty = ''; d.close(); return; }
      if (!embedded) { banner.replaceChildren(h('p', {text: 'Open Skills from the dashboard to save.'})); banner.hidden = false; return; }
      busy = true; save.disabled = true; save.textContent = 'Saving…'; banner.hidden = true;
      const fields = Array.from(box.querySelectorAll('input, select, textarea'));
      for (const f of fields) f.disabled = true;   // nothing typed meanwhile can be lost
      const r = await askSave(item.id, item.revision, JSON.stringify(payload()));
      for (const f of fields) f.disabled = false;
      busy = false; save.disabled = false; save.textContent = 'Save';
      if (r.ok) {
        d.dataset.dirty = '';
        d.close();
        say(r.changed ? 'Saved ' + item.name + '. A copy of the old version is kept.' : 'Nothing changed in ' + item.name + '.');
        await load(true);
        return;
      }
      banner.replaceChildren(h('p', {text: r.error || 'That could not be saved. Nothing was changed.'}));
      if (r.stale) banner.append(h('div', {className: 'row'}, h('button', {className: 'btn outline sm', type: 'button', text: 'Load the newer version',
        onclick: () => { d.dataset.dirty = ''; edit(it, d); }})));
      banner.hidden = false;
      banner.scrollIntoView?.({block: 'nearest'});
    });
    box.replaceChildren(banner, unsaved, ...parts, h('div', {className: 'sheet-actions'}, save, cancel));
    (ctl.description || ctl.text).focus();
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
    const intro = tab === 'services' ? h('p', {className: 'meta', text: 'Connected services (MCP servers) your helpers can use.' + checked()}) : null;
    $('loaded').replaceChildren(...[drawTabs(), intro, drawTools(), drawList()].filter(Boolean));
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
  // the list is drawn again only when the room crosses into or out of the narrow form (never on every resize step)
  addEventListener('resize', () => { if (model && tab !== 'bin' && formNow() !== drawnForm && $('list')) $('list').replaceWith(drawList()); });
  load();
})();

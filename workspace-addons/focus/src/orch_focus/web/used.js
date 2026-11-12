// What the agent used (skills, tools, connections), the helper tree, and the "All live" back link on a ticket page.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, P, TID, INAPP, els, keyOf, stamp} = S;
  // Visible text never says MCP or VPN and never shows a raw ticket id; "mcp__github__x" reads as "github__x".
  const text = value => String(value ?? '').replace(/\bmcp__/gi, '').replace(/\bVPN\b/gi, 'network').replace(/\bMCP\b/gi, 'connection').replace(/\bt_[a-z0-9]{6,16}\b/g, '');
  const KIND = {skill: 'Skill', tool: 'Tool', mcp: 'Connection'};
  const FROM = {harness: 'the agent tool', admin: 'the admin', workspace: 'this workspace', builtin: 'built in', marketplace: 'an add-on'};

  /* A small label after a step: "Skill · review", "Tool · Bash", "Connection · github · create issue". */
  function chip(used, withName = true) {
    if (!used || !KIND[used.kind]) return null;
    let label = KIND[used.kind];
    if (withName && used.name) label += ' · ' + text(used.name);
    if (withName && used.kind === 'mcp' && used.action) label += ' · ' + text(used.action);
    return h('span', {class: 'fx-used fx-used-' + used.kind, text: label});
  }

  function renderUsed(v) {
    const rows = (v.board && v.board.used) || [];
    const tab = els.tabs && els.tabs[3];
    if (tab) { tab.textContent = 'Used'; if (rows.length) tab.append(h('sup', {text: ' ' + rows.length})); }
    const key = keyOf(rows);
    if (!els.paneUsed || key === els.paneUsed.dataset.k) return;
    els.paneUsed.dataset.k = key;
    const content = h('div', {class: 'fx-results fx-used-page'}, h('h2', {text: 'What the agent used'}));
    if (!rows.length) content.append(h('p', {class: 'meta', text: 'Nothing used yet.'}));
    else {
      const note = u => text(u.note).trim();
      const notes = rows.some(u => note(u));  // the Note column only when some row has a note
      const head = h('tr', {}, ['What', 'Name', 'From', 'How often', ...(notes ? ['Note'] : [])].map(t => h('th', {scope: 'col', text: t})));
      const body = rows.map(u => h('tr', {},
        h('td', {}, chip(u, false)),
        h('td', {}, h('span', {text: text(u.name)}), u.kind === 'mcp' && (u.actions || []).length ? h('span', {class: 'fx-used-acts', text: u.actions.map(text).join(', ')}) : null),
        h('td', {text: FROM[u.source] || ''}),
        h('td', {class: 'fx-used-n', text: String(u.count ?? '')}),
        notes ? h('td', {text: note(u)}) : null));
      content.append(h('div', {class: 'fx-used-wrap'}, h('table', {class: 'fx-used-table'}, h('thead', {}, head), h('tbody', {}, body))));
    }
    els.paneUsed.replaceChildren(content);
  }

  /* The files the agent read or changed (display only: the paths come from the record and are never opened here). */
  const HOW = {read: 'Read', changed: 'Changed', touched: 'Used'};
  const SAFE = p => typeof p === 'string' && p.length <= 260 && !p.startsWith('/') && !/[\\\x00-\x1f\x7f]/.test(p) && !p.split('/').some(x => x === '..' || x === '' || x === '.');
  /* The files this ticket shares with another live ticket: path -> the other tickets ({ticket, key, title, how}). */
  function sharedFiles() {
    const out = new Map();
    for (const c of (S.state.live && S.state.live.same_file) || []) {
      const tickets = Array.isArray(c && c.tickets) ? c.tickets : [];
      if (typeof c.path !== 'string' || !tickets.some(t => t.ticket === TID)) continue;
      const others = tickets.filter(t => t.ticket !== TID);
      if (others.length) out.set(c.path, others);
    }
    return out;
  }
  const keyText = t => text(t.key) || 'another ticket';

  function renderFiles(v) {
    const rows = ((v.board && v.board.files) || []).filter(f => SAFE(f.path));
    const tab = els.tabs && els.tabs[2];
    if (tab) { tab.textContent = 'Files'; if (rows.length) tab.append(h('sup', {text: ' ' + rows.length})); }
    const shared = sharedFiles();
    const key = keyOf([rows, [...shared]]);
    if (!els.paneFiles || key === els.paneFiles.dataset.k) return;
    els.paneFiles.dataset.k = key;
    const content = h('div', {class: 'fx-results fx-files-page'}, h('h2', {text: 'Files this ticket touched'}));
    if (!rows.length) content.append(h('p', {class: 'meta', text: 'No files yet. A file shows up here when a step reads or changes it; some steps do not name a file.'}));
    else content.append(h('ul', {class: 'fx-files-list'}, rows.map(f => {
      const others = shared.get(f.path);
      return h('li', {class: 'fx-file' + (others ? ' shared' : '')},
        h('span', {class: 'fx-file-ic', 'aria-hidden': 'true', text: window.FocusHelpers.fileIcon(f.path)}),
        h('span', {class: 'fx-file-main'}, h('span', {class: 'fx-file-path', text: text(f.path)}),
          others ? h('span', {class: 'fx-file-why', text: 'Also open in ' + others.map(keyText).join(', ')}) : null),
        h('span', {class: 'fx-file-how', text: HOW[f.how] || 'Used'}),
        h('time', {class: 'fx-file-at', datetime: f.at || null, text: stamp(f.at)}));
    })));
    els.paneFiles.replaceChildren(content);
  }

  /* At the top of the Live tab: "📊 budget-2026.xlsx is also open in PIL-1 Plan the offsite agenda. Open PIL-1" */
  function renderClash() {
    if (!els.clash) return;
    const shared = sharedFiles();
    const key = keyOf([...shared]);
    if (key === els.clash.dataset.k) return;
    els.clash.dataset.k = key;
    els.clash.replaceChildren(...[...shared].slice(0, 3).map(([path, others]) => {
      const o = others[0];
      return h('p', {class: 'fx-clash', role: 'status'},
        h('span', {'aria-hidden': 'true', text: '⚠ '}), S.docName(text(path)), ' is also open in ',
        h('b', {text: [keyText(o), o.title !== o.key ? text(o.title) : ''].filter(Boolean).join(' ')}), '. ',
        h('a', {href: P + '/t/' + encodeURIComponent(o.ticket), text: 'Open ' + keyText(o)}));
    }));
  }

  /* The green chip after the title: the area this ticket works in (from /api/areas, a label only). */
  function renderArea() {
    if (!els.areaChip) return;
    const list = (S.state.areas && S.state.areas.areas) || [];
    const mine = list.filter(a => Array.isArray(a.tickets) && a.tickets.includes(TID));
    const area = mine.find(a => a.state === 'accepted') || null;
    const name = area ? text(area.name) : '';
    if (els.areaChip.textContent !== name) els.areaChip.textContent = name;
    els.areaChip.hidden = !name;
    if (area) els.areaChip.title = 'Area: ' + text(area.path);
  }

  /* "Working on this" in the left rail: the main agent, its helpers nested under their parent, each with what it
     does now. Picking a helper shows that helper's own view in the middle; Main (or the picked row again) goes back. */
  function pickAgent(agent, focusRow = true) {
    S.state.agentFilter = agent;
    const v = S.state.view;
    if (!v) return;
    const at = agent || 'main';
    renderTree(v); S.state.lastFeedKey = ''; S.views.live.renderFeed(v);
    if (focusRow) els.helpers.querySelector('.fx-agent[data-agent="' + CSS.escape(at) + '"]')?.focus();  // the row is drawn again; keep the keyboard on it
  }

  function renderTree(v) {
    const tree = (v.board && v.board.helper_tree) || [];
    const now = (v.board && v.board.agent_now) || {};
    const known = new Set(['main', ...tree.map(x => x.agent)]);
    if (!known.has(S.state.agentFilter) || S.state.agentFilter === 'main') S.state.agentFilter = null;
    const show = tree.length || v.run.running || v.run.run;
    const key = keyOf([tree, now, S.state.agentFilter, v.run.running, v.run.label, v.board.step, show]);
    if (key === els.helpers.dataset.k) return;
    els.helpers.dataset.k = key;
    if (!show) { els.helpers.replaceChildren(); return; }
    const kids = new Map();
    for (const x of tree) {
      const parent = known.has(x.parent) && x.parent !== x.agent ? x.parent : 'main';
      if (!kids.has(parent)) kids.set(parent, []);
      kids.get(parent).push(x);
    }
    const row = (agent, role, label, status, depth, dot) => {
      const on = agent === 'main' ? !S.state.agentFilter : S.state.agentFilter === agent;
      return h('button', {type: 'button', class: 'fx-agent', 'data-agent': agent, style: '--d:' + Math.min(depth, 4), 'aria-pressed': String(on),
        title: agent === 'main' ? 'Show all the work' : on ? 'Back to all the work' : 'Show what this helper does',
        onclick: () => pickAgent(agent === 'main' || on ? null : agent)},
      h('span', {class: 'fx-agent-dot ' + dot, icon: dot === 'done' ? 'check' : false, 'aria-hidden': 'true'}),
      h('span', {class: 'fx-agent-b'},
        h('span', {class: 'fx-agent-l'}, h('span', {class: 'fx-role ' + role.toLowerCase(), text: role}), h('span', {class: 'fx-agent-t', text: label})),
        status ? h('span', {class: 'fx-agent-s', text: status}) : null));
    };
    const line = s => text(S.plainNames(s));
    const rows = [row('main', 'MAIN', text(v.run.label) || 'Main agent', line(now.main || v.board.step || (v.run.running ? 'Working' : 'Resting')), 0, v.run.running ? 'working' : 'done')];
    const seen = new Set();
    const walk = (parent, depth) => {
      for (const x of kids.get(parent) || []) {
        if (seen.has(x.agent)) continue;
        seen.add(x.agent);
        const n = tree.indexOf(x) + 1;
        rows.push(row(x.agent, 'HELPER', 'Helper ' + n, line((x.open && now[x.agent]) || x.text), depth, x.ok === false ? 'bad' : x.open ? 'working' : 'done'));
        walk(x.agent, depth + 1);
      }
    };
    walk('main', 1);
    const had = els.helpers.contains(document.activeElement) ? document.activeElement.dataset.agent : null;
    els.helpers.replaceChildren(h('div', {class: 'fx-agents'}, h('p', {class: 'eyebrow'}, h('span', {text: 'Working on this'}), h('span', {text: String(tree.length + 1)})),
      h('div', {class: 'fx-agent-tree', role: 'group', 'aria-label': 'Working on this'}, rows)));
    if (had) els.helpers.querySelector('.fx-agent[data-agent="' + CSS.escape(had) + '"]')?.focus();
  }

  /* "← All live" before the title: shown only while some ticket is live; checked at build and every 15 s. */
  function backLink() {
    const count = h('span', {class: 'fx-back-n', text: ''});
    const link = h('a', {class: 'fx-back', href: INAPP ? '/#home' : '/', target: INAPP ? '_top' : '_self', hidden: true}, h('span', {text: '← All live'}), count);
    let loading = false, lastLive = '', lastAreas = '';
    /* The same fetch also feeds the same-file banner and the Files tab (S.state.live) and the area chip (S.state.areas). */
    async function load() {
      if (document.hidden || loading) return;
      loading = true;
      try {
        const [r, ra] = await Promise.all([fetch(P + '/api/live'), fetch(P + '/api/areas').catch(() => null)]);
        if (ra && ra.ok) {
          const areas = await ra.json(), json = JSON.stringify(areas);
          if (json !== lastAreas) { lastAreas = json; S.state.areas = areas; renderArea(); }
        }
        if (!r.ok) throw Error();
        const data = await r.json(), json = JSON.stringify(data);
        const n = (data.cards || []).length;
        count.textContent = String(n);
        link.setAttribute('aria-label', 'All live work (' + n + ')');
        link.hidden = !n;
        if (json !== lastLive) {
          lastLive = json; S.state.live = data;
          renderClash();
          if (S.state.view) renderFiles(S.state.view);
        }
      } catch (e) { link.hidden = true; }
      finally { loading = false; }
    }
    let mounted = false;
    const timer = setInterval(() => {
      if (mounted && !link.isConnected) { clearInterval(timer); return; }  // the page replaced the header (e.g. "No such ticket")
      mounted = mounted || link.isConnected;
      load();
    }, 15000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden && link.isConnected) load(); });
    load();
    return link;
  }

  S.register('used', {chip, renderUsed, renderFiles, renderClash, renderArea, renderTree, pickAgent, backLink});
})();

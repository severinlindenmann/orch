// What the agent used (skills, tools, connections), the helper tree, and the "All live" back link on a ticket page.
(function () {
  'use strict';
  const S = window.FocusStore;
  const {h, P, INAPP, els, keyOf} = S;
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
    const tab = els.tabs && els.tabs[2];
    if (tab) { tab.textContent = 'Used'; if (rows.length) tab.append(h('sup', {text: ' ' + rows.length})); }
    const key = keyOf(rows);
    if (!els.paneUsed || key === els.paneUsed.dataset.k) return;
    els.paneUsed.dataset.k = key;
    const content = h('div', {class: 'fx-results fx-used-page'}, h('h2', {text: 'What the agent used'}));
    if (!rows.length) content.append(h('p', {class: 'meta', text: 'Nothing used yet.'}));
    else {
      const head = h('tr', {}, ['What', 'Name', 'From', 'How often', 'Note'].map(t => h('th', {scope: 'col', text: t})));
      const body = rows.map(u => h('tr', {},
        h('td', {}, chip(u, false)),
        h('td', {}, h('span', {text: text(u.name)}), u.kind === 'mcp' && (u.actions || []).length ? h('span', {class: 'fx-used-acts', text: u.actions.map(text).join(', ')}) : null),
        h('td', {text: FROM[u.source] || ''}),
        h('td', {class: 'fx-used-n', text: String(u.count ?? '')}),
        h('td', {})));
      content.append(h('div', {class: 'fx-used-wrap'}, h('table', {class: 'fx-used-table'}, h('thead', {}, head), h('tbody', {}, body))));
    }
    els.paneUsed.replaceChildren(content);
  }

  /* The files the agent read or changed (display only: the paths come from the record and are never opened here). */
  const HOW = {read: 'Read', changed: 'Changed', touched: 'Used'};
  const SAFE = p => typeof p === 'string' && p.length <= 260 && !p.startsWith('/') && !/[\\\x00-\x1f\x7f]/.test(p) && !p.split('/').some(x => x === '..' || x === '' || x === '.');
  function renderFiles(v) {
    const rows = ((v.board && v.board.files) || []).filter(f => SAFE(f.path));
    const tab = els.tabs && els.tabs[3];
    if (tab) { tab.textContent = 'Files'; if (rows.length) tab.append(h('sup', {text: ' ' + rows.length})); }
    const key = keyOf(rows);
    if (!els.paneFiles || key === els.paneFiles.dataset.k) return;
    els.paneFiles.dataset.k = key;
    const content = h('div', {class: 'fx-results fx-files-page'}, h('h2', {text: 'Files this ticket touched'}));
    if (!rows.length) content.append(h('p', {class: 'meta', text: 'No files yet.'}));
    else content.append(h('ul', {class: 'fx-files-list'}, rows.map(f => h('li', {class: 'fx-file ' + (f.how === 'changed' ? 'changed' : '')},
      h('span', {class: 'fx-file-how', text: HOW[f.how] || 'Used'}), h('span', {class: 'fx-file-path', text: text(f.path)})))));
    els.paneFiles.replaceChildren(content);
  }

  /* Agents in the left rail: the main agent, its helpers nested under their parent. A click shows only that agent's steps. */
  function renderTree(v) {
    const tree = (v.board && v.board.helper_tree) || [];
    const known = new Set(['main', ...tree.map(x => x.agent)]);
    if (!tree.length || !known.has(S.state.agentFilter)) S.state.agentFilter = null;
    const key = keyOf([tree, S.state.agentFilter, v.run.running]);
    if (key === els.helpers.dataset.k) return;
    els.helpers.dataset.k = key;
    if (!tree.length) { els.helpers.replaceChildren(); return; }
    const kids = new Map();
    for (const x of tree) {
      const parent = known.has(x.parent) && x.parent !== x.agent ? x.parent : 'main';
      if (!kids.has(parent)) kids.set(parent, []);
      kids.get(parent).push(x);
    }
    const row = (agent, label, depth, dot) => {
      const on = S.state.agentFilter === agent;
      return h('button', {type: 'button', class: 'fx-agent', style: '--d:' + Math.min(depth, 4), 'aria-pressed': String(on), title: on ? 'Show all steps' : 'Show only these steps',
        onclick: e => {
          const at = [...els.helpers.querySelectorAll('.fx-agent')].indexOf(e.currentTarget);
          S.state.agentFilter = on ? null : agent; renderTree(S.state.view); S.state.lastFeedKey = ''; S.views.live.renderFeed(S.state.view);
          els.helpers.querySelectorAll('.fx-agent')[at]?.focus();  // the row is drawn again; keep the keyboard where it was
        }},
      h('span', {class: 'fx-agent-dot ' + dot, icon: dot === 'done' ? 'check' : false, 'aria-hidden': 'true'}), h('span', {class: 'fx-agent-t', text: label}));
    };
    const rows = [row('main', 'Main agent', 0, v.run.running ? 'working' : 'done')];
    const seen = new Set();
    const walk = (parent, depth) => {
      for (const x of kids.get(parent) || []) {
        if (seen.has(x.agent)) continue;
        seen.add(x.agent);
        rows.push(row(x.agent, text(x.text) || 'Helper', depth, x.ok === false ? 'bad' : x.open ? 'working' : 'done'));
        walk(x.agent, depth + 1);
      }
    };
    walk('main', 1);
    els.helpers.replaceChildren(h('div', {class: 'fx-agents'}, h('p', {class: 'eyebrow'}, h('span', {text: 'Agents'}), h('span', {text: String(tree.length + 1)})),
      h('div', {class: 'fx-agent-tree', role: 'group', 'aria-label': 'Agents'}, rows)));
  }

  /* "← All live" before the title: shown only while some ticket is live; checked at build and every 15 s. */
  function backLink() {
    const count = h('span', {class: 'fx-back-n', text: ''});
    const link = h('a', {class: 'fx-back', href: INAPP ? '/#home' : '/', target: INAPP ? '_top' : '_self', hidden: true}, h('span', {text: '← All live'}), count);
    let loading = false;
    async function load() {
      if (document.hidden || loading) return;
      loading = true;
      try {
        const r = await fetch(P + '/api/live');
        if (!r.ok) throw Error();
        const n = ((await r.json()).cards || []).length;
        count.textContent = String(n);
        link.setAttribute('aria-label', 'All live work (' + n + ')');
        link.hidden = !n;
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

  S.register('used', {chip, renderUsed, renderFiles, renderTree, backLink});
})();

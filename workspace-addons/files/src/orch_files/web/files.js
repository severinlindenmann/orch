/* The Files page (ORCH-654, the look of ORCH-606 draft D). Left: quick places, Your folders (the real folders of the
   workspace: a list and a live preview) and From tickets (automatic folders, one per ticket that has files, under
   Working / In review / Done / Earlier: a gallery of cards; versions of one file stack into one card). One search box
   over everything: names first, then the text inside files. Everything comes from this add-on's server (the index);
   text is only ever added with textContent, file content only through the kit's result widgets. */
(() => {
  'use strict';
  const UI = window.UI, P = document.documentElement.dataset.prefix || '';
  const Frame = window.OrchFrame || {url: u => u};
  const $ = s => document.querySelector(s);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = String(text); return n; };
  const btn = (cls, text) => { const b = el('button', cls, text); b.type = 'button'; return b; };
  const svg = (paths, size) => { const t = document.createElement('template'); t.innerHTML = '<svg viewBox="0 0 24 24" width="' + (size || 16) + '" height="' + (size || 16) + '" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>'; return t.content.firstChild; };
  const kitIcon = (name, size) => { const t = document.createElement('template'); t.innerHTML = window.icon(name, size || 16); return t.content.firstChild; };
  const IC = {
    folder: '<path d="M3 6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    spark: '<path d="m12 3 2 6 7 3-7 2-2 7-2-7-7-2 7-3z"/>',
    star: '<path d="m12 3 2.7 5.6 6.1.8-4.5 4.3 1.1 6.1-5.4-2.9-5.4 2.9 1.1-6.1-4.5-4.3 6.1-.8z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    back: '<path d="m15 6-6 6 6 6"/>',
    lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'
  };
  const phone = () => matchMedia('(max-width:720px)').matches;
  const TYPES = Object.fromEntries(UI.result.TYPES.map(t => [t.id, t]));
  const widgetType = k => k === 'doc' ? 'md' : TYPES[k] ? k : 'file';
  const iconOf = f => f.private ? svg(IC.lock) : kitIcon((TYPES[widgetType(f.kind)] || TYPES.file).icon);
  const sizeText = n => n < 1024 ? n + ' B' : n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : n < 104857600 ? (n / 1048576).toFixed(1) + ' MB' : Math.round(n / 1048576) + ' MB';
  const when = (secs, time) => UI.stamp(new Date(secs * 1000).toISOString(), {time: time !== false});
  const plural = (n, one) => Number(n).toLocaleString('en-US') + ' ' + one + (n === 1 ? '' : 's');
  const STATUS = {working: ['Working', 'working'], review: ['In review', 'review'], done: ['Done', 'done']};
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const PLACES = {recent: 'Recent', starred: 'Starred', new: 'New for you'};
  const TICKETS = {label: 'Open tickets', href: '/#tickets', target: '_top'};  // where helpers make files: the one next step of an empty page
  // Folds accents one character at a time, so the folded text keeps its length (marks land on the right letters)
  const fold = s => { let o = ''; for (const ch of String(s)) { const b = ch.normalize('NFD')[0].toLowerCase(); o += ch.length === 1 && b.length === 1 ? b : ch; } return o; };
  const leaf = path => path === '' ? (S.status.workspace || 'Your folders') : path.split('/').pop();
  const fileUrl = u => Frame.url(P + '/' + u);
  const VERSION = /^(.+?)[-_ .]?v(?:ersion)?[-_ ]?(\d{1,3})$/i;
  const versionOf = name => { const m = /^(.*?)(?:\.([^.]+))?$/.exec(name), v = VERSION.exec(m[1]); return v ? {key: v[1].toLowerCase() + '.' + (m[2] || '').toLowerCase(), n: +v[2]} : null; };

  async function api(path, opts) {
    const r = await fetch(P + path, Object.assign({headers: {Accept: 'application/json'}}, opts || {}));
    if (!r.ok) throw Object.assign(new Error(await r.text().catch(() => '')), {status: r.status});
    return r.json();
  }
  const act = (op, args) => api('/api/act', {method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify({op, args})});

  // ---- what the page shows right now
  const S = {
    place: 'folder', path: '', q: '', view: 'list', sort: null, dir: 1, sel: null, rows: [], took: 0, found: 0,
    closed: new Set(['earlier']), status: {}, tree: [], kids: new Map(), counts: new Map(), groups: [], node: null,
    sections: [], stars: new Set(), loaded: false, seq: 0
  };
  const gallery = () => S.place === 'tickets' && !S.q.trim();
  const ticketOf = id => { for (const g of S.groups) { const t = g.tickets.find(x => x.id === id); if (t) return t; } return null; };
  const nodeOf = id => { for (const g of S.groups) { if (g.id === id) return {g}; const tn = g.tickets.find(x => 't:' + x.id === id); if (tn) return {g, tn}; } return null; };

  // ---- data
  function setTree(folders) {
    S.tree = folders; S.kids = new Map(); S.counts = new Map();
    folders.forEach(f => {
      S.counts.set(f.path, f.count);
      if (f.path === '') return;
      const parent = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : '';
      if (!S.kids.has(parent)) S.kids.set(parent, []);
      S.kids.get(parent).push(f.path);
    });
    S.kids.forEach(v => v.sort((a, b) => leaf(a).localeCompare(leaf(b), undefined, {sensitivity: 'base'})));
    if (!S.loaded) S.kids.forEach((v, k) => { if (k !== '') S.closed.add(k); });  // every folder starts folded, the top shows
    S.kids.forEach(v => v.forEach(p => { if (S.kids.has(p) && !S.loaded) S.closed.add(p); }));
  }
  const kids = path => S.kids.get(path) || [];
  async function loadAll() {
    const [st, tree, tk, stars] = await Promise.all([api('/api/status'), api('/api/tree').catch(() => ({folders: []})), api('/api/tickets').catch(() => ({groups: []})), api('/api/starred').catch(() => ({files: []}))]);
    S.status = st; setTree(tree.folders || []); S.groups = tk.groups || []; S.stars = new Set((stars.files || []).map(f => f.path));
  }

  async function compute() {
    const seq = ++S.seq, t0 = performance.now(); let rows;
    const q = S.q.trim();
    if (q) {
      // Names answer at once; the text hits follow (draw() calls again with full set)
      const res = await api('/api/search?q=' + encodeURIComponent(q) + '&limit=100' + (S.namesFirst ? '&names=1' : ''));
      if (seq !== S.seq) return false;
      rows = res.items.map(f => ({type: 'file', f, hit: f.found === 'text' ? f.line : null}));
      S.took = (res.ms || 0) / 1000; S.unread = res.unread;
    } else if (S.place === 'recent' || S.place === 'starred' || S.place === 'new') {
      const res = await api('/api/' + S.place);
      if (seq !== S.seq) return false;
      rows = res.files.map(f => ({type: 'file', f}));
    } else if (S.place === 'tickets') {
      const n = nodeOf(S.node) || (S.groups[0] ? {g: S.groups[0]} : null);
      S.node = n ? (n.tn ? 't:' + n.tn.id : n.g.id) : null; S.sections = n ? (n.tn ? [n.tn] : n.g.tickets) : []; rows = [];
    } else {
      const res = await api('/api/folder?p=' + encodeURIComponent(S.path));
      if (seq !== S.seq) return false;
      rows = res.folders.map(d => ({type: 'folder', path: d.path, count: d.count})).concat(res.files.map(f => ({type: 'file', f})));
    }
    if (!q) S.took = (performance.now() - t0) / 1000;
    const key = S.sort || (q || S.place !== 'folder' ? null : 'name');
    if (key) {
      const val = r => r.type === 'folder' ? (key === 'name' ? leaf(r.path).toLowerCase() : key === 'size' ? r.count : '') : key === 'name' ? r.f.title.toLowerCase() : key === 'kind' ? r.f.word : r.f[key];
      rows.sort((a, b) => (a.type === b.type ? 0 : a.type === 'folder' ? -1 : 1) || (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * S.dir);
    }
    rows.forEach(r => { r.key = r.type === 'folder' ? 'dir:' + r.path : r.f.path; });
    S.rows = rows;
    if (!rows.some(r => r.key === S.sel)) S.sel = phone() ? null : (rows.find(r => r.type === 'file' && !r.f.private) || rows.find(r => r.type === 'file') || rows[0] || {}).key || null;
    return true;
  }
  const selRow = () => S.rows.find(r => r.key === S.sel);
  const fileRows = () => S.rows.filter(r => r.type === 'file').map(r => r.f);

  // ---- marking the words found (nodes only, never innerHTML)
  const words = () => fold(S.q).split(/\s+/).filter(Boolean);
  function marked(text, ws, cls) {
    const span = el('span', cls), f = fold(text); let at = 0;
    if (f.length !== text.length) { span.textContent = text; return span; }  // folding changed the length: no marks
    const hits = [];
    ws.forEach(w => { let i = f.indexOf(w); while (w && i >= 0) { hits.push([i, i + w.length]); i = f.indexOf(w, i + w.length); } });
    hits.sort((a, b) => a[0] - b[0]).forEach(([a, b]) => { if (a < at) return; span.append(text.slice(at, a)); span.append(el('mark', '', text.slice(a, b))); at = b; });
    span.append(text.slice(at)); return span;
  }
  function markInside(root, ws) {
    if (!root || !ws.length) return;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), nodes = [];
    while (w.nextNode()) if (ws.some(x => fold(w.currentNode.nodeValue).includes(x))) nodes.push(w.currentNode);
    nodes.slice(0, 200).forEach(n => n.replaceWith(...marked(n.nodeValue, ws).childNodes));
    const first = root.querySelector('mark'); if (first) requestAnimationFrame(() => { const b = first.closest('.result-body') || root; b.scrollTop = Math.max(0, first.offsetTop - b.offsetTop - 24); });
  }

  // ---- left: places and folders
  function drawTree() {
    const host = $('#files-tree'), keep = host.scrollTop; host.replaceChildren();
    const node = o => {
      const row = el('div', 'files-noderow'); row.dataset.depth = o.depth || 0;
      if (o.twist != null) {
        const tw = btn('files-twist'); tw.append(UI.chevron());
        tw.disabled = !o.has; tw.setAttribute('aria-expanded', String(!S.closed.has(o.twist))); tw.setAttribute('aria-label', (S.closed.has(o.twist) ? 'Show' : 'Hide') + ' what is in ' + o.label);
        tw.onclick = () => { S.closed.has(o.twist) ? S.closed.delete(o.twist) : S.closed.add(o.twist); drawTree(); };
        row.append(tw);
      }
      const b = btn('files-node'); b.append(o.icon, el('span', 'nm', o.label)); b.title = o.label + (o.key ? ' (' + o.key + ')' : '');
      if (o.key) b.append(el('span', 'k', o.key));
      if (o.count != null) b.append(el('span', 'n', Number(o.count).toLocaleString('en-US')));
      if (o.current) b.setAttribute('aria-current', 'true');
      b.onclick = o.go; row.append(b); host.append(row);
    };
    const reset = () => { S.q = ''; $('#files-q').value = ''; S.sort = null; S.dir = 1; S.sel = null; pane('files'); draw(); };
    const goFolder = p => () => { S.place = 'folder'; S.path = p; reset(); };
    const goPlace = p => () => { S.place = p; reset(); };
    const goNode = id => () => { S.place = 'tickets'; S.node = id; reset(); $('#files-gallery').scrollTop = 0; };
    const browsing = !S.q.trim();
    host.append(el('p', 'eyebrow', 'Quick places'));
    node({label: 'Recent', icon: kitIcon('clock'), current: browsing && S.place === 'recent', go: goPlace('recent')});
    node({label: 'Starred', icon: svg(IC.star), count: S.stars.size, current: browsing && S.place === 'starred', go: goPlace('starred')});
    node({label: 'New for you', icon: svg(IC.spark), count: S.status.new || 0, current: browsing && S.place === 'new', go: goPlace('new')});
    host.append(el('p', 'eyebrow', 'Your folders'));
    const walk = (path, depth) => {
      node({label: leaf(path), icon: svg(IC.folder), count: S.counts.get(path) || 0, current: browsing && S.place === 'folder' && S.path === path, go: goFolder(path), depth: Math.min(depth, 2), twist: path, has: kids(path).length > 0});
      if (!S.closed.has(path)) kids(path).forEach(k => walk(k, depth + 1));
    };
    walk('', 0);
    const from = el('p', 'eyebrow', 'From tickets'); from.id = 'files-from'; host.append(from);
    if (!S.groups.length) host.append(el('p', 'meta files-treefoot', 'Files helpers make for your tickets show up here.'));
    S.groups.forEach(g => {
      node({label: g.label, icon: kitIcon('ticket'), count: g.tickets.reduce((a, x) => a + x.files.length, 0), current: browsing && S.place === 'tickets' && S.node === g.id, go: goNode(g.id), depth: 0, twist: g.id, has: true});
      if (!S.closed.has(g.id)) g.tickets.forEach(tn => node({label: tn.title, key: tn.key, icon: svg(IC.folder), count: tn.files.length, current: browsing && S.place === 'tickets' && S.node === 't:' + tn.id, go: goNode('t:' + tn.id), depth: 2}));
    });
    host.append(el('p', 'meta files-treefoot', plural(S.status.total || 0, 'file') + ' in this workspace'));
    host.scrollTop = keep;
    const cur = host.querySelector('[aria-current=true]');
    if (cur && !phone()) { const r = cur.getBoundingClientRect(), h = host.getBoundingClientRect(); if (r.bottom > h.bottom) host.scrollTop += r.bottom - h.bottom + 8; else if (r.top < h.top) host.scrollTop -= h.top - r.top + 8; }
  }

  // ---- middle: where you are, the count, the head, the list, grid or gallery
  function drawWhere() {
    const c = $('#files-crumb'); c.replaceChildren();
    const q = S.q.trim(), n = gallery() ? S.sections.reduce((a, x) => a + x.files.length, 0) : S.rows.filter(r => r.type === 'file').length;
    const trail = crumbs => crumbs.forEach(([label, go], i) => {
      if (i) { const sep = el('span', '', '›'); sep.setAttribute('aria-hidden', 'true'); c.append(sep); }
      if (i === crumbs.length - 1) { const s = el('span', '', label); s.setAttribute('aria-current', 'page'); c.append(s); }
      else if (!go) c.append(el('span', '', label));
      else { const b = btn('', label); b.onclick = go; c.append(b); }
    });
    if (q) c.append(el('span', '', 'Found in all folders'));
    else if (S.place === 'tickets') {
      const cur = nodeOf(S.node);
      if (cur) trail([['From tickets', null], [cur.g.label, () => { S.node = cur.g.id; draw(); }]].concat(cur.tn ? [[cur.tn.title, null]] : []));
      else trail([['From tickets', null]]);
    } else if (S.place !== 'folder') trail([[PLACES[S.place], null]]);
    else {
      const parts = S.path ? S.path.split('/') : [];
      trail([['Your folders', () => { S.path = ''; S.sel = null; draw(); }]].concat(parts.map((p, i) => [p, () => { S.path = parts.slice(0, i + 1).join('/'); S.sel = null; draw(); }])));
    }
    const took = S.took < 0.01 ? 'under 0.01 s' : S.took.toFixed(2) + ' s';
    // the count names what the list shows: folders too, so "1 file" never sits over two folders and a file (ORCH-1691)
    const dirs = !q && S.place === 'folder' ? S.rows.filter(r => r.type === 'folder').length : 0;
    $('#files-count').textContent = q ? plural(n, 'file') + ' of ' + Number(S.status.total || 0).toLocaleString('en-US') + ', ' + took : (dirs ? plural(dirs, 'folder') + ', ' : '') + plural(n, 'file');
  }
  const COLS = [['name', 'Name', ''], ['kind', 'Kind', 'kindcol'], ['size', 'Size', ''], ['changed', 'Changed', '']];
  function drawHead() {
    const h = $('#files-head'); h.replaceChildren(); h.hidden = S.view === 'grid' || !S.rows.length || gallery();
    COLS.forEach(([key, label, cls]) => {
      const b = btn(cls, label); b.append(UI.chevron());
      b.setAttribute('aria-sort', S.sort === key || (!S.sort && key === 'name' && !S.q.trim() && S.place === 'folder') ? (S.dir > 0 ? 'ascending' : 'descending') : 'none');
      b.setAttribute('aria-label', 'Sort by ' + label.toLowerCase());
      b.onclick = () => { const cur = S.sort || (!S.q.trim() && S.place === 'folder' ? 'name' : null); S.dir = cur === key ? -S.dir : (key === 'changed' || key === 'size' ? -1 : 1); S.sort = key; draw(); };
      h.append(b);
    });
    h.append(el('span'));
  }
  const whereWords = f => f.ticket ? 'From tickets › ' + ((ticketOf(f.ticket) || {}).title || f.ticket) : f.folder ? 'Your folders › ' + f.folder.split('/').join(' › ') : 'Your folders';
  function rowNode(r, i) {
    const row = el('div', 'files-row'); row.id = 'files-r' + i; row.dataset.key = r.key; row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(r.key === S.sel));
    const name = el('div', 'files-name');
    if (r.type === 'folder') {
      name.append(svg(IC.folder), el('span', '', leaf(r.path)), el('span', 'sub phone', 'Folder · ' + plural(r.count, 'file')));
      row.append(name, el('span', 'kindcol', 'Folder'), el('span', 'num', plural(r.count, 'file')), el('span', '', ''), el('span', '', ''));
      return row;
    }
    const f = r.f, ws = r.hit !== undefined || S.q.trim() ? words() : [], below = f.name + (S.place !== 'folder' || S.q.trim() ? '  ·  ' + whereWords(f) : '');
    name.append(iconOf(f), marked(f.title, ws), marked(below, ws, 'sub'));
    if (r.hit) name.append(marked(r.hit, ws, 'sub hit'));
    name.append(el('span', 'sub phone', f.word + ' · ' + sizeText(f.size) + ' · ' + when(f.changed)));
    row.append(name, el('span', 'kindcol cut', f.word), el('span', 'num', sizeText(f.size)), el('span', 'cut', when(f.changed, false)), el('span', '', ''));
    return row;
  }
  function tileNode(r, i) {
    let card;
    if (r.type === 'folder') {
      card = el('article', 'result card files-foldertile'); card.dataset.size = 'sm';
      const head = el('header', 'result-head'); head.append(svg(IC.folder, 14), el('span', 'result-name', leaf(r.path)));
      const body = el('div', 'result-body'); body.append(svg(IC.folder, 40));
      card.append(head, body, el('p', 'result-meta meta', 'Folder · ' + plural(r.count, 'file')));
    } else {
      card = lazyCard(r.f, r.f.title, r.f.name);
      card.querySelectorAll('button,a').forEach(b => { b.tabIndex = -1; });
    }
    card.id = 'files-r' + i; card.dataset.key = r.key; card.setAttribute('role', 'option'); card.setAttribute('aria-selected', String(r.key === S.sel));
    return card;
  }
  function drawList() {
    const host = $('#files-list'); host.replaceChildren();
    const q = S.q.trim();
    host.hidden = gallery(); $('#files-gallery').hidden = !gallery();
    if (gallery()) return drawGallery();
    host.setAttribute('aria-label', q ? 'Files found' : 'Files in ' + (S.place === 'folder' ? leaf(S.path) : PLACES[S.place]));
    if (q && S.unread) host.append(el('p', 'files-note', 'Names are complete. Text inside ' + plural(S.unread, 'file') + ' is still being read, so some files may be missing here for a moment.'));
    if (!S.rows.length) {
      host.removeAttribute('aria-activedescendant');
      host.append(q ? UI.state({title: 'Nothing found for “' + q + '”', text: 'Try fewer letters or another word, for example a customer or a month. Pictures and videos are found by their name only.', action: {label: 'Clear search', onClick: clearSearch}})
        : UI.state(Object.assign(S.place === 'starred' ? {title: 'No starred files yet', text: 'Star a file in its preview to keep it here.'} : S.place === 'new' ? {title: 'Nothing new', text: 'Files made since you last looked show up here.'} : S.place === 'recent' ? {title: 'No files yet', text: 'Files you change show up here.'} : {title: 'This folder is empty', text: 'Files put into this folder show up here.'},
          {action: S.place !== 'folder' ? {label: 'Show your folders', onClick: () => openFolder('')} : S.path ? {label: 'Up one folder', onClick: () => openFolder(S.path.split('/').slice(0, -1).join('/'))} : TICKETS})));
      return;
    }
    const box = S.view === 'grid' ? el('div', 'result-grid') : host;
    S.rows.forEach((r, i) => box.append(S.view === 'grid' ? tileNode(r, i) : rowNode(r, i)));
    if (box !== host) host.append(box);
    const cur = host.querySelector('[aria-selected=true]');
    if (cur) host.setAttribute('aria-activedescendant', cur.id); else host.removeAttribute('aria-activedescendant');
  }

  // ---- previews: the server hands the widget its content; file addresses get this frame's file pass
  const previews = new Map();
  function itemFrom(f, got, name, meta) {
    const it = Object.assign({}, got, {name: name || f.title, meta: meta == null ? f.name : meta});
    ['src', 'download', 'href', 'thumb', 'poster'].forEach(k => { if (it[k] && !/^(data|blob):/.test(it[k])) it[k] = fileUrl(it[k]); else if (!it[k]) delete it[k]; });
    if (it.private) Object.assign(it, {type: 'file', size: undefined});
    return it;
  }
  function getPreview(f) {
    if (!previews.has(f.path)) previews.set(f.path, api('/api/preview?p=' + encodeURIComponent(f.path)).catch(() => ({type: widgetType(f.kind), state: 'error'})));
    return previews.get(f.path);
  }
  // A small card whose content arrives when it scrolls into sight (four at a time)
  const queue = [], running = {n: 0};
  function pump() {
    while (running.n < 4 && queue.length) {
      const job = queue.shift(); running.n++;
      getPreview(job.f).then(got => job.done(got)).finally(() => { running.n--; pump(); });
    }
  }
  const seen = new IntersectionObserver(es => es.forEach(e => { if (!e.isIntersecting) return; seen.unobserve(e.target); const j = e.target._job; if (j) { queue.push(j); pump(); } }), {rootMargin: '200px'});
  function lazyCard(f, name, meta, onOpen) {
    const base = {type: widgetType(f.kind), name, meta, size: f.size};
    let card = UI.result(Object.assign({state: 'loading'}, base), {size: 'sm', onOpen});
    card._job = {f, done: got => {
      const next = UI.result(itemFrom(f, got, name, meta), {size: 'sm', onOpen});
      ['id', 'role', 'aria-selected'].forEach(a => { if (card.hasAttribute(a)) next.setAttribute(a, card.getAttribute(a)); });
      if (card.dataset.key) next.dataset.key = card.dataset.key;
      next.querySelector('.result-name')?.setAttribute('title', name);
      next.querySelectorAll('button,a').forEach(b => { if (card.closest('#files-list')) b.tabIndex = -1; });
      card.replaceWith(next); card = next;
    }};
    seen.observe(card);
    return card;
  }

  // ---- From tickets: a gallery of cards, one part per ticket; a click opens the big preview with ← →
  const dayTime = f => { const d = new Date(f.changed * 1000); return DAYS[d.getDay()] + ' ' + d.toTimeString().slice(0, 5); };
  function drawGallery() {
    const host = $('#files-gallery'); host.replaceChildren();
    const cur = nodeOf(S.node);
    if (!cur) { host.append(UI.state({title: 'No files from tickets yet', text: 'Files helpers make for your tickets show up here, one folder per ticket.', action: TICKETS})); return; }
    const one = !!cur.tn, top = el('div', 'files-galhead');
    if (!one) {
      const t = el('div', 'files-galtitle'), h = el('h2', '', cur.g.label);
      t.append(kitIcon('ticket'), h, el('span', 'meta', plural(cur.g.tickets.length, 'ticket') + ' · ' + plural(cur.g.tickets.reduce((a, x) => a + x.files.length, 0), 'file')));
      top.append(t);
    }
    top.append(el('p', 'meta files-galhow', cur.g.id === 'earlier' ? 'Tickets done more than 30 days ago, one folder each.' : 'One folder per ticket, sorted by where the ticket stands. Nothing is moved on your computer.'));
    host.append(top);
    S.sections.forEach(sec => {
      const units = [], stacks = new Map(), count = {};
      sec.files.forEach(f => { count[f.title] = (count[f.title] || 0) + 1; });
      sec.files.forEach(f => {
        const v = versionOf(f.name);
        if (!v) { units.push({files: [f]}); return; }
        let u = stacks.get(v.key); if (!u) { u = {files: [], v: true}; stacks.set(v.key, u); units.push(u); }
        f._v = v.n; u.files.push(f);
      });
      const box = el('section', 'files-sec'), head = el('header', 'files-sechead'), st = STATUS[sec.status] || STATUS.working;
      const h = el('h2', 'files-sectitle');
      if (one) h.textContent = sec.title; else { const b = btn('', sec.title); b.setAttribute('aria-label', 'Open the folder ' + sec.title); b.onclick = () => { S.node = 't:' + sec.id; draw(); $('#files-gallery').scrollTop = 0; }; h.append(b); }
      const link = el('a', 'btn ghost sm', 'Open ticket'); link.href = '/#ticket/' + encodeURIComponent(sec.id); link.target = '_blank'; link.rel = 'noopener';
      const older = sec.files.length - units.length;
      head.append(svg(IC.folder), h, el('span', 'files-key', sec.key), el('span', 'badge ' + st[1], st[0]), el('span', 'meta', plural(units.length, 'file') + (older ? ' · ' + plural(older, 'older version') : '')), el('span', 'grow'), link);
      const grid = el('div', 'result-grid'), order = [];
      units.forEach(u => {
        u.files.sort((a, b) => (b._v || 0) - (a._v || 0) || b.changed - a.changed);
        const f = u.files[0], older = u.files.length - 1;
        const twin = !u.v && count[f.title] > 1 ? ' · ' + dayTime(f) : '';
        const name = u.v ? f.title + ' · version ' + f._v + (older ? ', ' + older + ' older' : '') : f.title + twin;
        u.files.forEach((x, i) => order.push({f: x, name: u.v ? x.title + ' · version ' + x._v + ' of ' + u.files.length + (i ? ' (older)' : '') : x.title + twin}));
        const card = lazyCard(f, name, f.name, () => openOverlay(order, order.findIndex(o => o.f === f)));
        const wrap = el('div', 'files-card' + (older ? ' files-stack' : '')); wrap.append(card); grid.append(wrap);
      });
      box.append(head, grid); host.append(box);
    });
  }
  async function openOverlay(order, index) {
    const items = await Promise.all(order.map(o => getPreview(o.f).then(got => itemFrom(o.f, got, o.name, o.f.name + ' · ' + o.f.word + ' · ' + sizeText(o.f.size) + ' · ' + when(o.f.changed) + ' · ' + whereWords(o.f)))));
    UI.resultOverlay(items, Math.max(0, index));
  }

  // ---- right: the live preview
  async function drawPreview() {
    const host = $('#files-preview'), mine = ++drawPreview.seq;
    const back = btn('btn ghost sm files-back'); back.append(svg(IC.back), el('span', '', 'Files')); back.onclick = () => pane('files');
    const r = selRow();
    if (!r) { host.replaceChildren(back, el('p', 'meta files-none', 'Choose a file to look inside it here.')); return; }
    const facts = el('dl', 'split-facts');
    const fact = (k, v) => { const d = el('div'), dd = el('dd'); dd.append(v); d.append(el('dt', '', k), dd); facts.append(d); };
    if (r.type === 'folder') {
      const card = el('div', 'card pad-card stack'); const h = el('div', 'row'); h.append(svg(IC.folder, 20), el('strong', '', leaf(r.path))); card.append(h);
      const acts = el('div', 'files-acts'), open = btn('btn outline sm', 'Open folder'); open.onclick = () => openFolder(r.path); acts.append(open);
      fact('Kind', 'Folder'); fact('Inside', plural(r.count, 'file') + (kids(r.path).length ? ', ' + plural(kids(r.path).length, 'folder') : ''));
      host.replaceChildren(back, card, acts, facts); return;
    }
    const f = r.f;
    if (f.private) {
      const card = el('div', 'card pad-card stack'), h = el('div', 'row'); h.append(svg(IC.lock, 20), el('strong', '', f.title));
      card.append(h, el('p', 'meta', 'This file looks private (a key, a password or settings), so orch shows only its name. What is inside is never read or shown.'));
      fact('Kind', f.word); fact('File name', f.name); fact('Size', sizeText(f.size)); fact('Changed', when(f.changed));
      const wb = btn('', whereWords(f)); wb.onclick = () => f.ticket ? openTicket(f) : openFolder(f.folder); fact('Folder', wb);
      host.replaceChildren(back, card, facts); return;
    }
    const loading = UI.result({type: widgetType(f.kind), name: f.title, meta: f.name, state: 'loading'}, {size: 'lg'});
    host.replaceChildren(back, loading);
    const got = await getPreview(f);
    if (mine !== drawPreview.seq) return;
    const item = itemFrom(f, got, f.title, f.name + ' · ' + whereWords(f));
    const card = UI.result(item, {size: 'lg'});
    if (S.q.trim()) markInside(card.querySelector('.result-body'), words());
    const acts = el('div', 'files-acts');
    const open = btn('btn outline sm', 'Open'); open.onclick = openBig; acts.append(open);
    if (item.download) { const dl = el('a', 'btn ghost sm'); dl.href = item.download; dl.setAttribute('download', ''); dl.append(kitIcon('download'), el('span', '', 'Download')); acts.append(dl); }
    if (got.too_big) acts.append(el('p', 'meta', 'Over 4 MB: open it from its folder on your computer.'));
    if (f.ticket) { const a = el('a', 'btn ghost sm', 'Open ticket'); a.href = '/#ticket/' + encodeURIComponent(f.ticket); a.target = '_blank'; a.rel = 'noopener'; acts.append(a); }
    const star = btn('btn ghost icon sm files-star'), on = S.stars.has(f.path); star.append(svg(IC.star));
    star.setAttribute('aria-pressed', String(on)); star.setAttribute('aria-label', (on ? 'Remove the star from ' : 'Star ') + f.title); star.title = on ? 'Starred' : 'Star';
    star.onclick = () => toggleStar(f, !on);
    acts.append(el('span', 'grow'), star);
    fact('Kind', f.word); fact('File name', f.name); fact('Size', sizeText(f.size)); fact('Changed', when(f.changed));
    const wb = btn('', whereWords(f)); wb.onclick = () => f.ticket ? openTicket(f) : openFolder(f.folder); fact('Folder', wb);
    if (f.ticket) { const t = ticketOf(f.ticket), dd = el('span'); dd.append((t ? t.title : f.ticket) + ' ', el('span', 'files-key', t ? t.key : '')); fact('Ticket', dd); }
    if (r.hit) fact('Found', marked(r.hit, words()));
    host.replaceChildren(back, card, acts, facts, el('p', 'meta files-keys', '↑ ↓ choose · Enter opens it big · Esc closes'));
  }
  drawPreview.seq = 0;
  // the switch in What is included: list what .gitignore names too; the list redraws after the next check
  $('#files-show-ignored').addEventListener('change', async e => {
    const box = e.target, on = box.checked;
    box.disabled = true;
    try { await act('show_ignored', {on}); S.status.show_ignored = wanted = on; fastLeft = 20; if (!inPoll) { clearTimeout(pollTimer); pollTimer = setTimeout(poll, 1500); } }
    catch (err) { box.checked = !on; UI.toast('That did not work. Try again.', 'error'); }
    finally { box.disabled = false; }
  });
  async function toggleStar(f, on) {
    try { await act(on ? 'star' : 'unstar', {path: f.path}); } catch (e) { UI.toast('That did not work. Try again.', 'error'); return; }
    on ? S.stars.add(f.path) : S.stars.delete(f.path);
    if (S.place === 'starred' && !S.q.trim()) await draw(); else { drawTree(); await drawPreview(); }
    $('#files-preview .files-star')?.focus();
  }

  // ---- notices and whole-page states
  function drawNotice() {
    const host = $('#files-notice'), st = S.status;
    if (!$('#files-show-ignored').disabled) $('#files-show-ignored').checked = !!st.show_ignored;
    $('#files-about-count').textContent = !st.ready ? 'Reading the files for the first time.' : plural(st.total, 'file') + (st.checked_at ? ' · checked ' + when(st.checked_at) : '');
    const empty = st.ready && !st.total && !st.building;
    $('#files').hidden = empty || !st.ready; $('#files-empty').hidden = !empty;
    if (empty && !$('#files-empty').firstChild) $('#files-empty').append(UI.state({title: 'No files yet', text: 'Files you put into this workspace folder show up under Your folders. Files helpers make for your tickets show up under From tickets.', action: TICKETS}));
    if (!st.ready || st.unread) {
      const total = st.total || 0, read = Math.max(0, total - (st.unread || 0));
      const box = el('div', 'banner info files-notice');
      box.append(el('strong', '', !st.ready ? 'Reading the names of your files for the first time…' : 'Still reading ' + read.toLocaleString('en-US') + ' of ' + total.toLocaleString('en-US') + ' files: names are ready, text follows'));
      if (st.ready && total) {
        const bar = el('div', 'progress'); bar.setAttribute('role', 'progressbar'); bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', String(total)); bar.setAttribute('aria-valuenow', String(read)); bar.setAttribute('aria-label', 'Files read');
        const fill = el('span'); fill.style.width = Math.round(read / total * 100) + '%'; bar.append(fill); box.append(bar);
      }
      host.replaceChildren(box); host.hidden = false;
    } else if (st.error) {
      host.replaceChildren(el('div', 'banner attn', 'The files could not all be checked just now. Orch tries again in a moment.')); host.hidden = false;
    } else { host.replaceChildren(); host.hidden = true; }
  }

  // ---- actions
  async function draw() {
    if (S.q.trim()) {
      S.namesFirst = true; const seq = S.seq + 1;
      await drawOnce();
      S.namesFirst = false;
      if (seq !== S.seq) return;  // something newer was asked meanwhile
    }
    return drawOnce();
  }
  async function drawOnce() {
    let ok;
    try { ok = await compute(); } catch (e) { ok = true; S.rows = []; UI.toast('That could not be read. Try again in a moment.', 'error'); }
    if (ok === false) return;
    $('#files').dataset.mode = gallery() ? 'gallery' : 'list'; $('#files-mid').classList.toggle('searching', !!S.q.trim());
    drawTree(); drawWhere(); drawHead(); drawList(); drawPreview();
    document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === S.view)));
  }
  function pane(p) { $('#files').dataset.pane = p; }
  function openFolder(path, quiet) { S.place = 'folder'; S.path = path; path.split('/').forEach((p, i, all) => S.closed.delete(all.slice(0, i + 1).join('/'))); S.closed.delete(''); S.q = ''; $('#files-q').value = ''; S.sort = null; S.dir = 1; S.sel = null; pane('files'); return draw().then(() => { if (!quiet) $('#files-list').focus({preventScroll: true}); }); }
  function openTicket(f) { S.place = 'tickets'; S.node = 't:' + f.ticket; const n = nodeOf(S.node); if (n) S.closed.delete(n.g.id); S.q = ''; $('#files-q').value = ''; S.sel = null; pane('files'); draw(); }
  function clearSearch() { S.q = ''; $('#files-q').value = ''; S.sel = null; draw(); $('#files-q').focus(); }
  function select(key, opts) {
    S.sel = key; const host = $('#files-list');
    host.querySelectorAll('[role=option]').forEach(n => n.setAttribute('aria-selected', String(n.dataset.key === key)));
    const cur = host.querySelector('[aria-selected=true]');
    if (cur) { host.setAttribute('aria-activedescendant', cur.id); if (opts && opts.scroll) cur.scrollIntoView({block: 'nearest'}); }
    drawPreview();
  }
  function openBig() {
    const r = selRow(); if (!r) return;
    if (r.type === 'folder') return openFolder(r.path);
    const list = fileRows().filter(f => !f.private), at = list.indexOf(r.f);
    if (at < 0) return;
    const from = Math.max(0, at - 10), part = list.slice(from, at + 11);  // the neighbours for ← →, not the whole folder
    openOverlay(part.map(f => ({f, name: f.title})), at - from);
  }
  function move(step) {
    if (!S.rows.length) return;
    const i = S.rows.findIndex(r => r.key === S.sel), j = step === 'first' ? 0 : step === 'last' ? S.rows.length - 1 : Math.max(0, Math.min(S.rows.length - 1, (i < 0 ? (step > 0 ? -1 : S.rows.length) : i) + step));
    select(S.rows[j].key, {scroll: true});
  }

  // ---- wiring
  const list = $('#files-list'), q = $('#files-q');
  $('.files-search-ic').append(svg(IC.search));
  const toFolders = $('#files-to-folders'); toFolders.append(svg(IC.back), el('span', '', 'Folders')); toFolders.onclick = () => pane('folders');
  list.addEventListener('click', e => {
    const row = e.target.closest('[role=option]'); if (!row) return;
    e.preventDefault(); e.stopPropagation();
    const r = S.rows.find(x => x.key === row.dataset.key); if (!r) return;
    if (r.type === 'folder') return openFolder(r.path);
    if (e.detail === 0 && r.key === S.sel) return openBig();
    select(r.key); list.focus({preventScroll: true});
    if (phone()) { pane('preview'); scrollTo(0, 0); }
  }, true);
  list.addEventListener('dblclick', e => { if (e.target.closest('[role=option]') && !phone()) openBig(); });
  const keys = e => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const grid = S.view === 'grid';
    if (e.key === 'ArrowDown' || (grid && e.key === 'ArrowRight' && e.target === list)) { e.preventDefault(); move(1); }
    else if (e.key === 'ArrowUp' || (grid && e.key === 'ArrowLeft' && e.target === list)) { e.preventDefault(); move(-1); }
    else if (e.key === 'Home' && e.target === list) { e.preventDefault(); move('first'); }
    else if (e.key === 'End' && e.target === list) { e.preventDefault(); move('last'); }
    else if (e.key === 'Enter') { e.preventDefault(); openBig(); }
  };
  list.addEventListener('keydown', keys);
  let typing = null;
  q.addEventListener('keydown', e => { if (e.key === 'Escape' && q.value) { e.preventDefault(); clearSearch(); } else keys(e); });
  q.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => { S.q = q.value; S.sort = null; S.dir = 1; S.sel = null; draw(); }, 60); });
  document.querySelectorAll('[data-view]').forEach(b => { b.onclick = () => { S.view = b.dataset.view; draw(); }; });
  document.addEventListener('keydown', e => {
    if (document.querySelector('dialog[open]')) return;
    const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
    if (e.key === '/' && !inField) { e.preventDefault(); q.focus(); q.select(); }
    if (e.key === 'Escape') {
      const about = $('#files-about'); if (about.open) { about.open = false; return; }
      if (phone() && $('#files').dataset.pane === 'preview') pane('files');
      else if (!inField && S.q) clearSearch();
    }
    if (e.target === document.body && /^Arrow(Up|Down)$/.test(e.key)) { list.focus({preventScroll: true}); keys(e); }
  });
  document.addEventListener('click', e => { const about = $('#files-about'); if (about.open && !about.contains(e.target)) about.open = false; });

  // The index is checked again in the background while the page is open: look for news every few seconds while
  // the first reading runs, then every 30 seconds; redraw quietly when something changed.
  // wanted: the switch the person just set, until the server reports it (a poll in flight carries the old one)
  let lastChecked = null, pollTimer = null, inPoll = false, wanted, fastLeft = 0;
  async function poll() {
    inPoll = true;
    try { await pollOnce(); } finally { inPoll = false; }
  }
  async function pollOnce() {
    let st;
    try { st = await api('/api/status'); } catch (e) {
      if (e.status === 401 || e.status === 403) {  // another computer without the sign-in: nothing of the workspace shows
        $('#files').hidden = true;
        $('#files-notice').replaceChildren(UI.state({title: 'Sign in to see your files', text: 'Open Files from the orch dashboard with your sign-in link.'}));
        $('#files-notice').hidden = false;
        return;
      }
      pollTimer = setTimeout(poll, 10000); return;
    }
    const changed = st.checked_at !== lastChecked || st.total !== S.status.total || !S.loaded;
    S.status = Object.assign(S.status, st);
    if (wanted !== undefined) { if (st.show_ignored === wanted) wanted = undefined; else S.status.show_ignored = wanted; }
    drawNotice();
    if (st.ready && changed) {
      lastChecked = st.checked_at;
      const first = !S.loaded;
      await loadAll().catch(() => null);
      previews.clear();
      // redraw what is shown, a search too (its hits may have changed); never under an open big view
      if (first) { S.loaded = true; await applyParams(); } else if (!document.querySelector('dialog[open]')) await draw();
      else drawTree();
    }
    // after the switch: check every 1.5 s until the list was read again with it
    const behind = st.ready && S.status.show_ignored !== st.ignored_shown && fastLeft > 0;
    if (behind) fastLeft--;
    pollTimer = setTimeout(poll, behind ? 1500 : !st.ready || st.unread || st.building ? 2500 : 30000);
  }
  async function applyParams() {
    const params = new URLSearchParams(location.search);
    if (params.get('open') != null) { await openFolder(params.get('open'), true); }
    else if (PLACES[params.get('place')]) S.place = params.get('place');
    else if (params.get('place') === 'tickets' || params.get('ticket')) {
      S.place = 'tickets'; S.node = S.groups[0] ? S.groups[0].id : null;
      const want = params.get('ticket');
      for (const g of S.groups) { const tn = g.tickets.find(x => x.key === want || x.id === want); if (tn) { S.node = 't:' + tn.id; S.closed.delete(g.id); break; } }
    }
    if (params.get('view') === 'grid') S.view = 'grid';
    if (params.get('q')) { S.q = params.get('q'); q.value = S.q; }
    await draw();
    if (params.get('pane')) pane(params.get('pane'));
    if (params.get('pick')) { const r = S.rows.find(x => x.type === 'file' && x.f.name === params.get('pick')); if (r) { select(r.key); if (phone()) pane('preview'); } }
    if (params.get('big')) openBig();
    if (params.get('about')) $('#files-about').open = true;
  }
  // This page is a whole app: the dashboard lets its frame fill the page (no extra margins)
  try { parent.postMessage({orch: 'embed-shell', path: location.pathname, chan: Frame.chan}, location.origin); } catch (e) { /* not framed */ }
  poll();
})();

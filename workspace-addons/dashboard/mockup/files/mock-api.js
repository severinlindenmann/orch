/* Files page mockup: answers the page's /api/* calls from data.js (window.FILES_DATA) in the browser, so the mockup
   runs the product's own files.js (workspace-addons/files/src/orch_files/web/files.js) and cannot drift from it.
   ?state=loading shows the first reading (names ready, text follows), ?state=empty a workspace with no files. */
(() => {
  'use strict';
  const D = window.FILES_DATA, params = new URLSearchParams(location.search);
  const STATE = params.get('state') || 'loaded';
  const files = STATE === 'empty' ? [] : D.files;
  const now = Date.parse(D.now + ':00Z') / 1000, secs = iso => Math.round(Date.parse(iso + ':00Z') / 1000);
  const fold = s => String(s).normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const WORD = {md: 'Document', text: 'Text', code: 'Code', data: 'Data', table: 'Table', page: 'Web page', pdf: 'PDF', picture: 'Picture', video: 'Video', audio: 'Audio', archive: 'Archive', file: 'Other file'};
  const kind = f => f.type || window.UI.result.kindOf(f.name);
  const tid = key => 't_' + key.toLowerCase().replace('-', '');
  const T = D.tickets, stars = new Set(files.filter(f => D.starred.includes(f.name)).map(f => pathOf(f)));
  function pathOf(f) { return f.ticket ? '.orch/tickets/' + tid(f.ticket) + '/artifacts/' + f.name : (f.folder ? f.folder + '/' : '') + f.name; }
  const row = f => ({path: pathOf(f), name: f.name, folder: f.ticket ? '.orch/tickets/' + tid(f.ticket) + '/artifacts' : f.folder, kind: kind(f) === 'file' ? 'file' : kind(f),
    word: f.word || (/\.xlsx$/.test(f.name) ? 'Excel sheet' : WORD[kind(f)] || 'Other file'), size: f.size, changed: secs(f.changed), ticket: f.ticket ? tid(f.ticket) : null, title: f.title, private: false});
  const rows = files.map(row), byPath = new Map(files.map(f => [pathOf(f), f]));
  const own = rows.filter(r => !r.ticket);

  function tree() {
    const counts = {'': 0};
    own.forEach(r => { counts[''] += 1; const p = r.folder ? r.folder.split('/') : []; p.forEach((_, i) => { const k = p.slice(0, i + 1).join('/'); counts[k] = (counts[k] || 0) + 1; }); });
    return {folders: Object.keys(counts).sort().map(path => ({path, count: counts[path]}))};
  }
  function folder(p) {
    const prefix = p ? p + '/' : '', subs = {};
    own.forEach(r => { if (r.folder.startsWith(prefix) && r.folder !== p) { const top = r.folder.slice(prefix.length).split('/')[0]; subs[top] = (subs[top] || 0) + 1; } });
    return {path: p, folders: Object.keys(subs).sort().map(n => ({path: prefix + n, name: n, count: subs[n]})), files: own.filter(r => r.folder === p).sort((a, b) => a.name.localeCompare(b.name))};
  }
  function tickets() {
    const parts = {working: [], review: [], done: [], earlier: []};
    Object.values(T).forEach(t => {
      const fs = rows.filter(r => r.ticket === tid(t.key)).sort((a, b) => b.changed - a.changed);
      if (!fs.length) return;
      const old = t.status === 'done' && (now - Date.parse(t.done + 'T12:00:00Z') / 1000) / 86400 > 30;
      const part = t.status === 'done' ? (old ? 'earlier' : 'done') : t.status;
      parts[part].push({id: tid(t.key), key: t.key, title: t.title, status: t.status, files: fs, newest: fs[0].changed});
    });
    const label = {working: 'Working', review: 'In review', done: 'Done', earlier: 'Earlier'};
    return {groups: Object.keys(parts).filter(k => parts[k].length).map(k => ({id: k, label: label[k], tickets: parts[k].sort((a, b) => b.newest - a.newest)}))};
  }
  function search(q, namesOnly) {
    const words = fold(q).split(/\s+/).filter(Boolean), out = [], t0 = performance.now();
    rows.forEach(r => {
      const f = byPath.get(r.path), t = r.ticket ? Object.values(T).find(x => tid(x.key) === r.ticket) : null;
      const name = fold(r.title + '  ' + r.name + '  ' + (t ? t.title + ' ' + t.key : r.folder));
      const lines = String(f.text || '').split('\n'), flines = lines.map(fold);
      if (words.every(w => name.includes(w))) return out.push({...r, found: 'name', rank: 0});
      if (namesOnly || STATE === 'loading') return;
      if (!words.every(w => name.includes(w) || flines.some(l => l.includes(w)))) return;
      const i = flines.findIndex(l => words.some(w => !name.includes(w) && l.includes(w)));
      out.push({...r, found: 'text', rank: 1, line: i >= 0 ? lines[i].replace(/^[#>\-*\s]+/, '') : null});
    });
    out.sort((a, b) => a.rank - b.rank || b.changed - a.changed);
    return {query: q, items: out, total: rows.length, unread: STATE === 'loading' ? D.building.total - D.building.read : 0, ms: Math.round((performance.now() - t0) * 10) / 10, ready: true};
  }
  function preview(p) {
    const f = byPath.get(p); if (!f) return null;
    const k = kind(f), base = {type: k === 'file' ? 'file' : k, name: f.title, size: f.size, download: 'api/file?p=' + encodeURIComponent(p) + '&dl=1'};
    if (k === 'picture') return {...base, src: f.src || f.thumb};
    if (k === 'video') return {...base, state: 'large', too_big: true, poster: f.poster, thumb: f.thumb};
    if (k === 'pdf') return {...base, thumb: f.thumb, pages: f.pages};
    if (k === 'archive') return {...base, files: f.files, total: f.total};
    if (f.rows) return {...base, type: 'table', rows: f.rows};
    if (f.text != null) return {...base, text: f.text};
    return base;
  }
  const answer = (u, body) => {
    const p = new URLSearchParams(u.search), path = u.pathname;
    if (path === '/api/status') return {ready: true, total: STATE === 'loading' ? D.building.total : rows.length, unread: STATE === 'loading' ? D.building.total - D.building.read : 0, checked_at: now - 40, building: STATE === 'loading', error: null, stars: stars.size, new_since: secs(D.lastLooked), new: rows.filter(r => r.changed > secs(D.lastLooked)).length, workspace: D.workspace, now};
    if (path === '/api/tree') return tree();
    if (path === '/api/folder') return folder(p.get('p') || '');
    if (path === '/api/tickets') return tickets();
    if (path === '/api/search') return search(p.get('q') || '', p.get('names') === '1');
    if (path === '/api/recent') return {files: rows.slice().sort((a, b) => b.changed - a.changed).slice(0, 30)};
    if (path === '/api/new') return {files: rows.filter(r => r.changed > secs(D.lastLooked)).sort((a, b) => b.changed - a.changed)};
    if (path === '/api/starred') return {files: rows.filter(r => stars.has(r.path))};
    if (path === '/api/preview') return preview(p.get('p'));
    if (path === '/api/act') { const a = JSON.parse(body || '{}'); a.op === 'star' ? stars.add(a.args.path) : stars.delete(a.args.path); return {result: {stars: stars.size}}; }
    return null;
  };
  const real = window.fetch.bind(window);
  window.fetch = async (input, opts) => {
    const u = new URL(String(input), location.href);
    if (!u.pathname.startsWith('/api/')) return real(input, opts);
    const data = answer(u, opts && opts.body);
    await new Promise(r => setTimeout(r, 30));
    return data == null ? new Response('not found', {status: 404}) : new Response(JSON.stringify(data), {status: 200, headers: {'Content-Type': 'application/json'}});
  };
})();

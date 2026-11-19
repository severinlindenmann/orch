'use strict';
// A ticket's results as the result widgets of the style guide (ORCH-697, draft D feature 10). One place turns what a
// ticket holds into widget items, and the style guide's one renderer (kit/results.js, UI.result / UI.resultOverlay)
// draws them: small on a wall tile, inside a session's chat, and on the ticket page; a click opens the big overlay.
//   files     the ticket's result files (orch ticket artifacts), not the files the person attached themselves
//   evidence  the files a step proved, a check run (command, exit, last output lines), a pull request, an address
//   links     the pull requests and addresses on the ticket (its references)
// Text kinds (document, text, code, data, table, change) are read through /api/file once and kept for a while;
// an archive's listing and a PDF's pages come from /api/file-info. A JSON file shaped {labels: [...], values: [...]}
// is a chart. Everything else the widget shows by its address (picture, video, audio, PDF, web page in its frame).
const RESULTS_TTL = 30000;              // a ticket's file list and a file's text are read again after this
const RESULTS_TEXT_MAX = 256 * 1024;    // characters of a text result kept; a longer one shows its first part
const RESULTS_RUNS = 3;                 // check runs shown per ticket, the newest
const RESULTS_TILE = 1;                 // widgets on a wall tile (the newest); the rest is "+N more"

function resultsArr(x) { return Array.isArray(x) ? x : []; }
function resultsStr(x) { return typeof x === 'string' ? x.trim() : ''; }
function resultsBase(name) { return String(name || '').split('/').pop(); }
function resultsUrl(tid, kind, name, dl) {
  return '/api/file?t=' + encodeURIComponent(tid) + '&k=' + encodeURIComponent(kind) + '&n=' + encodeURIComponent(name) + (dl ? '&dl=1' : '');
}
function resultsInfoUrl(tid, kind, name) {
  return '/api/file-info?t=' + encodeURIComponent(tid) + '&k=' + encodeURIComponent(kind) + '&n=' + encodeURIComponent(name);
}
function resultsPageUrl(tid, kind, name) {
  return '/view/' + encodeURIComponent(tid) + '/' + kind + '/' + String(name).split('/').map(encodeURIComponent).join('/');
}
function resultsKind(name) {
  if (typeof window === 'object' && window.UI?.result?.kindOf) return window.UI.result.kindOf(name);
  return 'file';
}
// A file of a step's evidence: .orch/tickets/<id>/evidence/<name> or .../artifacts/<name>
function resultsEvidenceFile(tid, ev) {
  const ref = String(ev?.ref || ''), m = /^\.orch\/tickets\/(t_[a-z0-9]{6,16})\/(evidence|artifacts)\/(.+)$/.exec(ref);
  return m && m[1] === tid && !m[3].split('/').includes('..') ? {kind:m[2], name:m[3]} : null;
}
// The files the person attached themselves (their own input, not a result): "Attached <name>" by a person
function resultsOwnFiles(t) {
  const own = new Set();
  for (const e of resultsArr(t?.history)) {
    const m = /^Attached (.+)$/.exec(String(e?.text || ''));
    if (m && /^human:/.test(String(e?.by || ''))) own.add(m[1].trim());
  }
  return own;
}
const RESULTS_PLURAL = (n, one, many) => n + ' ' + (n === 1 ? one : many || one + 's');
function resultsTime(at) {
  const ms = Date.parse(at || '');
  if (!Number.isFinite(ms)) return '';
  return typeof time === 'function' ? time(at) : new Date(ms).toISOString().slice(11, 16);
}
// One file as a widget item; its content (text, listing) comes later through resultsFill.
function resultsFileItem(tid, kind, file, extra = {}) {
  const name = file.name, base = resultsBase(name);
  let type = resultsKind(name);
  if (type === 'archive' && !/\.zip$/i.test(name)) type = 'file';  // only a zip lists its files
  const item = {type, name:base, size:typeof file.size === 'number' ? file.size : undefined, download:resultsUrl(tid, kind, name, true),
    key:kind + ':' + name, src0:{tid, kind, name}, at:file.mtime || extra.at || '', ...extra};
  if (!item.title) delete item.title;
  if (type === 'picture' || type === 'video' || type === 'audio' || type === 'pdf') { item.src = resultsUrl(tid, kind, name); item.href = item.src; }
  if (type === 'picture') item.alt = extra.title || base;
  if (type === 'page') { item.src = resultsPageUrl(tid, kind, name); item.href = item.src; }
  if (['md', 'text', 'code', 'data', 'table', 'change', 'archive', 'pdf'].includes(type)) item.state = 'loading';
  return item;
}
// What a check run says: passed, failed with its exit, or only ran
function resultsRunItem(tid, task, ev, i) {
  const cmd = resultsStr(ev.ref), ok = ev.exit === 0, failed = typeof ev.exit === 'number' && ev.exit !== 0;
  const word = ok ? 'Check passed' : failed ? 'Check failed (exit ' + ev.exit + ')' : 'Check ran';
  const tail = resultsStr(ev.output_tail), stamp = resultsTime(ev.ran_at || ev.at);
  const text = '$ ' + cmd + (tail ? '\n' + tail : '') + '\n' + word;
  return {type:'text', name:resultsStr(ev.title) || cmd.slice(0, 80), meta:word + (stamp ? ' · ' + stamp : ''), text, wrap:true,
    key:'run:' + cmd + ':' + (ev.ran_at || ev.at || i), at:ev.ran_at || ev.at || '', step:task?.id || undefined};
}
const RESULTS_PR = /^https:\/\/github\.com\/([^/]+\/[^/]+)\/(pull|issues)\/(\d+)/;
function resultsLinkItem(url, ref = {}, ev = {}) {
  const pr = RESULTS_PR.exec(url), title = resultsStr(ref.title) || resultsStr(ev.title);
  if (pr) {
    const issue = pr[2] === 'issues', status = resultsStr(ref.status);
    const word = (issue ? 'Issue ' : 'Pull request ') + pr[3];
    return {type:'pr', name:word, title:title && !/^(Issue|Pull request) #?\d+$/.test(title) ? title : '', status, href:url,
      meta:(issue ? 'Issue' : 'Pull request') + (status ? ' · ' + status : ''), checks:resultsArr(ref.checks).filter(c => c && c.name),
      key:'url:' + url.replace(/[#?].*$/, ''), at:ref.at || ev.at || ''};
  }
  let host = url;
  try { host = new URL(url).host; } catch { /* kept as written */ }
  return {type:'link', name:title || host, meta:host, href:url, key:'url:' + url, at:ref.at || ev.at || ''};
}
// Every result of one ticket as widget items, oldest first (the order they were made); files is the answer of
// /api/artifacts/<id> ({files: [{name, size, mtime}]}) or null while it is not read yet.
function resultsItems(t, files) {
  if (!t || typeof t !== 'object' || !t.id) return [];
  const tid = t.id, out = [], seen = new Set(), own = resultsOwnFiles(t);
  const add = (it, step) => {
    if (!it) return;
    if (seen.has(it.key)) {  // a result file a step also proved: the step and its words join the one widget
      const had = out.find(x => x.key === it.key);
      if (had && step && !had.step) had.step = step;
      if (had && it.title && !had.title) { had.title = it.title; if (had.type === 'picture') had.alt = it.title; }
      if (had && resultsAt(it) > resultsAt(had)) had.at = it.at;
      return;
    }
    if (step) it.step = step;
    seen.add(it.key); out.push(it);
  };
  for (const f of resultsArr(files?.files)) {
    if (f && typeof f.name === 'string' && !own.has(f.name)) add(resultsFileItem(tid, 'artifacts', f));
  }
  const runs = [];
  for (const task of resultsArr(t.checklist)) {
    if (!task || typeof task !== 'object') continue;
    resultsArr(task.evidence).forEach((ev, i) => {
      if (!ev || typeof ev !== 'object') return;
      const kind = ev.type || ev.kind, file = resultsEvidenceFile(tid, ev);
      if (file) {
        const known = file.kind === 'artifacts' ? resultsArr(files?.files).find(f => f && f.name === file.name) : null;
        if (!own.has(file.name)) add(resultsFileItem(tid, file.kind, known || {name:file.name}, {title:resultsStr(ev.title), at:ev.at || ''}), task.id);
      } else if (kind === 'command' && (typeof ev.exit === 'number' || ev.output_tail)) runs.push(resultsRunItem(tid, task, ev, i));
      else if ((kind === 'pr' || kind === 'url') && /^https:\/\//.test(String(ev.ref || ''))) {
        const ref = resultsArr(t.refs).find(r => r && (r.url || r.ref) === ev.ref) || {};
        add(resultsLinkItem(String(ev.ref), ref, ev), task.id);
      }
    });
  }
  // the newest run of each command, the newest few overall
  const lastRun = new Map();
  for (const r of runs) { const k = r.text.split('\n')[0]; if (!lastRun.has(k) || String(lastRun.get(k).at) <= String(r.at)) lastRun.set(k, r); }
  [...lastRun.values()].sort((a, b) => String(a.at).localeCompare(String(b.at))).slice(-RESULTS_RUNS).forEach(r => add(r, r.step));
  for (const r of resultsArr(t.refs)) {
    const url = r && typeof (r.url || r.ref) === 'string' ? (r.url || r.ref) : '';
    if (r && (r.kind === 'url' || !r.kind) && /^https:\/\//.test(url)) add(resultsLinkItem(url, r));
  }
  // files and runs first in the order made, then pull requests, then plain links
  const rank = it => it.type === 'link' ? 2 : it.type === 'pr' ? 1 : 0;
  return out.map((it, n) => [it, n]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(x => x[0]);
}
// ---- reading the content of a text, listing or chart result
// A unified diff: the files it changes with lines added and taken out
function resultsDiffFiles(text) {
  const files = [];
  let cur = null;
  for (const line of String(text || '').split('\n')) {
    const m = /^\+\+\+ (?:b\/)?(.+)$/.exec(line);
    if (m) { cur = [m[1].trim(), 0, 0]; if (cur[0] !== '/dev/null') files.push(cur); continue; }
    if (/^diff --git /.test(line) || /^--- /.test(line)) continue;
    if (cur && line[0] === '+') cur[1]++;
    else if (cur && line[0] === '-') cur[2]++;
  }
  return files;
}
// A JSON chart: {labels: [...], values: [numbers]} of the same length (unit, kind: 'line' are kept)
function resultsChart(text) {
  let d;
  try { d = JSON.parse(text); } catch { return null; }
  if (!d || typeof d !== 'object' || Array.isArray(d)) return null;
  const labels = resultsArr(d.labels), values = resultsArr(d.values);
  if (!labels.length || labels.length !== values.length || labels.length > 400 || !values.every(v => typeof v === 'number' && Number.isFinite(v))) return null;
  return {labels:labels.map(String), values, unit:resultsStr(d.unit) || undefined, labelName:resultsStr(d.label) || undefined, kind:d.kind === 'line' ? 'line' : undefined,
    title:resultsStr(d.title) || undefined};
}
// The item with what was read: {text}, {info}, or {error: 'large' | 'error'}
function resultsWith(item, got) {
  const it = {...item};
  delete it.state;
  if (got.error) { it.state = got.error === 'large' ? 'large' : 'error'; return it; }
  if (got.info) {
    if (it.type === 'archive') {
      const entries = resultsArr(got.info.entries);
      it.files = entries.map(e => [String(e.name), typeof e.size === 'number' ? resultsSize(e.size) : '']);
      it.total = typeof got.info.count === 'number' ? got.info.count : entries.length;
      it.meta = 'Archive · ' + RESULTS_PLURAL(it.total, 'file');
    } else if (it.type === 'pdf') {
      if (typeof got.info.pages === 'number' && got.info.pages > 0) { it.pages = got.info.pages; it.meta = 'PDF · ' + RESULTS_PLURAL(it.pages, 'page'); }
    } else if (it.type === 'table' && Array.isArray(got.info.rows)) {  // a workbook's first sheet: its header, then its rows
      it.rows = [resultsArr(got.info.columns).map(String), ...got.info.rows.map(r => resultsArr(r).map(String))];
      const n = typeof got.info.rowCount === 'number' ? got.info.rowCount : it.rows.length - 1;
      it.meta = 'Table · ' + RESULTS_PLURAL(n, 'row');
    }
    return it;
  }
  let text = String(got.text ?? '');
  if (text.length > RESULTS_TEXT_MAX) { text = text.slice(0, RESULTS_TEXT_MAX); it.state = 'large'; it.shown = 40; }
  it.text = text;
  const n = text ? text.replace(/\n$/, '').split('\n').length : 0;
  if (it.type === 'data') {
    const c = resultsChart(text);
    if (c) {
      Object.assign(it, c, {type:'chart', name:c.title || it.name, meta:'Chart · ' + RESULTS_PLURAL(c.values.length, 'value')});
      delete it.text; delete it.title;
      return it;
    }
    it.meta = 'Data · ' + RESULTS_PLURAL(n, 'line');
  } else if (it.type === 'change') {
    it.files = resultsDiffFiles(text);
    it.diff = text;
    it.meta = 'Change · ' + RESULTS_PLURAL(it.files.length, 'file');
  } else if (it.type === 'table') {
    const rows = Math.max(0, n - 1);
    it.meta = 'Table · ' + RESULTS_PLURAL(rows, 'row');
  } else if (it.type === 'md') it.meta = 'Document · ' + RESULTS_PLURAL(n, 'line');
  else if (it.type === 'code') it.meta = 'Code · ' + RESULTS_PLURAL(n, 'line');
  else if (it.type === 'text') it.meta = 'Text · ' + RESULTS_PLURAL(n, 'line');
  return it;
}
function resultsAt(it) { const ms = Date.parse(it.at || ''); return Number.isFinite(ms) ? ms : 0; }
function resultsSize(n) { return n < 1024 ? n + ' B' : n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
// ---- the page: reading, caching, drawing
const resultsCache = new Map();   // '<url>' -> {at, p: Promise, v}
function resultsGet(url, how) {
  const hit = resultsCache.get(url);
  if (hit && Date.now() - hit.at < RESULTS_TTL) return hit.p;
  const p = fetch(url, {credentials:'same-origin'}).then(async r => {
    if (r.status === 413) return {error:'large'};
    if (!r.ok) return {error:'error'};
    return how === 'json' ? r.json() : {text:await r.text()};
  }).catch(() => ({error:'error'}));
  resultsCache.set(url, {at:Date.now(), p});
  return p;
}
function resultsFiles(tid) {
  return resultsGet('/api/artifacts/' + encodeURIComponent(tid), 'json').then(d => (d && !d.error ? d : {files:[]}));
}
function resultsFill(item) {
  if (item.state !== 'loading' || !item.src0) return Promise.resolve(item);
  const {tid, kind, name} = item.src0;
  if (item.type === 'archive' || item.type === 'pdf' || (item.type === 'table' && /\.xlsx$/i.test(name))) {
    return resultsGet(resultsInfoUrl(tid, kind, name), 'json').then(d => d && d.error === 'too large' ? resultsWith(item, {error:'large'})
      : d && d.error === 'unreadable' ? resultsWith(item, {error:'error'})
        : d && d.error ? resultsWith(item, d) : resultsWith(item, {info:d || {}}));
  }
  return resultsGet(resultsUrl(tid, kind, name), 'text').then(d => resultsWith(item, d));
}
// All results of a ticket, read: the list draws at once (text kinds loading) and again when each one is read
function resultsLoad(t, onItems) {
  if (!t?.id) { onItems([]); return; }
  resultsFiles(t.id).then(files => {
    const list = resultsItems(t, files);
    onItems(list);
    const pending = list.filter(it => it.state === 'loading');
    if (!pending.length) return;
    Promise.all(list.map(resultsFill)).then(onItems);
  });
}
function resultsSig(list) { return list.map(it => [it.key, it.type, it.state || '', it.meta || '', (it.text || '').length, it.status || ''].join('\u0001')).join('\u0002'); }
// Draws a list of items into a host: small widgets in a grid, plain links as rows under them; a click opens the
// overlay over the whole list. max: at most that many widgets, then "+N more" (opens the overlay at the next one).
function resultsDraw(host, list, o = {}) {
  const UI = window.UI;
  if (!UI?.result) return;
  const sig = resultsSig(list) + '|' + (o.max || '') + '|' + (o.all ? resultsSig(o.all) : '');
  if (host.resultsSig === sig) return;
  host.resultsSig = sig;
  const widgets = list.filter(it => it.type !== 'link'), links = list.filter(it => it.type === 'link');
  if (o.newest) widgets.sort((a, b) => resultsAt(b) - resultsAt(a));  // a wall tile shows the newest result first
  const shown = o.max ? widgets.slice(0, o.max) : widgets, rest = widgets.length - shown.length;
  const grid = document.createElement('div');
  grid.className = 'result-grid' + (o.size === 'lg' ? ' big' : '');
  // the overlay steps through every result of the ticket (draft D), also from a step's message that shows only its own
  const pool = o.all ? o.all.filter(it => it.type !== 'link') : widgets;
  shown.forEach(it => grid.append(UI.result(it, {size:o.size === 'lg' ? 'lg' : 'sm', list:pool, index:Math.max(0, pool.indexOf(it)), onRetry:() => { resultsForget(it); resultsRefill(host); }})));
  if (rest > 0) {
    const more = document.createElement('button');
    more.type = 'button'; more.className = 'btn ghost sm result-more';
    more.textContent = '+' + rest + ' more';
    more.setAttribute('aria-label', 'Open the other ' + RESULTS_PLURAL(rest, 'result') + ' big');
    more.addEventListener('click', () => UI.resultOverlay(pool, Math.max(0, pool.indexOf(widgets[shown.length]))));
    grid.append(more);
  }
  const parts = [];
  if (widgets.length) parts.push(grid);
  if (links.length && !o.max) {
    const row = document.createElement('div');
    row.className = 'result-links';
    links.forEach(it => row.append(UI.result(it, {size:'sm'})));
    parts.push(row);
  }
  if (!parts.length && o.empty) {
    const p = document.createElement('p');
    p.className = 'meta'; p.textContent = o.empty;
    parts.push(p);
  }
  const log = host.closest('[data-live-chat]'), end = log && log.scrollHeight - log.scrollTop - log.clientHeight < 8;
  host.replaceChildren(...parts);
  host.hidden = !parts.length;
  if (end) log.scrollTop = log.scrollHeight;  // a chat that was at its end stays there when the widgets come in
}
function resultsForget(item) {
  if (!item?.src0) return;
  const {tid, kind, name} = item.src0;
  resultsCache.delete(resultsUrl(tid, kind, name)); resultsCache.delete(resultsInfoUrl(tid, kind, name));
}
// A host element: <div data-results-host="<ticket id>" data-results-size="sm|lg" data-results-max="3"
//   data-results-step="<task id>" data-results-empty="...">. The page's redraw keeps its children (app.js sync).
function resultsHost(tid, o = {}) {
  return h('div', {className:'results-host' + (o.cls ? ' ' + o.cls : ''), 'data-results-host':tid, 'data-key':o.key || 'results-' + tid,
    'data-results-size':o.size || 'sm', 'data-results-max':o.max ? String(o.max) : null, 'data-results-step':o.step || null,
'data-results-empty':o.empty || null, 'aria-label':o.label || null, role:o.label ? 'group' : null});
}
function resultsRefill(host) {
  const tid = host.dataset.resultsHost, t = typeof ticketOf === 'function' ? ticketOf(tid) : null;
  if (!t) return;
  const step = host.dataset.resultsStep || '';
  const o = {size:host.dataset.resultsSize, max:Number(host.dataset.resultsMax) || 0, empty:host.dataset.resultsEmpty || '', newest:host.dataset.resultsMax ? true : false};
  resultsLoad(t, list => { if (host.isConnected) resultsDraw(host, step ? list.filter(it => it.step === step) : list, step ? {...o, all:list} : o); });
}
// Fills every host under root; called after each redraw. A host fills again only when its ticket changed.
function resultsFillAll(root) {
  if (!root?.querySelectorAll || typeof window !== 'object' || !window.UI?.result) return;
  root.querySelectorAll('[data-results-host]').forEach(host => {
    const t = typeof ticketOf === 'function' ? ticketOf(host.dataset.resultsHost) : null;
    const stamp = t ? String(t.updated_at || t.updated || '') + '|' + resultsArr(t.checklist).length + '|' + resultsArr(t.refs).length : '';
    if (host.resultsStamp === stamp && host.resultsAt && Date.now() - host.resultsAt < RESULTS_TTL) return;
    host.resultsStamp = stamp; host.resultsAt = Date.now();
    resultsRefill(host);
  });
}
if (typeof module === 'object' && module.exports) {
  module.exports = {resultsItems, resultsWith, resultsDiffFiles, resultsChart, resultsEvidenceFile, resultsOwnFiles, resultsLinkItem, RESULTS_TILE};
}

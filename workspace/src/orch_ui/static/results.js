/* Result widgets and the big overlay (ORCH-263, look from Focus draft D).
   One widget per kind of result a helper hands back: Markdown, text and logs, code, JSON and YAML, table, web page,
   PDF, picture, video, audio, chart, change, pull request link, archive, plain link and unknown file.
   The overlay uses the dialog lifecycle of overlay.js (× Close, Esc, focus back to the opener; a click beside it does nothing).
     UI.result(item, {size: 'sm' | 'lg', state, list, index, onOpen, onRetry})   -> element
     UI.resultOverlay(list, index, {onRetry})                                   -> the open <dialog>
     UI.result.kindOf('notes.md') -> 'md'      UI.result.TYPES -> [{id, word, icon}]
   item = {type?, name, meta?, size? (bytes), href? (open), download? (url), state?, ...the kind's own fields below}.
   state: 'ready' (default), 'empty', 'loading', 'error', 'large' (too big: a partial preview when the item has one).
   Text only ever goes in with textContent; a web page only inside a frame with an empty sandbox. No fetching here:
   the page that uses a widget hands it the content. */
(() => {
  'use strict';
  const UI = window.UI = window.UI || {};
  const LIMIT = 10 * 1048576;
  const TYPES = [
    {id: 'md', word: 'Document', icon: 'note'}, {id: 'text', word: 'Text', icon: 'text'},
    {id: 'code', word: 'Code', icon: 'code'}, {id: 'data', word: 'Data', icon: 'braces'},
    {id: 'table', word: 'Table', icon: 'table'}, {id: 'page', word: 'Web page', icon: 'page'},
    {id: 'pdf', word: 'PDF', icon: 'file'}, {id: 'picture', word: 'Picture', icon: 'image'},
    {id: 'video', word: 'Video', icon: 'video'}, {id: 'audio', word: 'Audio', icon: 'wave'},
    {id: 'chart', word: 'Chart', icon: 'chart'}, {id: 'change', word: 'Change', icon: 'diff'},
    {id: 'pr', word: 'Pull request', icon: 'pull'}, {id: 'archive', word: 'Archive', icon: 'archive'},
    {id: 'link', word: 'Link', icon: 'link'}, {id: 'file', word: 'File', icon: 'file'}
  ];
  const BY = Object.fromEntries(TYPES.map(t => [t.id, t]));
  const EXT = {
    md: /^(md|markdown)$/, text: /^(txt|log|out)$/, code: /^(py|js|mjs|ts|tsx|jsx|sh|css|sql|rs|go|rb|java|swift|kt|c|h|cpp|toml|ini)$/,
    data: /^(json|jsonl|ya?ml)$/, table: /^(csv|tsv|xlsx)$/, page: /^html?$/, pdf: /^pdf$/, picture: /^(png|jpe?g|gif|webp|svg)$/,
    video: /^(mp4|webm|mov|m4v)$/, audio: /^(mp3|wav|m4a|ogg|oga|aac)$/, change: /^(diff|patch)$/, archive: /^(zip|tar|gz|tgz)$/
  };
  const kindOf = name => {
    const s = String(name || '');
    if (/^https?:\/\//.test(s)) return /\/pull\/\d+|\/issues\/\d+|merge_requests\/\d+/.test(s) ? 'pr' : 'link';
    const e = (/\.([^./]+)$/.exec(s)?.[1] || '').toLowerCase();
    return Object.keys(EXT).find(k => EXT[k].test(e)) || 'file';
  };
  const EMPTY = {
    md: 'This document is empty.', text: 'This file is empty.', code: 'This file is empty.', data: 'No data in this file.',
    table: 'This table has no rows.', page: 'This page is empty.', pdf: 'This PDF has no pages.', picture: 'This picture is empty.',
    video: 'This video has no picture or sound.', audio: 'This recording is silent.', chart: 'No numbers to show yet.',
    change: 'No files changed.', pr: 'No checks have run yet.', archive: 'This archive has no files.',
    link: 'This link has no address.', file: 'This file is empty.'
  };
  const MEDIA = new Set(['picture', 'video', 'audio', 'pdf', 'page']);

  // ---- small helpers
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined && text !== null) n.textContent = String(text); return n; };
  const ic = (name, size) => { const t = document.createElement('template'); t.innerHTML = window.icon ? window.icon(name, size || 16) : ''; return t.content; };
  const button = (label, cls, onClick, attrs) => {
    const b = el('button', 'btn ' + (cls || 'ghost sm')); b.type = 'button';
    if (attrs && attrs.icon) b.append(ic(attrs.icon, 16));
    if (label) b.append(el('span', '', label));
    if (onClick) b.addEventListener('click', onClick);
    for (const [k, v] of Object.entries(attrs || {})) if (k !== 'icon') b.setAttribute(k, v);
    return b;
  };
  // The one scheme check for every address an item brings (a helper or another workspace wrote it): http, https,
  // mailto or a relative address; anything else (javascript:, data:, vbscript:, blob: ...) is dropped.
  const safeHref = u => {
    const s = typeof u === 'string' ? u.trim() : '';
    if (!s) return '';
    const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(s.replace(/[\u0000-\u0020\u007f-\u009f]/g, ''));
    return !scheme || /^(https?|mailto)$/i.test(scheme[1]) ? s : '';
  };
  const linkBtn = (label, href, cls, iconName, dl) => {
    href = safeHref(href); if (!href) return null;
    const a = el('a', 'btn ' + (cls || 'ghost sm')); a.href = href;
    if (dl) a.setAttribute('download', ''); else { a.target = '_blank'; a.rel = 'noopener'; }
    if (iconName) a.append(ic(iconName, 16)); a.append(el('span', '', label)); return a;
  };
  const sizeText = n => n < 1024 ? n + ' B' : n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  const plural = (n, one, many) => n + ' ' + (n === 1 ? one : (many || one + 's'));
  const lines = t => String(t || '').replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n');
  const hostOf = href => { try { return new URL(href, location.href).host; } catch (e) { return String(href || ''); } };
  const filled = (item, type) => {
    switch (type) {
      case 'md': case 'text': case 'code': case 'data': return !!String(item.text || '').trim();
      case 'table': return parseRows(item).length > 1;
      case 'chart': return (item.values || []).length > 0;
      case 'change': return (item.files || []).length > 0;
      case 'pr': return true;
      case 'archive': return (item.files || []).length > 0;
      case 'link': return !!safeHref(item.href);
      case 'file': return item.size !== 0;
      default: return !!(item.src || item.thumb) && item.size !== 0;
    }
  };
  function stateOf(item, o, type) {
    const s = o.state || item.state;
    if (s && s !== 'ready') return s;
    if (!filled(item, type)) return 'empty';
    if (item.size > LIMIT && type !== 'link' && type !== 'pr') return 'large';
    return 'ready';
  }
  function metaOf(item, type) {
    if (item.meta) return item.meta;
    const w = BY[type].word;
    return item.size ? w + ' · ' + sizeText(item.size) : w;
  }

  // ---- text renderers (every bit of text through textContent)
  function inline(parent, text) {
    String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach(part => {
      if (/^\*\*[^*]+\*\*$/.test(part)) parent.append(el('strong', '', part.slice(2, -2)));
      else if (/^`[^`]+`$/.test(part)) parent.append(el('code', '', part.slice(1, -1)));
      else if (part) parent.append(document.createTextNode(part));
    });
  }
  function markdown(text, max) {
    const box = el('div', 'result-md'); let list = null, para = null, n = 0;
    // HTML comments are not shown in Markdown, as on GitHub (an agent tool's <!-- orch:begin --> markup, ORCH-1691)
    for (const raw of lines(String(text || '').replace(/<!--[\s\S]*?(?:-->|$)/g, ''))) {
      if (max && n >= max) break;
      const line = raw.trimEnd(), h = /^(#{1,6})\s+(.*)$/.exec(line), li = /^\s*(?:[-*+]|\d+\.)\s+(.*)$/.exec(line);
      if (!line.trim()) { list = null; para = null; continue; }
      if (h) { list = null; para = null; const t = el(h[1].length < 2 ? 'h3' : 'h4'); inline(t, h[2]); box.append(t); n++; continue; }
      if (li) { para = null; if (!list) { list = el('ul'); box.append(list); } const i = el('li'); inline(i, li[1]); list.append(i); n++; continue; }
      list = null;
      if (para) { para.append(document.createTextNode(' ')); inline(para, line.trim()); }
      else { para = el('p'); inline(para, line.trim()); box.append(para); n++; }
    }
    return box;
  }
  const KEYWORDS = /^(def|class|return|if|elif|else|for|while|in|not|and|or|import|from|as|with|try|except|finally|raise|function|const|let|var|new|async|await|export|default|true|false|null|None|True|False|fn|pub|use|match|struct|impl|echo|then|fi|do|done)$/;
  function highlight(parent, line) {
    const re = /(#.*$|\/\/.*$|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b[A-Za-z_][A-Za-z0-9_]*\b|\b\d+(?:\.\d+)?\b)/g;
    let at = 0, m;
    while ((m = re.exec(line))) {
      if (m.index > at) parent.append(document.createTextNode(line.slice(at, m.index)));
      const t = m[0], cls = /^(#|\/\/)/.test(t) ? 'tok-comment' : /^["']/.test(t) ? 'tok-string' : /^\d/.test(t) ? 'tok-const' : KEYWORDS.test(t) ? 'tok-keyword' : '';
      parent.append(cls ? el('span', cls, t) : document.createTextNode(t)); at = m.index + t.length;
    }
    if (at < line.length) parent.append(document.createTextNode(line.slice(at)));
  }
  function code(text, o) {
    const all = lines(text), from = o.from || 0, shown = all.slice(from, o.max ? from + o.max : undefined);
    const pre = el('pre', 'result-code' + (o.numbers === false ? '' : ' numbered') + (o.wrap ? ' wrap' : ''));
    shown.forEach((ln, i) => {
      const row = el('span', 'result-ln');
      if (o.numbers !== false) row.append(el('i', '', from + i + 1));
      const body = el('span'); if (o.highlight) highlight(body, ln); else body.textContent = ln;
      row.append(body); pre.append(row);
    });
    return pre;
  }
  const count = v => Array.isArray(v) ? plural(v.length, 'item') : plural(Object.keys(v).length, 'key');
  // A closed row says what is inside in words a person can read (its title or first text), not only "8 keys" (ORCH-1836).
  const GIST = ['title', 'name', 'summary', 'text', 'label', 'step', 'message', 'description', 'id'];
  function gist(v) {
    const plain = x => typeof x === 'string' && x.trim() ? x.replace(/\s+/g, ' ').trim() : null;
    const list = Array.isArray(v) ? v : Object.values(v);
    const pick = (!Array.isArray(v) && GIST.map(k => plain(v[k])).find(Boolean)) || list.map(plain).find(Boolean);
    return pick ? (pick.length > 90 ? pick.slice(0, 89) + '…' : pick) + ' · ' + count(v) : count(v);
  }
  function tree(value, depth, openTo) {
    const box = el('div', 'result-tree');
    const entries = Array.isArray(value) ? value.map((v, i) => [i, v]) : Object.entries(value);
    for (const [k, v] of entries) {
      if (v && typeof v === 'object') {
        const d = el('details'); if (depth < openTo) d.open = true;
        const s = el('summary'); s.append(el('span', 'result-key', k), el('i', '', gist(v))); d.append(s, tree(v, depth + 1, openTo));
        box.append(d);
      } else {
        const p = el('p'); p.append(el('span', 'result-key', k), el('span', typeof v === 'string' ? 'tok-string' : 'tok-const', JSON.stringify(v)));
        box.append(p);
      }
    }
    return box;
  }
  function parseData(text) { try { const v = JSON.parse(text); return v && typeof v === 'object' ? v : null; } catch (e) { return null; } }
  function parseRows(item) {
    if (item.rows) return item.rows;
    const out = [[]]; let cell = '', q = false; const s = String(item.text || ''), sep = item.sep || (s.split('\n')[0].includes('\t') ? '\t' : ',');
    for (let i = 0; i < s.length; i++) {
      const c = s[i];
      if (q) { if (c === '"' && s[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
      else if (c === '"') q = true;
      else if (c === sep) { out[out.length - 1].push(cell); cell = ''; }
      else if (c === '\n' || c === '\r') { if (c === '\r' && s[i + 1] === '\n') i++; out[out.length - 1].push(cell); cell = ''; out.push([]); }
      else cell += c;
    }
    if (cell || out[out.length - 1].length) out[out.length - 1].push(cell);
    return out.filter(r => r.length && r.some(c => c !== ''));
  }
  function table(rows, caption, o) {
    const wrap = el('div', 'result-table'), t = el('table'), head = rows[0] || [];
    t.append(el('caption', 'sr-only', caption));
    if (o.head !== false) { const th = el('thead'), tr = el('tr'); head.forEach((c, i) => { const h = el('th', o.num && o.num.includes(i) ? 'numeric' : '', c); h.scope = 'col'; tr.append(h); }); th.append(tr); t.append(th); }
    const tb = el('tbody');
    rows.slice(o.head === false ? 0 : 1, o.max ? (o.head === false ? 0 : 1) + o.max : undefined).forEach(r => {
      const tr = el('tr'); r.forEach((c, i) => { const d = el(i || o.head === false ? 'td' : 'th', o.num && o.num.includes(i) ? 'numeric' : '', c); if (!i && o.head !== false) d.scope = 'row'; tr.append(d); }); tb.append(tr);
    });
    t.append(tb); wrap.append(t); return wrap;
  }
  const kv = rows => { const d = el('dl', 'result-kv'); rows.forEach(([k, v]) => d.append(el('dt', '', k), el('dd', '', v))); return d; };

  // ---- pictures drawn on tokens (no colours here)
  const NS = 'http://www.w3.org/2000/svg';
  const svgEl = (tag, attrs) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v); return n; };
  function chart(item, big) {
    const vals = (item.values || []).map(Number), labels = item.labels || [], max = Math.max(1, ...vals), W = 120, H = big ? 60 : 44;
    const s = svgEl('svg', {viewBox: `0 0 ${W} ${H + (big ? 8 : 0)}`, class: 'result-chart', role: 'img', 'aria-label': (item.name || 'Chart') + ': ' + vals.length + ' values, highest ' + max});
    s.append(svgEl('path', {class: 'result-axis', d: `M2 ${H}H${W - 2}`}));
    const step = (W - 8) / Math.max(1, vals.length), bw = Math.max(2, step * 0.62);
    if (item.kind === 'line') {
      const pts = vals.map((v, i) => `${(4 + step * i + step / 2).toFixed(1)},${(H - 2 - (H - 6) * v / max).toFixed(1)}`).join(' ');
      s.append(svgEl('polyline', {class: 'result-line', points: pts}));
    } else vals.forEach((v, i) => s.append(svgEl('rect', {class: 'result-bar', x: (4 + step * i + (step - bw) / 2).toFixed(1), y: (H - (H - 4) * v / max).toFixed(1), width: bw.toFixed(1), height: ((H - 4) * v / max).toFixed(1), rx: 1})));
    if (big) labels.forEach((l, i) => { const t = svgEl('text', {class: 'result-tick', x: (4 + step * i + step / 2).toFixed(1), y: H + 6, 'text-anchor': 'middle'}); t.textContent = l; s.append(t); });
    return s;
  }
  function wave(seed) {
    const s = svgEl('svg', {viewBox: '0 0 120 24', class: 'result-wave', 'aria-hidden': 'true', preserveAspectRatio: 'none'});
    let d = '', x = 3, r = seed || 7;
    while (x < 118) { r = (r * 9301 + 49297) % 233280; const h = 3 + (r / 233280) * 18; d += `M${x} ${(12 - h / 2).toFixed(1)}v${h.toFixed(1)}`; x += 4; }
    s.append(svgEl('path', {d})); return s;
  }
  function pageGlyph(pages) {
    const s = svgEl('svg', {viewBox: '0 0 120 72', class: 'result-glyph', 'aria-hidden': 'true', preserveAspectRatio: 'xMidYMin slice'});
    s.append(svgEl('rect', {class: 'g-paper', x: 34, y: 6, width: 52, height: 66, rx: 1}), svgEl('rect', {class: 'g-head', x: 40, y: 13, width: 26, height: 4}));
    [23, 29, 35, 45, 51, 57].forEach((y, i) => s.append(svgEl('rect', {class: 'g-line', x: 40, y, width: [40, 36, 40, 24, 40, 32][i], height: 2})));
    if (pages > 1) s.append(svgEl('rect', {class: 'g-under', x: 38, y: 3, width: 52, height: 3}));
    return s;
  }

  // ---- body of one kind, by size: 'sm' (a glance), 'lg' (on a ticket page), 'xl' (the overlay)
  function body(item, type, size, state) {
    const big = size !== 'sm', xl = size === 'xl', large = state === 'large', name = item.name || BY[type].word;
    const keep = n => large ? (item.shown || n) : n;
    const cap = arr => large && item.shown ? arr.slice(0, item.shown) : arr;
    switch (type) {
      case 'md': return markdown(item.text, xl ? keep(0) : big ? keep(40) : 3);
      case 'text': {
        const all = lines(item.text);
        if (!big) return code(item.text, {from: Math.max(0, all.length - 4), numbers: false});
        return code(item.text, {wrap: true, numbers: xl, max: xl ? keep(0) : keep(400)});
      }
      case 'code': return code(item.text, {highlight: true, max: xl ? keep(0) : big ? keep(200) : 5});
      case 'data': {
        const v = parseData(item.text);
        if (!v) return code(item.text, {highlight: true, max: big ? keep(0) : 5});
        if (!big) { const box = el('div', 'result-tree flat'); (Array.isArray(v) ? v.map((x, i) => [i, x]) : Object.entries(v)).slice(0, 4).forEach(([k, x]) => { const p = el('p'); p.append(el('span', 'result-key', k), el('i', '', x && typeof x === 'object' ? gist(x) : JSON.stringify(x))); box.append(p); }); return box; }
        const part = large && item.shown ? (Array.isArray(v) ? cap(v) : Object.fromEntries(cap(Object.entries(v)))) : v;
        const box = el('div', 'stack'); box.append(tree(part, 0, xl ? 2 : 1));
        if (xl) { const d = el('details', 'result-source'); d.append(el('summary', '', 'Show source'), code(item.text, {highlight: true})); box.append(d); }
        return box;
      }
      case 'table': {
        const all = parseRows(item), rows = large && item.shown ? all.slice(0, item.shown + 1) : all, cols = (rows[0] || []).length, n = Math.max(0, rows.length - 1);
        const box = el('div', 'result-tablebox');
        const total = Math.max(0, all.length - 1), max = big ? (xl ? 0 : 50) : 2, seen = max ? Math.min(n, max) : n;
        box.append(table(rows, name, {max, num: item.numeric}));
        if (big) box.append(el('p', 'meta', (seen < total ? seen + ' of ' : '') + plural(total, 'row') + ' · ' + plural(cols, 'column')));
        return box;
      }
      case 'page': {
        const f = el('iframe', 'result-frame'); f.setAttribute('sandbox', ''); f.setAttribute('referrerpolicy', 'no-referrer'); f.loading = 'lazy'; f.title = name;
        if (safeHref(item.src)) f.src = safeHref(item.src); else f.srcdoc = String(item.html || '');
        if (!xl) { f.tabIndex = -1; f.setAttribute('aria-hidden', 'true'); }
        return f;
      }
      case 'pdf': {
        if (xl && safeHref(item.src)) { const o = el('object', 'result-frame'); o.type = 'application/pdf'; o.data = safeHref(item.src); o.setAttribute('aria-label', name); o.append(el('p', 'meta', 'This browser cannot show PDFs here. Use Download.')); return o; }
        const box = el('div', 'result-pic');
        if (item.thumb) { const im = el('img'); im.src = item.thumb; im.alt = 'First page of ' + name; im.loading = 'lazy'; box.append(im); } else box.append(pageGlyph(item.pages));
        if (item.pages) box.append(el('span', 'result-badge', plural(item.pages, 'page')));
        return box;
      }
      case 'picture': {
        const box = el('div', 'result-pic' + (xl ? ' fit' : '')), im = el('img');
        im.src = item.src || item.thumb; im.alt = item.alt || name; im.loading = 'lazy'; box.append(im);
        if (xl) {
          const t = button('Full size', 'outline sm', () => { const on = box.classList.toggle('full'); t.querySelector('span').textContent = on ? 'Fit to window' : 'Full size'; t.setAttribute('aria-pressed', String(on)); }, {'aria-pressed': 'false'});
          const w = el('div', 'stack'); w.append(box, el('div', 'row', null)); w.lastChild.append(t, el('span', 'meta', item.width ? item.width + ' × ' + item.height : '')); return w;
        }
        return box;
      }
      case 'video': {
        if (big && !large) { const v = el('video', 'result-media'); v.controls = true; v.preload = 'metadata'; if (item.poster) v.poster = item.poster; v.src = item.src; v.setAttribute('aria-label', name); return v; }
        const box = el('div', 'result-pic still');
        if (item.poster) { const im = el('img'); im.src = item.poster; im.alt = ''; box.append(im); }
        box.append(el('span', 'result-play')); box.lastChild.append(ic('play', 20));
        if (item.duration) box.append(el('span', 'result-badge', item.duration));
        return box;
      }
      case 'audio': {
        const box = el('div', 'stack result-audio');
        box.append(wave(name.length * 13));
        if (big && !large) { const a = el('audio', 'result-media'); a.controls = true; a.preload = 'metadata'; a.src = item.src; a.setAttribute('aria-label', name); box.append(a); }
        else if (item.duration) box.append(el('span', 'meta', item.duration));
        if (big && item.transcript) { const t = el('div', 'result-md'); t.append(el('h4', '', 'The words'), el('p', '', item.transcript)); box.append(t); }
        return box;
      }
      case 'chart': {
        const part = large && item.shown ? Object.assign({}, item, {labels: cap(item.labels || []), values: cap(item.values || [])}) : item;
        const box = el('div', 'stack'); box.append(chart(part, big));
        if (big) box.append(table([[item.labelName || 'Label', item.unit || 'Value']].concat((part.labels || []).map((l, i) => [l, String(part.values[i])])), name, {num: [1]}));
        return box;
      }
      case 'change': {
        const files = item.files || [], add = files.reduce((a, f) => a + (+f[1] || 0), 0), del = files.reduce((a, f) => a + (+f[2] || 0), 0);
        const facts = [['Files', plural(files.length, 'file') + ' changed'], ['Lines', '+' + add + ' added, −' + del + ' removed']];
        if (item.checks) facts.push(['Checks', item.checks]);
        if (!big) return kv(facts);
        const box = el('div', 'stack'); box.append(kv(facts), table([['File', 'Added', 'Removed']].concat(cap(files).map(f => [f[0], '+' + f[1], '−' + f[2]])), 'Files changed', {num: [1, 2]}));
        if (item.diff && !large) {
          const pre = el('pre', 'result-code result-diff');
          lines(item.diff).forEach(l => pre.append(el('span', 'result-ln' + (l[0] === '+' ? ' add' : l[0] === '-' ? ' del' : l[0] === '@' ? ' hunk' : ''), l)));
          box.append(pre);
        }
        return box;
      }
      case 'pr': {
        const checks = item.checks || [], green = checks.filter(c => c.state === 'pass').length;
        // ORCH-2347: the card says the reference's live state word (the one References shows), so a pull request never
        // reads "Open · No checks yet" here and "Conflict" there. A conflict gets no checks: the line says why.
        const st = /^[a-z][a-z ]{0,39}$/.test(item.status || '') ? item.status : 'open';
        const tone = {draft: 'draft', merged: 'merged', 'ready to merge': 'merged', closed: 'closed', 'checks failed': 'closed', conflict: 'warn'}[st] || 'open';
        const pill = el('span', 'pill result-state ' + tone, st.charAt(0).toUpperCase() + st.slice(1));
        const facts = el('div', 'stack');
        const line = checks.length ? green + ' of ' + plural(checks.length, 'check') + ' green'
          : st === 'conflict' ? 'Checks start after ' + (item.base || 'the base branch') + ' is merged in' : st === 'open' || st === 'draft' ? 'No checks yet' : '';
        const top = el('div', 'row'); top.append(pill); if (line) top.append(el('span', 'meta', line)); facts.append(top);
        if (item.title) facts.append(el('p', 'result-prtitle', item.title));
        if (big && checks.length) {
          const ul = el('ul', 'result-checks');
          cap(checks).forEach(c => { const li = el('li', 'row'); li.append(UI.statusIcon ? UI.statusIcon(c.state === 'pass' ? 'done' : c.state === 'fail' ? 'needs' : 'working') : el('span'), el('span', '', c.name), el('span', 'meta', c.state === 'pass' ? 'Green' : c.state === 'fail' ? 'Failed' : 'Running')); ul.append(li); });
          facts.append(ul);
        }
        return facts;
      }
      case 'archive': {
        const files = item.files || [], total = item.total || files.length;
        if (!big) { const box = kv(files.slice(0, 2).map(f => [f[0], f[1]])); if (total > 2) box.append(el('dt', '', 'and ' + (total - 2) + ' more'), el('dd', '', '')); return box; }
        const shown = cap(files), box = el('div', 'stack'); box.append(table([['File', 'Size']].concat(shown), name, {num: [1]}));
        box.append(el('p', 'meta', (shown.length < total ? shown.length + ' of ' : '') + plural(total, 'file'))); return box;
      }
      default: {
        const box = el('div', 'result-unknown');
        box.append(el('p', '', big ? 'This kind of file cannot be shown here. Download it and open it on your computer.' : (item.size ? sizeText(item.size) : 'No preview')));
        if (xl && item.download) { const b = linkBtn('Download', item.download, 'outline sm', 'download', true); if (b) box.append(b); }
        return box;
      }
    }
  }

  function stateBody(item, type, size, state, o) {
    const box = el('div', 'result-state-box ' + state);
    if (state === 'loading') {
      box.setAttribute('aria-busy', 'true'); box.append(el('span', 'sr-only', 'Loading ' + (item.name || '')));
      const shape = MEDIA.has(type) || type === 'chart' ? ['block'] : type === 'table' ? ['line', 'line', 'line short'] : ['line', 'line', 'line short'];
      shape.forEach(c => { const s = el('span', 'skeleton ' + c); s.setAttribute('aria-hidden', 'true'); box.append(s); });
      return box;
    }
    if (state === 'empty') { box.append(el('p', 'meta', EMPTY[type])); return box; }
    if (state === 'error') {
      box.setAttribute('role', 'alert');
      box.append(el('p', '', type === 'pr' ? 'Its state could not be loaded.' : type === 'link' ? 'This link could not be checked.' : 'Can’t preview this file.'));
      if (size !== 'sm') {
        const row = el('div', 'row');
        if (o.onRetry) row.append(button('Try again', 'outline sm', () => o.onRetry(item), {icon: 'refresh'}));
        { const b = item.download && size === 'lg' && linkBtn('Download', item.download, 'ghost sm', 'download', true); if (b) row.append(b); }
        if (row.childNodes.length) box.append(row);
      }
      return box;
    }
    return box;
  }

  function largeNote(item, type, size) {
    const media = MEDIA.has(type) && type !== 'pdf';
    const p = el('p', 'result-note');
    p.textContent = media ? 'Too big to show here.' : size === 'sm' ? 'Too big to show in full.' : 'Too big to show in full. The first part is shown; download it for the rest.';
    if (size === 'lg' && safeHref(item.download)) { p.append(' '); const a = el('a', '', 'Download'); a.href = safeHref(item.download); a.setAttribute('download', ''); p.append(a); }
    return p;
  }

  function content(item, type, size, state, o) {
    if (state === 'ready') return body(item, type, size, state);
    if (state === 'large') {
      const box = el('div', 'stack result-large');
      box.append(largeNote(item, type, size));
      const partial = !MEDIA.has(type) || type === 'pdf' || type === 'video' || type === 'audio';
      if (partial && filled(item, type)) box.append(body(item, type, size, state));
      return box;
    }
    return stateBody(item, type, size, state, o);
  }

  function linkWidget(item, size, state) {
    const href = safeHref(item.href), live = state === 'ready' && !!href;
    const a = el(live ? 'a' : 'div', 'result-link');
    a.dataset.size = size; a.dataset.type = 'link'; a.dataset.state = state;
    if (live) { a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    a.append(ic('link', 16));
    const text = el('span', 'result-linktext');
    text.append(el('span', 'result-name', item.name || hostOf(item.href)));
    const line = live ? (item.meta || hostOf(item.href)) + ' · opens in a new tab' : state === 'loading' ? 'Checking the address…' : state === 'error' ? 'This link could not be checked.' : EMPTY.link;
    text.append(el('span', 'meta', line)); a.append(text);
    if (state === 'loading') a.setAttribute('aria-busy', 'true');
    if (live) a.append(ic('external', 16));
    return a;
  }

  function result(item, o) {
    item = item || {}; o = o || {};
    const type = BY[item.type] ? item.type : kindOf(item.name || item.href), size = o.size === 'lg' ? 'lg' : 'sm', state = stateOf(item, o, type);
    if (type === 'link') return linkWidget(item, size, state === 'large' ? 'ready' : state);
    const card = el('article', 'result card');
    card.dataset.type = type; card.dataset.size = size; card.dataset.state = state;
    const head = el('header', 'result-head');
    head.append(ic(BY[type].icon, size === 'sm' ? 14 : 16));
    const name = el(size === 'sm' ? 'span' : 'h3', 'result-name', item.name || BY[type].word); head.append(name);
    const open = () => o.onOpen ? o.onOpen(item) : UI.resultOverlay(o.list || [item], o.list ? (o.index || 0) : 0, o);
    const canOpen = state !== 'loading' && !(state === 'empty' && size === 'sm');
    if (size === 'lg') {
      head.append(el('span', 'grow'));
      { const b = item.download && linkBtn('', item.download, 'ghost icon sm', 'download', true); if (b) { b.setAttribute('aria-label', 'Download ' + (item.name || '')); head.append(b); } }
      if (canOpen) head.append(button('', 'ghost icon sm', open, {icon: 'expand', 'aria-label': 'Open a big preview of ' + (item.name || BY[type].word), title: 'Open big'}));
    }
    const main = el('div', 'result-body'); main.append(content(item, type, size, state, o));
    if (size === 'sm') { main.setAttribute('aria-hidden', 'true'); main.inert = true; }
    const foot = el('p', 'result-meta meta', metaOf(item, type));
    card.append(head, main, foot);
    if (size === 'sm' && canOpen) {
      const b = el('button', 'result-open'); b.type = 'button';
      b.setAttribute('aria-label', 'Open a big preview of ' + (item.name || BY[type].word) + ', ' + metaOf(item, type));
      b.addEventListener('click', open); card.append(b);
    }
    return card;
  }

  // ---- the big overlay: one at a time, ← → through the list, × Close / Esc close it
  function resultOverlay(list, index, o) {
    o = o || {};
    const items = (list || []).filter(x => (BY[x.type] ? x.type : kindOf(x.name || x.href)) !== 'link');
    if (!items.length) return null;
    const startItem = list[index]; let i = Math.max(0, items.indexOf(startItem));
    const d = el('dialog', 'dialog result-overlay');
    const head = el('header', 'result-ov-head'), icon = el('span', 'result-ov-icon'), title = el('h2', 'result-ov-title'), meta = el('span', 'meta');
    const pos = el('span', 'meta result-ov-pos'); pos.setAttribute('aria-live', 'polite');
    const prev = button('', 'ghost icon sm', () => go(-1), {icon: 'chevron-right', 'aria-label': 'Previous result', class: 'btn ghost icon sm result-prev'});
    const next = button('', 'ghost icon sm', () => go(1), {icon: 'chevron-right', 'aria-label': 'Next result'});
    const acts = el('span', 'row result-ov-acts');
    const words = el('div', 'result-ov-words'); words.append(title, meta);
    head.append(icon, words, el('span', 'grow'), pos, prev, next, acts);
    const main = el('div', 'result-ov-body');
    d.append(head, main);
    function show(moved) {
      const item = items[i], type = BY[item.type] ? item.type : kindOf(item.name), state = stateOf(item, {}, type);
      icon.replaceChildren(ic(BY[type].icon, 18)); title.textContent = item.name || BY[type].word; meta.textContent = metaOf(item, type);
      d.setAttribute('aria-label', 'Big preview of ' + title.textContent);
      const many = items.length > 1; pos.textContent = many ? (i + 1) + ' of ' + items.length : ''; prev.hidden = next.hidden = !many;
      acts.replaceChildren();
      { const b = item.href && state !== 'loading' && linkBtn('Open in new tab', item.href, 'ghost sm', 'external'); if (b) acts.append(b); }
      { const b = item.download && state !== 'loading' && linkBtn('Download', item.download, 'ghost sm', 'download', true); if (b) acts.append(b); }
      main.dataset.type = type; main.dataset.state = state;
      main.replaceChildren(content(item, type, 'xl', state, o));
      if (moved) { main.classList.remove('moved'); void main.offsetWidth; main.classList.add('moved'); }
    }
    function go(step) { i = (i + step + items.length) % items.length; show(true); }
    d.addEventListener('keydown', e => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
      const t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT|VIDEO|AUDIO)$/.test(t.tagName));
      if (typing || items.length < 2) return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); } else if (e.key === 'ArrowRight') { e.preventDefault(); go(1); }
    });
    d.addEventListener('close', () => d.remove(), {once: true});
    show(false);
    document.body.append(d); d.showModal(); d.querySelector('.ui-overlay-close')?.focus({preventScroll: true});
    return d;
  }

  result.TYPES = TYPES; result.kindOf = kindOf; result.LIMIT = LIMIT; result.parseRows = parseRows;
  result.gist = gist; result.safeHref = safeHref;
  UI.result = result; UI.resultOverlay = resultOverlay;
})();

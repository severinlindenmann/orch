/* The shared file viewer: one wide dialog for every kind of ticket file (picture, PDF, web page, table, spreadsheet,
   note, code, text or log, sound, video, archive). × Close, Esc and a click outside close it; ← → move between the
   files of the list; Open in new tab, Download and Copy link are always there. Text is only ever added with
   textContent, a web page only inside a sandboxed frame. */
(() => {
  'use strict';
  const EXT = {
    image: /^(png|jpe?g|gif|webp|svg)$/, pdf: /^pdf$/, page: /^html?$/, table: /^(csv|tsv)$/, xlsx: /^xlsx$/,
    md: /^(md|markdown)$/, code: /^(json|jsonl|py|js|ts|css|xml|ya?ml|toml|ini|sh|sql|cfg|conf)$/, text: /^(txt|log)$/,
    audio: /^(m4a|aac|mp3|wav|caf|ogg|oga)$/, video: /^(mp4|webm|mov|m4v|ogv)$/, zip: /^zip$/
  };
  const extOf = name => (/\.([^./]+)$/.exec(String(name || ''))?.[1] || '').toLowerCase();
  const kindOf = name => Object.keys(EXT).find(k => EXT[k].test(extOf(name))) || 'other';
  const WORD = {image:'Picture', pdf:'PDF', page:'Website', table:'Table', xlsx:'Spreadsheet', md:'Note', code:'Code', text:'Text',
    audio:'Sound', video:'Video', zip:'Archive', other:'File'};
  const urlOf = (f, dl) => '/api/file?t=' + encodeURIComponent(f.tid) + '&k=' + encodeURIComponent(f.kind) + '&n=' + encodeURIComponent(f.name) + (dl ? '&dl=1' : '');
  const pageUrl = f => '/view/' + encodeURIComponent(f.tid) + '/' + encodeURIComponent(f.kind) + '/' + f.name.split('/').map(encodeURIComponent).join('/');
  const infoUrl = (f, sheet = 0) => '/api/file-info?t=' + encodeURIComponent(f.tid) + '&k=' + encodeURIComponent(f.kind) + '&n=' + encodeURIComponent(f.name) + '&s=' + sheet;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const btn = (label, cls, click, attrs = {}) => {
    const b = el('button', 'btn ' + cls, label); b.type = 'button'; b.onclick = click;
    for (const [k, v] of Object.entries(attrs)) b.setAttribute(k, v);
    return b;
  };
  const sizeText = n => n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB';
  const num = n => Number(n).toLocaleString('en-US');

  // ---- text helpers
  async function fetchText(url) {
    const r = await fetch(url);
    if (r.status === 413) throw Object.assign(new Error('large'), {large:true});
    if (!r.ok) throw new Error('no');
    return r.text();
  }
  async function fetchJson(url) {
    const r = await fetch(url);
    if (r.status === 413) throw Object.assign(new Error('large'), {large:true});
    if (!r.ok) throw new Error('no');
    return r.json();
  }
  function highlight(text, lang) {
    // One pass over the line: comment, string, number, keyword. Returns spans (textContent only).
    const re = lang === 'py' || lang === 'sh' ? /(#.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b\d+(?:\.\d+)?\b)|(\b(?:def|class|import|from|return|if|elif|else|for|while|in|not|and|or|with|as|try|except|None|True|False|print)\b)/g
      : lang === 'json' ? /()("(?:[^"\\]|\\.)*"(?=\s*:)|"(?:[^"\\]|\\.)*")|(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(\b(?:true|false|null)\b)/g
      : /(\/\/.*$|\/\*.*?\*\/)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)|(\b\d+(?:\.\d+)?\b)|(\b(?:export|import|from|function|return|const|let|var|if|else|for|while|new|class|await|async|true|false|null|undefined)\b)/g;
    const out = document.createDocumentFragment();
    let last = 0, m;
    re.lastIndex = 0;
    while ((m = re.exec(text))) {
      if (m[0] === '') { re.lastIndex++; continue; }
      if (m.index > last) out.append(text.slice(last, m.index));
      const cls = m[1] ? 'tok-c' : m[2] ? (lang === 'json' && /:$/.test(text.slice(m.index + m[0].length).trimStart().slice(0, 1)) ? 'tok-k' : 'tok-s') : m[3] ? 'tok-n' : 'tok-w';
      out.append(el('span', cls, m[0]));
      last = m.index + m[0].length;
    }
    if (last < text.length) out.append(text.slice(last));
    return out;
  }

  // ---- renderers: each fills `stage` and may add facts to `facts` (a function that appends to the meta line)
  const R = {};
  R.image = (f, stage, ctx) => {
    const wrap = el('div', 'fv-image fit');
    const img = el('img'); img.alt = f.title; img.src = urlOf(f);
    img.onerror = () => fail(stage, f);
    wrap.append(img); stage.append(wrap);
    const bar = el('div', 'fv-bar');
    const fit = btn('Original size', 'outline sm', () => { const on = wrap.classList.toggle('fit'); fit.textContent = on ? 'Original size' : 'Fit to window'; });
    bar.append(fit);
    const pics = ctx.files.filter(x => kindOf(x.name) === 'image');
    if (pics.length > 1) {
      const strip = el('div', 'fv-strip');
      pics.slice(0, 8).forEach(p => {
        const b = el('button', 'fv-thumb' + (p === f ? ' on' : '')); b.type = 'button'; b.setAttribute('aria-label', p.title);
        if (p === f) b.setAttribute('aria-current', 'true');
        const t = el('img'); t.alt = ''; t.loading = 'lazy'; t.src = urlOf(p); b.append(t);
        b.onclick = () => ctx.go(ctx.files.indexOf(p));
        strip.append(b);
      });
      bar.append(strip);
    }
    stage.prepend(bar);
    img.onload = () => ctx.facts(img.naturalWidth + ' × ' + img.naturalHeight + ' px');
  };
  R.pdf = (f, stage, ctx) => {
    const fr = el('object', 'fv-frame'); fr.type = 'application/pdf'; fr.data = urlOf(f); fr.setAttribute('aria-label', f.title);
    const fb = el('div', 'fv-fallback');
    fb.append(el('p', 'fv-fb-title', 'This browser cannot show the PDF here.'), el('p', 'meta', 'Open it in a new tab or download it.'));
    const a = el('a', 'btn primary', 'Download'); a.href = urlOf(f, true); a.download = f.name.split('/').pop(); fb.append(a);
    fr.append(fb);
    stage.append(fr);
    fetchJson(infoUrl(f)).then(i => { if (i.pages) ctx.facts(i.pages + (i.pages === 1 ? ' page' : ' pages')); }).catch(() => {});
  };
  R.page = (f, stage) => {
    const fr = el('iframe', 'fv-frame fv-page'); fr.title = f.title;
    fr.setAttribute('sandbox', 'allow-scripts'); fr.setAttribute('referrerpolicy', 'no-referrer');
    fr.src = pageUrl(f);
    stage.append(fr);
  };
  function tableView(stage, data, f, note) {
    const wrap = el('div', 'fv-tablewrap');
    const bar = el('div', 'fv-tablebar');
    const count = el('strong', '', num(data.rowCount) + (data.rowCount === 1 ? ' row · ' : ' rows · ') + data.columns.length + (data.columns.length === 1 ? ' column' : ' columns'));
    const search = el('input', 'fv-search'); search.type = 'search'; search.placeholder = 'Search preview rows…'; search.setAttribute('aria-label', 'Search preview rows');
    bar.append(count, search);
    const scroller = el('div', 'fv-scroll'); scroller.tabIndex = 0; scroller.setAttribute('role', 'region'); scroller.setAttribute('aria-label', f.title + ' table');
    const table = el('table', 'fv-table'), thead = el('thead'), tbody = el('tbody');
    const hr = el('tr'); hr.append(el('th', 'fv-n', '#'));
    let sortCol = -1, sortDir = 1, rows = data.rows.map((r, i) => ({i: i + 1, r}));
    data.columns.forEach((c, ci) => {
      const th = el('th'); th.scope = 'col'; th.setAttribute('aria-sort', 'none');
      const b = el('button', 'fv-sort', c || 'Column ' + (ci + 1)); b.type = 'button';
      b.onclick = () => { sortDir = sortCol === ci ? -sortDir : 1; sortCol = ci; [...hr.children].forEach(x => x.setAttribute?.('aria-sort', 'none')); th.setAttribute('aria-sort', sortDir > 0 ? 'ascending' : 'descending'); draw(); };
      th.append(b); hr.append(th);
    });
    thead.append(hr); table.append(thead, tbody); scroller.append(table);
    const draw = () => {
      const q = search.value.trim().toLowerCase();
      let list = rows.filter(x => !q || x.r.some(c => String(c).toLowerCase().includes(q)));
      if (sortCol >= 0) list = list.slice().sort((a, b) => {
        const x = a.r[sortCol] ?? '', y = b.r[sortCol] ?? '', nx = parseFloat(x), ny = parseFloat(y);
        return (Number.isFinite(nx) && Number.isFinite(ny) && String(nx) === String(x).trim() && String(ny) === String(y).trim() ? nx - ny : String(x).localeCompare(String(y), undefined, {numeric:true})) * sortDir;
      });
      tbody.replaceChildren(...list.map(x => { const tr = el('tr'); tr.append(el('td', 'fv-n', String(x.i))); data.columns.forEach((_, ci) => tr.append(el('td', '', x.r[ci] ?? ''))); return tr; }));
    };
    search.oninput = draw; draw();
    wrap.append(bar, scroller);
    if (note) wrap.append(note);
    stage.append(wrap);
  }
  R.table = async (f, stage) => {
    const text = await fetchText(urlOf(f));
    const tsv = /\.tsv$/i.test(f.name);
    const {columns, rows} = parseDelimited(text, tsv ? '\t' : ',');
    const shown = rows.slice(0, 200);
    const note = el('p', 'fv-note meta');
    note.append(rows.length > 200 ? 'Showing the first 200 of ' + num(rows.length) + ' rows. Search and sort apply to these 200 rows. ' : 'Showing all ' + num(rows.length) + (rows.length === 1 ? ' row. ' : ' rows. '));
    const a = el('a', '', rows.length > 200 ? 'Download all ' + num(rows.length) + ' rows' : 'Download'); a.href = urlOf(f, true); a.download = f.name.split('/').pop();
    note.append(a, '.');
    tableView(stage, {columns, rows: shown, rowCount: rows.length}, f, note);
  };
  R.xlsx = async (f, stage, ctx) => {
    const first = await fetchJson(infoUrl(f, 0));
    const holder = el('div', 'fv-sheet');
    stage.append(holder);
    const show = data => {
      holder.replaceChildren();
      const tabs = el('div', 'fv-tabs'); tabs.setAttribute('role', 'tablist');
      data.sheets.forEach((n, i) => {
        const t = el('button', 'fv-tab', n); t.type = 'button'; t.setAttribute('role', 'tab'); t.setAttribute('aria-selected', String(i === data.sheet));
        t.onclick = async () => { try { show(await fetchJson(infoUrl(f, i))); } catch (_) { fail(holder, f); } };
        tabs.append(t);
      });
      const inner = el('div', 'fv-sheet-body');
      const note = el('p', 'fv-note meta', (data.sheets.length === 1 ? '1 sheet. ' : data.sheets.length + ' sheets. ') + (data.rowCount > 200 ? 'Showing the first 200 of ' + num(data.rowCount) + ' rows. ' : ''));
      const a = el('a', '', 'Download the workbook'); a.href = urlOf(f, true); a.download = f.name.split('/').pop(); note.append(a, '.');
      tableView(inner, {columns: data.columns, rows: data.rows.slice(0, 200), rowCount: data.rowCount}, f, note);
      holder.append(tabs, inner);
    };
    show(first);
    ctx.facts(first.sheets.length + (first.sheets.length === 1 ? ' sheet' : ' sheets'));
  };
  // Small, safe Markdown: headings, lists, tables, quotes, rules, code, **bold**, *italic*, `code`, ![alt](pic), [text](link) as text.
  function inlineMd(text, f) {
    const out = document.createDocumentFragment();
    const re = /!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.append(text.slice(last, m.index));
      if (m[2] !== undefined) {
        if (/^[A-Za-z0-9._ \/-]+$/.test(m[2]) && !/^\/|\.\./.test(m[2])) {
          const dir = f.name.includes('/') ? f.name.slice(0, f.name.lastIndexOf('/') + 1) : '';
          const img = el('img'); img.alt = m[1]; img.loading = 'lazy'; img.src = urlOf({...f, name: dir + m[2]}); out.append(img);
        } else out.append(m[1]);
      } else if (m[4] !== undefined) out.append(m[3]);
      else if (m[5] !== undefined) out.append(el('strong', '', m[5]));
      else if (m[6] !== undefined) out.append(el('em', '', m[6]));
      else out.append(el('code', '', m[7]));
      last = m.index + m[0].length;
    }
    if (last < text.length) out.append(text.slice(last));
    return out;
  }
  function renderMd(src, f) {
    const root = el('article', 'fv-md');
    const lines = src.replace(/\r\n?/g, '\n').split('\n');
    let i = 0;
    const cells = l => l.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
    while (i < lines.length) {
      const line = lines[i];
      let m;
      if (!line.trim()) { i++; continue; }
      if ((m = /^(#{1,4})\s+(.*)$/.exec(line))) { const hd = el('h' + (m[1].length + 1)); hd.append(inlineMd(m[2], f)); root.append(hd); i++; continue; }
      if (/^```/.test(line)) { const code = []; i++; while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]); i++; const pre = el('pre'); pre.append(el('code', '', code.join('\n'))); root.append(pre); continue; }
      if (/^\s*([-*])\s+/.test(line)) { const ul = el('ul'); while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { const li = el('li'); li.append(inlineMd(lines[i].replace(/^\s*[-*]\s+/, ''), f)); ul.append(li); i++; } root.append(ul); continue; }
      if (/^\s*\d+\.\s+/.test(line)) { const ol = el('ol'); while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { const li = el('li'); li.append(inlineMd(lines[i].replace(/^\s*\d+\.\s+/, ''), f)); ol.append(li); i++; } root.append(ol); continue; }
      if (/^>\s?/.test(line)) { const q = el('blockquote'); const t = []; while (i < lines.length && /^>\s?/.test(lines[i])) t.push(lines[i++].replace(/^>\s?/, '')); q.append(inlineMd(t.join(' '), f)); root.append(q); continue; }
      if (/^(-{3,}|\*{3,})\s*$/.test(line)) { root.append(el('hr')); i++; continue; }
      if (line.includes('|') && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1] || '')) {
        const head = cells(line); i += 2;
        const table = el('table'), thead = el('thead'), tbody = el('tbody'), hr = el('tr');
        head.forEach(c => { const th = el('th'); th.append(inlineMd(c, f)); hr.append(th); }); thead.append(hr);
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { const tr = el('tr'); cells(lines[i]).forEach(c => { const td = el('td'); td.append(inlineMd(c, f)); tr.append(td); }); tbody.append(tr); i++; }
        table.append(thead, tbody); root.append(table); continue;
      }
      const para = [];
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*[-*]\s|\s*\d+\.\s|>)/.test(lines[i])) para.push(lines[i++]);
      const p = el('p'); p.append(inlineMd(para.join(' '), f)); root.append(p);
    }
    return root;
  }
  R.md = async (f, stage) => {
    const src = await fetchText(urlOf(f));
    const bar = el('div', 'fv-bar'), body = el('div', 'fv-panel');
    let source = false;
    const toggle = btn('Source', 'outline sm', () => {
      source = !source; toggle.textContent = source ? 'Rendered' : 'Source';
      body.replaceChildren(source ? Object.assign(el('pre', 'fv-source'), {textContent: src}) : renderMd(src, f));
    });
    bar.append(toggle);
    body.append(renderMd(src, f));
    stage.append(bar, body);
  };
  function codeView(stage, text, f, lang) {
    const lines = text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n');
    const bar = el('div', 'fv-bar');
    const copy = btn('Copy code', 'outline sm', async () => { try { await navigator.clipboard.writeText(lines.join('\n')); window.orch.toast('Code copied', 'ok'); } catch (_) { window.orch.toast('Could not copy.', 'error'); } });
    bar.append(copy, el('span', 'meta', lines.length + (lines.length === 1 ? ' line' : ' lines')));
    const code = el('div', 'fv-code'); code.tabIndex = 0; code.setAttribute('role', 'region'); code.setAttribute('aria-label', f.title + ' source');
    const frag = document.createDocumentFragment();
    lines.slice(0, 5000).forEach((l, i) => {
      const row = el('div', 'fv-line'); row.append(el('span', 'fv-no', String(i + 1)));
      const t = el('span', 'fv-src'); t.append(highlight(l, lang)); if (!l) t.append(' '); row.append(t); frag.append(row);
    });
    code.append(frag);
    stage.append(bar, code);
  }
  R.code = async (f, stage, ctx) => {
    let text = await fetchText(urlOf(f)), lang = extOf(f.name);
    if (lang === 'json') { try { text = JSON.stringify(JSON.parse(text), null, 2); } catch (_) { /* shown as it is */ } }
    codeView(stage, text, f, ['json', 'jsonl'].includes(lang) ? 'json' : lang === 'py' ? 'py' : lang === 'sh' ? 'sh' : 'js');
  };
  R.text = async (f, stage) => {
    const text = (await fetchText(urlOf(f))).replace(/\r\n?/g, '\n');
    const bar = el('div', 'fv-bar');
    const search = el('input', 'fv-search'); search.type = 'search'; search.placeholder = 'Find in file…'; search.setAttribute('aria-label', 'Find in file');
    const found = el('span', 'meta fv-found'); found.setAttribute('aria-live', 'polite');
    const wrap = btn('Wrap lines', 'outline sm', () => { const on = pre.classList.toggle('wrap'); wrap.setAttribute('aria-pressed', String(on)); });
    wrap.setAttribute('aria-pressed', 'false');
    const pre = el('pre', 'fv-text'); pre.tabIndex = 0; pre.setAttribute('aria-label', f.title + ' text');
    const draw = () => {
      const q = search.value;
      pre.replaceChildren();
      if (!q) { pre.textContent = text; found.textContent = ''; return; }
      const low = text.toLowerCase(), needle = q.toLowerCase();
      let at = 0, n = 0, i;
      while ((i = low.indexOf(needle, at)) !== -1 && n < 5000) {
        pre.append(text.slice(at, i), el('mark', '', text.slice(i, i + q.length)));
        at = i + q.length; n++;
      }
      pre.append(text.slice(at));
      found.textContent = n ? n + (n === 1 ? ' match' : ' matches') : 'No matches';
    };
    search.oninput = draw; draw();
    bar.append(search, found, wrap);
    stage.append(bar, pre);
  };
  R.audio = (f, stage) => {
    const wrap = el('div', 'fv-media');
    const a = el('audio'); a.controls = true; a.preload = 'metadata'; a.src = urlOf(f);
    a.onerror = () => fail(stage, f);
    wrap.append(a); stage.append(wrap);
  };
  R.video = (f, stage) => {
    const wrap = el('div', 'fv-media');
    const v = el('video'); v.controls = true; v.preload = 'metadata'; v.playsInline = true; v.src = urlOf(f);
    v.onerror = () => fail(stage, f);
    wrap.append(v); stage.append(wrap);
  };
  R.zip = async (f, stage, ctx) => {
    const i = await fetchJson(infoUrl(f));
    const wrap = el('div', 'fv-panel');
    wrap.append(el('p', 'meta', i.count + (i.count === 1 ? ' file inside' : ' files inside')));
    const table = el('table', 'fv-list'), tb = el('tbody');
    i.entries.forEach(e => { const tr = el('tr'); tr.append(el('td', '', e.name), el('td', 'num', sizeText(e.size))); tb.append(tr); });
    table.append(tb); wrap.append(table);
    if (i.count > i.entries.length) wrap.append(el('p', 'meta', 'Showing the first ' + i.entries.length + ' files. Download the archive to see all of them.'));
    stage.append(wrap);
    ctx.facts(i.count + (i.count === 1 ? ' file inside' : ' files inside'));
  };
  function fail(stage, f, large, plain) {
    stage.replaceChildren();
    const box = el('div', 'fv-fallback');
    box.append(el('p', 'fv-fb-title', large ? 'This file is too large to show here.' : plain ? 'There is no preview for this kind of file.' : 'This file cannot be shown here.'),
      el('p', 'meta', 'Download it to open it on your computer.'));
    const a = el('a', 'btn primary', 'Download'); a.href = urlOf(f, true); a.download = f.name.split('/').pop();
    box.append(a); stage.append(box);
  }
  function parseDelimited(text, sep) {
    text = String(text || '').replace(/^﻿/, '');
    const records = []; let row = [], field = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') { if (q && text[i + 1] === '"') { field += '"'; i++; } else if (q || !field) q = !q; else field += c; }
      else if (!q && c === sep) { row.push(field); field = ''; }
      else if (!q && (c === '\n' || c === '\r')) { row.push(field); records.push(row); row = []; field = ''; if (c === '\r' && text[i + 1] === '\n') i++; }
      else field += c;
    }
    if (field || row.length) { row.push(field); records.push(row); }
    return {columns: records.shift() || [], rows: records};
  }

  // ---- the dialog
  let open = null;
  function show(opts) {
    if (open) open.close(false);
    const files = opts.files, trigger = document.activeElement;
    let index = Math.max(0, Math.min(opts.index || 0, files.length - 1)), token = 0, done = false;
    const d = el('dialog', 'fv'); d.setAttribute('aria-labelledby', 'fv-title');
    const head = el('header', 'fv-head'), titles = el('div', 'fv-titles');
    const eyebrow = el('p', 'fv-eyebrow'), title = el('h2'); title.id = 'fv-title';
    const meta = el('p', 'meta fv-meta');
    titles.append(eyebrow, title, meta);
    head.append(titles);
    const actions = el('div', 'fv-actions'), left = el('div', 'row fv-left'), right = el('div', 'row fv-right');
    const open1 = el('a', 'btn outline sm', 'Open in new tab ↗'); open1.target = '_blank'; open1.rel = 'noopener noreferrer';
    const dl = el('a', 'btn ghost sm', 'Download');
    const copy = btn('Copy link', 'ghost sm', async () => {
      try { await navigator.clipboard.writeText(new URL(urlOf(files[index]), location.href).href); window.orch.toast('Link copied', 'ok'); }
      catch (_) { window.orch.toast('Could not copy the link.', 'error'); }
    });
    left.append(open1, dl, copy);
    const prev = btn('← Prev', 'outline sm', () => go(index - 1)), next = btn('Next →', 'outline sm', () => go(index + 1));
    right.append(prev, next); actions.append(left, right);
    const stage = el('div', 'fv-stage'); stage.setAttribute('aria-live', 'polite');
    const foot = el('footer', 'fv-foot'); foot.append(el('span', '', '← → Browse files'), el('span', '', 'Esc Close'));
    d.append(head, actions, stage, foot);
    document.body.append(d);

    const go = i => { if (i >= 0 && i < files.length && i !== index) { index = i; draw(); } };
    // × Close, Esc, a click outside and the focus trap come from the shared overlay (kit/overlay.js).
    function close(restore = true) {
      if (done) return;
      if (!restore) finish(false); else window.orch.close(d);
    }
    function finish(restore) {
      if (done) return; done = true; open = null;
      token++;
      d.remove();
      if (restore && trigger && trigger.isConnected) trigger.focus({preventScroll: true});
      if (opts.onClose) opts.onClose();
    }
    d.addEventListener('close', () => finish(true));
    function draw() {
      const f = files[index], kind = kindOf(f.name), mine = ++token;
      d.dataset.kind = kind;
      eyebrow.textContent = [opts.context, files.length > 1 ? (index + 1) + ' of ' + files.length + (files.length === 1 ? ' file' : ' files') : ''].filter(Boolean).join('  /  ');
      title.textContent = f.title;
      const base = f.meta || WORD[kind];
      meta.textContent = base;
      open1.href = kind === 'page' ? pageUrl(f) : urlOf(f);
      dl.href = urlOf(f, true); dl.download = f.name.split('/').pop();
      prev.disabled = index === 0; next.disabled = index === files.length - 1;
      prev.hidden = next.hidden = files.length < 2;
      stage.replaceChildren(el('div', 'fv-skeleton'));
      const body = el('div', 'fv-body');
      const ctx = {files, go, facts: t => { if (mine === token && t) meta.textContent = base + ' · ' + t; }};
      const ready = () => { if (mine === token) stage.replaceChildren(body); };
      const render = R[kind];
      if (!render) { fail(body, f, f.size > 25 * 1048576, true); ready(); return; }
      Promise.resolve().then(() => render(f, body, ctx)).then(ready).catch(e => { if (mine !== token) return; const b = el('div', 'fv-body'); fail(b, f, e && e.large); stage.replaceChildren(b); });
    }
    d.addEventListener('keydown', e => {
      const t = e.target, typing = t && (t.matches?.('input,textarea,select,audio,video') || t.isContentEditable);
      if (!typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        if (e.key === 'ArrowLeft') { e.preventDefault(); go(index - 1); }
        if (e.key === 'ArrowRight') { e.preventDefault(); go(index + 1); }
      }
    });
    open = {close};
    window.orch.open(d);
    draw();
    (d.querySelector('.ui-overlay-close') || d).focus();
    return d;
  }
  window.FileViewer = {open: show, kindOf, word: k => WORD[k], urlOf, extOf, parseDelimited};
})();

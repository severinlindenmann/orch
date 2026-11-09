/* Focus proof: tiles for the Proof tab and a preview panel that opens one proof and shows it in full.
   Files are only ever asked from this page's own /api/file (read by orch.safefile on the server). Every text
   is set with textContent, never innerHTML. */
(function () {
  'use strict';
  const TEXT_EXT = new Set('txt md log'.split(' '));
  const CODE_EXT = new Set('json jsonl xml yml yaml toml ini svg py js mjs ts tsx jsx css sh sql rs go java c h cpp rb diff patch'.split(' '));
  const IMG_EXT = new Set('png jpg jpeg gif webp'.split(' '));
  const KINDS = {
    command: ['code', 'Command'], text: ['note', 'Note'], doc: ['text', 'Text'], link: ['link', 'Link'], commit: ['code', 'Commit'], image: ['image', 'Picture'],
    pdf: ['file', 'PDF'], table: ['table', 'Table'], code: ['code', 'Code'], page: ['page', 'Page'], other: ['file', 'File'], missing: ['file', 'File'],
  };
  const MAX_ROWS = 500;

  function create({h, ic, P, TID, toast}) {
    let agent = 'agent';
    let pageKey = '';  /* from the ticket view (page_key): without it a page URL is a 404 */
    const base = name => String(name || '').split('/').pop();
    const prefix = '.orch/tickets/' + TID + '/evidence/';
    const extOf = n => { const b = base(n), i = b.lastIndexOf('.'); return i > 0 ? b.slice(i + 1).toLowerCase() : ''; };

    /* the file name inside the evidence folder, or null when the proof is not a copied file of this ticket */
    function fileName(ev) {
      const ref = String(ev.ref || '');
      return ev.type === 'file' && ev.missing !== true && ref.startsWith(prefix) && ref.length > prefix.length ? ref.slice(prefix.length) : null;
    }
    function kindOf(ev) {
      if (ev.type === 'command') return 'command';
      if (ev.type === 'note') return 'text';
      if (ev.type === 'commit') return 'commit';
      if (ev.type === 'pr' || ev.type === 'url') return 'link';
      const name = fileName(ev);
      if (name === null) return 'missing';
      const e = extOf(name);
      if (IMG_EXT.has(e)) return 'image';
      if (e === 'pdf') return 'pdf';
      if (e === 'csv' || e === 'tsv') return 'table';
      if (e === 'html' || e === 'htm') return 'page';
      if (TEXT_EXT.has(e)) return 'doc';
      if (CODE_EXT.has(e)) return 'code';
      return 'other';
    }
    /* a page by path (not ?n=): its relative CSS, scripts and pictures then load from the same folder */
    const pageUrl = ev => P + '/page/' + encodeURIComponent(TID) + '/' + pageKey + '/' + fileName(ev).split('/').map(encodeURIComponent).join('/');
    const url = (ev, mode) => mode === 'page' ? pageUrl(ev) : P + '/api/file?t=' + encodeURIComponent(TID) + '&n=' + encodeURIComponent(fileName(ev)) + '&m=' + mode;

    function title(ev, kind) {
      if (ev.type === 'file') return window.FocusHelpers.plainFileName(ev.ref) || 'File';
      if (ev.title) return String(ev.title);
      if (kind === 'text') return String(ev.ref || ev.text || 'Note');
      if (ev.type === 'file') return base(ev.ref) || 'File';
      if (kind === 'link') { const l = linkInfo(ev); return l.label; }
      return String(ev.ref || 'Result');
    }
    /* a link card: only https links open; "PR #88" or a commit stays text */
    function linkInfo(ev) {
      const ref = String(ev.ref || '').trim();
      let u = null;
      try { u = new URL(ref); } catch (e) { u = null; }
      const ok = !!u && u.protocol === 'https:' && !!u.hostname;
      const pr = ok ? /\/pull\/(\d+)/.exec(u.pathname) : /^PR\s*#?(\d+)$/i.exec(ref) || /^#(\d+)$/.exec(ref);
      return {ok, href: ok ? u.href : '', host: ok ? u.hostname : '', label: ev.type === 'pr' && pr ? 'PR #' + pr[1] : ok ? u.hostname + (u.pathname === '/' ? '' : u.pathname) : ref};
    }
    const who = ev => String(ev.by || '').startsWith('human:') ? ['●', 'You'] : ['○', agent + ' says'];
    function when(at) {
      const d = new Date(at);
      return at && !isNaN(d) ? d.toLocaleString(undefined, {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false}) : '';
    }
    const sizeText = n => n < 1024 ? n + ' bytes' : n < 1048576 ? (n / 1024).toFixed(n < 10240 ? 1 : 0) + ' KB' : (n / 1048576).toFixed(1) + ' MB';

    /* ---- tiles: never mount a live page, PDF, SVG or GIF ---- */
    const previewCache = new Map(), previewQueue = [];
    let previewActive = 0;
    function queuePreview(ev, kind) {
      const address = url(ev, 'view');
      if (!previewCache.has(address)) {
        previewCache.set(address, new Promise(resolve => { previewQueue.push({ev, kind, resolve}); }));
        drainPreviews();
      }
      return previewCache.get(address);
    }
    function drainPreviews() {
      while (previewActive < 4 && previewQueue.length) {
        const job = previewQueue.shift(); previewActive++;
        readPreview(job.ev, job.kind).catch(() => null).then(job.resolve).finally(() => { previewActive--; drainPreviews(); });
      }
    }
    async function readPreview(ev, kind) {
      const response = await fetch(url(ev, 'view'));
      if (!response.ok) return null;
      const mime = (response.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
      if (kind === 'image') {
        // Only the existing proofs API's PNG/JPEG/WebP content types authorize images.
        if (!['image/png', 'image/jpeg', 'image/webp'].includes(mime)) { await response.body?.cancel(); return null; }
        return {blob: await response.blob()};
      }
      if (mime !== 'text/plain') { await response.body?.cancel(); return null; }
      const reader = response.body.getReader(), bytes = new Uint8Array(2048);
      let used = 0;
      try {
        while (used < bytes.length) {
          const {value, done} = await reader.read();
          if (done) break;
          const part = value.subarray(0, bytes.length - used); bytes.set(part, used); used += part.length;
        }
      } finally { await reader.cancel(); }
      return {text: new TextDecoder().decode(bytes.subarray(0, used)).split('\n').slice(0, 8).join('\n')};
    }
    function tile(item, onOpen) {
      const {c, ev} = item, kind = kindOf(ev), [icon, label] = KINDS[kind], [mark, markText] = who(ev);
      const extension = extOf(fileName(ev) || ''), badge = label;
      const head = h('span', {class: 'fx-pt-k'}, h('span', {icon}), h('span', {class: 'fx-pt-badge', text: badge}), h('span', {text: label}), h('time', {datetime: ev.at || '', text: when(ev.at)}));
      const thumb = h('span', {class: 'fx-pt-preview'}, h('span', {icon}), h('span', {text: kind === 'page' ? 'Open to see the page' : badge}));
      const btn = h('button', {type: 'button', class: 'fx-ptile fx-k-' + kind, title: c.text || '', 'aria-haspopup': 'dialog', onclick: () => onOpen(btn)},
        head, thumb, h('span', {class: 'fx-pt-t', text: title(ev, kind)}),
        window.FocusHelpers.cleanOutcome(ev.text) ? h('span', {class: 'fx-pt-m'}, h('span', {class: 'fx-pt-who ' + (mark === '●' ? 'you' : 'agent'), text: mark + ' ' + markText + ': ' + window.FocusHelpers.cleanOutcome(ev.text)})) : null);
      const excerpt = text => thumb.replaceChildren(h('pre', {text: String(text).slice(0, 2048).split('\n').slice(0, 8).join('\n')}));
      if (kind === 'text') excerpt(ev.text || ev.ref || '');
      const textFile = ['doc', 'code', 'table'].includes(kind) && extension !== 'svg';
      const picture = kind === 'image' && ['png', 'jpg', 'jpeg', 'webp'].includes(extension);
      if (textFile || picture) {
        const load = () => queuePreview(ev, picture ? 'image' : 'text').then(data => {
          if (!data) return;
          if (data.text !== undefined) excerpt(data.text);
          else if (data.blob) {
            const src = URL.createObjectURL(data.blob);
            const img = h('img', {class: 'fx-pt-img', alt: '', onload: () => URL.revokeObjectURL(src), onerror: () => URL.revokeObjectURL(src)});
            img.src = src; thumb.replaceChildren(img);
          }
        });
        if (typeof IntersectionObserver !== 'undefined') {
          const observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) { observer.disconnect(); load(); } });
          observer.observe(btn);
        } else load();
      }
      return btn;
    }

    /* ---- body renderers ---- */
    function parseDelimited(text, sep) {
      text = String(text).replace(/^﻿/, '');
      const rows = [];
      let row = [], f = '', q = false;
      for (let i = 0; i < text.length; i++) {
        const ch = text[i];
        if (ch === '"') { if (q && text[i + 1] === '"') { f += '"'; i++; } else if (q || !f) q = !q; else f += ch; }
        else if (!q && ch === sep) { row.push(f); f = ''; }
        else if (!q && (ch === '\n' || ch === '\r')) { row.push(f); rows.push(row); row = []; f = ''; if (ch === '\r' && text[i + 1] === '\n') i++; }
        else f += ch;
      }
      if (f || row.length) { row.push(f); rows.push(row); }
      return rows;
    }
    function tableEl(text, sep) {
      const rows = parseDelimited(text, sep);
      if (!rows.length) return h('p', {class: 'muted', text: 'This table is empty.'});
      const cols = rows[0], body = rows.slice(1);
      const t = h('table', {}, h('thead', {}, h('tr', {}, cols.map(x => h('th', {scope: 'col', text: x})))), h('tbody', {}, body.slice(0, MAX_ROWS).map(r => h('tr', {}, r.map(x => h('td', {text: x}))))));
      return h('div', {}, h('div', {class: 'fx-pv-table', tabindex: '0', role: 'region', 'aria-label': 'Table'}, t),
        body.length > MAX_ROWS ? h('p', {class: 'meta', text: 'Showing ' + MAX_ROWS + ' of ' + body.length + ' rows. Download the file to see all of them.'}) : null);
    }
    const TOK = /("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(\/\/[^\n]*|#[^\n]*)|(-?\b\d+(?:\.\d+)?\b)|\b(true|false|null|None|True|False|def|class|return|import|from|if|else|elif|for|while|const|let|var|function|async|await|try|except|catch|new|in|not|and|or)\b/g;
    function highlight(text, json) {
      const frag = document.createDocumentFragment();
      if (text.length > 200000) { frag.append(text); return frag; }
      let last = 0, m;
      TOK.lastIndex = 0;
      while ((m = TOK.exec(text))) {
        if (m.index > last) frag.append(text.slice(last, m.index));
        let cls = m[1] ? 'tok-s' : m[2] ? 'tok-c' : m[3] ? 'tok-n' : 'tok-k';
        if (m[1] && json && /^\s*:/.test(text.slice(TOK.lastIndex, TOK.lastIndex + 8))) cls = 'tok-key';
        frag.append(h('span', {class: cls, text: m[0]}));
        last = TOK.lastIndex;
      }
      if (last < text.length) frag.append(text.slice(last));
      return frag;
    }
    function codeEl(text, name) {
      const isJson = /^(json|jsonl)$/.test(extOf(name));
      if (extOf(name) === 'json') { try { text = JSON.stringify(JSON.parse(text), null, 2); } catch (e) { /* show it as it is */ } }
      return h('pre', {class: 'fx-pv-pre code', tabindex: '0'}, highlight(text, isJson));
    }
    function note(text, bad) { return h('p', {class: 'fx-pv-note' + (bad ? ' bad' : ''), role: bad ? 'alert' : null, text}); }

    /* ---- the panel ---- */
    let items = [], idx = 0, panel = null, opener = null, ctl = null, copyText = '';
    const pv = {};
    const isOpen = () => !!panel;

    function build() {
      pv.icon = h('span', {class: 'fx-pv-ic'});
      pv.title = h('h2', {class: 'fx-pv-title', id: 'fx-pv-title'});
      pv.meta = h('p', {class: 'fx-pv-meta'});
      pv.count = h('span', {class: 'fx-pv-count meta', 'aria-live': 'polite'});
      pv.prev = h('button', {type: 'button', class: 'btn ghost icon sm fx-pv-prev', 'aria-label': 'Previous result', title: 'Previous (←)', onclick: () => step(-1)}, h('span', {icon: 'up'}));
      pv.next = h('button', {type: 'button', class: 'btn ghost icon sm fx-pv-next', 'aria-label': 'Next result', title: 'Next (→)', onclick: () => step(1)}, h('span', {icon: 'down'}));
      pv.copy = h('button', {type: 'button', class: 'btn ghost sm', onclick: copy}, h('span', {icon: 'text'}), h('span', {class: 'opt', text: 'Copy'}));
      pv.open = h('a', {class: 'btn ghost sm', target: '_blank', rel: 'noopener noreferrer'}, h('span', {icon: 'external'}), h('span', {class: 'opt', text: 'Open'}));
      pv.dl = h('a', {class: 'btn ghost sm'}, h('span', {icon: 'download'}), h('span', {class: 'opt', text: 'Download'}));
      pv.close = h('button', {type: 'button', class: 'btn ghost icon sm', 'aria-label': 'Close', title: 'Close (Esc)', onclick: close}, h('span', {icon: 'x'}));
      pv.body = h('div', {class: 'fx-pv-body', tabindex: '0'});
      const head = h('header', {class: 'fx-pv-h'}, pv.icon, h('div', {class: 'fx-pv-hd'}, pv.title, pv.meta), h('div', {class: 'fx-pv-tools'}, pv.prev, pv.count, pv.next, pv.copy, pv.open, pv.dl, pv.close));
      panel = h('div', {class: 'fx-pv', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'fx-pv-title'},
        h('div', {class: 'fx-pv-scrim', onclick: close}), h('div', {class: 'fx-pv-card'}, head, pv.body));
    }

    function open(list, i, from) {
      items = list; idx = i; opener = from || null;
      if (!panel) { build(); document.getElementById('fx').append(panel); document.addEventListener('keydown', onKey, true); }
      show();
      pv.close.focus();
    }
    function close() {
      if (!panel) return;
      if (ctl) ctl.abort();
      document.removeEventListener('keydown', onKey, true);
      panel.remove(); panel = null; ctl = null;
      if (opener && opener.isConnected) opener.focus();
      opener = null;
    }
    function step(d) {
      if (items.length < 2) return;
      idx = (idx + d + items.length) % items.length;
      show();
    }
    function onKey(e) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); close(); return; }
      if (e.target.closest && e.target.closest('input,textarea,select')) return;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); e.stopImmediatePropagation(); step(e.key === 'ArrowLeft' ? -1 : 1); return; }
      if (e.key === 'Tab') {  // keep the focus inside the panel
        const f = [...panel.querySelectorAll('button,a[href],[tabindex="0"],iframe')].filter(x => !x.hidden && x.offsetParent !== null);
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
        return;
      }
      if (e.key.length === 1 || e.key === 'Enter' || e.key === ' ') e.stopPropagation();  // the page's own shortcuts stay quiet
    }
    function setCopy(t) { copyText = t; pv.copy.hidden = !t; }
    function copy() {
      if (!copyText) return;
      const done = () => toast('Copied.', 'ok');
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(copyText).then(done, () => fallbackCopy(done));
      else fallbackCopy(done);
    }
    function fallbackCopy(done) {
      const ta = h('textarea', {style: 'position:fixed;opacity:0;left:-1000px', 'aria-hidden': 'true'});
      ta.value = copyText; panel.append(ta); ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { toast('Could not copy.', 'error'); }
      ta.remove();
    }

    function show() {
      const {c, ev} = items[idx], kind = kindOf(ev), [icon, label] = KINDS[kind], [mark, markText] = who(ev), name = fileName(ev);
      if (ctl) ctl.abort();
      ctl = new AbortController();
      pv.icon.replaceChildren(h('span', {icon}));
      pv.title.textContent = title(ev, kind);
      pv.meta.textContent = '';
      if (window.FocusHelpers.cleanOutcome(ev.text)) pv.meta.append(h('span', {class: 'fx-pt-who ' + (mark === '●' ? 'you' : 'agent'), text: mark + ' ' + markText}), ' · ');
      pv.meta.append(label + (when(ev.at) ? ' · ' + when(ev.at) : '') + (c.text ? ' · ' + c.text : ''));
      pv.count.textContent = items.length > 1 ? (idx + 1) + ' of ' + items.length : '';
      pv.prev.hidden = pv.next.hidden = items.length < 2;
      pv.dl.hidden = name === null;
      if (name !== null) { pv.dl.href = url(ev, 'dl'); pv.dl.setAttribute('download', base(name)); }
      const viewable = name !== null && ['image', 'pdf', 'table', 'code', 'doc', 'page'].includes(kind);
      const link = kind === 'link' ? linkInfo(ev) : null;
      pv.open.hidden = !(viewable || (link && link.ok));
      if (link && link.ok) pv.open.href = link.href;
      else if (viewable) pv.open.href = url(ev, kind === 'page' ? 'page' : 'view');
      copyText = kind === 'command' ? '$ ' + ev.ref + (ev.text ? '\n' + ev.text : '') : kind === 'link' || kind === 'commit' ? String(ev.ref || '') : kind === 'text' && name === null ? String(ev.ref || ev.text || '') : '';
      pv.copy.hidden = !copyText;
      pv.body.scrollTop = 0;
      pv.body.className = 'fx-pv-body fx-pvk-' + kind;
      pv.body.replaceChildren(h('p', {class: 'meta', text: 'Loading…'}));
      render(ev, kind, name, ctl.signal);
    }

    async function fetchText(ev, signal) {
      let r;
      try { r = await fetch(url(ev, 'view'), {signal}); } catch (e) { if (e.name === 'AbortError') return null; return {error: 'Could not reach Focus.'}; }
      if (signal.aborted) return null;
      if (r.status === 413) return {error: 'This file is too large to show here (over 2 MB). Download it instead.', big: true};
      if (!r.ok) return {error: r.status === 404 ? 'This file can no longer be shown. It may have been moved or changed.' : (await r.text()).slice(0, 200)};
      return {text: await r.text()};
    }
    const put = (el, signal) => { if (!signal.aborted) pv.body.replaceChildren(el); };

    async function render(ev, kind, name, signal) {
      if (kind === 'command') {
        return put(h('div', {class: 'fx-pv-stack'}, h('pre', {class: 'fx-pv-pre cmd', tabindex: '0'}, h('span', {class: 'prompt', text: '$ '}), String(ev.ref || '')),
          ev.text ? h('div', {}, h('p', {class: 'fx-pv-cap', text: 'Result'}), h('pre', {class: 'fx-pv-pre', tabindex: '0', text: String(ev.text)})) : h('p', {class: 'meta', text: 'No output was saved with this command.'})), signal);
      }
      if (kind === 'commit') return put(h('div', {class: 'fx-pv-stack'}, h('pre', {class: 'fx-pv-pre cmd', tabindex: '0', text: String(ev.ref || '')}), ev.text ? note(String(ev.text)) : null), signal);
      if (kind === 'link') {
        const l = linkInfo(ev);
        return put(h('div', {class: 'fx-pv-link'},
          h('p', {class: 'fx-pv-host', text: l.ok ? l.host : 'Not a web link'}), h('p', {class: 'mono fx-pv-url', text: String(ev.ref || '')}),
          ev.text ? note(String(ev.text)) : null,
          l.ok ? h('a', {class: 'btn primary', href: l.href, target: '_blank', rel: 'noopener noreferrer'}, h('span', {icon: 'external'}), h('span', {text: 'Open in a new tab'}))
            : h('p', {class: 'meta', text: 'Only https links open from here.'})), signal);
      }
      if (kind === 'text' && name === null) return put(h('p', {class: 'fx-pv-text', text: String(ev.ref || ev.text || '')}), signal);
      if (kind === 'missing') return put(fileCard(ev, null, 'This file is on another computer or no longer there, so it can’t be shown here.', signal), signal);
      if (kind === 'image') {
        const img = h('img', {class: 'fx-pv-img', alt: title(ev, kind), src: url(ev, 'view')});
        img.addEventListener('error', () => put(note('This picture can’t be shown. Download it instead.', true), signal), {once: true});
        return put(img, signal);
      }
      if (kind === 'pdf') return put(h('iframe', {class: 'fx-pv-pdf', src: url(ev, 'view'), title: title(ev, kind), referrerpolicy: 'no-referrer'}), signal);
      if (kind === 'other') return put(fileCard(ev, name, '', signal), signal);
      if (kind === 'page') {
        const src = await fetchText(ev, signal);
        if (!src) return;
        if (src.error) return put(fileCard(ev, name, src.error, signal), signal);
        setCopy(src.text);
        const area = h('div', {class: 'fx-pv-pagearea'});
        const showSource = () => area.replaceChildren(h('pre', {class: 'fx-pv-pre code', tabindex: '0'}, highlight(src.text, false)));
        const showPage = () => area.replaceChildren(h('p', {class: 'fx-pv-cap', text: 'Agent preview. Scripts in this page run in a closed box, apart from Focus. Don’t type secrets into this preview.'}),
          h('iframe', {class: 'fx-pv-frame', sandbox: 'allow-scripts', referrerpolicy: 'no-referrer', src: url(ev, 'page'), title: title(ev, kind)}));
        const seg = [['Page', showPage], ['Code', showSource]].map(([t, fn], n) => {
          const b = h('button', {type: 'button', class: 'btn sm ' + (n ? 'ghost' : ''), 'aria-pressed': String(!n), text: t, onclick: () => { seg.forEach(x => { x.classList.toggle('ghost', x !== b); x.setAttribute('aria-pressed', String(x === b)); }); fn(); }});
          return b;
        });
        showPage();
        return put(h('div', {class: 'fx-pv-stack'}, h('div', {class: 'fx-pv-seg', role: 'group', 'aria-label': 'Show the page as'}, seg), area), signal);
      }
      const src = await fetchText(ev, signal);
      if (!src) return;
      if (src.error) return put(fileCard(ev, name, src.error, signal), signal);
      setCopy(src.text);
      if (kind === 'table') return put(tableEl(src.text, extOf(name) === 'tsv' ? '\t' : ','), signal);
      if (kind === 'code') return put(codeEl(src.text, name), signal);
      return put(h('pre', {class: 'fx-pv-pre wrap', tabindex: '0', text: src.text}), signal);
    }

    /* name, size, time and Download (also when a preview is not possible) */
    function fileCard(ev, name, why, signal) {
      const sizeEl = h('dd', {text: '…'});
      const card = h('div', {class: 'fx-pv-file'}, why ? note(why, false) : null,
        h('details', {}, h('summary', {text: 'Details'}), h('dl', {class: 'fx-pv-dl'}, h('dt', {text: 'Name'}), h('dd', {text: base(name || ev.ref) || 'File'}), h('dt', {text: 'Size'}), sizeEl, h('dt', {text: 'Saved'}), h('dd', {text: when(ev.at) || 'unknown'}))),
        name !== null ? h('a', {class: 'btn primary', href: url(ev, 'dl'), download: base(name)}, h('span', {icon: 'download'}), h('span', {text: 'Download'})) : null);
      if (name === null) sizeEl.textContent = 'unknown';
      else fetch(url(ev, 'info'), {signal}).then(r => r.ok ? r.json() : null).then(j => { sizeEl.textContent = j ? sizeText(j.size) : 'over 25 MB or not available'; }).catch(() => { sizeEl.textContent = 'unknown'; });
      return card;
    }

    return {setAgent: label => { agent = label; }, tile, open, close, isOpen, kindOf, setPageKey: k => { pageKey = /^[0-9a-f]{16}$/.test(k) ? k : ''; }};
  }

  window.FocusProof = {create};
})();

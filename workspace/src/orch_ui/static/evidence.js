/* Pure HTML renderers. Only caller-supplied local preview paths are loaded. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.Evidence = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const safeSrc = s => typeof s === 'string' && /^[A-Za-z0-9._/#?=&%-]+$/.test(s) && !/^(javascript:|data:|\/\/)/i.test(s) ? s : '';
  const basename = ref => String(ref ?? '').split('?')[0].split(/[\\/]/).pop();
  function kindOf(ev) {
    if (ev.type !== 'file') return 'text';
    const match = basename(ev.ref).match(/\.([^.]+)$/);
    const ext = match ? match[1].toLowerCase() : '';
    if (/^(png|jpg|jpeg|gif|webp|svg)$/.test(ext)) return 'image';
    if (/^(csv|tsv)$/.test(ext)) return 'table';
    if (/^(html|htm)$/.test(ext)) return 'page';
    return 'text';
  }
  function parseDelimited(text, separator) {
    text = String(text ?? '').replace(/^\uFEFF/, '');
    if (!text) return {columns: [], rows: []};
    const records = [];
    let row = [], field = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '"') {
        if (quoted && text[i + 1] === '"') { field += '"'; i++; }
        else if (quoted || !field) quoted = !quoted;
        else field += c;
      } else if (!quoted && c === separator) { row.push(field); field = ''; }
      else if (!quoted && (c === '\n' || c === '\r')) {
        row.push(field); records.push(row); row = []; field = '';
        if (c === '\r' && text[i + 1] === '\n') i++;
      } else field += c;
    }
    if (field || row.length || !/[\r\n]$/.test(text)) { row.push(field); records.push(row); }
    return {columns: records.shift() || [], rows: records};
  }
  const parseCsv = text => parseDelimited(text, ',');
  const tableData = (ev, ctx) => parseDelimited(ctx.csv, /\.tsv$/i.test(String(ev.ref).split('?')[0]) ? '\t' : ',');
  // Fixed icon markup keeps these functions independent of browser globals.
  function symbol(kind) {
    const paths = {table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M10 10v10"/>',
      page: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 8h18"/>',
      image: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m3 17 6-6 5 5 3-3 4 4"/>'};
    return '<svg class="ic" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">' + paths[kind] + '</svg>';
  }
  function chip(ev, ctx = {}) {
    const kind = kindOf(ev), caption = ev.summary || basename(ev.ref), src = safeSrc(ctx.url);
    let preview;
    if (ctx.missing) preview = '<span class="tile-sym">on another computer</span>';
    else if (kind === 'image' && src) preview = `<img src="${esc(src)}" alt="" loading="lazy">`;
    else if (kind === 'table') preview = `<span class="tile-sym">${symbol(kind)}<span>${tableData(ev, ctx).rows.length} rows</span></span>`;
    else if (kind === 'page' || kind === 'image') preview = `<span class="tile-sym">${symbol(kind)}<span>${kind === 'page' ? 'Page' : 'Picture'}</span></span>`;
    else preview = `<span class="tile-txt">${esc(String(ev.summary || ev.text || ev.ref || '').replace(/\s+/g, ' '))}</span>`;
    return `<button type="button" class="tile${ctx.missing ? ' ev-missing' : ''}" aria-label="${esc(caption)}${ctx.missing ? ' · on another computer' : ''}"><span class="tile-img">${preview}</span><span class="tile-t">${esc(caption)}</span></button>`;
  }
  function full(ev, ctx = {}) {
    const kind = kindOf(ev), src = safeSrc(ctx.url), caption = ev.summary || basename(ev.ref);
    let body;
    if (ctx.missing) body = '<p class="ev-missing">on another computer</p>';
    else if (kind === 'image') body = src ? `<figure class="ev-img"><img src="${esc(src)}" alt="${esc(caption)}" loading="lazy"></figure>` : '<p class="muted">Picture preview unavailable.</p>';
    else if (kind === 'page') body = src ? `<div class="ev-html"><div class="agent-chrome">Helper preview</div><iframe sandbox="" referrerpolicy="no-referrer" src="${esc(src)}" title="${esc(caption)}" loading="lazy"></iframe></div>` : '<p class="muted">Page preview unavailable.</p>';
    else if (kind === 'table') {
      const data = tableData(ev, ctx);
      body = data.columns.length ? `<div class="ev-table" tabindex="0" role="region" aria-label="${esc(caption)}"><table><thead><tr>${data.columns.map(c => `<th scope="col">${esc(c)}</th>`).join('')}</tr></thead><tbody>${data.rows.slice(0, 50).map(row => `<tr>${row.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${data.rows.length > 50 ? `<p class="ev-cap">Showing 50 of ${data.rows.length} rows.</p>` : ''}` : '<p class="muted">No table rows to show.</p>';
    } else body = ev.type === 'note' ? `<p class="ev-note">${esc(ev.text || ev.summary || ev.ref)}</p>` : `<pre class="ev-text">${esc(ev.text || ev.summary || ev.ref)}</pre>`;
    return `<div class="ev-full">${body}<details class="ev-technical"><summary>Technical details</summary><dl class="tech-dl"><dt>Type</dt><dd>${esc(ev.type)}</dd><dt>${ev.type === 'command' ? 'Command' : 'Ref'}</dt><dd class="mono">${esc(ev.ref)}</dd></dl></details></div>`;
  }
  return {kindOf, parseCsv, chip, full, esc};
});

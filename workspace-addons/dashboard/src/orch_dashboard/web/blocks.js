'use strict';
// Add-on view blocks (contract: orch.addon-view/1). Builds DOM with textContent only: add-on text never becomes HTML.
// Links: a ticket id opens the ticket here, an https URL opens in a new tab. Nothing else is ever a link.
const OrchBlocks = (() => {
  const SVG = 'http://www.w3.org/2000/svg';
  const TONES = ['neutral', 'good', 'warn', 'needs-you', 'bad'];
  const TONE_WORD = {good: 'OK', warn: 'Check', 'needs-you': 'Needs you', bad: 'Failed', neutral: ''};
  const tone = t => TONES.includes(t) ? t : 'neutral';
  const TICKET = /^t_[a-z0-9]{6,16}$/;
  const HTTPS = /^https:\/\/[^\s<>"'`]+$/;
  const arr = v => Array.isArray(v) ? v : [];

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null && text !== '') e.textContent = String(text);
    return e;
  }
  function icon(id, cls) {
    const s = document.createElementNS(SVG, 'svg');
    s.setAttribute('class', 'ic' + (cls ? ' ' + cls : ''));
    s.setAttribute('aria-hidden', 'true'); s.setAttribute('focusable', 'false');
    const u = document.createElementNS(SVG, 'use'); u.setAttribute('href', '#i-' + id);
    s.append(u);
    return s;
  }
  // Wrap `child` in a link when `link` is a ticket id or an https URL; otherwise return it as is.
  function linked(cls, link, child) {
    const l = typeof link === 'string' ? link : '';
    if (TICKET.test(l)) { const a = el('a', cls); a.href = '#ticket/' + encodeURIComponent(l); a.append(...child); return a; }
    if (HTTPS.test(l)) {
      const a = el('a', cls); a.href = l; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.append(...child);
      const sr = el('span', 'sr-only', ' (opens in a new tab)'); a.append(sr);
      return a;
    }
    const d = el('div', cls); d.append(...child);
    return d;
  }
  const toneDot = t => { const d = el('span', 'tdot t-' + tone(t)); d.setAttribute('role', 'img'); d.setAttribute('aria-label', TONE_WORD[tone(t)] || 'Normal'); return d; };
  const toneTag = t => TONE_WORD[tone(t)] ? el('span', 'tone-word t-' + tone(t), TONE_WORD[tone(t)]) : null;
  const chip = c => { const s = el('span', 'chip' + (c.tone && c.tone !== 'neutral' ? ' t-' + tone(c.tone) : ''), c.label); return s; };
  const parseDate = v => { const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(v) ? v + 'T00:00:00' : v); return Number.isNaN(d.getTime()) ? null : d; };
  const hm = d => d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit'});
  const dayLabel = d => d.toLocaleDateString('en-GB', {weekday: 'short', day: 'numeric', month: 'short'});
  function duration(sec) {
    const n = Number(sec);
    if (!Number.isFinite(n)) return '';
    if (n < 60) return Math.round(n) + ' s';
    if (n < 3600) return Math.floor(n / 60) + ' min' + (Math.round(n % 60) ? ' ' + Math.round(n % 60) + ' s' : '');
    return Math.floor(n / 3600) + ' h ' + Math.round((n % 3600) / 60) + ' min';
  }
  function cell(col, v) {
    const td = el('td');
    if (v == null) { td.textContent = '—'; return td; }
    if (col.type === 'number') { td.className = 'num'; td.textContent = String(v); }
    else if (col.type === 'duration') { td.className = 'num'; td.textContent = duration(v) || '—'; }
    else if (col.type === 'date') { const d = parseDate(String(v)); td.textContent = d ? (/T/.test(String(v)) ? dayLabel(d) + ' ' + hm(d) : dayLabel(d)) : '—'; }
    else if (col.type === 'tone') { td.append(toneDot(String(v))); const w = toneTag(String(v)); if (w) td.append(' ', w); }
    else td.textContent = String(v);
    return td;
  }

  const draw = {
    stat(b) {
      const d = el('div', 'stat t-' + tone(b.tone));
      d.append(el('span', 'stat-value', b.value), el('span', 'stat-label', b.label));
      return d;
    },
    list(b) {
      const s = el('section', 'blk'); s.append(el('h2', 'blk-title', b.title));
      const ul = el('ul', 'blk-list');
      if (!arr(b.items).length) ul.append(el('li', 'blk-none', 'Nothing here.'));
      for (const it of arr(b.items)) {
        const body = el('span', 'li-main'); body.append(el('span', 'li-title', it.title));
        if (it.subtitle) body.append(el('small', 'li-sub', it.subtitle));
        if (arr(it.chips).length) { const c = el('span', 'tags'); c.append(...it.chips.map(chip)); body.append(c); }
        const li = el('li'), row = linked('li-row t-' + tone(it.tone), it.link, [toneDot(it.tone), body]);
        if (row.tagName === 'A') row.append(icon('chevron', 'go'));
        li.append(row); ul.append(li);
      }
      s.append(ul);
      if (b.more > 0) s.append(el('p', 'blk-more', `+${b.more} more`));
      return s;
    },
    calendar(b) {
      const s = el('section', 'blk panel strip-panel'), strip = el('ol', 'strip');
      const today = new Date().toDateString();
      for (const day of arr(b.days)) {
        const d = parseDate(day.date); if (!d) continue;
        const li = el('li', 'day' + (d.toDateString() === today ? ' today' : '') + (arr(day.items).length ? ' has' : ' empty'));
        const head = el('div', 'day-head'); head.append(el('span', '', d.toLocaleDateString('en-GB', {weekday: 'short'})), el('b', '', d.getDate()));
        li.append(head);
        for (const it of arr(day.items)) {
          // A frequent repeat is one item per day: "Every 5 min" in place of the time, a muted note below.
          const when = it.every ? el('time', 'every', it.every) : el('time', '', it.time || '');
          const parts = [when, el('span', '', it.title)];
          if (it.note) parts.push(el('small', 'run-note', it.note));
          const a = linked('run t-' + tone(it.tone) + (it.every ? ' repeat' : ''), it.link, parts);
          li.append(a);
        }
        strip.append(li);
      }
      s.append(strip);
      return s;
    },
    timeline(b) {
      const s = el('section', 'blk'); if (b.title) s.append(el('h2', 'blk-title', b.title));
      const ol = el('ol', 'blk-timeline');
      for (const it of arr(b.items)) {
        const d = parseDate(it.at);
        const when = el('time', '', d ? dayLabel(d) + ' ' + hm(d) : ''); if (d) when.dateTime = it.at;
        const li = el('li', 'tl t-' + tone(it.tone)), body = linked('tl-text', it.link, [el('span', '', it.text)]);
        li.append(toneDot(it.tone), body, when); ol.append(li);
      }
      s.append(ol);
      return s;
    },
    chips(b) {
      const s = el('section', 'blk'); if (b.title) s.append(el('h2', 'blk-title', b.title));
      const c = el('div', 'chips'); c.append(...arr(b.items).map(chip)); s.append(c);
      return s;
    },
    table(b) {
      const s = el('section', 'blk'); if (b.title) s.append(el('h2', 'blk-title', b.title));
      const wrap = el('div', 'table-wrap'), t = el('table', 'blk-table'), cols = arr(b.columns);
      const hr = el('tr');
      for (const c of cols) { const th = el('th', c.type === 'number' || c.type === 'duration' ? 'num' : '', c.label); th.scope = 'col'; hr.append(th); }
      const head = el('thead'); head.append(hr); t.append(head);
      const tb = el('tbody');
      for (const r of arr(b.rows)) {
        const tr = el('tr');
        cols.forEach((c, i) => {
          const td = cell(c, (r.cells || {})[c.key]);
          if (i === 0 && typeof r.link === 'string' && (TICKET.test(r.link) || HTTPS.test(r.link))) {
            const a = linked('cell-link', r.link, [...td.childNodes]); td.replaceChildren(a);
          }
          tr.append(td);
        });
        tb.append(tr);
      }
      t.append(tb); wrap.append(t); s.append(wrap);
      if (b.more > 0) s.append(el('p', 'blk-more', `+${b.more} more`));
      return s;
    },
  };

  // Stats sit together in one row; everything else follows in order. Unknown types are skipped.
  function render(blocks) {
    const root = document.createDocumentFragment();
    let stats = null;
    for (const b of arr(blocks)) {
      const f = b && Object.prototype.hasOwnProperty.call(draw, b.type) ? draw[b.type] : null;
      if (!f) continue;
      if (b.type === 'stat') { if (!stats) { stats = el('div', 'stats'); root.append(stats); } stats.append(f(b)); continue; }
      stats = null;
      root.append(f(b));
    }
    return root;
  }
  return {render, duration};
})();
if (typeof module !== 'undefined') module.exports = OrchBlocks;

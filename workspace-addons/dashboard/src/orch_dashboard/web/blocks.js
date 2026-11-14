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
  const ADDON = /^addon:([a-z][a-z0-9-]{1,31})(\/[A-Za-z0-9_./-]{0,100})?$/;
  const OWN = /^addon:(?![/\\])(?!.*\.\.)([A-Za-z0-9_./?=&%-]{0,300})$/;   // a page of the add-on whose view this is
  const APP = /^app:(home|tickets|notes|chat|settings|addon)(\/[a-z][a-z0-9-]{0,31}){0,2}$/;   // a page of the dashboard (hash route)
  const FILE = /^f_[a-z0-9]+$/;
  const LOCAL = /^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}\/?$/;
  let opts = {};   // {addonUrl(name) -> local page address or null}, set per render()
  const VERB = /^[a-z][a-z-]{0,20}$/;

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
    if (APP.test(l)) { const a = el('a', cls); a.href = '#' + l.slice(4); a.append(...child); return a; }  // a page of the dashboard itself
    const own = opts.self ? OWN.exec(l) : null;
    const am = own ? [l, opts.self, own[1] ? '/' + own[1] : ''] : ADDON.exec(l);
    if (am && !am[2]?.includes('..')) {
      // `addon:<name>/<path>`: that add-on's own page when it runs here, else a Start button (the page starts it).
      const base = typeof opts.addonUrl === 'function' ? opts.addonUrl(am[1]) : null;
      const inApp = typeof base === 'string' && LOCAL.test(base) && typeof opts.inApp === 'function' ? opts.inApp(am[1]) : null;
      if (inApp) { const a = el('a', cls); a.href = inApp(am[2] || '/'); a.append(...child); return a; }  // the add-on's page inside this app
      if (typeof base === 'string' && LOCAL.test(base)) {
        const a = el('a', cls); a.href = base.replace(/\/$/, '') + (am[2] || '/'); a.target = '_blank'; a.rel = 'noopener noreferrer'; a.append(...child);
        a.append(el('span', 'sr-only', ' (opens in a new tab)'));
        return a;
      }
      const b = el('button', cls + ' btn outline sm'); b.type = 'button'; b.dataset.action = 'start'; b.append(...child);
      b.append(el('span', '', ' · Start ' + am[1]));
      return b;
    }
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

  // An action is only drawn when it is the one generic add-on op with a plain verb and a ticket id as target.
  // The page (not this file) turns the data attributes into a request: the DOM carries no code.
  function actionAttrs(node, a, label) {
    const args = a && a.args || {};
    if (a && a.op === 'addon.edit' && TICKET.test(String(args.target))) { node.dataset.addonEdit = String(args.target); return true; }
    // shared-link ops only on the page of the add-on with the `links` panel (opts.links)
    const nat = a && /^link\.(copy|extend|stop)$/.exec(String(a.op));
    if (nat && opts.links === true && FILE.test(String(args.id))) { node.dataset.native = 'link-' + nat[1]; node.dataset.linkId = String(args.id); node.textContent = LINK_LABEL[a.op]; node.setAttribute('aria-label', LINK_LABEL[a.op]); return true; }   // always orch's words
    // A schedule that came by sync: "Allow on this computer" (the page signs it with the sync add-on; DOM = ticket id only)
    if (a && a.op === 'addon.allow' && TICKET.test(String(args.target))) { node.dataset.syncAllow = String(args.target); node.textContent = 'Allow on this computer'; node.setAttribute('aria-label', 'Allow on this computer'); return true; }   // always orch's words
    const ok = a && a.op === 'addon.act' && VERB.test(String(args.verb)) && TICKET.test(String(args.target));
    if (!ok) return false;
    node.dataset.addonAct = 'true'; node.dataset.verb = String(args.verb); node.dataset.target = String(args.target);
    if (label) node.dataset.label = label;
    return true;
  }
  const LINK_LABEL = {'link.copy': 'Copy link', 'link.extend': 'Extend', 'link.stop': 'Stop sharing'};
  const rowButton = (a, cls) => {
    const ghost = a.action && (a.action.op === 'addon.edit' || a.action.op === 'link.extend' || a.action.op === 'link.stop');
    const fixed = a.action && LINK_LABEL[a.action.op];   // a link op always says what it does, in orch's own words
    const b = el('button', 'btn ' + (ghost && a.tone !== 'bad' ? 'ghost' : 'outline') + ' sm' + (a.tone === 'bad' ? ' danger' : '') + (cls ? ' ' + cls : ''), fixed || a.label); b.type = 'button';
    if (a.confirm) b.dataset.confirm = String(a.confirm);
    return actionAttrs(b, a.action, a.label) ? b : null;
  };
  // Heading row of a block: the title, then quiet text (`meta`, or the `count`) at the right.
  function blkHead(b, tag) {
    const quiet = b.meta || (Number.isInteger(b.count) ? String(b.count) : '');
    if (!quiet) return b.title ? el(tag || 'h2', 'blk-title', b.title) : null;
    const d = el('div', 'blk-head'); if (b.title) d.append(el(tag || 'h2', 'blk-title', b.title));
    d.append(el('span', 'meta', quiet));
    return d;
  }
  const shownLink = to => typeof to === 'string' && (APP.test(to) || TICKET.test(to) || HTTPS.test(to));
  const MARKS = {arrow: '\u2197', repeat: '\u21ba', dash: '\u2014'};
  function emptyState(e) {
    const d = el('div', 'empty blk-empty'), mark = el('span', 'empty-mark', MARKS[e.mark] || MARKS.arrow); mark.setAttribute('aria-hidden', 'true');
    d.append(mark, el('h3', '', e.title)); if (e.text) d.append(el('p', '', e.text));
    for (const [key, cls] of [['button', 'btn primary sm'], ['link', 'btn ghost sm']]) {
      const x = e[key]; if (!x || !shownLink(x.to)) continue;
      const a = linked(cls, x.to, [x.label + (key === 'link' ? ' \u2192' : '')]);
      a.className = cls; d.append(a);
    }
    return d;
  }
  // "Send a message" opens its workspace thread in Chat via messageSend. The DOM carries only the checked peer id.
  const PEER = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
  function sendButton(it) {
    const a = arr(it.actions).find(x => x && x.action && x.action.op === 'message.send' && x.action.args && PEER.test(String(x.action.args.workspace)));
    if (!a) return null;
    const b = el('button', 'btn outline sm send-msg', a.label || 'Send a message'); b.type = 'button';
    b.dataset.sendTo = String(a.action.args.workspace); b.dataset.who = String(it.title || '');
    b.setAttribute('aria-label', (a.label || 'Send a message') + ' to ' + String(it.title || ''));
    return b;
  }
  function toggleEl(t) {
    if (t && t.action && /^link\./.test(String(t.action.op))) return null;   // a switch never carries a shared-link op
    const b = el('button', 'switch'); b.type = 'button';
    b.setAttribute('role', 'switch'); b.setAttribute('aria-checked', t.on ? 'true' : 'false'); b.setAttribute('aria-label', String(t.label));
    return actionAttrs(b, t.action, t.label) ? b : null;
  }
  function detailList(rows) {
    const dl = el('dl', 'acc-detail');
    for (const r of rows) {
      const d = el('div'), dt = el('dt', '', r.label), dd = el('dd', r.tone ? 't-' + tone(r.tone) : '');
      if (arr(r.lines).length) arr(r.lines).forEach(l => dd.append(el('p', 'acc-line', l)));
      else dd.append(String(r.value ?? ''));  // Copy only exists for the value that is shown
      if (r.copy && r.value && !arr(r.lines).length) {
        const c = el('button', 'btn ghost xs', 'Copy'); c.type = 'button'; c.dataset.copy = String(r.value);
        c.setAttribute('aria-label', 'Copy ' + r.label); dd.append(' ', c);
      }
      d.append(dt, dd); dl.append(d);
    }
    return dl;
  }
  function ticketLinks(items) {
    const box = el('div', 'acc-tickets');
    for (const t of items) {
      const a = el('a', 'acc-ticket'); a.href = '#ticket/' + encodeURIComponent(t.id);
      a.append(el('span', 'li-title', t.title));
      if (t.key) a.append(el('span', 'mono', t.key));
      if (t.status) a.append(chip(t.status));
      box.append(a);
    }
    return box;
  }
  function accordionItem(it, key) {
    const li = el('li', 'acc-li'), sw = it.toggle ? toggleEl(it.toggle) : null;
    const sendBtn = sendButton(it);
    const buttons = arr(it.actions).filter(a => !(a && a.action && a.action.op === 'message.send')).map(a => {
      const b = el('button', 'btn outline sm' + (a.tone === 'bad' ? ' danger' : ''), a.label); b.type = 'button';
      if (a.confirm) b.dataset.confirm = String(a.confirm);
      return actionAttrs(b, a.action, a.label) ? b : null;
    }).filter(Boolean);
    const expandable = arr(it.detail).length || arr(it.tickets).length || buttons.length;
    const finish = () => { if (sendBtn) li.append(sendBtn); if (sw) li.append(sw); return li; };
    const main = el('span', 'li-main'); main.append(el('span', 'li-title', it.title));
    if (it.subtitle) main.append(el('small', 'li-sub', it.subtitle));
    if (arr(it.chips).length) { const c = el('span', 'tags'); c.append(...it.chips.map(chip)); main.append(c); }
    if (!expandable) { const row = el('div', 'li-row grow'); row.append(toneDot(it.tone), main); li.append(row); return finish(); }
    const d = el('details', 'acc grow'); d.dataset.key = key;
    const sum = el('summary', 'li-row'); sum.append(el('span', 'chev'), toneDot(it.tone), main);
    const panel = el('div', 'acc-panel');
    if (arr(it.detail).length) panel.append(detailList(it.detail));
    if (arr(it.tickets).length) panel.append(ticketLinks(it.tickets));
    if (buttons.length) { const row = el('div', 'row acc-actions'); row.append(...buttons); panel.append(row); }
    d.append(sum, panel); li.append(d);
    return finish();
  }

  // One line per row: the title, quiet cells, and the actions that show on hover or keyboard focus.
  function compactItem(it) {
    const li = el('li', 'compact-li'), row = el('div', 'compact-row');
    const t = linked('li-title compact-title', it.link, [String(it.title)]);
    t.title = String(it.title);
    row.append(t); for (const m of arr(it.meta)) row.append(el('span', 'meta', m));
    const box = el('div', 'compact-actions');
    for (const a of arr(it.actions)) { const b = rowButton(a); if (b) box.append(b); }
    row.append(box); li.append(row);
    return li;
  }

  const draw = {
    stat(b) {
      const d = el('div', 'stat t-' + tone(b.tone));
      d.append(el('span', 'stat-value', b.value), el('span', 'stat-label', b.label));
      return d;
    },
    list(b) {
      const s = el('section', 'blk' + (b.compact ? ' blk-compact' : '') + (b.above ? ' blk-above' : '')), head = blkHead(b), ul = el('ul', 'blk-list');
      if (head) s.append(head);
      const host = b.above ? el('div', 'blk-card card') : s;
      if (b.above) s.append(host);
      if (!arr(b.items).length && b.empty) { host.append(emptyState(b.empty)); return s; }
      if (!arr(b.items).length) ul.append(el('li', 'blk-none', 'Nothing here.'));
      arr(b.items).forEach((it, n) => {
        if (b.compact) { ul.append(compactItem(it)); return; }
        if (arr(it.detail).length || arr(it.tickets).length || arr(it.actions).length || it.toggle) {
          ul.append(accordionItem(it, 'acc-' + String(b.title).slice(0, 30) + '-' + n)); return;
        }
        const body = el('span', 'li-main'); body.append(el('span', 'li-title', it.title));
        if (it.subtitle) body.append(el('small', 'li-sub', it.subtitle));
        if (arr(it.chips).length) { const c = el('span', 'tags'); c.append(...it.chips.map(chip)); body.append(c); }
        const li = el('li'), row = linked('li-row t-' + tone(it.tone), it.link, [toneDot(it.tone), body]);
        if (row.tagName === 'A') row.append(icon('chevron', 'go'));
        li.append(row); ul.append(li);
      });
      host.append(ul);
      if (b.more > 0) host.append(el('p', 'blk-more', `+${b.more} more`));
      return s;
    },
    footnote(b) {
      const p = el('p', 'blk-footnote'); p.append(el('span', '', b.text));
      if (b.link && shownLink(b.link.to)) p.append(linked('', b.link.to, [b.link.label + ' \u2192']));
      return p;
    },
    settings(b) {
      const s = el('section', 'blk blk-settings'), head = el('header', 'card-h'); head.append(el('h3', '', b.title)); s.append(head);
      for (const r of arr(b.rows)) {
        const row = el('div', 'setting-row'), val = el('div', 'row-value' + (r.tone && r.tone !== 'neutral' ? ' t-' + tone(r.tone) : '')), act = el('div', 'row-action');
        val.append(String(r.value)); if (r.note) val.append(el('p', 'meta', r.note));
        if (r.button) { const b2 = rowButton({label: r.button.label, action: r.button.action}); if (b2) act.append(b2); }
        row.append(el('div', 'row-label', r.label), val, act); s.append(row);
      }
      return s;
    },
    radio(b) {
      const s = el('section', 'blk blk-radio'); s.setAttribute('aria-label', String(b.title));
      const head = el('header', 'card-h'); head.append(el('h3', '', b.title)); s.append(head);
      const box = el('div', 'sync-options'); box.setAttribute('role', 'radiogroup'); box.setAttribute('aria-label', String(b.title));
      const name = 'radio-' + String(b.title).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 30);
      for (const o of arr(b.options)) {
        const label = el('label'), input = el('input'); input.type = 'radio'; input.name = name; input.checked = o.selected === true; input.dataset.selected = o.selected === true ? 'true' : 'false';
        const a = o.action || {}, args = a.args || {};
        if (a.op === 'addon.act' && VERB.test(String(args.verb)) && /^[a-z][a-z0-9-]{0,20}$/.test(String(args.target))) { input.dataset.radioVerb = String(args.verb); input.dataset.radioTarget = String(args.target); }
        else if (typeof o.link === 'string' && APP.test(o.link)) input.dataset.radioGo = o.link.slice(4);
        else input.disabled = true;
        label.append(input, String(o.label)); box.append(label);
      }
      s.append(box);
      return s;
    },
    calendar(b) {
      const s = el('section', 'blk blk-above'), strip = el('ol', 'strip'), head = blkHead(b);
      if (head) s.append(head);
      const box = el('div', 'blk-card card strip-panel');
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
      box.append(strip); s.append(box);
      return s;
    },
    timeline(b) {
      const s = el('section', 'blk'), head = blkHead(b); if (head) s.append(head);
      const ol = el('ol', 'blk-timeline');
      for (const it of arr(b.items)) {
        const d = parseDate(it.at);
        const when = el('time', '', d ? dayLabel(d) + ' ' + hm(d) : ''); if (d) when.dateTime = it.at;
        const li = el('li', 'tl t-' + tone(it.tone)), body = linked('tl-text', it.link, [el('span', '', typeof window !== 'undefined' && window.DashHelpers ? window.DashHelpers.plainNames(it.text) : it.text)]);
        li.append(toneDot(it.tone), body, when); ol.append(li);
      }
      s.append(ol);
      return s;
    },
    chips(b) {
      const s = el('section', 'blk'), head = blkHead(b); if (head) s.append(head);
      const c = el('div', 'chips'); c.append(...arr(b.items).map(chip)); s.append(c);
      return s;
    },
    table(b) {
      const s = el('section', 'blk'), head = blkHead(b); if (head) s.append(head);
      const wrap = el('div', 'table-wrap'), t = el('table', 'blk-table data-table'), cols = arr(b.columns);
      const hr = el('tr');
      const rowsList = arr(b.rows), hasActions = rowsList.some(r => arr(r.actions).length), hasToggle = rowsList.some(r => r.toggle);
      for (const c of cols) { const th = el('th', c.type === 'number' || c.type === 'duration' ? 'num' : '', c.label); th.scope = 'col'; hr.append(th); }
      if (hasActions) { const th = el('th', '', 'Actions'); th.scope = 'col'; hr.append(th); }
      if (hasToggle) { const th = el('th', '', 'On'); th.scope = 'col'; hr.append(th); }
      const thead = el('thead'); thead.append(hr); t.append(thead);
      const tb = el('tbody');
      for (const r of arr(b.rows)) {
        const tr = el('tr');
        cols.forEach((c, i) => {
          const td = cell(c, (r.cells || {})[c.key]);
          if (i === 0 && typeof r.link === 'string' && (TICKET.test(r.link) || HTTPS.test(r.link))) {
            const a = linked('cell-link', r.link, [...td.childNodes]); td.replaceChildren(a);
          }
          if (i === 0 && r.subtitle) td.append(el('span', 'subline', r.subtitle));
          tr.append(td);
        });
        if (hasActions) {
          const td = el('td'), box = el('div', 'row');
          for (const a of arr(r.actions)) { const btn = rowButton(a); if (btn) box.append(btn); }
          td.append(box); tr.append(td);
        }
        if (hasToggle) { const td = el('td'), sw = r.toggle ? toggleEl(r.toggle) : null; if (sw) td.append(sw); tr.append(td); }
        tb.append(tr);
      }
      t.append(tb); wrap.append(t); s.append(wrap);
      if (b.more > 0) s.append(el('p', 'blk-more', `+${b.more} more`));
      return s;
    },
  };

  // Stats sit together in one row; everything else follows in order. Unknown types are skipped.
  function render(blocks, options) {
    opts = options || {};
    const root = document.createDocumentFragment();
    let stats = null, pair = null, settings = null;
    for (const b of arr(blocks)) {
      const f = b && Object.prototype.hasOwnProperty.call(draw, b.type) ? draw[b.type] : null;
      if (!f) continue;
      if (b.type === 'stat') { if (!stats) { stats = el('div', 'stats'); root.append(stats); } stats.append(f(b)); continue; }
      stats = null;
      const node = f(b);
      if (b.type === 'radio' && settings) { settings.append(...node.childNodes); continue; }   // a choice sits in the card above it
      settings = b.type === 'settings' ? node : null;
      if (b.type === 'list' && b.span === 'half') {   // two half lists side by side
        if (!pair || pair.childNodes.length >= 2) { pair = el('div', 'blk-pair'); root.append(pair); }
        pair.append(node); continue;
      }
      pair = null;
      root.append(node);
    }
    return root;
  }
  const appHash = to => typeof to === 'string' && APP.test(to) ? '#' + to.slice(4) : null;
  return {render, duration, appHash};
})();
if (typeof module !== 'undefined') module.exports = OrchBlocks;

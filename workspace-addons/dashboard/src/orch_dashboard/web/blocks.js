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
  const picked = new Map();   // a table's chosen tab and Show more, kept over repaints (title|filter column)
  const ADDON = /^addon:([a-z][a-z0-9-]{1,31})(\/[A-Za-z0-9_./-]{0,100})?$/;
  const OWN = /^addon:(?![/\\])(?!.*\.\.)([A-Za-z0-9_./?=&%-]{0,300})$/;   // a page of the add-on whose view this is
  const APP = /^app:(home|tickets|notes|chat|settings|addon)(\/[a-z][a-z0-9-]{0,31}){0,2}$/;   // a page of the dashboard (hash route)
  const FILE = /^f_[a-z0-9]+$/;
  const LOCAL = /^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}\/?$/;
  let opts = {};   // {addonUrl(name) -> local page address or null}, set per render()
  const openLogs = new Set();   // ids whose whole log is open: kept when the page refreshes (ORCH-1130)
  const VERB = /^[a-z][a-z-]{0,20}$/;
  const HIDDEN = /[\u0000-\u001f\u007f-\u009f\u061c\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/;
  const ITEM = /^[a-z]_[a-z0-9]{6,16}$/;   // the id of one thing an add-on keeps (a ticket t_…, a lesson l_…)

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null && text !== '') e.textContent = String(text);
    return e;
  }
  // Icons come from the kit's one set (kit/icons.js, trusted constants, parsed as SVG, never as page HTML); an unknown
  // name draws an empty icon instead of a stray glyph.
  function icon(id, cls) {
    const markup = window.icon ? window.icon(id === 'chevron' ? 'chevron-right' : id, 16, cls || '') : '';
    const svg = markup ? new DOMParser().parseFromString(markup, 'image/svg+xml').documentElement : null;
    if (svg && svg.localName === 'svg') return document.importNode(svg, true);
    const s = document.createElementNS(SVG, 'svg');
    s.setAttribute('class', 'ic' + (cls ? ' ' + cls : '')); s.setAttribute('aria-hidden', 'true');
    return s;
  }
  // Wrap `child` in a link when `link` is a ticket id, an https URL or a local app address; otherwise return it as is.
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
    if (HTTPS.test(l) || LOCAL.test(l)) {  // an https page, or an app on this computer (http://127.0.0.1:<port>)
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
  const CHIP_TONE = {good: 'success', warn: 'warning', 'needs-you': 'attn', bad: 'danger', neutral: ''};
  const toneChip = (t, text, extra) => el('span', ['chip', CHIP_TONE[tone(t)], extra].filter(Boolean).join(' '), text);
  const shownLink2 = l => typeof l === 'string' && (TICKET.test(l) || HTTPS.test(l) || APP.test(l));
  const on = (node, ev, fn) => { if (node && typeof node.addEventListener === 'function') node.addEventListener(ev, fn); };
  const NICE = [2, 4, 6, 8, 10, 20, 30, 40, 50, 60, 80, 100, 150, 200, 300, 400, 500, 1000];   // even: the middle line is a whole number
  const nice = v => NICE.find(x => x >= v) || Math.ceil(v / 1000) * 1000;
  const pct = (v, max) => Math.max(0, Math.min(100, max > 0 ? v / max * 100 : 0)).toFixed(1) + '%';
  const parseDate = v => { const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(v) ? v + 'T00:00:00' : v); return Number.isNaN(d.getTime()) ? null : d; };
  const hm = d => typeof window !== 'undefined' && window.UI?.clock ? window.UI.clock(d) : d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit', hour12: false});
  const dayLabel = d => typeof window !== 'undefined' && window.UI?.stamp ? window.UI.stamp(d, {time: false}) : d.toLocaleDateString('en-GB', {weekday: 'short', day: 'numeric', month: 'short'});
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
    // One text line in a small window (addon.prompt): the dialog is the page's; here only checked plain text goes into the DOM.
    if (a && a.op === 'addon.prompt' && VERB.test(String(args.verb)) && ITEM.test(String(args.target)) && typeof args.value === 'string' && args.value.length <= 200 && !HIDDEN.test(args.value) && typeof args.label === 'string' && args.label.length >= 1 && args.label.length <= 40 && !HIDDEN.test(args.label)) {
      node.dataset.addonPrompt = String(args.target); node.dataset.verb = String(args.verb); node.dataset.value = args.value; node.dataset.promptLabel = args.label;
      return true;
    }
    const ok = a && a.op === 'addon.act' && VERB.test(String(args.verb)) && ITEM.test(String(args.target));
    if (!ok) return false;
    node.dataset.addonAct = 'true'; node.dataset.verb = String(args.verb); node.dataset.target = String(args.target);
    if (args.review === true) node.dataset.review = 'true';   // the page shows what the add-on says it does before the click
    if (label) node.dataset.label = label;
    return true;
  }
  const LINK_LABEL = {'link.copy': 'Copy link', 'link.extend': 'Extend', 'link.stop': 'Stop sharing'};
  const rowButton = (a, cls) => {
    const ghost = a.action && (a.action.op === 'addon.edit' || a.action.op === 'addon.prompt' || a.action.op === 'link.extend' || a.action.op === 'link.stop');
    const fixed = a.action && LINK_LABEL[a.action.op];   // a link op always says what it does, in orch's own words
    const b = el('button', 'btn ' + (ghost && a.tone !== 'bad' ? 'ghost' : 'outline') + ' sm' + (a.tone === 'bad' ? ' danger' : '') + (cls ? ' ' + cls : ''), fixed || a.label); b.type = 'button';
    if (a.confirm) b.dataset.confirm = String(a.confirm);
    return actionAttrs(b, a.action, a.label) ? b : null;
  };
  // A shared link also gets "Open" (owner 15 Nov, fb4): same checked link id, the page opens the link in a new tab.
  const openFirst = b => {
    if (b.dataset.native !== 'link-copy') return [b];
    const o = el('button', 'btn ghost sm', 'Open'); o.type = 'button'; o.dataset.native = 'link-open'; o.dataset.linkId = b.dataset.linkId; o.setAttribute('aria-label', 'Open link');
    return [o, b];
  };
  // Heading row of a block: the title, then quiet text (`meta`, or the `count`) at the right.
  function blkHead(b, tag) {
    const quiet = b.meta || (Number.isInteger(b.count) ? String(b.count) : '');
    if (!quiet) return b.title ? el(tag || 'h2', 'blk-title', b.title) : null;
    const d = el('div', 'blk-head'); if (b.title) d.append(el(tag || 'h2', 'blk-title', b.title));
    d.append(el('span', 'meta', quiet));
    return d;
  }
  const shownLink = to => typeof to === 'string' && (APP.test(to) || TICKET.test(to) || HTTPS.test(to) || LOCAL.test(to));  // LOCAL: an app on this computer (ORCH-846)
  const MARKS = {arrow: '\u2197', repeat: '\u21ba', dash: '\u2014'};
  function emptyState(e) {
    // The one master empty state (UI.state); the buttons stay real links checked by shownLink.
    let d;
    if (typeof window !== 'undefined' && window.UI && window.UI.state) { d = window.UI.state({kind: 'empty', title: e.title, text: e.text}); d.classList.add('blk-empty'); }
    else { d = el('div', 'empty blk-empty'); const mark = el('span', 'empty-mark', MARKS[e.mark] || MARKS.arrow); mark.setAttribute('aria-hidden', 'true'); d.append(mark, el('h3', '', e.title)); if (e.text) d.append(el('p', '', e.text)); }
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
    // A switch says what it turns on: the add-on's short words sit beside it (bug hunt 17 Nov: a bare On/Off).
    const swText = sw && it.toggle.text ? el('span', 'switch-text', it.toggle.text) : null;
    if (swText) swText.setAttribute('aria-hidden', 'true');
    const finish = () => { if (sendBtn) li.append(sendBtn); if (swText) li.append(swText); if (sw) li.append(sw); return li; };
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
    for (const a of arr(it.actions)) { const b = rowButton(a); if (b) box.append(...openFirst(b)); }
    row.append(box); li.append(row);
    return li;
  }


  // ---- List and panel (split, ORCH-326): a slim list on the left, the chosen item in full on the right; on a phone the
  // list first, then the panel with a way back (kit .split-view). The chosen item has an address: #<page>?<param>=<id>.
  // Every action of an item may only name that item's own id as its target; anything else is not drawn.
  const SPLIT_ID = /^[a-z0-9][a-z0-9_.:-]{0,63}$/;
  const PARAM = /^[a-z]{1,12}$/;
  const splitParam = b => PARAM.test(String(b.param)) ? String(b.param) : 'item';
  const hashBase = () => typeof location !== 'undefined' ? String(location.hash || '').split('?')[0] : '';
  function splitChosen(param) {
    if (typeof location === 'undefined') return null;
    const q = String(location.hash || '').split('?')[1];
    const v = q ? new URLSearchParams(q).get(param) : null;
    return v && SPLIT_ID.test(v) ? v : null;
  }
  const STATE_DOT = {good: 'dot-ok', bad: 'dot-err', 'needs-you': 'dot-err', warn: 'dot-warn', neutral: 'dot-off'};
  const stateDot = t => { const d = el('span', STATE_DOT[tone(t)]); d.setAttribute('aria-hidden', 'true'); return d; };
  const STATE_PILL = {good: 'pill done', bad: 'pill failed', 'needs-you': 'pill failed', warn: 'pill needs', neutral: 'pill'};
  const statePill = c => { const p = el('span', STATE_PILL[tone(c.tone)]); p.append(stateDot(c.tone), String(c.label)); return p; };
  // One button of an item: its own add-on verb (target = this item) or a link. `cls` is the kit look.
  function splitButton(x, it, cls) {
    if (!x || typeof x.label !== 'string') return null;
    const a = x.action, args = a && a.args || {};
    if (a) {
      if (!(a.op === 'addon.act' && VERB.test(String(args.verb)) && args.target === it.id)) return null;
      const b = el('button', cls, x.label); b.type = 'button';
      b.dataset.addonAct = 'true'; b.dataset.verb = String(args.verb); b.dataset.target = it.id; b.dataset.label = x.label;
      b.setAttribute('aria-label', x.label + ' ' + it.title);
      return b;
    }
    if (shownLink(x.link)) { const l = linked(cls, x.link, [x.label]); l.className = cls; return l; }
    return null;
  }
  function splitRow(it, cur, param) {
    const row = el('div', 'list-row' + (cur ? ' cur' : '')); row.dataset.splitRow = it.id;
    const a = el('a', 'grow plain-link'); a.href = hashBase() + '?' + param + '=' + encodeURIComponent(it.id);
    a.dataset.splitPick = it.id; if (cur) a.setAttribute('aria-current', 'true');
    a.append(String(it.title), el('span', 'subline', it.state.label));
    row.append(stateDot(it.state.tone), a);
    if (!it.question) { const b = splitButton(it.action, it, 'btn outline sm'); if (b) row.append(b); }
    return row;
  }
  function splitFacts(facts, it) {
    const dl = el('dl', 'split-facts');
    for (const f of arr(facts)) {
      const d = el('div'), dd = el('dd');
      if (f.switch && f.switch.action) {
        const a = f.switch.action, args = a.args || {};
        if (a.op === 'addon.act' && VERB.test(String(args.verb)) && args.target === it.id) {
          const label = el('label', 'row'), sw = el('button', 'switch'); sw.type = 'button';
          sw.setAttribute('role', 'switch'); sw.setAttribute('aria-checked', f.switch.on ? 'true' : 'false'); sw.setAttribute('aria-label', String(f.switch.label));
          sw.dataset.addonAct = 'true'; sw.dataset.verb = String(args.verb); sw.dataset.target = it.id; sw.dataset.label = String(f.switch.label);
          label.append(sw, el('span', '', f.value || '')); dd.append(label);
        } else dd.append(String(f.value || ''));
      } else {
        if (f.tone) dd.append(stateDot(f.tone), ' ');
        dd.append(f.link && shownLink(f.link) ? linked('', f.link, [String(f.value || f.link)]) : String(f.value || ''));
      }
      d.append(el('dt', '', f.label), dd); dl.append(d);
    }
    return dl;
  }
  function splitLog(log, it) {
    const box = el('div', 'log-lines'); box.dataset.log = it.id; box.tabIndex = -1;
    box.setAttribute('role', 'group'); box.setAttribute('aria-label', (log.title || 'Last log lines') + ' of ' + it.title);
    box.append(el('div', 'log-lines-h', log.title || 'Last log lines'));
    if (arr(log.lines).length) {
      const ol = el('ol'); arr(log.lines).forEach(l => ol.append(el('li', '', l))); box.append(ol);
      if (arr(log.lines).length > 6) { box.classList.add(openLogs.has(it.id) ? 'log-full' : 'log-short'); box.dataset.long = '1'; } // Open log shows every line
      else if (openLogs.has(it.id)) box.classList.add('log-full');
    }
    else box.append(el('p', 'meta', log.empty || 'Nothing written yet.'));
    return box;
  }
  function splitPanel(it, shown, label) {
    const p = it.panel || {}, s = el('section', 'split-panel stack-lg'); s.dataset.splitPanel = it.id; s.tabIndex = -1;
    s.setAttribute('aria-label', String(it.title)); if (!shown) s.hidden = true;
    const back = el('div', 'phone-only'), bb = el('button', 'btn ghost sm', '← All ' + String(label || 'items').toLowerCase()); bb.type = 'button'; bb.dataset.splitPick = '';
    back.append(bb); s.append(back);
    const head = el('div'), top = el('div', 'row'); top.append(el('h2', 't-sect grow', it.title), statePill(it.state)); head.append(top);
    if (p.text) head.append(el('p', 'muted', p.text));
    s.append(head);
    const row = el('div', 'row');
    if (it.question) row.append(el('span', 'muted', 'The question above is about this one.'));
    else arr(p.buttons).forEach((x, i) => { const b = splitButton(x, it, 'btn sm ' + (x.primary ? 'primary' : 'outline')); if (b) row.append(b); });
    if (p.log) { const w = openLogs.has(it.id) ? 'Close log' : 'Open log', o = el('button', 'btn ghost sm', w); o.type = 'button'; o.dataset.splitLog = it.id; o.setAttribute('aria-label', w + ' of ' + it.title); row.append(o); }
    if (row.childNodes.length) s.append(row);
    if (arr(p.facts).length) s.append(splitFacts(p.facts, it));
    if (p.note) s.append(el('p', 'muted', p.note));
    if (p.log) s.append(splitLog(p.log, it));
    const dg = p.danger, da = dg && dg.action, dargs = da && da.args || {};
    if (dg && da && da.op === 'addon.act' && VERB.test(String(dargs.verb)) && dargs.target === it.id && dg.confirm && arr(dg.confirm.lines).length) {
      const foot = el('div', 'row between quiet-note'), b = el('button', 'btn danger sm', dg.label); b.type = 'button';
      b.dataset.addonAct = 'true'; b.dataset.verb = String(dargs.verb); b.dataset.target = it.id; b.dataset.label = dg.label;
      b.dataset.confirm = String(dg.confirm.title); b.dataset.confirmLines = arr(dg.confirm.lines).join('\n'); b.dataset.keep = dg.confirm.keep || 'Keep it';
      b.setAttribute('aria-label', dg.label + ' ' + it.title);
      foot.append(el('span', 'meta', dg.note || ''), b); s.append(foot);
    }
    return s;
  }
  function splitQuestion(it) {
    const q = it.question, box = el('div', 'banner attn'), g = el('div', 'grow stack');
    g.setAttribute('role', 'group'); g.setAttribute('aria-label', 'Question about ' + it.title);
    const words = el('div'); words.append(el('strong', '', q.title)); if (q.text) words.append(el('p', 'muted', q.text));
    const row = el('div', 'row');
    arr(q.buttons).forEach((x, i) => { const b = splitButton(x, it, 'btn sm ' + (i === 0 ? 'primary' : x.link ? 'ghost' : 'outline')); if (b) row.append(b); });
    g.append(words, row); box.append(g);
    return box;
  }
  function drawSplit(b) {
    const s = el('section', 'blk blk-above blk-split'), param = splitParam(b);
    s.dataset.splitParam = param;
    const groups = arr(b.groups).map(g => ({...g, items: arr(g.items).filter(it => it && SPLIT_ID.test(String(it.id)) && it.state && typeof it.title === 'string')})).filter(g => g.items.length);
    const all = groups.flatMap(g => g.items);
    if (!all.length) { const c = el('div', 'card'); c.append(b.empty ? emptyState(b.empty) : el('p', 'blk-none', 'Nothing here.')); s.append(c); return s; }
    const asked = all.filter(it => it.question && arr(it.question.buttons).length);
    asked.forEach(it => s.append(splitQuestion(it)));
    const want = splitChosen(param), picked = all.some(it => it.id === want) ? want : null, shown = picked || all[0].id;
    const grid = el('div', 'split-view'); if (picked) grid.dataset.picked = 'true';
    const nav = el('nav', 'split-list focus-list'); nav.setAttribute('aria-label', String(b.title || 'List'));
    for (const g of groups) {
      const h = el('div', 'card-h'); h.append(el('h2', '', g.title), el('span', 'grow'));
      if (g.meta) { const m = el('span', 'meta', g.meta); m.setAttribute('role', 'status'); h.append(m); }
      nav.append(h);
      g.items.forEach(it => nav.append(splitRow(it, it.id === shown, param)));
    }
    grid.append(nav, ...all.map(it => splitPanel(it, it.id === shown, b.title)));
    s.append(grid);
    return s;
  }
  // The page calls this on a click on [data-split-pick]: show that item (or the list again on a phone, id ''), keep the
  // address, move the focus. No re-render, no request.
  function splitPick(section, id) {
    if (!section) return;
    const param = section.dataset.splitParam || 'item', grid = section.querySelector('.split-view');
    const panels = [...section.querySelectorAll('[data-split-panel]')];
    const target = id ? panels.find(p => p.dataset.splitPanel === id) : null;
    if (id && !target) return;
    const base = String(location.hash || '').split('?')[0];
    history.replaceState(null, '', base + (id ? '?' + param + '=' + encodeURIComponent(id) : ''));
    if (target) { panels.forEach(p => { p.hidden = p !== target; }); grid.dataset.picked = 'true'; }
    else delete grid.dataset.picked;
    const on = target ? id : (panels.find(p => !p.hidden) || {}).dataset?.splitPanel;
    section.querySelectorAll('[data-split-row]').forEach(r => {
      const cur = r.dataset.splitRow === on; r.classList.toggle('cur', cur);
      const a = r.querySelector('[data-split-pick]'); if (a) { if (cur) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current'); }
    });
    if (target) target.focus({preventScroll: !matchMedia('(max-width:720px)').matches});
    else section.querySelector('[data-split-row].cur [data-split-pick]')?.focus();
  }
  function splitLogShow(section, id) {
    const l = section && [...section.querySelectorAll('[data-log]')].find(n => n.dataset.log === id);
    if (!l) return;
    const open = !l.classList.contains('log-full');
    if (open) openLogs.add(id); else openLogs.delete(id);
    l.classList.toggle('log-full', open); l.classList.toggle('log-short', !open && l.dataset.long === '1');
    for (const b of section.querySelectorAll('[data-split-log]')) if (b.dataset.splitLog === id) { b.textContent = open ? 'Close log' : 'Open log'; b.setAttribute('aria-label', (open ? 'Close log of ' : 'Open log of ') + (b.getAttribute('aria-label') || '').replace(/^(Open|Close) log of /, '')); }
    l.scrollIntoView({block: 'nearest'}); l.focus({preventScroll: true});
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
    split: drawSplit,
    // Bars per label (e.g. per day), side by side or stacked; each column says its numbers on hover or focus.
    chart(b) {
      const s = el('section', 'blk card blk-chart'), head = blkHead(b); if (head) s.append(head);
      const labels = arr(b.labels), series = arr(b.series).slice(0, 3), n = labels.length;
      const val = (x, i) => { const v = Number(arr(x.values)[i]); return Number.isFinite(v) && v > 0 ? v : 0; };
      const tops = labels.map((_, i) => b.stacked ? series.reduce((a, x) => a + val(x, i), 0) : Math.max(0, ...series.map(x => val(x, i))));
      const top = Math.max(0, ...tops);
      if (!top && b.empty) { s.append(emptyState(b.empty)); return s; }
      const legend = el('div', 'chart-legend');
      for (const x of series) { const k = el('span', 'chart-key c-' + tone(x.tone)); k.append(el('i', 'chart-sw'), String(x.name)); legend.append(k); }
      s.append(legend);
      const max = nice(Math.max(1, top));
      const box = el('div', 'chart' + (n > 16 ? ' dense' : '')); box.setAttribute('role', 'group'); box.setAttribute('aria-label', String(b.title || 'Chart'));
      const axis = el('div', 'chart-axis'); axis.setAttribute('aria-hidden', 'true');
      axis.append(el('span', '', String(max)), el('span', '', String(max / 2)), el('span', '', '0'));
      const plot = el('div', 'chart-plot'), tip = el('div', 'chart-tip'); tip.hidden = true; tip.setAttribute('aria-hidden', 'true');
      labels.forEach((lab, i) => {
        const said = String(lab) + ': ' + series.map(x => x.name + ' ' + val(x, i)).join(', ');
        const col = el('div', 'chart-col'); col.tabIndex = 0; col.setAttribute('role', 'img'); col.setAttribute('aria-label', said);
        const bars = el('div', 'chart-bars' + (b.stacked ? ' stacked' : ''));
        for (const x of (b.stacked ? [...series].reverse() : series)) {
          const bar = el('span', 'chart-bar c-' + tone(x.tone)); bar.style.height = pct(val(x, i), max); bars.append(bar);
        }
        col.append(bars, el('span', 'chart-label' + ((n - 1 - i) % (n > 16 ? 3 : n > 9 ? 2 : 1) ? ' quiet' : ''), lab));
        const show = () => {
          tip.replaceChildren(el('strong', '', lab));
          for (const x of series) { const k = el('span', 'chart-key c-' + tone(x.tone)); k.append(el('i', 'chart-sw'), x.name + ': ' + val(x, i)); tip.append(k); }
          tip.hidden = false;
          const w = tip.offsetWidth || 0, pw = plot.clientWidth || 0, cx = (col.offsetLeft || 0) + (col.offsetWidth || 0) / 2;
          tip.style.left = Math.max(0, Math.min(pw - w, cx - w / 2)) + 'px';
        };
        on(col, 'pointerenter', show); on(col, 'focus', show);
        on(col, 'pointerleave', () => { tip.hidden = true; }); on(col, 'blur', () => { tip.hidden = true; });
        plot.append(col);
      });
      plot.append(tip); box.append(axis, plot); s.append(box);
      return s;
    },
    // Work moving left to right through a few stages (a merge queue: being checked -> in line -> merged lately).
    flow(b) {
      const s = el('section', 'blk card blk-flow'), d = el('div', 'blk-head');
      const title = el('h2', 'blk-title'); title.append(shownLink2(b.link) ? linked('flow-title', b.link, [String(b.title)]) : String(b.title));
      d.append(title); if (b.meta) d.append(el('span', 'meta', b.meta)); s.append(d);
      const row = el('div', 'flow-stages');
      for (const st of arr(b.stages).slice(0, 4)) {
        const box = el('div', 'flow-stage' + (st.active ? ' active' : '') + (st.tone && st.tone !== 'neutral' ? ' t-' + tone(st.tone) : ''));
        const h = el('div', 'flow-head'); h.append(el('span', 'meta', st.label), el('strong', 'flow-value', st.value)); box.append(h);
        if (st.text) box.append(el('span', 'flow-text', st.text));
        const items = arr(st.items);
        if (items.length) {
          const chips = el('div', 'flow-items');
          for (const it of items) {
            const parts = [];
            if (Number.isInteger(it.place)) parts.push(el('span', 'flow-place', String(it.place)));
            parts.push(String(it.label));
            const cls = ['chip', 'flow-chip', st.active && (!it.tone || it.tone === 'neutral') ? 'info' : CHIP_TONE[tone(it.tone)]].filter(Boolean).join(' ');
            const c = shownLink2(it.link) ? linked(cls, it.link, parts) : (() => { const x = el('span', cls); x.append(...parts); return x; })();
            if (it.hint) c.title = String(it.hint);
            chips.append(c);
          }
          if (st.more > 0) chips.append(el('span', 'chip outline flow-chip', '+' + st.more));
          box.append(chips);
        }
        const p = st.progress;
        if (p && Number(p.max) > 0) {
          const bar = el('progress', 'flow-progress'); bar.max = Number(p.max); bar.value = Math.min(Number(p.value) || 0, Number(p.max));
          bar.setAttribute('aria-label', String(p.label)); box.append(bar);
        }
        const bars = arr(st.bars);
        if (bars.length) {
          const most = Math.max(1, ...bars.map(x => Number(x.value) || 0));
          const g = el('div', 'flow-bars'); g.setAttribute('role', 'img'); g.setAttribute('aria-label', String(st.bars_label || st.label));
          for (const x of bars) { const k = el('span', 'flow-bar t-' + tone(x.tone)); k.style.height = pct(Math.max(Number(x.value) || 0, most / 8), most); if (x.hint) k.title = String(x.hint); g.append(k); }
          box.append(g);
        }
        row.append(box);
      }
      s.append(row);
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
      const s = el('section', 'blk blk-above'), strip = el('ol', 'week-strip'), head = blkHead(b);
      if (head) s.append(head);
      const box = el('div', 'blk-card card strip-panel');
      const today = new Date().toDateString();
      const days = arr(b.days).filter(day => parseDate(day.date));
      // A repeat that shows up on several days in a row ("Every 2 hours") is ONE band across those days, not a card per day.
      const bands = [];
      days.forEach((day, i) => {
        for (const it of arr(day.items)) {
          if (!it.every) continue;
          const last = bands.find(x => x.link === it.link && x.every === it.every && x.to === i);
          if (last) last.to = i + 1; else bands.push({link: it.link, every: it.every, title: it.title, full: it.full, tone: it.tone, from: i, to: i + 1});
        }
      });
      const banded = it => it.every && bands.some(x => x.link === it.link && x.every === it.every);
      if (bands.length) {
        const row = el('div', 'week-bands');
        for (const x of bands) {
          const a = linked('run band t-' + tone(x.tone), x.link, [el('time', 'every', x.every), el('span', '', x.title)]);
          if (x.full) a.title = x.full;
          a.style.gridColumn = (x.from + 1) + ' / ' + (x.to + 1);
          row.append(a);
        }
        box.append(row);
      }
      for (const day of days) {
        const d = parseDate(day.date);
        const items = arr(day.items).filter(it => !banded(it));
        const li = el('li', 'day' + (d.toDateString() === today ? ' today' : '') + (items.length ? ' has' : ' empty'));
        const head = el('div', 'day-head'); head.append(el('span', '', d.toLocaleDateString('en-GB', {weekday: 'short'})), el('b', '', d.getDate()));
        li.append(head);
        for (const it of items) {
          const parts = [el('time', '', it.time || ''), el('span', '', it.title)];
          if (it.note) parts.push(el('small', 'run-note', it.note));
          const a = linked('run t-' + tone(it.tone), it.link, parts);
          if (it.full) a.title = it.full;
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
      const s = el('section', 'blk' + (b.filter || b.compact ? ' card' : '')), head = blkHead(b); if (head) s.append(head);
      const wrap = el('div', 'table-wrap'), t = el('table', 'blk-table data-table' + (b.compact ? ' compact' : '')), cols = arr(b.columns);
      const hr = el('tr');
      const rowsList = arr(b.rows), hasActions = rowsList.some(r => arr(r.actions).length), hasToggle = rowsList.some(r => r.toggle);
      // The switch column is named by what it turns on (the add-on's `text`, e.g. Repeats); at phone width the same
      // words sit beside each switch on its card.
      const toggleText = String((rowsList.find(r => r.toggle && r.toggle.text) || {toggle:{}}).toggle.text || 'On');
      for (const c of cols) { const th = el('th', c.type === 'number' || c.type === 'duration' ? 'num' : '', c.label); th.scope = 'col'; hr.append(th); }
      if (hasActions) { const th = el('th', '', 'Actions'); th.scope = 'col'; hr.append(th); }
      if (hasToggle) { const th = el('th', '', toggleText); th.scope = 'col'; hr.append(th); }
      const thead = el('thead'); thead.append(hr); t.append(thead);
      const tb = el('tbody');
      const trs = [];
      // compact: the row's own column (where its link goes) and long text columns end in an ellipsis
      const long = new Set(cols.filter(c => c.type === 'text' && rowsList.some(r => String((r.cells || {})[c.key] ?? '').length > 40)).map(c => c.key));
      for (const r of arr(b.rows)) {
        const tr = el('tr'), links = r.links && typeof r.links === 'object' ? r.links : {}, tones = r.tones && typeof r.tones === 'object' ? r.tones : {};
        // the row's link sits on its first cell that has no link of its own
        const mainKey = (cols.find(c => !(Object.prototype.hasOwnProperty.call(links, c.key) && shownLink2(links[c.key]))) || cols[0] || {}).key;
        cols.forEach((c, i) => {
          const v = (r.cells || {})[c.key];
          const td = cell(c, v); td.dataset.label = c.label || '';
          if (c.type === 'text' && v != null && TONES.includes(tones[c.key])) td.replaceChildren(toneChip(tones[c.key], String(v)));
          if (b.compact && c.type === 'text' && typeof v === 'string') td.title = v;
          const own = Object.prototype.hasOwnProperty.call(links, c.key) ? links[c.key] : null;
          if (own != null && shownLink2(own)) {
            const a = linked(i === 0 ? 'cell-link' : 'cell-ref', own, [...td.childNodes]); td.replaceChildren(a);
          } else if (c.key === mainKey && typeof r.link === 'string' && (TICKET.test(r.link) || HTTPS.test(r.link))) {
            const a = linked('cell-link', r.link, [...td.childNodes]); td.replaceChildren(a);
          }
          if (b.compact && c.key === mainKey) td.className = (td.className + ' cell-main').trim();
          else if (b.compact && long.has(c.key)) td.className = (td.className + ' cell-long').trim();
          if (c.key === mainKey && r.subtitle) td.append(el('span', 'subline', r.subtitle));
          tr.append(td);
        });
        if (hasActions) {
          const td = el('td', 'cell-actions'), box = el('div', 'row');
          for (const a of arr(r.actions)) { const btn = rowButton(a); if (btn) box.append(...openFirst(btn)); }
          td.append(box); tr.append(td);
        }
        if (hasToggle) {
          const td = el('td', 'cell-toggle'), sw = r.toggle ? toggleEl(r.toggle) : null;
          if (sw) { td.dataset.label = toggleText; td.append(sw); }
          tr.append(td);
        }
        tb.append(tr); trs.push([tr, r]);
      }
      t.append(tb);
      // Tabs by one text column (All, then each value with its count) and a fold under All: plain show/hide of rows.
      const fcol = cols.find(c => c.key === b.filter && c.type === 'text');
      const fold = Number.isInteger(b.fold) && b.fold > 0 ? b.fold : 0;
      const foot = el('div', 'blk-table-foot');
      // The page is painted again on every poll and the dashboard keeps the nodes already shown (with the
      // listeners of the first paint), so the handlers read rows and tabs from the live page, never from this
      // paint's records, and the chosen tab and "Show more" outlive a repaint (picked, per table).
      const tkey = `${b.title || ''}|${b.filter || ''}`;
      const mem = picked.get(tkey) || {pick: null, open: false};
      if (fcol) for (const [tr, r] of trs) tr.dataset.f = String((r.cells || {})[fcol.key] ?? '');
      if (mem.pick != null && !trs.some(([tr]) => tr.dataset.f === mem.pick)) mem.pick = null;  // that tab is gone
      const apply = (box, pick, open) => {
        const rows = [...box.querySelectorAll('tbody > tr')];
        let shown = 0;
        for (const tr of rows) {
          const hit = pick == null || tr.dataset.f === pick;
          const fits = hit && (pick != null || open || !fold || shown < fold);
          tr.hidden = !fits; if (fits) shown += 1;
        }
        const left = pick == null && fold && !open ? rows.length - shown : 0;
        const ft = box.querySelector('.blk-table-foot') || foot;
        ft.replaceChildren();
        if (left > 0) {
          const m = el('button', 'btn ghost sm', `Show ${left} more`); m.type = 'button';
          on(m, 'click', () => { const now = picked.get(tkey) || {pick: null, open: false}; now.open = true; picked.set(tkey, now); apply(m.closest('.blk') || box, now.pick, true); });
          ft.append(m);
        }
        ft.hidden = !left;
      };
      if (fcol) {
        const counts = new Map();
        for (const [, r] of trs) { const k = String((r.cells || {})[fcol.key] ?? ''); if (k) counts.set(k, (counts.get(k) || 0) + 1); }
        const tabs = el('div', 'tabs blk-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', String(fcol.label));
        const tab = (label, n, key) => {
          const x = el('button'); x.type = 'button'; x.setAttribute('role', 'tab'); x.setAttribute('aria-selected', key === mem.pick ? 'true' : 'false');
          if (key != null) x.dataset.f = key;
          x.append(String(label), el('sup', '', String(n)));
          on(x, 'click', () => {
            const box = x.closest('.blk') || s, now = picked.get(tkey) || {pick: null, open: false};
            now.pick = 'f' in x.dataset ? x.dataset.f : null; picked.set(tkey, now);
            for (const y of x.parentNode.childNodes) y.setAttribute('aria-selected', y === x ? 'true' : 'false');
            apply(box, now.pick, now.open);
          });
          return x;
        };
        tabs.append(tab('All', trs.length, null));
        for (const [k, n] of counts) tabs.append(tab(k, n, k));
        s.append(tabs);
      }
      wrap.append(t); s.append(wrap);
      if (fold || mem.pick != null) { s.append(foot); apply(s, mem.pick, mem.open); }
      if (!fold) foot.hidden = true;
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
      if ((b.type === 'list' || b.type === 'chart') && b.span === 'half') {   // two half blocks side by side
        if (!pair || pair.childNodes.length >= 2) { pair = el('div', 'blk-pair'); root.append(pair); }
        pair.append(node); continue;
      }
      pair = null;
      root.append(node);
    }
    return root;
  }
  const appHash = to => typeof to === 'string' && APP.test(to) ? '#' + to.slice(4) : null;
  return {render, duration, appHash, splitPick, splitLogShow};
})();
if (typeof module !== 'undefined') module.exports = OrchBlocks;

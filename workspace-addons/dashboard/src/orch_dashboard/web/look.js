'use strict';
// Workspace look: the badge (icon or letter on a colour), the Settings > General picker (categories + recent),
// the description row (a proposal the owner approves), the "shared pages" switch and the favicon.
// Data: state.look from the server (orch look show / status / profile); the 100 icons and 12 colours in look-icons.js.
// Everything is built with createElement and textContent: a workspace name is never put into markup.
(() => {
  const D = window.OrchLookData;
  if (!D) return;
  const COLORS = D.colors, BYID = Object.fromEntries(COLORS.map(c => [c.id, c]));
  const RECENT_KEY = 'orch.look.recent';
  const SVGNS = 'http://www.w3.org/2000/svg';
  const EXTRA = {finance: ['wallet', 'savings', 'cash', 'bank', 'receipt', 'growth', 'calculator'], bills: ['receipt'], taxes: ['bank', 'legal'], budget: ['savings', 'calculator']};

  let look = null, name = 'Workspace';
  let open = false, draft = {icon: null, color: null}, cat = null, light = false;
  let editing = false, descDraft = '', busy = false, status = '', statusTone = 'ok';

  const clean = v => String(v == null ? '' : v).normalize('NFC').trim();
  function hash(text) {
    let h = 5381;
    for (const b of new TextEncoder().encode(clean(text))) h = (Math.imul(h, 33) + b) >>> 0;
    return h;
  }
  const defaultColor = text => COLORS[hash(text) % COLORS.length].id;
  function letter(text) {
    const c = Array.from(clean(text)).find(ch => /[\p{L}\p{N}]/u.test(ch));
    if (!c) return '?';
    const u = c.toUpperCase();
    return Array.from(u).length === 1 ? u : c;
  }
  const resolve = (l, text) => ({icon: l && D.icons[l.icon] ? l.icon : null, color: l && BYID[l.color] ? l.color : defaultColor(text)});

  function n(tag, attrs = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'className') node.className = v;
      else if (k === 'disabled' || k === 'hidden') node[k] = !!v;
      else node.setAttribute(k, v === true ? '' : String(v));
    }
    node.append(...kids.flat().filter(x => x != null && x !== false));
    return node;
  }

  const parsed = {};
  function svgIcon(id, px) {
    const i = D.icons[id];
    if (!i) return null;
    if (!parsed[id]) {
      const doc = new DOMParser().parseFromString(`<svg xmlns="${SVGNS}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${i.b}</svg>`, 'image/svg+xml');
      parsed[id] = doc.documentElement;
    }
    const s = document.importNode(parsed[id], true);
    s.setAttribute('width', px); s.setAttribute('height', px);
    return s;
  }

  // A badge: tinted rounded square with the icon, or the first letter of the name, in the colour.
  function badge(l, text, size = 32, opts = {}) {
    const r = resolve(l, text);
    const node = n('span', {className: 'wsb s' + size + (opts.light ? ' light' : ''), 'data-c': r.color, role: 'img', 'aria-label': clean(text)});
    if (r.icon) node.append(svgIcon(r.icon, Math.round(size * (size <= 20 ? 0.75 : 0.52))));
    else node.append(n('b', {}, letter(text)));
    return node;
  }

  // ---- favicon: the same badge as a small SVG
  const mix = (hex, pct) => {
    const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)), bg = [0x15, 0x18, 0x1d];
    return '#' + c.map((v, i) => Math.round(v * pct + bg[i] * (1 - pct)).toString(16).padStart(2, '0')).join('');
  };
  const xml = t => t.replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
  function faviconHref(l, text) {
    const r = resolve(l, text), tone = BYID[r.color].dark;
    const glyph = r.icon
      ? `<g transform="translate(5 5) scale(.917)" fill="none" stroke="${tone}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${D.icons[r.icon].b}</g>`
      : `<text x="16" y="23" text-anchor="middle" font-family="system-ui,sans-serif" font-weight="700" font-size="20" fill="${tone}">${xml(letter(text))}</text>`;
    const svg = `<svg xmlns="${SVGNS}" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="${mix(tone, 0.18)}"/>${glyph}</svg>`;
    return 'data:image/svg+xml,' + encodeURIComponent(svg);
  }
  function paintFavicon() {
    const link = document.querySelector('link[rel="icon"]');
    if (look && link) {
      link.setAttribute('href', faviconHref(look, name));
      document.title = clean(name) + ' · orch';
    }
  }

  // ---- recent icons (kept in this browser)
  const recent = () => { try { const v = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); return Array.isArray(v) ? v.filter(i => D.icons[i]).slice(0, 8) : []; } catch (_) { return []; } };
  const remember = id => { if (!id) return; try { localStorage.setItem(RECENT_KEY, JSON.stringify([id, ...recent().filter(i => i !== id)].slice(0, 8))); } catch (_) { /* no storage */ } };

  function suggested() {
    const words = (clean(name) + ' ' + clean(look && look.description)).toLowerCase().match(/[a-z]{3,}/g) || [];
    const out = new Set();
    words.forEach(w => (EXTRA[w] || []).forEach(i => D.icons[i] && out.add(i)));
    Object.entries(D.icons).forEach(([id, i]) => { if (words.some(w => (i.l + ' ' + i.k).toLowerCase().split(' ').includes(w))) out.add(id); });
    return [...out].slice(0, 7);
  }

  const lookText = l => {
    const r = resolve(l, name), set = l && BYID[l.color];
    return (r.icon ? D.icons[r.icon].l : 'First letter') + ' · ' + (set ? set.label : 'Automatic colour');
  };

  function tab(key, label) {
    return n('button', {type: 'button', role: 'tab', className: 'lk-chip', 'data-lk': 'cat', 'data-v': key, 'data-key': 'lk-cat-' + key, 'aria-pressed': String(cat === key)}, label);
  }
  function tile(id) {
    const label = id ? D.icons[id].l : 'First letter';
    return n('button', {type: 'button', className: 'lk-tile', 'data-lk': 'icon', 'data-v': id || '', 'data-key': 'lk-icon-' + (id || 'none'), title: label, 'aria-pressed': String((draft.icon || null) === id)},
      id ? svgIcon(id, 20) : n('b', {}, letter(name)), n('span', {}, label));
  }

  function picker() {
    const rec = recent();
    if (!cat || (cat === 'recent' && !rec.length)) cat = rec.length ? 'recent' : 'suggested';
    const cats = [...(rec.length ? [['recent', 'Recent']] : []), ['suggested', 'Suggested'], ...D.categories.map(c => [c.id, c.label])];
    const ids = cat === 'recent' ? rec : cat === 'suggested' ? suggested() : Object.keys(D.icons).filter(i => D.icons[i].c === cat);
    const tone = draft.color || defaultColor(name);
    const swatches = [n('button', {type: 'button', className: 'lk-sw auto', 'data-lk': 'color', 'data-v': '', 'data-key': 'lk-color-auto', title: 'Automatic', 'aria-label': 'Automatic colour', 'aria-pressed': String(!draft.color)})]
      .concat(COLORS.map(c => n('button', {type: 'button', className: 'lk-sw', 'data-c': c.id, 'data-lk': 'color', 'data-v': c.id, 'data-key': 'lk-color-' + c.id, title: c.label, 'aria-label': c.label, 'aria-pressed': String(draft.color === c.id)})));
    const changed = (draft.icon || null) !== (look.icon || null) || (draft.color || null) !== (look.color || null);
    const prev = (size, label, shape) => n('div', {className: 'lk-pv-row'}, badge(draft, name, size, {light}), n('div', {}, n('b', {}, clean(name)), n('div', {className: 'meta'}, label)));
    return n('div', {className: 'lk-picker', 'data-key': 'lk-picker', 'data-c': tone},
      n('div', {},
        n('p', {className: 'meta'}, 'Icon'),
        n('div', {className: 'lk-chips', role: 'tablist', 'aria-label': 'Icon groups'}, cats.map(([k, l]) => tab(k, l))),
        n('div', {className: 'lk-grid', 'data-key': 'lk-grid'}, cat === 'suggested' || cat === 'recent' ? tile(null) : null, ids.map(tile)),
        n('p', {className: 'meta lk-colour-label'}, 'Colour · ', n('b', {}, draft.color ? BYID[draft.color].label : 'Automatic')),
        n('div', {className: 'lk-swatches', role: 'group', 'aria-label': 'Colour'}, swatches)),
      n('div', {className: 'lk-preview' + (light ? ' light' : ''), 'aria-live': 'polite'},
        n('div', {className: 'lk-pv-head'}, n('p', {className: 'eyebrow grow'}, 'How it looks'),
          n('button', {type: 'button', className: 'btn ghost sm', 'data-lk': 'light', 'data-key': 'lk-light'}, light ? 'Dark' : 'Light')),
        prev(32, 'Dashboard and shared pages'), prev(46, 'Phone'), prev(16, 'Browser tab, real size')),
      n('div', {className: 'lk-foot'},
        n('span', {className: 'meta grow'}, 'Shown in the dashboard, on your phone and on shared pages.'),
        n('button', {type: 'button', className: 'btn ghost sm', 'data-lk': 'cancel', 'data-key': 'lk-cancel'}, 'Cancel'),
        n('button', {type: 'button', className: 'btn primary sm', 'data-lk': 'save', 'data-key': 'lk-save', disabled: !changed || busy}, 'Save')));
  }

  function descriptionRow() {
    const svc = look.service;
    const body = editing
      ? n('div', {className: 'grow lk-desc-edit'},
          n('input', {className: 'input', type: 'text', maxlength: 280, 'data-key': 'lk-desc-input', 'data-lk-input': 'desc', 'aria-label': 'Description', value: descDraft}),
          n('div', {className: 'lk-desc-actions'},
            n('button', {type: 'button', className: 'btn primary sm', 'data-lk': 'desc-save', 'data-key': 'lk-desc-save', disabled: busy}, 'Send for approval'),
            n('button', {type: 'button', className: 'btn ghost sm', 'data-lk': 'desc-cancel', 'data-key': 'lk-desc-cancel'}, 'Cancel')))
      : n('div', {className: 'grow'},
          n('p', {className: 'set-ctl'}, look.description || (svc ? 'Not set' : '')),
          look.pending != null ? n('p', {className: 'meta lk-pending', 'data-testid': 'look-pending'}, 'Waiting for approval: “' + look.pending + '”') : null,
          !svc ? n('p', {className: 'meta'}, 'A short line about this workspace, shown on your phone and on pages you share. You can write one once your phone or page sharing is turned on under Add-ons.') : null);
    return n('div', {className: 'card-row', 'data-key': 'lk-desc-row'}, n('span', {className: 'set-label'}, 'Description'), body,
      !editing && svc ? n('button', {type: 'button', className: 'btn sm', 'data-lk': 'desc-edit', 'data-key': 'lk-desc-edit'}, 'Edit') : null);
  }

  function section() {
    if (!look) return null;
    const on = look.shared_pages !== false;
    const set = look.icon || look.color;
    return n('div', {className: 'stack', 'data-key': 'settings-look', 'data-testid': 'settings-look'},
      n('h2', {className: 'set-sub'}, 'Workspace look'),
      n('div', {className: 'card'},
        n('div', {className: 'card-row', 'data-key': 'lk-look-row'}, n('span', {className: 'set-label'}, 'Icon and colour'),
          n('div', {className: 'grow lk-current'}, badge(look, name, 32), n('span', {className: 'meta'}, lookText(look))),
          open ? null : n('button', {type: 'button', className: 'btn sm', 'data-lk': 'open', 'data-key': 'lk-open', 'data-testid': 'look-change'}, 'Change')),
        open ? picker() : null,
        descriptionRow(),
        // Like every other switch row: the words left, the switch right, one row at any width.
        n('div', {className: 'card-row lk-shared-row', 'data-key': 'lk-shared-row'},
          n('div', {className: 'grow'}, n('h3', {}, 'Shared pages: show workspace name and icon'),
            n('p', {className: 'meta'}, 'On files you share with a link. Turn off to show nothing.')),
          n('button', {type: 'button', className: 'switch', role: 'switch', 'aria-checked': String(on), 'aria-label': 'Show workspace name and icon on shared pages', 'data-lk': 'shared', 'data-key': 'lk-shared', 'data-testid': 'look-shared-pages', disabled: busy}))),
      status ? n('p', {className: 'meta lk-status ' + statusTone, role: 'status', 'data-key': 'lk-status'}, status) : null,
      set === null && look.set_by === null ? n('p', {className: 'meta'}, 'Nobody has picked an icon yet. A helper can pick one for you, or press Change.') : null);
  }

  function repaint() {
    const host = document.querySelector('[data-key="settings-look"]');
    if (!host) return;
    const a = document.activeElement, key = a && a.dataset ? a.dataset.key : null;
    const keep = host.contains(a) && a.matches('input') ? [a.selectionStart, a.selectionEnd] : null;
    const next = section();
    host.replaceChildren(...(next ? [...next.childNodes] : []));
    if (key) {
      const again = [...host.querySelectorAll('[data-key]')].find(x => x.dataset.key === key);
      if (again && !again.disabled) { again.focus({preventScroll: true}); if (keep && again.setSelectionRange) again.setSelectionRange(...keep); }
    }
    window.dispatchEvent(new CustomEvent('orch:look-painted'));
  }

  async function run(op, args) {
    if (busy || typeof window.orchAct !== 'function') return null;
    busy = true; repaint();
    const r = await window.orchAct(op, args);
    busy = false;
    if (!r.ok) { status = r.text || 'That did not work.'; statusTone = 'bad'; window.orch?.toast(status, 'error'); }
    repaint();
    return r;
  }

  document.addEventListener('input', e => {
    if (e.target.matches('[data-lk-input="desc"]')) descDraft = e.target.value;
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && editing && e.target.matches('[data-lk-input="desc"]')) { editing = false; repaint(); }
    if (e.key === 'Enter' && e.target.matches('[data-lk-input="desc"]')) { e.preventDefault(); document.querySelector('[data-lk="desc-save"]')?.click(); }
  });
  document.addEventListener('click', async e => {
    const t = e.target.closest('[data-lk]');
    if (!t || !look || t.disabled) return;
    const v = t.dataset.v;
    switch (t.dataset.lk) {
      case 'open': open = true; draft = {icon: look.icon || null, color: look.color || null}; cat = null; status = ''; repaint(); break;
      case 'cancel': open = false; repaint(); break;
      case 'icon': draft.icon = v || null; repaint(); break;
      case 'color': draft.color = v || null; repaint(); break;
      case 'cat': cat = v; repaint(); break;
      case 'light': light = !light; repaint(); break;
      case 'save': {
        const r = await run('look.set', {icon: draft.icon, color: draft.color});
        if (r && r.ok) { remember(draft.icon); Object.assign(look, {icon: draft.icon, color: draft.color, set_by: 'human'}); open = false; status = 'Saved. Your phone and shared pages show it at their next refresh.'; statusTone = 'ok'; paintFavicon(); repaint(); window.dispatchEvent(new CustomEvent('orch:look-saved')); }
        break;
      }
      case 'desc-edit': editing = true; descDraft = look.description || ''; status = ''; repaint(); document.querySelector('[data-key="lk-desc-input"]')?.focus(); break;
      case 'desc-cancel': editing = false; repaint(); break;
      case 'desc-save': {
        const r = await run('look.description', {service: look.service, text: descDraft});
        if (r && r.ok) { editing = false; look.pending = descDraft.trim(); status = 'Sent. It changes when you approve it in the ' + look.service + ' admin page.'; statusTone = 'ok'; repaint(); }
        break;
      }
      case 'shared': {
        const want = look.shared_pages === false;
        const r = await run('look.shared', {on: want});
        if (r && r.ok) { look.shared_pages = want; status = want ? 'Shared pages show the workspace name and icon.' : 'Shared pages no longer show the workspace name and icon.'; statusTone = 'ok'; repaint(); }
        break;
      }
    }
  });

  window.addEventListener('orch:state', e => {
    look = e.detail && e.detail.look ? e.detail.look : null;
    name = clean(e.detail && e.detail.workspace) || 'Workspace';
    if (look) {
      if (!open) draft = {icon: look.icon || null, color: look.color || null};
      paintFavicon();
    }
    if (look && !e.detail.__lookKeep) repaint();
  });

  window.OrchLook = {
    badge, resolve, defaultColor, letter, faviconHref,
    current: () => look, name: () => name,
    settingsSection: () => section(),
  };
})();

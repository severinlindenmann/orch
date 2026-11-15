'use strict';
// Workspace look: the badge (icon or letter on a colour), the Settings > General picker (categories + recent),
// the Workspace profile card (name, one description, tags, icon and colour, relay state), the "shared pages" switch and the favicon.
// Data: state.look from the server (orch look show / status / profile); the 100 icons and 12 colours in look-icons.js.
// Everything is built with createElement and textContent: a workspace name is never put into markup.
(() => {
  const D = window.OrchLookData;
  if (!D) return;
  const COLORS = D.colors, BYID = Object.fromEntries(COLORS.map(c => [c.id, c]));
  const RECENT_KEY = 'orch.look.recent';
  const SVGNS = 'http://www.w3.org/2000/svg';
  const EXTRA = {finance: ['wallet', 'savings', 'cash', 'bank', 'receipt', 'growth', 'calculator'], bills: ['receipt'], taxes: ['bank', 'legal'], budget: ['savings', 'calculator']};

  let look = null, name = 'Workspace', owner = null;
  let open = false, more = false, short = [], draft = {icon: null, color: null}, cat = null, light = false;
  let editing = false, pd = {name: '', description: '', tags: [], tag: ''}, ws = {name: '', description: ''}, busy = false, status = '', statusTone = 'ok';

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

  // The first 12 icons: the current choice, recent ones, suggested ones, then the rest in order.
  // Taken once when the picker opens so tiles never move under the pointer.
  function firstIcons() {
    return [...new Set([draft.icon, look.icon, ...recent(), ...suggested(), ...Object.keys(D.icons)].filter(i => i && D.icons[i]))].slice(0, 12);
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
    const prev = (size, label) => n('div', {className: 'lk-pv-row'}, badge(draft, name, size, {light}), n('div', {}, n('b', {}, clean(name)), n('div', {className: 'meta'}, label)));
    const icons = more
      ? [n('div', {className: 'lk-chips', role: 'tablist', 'aria-label': 'Icon groups'}, cats.map(([k, l]) => tab(k, l))),
        n('div', {className: 'lk-grid', 'data-key': 'lk-grid'}, cat === 'suggested' || cat === 'recent' ? tile(null) : null, ids.map(tile))]
      : [n('div', {className: 'lk-grid', 'data-key': 'lk-grid'}, tile(null), short.map(tile))];
    return n('div', {className: 'lk-picker', 'data-key': 'lk-picker', 'data-c': tone},
      n('div', {},
        n('p', {className: 'meta'}, 'Icon'),
        icons,
        n('button', {type: 'button', className: 'btn ghost sm', 'data-lk': 'more', 'data-key': 'lk-more', 'aria-expanded': String(more)}, more ? 'Fewer icons' : 'More icons'),
        n('p', {className: 'meta lk-colour-label'}, 'Colour · ', n('b', {}, draft.color ? BYID[draft.color].label : 'Automatic')),
        n('div', {className: 'lk-swatches', role: 'group', 'aria-label': 'Colour'}, swatches)),
      n('div', {className: 'lk-preview' + (light ? ' light' : ''), 'aria-live': 'polite'},
        n('div', {className: 'lk-pv-head'}, n('p', {className: 'eyebrow grow'}, 'How it looks'),
          n('button', {type: 'button', className: 'btn ghost sm', 'data-lk': 'light', 'data-key': 'lk-light'}, light ? 'Dark' : 'Light')),
        prev(32, 'In the dashboard, on your phone and on shared pages')),
      n('div', {className: 'lk-foot'},
        n('span', {className: 'meta grow'}, 'Shown in the dashboard, on your phone and on shared pages.'),
        n('button', {type: 'button', className: 'btn ghost sm', 'data-lk': 'cancel', 'data-key': 'lk-cancel'}, 'Cancel'),
        n('button', {type: 'button', className: 'btn primary sm', 'data-lk': 'save', 'data-key': 'lk-save', disabled: !changed || busy}, 'Save')));
  }

  // ---- Workspace profile card: name, one description, tags, icon and colour, and (relay on) its state there.
  const TAGMAX = 4;
  const tagClean = t => clean(t).toLowerCase().replace(/[\s_]+/g, '-').replace(/[^a-z0-9-]/g, '').replace(/^-+|-+$/g, '').slice(0, 24);
  const shownDescription = () => ws.description || (look && look.description) || '';
  function addTag() {
    const t = tagClean(pd.tag);
    pd.tag = '';
    if (t && !pd.tags.includes(t) && pd.tags.length < TAGMAX) pd.tags = [...pd.tags, t];
  }
  function profileRow(label, view, edit, key) {
    return n('div', {className: 'card-row name-row', 'data-key': 'pf-' + key + '-row'}, n('span', {className: 'set-label'}, label), editing && edit ? n('div', {className: 'grow set-ctl lk-desc-edit'}, edit) : n('div', {className: 'grow set-ctl'}, view));
  }
  function chips(tags, removable) {
    return n('div', {className: 'lk-tags', 'data-key': 'pf-tags'}, tags.map(t => n('span', {className: 'chip'}, t, removable ? n('button', {type: 'button', className: 'lk-tag-x', 'data-lk': 'tag-del', 'data-v': t, 'aria-label': 'Remove ' + t}, '×') : null)));
  }
  function relayRow() {
    const svc = look.service;
    if (!svc) return null;
    const where = svc === 'publish' ? 'publish' : 'relay';
    const pend = look.waiting;
    return n('div', {className: 'card-row', 'data-key': 'pf-relay-row'}, n('span', {className: 'set-label'}, 'On the ' + where),
      n('div', {className: 'grow'},
        look.relay_name ? n('p', {className: 'set-ctl', 'data-testid': 'profile-relay-name'}, 'Name on ' + where + ': ' + look.relay_name + ' — set by the ' + where + ' owner') : null,
        n('p', {className: 'meta lk-pending', 'data-testid': 'profile-relay-state'}, pend ? 'Waiting for ' + where + ' approval' : 'Live on ' + where),
        pend && look.pending != null ? n('p', {className: 'meta'}, 'Proposed: “' + look.pending + '”') : null,
        pend && look.pending_tags ? n('p', {className: 'meta'}, 'Proposed tags: ' + look.pending_tags.join(', ')) : null));
  }
  function profileCard() {
    if (!look) return null;
    const svc = look.service;
    const tagsNow = look.tags || [];
    const foot = editing ? n('div', {className: 'card-row'}, n('div', {className: 'grow'}), n('button', {type: 'button', className: 'btn ghost sm', 'data-lk': 'pf-cancel', 'data-key': 'pf-cancel'}, 'Cancel'),
      n('button', {type: 'button', className: 'btn primary sm', 'data-lk': 'pf-save', 'data-key': 'pf-save', disabled: busy}, svc ? 'Save and send' : 'Save')) : null;
    return n('div', {className: 'stack', 'data-key': 'settings-profile', 'data-testid': 'settings-profile'},
      n('h2', {className: 'set-sub'}, 'Workspace profile'),
      n('div', {className: 'card'},
        profileRow('Name', n('div', {className: 'row'}, n('p', {className: 'grow', 'data-key': 'pf-name-value'}, ws.name || name),
          n('button', {type: 'button', className: 'btn sm', 'data-lk': 'pf-edit', 'data-key': 'pf-edit'}, 'Edit')),
        [n('input', {className: 'input', type: 'text', maxlength: 60, 'data-key': 'pf-name', 'data-lk-input': 'name', 'aria-label': 'Name', value: pd.name, placeholder: name}),
          n('p', {className: 'meta'}, 'The name shown for this workspace. Your folder keeps its own name.')], 'name'),
        profileRow('Description', n('p', {className: shownDescription() ? '' : 'meta', 'data-key': 'pf-description-value'}, shownDescription() || 'Not set'),
          [n('input', {className: 'input', type: 'text', maxlength: 280, 'data-key': 'pf-description', 'data-lk-input': 'description', 'aria-label': 'Description', value: pd.description, placeholder: 'For example: our website and newsletter'}),
            n('p', {className: 'meta'}, 'One short line about what this workspace is for.' + (svc ? ' It is sent to the ' + (svc === 'publish' ? 'publish' : 'relay') + ' too, for your phone and shared pages.' : ''))], 'description'),
        svc ? profileRow('Tags', tagsNow.length ? chips(tagsNow, false) : n('p', {className: 'meta'}, 'None'),
          [chips(pd.tags, true), pd.tags.length < TAGMAX ? n('div', {className: 'row'}, n('input', {className: 'input', type: 'text', maxlength: 24, 'data-key': 'pf-tag', 'data-lk-input': 'tag', 'aria-label': 'New tag', value: pd.tag, placeholder: 'tag'}),
            n('button', {type: 'button', className: 'btn sm', 'data-lk': 'tag-add', 'data-key': 'pf-tag-add'}, 'Add')) : null,
            n('p', {className: 'meta'}, 'Two to four short words, so others find this workspace. Lowercase letters, digits and hyphens.')], 'tags') : null,
        foot,
        n('div', {className: 'card-row', 'data-key': 'lk-look-row'}, n('span', {className: 'set-label'}, 'Icon and colour'),
          n('div', {className: 'grow lk-current'}, badge(open ? draft : look, name, 32), n('span', {className: 'meta', 'data-testid': 'look-summary'}, lookText(open ? draft : look))),
          open ? null : n('button', {type: 'button', className: 'btn sm', 'data-lk': 'open', 'data-key': 'lk-open', 'data-testid': 'look-change'}, 'Change')),
        open ? picker() : null,
        relayRow()),
      status ? n('p', {className: 'meta lk-status ' + statusTone, role: 'status', 'data-key': 'lk-status'}, status) : null,
      !open && !(look.icon || look.color) && look.set_by == null ? n('p', {className: 'meta'}, 'Nobody has picked an icon yet. A helper can pick one for you, or press Change.') : null);
  }

  async function saveProfile() {
    const svc = look.service, sent = [];
    const name2 = clean(pd.name), desc2 = clean(pd.description);
    if (name2 !== clean(ws.name) && (name2 || ws.name)) {
      const r = await run('workspace.set', {field: 'name', text: name2});
      if (!r || !r.ok) return;
      ws.name = name2;
    }
    const descChanged = desc2 !== clean(shownDescription());
    if (desc2 !== clean(ws.description)) {
      const r = await run('workspace.set', {field: 'description', text: desc2});
      if (!r || !r.ok) return;
      ws.description = desc2;
    }
    if (svc) {
      const body = {service: svc};
      if (descChanged) body.description = desc2;
      if (pd.tags.join(',') !== (look.tags || []).join(',')) body.tags = pd.tags;
      if (body.description != null || body.tags) {
        const r = await run('look.profile', body);
        if (!r || !r.ok) return;
        if (body.description != null) look.pending = desc2;
        if (body.tags) look.pending_tags = body.tags;
        look.waiting = true;
        sent.push(svc === 'publish' ? 'publish' : 'relay');
      }
    }
    editing = false;
    status = sent.length ? 'Saved. Sent to the ' + sent[0] + ' for approval; it goes live when the owner approves.' : 'Saved.';
    statusTone = 'ok';
    repaint();
  }

  // Who owns this workspace: the person chosen in "You: ..." (switch person). Shown here only; it is not sent to other workspaces.
  function ownerRow() {
    return n('div', {className: 'card-row', 'data-key': 'lk-owner-row'}, n('span', {className: 'set-label'}, 'Owner'),
      n('div', {className: 'grow'},
        n('p', {className: 'set-ctl', 'data-testid': 'look-owner'}, owner || 'Not set'),
        n('p', {className: 'meta'}, owner ? 'Taken from “You” in the sidebar. Only you see it here; it is not sent to other workspaces.' : 'Choose your name under “You” in the sidebar. Only you see it here; it is not sent to other workspaces.')));
  }

  function section() {
    if (!look) return null;
    const on = look.shared_pages !== false;
    return n('div', {className: 'stack', 'data-key': 'settings-look', 'data-testid': 'settings-look'},
      n('h2', {className: 'set-sub'}, 'Shared pages'),
      n('div', {className: 'card'},
        ownerRow(),
        // Like every other switch row: the words left, the switch right, one row at any width.
        n('div', {className: 'card-row lk-shared-row', 'data-key': 'lk-shared-row'},
          n('div', {className: 'grow'}, n('h3', {}, 'Shared pages: show workspace name and icon'),
            n('p', {className: 'meta'}, 'On files you share with a link. Turn off to show nothing.')),
          n('button', {type: 'button', className: 'switch', role: 'switch', 'aria-checked': String(on), 'aria-label': 'Show workspace name and icon on shared pages', 'data-lk': 'shared', 'data-key': 'lk-shared', 'data-testid': 'look-shared-pages', disabled: busy}))),
      null);
  }

  function repaint() {
    for (const [sel, make] of [['settings-look', section], ['settings-profile', profileCard]]) {
      const host = document.querySelector('[data-key="' + sel + '"]');
      if (!host) continue;
      const a = document.activeElement, key = a && a.dataset ? a.dataset.key : null;
      const keep = host.contains(a) && a.matches('input') ? [a.selectionStart, a.selectionEnd] : null;
      const next = make();
      host.replaceChildren(...(next ? [...next.childNodes] : []));
      if (key) {
        const again = [...host.querySelectorAll('[data-key]')].find(x => x.dataset.key === key);
        if (again && !again.disabled) { again.focus({preventScroll: true}); if (keep && again.setSelectionRange) again.setSelectionRange(...keep); }
      }
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
    const k = e.target.dataset && e.target.dataset.lkInput;
    if (k) pd[k] = e.target.value;
  });
  document.addEventListener('keydown', e => {
    const k = e.target.dataset && e.target.dataset.lkInput;
    if (!k) return;
    if (e.key === 'Escape' && editing) { editing = false; repaint(); }
    if (e.key === 'Enter') { e.preventDefault(); if (k === 'tag') { addTag(); repaint(); document.querySelector('[data-key="pf-tag"]')?.focus(); } else document.querySelector('[data-lk="pf-save"]')?.click(); }
  });
  document.addEventListener('click', async e => {
    const t = e.target.closest('[data-lk]');
    if (!t || !look || t.disabled) return;
    const v = t.dataset.v;
    switch (t.dataset.lk) {
      case 'open': open = true; more = false; draft = {icon: look.icon || null, color: look.color || null}; short = firstIcons(); cat = null; status = ''; repaint(); break;
      case 'cancel': open = false; repaint(); break;
      case 'icon': draft.icon = v || null; if (draft.icon && !short.includes(draft.icon)) short = [draft.icon, ...short].slice(0, 12); repaint(); break;
      case 'color': draft.color = v || null; repaint(); break;
      case 'cat': cat = v; repaint(); break;
      case 'more': more = !more; repaint(); break;
      case 'light': light = !light; repaint(); break;
      case 'save': {
        const r = await run('look.set', {icon: draft.icon, color: draft.color});
        if (r && r.ok) { remember(draft.icon); Object.assign(look, {icon: draft.icon, color: draft.color, set_by: 'human'}); open = false; status = 'Saved. Your phone and shared pages show it at their next refresh.'; statusTone = 'ok'; paintFavicon(); repaint(); window.dispatchEvent(new CustomEvent('orch:look-saved')); }
        break;
      }
      case 'pf-edit': editing = true; pd = {name: ws.name || name, description: shownDescription(), tags: [...(look.tags || [])], tag: ''}; status = ''; repaint(); document.querySelector('[data-key="pf-name"]')?.focus(); break;
      case 'pf-cancel': editing = false; repaint(); break;
      case 'tag-add': addTag(); repaint(); document.querySelector('[data-key="pf-tag"]')?.focus(); break;
      case 'tag-del': pd.tags = pd.tags.filter(x => x !== v); repaint(); break;
      case 'pf-save': await saveProfile(); break;
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
    if (!editing) ws = {name: clean(e.detail && e.detail.settings && e.detail.settings.ws_name), description: clean(e.detail && e.detail.settings && e.detail.settings.ws_description)};
    owner = clean(e.detail && e.detail.people && e.detail.people.me) || null;
    if (look) {
      if (!open) draft = {icon: look.icon || null, color: look.color || null};
      paintFavicon();
    }
    if (look && !e.detail.__lookKeep) repaint();
  });

  window.OrchLook = {
    badge, resolve, defaultColor, letter, faviconHref,
    current: () => look, name: () => name,
    settingsSection: () => section(), profileCard: () => profileCard(),
  };
})();

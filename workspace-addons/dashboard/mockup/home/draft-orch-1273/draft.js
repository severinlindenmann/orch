'use strict';
// ORCH-1273 drafts: the workspace switcher with "Saved places". One script for the three drafts; the body's
// data-draft (a, b or c) picks the layout. Mock data only: nothing is stored and no row really opens a page.
// Draft A: everything in the one menu, one step at a time. Draft B: a short menu for switching, a sheet for managing.
// Draft C: one panel with a find field, relay and publish as two tiles, the workspaces as a list.
(() => {
  const V = document.body.dataset.draft;
  const UI = window.UI;
  const params = new URLSearchParams(location.search);
  const state = params.get('state') || 'menu';
  const shots = params.get('shots') === '1';
  const phone = () => matchMedia('(max-width:720px)').matches;
  const $ = s => document.querySelector(s);

  // ---------- small builders ----------
  const h = (tag, attrs = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'className') node.className = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? '' : String(v));
    }
    node.append(...kids.flat(Infinity).filter(x => x != null && x !== false));
    return node;
  };
  const ICONS = {
    relay: 'M4 12h16M8 8l-4 4 4 4m8-8 4 4-4 4',
    publish: 'M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1',
    plus: 'M12 5v14M5 12h14',
    share: 'M4 13v6h16v-6M12 15V3m-4 4 4-4 4 4',
    back: 'm14 6-6 6 6 6',
    next: 'm10 6 6 6-6 6',
    updown: 'm7 15 5 5 5-5M7 9l5-5 5 5',
  };
  const icon = (name, size = 16) => {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [k, v] of [['viewBox', '0 0 24 24'], ['width', size], ['height', size], ['fill', 'none'], ['stroke', 'currentColor'],
      ['stroke-width', '2'], ['stroke-linecap', 'round'], ['stroke-linejoin', 'round'], ['aria-hidden', 'true']]) s.setAttribute(k, v);
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', ICONS[name]);
    s.append(p);
    return s;
  };
  const KIND = {workspace: 'Workspace', relay: 'Relay', publish: 'Publish'};
  const badge = (p, size = 32) => {
    const b = h('span', {className: 'wsb s' + size, role: 'img', 'aria-label': p.kind && p.kind !== 'workspace' ? KIND[p.kind] : p.name},
      p.kind === 'relay' || p.kind === 'publish' ? icon(p.kind, size > 26 ? 16 : 14) : h('b', {}, p.name.slice(0, 1).toUpperCase()));
    b.style.setProperty('--c', 'var(--' + p.c + ')');
    return b;
  };

  // ---------- mock data ----------
  const LOCAL = [
    {id: 'orch', name: 'Orch development', c: 'brand', here: true, url: 'https://ws-orch.internal.severin.io', line: 'Current'},
    {id: 'mkt', name: 'Marketing', c: 'chart-4', off: true, line: 'Not running'},
  ];
  const SAVED = [
    {id: 'nb', name: 'Notebook', kind: 'workspace', url: 'http://127.0.0.1:64381', c: 'info', line: 'Only in this browser', local: true, rank: 1},
    {id: 'fs', name: 'Fernscout', kind: 'workspace', url: 'https://fs.office.example.ch', c: 'success', line: 'last opened 3 days ago', rank: 3},
    {id: 'ks', name: 'Kunden-Support', kind: 'workspace', url: 'http://10.20.0.14:8790', c: 'warning', line: 'Sign in once', insecure: true, signin: true, rank: 9},
    {id: 'relay', name: 'Relay', kind: 'relay', url: 'https://relay.example.ch/admin', c: 'danger', line: 'last opened yesterday', rank: 2},
    {id: 'pub', name: 'Publish', kind: 'publish', url: 'https://publish.example.ch/admin', c: 'info', line: 'last opened 2 weeks ago', rank: 4},
  ];
  const ARRIVED = [
    {id: 'pil', name: 'Pilatus', kind: 'workspace', url: 'https://pilatus.example.ch', c: 'warning', line: 'Sign in once', signin: true, rank: 9},
    {id: 'lab', name: 'Lab', kind: 'workspace', url: 'https://lab.internal.example.ch', c: 'chart-4', line: 'Sign in once', signin: true, rank: 9},
  ];
  const SHARE_LINK = 'https://ws-orch.internal.severin.io/#places=eyJ2IjoxLCJwIjpbeyJuIjoiRmVybnNjb3V0IiwidSI6Imh0dHBzOi8vZnMub2ZmaWNl';
  const PALETTE = ['info', 'success', 'warning', 'danger', 'chart-4', 'brand'];

  const S = {
    open: true,            // the menu (A, B) or the panel (C) is open
    saved: SAVED.map(p => ({...p})),
    arrived: [],           // places that came in a link and wait for Keep / Not now
    form: null,            // the Add place form: {address, kind, name, error}
    rowMenu: null,         // id of the row whose "…" menu is open
    renaming: null,        // id of the row being renamed
    sheet: false,          // B: the Saved places sheet
    share: false,          // Share my places is showing
    q: '',                 // C: the find field
    review: false,         // A: the keep question is showing as a step
    renameText: null,      // typed, not yet saved name of the row being renamed
  };
  let seq = 0, menuAt = 0;

  // ---------- checks on an address (plain words on refusal) ----------
  function check(text) {
    let t = text.trim();
    if (!t) return {error: 'Paste the address of the place first.'};
    if (!t.includes('://') && !/^(javascript|data|file|ftp|mailto|vbscript|blob):/i.test(t)) {
      t = (/^(127\.|10\.|192\.168\.|localhost)/.test(t) ? 'http://' : 'https://') + t;
    }
    let u;
    try { u = new URL(t); } catch { return {error: 'This is not a full address. An address starts with https:// or http://.'}; }
    if (u.protocol !== 'https:' && u.protocol !== 'http:') {
      return {error: 'This address cannot be saved. Only addresses that start with https:// or http:// work.'};
    }
    const local = /^(127\.0\.0\.1|localhost|\[::1\])$/.test(u.hostname);
    return {url: u.origin + (u.pathname === '/' ? '' : u.pathname), host: u.host, local, insecure: u.protocol === 'http:' && !local};
  }
  const hintFor = text => {
    const r = text.trim() ? check(text) : {};
    if (r.local) return 'Works only on this computer. It stays in this browser.';
    if (r.insecure) return 'This address is not secure (http).';
    return '';
  };

  // ---------- pieces every draft uses ----------
  function toastOpen(p) {
    UI.toast(p.signin ? 'Draft: this opens the sign-in page of ' + p.name + '.' : 'Draft: this opens ' + p.name + '.');
  }

  function removePlace(p) {
    const at = S.saved.indexOf(p);
    S.saved.splice(at, 1);
    S.rowMenu = null;
    render();
    const box = UI.toast('Removed ' + p.name, () => { S.saved.splice(Math.min(at, S.saved.length), 0, p); render(); });
    // Draft A: Undo only, the toast hides by itself
    if (V === 'a') box.querySelector('.btn.ghost')?.remove();
  }

  // One row: the place itself (a link: one click switches) and, for a saved place, "…" with Rename and Remove.
  function row(p, opt = {}) {
    const saved = !!p.kind;
    if (S.renaming === p.id) return renameRow(p);
    const mark = p.insecure ? h('span', {className: 'badge attn'}, 'not secure') : null;
    const line = saved && !opt.tile && !(V === 'a' && p.kind === 'workspace') ? KIND[p.kind] + ' · ' + p.line : p.line;
    const details = h('span', {className: 'grow sw-item-details'},
      h('span', {className: 'd-name'}, h('span', {className: 'ws-item-name'}, p.name), mark),
      h('span', {className: 'meta'}, line),
      opt.address && p.url ? h('span', {className: 'meta d-address'}, p.url) : null);
    const side = p.here ? h('span', {className: 'sw-item-status'}, h('span', {className: 'sw-tick', 'aria-hidden': 'true'}, '✓'))
      : opt.host && p.url ? h('span', {className: 'meta d-host'}, new URL(p.url).host) : null;
    const attrs = {className: 'sw-item' + (p.off ? ' off' : ''), role: 'menuitem', title: p.url || null};
    let main;
    if (p.here) main = h('div', {...attrs, 'aria-current': 'true', tabindex: 0}, badge(p, opt.size), details, side);
    else if (p.off) main = h('div', {...attrs, 'aria-disabled': 'true', tabindex: 0}, badge(p, opt.size), details, side);
    else main = h('a', {...attrs, href: '#', onclick: e => { e.preventDefault(); toastOpen(p); }}, badge(p, opt.size), details, side);
    if (!saved || opt.manage === false) return h('div', {className: 'd-row'}, main);
    const more = h('button', {className: 'btn ghost icon sm d-more', type: 'button', 'aria-label': 'More for ' + p.name, 'aria-haspopup': 'menu',
      'aria-expanded': String(S.rowMenu === p.id), 'data-more': p.id,
      onclick: () => { document.querySelector('#ui-toasts')?.replaceChildren(); S.rowMenu = S.rowMenu === p.id ? null : p.id; menuAt = Date.now(); render(); }}, '⋯');
    return h('div', {className: 'd-row', 'data-place': p.id}, main, more);
  }

  // The "…" menu sits above everything (fixed), so a scrolling list never cuts it off.
  function placeRowMenu() {
    document.querySelectorAll('.d-row-menu').forEach(n => n.remove());
    const p = S.saved.find(x => x.id === S.rowMenu);
    const btn = p && document.querySelector('[data-more="' + p.id + '"]');
    if (!btn) return;
    const pop = h('div', {className: 'menu-pop d-row-menu', role: 'menu', 'aria-label': 'More for ' + p.name},
      h('button', {className: 'menu-item', type: 'button', role: 'menuitem', onclick: () => { S.rowMenu = null; S.renaming = p.id; S.renameText = null; render(); }}, 'Rename'),
      h('button', {className: 'menu-item', type: 'button', role: 'menuitem', onclick: () => removePlace(p)}, 'Remove'));
    (UI.overlay.top() || document.body).append(pop);
    if (V === 'a') {
      // Draft A: never over another row. Desktop: beside the menu, level with its row. Phone: one line over its own row.
      const line = btn.closest('.d-row').getBoundingClientRect(), side = menu.getBoundingClientRect();
      pop.classList.toggle('d-row-menu-line', phone());
      const pw = pop.offsetWidth, hh = pop.offsetHeight;
      pop.style.left = (phone() ? Math.max(8, btn.getBoundingClientRect().left - pw - 4) : side.right + 4) + 'px';
      pop.style.top = Math.max(8, Math.min(line.top + (line.height - hh) / 2, innerHeight - hh - 8)) + 'px';
      pop.querySelector('button').focus({preventScroll: true});
      return;
    }
    const r = btn.getBoundingClientRect(), w = pop.offsetWidth, ph = pop.offsetHeight;
    const up = r.bottom + 4 + ph > innerHeight - 8;
    pop.style.left = Math.max(8, Math.min(r.right - w, innerWidth - w - 8)) + 'px';
    pop.style.top = (up ? r.top - ph - 4 : r.bottom + 4) + 'px';
    pop.querySelector('button').focus({preventScroll: true});
  }

  function renameRow(p) {
    const input = h('input', {className: 'input', value: S.renameText ?? p.name, maxlength: 40, 'aria-label': 'Name of ' + p.name, 'data-autofocus': true,
      oninput: () => { S.renameText = input.value; }});
    return h('form', {className: 'd-row d-rename', onsubmit: e => {
      e.preventDefault();
      const name = input.value.trim();
      if (name) p.name = name;
      S.renaming = null; S.renameText = null; render();
    }}, badge(p), input,
    h('button', {className: 'btn primary sm', type: 'submit'}, 'Save'),
    h('button', {className: 'btn ghost sm', type: 'button', onclick: () => { S.renaming = null; S.renameText = null; render(); }}, 'Cancel'));
  }

  // Add place: address, kind, optional name. A bad address is refused in plain words.
  function addForm() {
    const f = S.form;
    const hint = h('p', {className: 'meta d-hint', id: 'add-hint'}, hintFor(f.address));
    const error = h('p', {className: 'd-error', id: 'add-error', role: 'alert'}, f.error || '');
    const address = h('input', {className: 'input', id: 'add-address', value: f.address, placeholder: 'https://', autocomplete: 'off',
      inputmode: 'url', autocapitalize: 'off', spellcheck: 'false', 'aria-describedby': 'add-error add-hint', 'aria-invalid': f.error ? 'true' : null,
      'data-autofocus': true,
      oninput: () => { f.address = address.value; f.error = ''; error.textContent = ''; address.removeAttribute('aria-invalid'); hint.textContent = hintFor(f.address); }});
    const name = h('input', {className: 'input', id: 'add-name', value: f.name, maxlength: 40, autocomplete: 'off', oninput: () => { f.name = name.value; }});
    const kinds = h('div', {className: 'segmented', role: 'radiogroup', 'aria-label': 'Kind'}, Object.entries(KIND).map(([k, label]) =>
      h('label', {}, h('input', {className: 'sr-only', type: 'radio', name: 'add-kind', value: k, checked: f.kind === k, onchange: () => { f.kind = k; }}), label)));
    return h('form', {className: 'd-form', 'aria-label': 'Add place', novalidate: true, onsubmit: e => {
      e.preventDefault();
      const r = check(f.address);
      if (r.error) { f.error = r.error; render(); return; }
      const p = {id: 'new' + (++seq), name: f.name.trim() || r.host, kind: f.kind, url: r.url, c: PALETTE[seq % PALETTE.length],
        line: r.local ? 'Only in this browser' : 'Sign in once', local: r.local, insecure: r.insecure, signin: !r.local, rank: 0};
      S.saved.push(p); S.form = null; S.q = '';
      render();
      UI.toast('Saved ' + p.name);
    }},
    V === 'b' ? h('strong', {}, 'Add place') : null,
    h('label', {className: 'field', for: 'add-address'}, 'Address', address), error, hint,
    h('div', {className: 'field'}, h('span', {}, 'Kind'), kinds),
    h('label', {className: 'field', for: 'add-name'}, 'Name (optional)', name),
    h('div', {className: 'row d-form-actions'},
      h('button', {className: 'btn primary', type: 'submit'}, 'Save'),
      h('button', {className: 'btn ghost', type: 'button', onclick: () => { S.form = null; render(); }}, 'Cancel')));
  }
  const openForm = (address = '') => { S.form = {address, kind: 'workspace', name: '', error: ''}; S.rowMenu = null; S.share = false; };

  // "New places from a link: keep?": nothing is saved without a tap; every address is shown in full.
  function keepBlock(bare) {
    if (!S.arrived.length) return null;
    const keep = p => { S.saved.push(p); S.arrived.splice(S.arrived.indexOf(p), 1); };
    return h('section', {className: bare ? 'd-keep d-keep-bare' : 'banner attn d-keep', 'aria-label': 'New places from a link'},
      bare ? null : h('strong', {}, 'New places from a link: keep?'),
      S.arrived.map(p => h('div', {className: 'd-keep-row'}, badge(p),
        h('span', {className: 'd-keep-text'}, h('span', {className: 'ws-item-name'}, p.name), h('span', {className: 'meta d-address'}, p.url)),
        h('span', {className: 'row d-keep-actions'},
          h('button', {className: 'btn outline sm', type: 'button', 'aria-label': 'Keep ' + p.name, onclick: () => { keep(p); render(); UI.toast('Kept ' + p.name); }}, 'Keep'),
          h('button', {className: 'btn ghost sm', type: 'button', 'aria-label': 'Not now for ' + p.name, onclick: () => { S.arrived.splice(S.arrived.indexOf(p), 1); render(); }}, 'Not now')))),
      S.arrived.length > 1 ? h('div', {className: 'row d-keep-all'},
        h('button', {className: 'btn primary sm', type: 'button', onclick: () => { const n = S.arrived.length; [...S.arrived].forEach(keep); render(); UI.toast('Kept ' + n + ' places'); }}, 'Keep all'),
        h('button', {className: 'btn ghost sm', type: 'button', onclick: () => { S.arrived = []; render(); }}, 'Not now')) : null,
      h('p', {className: 'meta'}, 'Only places you keep are saved here.'));
  }

  // The QR picture comes from the kit (qr.js); null when the text is too long for one.
  function qr() {
    return window.OrchQR?.svg(SHARE_LINK, {label: 'QR code with the link to your places'}) || null;
  }

  function shareBlock() {
    const locals = S.saved.filter(p => p.local).map(p => p.name);
    const link = h('input', {className: 'input', readonly: true, value: SHARE_LINK, 'aria-label': 'Link to your places', onfocus: e => e.target.select()});
    return h('div', {className: 'd-share'},
      h('p', {className: 'muted'}, 'Open this link on a new phone or in another browser. It asks there which places to keep.'),
      h('div', {className: 'd-share-link'}, link, h('button', {className: 'btn primary', type: 'button', onclick: () => UI.copy(SHARE_LINK)}, 'Copy')),
      qr(),
      V === 'a' ? h('p', {className: 'meta'}, 'Anyone with this link sees these addresses.') : null,
      h('p', {className: 'meta'}, 'Addresses that only work on this computer are not included' + (locals.length ? ' (' + locals.join(', ') + ').' : '.')));
  }

  const emptyLine = onAdd => h('div', {className: 'd-empty'},
    h('p', {className: 'meta'}, 'Nothing saved yet. Add a place to switch to it from here.'),
    onAdd ? h('button', {className: 'btn outline sm', type: 'button', onclick: onAdd}, icon('plus', 14), 'Add place') : null);

  const eyebrow = text => h('p', {className: 'eyebrow'}, text);

  // ---------- the switcher box and the dropdown menu (A and B) ----------
  const box = $('#ws-box');
  let menu = null;

  function drawMenu(kids, label) {
    if (menu) { menu.remove(); menu = null; }
    box.setAttribute('aria-expanded', String(S.open));
    if (!S.open || V === 'c') return;
    menu = h('div', {className: 'sw-menu', role: 'menu', 'aria-label': label}, kids);
    box.insertAdjacentElement('afterend', menu);
    menu.style.top = box.offsetTop + box.offsetHeight + 4 + 'px';
    menu.onkeydown = e => {
      if (e.target.matches('input')) return;
      const rows = [...menu.querySelectorAll('[role=menuitem]')];
      const index = rows.indexOf(document.activeElement);
      const next = {ArrowDown: (index + 1) % rows.length, ArrowUp: (index - 1 + rows.length) % rows.length, Home: 0, End: rows.length - 1};
      if (e.key in next) { e.preventDefault(); rows[next[e.key]]?.focus(); }
    };
  }

  // A persistent dialog whose inside is drawn again on every change (so it does not flash).
  function makeDialog(className, onClosed) {
    const d = h('dialog', {className});
    const body = h('div', {className: 'd-dialog-body'});
    d.append(body);
    document.body.append(d);
    d.addEventListener('close', () => { onClosed(); render(); });
    return {d, body, sync(open, label, kids) {
      d.setAttribute('aria-label', label);
      if (open) { body.replaceChildren(...[kids].flat(Infinity).filter(Boolean)); if (!d.open) d.showModal(); }
      else if (d.open) d.close();
    }};
  }

  // ---------- Draft A: everything inside the one menu ----------
  // The menu shows one thing at a time: the list, or a step (Add place, the keep question, Share my places) with
  // a back arrow in its head. A step stays when the menu is closed and opened again, so typed text is not lost.
  function renderA() {
    const toList = () => { S.form = null; S.share = false; S.review = false; render(); };
    const head = title => h('div', {className: 'd-head'},
      h('button', {className: 'btn ghost icon sm', type: 'button', 'aria-label': 'Back to all places', onclick: toList}, icon('back')),
      h('strong', {}, title));
    if (S.review && !S.arrived.length) S.review = false;
    let kids;
    if (S.form) kids = [head('Add place'), addForm()];
    else if (S.share) kids = [head('Share my places'), shareBlock()];
    else if (S.review) kids = [head('New places from a link: keep?'), keepBlock(true)];
    else kids = [
      S.arrived.length ? h('div', {className: 'banner attn d-arrived', role: 'status'},
        h('span', {className: 'grow'}, S.arrived.length === 1 ? '1 new place from a link' : S.arrived.length + ' new places from a link'),
        h('button', {className: 'btn outline sm', type: 'button', onclick: () => { S.review = true; S.rowMenu = null; render(); }}, 'Review')) : null,
      eyebrow('On this computer'), LOCAL.map(p => row(p)),
      eyebrow('Saved places'),
      S.saved.length ? S.saved.map(p => row(p)) : emptyLine(() => { openForm(); render(); }),
      h('hr', {className: 'd-rule'}),
      h('div', {className: 'd-foot'},
        S.saved.length ? h('button', {className: 'btn ghost sm', type: 'button', onclick: () => { openForm(); render(); }}, icon('plus', 14), 'Add place') : null,
        S.saved.some(p => !p.local) ? h('button', {className: 'btn ghost sm', type: 'button', onclick: () => { S.share = true; S.rowMenu = null; render(); }}, icon('share', 14), 'Share my places') : null),
    ];
    drawMenu(kids, 'Workspaces and saved places');
    if (menu) menu.classList.toggle('d-step', !!(S.form || S.share || S.review));
  }

  // ---------- Draft B: a short menu for switching, a sheet for managing ----------
  let sheetB = null;
  function renderB() {
    const recent = [...S.saved].sort((a, b) => a.rank - b.rank).slice(0, 4);
    const openSheet = form => { S.sheet = true; S.open = false; if (form) openForm(); };
    const kids = [
      eyebrow('On this computer'), LOCAL.map(p => row(p, {size: 26})),
      eyebrow(S.saved.length > recent.length ? 'Saved places · last opened' : 'Saved places'),
      S.saved.length ? recent.map(p => row(p, {manage: false, size: 26})) : emptyLine(() => { openSheet(true); render(); }),
      h('hr', {className: 'd-rule'}),
      S.arrived.length ? h('button', {className: 'sw-item d-link-row', type: 'button', role: 'menuitem', onclick: () => { openSheet(); render(); }},
        h('span', {className: 'badge attn'}, String(S.arrived.length)),
        h('span', {className: 'grow'}, 'New places from a link'), icon('next', 14)) : null,
      h('button', {className: 'sw-item d-link-row', type: 'button', role: 'menuitem', onclick: () => { openSheet(); render(); }},
        h('span', {className: 'grow'}, 'All saved places'), S.saved.length ? h('span', {className: 'meta'}, String(S.saved.length)) : null, icon('next', 14)),
    ];
    drawMenu(kids, 'Workspaces and saved places');
    sheetB = sheetB || makeDialog('sheet d-sheet', () => { S.sheet = false; S.share = false; S.form = null; S.rowMenu = null; S.renaming = null; S.open = true; });
    let inside = null;
    if (S.sheet && S.share) {
      inside = [h('div', {className: 'd-head'}, h('button', {className: 'btn ghost icon sm', type: 'button', 'aria-label': 'Back to saved places', onclick: () => { S.share = false; render(); }}, icon('back')), h('h2', {}, 'Share my places')), shareBlock()];
    } else if (S.sheet) {
      inside = [
        h('h2', {}, 'Saved places'),
        keepBlock(),
        S.form ? addForm() : h('div', {className: 'row d-sheet-actions'},
          h('button', {className: 'btn ' + (S.arrived.length ? 'outline' : 'primary'), type: 'button', onclick: () => { openForm(); render(); }}, icon('plus'), 'Add place'),
          S.saved.some(p => !p.local) ? h('button', {className: 'btn outline', type: 'button', onclick: () => { S.share = true; S.rowMenu = null; render(); }}, icon('share'), 'Share my places') : null),
        S.saved.length ? h('div', {className: 'sw-menu d-flat', role: 'menu', 'aria-label': 'Saved places'}, S.saved.map(p => row(p, {address: true})))
          : h('p', {className: 'meta'}, 'Nothing saved yet. Add a place to switch to it from here.'),
      ];
    }
    sheetB.sync(S.sheet, S.share ? 'Share my places' : 'Saved places', inside);
  }

  // ---------- Draft C: one panel: find field, relay and publish as tiles, workspaces as a list ----------
  let panelC = null;
  function renderC() {
    drawMenu();
    panelC = panelC || makeDialog('dialog d-panel', () => { S.open = false; S.share = false; S.form = null; S.rowMenu = null; S.renaming = null; S.q = ''; });
    let inside = null;
    const back = label => h('button', {className: 'btn ghost icon sm', type: 'button', 'aria-label': label, onclick: () => { S.share = false; S.form = null; render(); }}, icon('back'));
    if (S.open && S.share) inside = [h('div', {className: 'd-head'}, back('Back to all places'), h('h2', {}, 'Share my places')), shareBlock()];
    else if (S.open && S.form) inside = [h('div', {className: 'd-head'}, back('Back to all places'), h('h2', {}, 'Add place')), addForm()];
    else if (S.open) {
      const q = S.q.trim().toLowerCase();
      const hit = p => !q || p.name.toLowerCase().includes(q) || (p.url || '').toLowerCase().includes(q) || (p.kind && KIND[p.kind].toLowerCase().includes(q));
      const local = LOCAL.filter(hit), apps = S.saved.filter(p => p.kind !== 'workspace').filter(hit), places = S.saved.filter(p => p.kind === 'workspace').filter(hit);
      const looksLikeAddress = /[:.\/]/.test(q) && !/\s/.test(q);
      const find = h('input', {className: 'input', type: 'search', value: S.q, placeholder: 'Find a place or paste an address', 'aria-label': 'Find a place or paste an address',
        autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', 'data-autofocus': !phone() && !S.renaming, 'data-keep-focus': 'find',
        oninput: () => { S.q = find.value; S.rowMenu = null; render(); },
        onkeydown: e => { if (e.key === 'Enter' && looksLikeAddress) { e.preventDefault(); openForm(S.q.trim()); render(); } }});
      inside = [
        h('h2', {className: 'sr-only'}, 'Switch to another place'),
        find,
        looksLikeAddress ? h('button', {className: 'sw-item d-link-row d-add-hit', type: 'button', onclick: () => { openForm(S.q.trim()); render(); }},
          h('span', {className: 'wsb s32'}, icon('plus')), h('span', {className: 'grow sw-item-details'}, h('span', {className: 'ws-item-name'}, 'Add place'), h('span', {className: 'meta d-address'}, S.q.trim())), icon('next', 14)) : null,
        q ? null : keepBlock(),
        apps.length ? h('div', {className: 'sw-menu d-flat d-apps', role: 'menu', 'aria-label': 'Relay and publish'}, apps.map(p => row(p, {tile: true}))) : null,
        local.length ? eyebrow('On this computer') : null,
        local.length ? h('div', {className: 'sw-menu d-flat', role: 'menu', 'aria-label': 'On this computer'}, local.map(p => row(p, {host: true}))) : null,
        q && !places.length ? null : eyebrow('Saved places'),
        places.length ? h('div', {className: 'sw-menu d-flat', role: 'menu', 'aria-label': 'Saved places'}, places.map(p => row(p, {host: true})))
          : q ? null : S.saved.length ? null : emptyLine(null),
        q && !local.length && !apps.length && !places.length && !looksLikeAddress ? h('p', {className: 'meta d-none'}, 'No place with that name.') : null,
        h('div', {className: 'd-foot'},
          h('button', {className: 'btn ' + (S.saved.length ? 'ghost' : 'primary') + ' sm', type: 'button', onclick: () => { openForm(); render(); }}, icon('plus', 14), 'Add place'),
          S.saved.some(p => !p.local) ? h('button', {className: 'btn ghost sm', type: 'button', onclick: () => { S.share = true; S.rowMenu = null; render(); }}, icon('share', 14), 'Share my places') : null),
      ];
    }
    panelC.sync(S.open, S.share ? 'Share my places' : S.form ? 'Add place' : 'Switch to another place', inside);
  }

  // ---------- drawing ----------
  function render() {
    const keep = document.activeElement?.dataset?.keepFocus, caret = document.activeElement?.selectionStart;
    ({a: renderA, b: renderB, c: renderC})[V]();
    // the form (and its refusal) is always in view, also at the end of a long menu
    document.querySelector('.d-form')?.scrollIntoView({block: 'nearest'});
    if (V === 'a') document.querySelector('.sw-menu.d-step')?.scrollIntoView({block: 'nearest'});
    placeRowMenu();
    const again = keep && document.querySelector('[data-keep-focus="' + keep + '"]');
    if (again) { again.focus({preventScroll: true}); try { again.setSelectionRange(caret, caret); } catch {} }
    else if (!shots) document.querySelector('[data-autofocus]')?.focus({preventScroll: true});
    else document.activeElement?.blur?.();
  }

  function toggle() {
    S.open = !S.open;
    if (!S.open) { S.rowMenu = null; if (V !== 'a') { S.form = null; S.renaming = null; } }
    render();
  }
  box.addEventListener('click', toggle);
  box.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  // A click outside closes the "…" menu, then the dropdown (the click's own path, because a redraw replaces the nodes).
  document.addEventListener('click', e => {
    const path = e.composedPath();
    const inside = sel => path.some(n => n.matches?.(sel));
    if (S.rowMenu && !inside('.d-row-menu,.d-more')) { S.rowMenu = null; render(); return; }
    if (V !== 'c' && S.open && menu && !inside('.sw-menu,.d-row-menu,#ws-box,.preview-controls,.ui-toasts,dialog,.tabbar')) { S.open = false; if (V !== 'a') { S.form = null; S.renaming = null; } render(); }
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (S.rowMenu) { S.rowMenu = null; e.stopImmediatePropagation(); e.preventDefault(); render(); }
    else if (S.renaming) { S.renaming = null; e.stopImmediatePropagation(); e.preventDefault(); render(); }
    else if (V !== 'c' && S.open && !UI.overlay.top()) { S.open = false; if (V !== 'a') S.form = null; render(); box.focus(); }
  }, true);
  addEventListener('resize', () => { if (S.rowMenu) { S.rowMenu = null; render(); } });
  // scrolling closes the "…" menu (it would stay behind), but not the scroll that is still settling from the tap that opened it
  document.addEventListener('scroll', () => { if (S.rowMenu && Date.now() - menuAt > 400) { S.rowMenu = null; render(); } }, true);

  // ---------- preview states (the pill bottom right; ?state=… in the address) ----------
  const STATES = [
    ['menu', 'Menu open'], V === 'b' ? ['sheet', 'Saved places'] : null, ['rowmenu', 'Row menu'], ['rename', 'Rename'], ['add', 'Add place'],
    ['refused', 'Bad address'], ['keep', 'From a link'], V === 'a' ? ['review', 'Keep question'] : null, ['share', 'Share my places'], ['empty', 'Empty'], ['removed', 'Removed'], ['closed', 'Closed'],
  ].filter(Boolean);
  const manage = () => { if (V === 'b') { S.sheet = true; S.open = false; } };
  const apply = {
    menu() {},
    sheet() { manage(); },
    rowmenu() { manage(); S.rowMenu = 'fs'; },
    rename() { manage(); S.renaming = 'fs'; },
    add() { manage(); openForm('https://pilatus.example.ch'); S.form.name = 'Pilatus'; },
    refused() { manage(); openForm('javascript:alert(1)'); S.form.error = check(S.form.address).error; },
    keep() { S.arrived = ARRIVED.map(p => ({...p})); if (V === 'b') manage(); },
    review() { S.arrived = ARRIVED.map(p => ({...p})); S.review = true; },
    share() { manage(); S.share = true; },
    empty() { S.saved = []; },
    removed() { manage(); },
    closed() { S.open = false; },
  };

  const pill = h('details', {className: 'preview-controls shared-preview', 'aria-label': 'Preview controls'},
    h('summary', {}, 'Preview · Draft ' + V.toUpperCase()),
    h('div', {className: 'preview-options'},
      STATES.map(([id, label]) => h('button', {type: 'button', className: 'btn ghost xs', 'aria-pressed': String(id === state), onclick: () => {
        const u = new URL(location.href); u.searchParams.set('state', id); location.href = u.href;
      }}, label)),
      ['a', 'b', 'c'].filter(x => x !== V).map(x => h('a', {className: 'btn outline xs', href: 'draft-' + x + '.html'}, 'Draft ' + x.toUpperCase())),
      h('a', {className: 'btn outline xs', href: 'index.html'}, 'All drafts')));
  if (!shots) pill.open = !phone();
  UI.placePreview = () => { if (!shots) (UI.overlay.top() || document.body).append(pill); };

  // A phone has no side menu until "More" is pressed: the drafts start with it open so the switcher shows.
  if (phone()) {
    const side = $('.sidebar');
    side.dataset.open = 'true';
    document.querySelector('.tabbar button')?.setAttribute('aria-expanded', 'true');
  }
  (apply[state] || apply.menu)();
  UI.placePreview();
  render();
  if (state === 'removed') removePlace(S.saved.find(p => p.id === 'fs'));
})();

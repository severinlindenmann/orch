'use strict';
// The workspace switcher: the workspace box at the top of the sidebar shows this workspace's badge; a click lists the
// workspaces orch knows on this computer (state.look.workspaces) and opens another one in this tab.
// Needs look.js (window.OrchLook.badge). No workspace string is put into markup.
(() => {
  const box = document.querySelector('.workspace');
  if (!box) return;
  let look = null, slot = null, menu = null, wired = false;
  const n = (tag, attrs = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'className') node.className = v; else node.setAttribute(k, v === true ? '' : String(v));
    }
    node.append(...kids.flat().filter(x => x != null && x !== false));
    return node;
  };
  const chevron = () => {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [k, v] of [['viewBox', '0 0 24 24'], ['width', '14'], ['height', '14'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', '2'], ['aria-hidden', 'true'], ['class', 'ws-chev']]) s.setAttribute(k, v);
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', 'm7 15 5 5 5-5M7 9l5-5 5 5');
    s.append(p);
    return s;
  };

  function wire() {
    if (wired) return;
    wired = true;
    const name = document.getElementById('workspace-name'), meta = box.querySelector('.meta');
    slot = n('span', {className: 'ws-badge-slot'});
    const text = n('span', {className: 'ws-text'});
    text.append(...[name, meta].filter(Boolean));
    box.classList.add('ws-switch');
    box.setAttribute('role', 'button');
    box.setAttribute('tabindex', '0');
    box.setAttribute('aria-haspopup', 'menu');
    box.setAttribute('aria-expanded', 'false');
    box.setAttribute('data-testid', 'ws-switch');
    box.replaceChildren(slot, text, chevron());
    box.addEventListener('click', toggle);
    box.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } else if (e.key === 'Escape') close(); });
  }

  function close() {
    if (menu) { menu.remove(); menu = null; }
    box.setAttribute('aria-expanded', 'false');
  }

  function item(w) {
    const L = window.OrchLook;
    const inner = [L.badge(w, w.name, 26), n('span', {className: 'grow ws-item-name'}, w.name)];
    if (w.here) return n('div', {className: 'sw-item', role: 'menuitem', 'aria-current': 'true', 'data-testid': 'ws-item'}, ...inner, n('span', {className: 'sw-tick', 'aria-label': 'This workspace'}, '✓'));
    if (w.url) return n('a', {className: 'sw-item', role: 'menuitem', href: w.url, 'data-testid': 'ws-item'}, ...inner);
    return n('div', {className: 'sw-item off', role: 'menuitem', 'aria-disabled': 'true', 'data-testid': 'ws-item'}, ...inner, n('span', {className: 'meta'}, 'Not running'));
  }

  function toggle() {
    if (!look) return;
    if (menu) { close(); return; }
    const list = (look.workspaces || []).slice().sort((a, b) => (b.here - a.here) || a.name.localeCompare(b.name));
    menu = n('div', {className: 'sw-menu', role: 'menu', 'aria-label': 'Workspaces on this computer', 'data-testid': 'ws-menu'},
      n('p', {className: 'eyebrow'}, 'On this computer'), list.map(item),
      list.length < 2 ? n('p', {className: 'meta sw-hint'}, 'Other workspaces show here while they run. Start one with orch start.') : null);
    box.insertAdjacentElement('afterend', menu);
    menu.style.top = box.offsetTop + box.offsetHeight + 4 + 'px';
    box.setAttribute('aria-expanded', 'true');
    menu.querySelector('a,[aria-current]')?.focus?.();
  }

  document.addEventListener('click', e => { if (menu && !menu.contains(e.target) && !box.contains(e.target)) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && menu) { close(); box.focus(); } });

  function paint() {
    if (!look || !window.OrchLook) { if (menu) close(); return; }
    wire();
    const me = (look.workspaces || []).find(w => w.here);
    slot.replaceChildren(window.OrchLook.badge(look, window.OrchLook.name(), 32));
    if (menu && !me) close();
    void me;
  }

  window.addEventListener('orch:state', e => { look = e.detail && e.detail.look ? e.detail.look : null; paint(); });
  window.addEventListener('orch:look-saved', paint);
})();

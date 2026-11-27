'use strict';
// The person block (look A, ORCH-1880): one row with the avatar (a green dot = signed in), the name, then Phone and Settings
// as icons. Pick who is using this dashboard, or add a person (a name only, no password, no rights).
// The chosen person is who tickets and history lines say did it. Data: state.people ({me, people}); null = nothing shown.
(() => {
  const root = document.getElementById('side-person');
  if (!root) return;
  let ppl, sess = null, adding = false, busy = false, closeNext = false;
  const node = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'className') n.className = v;
      else n.setAttribute(k, v === true ? '' : String(v));
    }
    n.append(...kids.flat().filter(x => x != null && x !== false));
    return n;
  };
  const initial = name => (String(name).trim()[0] || '?').toUpperCase();
  const avatar = name => node('span', {className: 'avatar sm', 'aria-hidden': 'true'}, initial(name));

  const SESSION_LABEL = {
    'signed-in': ['Signed in', 'You can make changes here.'],
    'view-only': ['View only', 'Not signed in on this browser: open the dashboard from orch to make changes.'],
    'helper': ['View only', 'A helper opened this page, so you can only look. To make changes, open orch yourself.'],
  };
  async function loadSession() {
    try {
      const r = await fetch('/api/session-state', {cache: 'no-store'});
      const j = r.ok ? await r.json() : null;
      const next = j && SESSION_LABEL[j.state] ? j.state : null;
      if (next !== sess) { sess = next; paint(); }
    } catch (e) { /* offline: keep what is shown */ }
  }
  loadSession();
  window.addEventListener('focus', loadSession);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loadSession(); });

  function paint() {
    const open = !closeNext && root.querySelector('details')?.open;
    closeNext = false;
    root.replaceChildren();
    if (!ppl) { root.hidden = true; return; }
    root.hidden = false;
    const me = ppl.me, list = ppl.people || [];
    const items = list.map(n => node('button', {type: 'button', className: 'menu-item', 'data-person': n, 'data-testid': 'person-' + n, disabled: busy},
      avatar(n), node('span', {className: 'truncate'}, n), n === me ? node('span', {className: 'grow'}) : null, n === me ? node('span', {className: 'ck', 'aria-label': 'You'}, '✓') : null));
    const add = adding
      ? node('form', {className: 'person-add', 'data-person-form': ''},
        node('input', {className: 'input', name: 'name', maxlength: '40', placeholder: 'Name', 'aria-label': 'Name of the new person', autocomplete: 'off', 'data-testid': 'person-name'}),
        node('button', {type: 'submit', className: 'btn primary sm', 'data-testid': 'person-add-save', disabled: busy}, 'Add'))
      : node('button', {type: 'button', className: 'menu-item', 'data-person-add': '', 'data-testid': 'person-add'}, 'Add person');
    const label = SESSION_LABEL[sess];
    const face = avatar(me || 'You');
    if (label) face.append(node('span', {className: 'dot' + (sess === 'signed-in' ? ' ok' : ''), 'aria-hidden': 'true'}));
    const d = node('details', {className: 'menu person-menu', open: open || adding},
      node('summary', {className: 'nav-item', 'aria-label': (me ? 'You: ' + me : 'Pick your name') + (label ? ', ' + label[0].toLowerCase() : '') + '. Switch person', title: [me, label ? (sess === 'signed-in' ? label[0] : label[0] + ': ' + label[1]) : null].filter(Boolean).join(' · ') || null, 'data-testid': 'person-switch'},
        face, (me ? node('span', {className: 'nav-label'}, me) : node('span', {className: 'nav-label pick', 'data-testid': 'person-pick'}, node('strong', {}, 'Pick your name'))), node('span', {className: 'grow'}), node('span', {className: 'chev', 'aria-hidden': 'true'})),
      node('div', {className: 'menu-pop', role: 'menu'}, node('p', {className: 'eyebrow'}, 'You are'), ...items, add,
        window.orchLogin?.token() ? node('button', {type: 'button', className: 'menu-item', 'data-logout': '', 'data-testid': 'logout'}, 'Log out') : null));
    root.append(d);
    // the dot's words for a screen reader: "Signed in", "View only", or why a helper's page is view only
    if (label) root.append(node('span', {className: 'sr-only session-state', role: 'status', 'data-testid': 'session-state', 'data-state': sess}, sess === 'helper' ? label[1] : label[0]));
    if (adding) d.querySelector('input')?.focus();
  }

  async function call(op, name) {
    if (busy || typeof window.orchAct !== 'function') return;
    busy = true; paint();
    let r;
    if (window.orchLogin?.token()) {  // a token login: this browser's own profile (ORCH-1035)
      let why = null;
      try { why = await window.orchLogin.pick(name, op === 'person.add'); } catch (_) { why = 'That did not work. Try again.'; }
      r = {ok: !why, text: why};
    } else r = await window.orchAct(op, {name});
    busy = false;
    if (!r.ok) window.orch?.toast(r.text || 'That did not work. Try again.', 'error');
    else { adding = false; closeNext = true; }  // picked: the menu closes
    paint();
  }

  root.addEventListener('click', event => {
    const pick = event.target.closest('[data-person]');
    if (pick) { call('person.set', pick.dataset.person); return; }
    if (event.target.closest('[data-person-add]')) { adding = true; paint(); }
    if (event.target.closest('[data-logout]')) window.orchLogin?.logout();
  });
  root.addEventListener('submit', event => {
    event.preventDefault();
    const name = new FormData(event.target).get('name');
    if (String(name || '').trim()) call('person.add', String(name));
  });
  window.addEventListener('orch:person', () => paint());
  window.addEventListener('orch:state', event => {
    const next = event.detail?.people || null;
    if (JSON.stringify(next) !== JSON.stringify(ppl)) { ppl = next; paint(); }
  });
})();

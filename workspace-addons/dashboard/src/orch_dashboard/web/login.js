'use strict';
// The login screen with a token and the profile picker (ORCH-1035). A browser that is not signed in (behind the
// gateway, on another computer) sees "Welcome, log in with your token" instead of an empty page; the token comes from
// `orch dashboard token new` on the workspace computer. After the login it picks a profile ("Who is using orch?"):
// that profile is who this browser acts as (kept on the server for this browser's session), and can be switched
// from the "You:" menu. A sign-in link (`#launch=`) keeps working as before. Builders: UI.doorLogin, UI.profilePicker.
(() => {
  const KEY = 'orch_page_secret';
  let me = null, door = null, kind = null;
  window.orchBrowserPerson = null;

  const post = (path, body) => fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  const textOf = async r => { try { return (await r.text()).trim(); } catch (_) { return ''; } };

  function close() { if (door) door.remove(); door = null; kind = null; }
  function setPerson(p) {
    window.orchBrowserPerson = p || null;
    window.dispatchEvent(new CustomEvent('orch:person', {detail: window.orchBrowserPerson}));
  }

  function showLogin() {
    if (kind === 'login' || !window.UI?.doorLogin) return;
    close();
    Array.prototype.forEach.call(document.querySelectorAll('dialog[open]'), d => { try { d.close(); } catch (_) { /* gone */ } });
    document.getElementById('orch-signin')?.remove();
    door = UI.doorLogin({
      hintCommand: 'orch dashboard token new',
      onLogin: async token => {
        const r = await post('/session', {login: token});
        if (!r.ok) return (await textOf(r)) || 'That did not work. Try again.';
        const j = await r.json();
        try { localStorage.setItem(KEY, j.secret || ''); sessionStorage.removeItem(KEY); } catch (_) { return 'This browser keeps no data for this page, so it cannot stay logged in.'; }
        location.reload();
        return null;
      },
    });
    door.dataset.testid = 'login-door';
    kind = 'login';
    document.body.append(door);
  }

  async function pick(name, add) {
    const r = await post('/session/profile', {name, add: !!add});
    if (!r.ok) return (await textOf(r)) || 'That did not work. Try again.';
    const j = await r.json();
    me = {...(me || {}), person: j.person, people: j.people, needs_profile: false};
    setPerson(j.person);
    close();
    return null;
  }

  function showPicker() {
    if (kind === 'picker' || !window.UI?.profilePicker || me?.login !== 'token') return;
    close();
    door = UI.profilePicker({people: me.people || [], current: me.person, onPick: n => pick(n, false), onAdd: n => pick(n, true), onLogout: logout});
    door.dataset.testid = 'profile-picker';
    if (me.person) door.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });  // switching: Esc keeps the profile
    kind = 'picker';
    document.body.append(door);
  }

  async function logout() {
    try { await post('/session/logout', {}); } catch (_) { /* gone anyway */ }
    try { localStorage.removeItem(KEY); sessionStorage.removeItem(KEY); } catch (_) { /* none */ }
    location.reload();
  }

  async function load() {
    let r;
    try { r = await fetch('/session/me', {cache: 'no-store'}); } catch (_) { return; }  // offline: the page says so
    if (r.status === 401) { showLogin(); return; }
    if (!r.ok) return;
    me = await r.json();
    if (me.login !== 'token') return;  // a sign-in link, or this computer's own page: as before
    if (me.needs_profile) showPicker();
    else setPerson(me.person);
  }

  window.orchLogin = {
    // the token login is there (orch installed next to the dashboard) unless the server said otherwise
    available: () => me?.token_login !== false,
    token: () => me?.login === 'token',
    showLogin, showPicker, logout,
    pick: (name, add) => pick(name, add),
  };
  if (/[#&]launch=/.test(location.hash || '')) return;  // session.js hands the sign-in link over and reloads
  load();
})();

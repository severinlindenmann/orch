// Starts the page session (H1/H2): a one-time sign-in link (`orch dashboard open`, or `orch dashboard open --print` for
// another computer) opens this page with a token in the URL fragment. The fragment is never sent in a request; it is
// posted once and removed from the address bar. The answer carries the page secret: it is kept in localStorage (per
// origin, so a page on another port or host never sees it; every tab of this browser shares it, so a second window
// works too) and sent as X-Orch-Page on every same-origin request. The session cookie alone is never enough (browsers
// send it to every port of the host). The page keeps loading meanwhile, with no stop and no reload (ORCH-1670): every
// request waits for the sign-in, and app.js starts its data after it (window.orchSignIn). The sign-in is the ONLY
// check: where the browser is (this computer, another one, behind a proxy) does not matter.
(function () {
  var KEY = "orch_page_secret", HEADER = "X-Orch-Page", COMMAND = "orch dashboard open";
  function stored() {
    var v = "";
    try { v = localStorage.getItem(KEY) || ""; } catch (e) { v = ""; }
    if (v) return v;
    try {  // a tab signed in before the secret moved to localStorage: keep it, and share it with the other tabs
      v = sessionStorage.getItem(KEY) || "";
      if (v) localStorage.setItem(KEY, v);
    } catch (e) { /* no storage */ }
    return v;
  }
  var realFetch = window.fetch, pendingSignIn = null;  // pendingSignIn: the sign-in of this load while it runs
  window.fetch = function (input, init) {
    var self = this;
    if (pendingSignIn) return pendingSignIn.then(function () { return send(self, input, init); });
    return send(self, input, init);
  };
  function send(self, input, init) {
    var secret = stored();
    if (secret) {
      var url = (typeof Request !== "undefined" && input instanceof Request) ? input.url : String(input);
      var local = false;
      try { local = new URL(url, location.href).origin === location.origin; } catch (e) { local = false; }
      if (local) {
        init = Object.assign({}, init || {});
        var h = new Headers(init.headers || (typeof input !== "string" && input ? input.headers : undefined) || {});
        h.set(HEADER, secret);
        init.headers = h;
      }
    }
    return realFetch.call(self, input, init).then(function (r) {
      if (r.status === 401 || r.status === 403) signInNotice(r);
      return r;
    });
  }
  // The server does not know this browser's session (never signed in here, or the sign-in ended): say so once, in
  // plain words. Nothing restarted: this is never an update notice (those come from update.js after a real update).
  function signInNotice(r) {
    r.clone().text().then(function (t) {
      var login = window.orchLogin;  // login.js (ORCH-1035): the login screen and the profile picker
      if (t.indexOf("Sign in to ") === 0) {
        if (login && login.available()) login.showLogin(); else showSignIn(t);
      } else if (t === "Pick a profile first." && login) login.showPicker();
    }).catch(function () {});
  }
  function showSignIn(t) {
    {
      if (document.getElementById("orch-signin")) return;
      // never under an open dialog (a modal sits above the page): close it so the notice can be read
      Array.prototype.forEach.call(document.querySelectorAll("dialog[open]"), function (d) { try { d.close(); } catch (e) { /* gone */ } });
      var b = document.createElement("div");
      b.id = "orch-signin"; b.className = "banner info orch-notice"; b.setAttribute("role", "alert");
      b.style.cssText = "margin:8px 16px 0";
      var d = document.createElement("div"); d.textContent = t; b.appendChild(d);
      if (t.indexOf(COMMAND) !== -1) {  // the notice names the sign-in command: one click copies it
        var c = document.createElement("button"); c.type = "button"; c.className = "btn primary sm"; c.textContent = "Copy command";
        c.style.marginTop = "8px"; c.style.marginRight = "8px";
        c.onclick = function () {
          var done = function () { c.textContent = "Copied"; };
          try { navigator.clipboard.writeText(COMMAND).then(done, function () { c.textContent = COMMAND; }); }
          catch (e) { c.textContent = COMMAND; }  // no clipboard here: show the words to type
        };
        b.appendChild(c);
      }
      var x = document.createElement("button"); x.type = "button"; x.className = "btn sm"; x.textContent = "Got it"; x.style.marginTop = "8px";
      x.onclick = function () { b.remove(); };
      b.appendChild(x);
      (document.body || document.documentElement).insertBefore(b, (document.body || document.documentElement).firstChild);
    }
  }
  // A sign-in link pasted into a tab that is already open only changes the hash: no load happens, so the router would
  // show "Page not found" for it. Treat it like a fresh load: this listener is added before the app's (session.js
  // loads first), takes the token out of the address and stops the event, so the app never routes to it (#1918).
  window.addEventListener("hashchange", function (e) {
    if (!spend(false)) return;
    if (e && e.stopImmediatePropagation) e.stopImmediatePropagation();
  });
  spend(true);
  function spend(loading) {
    var m = /[#&]launch=([A-Za-z0-9_-]{20,64})/.exec(location.hash || "");
    if (!m) return false;
    // The app must NOT fetch (or read a one-time notice) before the session exists. While the page loads, its scripts
    // keep loading: every request waits for this sign-in (pendingSignIn) and app.js starts after it. Never window.stop() and
    // reload here: that aborted every script already on its way and loaded the page twice (ORCH-1670). A tab that was
    // already open (a pasted link) did start without the session, so it reloads once signed in.
    // the page address before the token stays (a live page address of one ticket, then #launch=...)
    history.replaceState(null, "", location.pathname + location.search + (location.hash || "").replace(/[#&]launch=[A-Za-z0-9_-]+$/, ""));
    var failed = "This sign-in link did not work. Sign in again: run orch dashboard open in your terminal.";
    var never = function () { return new Promise(function () { /* a refused link: nothing starts, the words stay */ }); };
    var done = realFetch("/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: m[1] }),
    }).then(function (r) {
      if (!r.ok) {  // a used or ended link: say so (the page would stay on empty boxes with no word why)
        return r.text().then(function (t) { showSignIn(t || failed); return never(); });
      }
      return r.json().then(function (j) {
        try { localStorage.setItem(KEY, j.secret || ""); } catch (e) { /* no storage: the page stays watch-only */ }
        try { sessionStorage.removeItem(KEY); } catch (e) { /* none */ }
        if (!loading) location.reload();
      });
    }, function () { showSignIn(failed); return never(); });
    if (loading) {
      pendingSignIn = done.then(function () { pendingSignIn = null; });
      window.orchSignIn = pendingSignIn;
    }
    return true;
  }
})();
// A page loaded while an add-on change reinstalls orch can get its scripts missing or empty (the old server still
// answers while the files are replaced) and then stays on the loading skeleton (ORCH-1034, seen in the walk). A
// script of this page that fails to load: reload once a few seconds later, when the restarted server serves them,
// at most every 20 s so a page that really lacks a file does not reload without end.
(function () {
  var KEY = "orch_reload_broken", armed = false;
  window.addEventListener("error", function (event) {
    var el = event && event.target;
    if (armed || !el || el.tagName !== "SCRIPT" || !el.src) return;
    try { if (new URL(el.src, location.href).origin !== location.origin) return; } catch (e) { return; }
    var last = 0;
    try { last = Number(sessionStorage.getItem(KEY)) || 0; } catch (e) { return; }  // no storage: never reload
    if (Date.now() - last < 20000) return;
    armed = true;
    try { sessionStorage.setItem(KEY, String(Date.now())); } catch (e) { return; }
    setTimeout(function () { location.reload(); }, 4000);
  }, true);
})();

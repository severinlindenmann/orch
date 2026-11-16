// Starts the page session (H1/H2): a one-time sign-in link (`orch start`, or `orch start --print-launch-url` for
// another computer) opens this page with a token in the URL fragment. The fragment is never sent in a request; it is
// posted once and removed from the address bar. The answer carries the page secret: it is kept in localStorage (per
// origin, so a page on another port or host never sees it; every tab of this browser shares it, so a second window
// works too) and sent as X-Orch-Page on every same-origin request. The session cookie alone is never enough (browsers
// send it to every port of the host). Then the page reloads. The sign-in is the ONLY check: where the browser is (this
// computer, another one, behind a proxy) does not matter.
(function () {
  var KEY = "orch_page_secret", HEADER = "X-Orch-Page";
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
  var realFetch = window.fetch;
  window.fetch = function (input, init) {
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
    return realFetch.call(this, input, init).then(function (r) {
      if (r.status === 403) signInNotice(r);
      return r;
    });
  };
  // The server does not know this browser's session (never signed in here, or the sign-in ended): say so once, in
  // plain words. Nothing restarted: this is never an update notice (those come from update.js after a real update).
  function signInNotice(r) {
    r.clone().text().then(function (t) {
      if (t.indexOf("Sign in to ") !== 0 || document.getElementById("orch-signin")) return;
      // never under an open dialog (a modal sits above the page): close it so the notice can be read
      Array.prototype.forEach.call(document.querySelectorAll("dialog[open]"), function (d) { try { d.close(); } catch (e) { /* gone */ } });
      var b = document.createElement("div");
      b.id = "orch-signin"; b.className = "banner info orch-notice"; b.setAttribute("role", "alert");
      b.style.cssText = "margin:8px 16px 0";
      var d = document.createElement("div"); d.textContent = t; b.appendChild(d);
      var x = document.createElement("button"); x.type = "button"; x.textContent = "Got it"; x.style.marginTop = "8px";
      x.onclick = function () { b.remove(); };
      b.appendChild(x);
      (document.body || document.documentElement).insertBefore(b, (document.body || document.documentElement).firstChild);
    }).catch(function () {});
  }
  var m = /[#&]launch=([A-Za-z0-9_-]{20,64})/.exec(location.hash || "");
  if (!m) return;
  // The app must NOT start (and fetch, and read a one-time notice) while the page is only a bootstrap: stop loading the
  // rest of the page, hand the token over, and reload; everything starts after the reload with the session.
  if (window.stop) window.stop();
  history.replaceState(null, "", location.pathname + location.search);
  realFetch("/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: m[1] }),
  }).then(function (r) {
    if (!r.ok) return;
    return r.json().then(function (j) {
      try { localStorage.setItem(KEY, j.secret || ""); } catch (e) { /* no storage: the page stays watch-only */ }
      try { sessionStorage.removeItem(KEY); } catch (e) { /* none */ }
      location.reload();
    });
  });
})();

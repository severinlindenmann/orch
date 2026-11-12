// Starts the page session (H1/H2): `orch start` opens this page with a one-time launch token in the URL fragment.
// The fragment is never sent in a request; it is posted once and removed from the address bar. The answer carries the
// page secret: it is kept in sessionStorage (per origin, so a page on another local port never sees it) and sent as
// X-Orch-Page on every same-origin request. The session cookie alone is never enough (browsers send it to every
// local port). Then the page reloads.
(function () {
  var KEY = "orch_page_secret", HEADER = "X-Orch-Page";
  function stored() { try { return sessionStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
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
    return realFetch.call(this, input, init);
  };
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
      try { sessionStorage.setItem(KEY, j.secret || ""); } catch (e) { /* no storage: the page stays watch-only */ }
      location.reload();
    });
  });
})();

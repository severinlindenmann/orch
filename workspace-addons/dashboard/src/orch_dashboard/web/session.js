// Starts the page session (H1): `orch start` opens this page with a one-time launch token in the URL fragment.
// The fragment is never sent in a request; it is posted once, removed from the address bar, and the page reloads.
(function () {
  var m = /[#&]launch=([A-Za-z0-9_-]{20,64})/.exec(location.hash || "");
  if (!m) return;
  history.replaceState(null, "", location.pathname + location.search);
  fetch("/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: m[1] }),
  }).then(function (r) { if (r.ok) location.reload(); });
})();

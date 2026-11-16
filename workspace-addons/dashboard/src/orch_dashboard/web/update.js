// The update banners ("Update started", then the outcome) and the update phase Settings > About & updates shows.
// The Update button (Settings) runs `orch update`; this page script polls its result and reports it.
(function () {
  function el(tag, text, cls) { var e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; }
  function place(b) {
    var anchor = document.getElementById("content");
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(b, anchor); else document.body.insertBefore(b, document.body.firstChild);
  }
  var shown = "";
  // the update banners ("started", then the outcome): ONE at a time, a new one replaces the old; "Got it" clears it
  function banner(text, changes) {
    var old = document.querySelectorAll ? document.querySelectorAll(".orch-update-banner") : [];
    for (var k = 0; k < old.length; k++) old[k].remove();
    var b = el("div", text, "orch-notice"); b.setAttribute("role", "status");
    b.className = "banner info orch-notice orch-update-banner"; b.style.cssText = "margin:8px 16px 0";
    if (changes) {  // after an update: where the list of changes is (Settings > About & updates)
      var a = el("a", "What changed"); a.href = "#settings/about"; a.style.cssText = "margin-left:12px"; a.setAttribute("data-key", "update-changes-link");
      b.appendChild(a);
    }
    var x = el("button", "Got it"); x.type = "button"; x.style.cssText = "margin-left:12px"; x.onclick = function () { b.remove(); };
    b.appendChild(x); place(b);
    return b;
  }
  // the detached update: "Update finished" / "Update failed: <reason>" (also after the page reconnects)
  // The page stops waiting after 3 minutes (the start time survives the page reloading while orch restarts).
  var UPDATE_WAIT = 180000, UPDATE_KEY = "orch-update-started";
  function updateDone() { try { sessionStorage.removeItem(UPDATE_KEY); } catch (e) {} }
  function updateOverdue(unreachable) {
    var at = 0;
    try { at = Number(sessionStorage.getItem(UPDATE_KEY)) || 0; } catch (e) {}
    if (!at || Date.now() - at < UPDATE_WAIT) return;
    updateDone();
    // unreachable = this page's server is gone (restarted, maybe on another address): not a failed update
    var t = unreachable === true
      ? "orch restarted. Reload the dashboard."
      : "The update did not finish. orch is still the old version. Start the update again when you are ready.";
    if (t !== shown) { shown = t; banner(t); }
  }
  // "Updated orch 24 → 25." when the version before is known (the Settings button keeps it for the page reload)
  function finishedWords(release) {
    var to = Number(release);
    if (!(to > 0)) return "Update finished.";
    var from = null;
    try { from = JSON.parse(sessionStorage.getItem("orch-update-from")); } catch (e) {}
    try { sessionStorage.removeItem("orch-update-from"); } catch (e) {}
    from = Number(String(from == null ? "" : from).replace(/^orch /, ""));
    return from > 0 && from !== to ? "Updated orch " + from + " \u2192 " + to + "." : "Updated to orch " + to + ".";
  }
  function tell(state, reason) {
    if (!state) return;
    try { window.dispatchEvent(new CustomEvent("orch-update-state", {detail: {state: state, reason: reason || ""}})); } catch (e) {}
  }
  function updateStatus() {
    var gone = false;
    fetch("/api/update-status", {headers: {"Accept": "application/json"}}).then(function (r) { gone = !r.ok; return r.ok ? r.json() : {}; }).then(function (s) {
      if (!s || !s.state || s.state === "running") {
        tell(s && s.state === "running" ? "running" : gone ? "unreachable" : "");  // Settings > About & updates shows the steps
        updateOverdue(gone); return;
      }
      tell(s.state, s.reason);
      updateDone();
      var why = (s.reason || "it did not finish").replace(/[.\s]+$/, "");
      var t = s.state === "finished" ? finishedWords(s.release) : "Update failed: " + why + ".";
      if (t !== shown) { shown = t; banner(t, s.state === "finished"); }
    }).catch(function () { tell("unreachable"); updateOverdue(true); });
  }
  updateStatus(); setInterval(updateStatus, 4000);
})();

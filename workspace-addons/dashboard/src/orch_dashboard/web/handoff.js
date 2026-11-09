// "Requested by a command": a terminal asked for something only you may do. Shows the request in plain words; ONE click
// (Continue) lets the dashboard do it. Never focuses a button, no typed words. No token is shown here.
(function () {
  var box = null, seen = "";
  function el(tag, text, cls) { var e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; }
  function post(op, id) {
    return fetch("/api/act", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({op: op, args: {id: id}})});
  }
  // ONE element in the page layout (right under the top bar, above the page), never floating over the page: it
  // can not cover the review bar or any other action. One request = one sentence and two buttons; several =
  // "2 requests waiting" that opens a list, each row with its own buttons. Plain words only: the sentence comes
  // from orch with {value} where the person's own text goes (shown as text, never as markup or JSON).
  var open = false;
  function sentence(i) { return String(i.label || "Do this?").split("{value}").join(String(i.value || "")); }
  function buttons(i) {
    var row = el("span", "", "ho-btns");
    var ok = el("button", "Continue", "btn primary"), no = el("button", "Not now", "btn");
    ok.type = no.type = "button";
    ok.onclick = function () {
      ok.disabled = true;
      post("handoff.confirm", i.id).then(function (r) {
        if (r.ok) {
          if (r.status === 202) { r.text().then(function (t) { banner(t); }); }
          poll();
        } else { return r.text().then(function (t) { ok.disabled = false; banner(t); }); }
      });
    };
    no.onclick = function () { post("handoff.dismiss", i.id).then(poll); };
    row.appendChild(ok); row.appendChild(no);
    return row;
  }
  function slot() {
    if (box) return box;
    box = el("section", "", "banner attn orch-handoff"); box.id = "handoff"; box.setAttribute("aria-live", "polite");
    box.style.cssText = "margin:8px 16px 0;flex-direction:column;align-items:stretch;gap:8px";
    var anchor = document.getElementById("content");
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(box, anchor); else document.body.insertBefore(box, document.body.firstChild);
    return box;
  }
  function render(items) {
    var key = JSON.stringify(items) + open;
    if (key === seen) return;
    seen = key;
    var b = slot();
    b.textContent = "";
    b.hidden = !items.length;
    if (!items.length) { open = false; return; }
    var head = el("div"); head.style.cssText = "display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center";
    var small = el("span", "Requested by a command", "meta"); small.style.cssText = "flex-basis:100%;font-size:12px;opacity:.75";
    head.appendChild(small);
    if (items.length === 1) {
      var t = el("span", sentence(items[0])); t.style.cssText = "flex:1;min-width:200px;white-space:pre-wrap";
      head.appendChild(t); head.appendChild(buttons(items[0])); b.appendChild(head); return;
    }
    var sum = el("span", items.length + " requests waiting"); sum.style.cssText = "flex:1;font-weight:600";
    var tog = el("button", open ? "Hide" : "Show", "btn"); tog.type = "button"; tog.setAttribute("aria-expanded", String(open));
    tog.onclick = function () { open = !open; seen = ""; render(items); };
    head.appendChild(sum); head.appendChild(tog); b.appendChild(head);
    if (open) items.forEach(function (i) {
      var r = el("div"); r.style.cssText = "display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;border-top:1px solid var(--border);padding-top:8px";
      var t = el("span", sentence(i)); t.style.cssText = "flex:1;min-width:200px;white-space:pre-wrap";
      r.appendChild(t); r.appendChild(buttons(i)); b.appendChild(r);
    });
  }
  function poll() {
    fetch("/api/handoffs", {headers: {"Accept": "application/json"}}).then(function (r) { return r.ok ? r.json() : []; }).then(render).catch(function () {});
  }
  function place(b) {
    var anchor = document.getElementById("content");
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(b, anchor); else document.body.insertBefore(b, document.body.firstChild);
  }
  function notices() {
    fetch("/api/notices", {headers: {"Accept": "application/json"}}).then(function (r) { return r.ok ? r.json() : []; }).then(function (items) {
      items.forEach(function (n) {
        var b = el("div", "", "orch-notice"); b.setAttribute("role", "status");
        b.className = "banner info orch-notice"; b.style.cssText = "margin:8px 16px 0";
        b.appendChild(el("div", n.text));
        var x = el("button", "Got it"); x.type = "button"; x.style.marginTop = "8px"; x.onclick = function () { b.remove(); };
        b.appendChild(x); place(b);
      });
    }).catch(function () {});
  }
  var shown = "";
  function banner(text) {
    var b = el("div", text, "orch-notice"); b.setAttribute("role", "status");
    b.className = "banner info orch-notice"; b.style.cssText = "margin:8px 16px 0";
    var x = el("button", "Got it"); x.type = "button"; x.style.cssText = "margin-left:12px"; x.onclick = function () { b.remove(); };
    b.appendChild(x); place(b);
  }
  // the detached update: "Update finished" / "Update failed: <reason>" (also after the page reconnects)
  function updateStatus() {
    fetch("/api/update-status", {headers: {"Accept": "application/json"}}).then(function (r) { return r.ok ? r.json() : {}; }).then(function (s) {
      if (!s || !s.state || s.state === "running") return;
      var t = s.state === "finished" ? "Update finished." : "Update failed: " + (s.reason || "it did not finish") + ".";
      if (t !== shown) { shown = t; banner(t); }
    }).catch(function () {});
  }
  notices(); poll(); updateStatus(); setInterval(poll, 4000); setInterval(updateStatus, 4000);
})();

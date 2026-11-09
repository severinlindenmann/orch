// "Requested by a command": a terminal asked for something only you may do. Shows the full request; ONE click
// (Continue) lets the dashboard do it. Never focuses a button, no typed words. No token is shown here.
(function () {
  var box = null, seen = "";
  function el(tag, text, cls) { var e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; }
  function post(op, id) {
    return fetch("/api/act", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({op: op, args: {id: id}})});
  }
  var WORDS = {"ticket.answer": "Send an answer", "run.human_input": "Send a message to the agent", "ticket.verdict": "Decide on a ticket", "relay.allow": "Allow another workspace", "update": "Update orch", "relay.connect": "Connect to a relay", "chat.send": "Write in Chat"};
  function render(items) {
    var key = JSON.stringify(items);
    if (key === seen) return;
    seen = key;
    if (!box) { box = el("section", "", "orch-handoff"); box.setAttribute("aria-live", "polite"); box.style.cssText = "position:fixed;right:16px;bottom:16px;max-width:380px;z-index:50;display:flex;flex-direction:column;gap:8px"; document.body.appendChild(box); }
    box.textContent = "";
    items.forEach(function (i) {
      var c = el("div", "", "orch-handoff-card");
      c.style.cssText = "background:#fff;color:#111;border:1px solid #c9c9c9;border-radius:10px;padding:12px;box-shadow:0 4px 16px rgba(0,0,0,.15)";
      c.appendChild(el("div", "Requested by a command", "orch-handoff-from")).style.cssText = "font-size:12px;opacity:.7";
      c.appendChild(el("div", WORDS[i.op] || "Do something", "")).style.fontWeight = "600";
      if (i.label) c.appendChild(el("div", i.label));
      if (i.value) c.appendChild(el("div", i.value)).style.cssText = "white-space:pre-wrap;margin-top:4px";
      var row = el("div"); row.style.cssText = "margin-top:8px;display:flex;gap:8px";
      var ok = el("button", "Continue"), no = el("button", "Not now");
      ok.type = no.type = "button";
      ok.onclick = function () { ok.disabled = true; post("handoff.confirm", i.id).then(function (r) { if (r.ok) { if (r.status === 202) { r.text().then(function (t) { var b = el("div", t, "orch-notice"); b.setAttribute("role", "status"); b.style.cssText = "position:fixed;left:16px;right:16px;top:16px;max-width:560px;margin:0 auto;z-index:60;background:#fff8e1;color:#111;border:1px solid #e0c36a;border-radius:10px;padding:12px"; document.body.appendChild(b); setTimeout(function () { b.remove(); }, 15000); }); } poll(); } else { return r.text().then(function (t) { ok.disabled = false; alert(t); }); } }); };
      no.onclick = function () { post("handoff.dismiss", i.id).then(poll); };
      row.appendChild(ok); row.appendChild(no); c.appendChild(row); box.appendChild(c);
    });
  }
  function poll() {
    fetch("/api/handoffs", {headers: {"Accept": "application/json"}}).then(function (r) { return r.ok ? r.json() : []; }).then(render).catch(function () {});
  }
  function notices() {
    fetch("/api/notices", {headers: {"Accept": "application/json"}}).then(function (r) { return r.ok ? r.json() : []; }).then(function (items) {
      items.forEach(function (n) {
        var b = el("div", "", "orch-notice"); b.setAttribute("role", "status");
        b.style.cssText = "position:fixed;left:16px;right:16px;top:16px;max-width:560px;margin:0 auto;z-index:60;background:#fff8e1;color:#111;border:1px solid #e0c36a;border-radius:10px;padding:12px;box-shadow:0 4px 16px rgba(0,0,0,.15)";
        b.appendChild(el("div", n.text));
        var x = el("button", "Got it"); x.type = "button"; x.style.marginTop = "8px"; x.onclick = function () { b.remove(); };
        b.appendChild(x); document.body.appendChild(b);
      });
    }).catch(function () {});
  }
  notices(); poll(); setInterval(poll, 4000);
})();

// A terminal asked for something only you may do. Shows the request in plain words; ONE click
// (Send answer / Continue) lets the dashboard do it. Never focuses a button, no typed words. No token is shown here.
(function () {
  var box = null, seen = "";
  function el(tag, text, cls) { var e = document.createElement(tag); if (text) e.textContent = text; if (cls) e.className = cls; return e; }
  function post(op, id) {
    return fetch("/api/act", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({op: op, args: {id: id}})});
  }
  // ONE element in the page layout (right under the top bar, above the page), never floating over the page: it
  // can not cover the review bar or any other action. One request = one sentence and two buttons; several =
  // "2 requests waiting" that opens a list, each row with its own buttons. Plain words only: the sentence comes
  // from orch as structured parts; the person's own text is a separate "Exact text" block.
  var open = false;
  // One FIXED template per op. Every untrusted fragment (a title, a question, a path, a host, a name) goes into its
  // own <span> with textContent: nothing is ever substituted into a string, so a title that says "{value}" or
  // carries quotes can only ever be shown as itself. The exact text the person approves is a separate block.
  function cap(t) { t = String(t == null ? "" : t).replace(/\s+/g, " ").replace(/[\u201c\u201d\u201e\u00ab\u00bb"]/g, "'"); return t.length > 120 ? t.slice(0, 120) + "\u2026" : t; }
  function q(t) { var s = el("span"); s.className = "ho-part"; s.style.fontWeight = "600"; s.textContent = "\u201c" + cap(t) + "\u201d"; return s; }
  function plain(t) { var s = el("span"); s.style.fontWeight = "600"; s.textContent = cap(t); return s; }
  // a target that matters (a server, a source, a folder) is never cut in the sentence; the full value is also in the exact block
  function full(t) { var s = el("span"); s.style.cssText = "font-weight:600;overflow-wrap:anywhere"; s.textContent = String(t == null ? "" : t); return s; }
  function say(parts) {  // [string | element]...
    var s = el("span"); s.className = "ho-sentence"; s.style.cssText = "flex:1;min-width:200px";
    parts.forEach(function (p) { s.appendChild(typeof p === "string" ? document.createTextNode(p) : p); });
    return s;
  }
  function shortValue(v) { return v.length <= 120 && !/[\r\n]/.test(v); }  // shown in the sentence, no separate block
  function stepName(p) {  // "step 3, “text”": the number is orch's, the text is the agent's
    var n = Number(p.n) > 0 ? "step " + Number(p.n) + ", " : "";
    var s = el("span"); s.appendChild(document.createTextNode(n)); s.appendChild(q(p.step)); return s;
  }
  var STATUS = {done: ["Move ", " to Done?"], review: ["Move ", " to Review?"], back: ["Send ", " back to work?"]};
  var INSIGHTS_SETTING = {"insights.keep_days": "how long full detail is kept", "insights.max_mb": "the largest size of the record", "insights.share_counts": "sharing counts with your admin", "insights.share_names": "sharing this workspace's names"};
  function insightsValue(key, v) {  // plain words for the value; anything unexpected is shown capped, never as markup
    var n = Number(v);
    if (key === "insights.keep_days" && n > 0) return n + " days";
    if (key === "insights.max_mb" && n > 0) return n >= 1024 ? n / 1024 + " GB" : n + " MB";
    if (v === "on" || v === "off" || v === true || v === false) return v === "on" || v === true ? "on" : "off";
    return cap(v);
  }
  var TEMPLATES = {
    "copy.remove_orphaned": function (p) { return ["Remove copies of the missing project ", plain(p.ws8), p.discard ? ", discarding changes that cannot be saved?" : ", saving changes first?"]; },
    "copy.retry": function (p) { return ["Try cleaning up the copy for ", q(p.title), " again?"]; },
    "ticket.answer": function (p, i) {  // "Send this answer to Weekly report? Which colour → Blue"
      var v = i && i.value != null ? String(i.value) : "";
      return ["Send this answer to ", plain(p.title), "? "].concat(p.question ? [el("span", cap(p.question))] : [], v && shortValue(v) ? [" \u2192 ", full(v)] : []);
    },
    "ticket.verdict": function (p) {
      if (p.status) { var w = STATUS[p.status] || STATUS.back; return [w[0], q(p.title), w[1] + (p.also && p.also.length ? " (it also changes: " + p.also.map(cap).join(", ") + ")" : "")]; }
      return ["Send ", q(p.title), " back with a note?"];
    },
    "run.human_input": function (p) { return ["Send a message to the helper on ", q(p.title), "?"]; },
    "chat.send": function (p) { return p.thread ? ["Send a message to ", plain(p.thread), "?"] : ["Send a message in Chat?"]; },
    "check.wont_do": function (p) { return ["Mark ", stepName(p), " on ", q(p.title), " as won't do?"]; },
    "check.wont_do_undo": function (p) {
      var verb = {edit: "Rename ", remove: "Remove "}[p.action] || "Open ";
      return [verb, stepName(p), " on ", q(p.title), p.action === "edit" || p.action === "remove" ? "?" : " again?"];
    },
    "config.agents_may_finish": function () { return ["Let agents mark tickets Done?"]; },
    "config.permissions": function (p) { return ["Let helpers do more without asking (mode ", plain(p.mode), ")?"]; },
    "config.copy_setup": function () { return ["Run a command whenever a separate copy is made?"]; },
    "config.agent_add": function (p) { return ["Add the helper ", plain(p.name), "? orch will run this command for every task."]; },
    "config.share": function () { return ["Share the orch entry with your team (AGENTS.md)?"]; },
    "look.shared_pages": function (p) { return [p.on ? "Show the workspace name and icon on shared file pages?" : "Stop showing the workspace name and icon on shared file pages?"]; },
    "look.icon": function (p) { return ["Change the workspace icon to ", plain(p.icon), " and colour to ", plain(p.color), "?"]; },
    "group.write_as_person": function (p) { return ["Write into the group ", q(p.title), p.host ? " (host " + p.host + ")" : "", " as yourself?"]; },
    "group.remove_member": function (p) { return ["Remove ", q(p.workspace), " from the group ", q(p.title), "?"]; },
    "group.share_file": function (p) { return ["Share ", q(p.file), " with the group ", q(p.title), p.host ? " (host " + p.host + ")" : "", "?"]; },
    "chat.make_ticket": function () { return ["Make a ticket from this Chat conversation?"]; },
    "update": function (p) { return ["Update orch from ", full(p.source), "?"]; },
    "relay.connect": function (p) {
      var s = p.scheme === "http" ? "http://" : "https://";
      return ["Connect to ", full(s + p.host), "?" + (p.scheme === "http" ? " This address is not encrypted." : "")];
    },
    "relay.allow": function (p) { return ["Allow ", plain(p.peer), " to start ", q(p.task), " (" + cap(p.mode) + ")?"]; },
    "private.allow": function (p) { return ["Allow ", q(p.name), " to run ", full(p.command), p.interactive ? " (and, live: " : "", p.interactive ? full(p.interactive) : "", p.interactive ? ")" : "", " on this computer?"]; },
    "private.move": function () { return ["Move your orch files that are not shared with the team out of the team repo?"]; },
    "config.agent_add": function (p) { return ["Add the helper ", q(p.name), " that runs ", full(p.command)].concat(p.interactive ? [" (live: ", full(p.interactive), ")"] : [], ["?"]); },
    "insights.settings": function (p) { return ["Change ", plain(INSIGHTS_SETTING[p.setting] || "an Insights setting"), " to ", plain(insightsValue(p.setting, p.value)), "?"]; },
    "record.delete_detail": function (p) { return ["Delete the full detail of ", q(p.title), "? The counts stay."]; },
    "addon.add_local": function (p) { return ["Add the add-on from ", full(p.path), " (version ", plain(p.short), ")? It runs inside orch."]; }
  };
  function sentence(i) {
    var p = i.parts && typeof i.parts === "object" ? i.parts : {};
    var f = TEMPLATES[i.op];
    return say(f ? f(p, i) : ["Do something on this computer?"]);
  }
  var EXACT_LABEL = {"config.agent_add": "Exact values:", "private.allow": "Exact values:", "relay.connect": "Exact address:", "update": "Exact source:", "addon.add_local": "Exact folder:", "group.share_file": "Exact file:", "config.copy_setup": "Exact command:"};
  function block(label, text) {
    var d = el("div"); d.className = "ho-exact"; d.style.cssText = "flex-basis:100%;margin-top:4px";
    var l = el("div", label, "meta"); l.style.cssText = "font-size:12px;opacity:.75";
    var pre = el("pre"); pre.textContent = String(text); pre.style.cssText = "margin:2px 0 0;padding:8px;border:1px solid var(--border);border-radius:8px;background:var(--surface);font:13px/1.4 ui-monospace,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:160px;overflow:auto";
    d.appendChild(l); d.appendChild(pre);
    return d;
  }
  function exact(i) {  // the exact text / target that will be used, never merged into the sentence, never cut
    var w = el("div"); w.style.cssText = "flex-basis:100%";
    if (i.exact) w.appendChild(block(EXACT_LABEL[i.op] || "Exact value:", i.exact));
    if (i.value && !(i.op === "ticket.answer" && shortValue(String(i.value)))) w.appendChild(block("Exact text:", i.value));
    return w.childNodes.length ? w : null;
  }
  var OK_LABEL = {"ticket.answer": "Send answer", "run.human_input": "Send message", "chat.send": "Send message"};
  function buttons(i) {
    var row = el("span", "", "ho-btns"); row.style.cssText = "display:inline-flex;gap:8px;flex-wrap:wrap";
    var ok = el("button", OK_LABEL[i.op] || "Continue", "btn primary"), no = el("button", "Not now", "btn");
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
  function source() {  // where the request came from: behind a small click
    var d = el("details"), s = el("summary", "Technical details", "meta"), p = el("p", "Requested from a terminal on this computer.", "meta");
    s.style.cssText = "font-size:12px;cursor:pointer;min-height:44px;display:flex;align-items:center"; p.style.cssText = "margin:4px 0 0;font-size:12px";
    d.appendChild(s); d.appendChild(p); return d;
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
    if (items.length === 1) {
      head.appendChild(sentence(items[0])); head.appendChild(buttons(items[0])); b.appendChild(head);
      var x1 = exact(items[0]); if (x1) b.appendChild(x1);
      b.appendChild(source());
      return;
    }
    var sum = el("span", items.length + " requests waiting"); sum.style.cssText = "flex:1;font-weight:600";
    var tog = el("button", open ? "Hide" : "Show", "btn"); tog.type = "button"; tog.setAttribute("aria-expanded", String(open));
    tog.onclick = function () { open = !open; seen = ""; render(items); };
    head.appendChild(sum); head.appendChild(tog); b.appendChild(head);
    if (open) items.forEach(function (i) {
      var r = el("div"); r.style.cssText = "display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;border-top:1px solid var(--border);padding-top:8px";
      r.appendChild(sentence(i)); r.appendChild(buttons(i));
      var x = exact(i); if (x) r.appendChild(x);
      b.appendChild(r);
    });
    b.appendChild(source());
  }
  function poll() {
    fetch("/api/handoffs", {headers: {"Accept": "application/json"}}).then(function (r) { return r.ok ? r.json() : []; }).then(render).catch(function () {});
  }
  function place(b) {
    var anchor = document.getElementById("content");
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(b, anchor); else document.body.insertBefore(b, document.body.firstChild);
  }
  var noticed = {};
  function notices() {  // reading never clears a notice: only "Got it" does (the id goes back to the server)
    fetch("/api/notices", {headers: {"Accept": "application/json"}}).then(function (r) { return r.ok ? r.json() : []; }).then(function (items) {
      items.forEach(function (n) {
        if (noticed[n.id]) return;
        noticed[n.id] = true;
        var b = el("div", "", "orch-notice"); b.setAttribute("role", "status");
        b.className = "banner info orch-notice"; b.style.cssText = "margin:8px 16px 0";
        b.appendChild(el("div", n.text));
        var x = el("button", "Got it"); x.type = "button"; x.style.marginTop = "8px";
        x.onclick = function () {
          fetch("/api/act", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({op: "notice.ack", args: {id: n.id}})}).then(function (r) { if (r.ok) b.remove(); });
        };
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

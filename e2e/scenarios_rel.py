"""Relay (R) scenarios: the orch CLI for what a workspace does, HTTP for rule violations and admin."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from lib import Fail, Skip, check, http, scenario, tar_gz
from scenarios_ws import _fake_agent, tload

SECRET = "SECRET-PLAIN-MARKER-7f3a"


def ids(e):
    return e.relay_all()


def inbox(e, ws):
    return e.orchj(ws, "relay", "inbox")


def tickets(e, ws):
    return [json.loads(p.read_text()) for p in sorted((e.ws(ws) / ".orch/tickets").glob("t_*.json"))]


@scenario("R1")
def r1(e):
    """Admin adds three workspaces with description/tags, sets rules; connect works; onboarding script served."""
    i = ids(e)
    for n in i:
        prompt = e.prompts[("rel", n)]
        check("orch addon add relay --yes" in prompt and "orch relay connect" in prompt and i[n] in prompt, f"{n} prompt: {prompt[:80]}")
        who = e.orchj(n, "relay", "whoami")
        check(who["id"] == i[n], f"whoami {who}")
        check((e.ws(n) / ".agents/skills/orch-relay/SKILL.md").is_file(), f"{n}: skill missing")
        check("<!-- orch:addon:relay -->" in (e.ws(n) / "AGENTS.md").read_text(), f"{n}: AGENTS block")
    rules = e.rel.admin.call("GET", "/admin/api/rules").json()["rules"]
    mine = [r for r in rules if r["from"] == i["Pilatus"] and r["to"] == i["Reports"]]
    check(mine and all(mine[0][k] for k in ("text", "files", "delegate", "start")), f"rules {rules}")
    check(http("GET", e.rel.url + "/onboarding.sh").status == 200, "onboarding.sh")
    return "onboarding line on a machine without orch not run (needs a fresh VM)"


@scenario("R14")
def r14(e):
    """After refresh Pilatus's workspaces.json lists Reports and Home as specified; tag edit shows next refresh."""
    i = ids(e)
    e.orch("Pilatus", "relay", "refresh")
    p = e.ws("Pilatus") / ".agents/skills/orch-relay/workspaces.json"
    d = json.loads(p.read_text())
    by = {w["id"]: w for w in d["workspaces"]}
    rep, home = by[i["Reports"]], by[i["Home"]]
    check(all(rep["can_send"].values()), f"Reports can_send {rep['can_send']}")
    check(home["accepts_from"] == {"text": True, "files": False, "delegate": False, "start": False}, f"Home accepts {home['accepts_from']}")
    check(rep["description"] and "reports" in rep["tags"], "Reports description/tags missing")
    r = e.rel.admin.call("PATCH", f"/admin/api/workspaces/{i['Reports']}", {"tags": ["reports", "weekly", "edited"]})
    check(r.status == 200, f"tag edit {r}")
    e.orch("Pilatus", "relay", "refresh")
    d = json.loads(p.read_text())
    check("edited" in {w["id"]: w for w in d["workspaces"]}[i["Reports"]]["tags"], "tag edit not in the next refresh")
    return "agent picking Reports from the file: agent lane"


@scenario("R2")
def r2(e):
    """Pilatus sends text + file to Reports; Reports sees both in its inbox; file sha256 matches."""
    i = ids(e)
    f = e.tmp / "r2-data.bin"
    f.write_bytes(os.urandom(200_000))
    e.orch("Pilatus", "relay", "send", i["Reports"], "hello reports")
    e.orch("Pilatus", "relay", "send", i["Reports"], "the file", "--file", str(f))
    items = inbox(e, "Reports")
    txt = [m for m in items if m["type"] == "text" and m["body"]["text"] == "hello reports"]
    fil = [m for m in items if m["type"] == "file"]
    check(txt and fil, f"inbox lacks text or file: {[m['type'] for m in items]}")
    out = e.orchj("Reports", "relay", "download", fil[0]["id"])
    got = Path(out["path"]).read_bytes()
    check(hashlib.sha256(got).hexdigest() == hashlib.sha256(f.read_bytes()).hexdigest() == fil[0]["body"]["sha256"], "sha256 differs")
    check("/received/" in out["path"], f"download path {out['path']}")


@scenario("R3")
def r3(e):
    """No rule -> 403 not_allowed; spoofed from -> 403; foreign blob id -> 403."""
    i = ids(e)
    m = e.msg(i["Reports"], i["Pilatus"], "text", {"text": "x"})
    r = e.rapi("Reports", "POST", "/v1/messages", m)
    check(r.status == 403 and (r.json() or {}).get("error") == "not_allowed", f"no rule: {r}")
    m = e.msg(i["Pilatus"], i["Reports"], "text", {"text": "spoof"})
    check(e.rapi("Reports", "POST", "/v1/messages", m).status == 403, "spoofed from accepted")
    blob = e.rapi("Pilatus", "POST", "/v1/blobs", b"pilatus-only bytes").json()
    # Reports has no files rule at all, and the blob is not its own: either way 403
    m = e.msg(i["Reports"], i["Pilatus"], "file", {"blob_id": blob["blob_id"], "name": "x", "size": blob["size"], "sha256": blob["sha256"]})
    check(e.rapi("Reports", "POST", "/v1/messages", m).status == 403, "foreign blob accepted")
    # stronger: Home may send text to Pilatus but has no files rule; Pilatus->Reports has files: Reports cannot read Pilatus's blob
    check(e.rapi("Reports", "GET", f"/v1/blobs/{blob['blob_id']}").status == 404, "Reports can read a blob nobody sent it")
    # and Pilatus cannot send Reports a file message with someone else's blob (Home's)
    hb = e.rapi("Home", "POST", "/v1/blobs", b"home bytes").json()
    m = e.msg(i["Pilatus"], i["Reports"], "file", {"blob_id": hb["blob_id"], "name": "x", "size": hb["size"], "sha256": hb["sha256"]})
    check(e.rapi("Pilatus", "POST", "/v1/messages", m).status == 403, "Pilatus sent Home's blob")


@scenario("R4")
def r4(e):
    """Reports offline (not polling), Pilatus sends 3 messages: all arrive in order on the next inbox."""
    i = ids(e)
    for n in (1, 2, 3):
        e.orch("Pilatus", "relay", "send", i["Reports"], f"r4-msg-{n}")
    raw = e.rapi("Reports", "GET", "/v1/inbox").json()["items"]
    order_raw = [m["body"]["text"] for m in raw if m["type"] == "text" and m["body"]["text"].startswith("r4-msg")]
    check(order_raw == ["r4-msg-1", "r4-msg-2", "r4-msg-3"], f"relay order {order_raw}")
    items = inbox(e, "Reports")
    cli = [m["body"]["text"] for m in items if m["type"] == "text" and m["body"]["text"].startswith("r4-msg")]
    check(cli == ["r4-msg-1", "r4-msg-2", "r4-msg-3"], f"CLI order {cli}")


@scenario("R5")
def r5(e):
    """Same message twice = duplicate; same id other text = 409; processed once (inbox-seen)."""
    i = ids(e)
    m = e.msg(i["Pilatus"], i["Reports"], "text", {"text": "dup-test"})
    r1_ = e.rapi("Pilatus", "POST", "/v1/messages", m)
    r2_ = e.rapi("Pilatus", "POST", "/v1/messages", m)
    check(r1_.status == 201 and r2_.status == 200 and (r2_.json() or {}).get("duplicate") is True, f"dup {r1_} {r2_}")
    m2 = dict(m, body={"text": "other"})
    check(e.rapi("Pilatus", "POST", "/v1/messages", m2).status == 409, "same id other text not 409")
    raw = e.rapi("Reports", "GET", "/v1/inbox").json()["items"]
    check(sum(1 for x in raw if x["id"] == m["id"]) == 1, "stored twice")
    items = inbox(e, "Reports")
    check(any(x["id"] == m["id"] for x in items), "not in the CLI inbox")
    first = e.orchj("Reports", "relay", "done", m["id"])
    second = e.orchj("Reports", "relay", "done", m["id"])
    check(first["new"] is True and second["new"] is False, f"done twice: {first} {second}")
    check(m["id"] in json.loads((e.ws("Reports") / ".orch/inbox-seen.json").read_text()), "inbox-seen.json lacks the id")
    # delivered again by the relay (not acked case): the same id is not printed twice
    again = [x for x in inbox(e, "Reports") if x["id"] == m["id"]]
    check(not again, "a processed message was printed again")


def _agent_runs(log: Path) -> int:
    import re
    return len(re.findall(r"^end \d+$", log.read_text(), re.M)) if log.exists() else 0  # one end line per finished run


def _automation_on(e, ws):
    """R6-R8 need the automation add-on in this workspace; A5 turns it on too, but the R group runs alone as well."""
    e.sh(["orch", "addon", "add", "automation", "--yes"], cwd=e.ws(ws), check_rc=True, timeout=600)


def _sched_once(e, ws):
    rc, out, err = e.sh(["orch", "automation", "run", "--once"], cwd=e.ws(ws), timeout=120)
    check(rc == 0, f"automation run --once: {err or out}")
    for _ in range(40):  # core starts the agent detached: wait until no run holds a ticket any more
        if not list((e.ws(ws) / ".orch/run/tickets").glob("*.json")):
            break
        time.sleep(0.5)


@scenario("R6")
def r6(e):
    """delegate: nothing runs until the human allows once; then one ticket (no double) and the agent starts."""
    e.ensure_addons()
    _automation_on(e, "Reports")
    i = ids(e)
    log = _fake_agent(e, e.ws("Reports"))
    before = len(tickets(e, "Reports"))
    e.orch("Pilatus", "relay", "delegate", i["Reports"], "R6 delegated work", "--text", "please do it", "--check", "step one")
    it = [m for m in inbox(e, "Reports") if m["type"] == "delegate"]
    check(it and it[-1]["allowed"] is False, f"delegate should wait for the human: {it}")
    mid = it[-1]["id"]
    _sched_once(e, "Reports")
    asking = [t for t in tickets(e, "Reports") if (t.get("ext", {}).get("relay") or {}).get("allow_message") == mid]
    check(len(asking) == 1 and asking[0]["status"] == "waiting", f"one waiting allow-question ticket expected: {asking}")
    check(_agent_runs(log) == 0 and len(tickets(e, "Reports")) == before + 1, "automation acted before the human allowed")
    e.orch("Reports", "relay", "allow", mid, "--once")
    allow = [m for m in inbox(e, "Pilatus") if m["type"] == "allow"]
    check(allow and allow[-1]["reply_to"] == mid, f"allow message back to Pilatus: {allow}")
    _sched_once(e, "Reports")
    new = [t for t in tickets(e, "Reports") if "R6 delegated work" in t["title"] or (t.get("ext", {}).get("relay") or {}).get("message") == mid]
    check(_agent_runs(log) == 1, f"agent runs: {_agent_runs(log)}")
    check(len(tickets(e, "Reports")) - before == len(new), f"unrelated tickets appeared: {[t['title'] for t in tickets(e, 'Reports')]}")
    check(len(new) == 1, f"DOUBLE TICKET: {len(new)} tickets for one delegate: {[(t['id'], t['title']) for t in new]}")
    check(new[0]["id"] == asking[0]["id"], "the allow-question ticket is the one that runs")
    check([c["text"].endswith(": step one") and c["text"].startswith("From ") for c in new[0]["checklist"]] == [True], f"checklist not copied: {new[0]['checklist']}")
    _sched_once(e, "Reports")
    check(_agent_runs(log) == 1, "once-allow was used twice")


@scenario("R7")
def r7(e):
    """start weekly-report: allow --permanent; next start with the token runs without asking; admin allows list."""
    e.ensure_addons()
    _automation_on(e, "Reports")
    i = ids(e)
    log = _fake_agent(e, e.ws("Reports"))
    base = _agent_runs(log)
    e.orch("Pilatus", "relay", "start", i["Reports"], "weekly-report", "run the weekly report")
    st = [m for m in inbox(e, "Reports") if m["type"] == "start" and m["body"]["key"] == "weekly-report"]
    check(st and st[-1]["allowed"] is False, "first start must wait for the human")
    e.orch("Reports", "relay", "allow", st[-1]["id"], "--permanent")
    inbox(e, "Pilatus")  # stores the received allow token
    _sched_once(e, "Reports")
    # the message that was just allowed runs right away (like --once) ...
    check(_agent_runs(log) == base + 1, "the message allowed with --permanent did not run")
    e.orch("Pilatus", "relay", "start", i["Reports"], "weekly-report", "second time")
    st2 = [m for m in inbox(e, "Reports") if m["type"] == "start" and m["body"].get("text") == "second time"]
    check(st2 and st2[-1]["allowed"] is True, f"second start with token must be allowed: {st2}")
    _sched_once(e, "Reports")
    check(_agent_runs(log) == base + 2, "second start (with token) did not run")
    keyed = [t for t in tickets(e, "Reports") if (t.get("ext", {}).get("relay") or {}).get("start_key") == "weekly-report"]
    check(len(keyed) == 1, f"second start made another ticket: {len(keyed)}")
    al = e.rel.admin.call("GET", "/admin/api/allows").json()["items"]
    check(any(a["kind"] == "start" and a["key"] == "weekly-report" and a["mode"] == "permanent" and a["from"] == i["Reports"] for a in al), f"admin allows: {al}")


@scenario("R8")
def r8(e):
    """start with a wrong token, or with another key's token: not run, waits for the human."""
    e.ensure_addons()
    _automation_on(e, "Reports")
    i = ids(e)
    if not (e.ws("Pilatus") / ".orch/secrets/allows.json").exists():
        r7(e)
    # nothing else may be due in Reports, so any agent start below comes from the bad-token messages
    due = [t["id"] for t in tickets(e, "Reports") if t["status"] in ("open", "active", "waiting")
           and (((t.get("ext") or {}).get("automation") or {}).get("recurring") or (t.get("waiting_on") or {}).get("kind") == "time")]
    check(not due, f"Reports has scheduled tickets left from earlier scenarios: {due}")
    log = _fake_agent(e, e.ws("Reports"))
    allows = json.loads((e.ws("Pilatus") / ".orch/secrets/allows.json").read_text())
    tok = allows["received"][0]["token"]
    for key, token in (("weekly-report", "ora_" + "A" * 22), ("other-task", tok)):
        m = e.msg(i["Pilatus"], i["Reports"], "start", {"key": key, "text": "sneaky", "allow_token": token})
        check(e.rapi("Pilatus", "POST", "/v1/messages", m).status == 201, "relay should accept (receiver checks)")
        items = [x for x in inbox(e, "Reports") if x["id"] == m["id"]]
        check(items and items[0]["allowed"] is False, f"{key} with bad token must not be allowed: {items}")
    _sched_once(e, "Reports")
    ran = log.read_text()
    runs = sorted(p.name for p in (e.ws("Reports") / ".orch/run/logs").glob("*.log"))
    check(_agent_runs(log) == 0, f"agent ran for a message with a bad token: fake agent log {ran!r}; run logs {runs}")


@scenario("R9")
def r9(e):
    """Webhook once: ticket waits on it, curl wakes the automation's agent; second call -> 410."""
    e.ensure_addons()
    ids(e)
    ws = e.ws("Pilatus")
    log = _fake_agent(e, ws)
    t = e.orchj("Pilatus", "ticket", "new", "R9 webhook")["id"]
    w = e.orchj("Pilatus", "relay", "webhook", "new", "--once", "--ticket", t)
    check(w["url"].startswith(e.rel.url + "/webhook/") or "/webhook/" in w["url"], f"url {w}")
    url = w["url"].replace("https://relay.severin.io", e.rel.url) if e.mode == "local" else w["url"]
    e.orch("Pilatus", "wait", t, "--on", f"external:{w['id']}")
    r = http("POST", url, {"Content-Type": "application/json"}, b'{"hello":"world"}')
    check(r.status == 202, f"webhook call {r}")
    check(http("POST", url, None, b"x").status == 410, "second call must be 410")
    _sched_once(e, "Pilatus")
    check(_agent_runs(log) == 1, f"automation did not wake the agent: {_agent_runs(log)}")
    d = tload(ws, t)
    check(any("Automation started" in h["text"] for h in d["history"]), "no history entry")


@scenario("R10")
def r10(e):
    """Permanent webhook with a GitHub-style payload: one message per call; wrong token 401."""
    ids(e)
    w = e.orchj("Pilatus", "relay", "webhook", "new", "--permanent")
    url = w["url"].replace("https://relay.severin.io", e.rel.url) if e.mode == "local" else w["url"]
    payload = json.dumps({"action": "closed", "pull_request": {"merged": True, "number": 88}}).encode()
    for n in range(2):
        r = http("POST", url, {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": f"d{n}", "Content-Type": "application/json"}, payload)
        check(r.status == 202, f"call {n}: {r}")
    bad = url.split("token=")[0] + "token=whk_wrong"
    check(http("POST", bad, None, payload).status == 401, "wrong token not 401")
    got = [m for m in inbox(e, "Pilatus") if m["type"] == "webhook" and m["body"]["webhook_id"] == w["id"]]
    check(len(got) == 2 and got[0]["body"]["headers"].get("x-github-event") == "pull_request", f"webhook messages: {len(got)}")
    check(json.loads(got[0]["body"]["payload"])["pull_request"]["merged"] is True, "payload not kept")
    e.orch("Pilatus", "relay", "webhook", "delete", w["id"])


@scenario("R11")
def r11(e):
    """Shared skill + MCP + credential assigned to Home: refresh installs; unassign removes; ../ archive rejected."""
    i = ids(e)
    skill = tar_gz({"acme-sql/SKILL.md": "---\nname: acme-sql\ndescription: SQL helper\n---\nUse sql.\n"})
    ad = e.rel.admin
    check(ad.call("PUT", "/admin/api/shared/skills/acme-sql", raw=skill).status == 200, "upload skill")
    check(ad.call("PUT", "/admin/api/shared/mcp/acme-docs", {"config": {"command": "npx", "args": ["acme-docs"]}}).status == 200, "mcp")
    check(ad.call("PUT", "/admin/api/shared/credentials/ACME_TOKEN", {"value": "acme-secret-value"}).status == 200, "cred")
    try:
        check(ad.call("PUT", f"/admin/api/shared/assign/{i['Home']}", {"skills": ["acme-sql"], "mcp": ["acme-docs"], "credentials": ["ACME_TOKEN"]}).status == 200, "assign")
        hint = [m for m in inbox(e, "Home") if m["type"] == "refresh-hint"]
        check(hint, "Home got no refresh-hint")
        e.orch("Home", "relay", "refresh")
        home = e.ws("Home")
        check((home / ".agents/skills/acme-sql/SKILL.md").is_file(), "skill not installed")
        check(json.loads((home / ".orch/secrets/credentials.json").read_text()) == {"ACME_TOKEN": "acme-secret-value"}, "credentials.json")
        check("acme-docs" in json.loads((home / ".orch/secrets/mcp.json").read_text())["mcpServers"], "mcp.json")
        check(not (e.ws("Pilatus") / ".agents/skills/acme-sql").exists(), "Pilatus got the skill")
        e.orch("Pilatus", "relay", "refresh")
        check(not (e.ws("Pilatus") / ".agents/skills/acme-sql").exists(), "Pilatus got the skill after refresh")
        ad.call("PUT", f"/admin/api/shared/assign/{i['Home']}", {"skills": [], "mcp": [], "credentials": []})
        e.orch("Home", "relay", "refresh")
        check(not (home / ".agents/skills/acme-sql").exists(), "skill not removed after unassign")
        check(json.loads((home / ".orch/secrets/credentials.json").read_text()) == {}, "credential not removed")
        evil = tar_gz({"../x": "evil", "SKILL.md": "x"})
        r = ad.call("PUT", "/admin/api/shared/skills/evil", raw=evil)
        check(r.status in (400, 422), f"a ../ archive was accepted by the admin API: {r.status}")
    finally:
        for kind, n in (("skills", "acme-sql"), ("mcp", "acme-docs"), ("credentials", "ACME_TOKEN"), ("skills", "evil")):
            ad.call("DELETE", f"/admin/api/shared/{kind}/{n}")


@scenario("R12")
def r12(e):
    raise Skip("agent scenario (another lane)")


@scenario("R13")
def r13(e):
    """Admin reads messages decrypted; the relay DB holds no plain bodies (local)."""
    i = ids(e)
    e.orch("Pilatus", "relay", "send", i["Reports"], SECRET)
    r = e.rel.admin.call("GET", f"/admin/api/messages?workspace={i['Reports']}&type=text")
    check(r.status == 200 and SECRET in r.text, f"admin cannot read the message: {r.status}")
    if e.mode == "local":
        blob = b"".join(p.read_bytes() for p in e.rel.data.glob("relay.db*"))
        check(SECRET.encode() not in blob, "plain message body found in the database files")
        check(b"acme-secret-value" not in blob, "credential value found in the database")
        for p in (e.rel.data / "blobs").glob("*"):
            check(b"pilatus-only bytes" not in p.read_bytes(), "plain blob on disk")


@scenario("R15")
def r15(e):
    """Phone paired with Pilatus writes (the text becomes a ticket); Pilatus answers it (relay send ph_ + ask --phone), refresh lists the phone;
    Home (not paired with that phone) cannot reach it and is told what to do."""
    from scenarios_misc import pair, phone

    i, ph = pair(e, ["Pilatus"], label="R15 iPhone")
    r = phone(e, ph, "POST", "/v1/phone/send", {"to": i["Pilatus"], "text": "can you answer my phone"})
    check(r.status == 201, f"phone send: {r}")
    _, out, _ = e.orch("Pilatus", "relay", "refresh")
    check("phone" in out and "0 phones" not in out, f"refresh: {out}")
    d = json.loads((e.ws("Pilatus") / ".agents/skills/orch-relay/workspaces.json").read_text())
    check(ph[0] in [p["id"] for p in d.get("phones", [])], f"workspaces.json phones: {d.get('phones')}")
    _, out, _ = e.orch("Pilatus", "relay", "inbox")
    # a text from the phone becomes a ticket (the inbox says which); the text is the ticket's content
    check("Message from R15 iPhone" in out and "new ticket" in out, f"inbox: {out}")
    made = [t for t in tickets(e, "Pilatus") if "can you answer my phone" in json.dumps(t)]
    check(len(made) == 1, f"the phone text did not become exactly one ticket: {[t.get('title') for t in tickets(e, 'Pilatus')]}")
    e.orch("Pilatus", "relay", "send", ph[0], "yes, I can answer your phone")
    e.orch("Pilatus", "relay", "send", "R15 iPhone", "by name too")
    t = e.orchj("Pilatus", "ticket", "new", "R15 phone question")["id"]
    e.orch("Pilatus", "ask", t, "Ship it?", "--option", "yes", "--option", "no", "--phone")
    got = [x["message"]["body"]["text"] for x in phone(e, ph, "GET", "/v1/phone/messages").json()["items"]]
    # ask --phone also sends the ticket snapshot as a quiet note (mobile chat, V2-M1)
    check(got[:5] == ["Waiting for your answer", "by name too", "yes, I can answer your phone", "Got it: can you answer my phone", "can you answer my phone"], f"phone messages: {got}")
    qs = [q for q in phone(e, ph, "GET", "/v1/phone/questions").json()["items"] if q["message"].get("ticket") == t]
    check(len(qs) == 1, f"phone questions: {qs}")
    # Home is not on this phone's list: refused with what to do, and its directory lists no such phone
    rc, out, err = e.orch("Home", "relay", "send", ph[0], "hi", ok=False)
    check(rc != 0 and "Phones" in (out + err) and "admin" in (out + err), f"Home -> phone: {rc} {out} {err}")
    e.orch("Home", "relay", "refresh")
    d = json.loads((e.ws("Home") / ".agents/skills/orch-relay/workspaces.json").read_text())
    check(ph[0] not in [p["id"] for p in d.get("phones", [])], "Home lists a phone it may not reach")
    check(not [x for x in phone(e, ph, "GET", "/v1/phone/messages").json()["items"] if x["message"]["body"]["text"] == "hi"], "Home reached the phone")
    return "showing the reply in the iPhone app: mobile lane (GET /v1/phone/messages, text push)"

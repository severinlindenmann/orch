"""Python lanes: B agent run + latency, W workspace to workspace, U subscribers, Z production smoke.

Timing probes are what the owner cares about most: how fast does the dashboard (and the phone) show a change.
"""
from __future__ import annotations

import json
import stat
import time
from pathlib import Path

import lib
from lane import Blocked, Lane, Skipped
from receiver import Receiver

STATE_POLL_S = 0.5  # /api/state runs `orch` subprocesses on every call; 0.5 s keeps the probe light and still < the page's 3 s poll


def act(dash: str, op: str, args: dict) -> lib.Resp:
    return lib.http("POST", dash + "/api/act", {"Content-Type": "application/json", "Origin": dash},
                    {"op": op, "args": args})


def state(dash: str) -> dict:
    r = lib.http("GET", dash + "/api/state", timeout=20)
    return r.json() or {}


def poll(dash: str, pred, secs: float, every: float = STATE_POLL_S):
    """Return seconds until pred(state) is truthy (from now), or None."""
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            s = state(dash)
            if pred(s):
                return time.time() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(every)
    return None


def _ticket(s: dict, tid: str) -> dict:
    return next((t for t in s.get("tickets", []) if t.get("id") == tid), {})


# ---------------------------------------------------------------------------------------------- lane B


FAKE_AGENT = r"""#!/bin/sh
# fake agent for the timing dry run: asks one question, waits for the answer, finishes the task with proof
T="${ORCH_TICKET:-$1}"
echo "$(python3 -c 'import time;print(time.time())') start" >> "$FAKE_LOG"
orch ask "$T" "Which greeting should I write?" --option Hi --option Hello --recommend Hi >/dev/null 2>&1
echo "$(python3 -c 'import time;print(time.time())') answered" >> "$FAKE_LOG"
orch check done "$T" c1 --note "wrote hello.txt" --by agent:fake >/dev/null 2>&1 || orch check done "$T" c1 --note "done" >/dev/null 2>&1
echo "$(python3 -c 'import time;print(time.time())') done" >> "$FAKE_LOG"
"""


def lane_b(env, out: Path, real_agents: bool, runs: int = 3) -> Lane:
    L = Lane("B", "Agent run and latency", out)
    e = env.e
    ws = "Pilatus"
    w = e.ws(ws)
    dash = env.urls.get("pilatus")
    if not dash:
        L.step("B00", "dashboard of Pilatus is up", lambda st: (_ for _ in ()).throw(Blocked("no dashboard url")))
        return L
    fake_log = env.root / "fake-agent.log"
    cfg = w / ".orch" / "config.toml"
    if real_agents:
        agent_line = ("claude -p {prompt} --permission-mode acceptEdits --max-turns 20 "
                      "--allowedTools 'Bash(orch:*)' Read Write Edit")
        cfg.write_text(f'[workspace]\nagent = "e2eagent"\n\n[agents.e2eagent]\nadapter = "generic"\ncommand = {json.dumps(agent_line)}\n\n[automation]\ninterval = 2\n')
    else:
        script = env.root / "fake-agent.sh"
        script.write_text(FAKE_AGENT)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        cfg.write_text('[workspace]\nagent = "e2eagent"\n\n[agents.e2eagent]\nadapter = "generic"\n'
                       f'command = {json.dumps(f"env FAKE_LOG={fake_log} sh {script} {{prompt}}")}\n\n[automation]\ninterval = 2\n')
        L.notes.append("fake scripted agent (dry run): latency of orch + dashboard only, not of a model")
    samples = {k: [] for k in ("start_to_working", "ask_to_needs", "answer_to_history", "done_to_dashboard")}

    def one_run(i: int):
        def go(st):
            title = f"Write hello {i}"
            r = act(dash, "ticket.new", {"title": title, "note": "Write hello.txt with the greeting I choose."})
            if r.status != 200:
                raise RuntimeError(f"ticket.new {r.status} {r.text[:150]}")
            tid = next(t["id"] for t in r.json()["tickets"] if t["title"] == title)
            e.sh(["orch", "check", "add", tid, "Write hello.txt"], cwd=w)
            t0 = time.time()
            rs = act(dash, "run.start", {"ticket": tid})
            st["actions"].append({"do": "run.start", "ms": int((time.time() - t0) * 1000), "status": "ok" if rs.status == 200 else "fail"})
            if rs.status != 200:
                raise RuntimeError(f"run.start {rs.status} {rs.text[:150]}")
            a = poll(dash, lambda s: bool(s.get("runs", {}).get(tid)) or _ticket(s, tid).get("status") == "active", 40)
            samples["start_to_working"].append(a if a is not None else 40.0)
            n = poll(dash, lambda s: any(tid in json.dumps(x) for x in s.get("needs", [])), 60)
            if n is None:
                raise RuntimeError("the question never reached 'Needs you'")
            samples["ask_to_needs"].append(time.time() - t0 - (a or 0))
            qid = None
            for x in state(dash).get("needs", []):
                if tid in json.dumps(x):
                    st["needs_item"] = x
                    qid = (x.get("answer") or {}).get("question") or x.get("question")
            for q in _ticket(state(dash), tid).get("questions", []):
                if q.get("answer") is None and not q.get("answered_at"):
                    qid = q.get("id")
            ra = act(dash, "answer", {"ticket": tid, "question": qid, "answer": "Hi"}) if qid else None
            if ra is None or ra.status != 200:
                st["note"] = f"answer op: {ra.status if ra else 'no question id'} {(ra.text[:120] if ra else '')}"
                e.sh(["orch", "answer", tid, qid or "q1", "Hi"], cwd=w)
            h = poll(dash, lambda s: "answered" in json.dumps(_ticket(s, tid).get("history", [])).lower(), 20)
            samples["answer_to_history"].append(h if h is not None else 20.0)
            all_done = lambda s: bool(_ticket(s, tid).get("checklist")) and all(c.get("done") for c in _ticket(s, tid)["checklist"])
            d = poll(dash, all_done, 90)
            if d is None:
                s_ = state(dash)
                raise RuntimeError("the task was never checked off: " + json.dumps({"ticket": _ticket(s_, tid), "run": s_.get("runs", {}).get(tid),
                                   "needs": s_.get("needs")})[:900])
            fin = _ticket(state(dash), tid).get("status")
            if fin != "done":
                L.finding("status", f"Ticket stays '{fin}' after its last task is checked", f"Run {i}: the agent checked the last task with proof, "
                          f"but the ticket status is still '{fin}' (Home shows it as not finished).",
                          "When the last task is done and the agent ends the run, the status should say Done (or Waiting for you to close), "
                          "never the same word as while it works. Belongs to the statuses work (core-flow).", step=f"B{i:02d}")
            samples["done_to_dashboard"].append(d)
            st["note"] = f"{tid}: working {samples['start_to_working'][-1]:.1f}s, needs {samples['ask_to_needs'][-1]:.1f}s"
        return go

    for i in range(1, runs + 1):
        L.step(f"B{i:02d}", f"Create ticket, Start, question, answer, done (run {i})", one_run(i),
               expect="chip changes to working fast, question in Needs you, answer shown, ticket Done")
    L.probe("B-start", "Start click to dashboard shows a run", samples["start_to_working"], 2, 4)
    L.probe("B-needs", "Agent asks to Needs you on Home", samples["ask_to_needs"], 3, 5)
    L.probe("B-answer", "Answer click to history line", samples["answer_to_history"], 2, 4)
    L.probe("B-done", "Agent done to Done on dashboard", samples["done_to_dashboard"], 3, 5)
    return L


# ---------------------------------------------------------------------------------------------- lane W


def lane_w(env, out: Path) -> Lane:
    L = Lane("W", "Workspace to workspace", out)
    e = env.e
    pil, rep = e.ws("Pilatus"), e.ws("Reports")
    rid = env.vars["relay_id_reports"]
    s_inbox, s_dash = [], []

    def send(i):
        def go(st):
            body = f"hello from Pilatus {i} {int(time.time())}"
            t0 = time.time()
            rc, out_, err = e.sh(["orch", "relay", "send", rid, body], cwd=pil, timeout=60)
            if rc:
                raise RuntimeError((err or out_)[-200:])
            end = time.time() + 30
            seen = None
            while time.time() < end:
                rc, o, _ = e.sh(["orch", "relay", "inbox", "--json"], cwd=rep, timeout=30)
                if body in o:
                    seen = time.time() - t0
                    break
                time.sleep(0.5)
            if seen is None:
                raise RuntimeError("the message never reached the inbox of Reports")
            s_inbox.append(seen)
            dash = env.urls.get("reports")
            if dash:
                d = poll(dash, lambda s: body in json.dumps(s), 20)
                if d is None:
                    L.finding("latency", "Message from another workspace is not shown on the dashboard",
                              f"Send {i}: the text reached `relay inbox` in {seen:.1f} s but was not in the dashboard state of Reports after 20 more seconds.",
                              "Show arrivals from other workspaces on Home (Needs you or Recently) within 5 s, or say where to find them.",
                              step=f"W{i:02d}", severity="functional")
                else:
                    s_dash.append(seen + d)
        return go

    for i in range(1, 4):
        L.step(f"W{i:02d}", f"Send text Pilatus to Reports ({i}) and see it arrive", send(i),
               expect="the message is in the inbox of Reports and on its dashboard")
    L.probe("W-inbox", "Workspace to workspace: send to inbox", s_inbox, 2, 5)
    L.probe("W-dash", "Workspace to workspace: send to target dashboard", s_dash, 5, 8)

    def refused(st):
        rc, o, err = e.sh(["orch", "relay", "send", env.vars["relay_id_pilatus"], "no rule", "--file", str(env.root / "env.json")],
                          cwd=rep, timeout=60)
        if rc == 0:
            raise RuntimeError("a file was sent without a rule that allows files")
        if not (err or o).strip():
            raise RuntimeError("refusal has no reason")
        st["note"] = (err or o).strip()[:200]
    L.step("W04", "Send a file without a rule: refused with a reason", refused, expect="plain refusal reason")
    return L


# ---------------------------------------------------------------------------------------------- lane U


def lane_u(env, out: Path) -> Lane:
    L = Lane("U", "Subscribers", out)
    e = env.e
    rcv = Receiver()
    rcv.start()
    try:
        def create(st):
            r = e.rel.admin.call("GET", "/admin/api/subscribers")
            st["note"] = f"admin subscribers list {r.status}"
            if r.status == 404:
                raise Skipped("this relay has no subscribers API on this develop")
            if r.status != 200:
                raise RuntimeError(f"{r.status} {r.text[:150]}")
        L.step("U01", "Relay admin lists subscribers", create)
        L.step("U02", "Receiver is up", lambda st: lib.wait_http(rcv.url + "/health", 5) or (_ for _ in ()).throw(RuntimeError("receiver down")))
    finally:
        rcv.stop()
    return L


# ---------------------------------------------------------------------------------------------- lane Z


def lane_z(env, out: Path, prod: dict | None = None) -> Lane:
    L = Lane("Z", "Production smoke (read-only)", out)
    prod = prod or {}
    if not prod:
        L.step("Z01", "Production health", lambda st: (_ for _ in ()).throw(Skipped("no production URLs given (--prod relay=URL,publish=URL)")))
        return L
    for name, url in prod.items():
        def chk(st, url=url):
            r = lib.http("GET", url.rstrip("/") + "/health", timeout=15)
            if r.status != 200:
                raise RuntimeError(f"/health {r.status}")
        L.step(f"Z-{name}", f"{name} /health", chk)
    return L

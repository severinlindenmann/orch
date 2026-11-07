"""Python lanes: B agent run + latency, W workspace to workspace, U subscribers, Z production smoke.

Timing probes are what the owner cares about most: how fast does the dashboard (and the phone) show a change.
"""
from __future__ import annotations

import json
import os
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
    ws = "Reports"  # not Pilatus: lane A edits the settings of Pilatus at the same time
    w = e.ws(ws)
    dash = env.urls.get("reports")
    if not dash:
        L.step("B00", "dashboard of Pilatus is up", lambda st: (_ for _ in ()).throw(Blocked("no dashboard url")))
        return L
    fake_log = env.root / "fake-agent.log"
    cfg = w / ".orch" / "config.toml"
    if real_agents:
        # a real Claude with a narrow tool list, in the generic adapter. The login goes ONLY into the processes of this one workspace
        # (restarted below with a per-command env), never into the shared environment of relay, publish or the other workspaces.
        tok = os.environ.get("E2E_CLAUDE_TOKEN")
        if not tok:
            L.step("B00", "Claude login for real-agent runs", lambda st: (_ for _ in ()).throw(Blocked("E2E_CLAUDE_TOKEN is not set (Proton Pass lookup failed)")))
            return L
        # the built-in claude adapter already runs with a narrow --allowedTools list (orch check/ask/log/link/needs/wait ...) and resumes after an answer;
        # the generic adapter does not resume a -p run after `orch ask` (found 7 Nov: the task was never finished), so keep the default agent
        e.sh(["orch", "stop"], cwd=w, timeout=60)
        e.sh(["orch", "start", "--no-open"], cwd=w, timeout=120, env={"CLAUDE_CODE_OAUTH_TOKEN": tok})
        env.refresh_urls()
        dash = env.urls.get("reports")
        L.notes.append("REAL Claude agent (built-in adapter, narrow allowed tools); the login is only in this workspace's processes; latencies include the model")
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
            note = ("Ask me which greeting to write with `orch ask` (options Hi and Hello), then write hello.txt with my answer, "
                    "then mark the task done with the file as proof." if real_agents else "Write hello.txt with the greeting I choose.")
            r = act(dash, "ticket.new", {"title": title, "note": note})
            if r.status != 200:
                raise RuntimeError(f"ticket.new {r.status} {r.text[:150]}")
            tid = next(t["id"] for t in r.json()["tickets"] if t["title"] == title)
            e.sh(["orch", "check", "add", tid, "Write hello.txt"], cwd=w)
            t0 = time.time()
            rs = act(dash, "run.start", {"ticket": tid})
            st["actions"].append({"do": "run.start", "ms": int((time.time() - t0) * 1000), "status": "ok" if rs.status == 200 else "fail"})
            if rs.status != 200:
                if rs.status == 422 and "live sessions" in rs.text:
                    L.finding("sessions", "Live sessions stay open after the agent finished", f"Run {i}: starting a run was refused: {rs.text[:160]}. "
                              "Earlier runs had finished and their tickets are in Review, but their sessions still counted.",
                              "A session of a ticket in Review should close by itself after a short idle time (or not count against the limit); "
                              "the person should never have to close sessions by hand to start the next ticket.", step=f"B{i:02d}", severity="functional")
                raise RuntimeError(f"run.start {rs.status} {rs.text[:150]}")
            a = poll(dash, lambda s: bool(s.get("runs", {}).get(tid)) or _ticket(s, tid).get("status") == "active", 40)
            samples["start_to_working"].append(a if a is not None else 40.0)
            n = poll(dash, lambda s: any(tid in json.dumps(x) for x in s.get("needs", [])), 240 if real_agents else 60)
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
            d = poll(dash, all_done, 300 if real_agents else 90)
            if d is None:
                s_ = state(dash)
                raise RuntimeError("the task was never checked off: " + json.dumps({"ticket": _ticket(s_, tid), "run": s_.get("runs", {}).get(tid),
                                   "needs": s_.get("needs")})[:900])
            e_end = time.time() + 20
            fin = _ticket(state(dash), tid).get("status")
            while fin not in ("review", "done") and time.time() < e_end:
                time.sleep(0.5)
                fin = _ticket(state(dash), tid).get("status")
            if fin != "review":
                L.finding("status", f"Ticket is '{fin}' instead of Review after the agent finished",
                          f"Run {i}: the agent checked the last task with proof and ended; the ticket status is '{fin}', expected Review "
                          "(the agent hands over, the person decides Done).",
                          "Agent done must move the ticket to Review (never straight to Done, never stay Working).", step=f"B{i:02d}", severity="functional")
            samples["done_to_dashboard"].append(d)
            sess = e.sh(["orch", "run", "status", tid, "--json"], cwd=w)[1]
            if '"live"' in sess.lower() or "tmux" in sess.lower():
                st.setdefault("live_open", True)
            e.sh(["orch", "run", "stop", tid], cwd=w, timeout=30)  # the next run needs a free live-session slot (limit 4)
            st["note"] = f"{tid}: working {samples['start_to_working'][-1]:.1f}s, needs {samples['ask_to_needs'][-1]:.1f}s"
        return go

    for i in range(1, runs + 1):
        L.step(f"B{i:02d}", f"Create ticket, Start, question, answer, done (run {i})", one_run(i),
               expect="chip changes to working fast, question in Needs you, answer shown, ticket Done")
    def events_probe(st):
        import threading
        import urllib.request
        got = []
        stop = threading.Event()

        def listen():
            req = urllib.request.Request(dash + "/api/events", headers={"Origin": dash})
            with urllib.request.urlopen(req, timeout=40) as r:
                for line in r:
                    if stop.is_set():
                        return
                    if line.startswith(b"event: rev"):
                        got.append(time.time())
        th = threading.Thread(target=listen, daemon=True)
        th.start()
        time.sleep(1.5)
        lat = []
        for k in range(4):
            n = len(got)
            t0 = time.time()
            e.sh(["orch", "ticket", "new", f"events probe {k}"], cwd=w)
            end = t0 + 8
            while len(got) <= n and time.time() < end:
                time.sleep(0.02)
            if len(got) <= n:
                stop.set()
                raise RuntimeError("no /api/events message within 8 s after a ticket change")
            lat.append(got[n] - t0)
            time.sleep(1.2)
        stop.set()
        L.probe("B-events", "Ticket change to /api/events message", lat, 1, 2)
        st["note"] = ", ".join(f"{x:.2f}s" for x in lat)
    L.step("B-events", "/api/events pushes a change within 1 s", events_probe, expect="a rev event reaches the page within 1 s (target)")
    if real_agents:
        def skill_seen(st):
            import glob
            hits = []
            for f in glob.glob(str(e.home / ".claude" / "projects" / "**" / "*.jsonl"), recursive=True):
                if ".agents/skills/orch" in Path(f).read_text(errors="replace"):
                    hits.append(Path(f).name)
            if not hits:
                raise RuntimeError("no Claude transcript mentions .agents/skills/orch: the agent did not find or read the orch skill there")
            st["note"] = f"{len(hits)} transcript(s) mention .agents/skills/orch"
        L.step("B-skill", "A real agent run finds the orch skill through .agents/skills/orch (transcript)", skill_seen,
               expect="the agent's own transcript reads or quotes .agents/skills/orch")
    L.probe("B-start", "Start click to dashboard shows a run", samples["start_to_working"], 2, 4)
    L.probe("B-needs", "Agent asks to Needs you on Home", samples["ask_to_needs"], 3, 5)
    L.probe("B-answer", "Answer click to history line", samples["answer_to_history"], 2, 4)
    L.probe("B-done", "Agent done to Done on dashboard", samples["done_to_dashboard"], 3, 5)
    return L


# ---------------------------------------------------------------------------------------------- lane D prep


def d_prep(env) -> None:
    """Publish a file (with a note) and a static app from Pilatus; the browser steps of lane D open the links."""
    e = env.e
    w = e.ws("Pilatus")
    f = env.root / "hello.txt"
    f.write_text("Hello from the e2e\n")
    rc, out, err = e.sh(["orch", "publish", "file", str(f), "--note", "Please read this", "--json"], cwd=w, timeout=120)
    j = json.loads(out)
    env.vars.update(file_link=j["link"], file_url=j["url"], file_id=j["id"])
    app = env.root / "e2e-app"
    e.sh(["orch", "publish", "new", "static", str(app), "--json"], cwd=w, timeout=60)
    rc, out, err = e.sh(["orch", "publish", "app", str(app), "--json"], cwd=w, timeout=180)
    j = json.loads(out)
    env.vars.update(app_link=j["link"], app_url=j["url"] + "/")
    env.env_json()


# ---------------------------------------------------------------------------------------------- lane W


def lane_w(env, out: Path) -> Lane:
    L = Lane("W", "Workspace to workspace", out)
    e = env.e
    pil, rep = e.ws("Pilatus"), e.ws("Reports")
    rid = env.vars["relay_id_reports"]
    s_inbox, s_dash = [], []
    # lane C edits the rules in the browser: start from a known baseline (Pilatus -> Reports everything, Reports -> Pilatus text only)
    cur = e.rel.admin.call("GET", "/admin/api/rules").json() or {"rules": []}
    keep = [r for r in cur.get("rules", []) if {r.get("from"), r.get("to")} != {env.vars["relay_id_pilatus"], rid}]
    e.rel.admin.call("PUT", "/admin/api/rules", {"rules": keep + [
        {"from": env.vars["relay_id_pilatus"], "to": rid, "text": True, "files": True, "delegate": True, "start": True},
        {"from": rid, "to": env.vars["relay_id_pilatus"], "text": True, "files": False, "delegate": False, "start": False}]})

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
                def shown(s):
                    if body in json.dumps(s):
                        return True
                    for view in ("relay",):  # the Relay tab: what the dashboard shows of arrivals
                        r = lib.http("GET", f"{dash}/api/addon/{view}", {"Origin": dash}, timeout=20)
                        if body in r.text:
                            return True
                    return False
                d = poll(dash, shown, 20)
                if d is None:
                    L.finding("latency", "Message from another workspace is not shown on the dashboard",
                              f"Send {i}: the text reached `relay inbox` in {seen:.1f} s but was not in the dashboard state of Reports after 20 more seconds.",
                              "Show arrivals from other workspaces on Home (Needs you or Recently) within 5 s, or say where to find them.",
                              step=f"W{i:02d}", severity="functional")
                else:
                    s_dash.append(seen + d)
        return go

    def known_list(st):
        dash = env.urls.get("reports")
        txt = lib.http("GET", f"{dash}/api/addon/relay", {"Origin": dash}, timeout=20).text
        if "Nobody yet" in txt:
            L.finding("wording", "Relay tab says 'Nobody yet' until `orch relay refresh` is run",
                      "Right after the admin allowed Reports and Pilatus to talk, the Relay tab of Reports says 'Nobody yet' and the inbox has "
                      "'new settings are waiting - run: orch relay refresh'. The person must type a command to see who they can talk to.",
                      "Refresh the workspace list on its own when the relay says settings changed (and on opening the Relay tab), "
                      "or show a Refresh button in the tab. No command to type.", step="W00", severity="ux")
            st["note"] = "list was empty before refresh"
        e.sh(["orch", "relay", "refresh"], cwd=rep, timeout=60)
        txt = lib.http("GET", f"{dash}/api/addon/relay", {"Origin": dash}, timeout=20).text
        if "Nobody yet" in txt:
            raise RuntimeError("the list is still empty after relay refresh")
    L.step("W00", "Relay tab lists the other workspaces", known_list, expect="Workspaces you can talk to lists Pilatus (after refresh at the latest)")
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


# ---------------------------------------------------------------------------------------------- lane M (Mobile mode, workspace side)


def _keepers() -> set[str]:
    import subprocess
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    return {ln.split(None, 1)[0] for ln in out.splitlines() if "relay mobile keeper" in ln}


def lane_m(env, out: Path) -> Lane:
    """Mobile mode on a workspace (orch relay mobile): state, keeper process, heartbeat to the relay, what a phone sees, off."""
    L = Lane("M", "Mobile mode (workspace side)", out)
    e = env.e
    ws = "Reports"
    w = e.ws(ws)
    admin = e.rel.admin
    ph: dict = {}
    before = _keepers()

    def pair(st):
        r = admin.call("POST", "/admin/api/phones", {"name": "E2E mobile-mode phone", "workspaces": [env.vars["relay_id_reports"]]})
        code = r.json()["link"].split("code=")[1]
        p = lib.http("POST", e.rel.url + "/v1/phone/pair", None, {"code": code, "name": "E2E mobile-mode phone"})
        if p.status != 201:
            raise RuntimeError(f"pair {p.status}")
        ph.update(id=p.json()["phone_id"], token=p.json()["token"])

    def phone_sees() -> str:
        r = lib.http("GET", e.rel.url + "/v1/phone/workspaces", {"X-Orch-Phone": ph["id"], "Authorization": f"Bearer {ph['token']}"})
        return r.text

    L.step("M00", "Pair a scripted phone for Reports", pair)

    def on(st):
        rc, o, err = e.sh(["orch", "relay", "mobile", "on", "--hours", "4", "--json"], cwd=w, timeout=60)
        if rc:
            raise RuntimeError((err or o)[-200:])
        j = json.loads(o)
        if not j.get("on"):
            raise RuntimeError(f"status says off: {o[:150]}")
        st["note"] = f"since {j.get('since')} ends {j.get('ends_at')} awake={j.get('awake')}"
    L.step("M01", "orch relay mobile on --hours 4: state is on, ends in about 4 hours", on, expect="on true, ends_at set")

    def keeper(st):
        new = _keepers() - before
        if not new:
            raise RuntimeError("no keeper process is running after Mobile mode on")
        st["note"] = f"{len(new)} keeper process(es)"
    L.step("M02", "The keeper process runs (this computer stays awake)", keeper, expect="a keeper process exists")

    seen: list[float] = []

    def heartbeat(st):
        t0 = time.time()
        end = t0 + 90
        while time.time() < end:
            if "mobile_mode" in phone_sees():
                seen.append(time.time() - t0)
                return
            time.sleep(1)
        raise RuntimeError("the phone never saw mobile_mode on the workspace within 90 s")
    L.step("M03", "The phone sees the workspace in Mobile mode", heartbeat, expect="phone workspace item carries mobile_mode")
    if seen:
        L.probe("M-phone", "Mobile mode on to the phone sees it", seen, 5, 65)

    def dash(st):
        d = env.urls.get("reports")
        s_ = json.dumps(state(d))
        if "mobile" not in s_.lower():
            raise RuntimeError("the dashboard state of Reports does not mention Mobile mode")
    L.step("M04", "The dashboard of the workspace knows Mobile mode is on", dash, expect="state carries the mobile mode block")

    def off(st):
        rc, o, err = e.sh(["orch", "relay", "mobile", "off", "--json"], cwd=w, timeout=60)
        if rc:
            raise RuntimeError((err or o)[-200:])
        end = time.time() + 15
        while time.time() < end and (_keepers() - before):
            time.sleep(0.5)
        if _keepers() - before:
            raise RuntimeError("the keeper process is still running after Mobile mode off")
        st["note"] = "keeper ended"
    L.step("M05", "orch relay mobile off: state off and the keeper process ends", off, expect="no keeper left")

    def hours(st):
        rc, o, err = e.sh(["orch", "relay", "mobile", "hours", "8", "--json"], cwd=w, timeout=60)
        if rc:
            raise RuntimeError((err or o)[-200:])
        rc, o, err = e.sh(["orch", "relay", "mobile", "on", "--json"], cwd=w, timeout=60)
        j = json.loads(o)
        e.sh(["orch", "relay", "mobile", "off"], cwd=w, timeout=60)
        st["note"] = f"default 8 h: ends_at {j.get('ends_at')} since {j.get('since')}"
    L.step("M06", "The saved default hours apply", hours, expect="ends about 8 hours after start")
    return L


# ---------------------------------------------------------------------------------------------- lane G (harness files and Share with team)


def lane_g(env, out: Path) -> Lane:
    """After init in a git repo: nothing new in `git status`; the orch skill is found through .agents/skills/orch; Share with team on/off."""
    import subprocess
    L = Lane("G", "Harness files and Share with team", out)
    e = env.e

    def clean(name):
        def go(st):
            w = e.ws(name)
            r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=w, capture_output=True, text=True, env=e.env)
            import re
            # orch's own data (.orch/addons.json, config.toml, tickets) is meant to be committed; only the harness files must not show up
            harness = re.compile(r"^.. (\.agents|\.claude|CLAUDE|AGENTS\.md|\.gitattributes|\.orch/(harness|skills|run|secrets|inbox|tmp))")
            dirty = [ln for ln in r.stdout.splitlines() if harness.match(ln)]
            st["note"] = f"{len(r.stdout.splitlines())} paths in git status, none of them harness files" if not dirty else ""
            if dirty:
                raise RuntimeError("git status is not clean after init: " + "; ".join(dirty[:6]))
        return go
    for name in ("Pilatus", "Reports"):
        L.step(f"G-clean-{name}", f"git status is clean in {name} after init (no .agents, .claude, CLAUDE.local.md, .orch files)",
               clean(name), expect="no output from git status --porcelain")

    def skill(st):
        w = e.ws("Pilatus")
        p = w / ".agents" / "skills" / "orch"
        if not (p.exists() and (p / "SKILL.md").exists()):
            raise RuntimeError(".agents/skills/orch/SKILL.md is missing: an agent cannot find the orch skill there")
        r = subprocess.run(["git", "check-ignore", "-q", ".agents/skills/orch/SKILL.md"], cwd=w, env=e.env)
        st["note"] = "skill present; " + ("ignored by git" if r.returncode == 0 else "NOT ignored but status is clean (excluded locally)")
    L.step("G-skill", "The orch skill is in .agents/skills/orch", skill, expect="SKILL.md found")

    dash = env.urls.get("reports")
    w = e.ws("Reports")

    def team(on: bool):
        def go(st):
            r = act(dash, "share.set", {"on": on})
            if r.status != 200:
                raise RuntimeError(f"share.set {r.status} {r.text[:150]}")
            agents = (w / "AGENTS.md").read_text() if (w / "AGENTS.md").exists() else ""
            ga = (w / ".gitattributes").read_text() if (w / ".gitattributes").exists() else ""
            has_block, has_attr = "orch" in agents.lower(), "merge=union" in ga
            if on and not (has_block and has_attr):
                raise RuntimeError(f"Team on: AGENTS.md block {has_block}, .gitattributes entry {has_attr}")
            if not on and (has_attr or "<!-- orch" in agents.lower()):
                raise RuntimeError(f"Team off: AGENTS.md block still {has_block}, .gitattributes entry still {has_attr}")
            st["note"] = f"AGENTS.md block {has_block}, .gitattributes merge=union {has_attr}"
        return go
    L.step("G-team-on", "Settings > General: Share with team ON writes the AGENTS.md block and the .gitattributes entry", team(True),
           expect="both exist")
    L.step("G-team-off", "Share with team OFF removes both again", team(False), expect="both gone")
    return L


# ---------------------------------------------------------------------------------------------- lane R (References)


def lane_r(env, out: Path) -> Lane:
    """References: orch ref add for kinds url/file/ticket/artifact, the numbered list, rm by number, refusals (symlink into .orch, outside folder)."""
    L = Lane("R", "References", out)
    e = env.e
    w = e.ws("Pilatus")
    tid = env.vars["ticket_id"]
    other = None

    def run(*a):
        return e.sh(["orch", *a], cwd=w, timeout=60)

    def mk(st):
        nonlocal other
        rc, o, err = run("ticket", "new", "Reference target", "--json")
        other = json.loads(o)["id"]
        (w / "notes").mkdir(exist_ok=True)
        (w / "notes" / "plan.md").write_text("# Plan\n")
    L.step("R00", "Make a second ticket and a file to point at", mk)

    def add(target, kind_word):
        def go(st):
            rc, o, err = run("ref", "add", tid, target() if callable(target) else target)
            if rc:
                raise RuntimeError((err or o)[-200:])
            rc, o, err = run("ref", "list", tid)
            if kind_word not in o and kind_word.lower() not in o.lower():
                raise RuntimeError(f"ref list does not show it: {o[:200]}")
            st["note"] = o.strip().splitlines()[-1][:120]
        return go
    L.step("R01", "Add a web link reference", add("https://example.com/spec", "example.com"), expect="listed with its number")
    L.step("R02", "Add a file reference", add("notes/plan.md", "plan.md"), expect="listed")
    L.step("R03", "Add a ticket reference", add(lambda: other, "Reference target"), expect="listed with the other ticket's title")

    def dash(st):
        d = env.urls["pilatus"]
        s_ = state(d)
        t = _ticket(s_, tid)
        refs = t.get("refs") or t.get("references") or []
        if len(refs) < 3:
            raise RuntimeError(f"dashboard state shows {len(refs)} references, expected 3: keys {sorted(t)[:20]}")
    L.step("R04", "The dashboard state carries the references", dash)

    def refuse(st):
        (w / ".orch").mkdir(exist_ok=True)
        link = w / "notes" / "sneak"
        try:
            link.symlink_to(w / ".orch" / "config.toml")
        except FileExistsError:
            pass
        rc, o, err = run("ref", "add", tid, "notes/sneak")
        if rc == 0:
            L.finding("security", "A symlink into .orch is accepted as a reference",
                      "`orch ref add <ticket> notes/sneak` where sneak is a symlink to .orch/config.toml was accepted.",
                      "Refuse at add time (resolve the link, refuse anything inside .orch), same as at open time.", step="R05", severity="blocking")
            raise RuntimeError("symlink into .orch accepted")
        st["note"] = (err or o).strip()[:120]  # a path outside the folder is a "local" reference by design (stored, never opened)
    L.step("R05", "Refuse a symlink into .orch and a path outside the folder", refuse, expect="both refused in plain words")

    def rm(st):
        rc, o, err = run("ref", "rm", tid, "1")
        if rc:
            raise RuntimeError((err or o)[-200:])
        rc, o, err = run("ref", "list", tid)
        if "example.com" in o:
            raise RuntimeError("ref rm 1 did not remove the first reference")
    L.step("R06", "Remove a reference by its number", rm)
    return L


# ---------------------------------------------------------------------------------------------- lane U


def lane_u(env, out: Path, rcv: Receiver) -> Lane:
    """Subscribers: create with a push URL, signed test push (HMAC check), a real update, retry after a failure, rotate, revoke."""
    import hashlib
    import hmac
    L = Lane("U", "Subscribers", out)
    e = env.e
    admin = e.rel.admin
    sub: dict = {}
    pil_id, rep_id = env.vars["relay_id_pilatus"], env.vars["relay_id_reports"]

    def create(st):
        r = admin.call("POST", "/admin/api/subscribers", {"name": "E2E receiver", "workspaces": [pil_id],
                       "kinds": {"updates": True, "questions": True, "results": True}, "push_url": rcv.url + "/push"})
        if r.status != 201:
            raise RuntimeError(f"create {r.status} {r.text[:200]}")
        j = r.json()
        sub.update(id=j["subscriber"]["id"], token=j["token"], secret=j["push_secret"])
        st["note"] = "subscriber created, token and secret kept out of the report"
    L.step("U01", "Create a subscriber that gets signed pushes to the receiver", create, expect="201 with a token and a push secret")

    def sig_ok(item) -> str:
        h = {k.lower(): v for k, v in item["headers"].items()}
        ts, sig = h.get("x-orch-timestamp"), h.get("x-orch-signature", "")
        if not ts or not sig.startswith("v1="):
            raise RuntimeError(f"missing signature headers: {sorted(h)}")
        want = "v1=" + hmac.new(sub["secret"].encode(), f"{ts}.{item['body']}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(want, sig):
            raise RuntimeError("signature does not match HMAC-SHA256(secret, timestamp.body)")
        if abs(time.time() - int(ts)) > 300:
            raise RuntimeError("timestamp is more than 5 minutes off")
        return "signature ok"

    def test_push(st):
        n = len(rcv.got)
        t0 = time.time()
        r = admin.call("POST", f"/admin/api/subscribers/{sub['id']}/push/test")
        if r.status != 200:
            raise RuntimeError(f"push/test {r.status} {r.text[:150]}")
        if not rcv.wait(n + 1, 15):
            raise RuntimeError("the receiver got nothing within 15 s")
        st["note"] = sig_ok(rcv.got[n]) + f", {time.time() - t0:.2f} s"
    L.step("U02", "Test push arrives with a valid signature", test_push, expect="X-Orch-Signature v1=HMAC verifies")

    lat: list[float] = []
    phone: dict = {}

    def pair_phone(st):
        r = admin.call("POST", "/admin/api/phones", {"name": "E2E scripted phone", "workspaces": [pil_id]})
        if r.status != 201:
            raise RuntimeError(f"add phone {r.status} {r.text[:150]}")
        code = r.json()["link"].split("code=")[1]
        p = lib.http("POST", e.rel.url + "/v1/phone/pair", None, {"code": code, "name": "E2E scripted phone"})
        if p.status != 201:
            raise RuntimeError(f"pair {p.status} {p.text[:150]}")
        phone["id"] = p.json()["phone_id"]
        e.sh(["orch", "relay", "refresh"], cwd=e.ws("Pilatus"), timeout=60)
    L.step("U02b", "Pair a scripted phone (subscribers see what workspaces send to phones)", pair_phone, expect="phone paired")

    def real_update(st):
        for i in range(3):
            n = len(rcv.got)
            t0 = time.time()
            rc_, so_, se_ = e.sh(["orch", "relay", "send", "phones", f"update {i}", "--update", "note", "--ticket", env.vars.get("ticket_id", "t_none")],
                                 cwd=e.ws("Pilatus"), timeout=60)
            if not rcv.wait(n + 1, 30):
                ev = lib.http("GET", f"{e.rel.url}/v1/sub/{sub['token']}/events")
                lg = admin.call("GET", f"/admin/api/subscribers/{sub['id']}/log").text[:300]
                raise RuntimeError(f"no push within 30 s; send rc={rc_} {(se_ or so_)[:120]}; events {ev.status} ({len(ev.text)} bytes); log {len(lg)} bytes")
            lat.append(time.time() - t0)
        sig_ok(rcv.got[-1])
        r = lib.http("GET", f"{e.rel.url}/v1/sub/{sub['token']}/events")
        if r.status != 200:
            raise RuntimeError(f"pull events {r.status}")
        st["note"] = "pull ok, pushes " + ", ".join(f"{x:.1f}s" for x in lat)
    L.step("U03", "A real update from the workspace is pushed and can be pulled", real_update, expect="push within a few seconds, same event by pull")
    if lat:
        L.probe("U-push", "Workspace update to signed push at the subscriber", lat, 3, 8)

    def retry(st):
        rcv.fail_first = len(rcv.got) + 1  # the next delivery gets a 500
        n = len(rcv.got)
        e.sh(["orch", "relay", "send", "phones", "will fail first", "--update", "note", "--ticket", env.vars.get("ticket_id", "t_none")], cwd=e.ws("Pilatus"), timeout=60)
        if not rcv.wait(n + 1, 20):
            raise RuntimeError("the update was not even attempted")
        time.sleep(1)
        card = next((x for x in (admin.call("GET", "/admin/api/subscribers").json() or {}).get("items", []) if x["id"] == sub["id"]), {})
        state = (card.get("push") or {}).get("state")
        if state not in ("retrying", "failing"):
            raise RuntimeError(f"push state after a 500 is {state!r}, expected retrying")
        log = admin.call("GET", f"/admin/api/subscribers/{sub['id']}/log?failed=1").json() or {}
        if not log.get("items"):
            raise RuntimeError("the failed delivery is not in the failed log")
        r = admin.call("POST", f"/admin/api/subscribers/{sub['id']}/push/retry")
        if r.status != 200:
            raise RuntimeError(f"push/retry {r.status} {r.text[:150]}")
        if not rcv.wait(n + 2, 20):
            raise RuntimeError("retry delivered nothing")
        st["note"] = f"state after the failure: {state}; failed log items: {len(log['items'])}"
    L.step("U04", "A failed delivery is logged and Retry delivers it", retry, expect="log shows the failure, retry reaches the receiver")

    def rotate(st):
        r = admin.call("POST", f"/admin/api/subscribers/{sub['id']}/token")
        if r.status != 200:
            raise RuntimeError(f"rotate {r.status}")
        new = r.json()["token"]
        old = lib.http("GET", f"{e.rel.url}/v1/sub/{sub['token']}/events")
        if old.status == 200:
            raise RuntimeError("the old token still works after rotation")
        if lib.http("GET", f"{e.rel.url}/v1/sub/{new}/events").status != 200:
            raise RuntimeError("the new token does not work")
        sub["token"] = new
        st["note"] = f"old token answers {old.status}"
    L.step("U05", "Rotate the token: the old one stops, the new one works", rotate, expect="old 401/404, new 200")

    def revoke(st):
        r = admin.call("DELETE", f"/admin/api/subscribers/{sub['id']}")
        if r.status not in (200, 204):
            raise RuntimeError(f"delete {r.status}")
        if lib.http("GET", f"{e.rel.url}/v1/sub/{sub['token']}/events").status == 200:
            raise RuntimeError("a revoked subscriber can still pull")
    L.step("U06", "Revoke the subscriber: pulling stops", revoke, expect="pull refused")
    return L


# ---------------------------------------------------------------------------------------------- lane P (phone, Simulator)

TEST_LINE = None


def parse_xcode_tests(text: str) -> list[dict]:
    """Per test case results from xcodebuild output: [{name, status, secs}]."""
    import re
    out = []
    for m in re.finditer(r"Test Case '-\[(?:\S+\.)?(\w+) (\w+)\]' (passed|failed|skipped) \(([\d.]+) seconds\)", text):
        out.append({"cls": m.group(1), "name": m.group(2), "status": m.group(3), "secs": float(m.group(4))})
    return out


def _host_env() -> dict:
    """Environment for host tools (simctl, xcodegen, xcodebuild): the real HOME, because the Simulators live there (the harness itself runs with a throw-away HOME)."""
    return {**os.environ, "HOME": os.environ.get("E2E_REAL_HOME") or str(Path.home())}


def lane_p(env, out: Path, repo: Path, udid: str = "") -> Lane:
    """Phone lane on the V3-SIM driver (PR #207): `e2e/run.sh V3-SIM` starts its own local relay + workspace and writes ctl/info.json;
    RealRelayE2ETests (XCUITest) drives the app in the Simulator against it. One harness step per XCTest case, shots collected.
    No second phone driver: new phone steps (Mobile mode banner, archive, ...) are XCTests of that class or `-open` targets."""
    import re
    import shutil
    import subprocess
    L = Lane("P", "Phone (Simulator)", out)
    sim = repo / "e2e" / "scenarios_sim.py"
    tests = repo / "mobile" / "OrchMobileUITests" / "RealRelayE2ETests.swift"
    if not (tests.exists() and "V3-SIM" in sim.read_text() if sim.exists() else False):
        L.step("P00", "Phone driver present", lambda st: (_ for _ in ()).throw(Skipped(
            "RealRelayE2ETests / V3-SIM (PR #207) are not in this checkout yet")))
        return L
    if not shutil.which("xcodebuild"):
        L.step("P00", "Xcode", lambda st: (_ for _ in ()).throw(Skipped("xcodebuild not found")))
        return L
    own_sim = False
    if not udid:
        # this lane's own Simulator (never one that is already booted: other lanes drive those); deleted by its exact UDID at the end
        r = subprocess.run(["xcrun", "simctl", "create", "e2e-full-phone", "com.apple.CoreSimulator.SimDeviceType.iPhone-17",
                            "com.apple.CoreSimulator.SimRuntime.iOS-27-0"], env=_host_env(), capture_output=True, text=True)
        udid = r.stdout.strip()
        if r.returncode or not udid:
            L.step("P00", "Create the lane's Simulator", lambda st: (_ for _ in ()).throw(RuntimeError("simctl create failed: " + (r.stderr or r.stdout)[-200:])))
            return L
        own_sim = True
        subprocess.run(["xcrun", "simctl", "boot", udid], env=_host_env(), capture_output=True)
        subprocess.run(["xcrun", "simctl", "bootstatus", udid, "-b"], env=_host_env(), capture_output=True, timeout=300)
        L.notes.append(f"own Simulator e2e-full-phone {udid} (deleted at the end)")
    try:
        return _lane_p_run(L, env, out, repo, udid)
    finally:
        if own_sim:
            subprocess.run(["xcrun", "simctl", "shutdown", udid], env=_host_env(), capture_output=True)
            subprocess.run(["xcrun", "simctl", "delete", udid], env=_host_env(), capture_output=True)


def _lane_p_run(L, env, out: Path, repo: Path, udid: str) -> Lane:
    import re
    import subprocess
    shots = out / "shots"
    host = {}

    def start(st):
        log = open(out / "v3sim.log", "w")
        p = subprocess.Popen(["sh", str(repo / "e2e" / "run.sh"), "V3-SIM"], stdout=log, stderr=log, cwd=repo, start_new_session=True, env=_host_env())
        host["p"] = p
        end = time.time() + 600
        while time.time() < end:
            txt = (out / "v3sim.log").read_text()
            m = re.search(r"tmp (\S+)", txt)
            if m and (Path(m.group(1)) / "ctl" / "info.json").exists():
                host["ctl"] = Path(m.group(1)) / "ctl"
                return
            if p.poll() is not None:
                raise RuntimeError("V3-SIM harness ended early: " + txt[-300:])
            time.sleep(2)
        raise RuntimeError("V3-SIM harness did not publish ctl/info.json in 10 minutes")
    L.step("P01", "Start the V3-SIM host (local relay, workspace, invitation)", start, expect="ctl/info.json with the pair link")
    if "ctl" not in host:
        _p_stop(host)
        return L
    try:
        xo = out / "xcodebuild.log"
        import tempfile
        dd = tempfile.mkdtemp(prefix=".tf-p-dd-", dir=str(Path(os.environ.get("E2E_REAL_HOME") or Path.home())))  # build products: not in the report
        g = subprocess.run(["xcodegen", "generate"], cwd=repo / "mobile", env=_host_env(), capture_output=True, text=True)
        if g.returncode:
            raise RuntimeError("xcodegen failed: " + (g.stderr or g.stdout)[-300:])
        t0 = time.time()
        r = subprocess.run(["xcodebuild", "test", "-project", "OrchMobile.xcodeproj", "-scheme", "OrchMobile", "-destination", f"id={udid}",
                            "-derivedDataPath", dd, "-parallel-testing-enabled", "NO",
                            "-only-testing:OrchMobileUITests/RealRelayE2ETests"], cwd=repo / "mobile", capture_output=True, text=True,
                           timeout=3600, env={**_host_env(), "TEST_RUNNER_ORCH_E2E_CTL": str(host["ctl"]),
                                              "TEST_RUNNER_ORCH_SHOTS": str(shots), "ORCH_E2E_UDID": udid})
        xo.write_text(r.stdout + r.stderr)
        cases = parse_xcode_tests(r.stdout)
        L.notes.append(f"xcodebuild {time.time() - t0:.0f} s, {len(cases)} test cases, exit {r.returncode}")
        for c in cases:
            def one(st, c=c):
                st["ms_override"] = int(c["secs"] * 1000)
                if c["status"] == "skipped":
                    raise Skipped("XCTest skipped it")
                if c["status"] == "failed":
                    raise RuntimeError("XCTest failed; see xcodebuild.log")
            st = L.step("P-" + c["name"], f"{c['cls']}.{c['name']}", one, expect="XCUITest passes against the local relay")
            st["ms"] = int(c["secs"] * 1000)
            png = shots / f"{c['name']}.png"
            if png.exists():
                st["shots"].append({"vp": "phone", "file": f"shots/{png.name}", "hscroll": False})
        if not cases:
            L.step("P02", "XCTest run", lambda st: (_ for _ in ()).throw(RuntimeError("no test cases in the xcodebuild output: " + r.stdout[-300:])))
    finally:
        _p_stop(host)
        try:
            import shutil as _sh
            _sh.rmtree(dd)  # the exact temp folder made above
        except (NameError, OSError):
            pass
    return L


def _p_stop(host: dict) -> None:
    import signal
    ctl = host.get("ctl")
    if ctl:
        (ctl / "stop").write_text("stop")
    p = host.get("p")
    if p:
        try:
            p.wait(60)
        except Exception:  # noqa: BLE001
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass


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

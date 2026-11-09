"""v2 scenarios with REAL agent CLIs (opt-in: `e2e/run.sh V2-R3,V2-R4,V2-R5,V2-R7`). Each one skips cleanly when the
CLI or its login is missing. Prompts are tiny on purpose. Judged by end state (ticket sessions, claim files), not prose."""
from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from agentlib import adh_table, codex_home, run_agent, save_transcript, tokens_from
from lib import Skip, check, http, scenario

# the core v2 scenarios have the same module name (e2e/scenarios_v2.py): load that file under another name
_spec = importlib.util.spec_from_file_location("v2core", Path(__file__).resolve().parent.parent / "scenarios_v2.py")
_v2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v2)
W, attach_watch, wait_for = _v2.W, _v2.attach_watch, _v2.wait_for

WORD = "MANGO"
ASK = "What was the secret word? Reply with that single word spelled backwards in lowercase. Do not run commands."


def real_w(e, sid: str, tool: str, tmux: bool = False) -> W:
    """A workspace whose agent is the real CLI (linked into its own bin folder), with only that agent's login."""
    exe = shutil.which(tool, path=e.path)
    if not exe:
        raise Skip(f"{tool} is not installed")
    env: dict = {}
    if tool == "claude":
        if not os.environ.get("E2E_CLAUDE_TOKEN"):
            raise Skip("no Claude setup-token available")
        env["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["E2E_CLAUDE_TOKEN"]
    else:
        if not (Path(codex_home(e)) / "auth.json").is_file():
            raise Skip("no Codex login (auth.json) available")
        env["CODEX_HOME"] = codex_home(e)
    d = e.tmp / "realbin" / sid.lower()
    d.mkdir(parents=True)
    (d / tool).symlink_to(exe)
    w = W(e, sid, tmux=tmux, extra_bin=d, env=env)
    w.init()
    w.o("config", "set", "workspace.agent", tool, by=None)
    return w


def _resume_twice(e, sid: str, tool: str) -> str:
    w = real_w(e, sid, tool)
    tid = w.ticket(f"Remember a word ({tool})")
    w.o("ticket", "summary", tid, f"The secret word is {WORD}. Reply OK. Do not run commands.")
    r1 = w.j("run", "start", tid)
    check(r1["resumed"] is False and r1["agent"] == tool, f"first run: {r1}")
    w.wait_done(tid, 240)
    ses = w.load(tid).get("sessions") or []
    check(len(ses) == 1 and ses[0]["agent"] == tool and ses[0]["id"],
          f"no session recorded after run 1: {ses}; log tail: {(w.root / r1['log']).read_text(errors='replace')[-500:]!r}")
    sid1 = ses[0]["id"]
    w.o("run", "send", tid, ASK, "--by", "human:anna")
    r2 = w.j("run", "start", tid)
    check(r2["resumed"] is True and r2["session"] == sid1, f"second run must continue {sid1}: {r2}")
    w.wait_done(tid, 240)
    log = (w.root / r2["log"]).read_text(errors="replace").lower()
    check(WORD[::-1].lower() in log, f"the resumed conversation did not know the word (log tail): {log[-400:]!r}")
    check(w.load(tid)["sessions"][0]["id"] == sid1, "session id changed on resume")
    return sid1


@scenario("V2-R3", slow=True)
def r3(e):
    """Claude one-shot resumes by id across two runs (--session-id, then --resume)."""
    return f"session {_resume_twice(e, 'V2-R3', 'claude')[:8]} continued"


@scenario("V2-R4", slow=True)
def r4(e):
    """Codex exec resume: the id comes from the first run's output, the second run continues it."""
    return f"thread {_resume_twice(e, 'V2-R4', 'codex')[:8]} continued"


def _pane(w: W, sock: str, tid: str) -> str:
    p = subprocess.run(["tmux", "-L", sock, "capture-pane", "-p", "-t", f"={tid}:"], capture_output=True, text=True, env=w.env)
    return p.stdout


def _live_state(w: W, tid: str) -> str | None:
    return ((w.claim(tid) or {}).get("live") or {}).get("state")


def _settled(w: W, tid: str) -> bool:
    """Idle with nothing left to paste (the SessionStart hook says idle before the first prompt went in)."""
    pend = w.root / ".orch/run/pending" / f"{tid}.jsonl"
    items = [json.loads(x) for x in pend.read_text().splitlines()] if pend.exists() else []
    return _live_state(w, tid) == "idle" and all(i.get("delivered_at") for i in items) and bool(items)


@scenario("V2-R5", slow=True)
def r5(e):
    """Live Claude in tmux: answer pasted on idle, attach --watch, kill the pane -> continue by id, idle close keeps the id."""
    w = real_w(e, "V2-R5", "claude", tmux=True)
    if not shutil.which("tmux", path=w.env["PATH"]):
        raise Skip("tmux is not installed")
    # a fresh HOME: skip the first-run screens of the interactive CLI (onboarding, folder trust)
    home = Path(e.env["HOME"])
    (home / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark",
        "projects": {str(w.root.resolve()): {"hasTrustDialogAccepted": True, "allowedTools": []}}}))
    tid = w.ticket("Remember a word (live)")
    w.o("ticket", "summary", tid, f"The secret word is {WORD}. Reply OK. Do not run commands.")
    r = w.j("run", "start", tid, "--mode", "live")
    sock = r["tmux"]["socket"]
    check(r["mode"] == "live", f"live start: {r}")
    sid = wait_for(lambda: (w.load(tid).get("sessions") or [{}])[0].get("id"), 120)
    check(sid, f"the SessionStart hook never recorded the session id; pane: {_pane(w, sock, tid)[-400:]!r}")
    check(wait_for(lambda: _settled(w, tid), 240), f"live Claude never settled (Stop hook); pane: {_pane(w, sock, tid)[-400:]!r}")
    # the answer is pasted when idle, once
    w.o("run", "send", tid, ASK, "--by", "human:anna")
    pend = w.root / ".orch/run/pending" / f"{tid}.jsonl"
    check(wait_for(lambda: all(json.loads(x).get("delivered_at") for x in pend.read_text().splitlines()), 120), "the sent text was never pasted")
    check(wait_for(lambda: WORD[::-1].lower() in _pane(w, sock, tid).lower(), 180), f"Claude did not answer in the pane: {_pane(w, sock, tid)[-500:]!r}")
    seen = attach_watch(w, tid, WORD[::-1].lower().encode())
    check(len(seen) > 20, "attach --watch showed nothing")
    # kill the pane: the claim is dead and the next start continues by id
    subprocess.run(["tmux", "-L", sock, "kill-session", "-t", f"={tid}:"], capture_output=True, env=w.env)
    check(wait_for(lambda: w.j("run", "status", tid).get("state") in ("dead", None) or w.claim(tid) is None, 30), "claim of a killed pane is not dead")
    r2 = w.j("run", "start", tid, "--mode", "live")
    check(r2["resumed"] is True and r2["session"] == sid, f"must continue {sid} after the pane was killed: {r2}")
    check(wait_for(lambda: _settled(w, tid), 240), "resumed live Claude never settled")
    # a forced idle close ends the session but keeps the id
    w.o("run", "status", tid, env={"ORCH_RUN_IDLE_SECONDS": "0.01"}, by=None)
    check(w.claim(tid) is None, f"idle close did not end the live run: claim {w.claim(tid)}; pending {pend.read_text()[-400:]!r}")
    check(w.load(tid)["sessions"][0]["id"] == sid, "idle close lost the session id")
    return f"session {sid[:8]}"


@scenario("V2-R7", slow=True)
def r7(e):
    """A hand-started Claude claims with and without a session id; a claim without a process is never auto-taken."""
    w = real_w(e, "V2-R7", "claude")
    uuid = "5f0e8a52-77f4-4c1d-9a0b-2d6f1c3b9e11"
    ta = w.ticket("Hand started with a session id")
    tb = w.ticket("Hand started without a session id")
    run_agent(e, "V2-R7-a", "claude", w.root,
              f"Run exactly these two shell commands and nothing else: `orch run claim {ta} --session {uuid}` and then `orch run release {ta}`.",
              timeout=240)
    ses = w.load(ta).get("sessions") or []
    check(len(ses) == 1 and ses[0]["id"] == uuid and ses[0]["agent"] == "claude", f"claim --session did not record the id: {ses}")
    check(w.claim(ta) is None, "the hand-started claim was not released")
    run_agent(e, "V2-R7-b", "claude", w.root, f"Run exactly this one shell command and nothing else: `orch run claim {tb}`. Do not release it.", timeout=240)
    c = w.claim(tb)
    check(c and c["agent"] == "claude" and c["by"] == "agent:claude" and c["pid"] is None, f"claim without session id: {c}")
    check(not w.load(tb).get("sessions"), "a session was invented for a claim without an id")
    rc, out, err = w.o("run", "start", tb, "--json", ok=False)
    check(rc == 2 and (w.claim(tb) or {}).get("run") == c["run"], f"start must not take over a hand-started claim: rc={rc}")


# a live tool asks before shell commands other than orch (by design: the person answers in the live session)
TITLE = "A tiny giraffe fact page: giraffe.html and giraffe.json (file tools and orch only, no other shell commands)"


def _dashboard_start(e, sid: str, tmux: bool) -> str:
    """The owner's flow: init --recommended, the dashboard, a ticket with no tasks, Start in the dashboard. The real
    agent must make at least one task and a summary within a few minutes. The folder is NOT pre-trusted."""
    w = real_w(e, sid, "claude", tmux=tmux)
    if tmux and not shutil.which("tmux", path=w.env["PATH"]):
        raise Skip("tmux is not installed")
    home = Path(e.env["HOME"])
    cfg = home / ".claude.json"
    if not cfg.exists():  # someone who uses Claude Code already: onboarding done, this folder never trusted
        cfg.write_text(json.dumps({"hasCompletedOnboarding": True, "theme": "dark"}))
    w.o("init", "--recommended", "--yes", by=None)
    w.o("start", "--no-open", by=None)
    try:
        return _dashboard_flow(e, w, tmux)
    finally:
        w.sh(["orch", "stop"])  # free the dashboard's port before the next scenario starts its own


def _dashboard_flow(e, w: W, tmux: bool) -> str:
    rows = w.j("status", by=None)[0]["addons"]
    base = next(r["url"] for r in rows if r["addon"] == "dashboard").rstrip("/")

    def act(op, args):
        r = http("POST", base + "/api/act", {"Origin": base, "Sec-Fetch-Site": "same-origin"}, {"op": op, "args": args})
        check(r.status == 200, f"dashboard {op}: {r.status} {r.body[:300]!r}")
        return r.json()

    tid = next(t["id"] for t in act("ticket.new", {"title": TITLE})["tickets"])
    claim = act("run.start", {"ticket": tid})["runs"][tid]["claim"]
    check(claim["mode"] == ("live" if tmux else "oneshot"), f"Start picked {claim['mode']}")

    def progress():
        t = w.load(tid)
        return bool(t.get("checklist")) and bool(t.get("summary"))

    ok = wait_for(progress, 420, 3)
    t = w.load(tid)
    rec = w.claim(tid) or {}
    where = ""
    if tmux and rec.get("tmux"):
        where = _pane(w, rec["tmux"]["socket"], tid)[-600:]
    elif claim.get("log"):
        where = (w.root / claim["log"]).read_text(errors="replace")[-600:]
    check(ok, f"no task + summary after 7 min: checklist {t.get('checklist')}, summary {t.get('summary')!r}, "
              f"claim {rec.get('live') or rec.get('mode')}; tail: {where!r}")
    if not tmux and claim.get("log"):
        log = (w.root / claim["log"]).read_text(errors="replace")
        check('"type":' in log, "the one-shot log has no stream lines (Focus cannot show steps)")
    if tmux:
        w.o("run", "stop", tid)
    return f"{len(t['checklist'])} task(s), summary {t['summary'][:60]!r}"


@scenario("V2-R8", slow=True)
def r8(e):
    """Dashboard Start, live in tmux, real Claude, folder not trusted before: tasks and a summary appear."""
    return _dashboard_start(e, "V2-R8", tmux=True)


@scenario("V2-R9", slow=True)
def r9(e):
    """Dashboard Start without tmux (one step at a time), real Claude: tasks and a summary appear, the log streams."""
    return _dashboard_start(e, "V2-R9", tmux=False)


# ---- AG-ADH: do agents use orch on their own? (adherence benchmark, opt-in, slow and costly) ---------------------
# 10 prompts x agents x start modes x repeats. Not part of `agents`/`all`: only by id (`e2e/run.sh AG-ADH`).
# Config (env, passed through agents/run.sh): ADH_REPEATS (3), ADH_AGENTS (claude,codex), ADH_MODES (orch,hand),
# ADH_PROMPTS (ids, default all), ADH_QUICK=1 (1 repeat, prompts typo+q-normalise), ADH_PARALLEL (1), ADH_TIMEOUT (420 s).
def tickets(ws: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((ws / ".orch/tickets").glob("t_*.json"))]


ADH_FILES = {
    "ingestion/__init__.py": "",
    "ingestion/job.py": '''"""Nightly ingestion job: reads customer rows and normalises them."""
FIELDS = ["cust_id", "name", "amount"]


def normalise(row):
    return {"cust_id": row["cust_id"].strip(), "name": row["name"].title(), "amount": float(row["amount"])}


def run(rows):
    return [normalise(r) for r in rows]
''',
    "ingestion/report.py": '''from ingestion.job import run


def totals(rows):
    out = {}
    for r in run(rows):
        out[r["cust_id"]] = out.get(r["cust_id"], 0) + r["amount"]
    return out
''',
    "ingestion/stats.py": '''def average(values):
    """Mean of a list of numbers (0 for an empty list)."""
    if not values:
        return 0
    return sum(values) / (len(values) + 1)
''',
    "tests/__init__.py": "",
    "tests/test_job.py": '''import unittest

from ingestion.job import run
from ingestion.report import totals

ROWS = [{"cust_id": " c1 ", "name": "ann lee", "amount": "2.5"}, {"cust_id": "c1", "name": "ann lee", "amount": "1"}]


class JobTest(unittest.TestCase):
    def test_run_keeps_the_customer_id(self):
        self.assertEqual(run(ROWS)[0]["cust_id"], "c1")

    def test_totals_per_customer(self):
        self.assertEqual(totals(ROWS), {"c1": 3.5})


if __name__ == "__main__":
    unittest.main()
''',
    "README.md": "# Ingestion\n\nThe nightly job normalises customer rows (field `cust_id`). It recieves rows as dicts and returns clean ones.\n",
}
ADH_PROMPTS = [  # (id, kind, text)
    ("rename", "work", "In the ingestion job of this project, rename the field `cust_id` to `customer_id` everywhere (code and tests) and make sure the tests still pass."),
    ("typo", "work", "There is a spelling mistake in README.md. Please fix it."),
    ("add-test", "work", "Add a unit test to tests/test_job.py that checks `normalise` turns the name \"ann lee\" into \"Ann Lee\"."),
    ("multi-file", "work", "Add an optional `currency` column: `normalise` should return a `currency` key (default \"EUR\" when the row has none), and the README should mention it. Update the tests."),
    ("refactor", "work", "In ingestion/job.py, move the amount parsing out of `normalise` into a small helper `parse_amount(value)`. Behaviour must not change."),
    ("docs", "work", "Add a short 'Running the tests' section to README.md that says to run `python3 -m unittest`."),
    ("bug", "work", "`average([2, 4])` in ingestion/stats.py returns 2.0 but should be 3.0. Please fix the bug."),
    ("q-normalise", "question", "What does `normalise` do with the `name` field? Just answer, do not change anything."),
    ("q-imports", "question", "Which files in this project import from `ingestion.job`? Just answer, do not change anything."),
    ("q-totals", "question", "Explain what `totals` returns when two rows have the same customer id. Just answer, do not change anything."),
]
ADH_SKIP_DIRS = {".git", ".orch", ".agents", ".claude", "__pycache__", ".pytest_cache"}
ADH_SKIP_FILES = {"AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", ".gitignore"}


def _adh_snapshot(root: Path) -> dict[str, tuple[str, float]]:
    out = {}
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and not (set(rel.parts) & ADH_SKIP_DIRS) and rel.name not in ADH_SKIP_FILES:
            out[str(rel)] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime)
    return out


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def adh_measure(w, base: dict, pre: set[str]) -> dict:
    """Facts of one finished run: tickets beyond the pre-made one(s), task-before-first-change, proof on done tasks."""
    now = _adh_snapshot(w.root)
    changed = [k for k, (h, _) in now.items() if base.get(k, (None,))[0] != h]
    first_change = min((now[k][1] for k in changed), default=None)
    tks = tickets(w.root)
    new = [t for t in tks if t["id"] not in pre]
    mine = tks if pre else new  # orch-started: the started ticket counts too
    adds = [_epoch(h["at"]) for t in mine for h in t["history"] if h["by"].startswith("agent:") and re.fullmatch(r"Added check c\d+", h["text"])]
    checks = [c for t in mine for c in t["checklist"]]
    done = [c for c in checks if c.get("done")]
    return {
        "ticket": bool(new), "extra_tickets": len(new), "files_changed": len(changed),
        "checks": len(checks), "done": len(done),
        # history `at` has 1 s resolution (truncated): a task added in the same second as the change counts as first
        "task_first": bool(adds) and first_change is not None and min(adds) <= first_change,
        "proof": bool(done) and all(c.get("evidence") for c in done),
    }


def _adh_run(e, agent: str, mode: str, pid: str, kind: str, text: str, rep: int, timeout: int) -> dict:
    name = f"ADH-{agent}-{mode}-{pid}-{rep}"
    rec = {"agent": agent, "mode": mode, "prompt": pid, "kind": kind, "rep": rep}
    t0 = time.time()
    try:
        w = real_w(e, name, agent)
        if agent == "codex":  # orch starts `codex exec` with no flags: without a config the sandbox is read-only (a person's ~/.codex sets it)
            (Path(codex_home(e)) / "config.toml").write_text('sandbox_mode = "workspace-write"\n')
        for rel, txt in ADH_FILES.items():
            (w.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (w.root / rel).write_text(txt)
        w.sh(["git", "add", "-A"], check_rc=True)
        w.sh(["git", "-c", "user.name=e2e", "-c", "user.email=e2e@example.com", "commit", "-qm", "fixture"], check_rc=True)
        base = _adh_snapshot(w.root)
        pre: set[str] = set()
        if mode == "orch":
            tid = w.ticket(text[:200])
            pre = {tid}
            w.o("ticket", "summary", tid, text)
            r = w.j("run", "start", tid)
            w.wait_done(tid, timeout)
            log = (w.root / r["log"]).read_text(errors="replace") if r.get("log") else ""
            save_transcript(e, name, f"# orch run start {tid} ({agent})\n# prompt: {text}\n\n{log}")
            rec["tokens"], rec["timed_out"] = tokens_from(log), False
        else:
            run = run_agent(e, name, agent, w.root, text, timeout=timeout, env_over=w.env)
            rec["tokens"], rec["timed_out"] = run.tokens, run.timed_out
        rec.update(adh_measure(w, base, pre))
    except Skip:
        raise
    except Exception as x:  # noqa: BLE001  one bad run must not end the benchmark
        rec["error"] = f"{type(x).__name__}: {' '.join(str(x).split())[:200]}"
    rec["secs"] = round(time.time() - t0)
    return rec


@scenario("AG-ADH", slow=True)
def ag_adh(e):
    """AG-ADH (opt-in, costly): adherence benchmark - do claude/codex make a ticket + tasks + proof on their own?"""
    quick = os.environ.get("ADH_QUICK") == "1"
    reps = int(os.environ.get("ADH_REPEATS") or (1 if quick else 3))
    agents = [a for a in (os.environ.get("ADH_AGENTS") or "claude,codex").split(",") if a]
    modes = [m for m in (os.environ.get("ADH_MODES") or "orch,hand").split(",") if m]
    want = [p for p in (os.environ.get("ADH_PROMPTS") or ("typo,q-normalise" if quick else "")).split(",") if p]
    prompts = [p for p in ADH_PROMPTS if not want or p[0] in want]
    check(prompts and all(a in ("claude", "codex") for a in agents) and all(m in ("orch", "hand") for m in modes),
          f"bad ADH config: agents {agents} modes {modes} prompts {want}")
    timeout, par = int(os.environ.get("ADH_TIMEOUT") or 420), int(os.environ.get("ADH_PARALLEL") or 1)
    jobs = [(a, m, p, r) for r in range(1, reps + 1) for a in agents for m in modes for p in prompts]
    # rough per-run figures from AG-W2/W7 and V2-R3/R4 runs (cache reads included); real totals are printed at the end
    est_s = sum(150 if p[1] == "work" else 60 for _, _, p, _ in jobs)
    est_tok = sum(250_000 if p[1] == "work" else 80_000 for _, _, p, _ in jobs)
    print(f"AG-ADH budget estimate: {len(jobs)} runs ({reps} repeat(s) x {len(agents)} agent(s) x {len(modes)} start mode(s) x "
          f"{len(prompts)} prompt(s)); about {est_s // 60} min sequential ({est_s // 60 // max(par, 1)} min at parallel {par}), "
          f"about {est_tok / 1e6:.1f}M tokens (rough, cache reads included)", flush=True)
    out = Path(os.environ.get("E2E_OUT_DIR") or e.tmp)
    records: list[dict] = []
    skipped: set[str] = set()
    t0, lock = time.time(), threading.Lock()

    def one(job):
        a, m, p, r = job
        try:
            rec = _adh_run(e, a, m, p[0], p[1], p[2], r, timeout)
        except Skip as s:
            skipped.add(f"{a}: {s}")
            return
        with lock:
            records.append(rec)
            (out / "adh.json").write_text(json.dumps({"config": {"repeats": reps, "agents": agents, "modes": modes, "prompts": [p[0] for p in prompts]},
                                                      "records": records}, indent=1))
            print(f"[{len(records)}/{len(jobs)}] {a:6} {m:4} {p[0]:12} rep{r} {rec['secs']:>4}s "
                  + (f"ERROR {rec['error']}" if rec.get("error") else
                     f"ticket={rec['ticket']} tasks={rec['checks']} first={rec['task_first']} proof={rec['proof']} files={rec['files_changed']}"), flush=True)

    with concurrent.futures.ThreadPoolExecutor(max(par, 1)) as ex:
        list(ex.map(one, jobs))
    check(records, f"every run was skipped: {sorted(skipped)}")
    total_s, toks = time.time() - t0, sum(r.get("tokens") or 0 for r in records)
    table = adh_table(records)
    summary = (f"\nAG-ADH adherence (work: ticket / task before first file change / proof on done tasks; question: false tickets)\n{table}\n"
               f"totals: {len(records)} runs, {total_s / 60:.0f} min wall, {toks:,} tokens, {sum(1 for r in records if r.get('error'))} errors"
               + (f"; skipped: {sorted(skipped)}" if skipped else ""))
    print(summary, flush=True)
    (out / "adh.md").write_text(summary + "\n")
    errs = sum(1 for r in records if r.get("error"))
    return f"{len(records)} runs, {errs} errors, {toks:,} tokens, {total_s / 60:.0f} min; table in {out / 'adh.md'}"

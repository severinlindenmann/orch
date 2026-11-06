"""v2 scenarios (V2-*): the core alone, runs (claim, resume, live in tmux), needs, relay outbox, servers alone.

Everything here uses the generic fake agent (fixtures/generic-agent/agent.py), or a fake `claude` script, so no real
Claude or Codex is needed. Real-agent variants live in agents/scenarios_v2.py (opt-in). Each scenario makes its own
workspace folder and runs with a private PATH that names no claude, codex or tmux unless the scenario asks for it.
"""
from __future__ import annotations

import hashlib
import json
import os
import pty
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from lib import Fail, check, free_port, http, scenario, wait_http

AGENT = Path(__file__).parent / "fixtures" / "generic-agent" / "agent.py"
NEEDS_FIXTURE = Path(__file__).parent / "fixtures" / "needs-addon"
ESSENTIALS = ("uv", "node", "git", "python3", "ps", "sh", "env", "sleep", "cat", "date", "ls", "head", "tail", "kill", "mkdir", "rm", "cp", "tr", "grep")


def wait_for(fn, secs: float = 30, step: float = 0.1):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


class W:
    """One workspace folder for one scenario, and the way to run orch in it."""

    def __init__(self, e, sid: str, tmux: bool = False, extra_bin: Path | None = None, env: dict | None = None):
        self.e = e
        self.root = e.tmp / "v2" / sid.lower()
        self.root.mkdir(parents=True)
        self.log = e.tmp / f"{sid.lower()}-agent.log"
        self.bindir = e.tmp / "v2bin" / sid.lower()
        self.bindir.mkdir(parents=True)
        want = list(ESSENTIALS) + (["tmux"] if tmux else [])
        for tool in want:
            p = shutil.which(tool, path=e.path)
            if p and not (self.bindir / tool).exists():
                (self.bindir / tool).symlink_to(p)
        parts = ([str(extra_bin)] if extra_bin else []) + [str(e.bin), str(self.bindir)]
        self.env = {"PATH": os.pathsep.join(parts), "GENERIC_AGENT_LOG": str(self.log), "ORCH_CMD": "orch", **(env or {})}
        e.sh(["git", "init", "-q", "-b", "main"], cwd=self.root, env=self.env, check_rc=True)
        # registered now, so a failing scenario still kills the tmux server it started (socket = hash of the folder)
        self.tmux_sockets: list[str] = (
            ["orch-" + hashlib.sha256(str(self.root.resolve()).encode("utf-8")).hexdigest()[:8]] if tmux else []
        )
        e.cleanup.append(self.close)
        # `orch start` (or a scenario's own dashboard) leaves background servers: always stop them, even when the scenario fails
        e.cleanup.append(lambda: self.e.sh(["orch", "stop"], cwd=self.root, env=self.env))

    def close(self):
        for s in self.tmux_sockets:
            subprocess.run(["tmux", "-L", s, "kill-server"], capture_output=True, env={"PATH": self.env["PATH"] + ":/opt/homebrew/bin:/usr/bin"})

    def sh(self, cmd, **kw):
        kw["env"] = {**self.env, **kw.get("env", {})}
        return self.e.sh(cmd, cwd=self.root, **kw)

    def o(self, *args, ok=True, by: str | None = "human:e2e", env=None, input=None):
        a = list(args) + (["--by", by] if by and "--by" not in args else [])
        rc, out, err = self.sh(["orch", *a], env=env or {}, input=input)
        if ok and rc != 0:
            raise Fail(f"orch {' '.join(args)[:70]} exit {rc}: {(err or out).strip()[-240:]}")
        return rc, out, err

    def j(self, *args, **kw):
        rc, out, err = self.o(*args, "--json", **kw)
        try:
            return json.loads(out)
        except ValueError:
            raise Fail(f"orch {' '.join(args)[:60]} did not print JSON: {out[:160]!r}") from None

    def init(self):
        self.o("init", "--yes", by=None)
        return self

    def agent(self, extra: str = "", name: str = "fake", interactive: bool = False):
        py, ag = shlex.quote(sys.executable), shlex.quote(str(AGENT))
        cmd = f"{py} {ag} {extra} {{prompt}}".replace("  ", " ")
        flags = ["--interactive", f"{py} {ag} --interactive"] if interactive else []
        self.o("config", "agent", "add", name, "--command", cmd, *flags, by=None)
        self.o("config", "set", "workspace.agent", name, by=None)

    def ticket(self, title: str, *checks: str, parent: str | None = None) -> str:
        extra = ["--parent", parent] if parent else []
        tid = self.j("ticket", "new", title, *extra)["id"]
        for c in checks:
            self.o("check", "add", tid, c)
        return tid

    def load(self, tid: str) -> dict:
        return json.loads((self.root / ".orch" / "tickets" / f"{tid}.json").read_text())

    def claim_file(self, tid: str) -> Path:
        return self.root / ".orch" / "run" / "tickets" / f"{tid}.json"

    def claim(self, tid: str) -> dict | None:
        try:
            return json.loads(self.claim_file(tid).read_text())
        except (OSError, ValueError):
            return None

    def wait_done(self, tid: str, secs: float = 40):
        """The claim is gone: the detached run finished (or was stopped)."""
        check(wait_for(lambda: not self.claim_file(tid).exists(), secs), f"run on {tid} did not finish: {self.claim(tid)}")

    def wait_claim(self, tid: str, secs: float = 15) -> dict:
        c = wait_for(lambda: (self.claim(tid) or {}).get("agent_pid") and self.claim(tid), secs)
        check(c, f"no running agent on {tid}")
        return c

    def lines(self, kind: str) -> list[str]:
        if not self.log.exists():
            return []
        return [ln.split(": ", 1)[1] for ln in self.log.read_text().splitlines() if ln.startswith(kind + ":")]

    def history(self, tid: str) -> list[dict]:
        return self.load(tid)["history"]


def pty_run(cmd: list[str], cwd: Path, env: dict, answers: list[str], secs: float = 30) -> tuple[int, str]:
    """Run a command that asks questions on a terminal; answers go in one line each."""
    master, slave = pty.openpty()
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    for a in answers:
        os.write(master, (a + "\n").encode())
    out = b""
    end = time.time() + secs
    while time.time() < end:
        r, _, _ = select.select([master], [], [], 0.2)
        if r:
            try:
                d = os.read(master, 4096)
            except OSError:
                break
            if not d:
                break
            out += d
        if p.poll() is not None and not r:
            break
    try:
        rc = p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        rc = -9
    os.close(master)
    return rc, out.decode("utf-8", "replace")


def attach_watch(w: W, tid: str, needle: bytes, secs: float = 15) -> bytes:
    """`orch run attach --watch` on a terminal; returns what it showed until `needle` appeared."""
    master, slave = pty.openpty()
    p = subprocess.Popen(["orch", "run", "attach", tid, "--watch"], cwd=w.root, env={**w.e.env, **w.env, "TERM": "xterm"},
                         stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    seen = b""
    end = time.time() + secs
    while time.time() < end and needle not in seen:
        if select.select([master], [], [], 0.3)[0]:
            try:
                seen += os.read(master, 8192)
            except OSError:
                break
    p.kill()
    p.wait()
    os.close(master)
    return seen


# ------------------------------------------------------------------------------------------------ core alone


@scenario("V2-I1")
def i1_init_recommended(e):
    """`orch init --recommended --yes` turns on the dashboard, automation and focus add-ons, and not relay or publish."""
    w = W(e, "V2-I1")
    out = w.j("init", "--recommended", "--yes", by=None)
    check(sorted(out.get("recommended") or []) == ["automation", "dashboard", "focus"], f"init turned on {out.get('recommended')}")
    rows = w.j("addon", "list", by=None)
    on = sorted(r["name"] for r in rows if r["active"])
    check(on == ["automation", "dashboard", "focus"], f"active add-ons after init --recommended: {on}")


@scenario("V2-C1")
def c1(e):
    """Core alone (no add-on): owner/due/note, summary, task ops, --file proof (gitignored), sub-ticket + warning, needs."""
    w = W(e, "V2-C1").init()
    check(not (w.root / ".orch" / "addons.json").exists() and not (w.root / ".orch" / "addons").exists(), "an add-on is installed")
    tid = w.ticket("Invoice export", "first", "second", "third")
    w.o("ticket", "edit", tid, "--owner", "anna", "--due", "2026-12-01", "--note", "see the finance sheet")
    w.o("ticket", "summary", tid, "Export works for one customer.")
    t = w.load(tid)
    check((t["owner"], t["due"], t["note"], t["summary"]) == ("anna", "2026-12-01", "see the finance sheet", "Export works for one customer."), f"fields: {t}")
    check(w.j("ticket", "show", tid)["summary"].startswith("Export works"), "summary not in show --json")
    # task edit / move / remove / reopen
    w.o("check", "edit", tid, "c1", "first renamed")
    w.o("check", "move", tid, "c1", "--after", "c3")
    check([c["id"] for c in w.load(tid)["checklist"]] == ["c2", "c3", "c1"], f"order after move: {[c['id'] for c in w.load(tid)['checklist']]}")
    check(w.load(tid)["checklist"][2]["text"] == "first renamed", "rename lost")
    w.o("check", "remove", tid, "c2")
    check([c["id"] for c in w.load(tid)["checklist"]] == ["c3", "c1"], "remove did not remove")
    # proof file: copied into the ticket folder, not tracked by git
    (w.root / "export.csv").write_text("id,total\n1,10\n")
    ev = w.j("check", "done", tid, "c3", "--file", "export.csv", "--title", "Export")["evidence"][0]
    check(ev["type"] == "file" and ev["title"] == "Export", f"evidence {ev}")
    copy = w.root / ev["ref"]
    check(copy.is_file() and copy.read_text() == "id,total\n1,10\n", f"proof copy missing at {ev['ref']}")
    rc, out, _ = w.sh(["git", "check-ignore", ev["ref"]])
    check(rc == 0, "proof copy is not ignored by git")
    w.o("check", "reopen", tid, "c3")
    check(not w.load(tid)["checklist"][0]["done"], "reopen did not reopen")
    # sub-ticket and the close warning (saved anyway)
    kid = w.ticket("Column order", parent=tid)
    check(w.load(kid).get("parent") == tid, f"sub-ticket parent: {w.load(kid)}")
    w.o("check", "done", tid, "c3", "--note", "checked")
    w.o("check", "done", tid, "c1", "--note", "checked")
    rc, out, err = w.o("ticket", "status", tid, "done")
    check("sub-tickets are still open" in err and "Column order" in err, f"no close warning on stderr: {err!r}")
    check(w.load(tid)["status"] == "done", "the parent was not closed (warning only)")
    # needs: nothing, then a question, then nothing again
    check("Nothing needs you" in w.o("needs")[1], "needs not empty")
    w.o("ask", kid, "Which order?", "--option", "A", "--option", "B")
    rows = w.j("needs")
    check(len(rows) == 1 and rows[0]["source"] == "core" and rows[0]["kind"] == "question" and rows[0]["ticket"] == kid, f"needs rows {rows}")
    qid = w.load(kid)["questions"][0]["id"]
    w.o("answer", kid, qid, "A")
    check(w.j("needs") == [], "needs still lists an answered question")


@scenario("V2-C2")
def c2(e):
    """Two writer processes on one ticket both land; a stale --if-revision edit gets exit 2."""
    w = W(e, "V2-C2").init()
    tid = w.ticket("Shared ticket")
    rev0 = w.load(tid)["revision"]
    procs = []
    for who in ("a", "b"):
        script = "; ".join(f"orch check add {tid} {who}{i} --by human:{who}" for i in range(6))
        procs.append(subprocess.Popen(["sh", "-c", script], cwd=w.root, env={**e.env, **w.env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
    for p in procs:
        out, err = p.communicate(timeout=120)
        check(p.returncode == 0, f"a writer failed: {err.decode()[-200:]}")
    texts = sorted(c["text"] for c in w.load(tid)["checklist"])
    check(texts == sorted(f"{x}{i}" for x in "ab" for i in range(6)), f"lost writes: {texts}")
    check(w.load(tid)["revision"] >= rev0 + 12, "revision did not count every write")
    rc, out, err = w.o("ticket", "edit", tid, "--note", "mine", "--if-revision", str(rev0), ok=False)
    check(rc == 2 and "was changed by" in err, f"stale edit: rc={rc} {err!r}")
    check(not w.load(tid).get("note"), "stale edit was written")
    cur = w.load(tid)["revision"]
    rc, out, err = w.o("ticket", "edit", tid, "--note", "mine", "--if-revision", str(cur), ok=False)
    check(rc == 0 and w.load(tid)["note"] == "mine", f"edit on the revision just seen: rc={rc} {err!r}")


@scenario("V2-C3")
def c3(e):
    """A clone shows proof 'on another computer'; orch run argv does not resume another computer's session."""
    w = W(e, "V2-C3").init()
    tid = w.ticket("Report", "make the file")
    (w.root / "out.txt").write_text("proof\n")
    w.o("check", "done", tid, "c1", "--file", "out.txt")
    w.sh(["git", "add", "-A"], check_rc=True)
    w.sh(["git", "-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", "commit", "-q", "-m", "ws"], check_rc=True)
    clone = e.tmp / "v2" / "v2-c3-clone"
    w.sh(["git", "clone", "-q", str(w.root), str(clone)], check_rc=True)
    rc, out, err = e.sh(["orch", "ticket", "show", tid], cwd=clone, env=w.env)
    check(rc == 0 and "on another computer" in out, f"clone does not say proof is on another computer: {out[-300:]!r}")
    check(not list((clone / ".orch" / "tickets" / tid).glob("evidence/*")), "proof file came with the clone")
    # sessions are per computer: this one resumes, a session recorded on another host does not
    sid = "0b3a4c6e-1111-4222-8333-444455556666"
    w.o("run", "claim", tid, "--agent", "claude", "--session", sid)
    w.o("run", "release", tid)
    argv = w.j("run", "argv", tid, "--agent", "claude")["argv"]
    check("--resume" in argv and sid in argv, f"same computer should resume: {argv}")
    p = w.root / ".orch" / "tickets" / f"{tid}.json"
    d = json.loads(p.read_text())
    for s in d["sessions"]:
        s["host"] = "some-other-computer"
    p.write_text(json.dumps(d, indent=2))
    argv = w.j("run", "argv", tid, "--agent", "claude")["argv"]
    check("--resume" not in argv and sid not in argv and "--session-id" in argv, f"another computer's session must not be resumed: {argv}")


@scenario("V2-C4")
def c4(e):
    """The documented manual core run path: no add-on, generic agent, `orch run start <tid>` finishes the ticket."""
    w = W(e, "V2-C4").init()
    w.agent()
    tid = w.ticket("Write the summary", "do the step")
    r = w.j("run", "start", tid)
    check(r["agent"] == "fake" and r["resumed"] is False and r["mode"] == "oneshot", f"start result {r}")
    w.wait_done(tid)
    t = w.load(tid)
    check(t["checklist"][0]["done"], f"the agent did not finish the task: {t['checklist']}")
    check(any(h["by"] == "agent:fake" for h in t["history"]), f"no entry by agent:fake: {[h['by'] for h in t['history']]}")
    check((w.root / r["log"]).is_file(), "run log missing")
    check(len(w.lines("prompt")) == 1 and tid in w.lines("prompt")[0], f"prompts {w.lines('prompt')}")
    check(not (w.root / ".orch" / "addons").exists(), "an add-on appeared")


# ------------------------------------------------------------------------------------------------ runs


@scenario("V2-R1")
def r1(e):
    """Busy ticket: start saves the request (exit 2); footer on stderr, --json stdout parses; drained once, never two agents."""
    w = W(e, "V2-R1").init()
    w.agent("--silent 5")
    tid = w.ticket("Busy one", "step")
    first = w.j("run", "start", tid)
    rc, out, err = w.o("run", "start", tid, "--text", "please also use CHF", "--json", ok=False)
    j = json.loads(out)
    check(rc == 2 and j.get("pending") is True and j["holder"]["run"] == first["run"], f"busy start: rc={rc} {out!r}")
    # a person edits the ticket; the running agent's next orch command shows it on stderr, stdout stays clean JSON
    w.o("log", tid, "Marco says: ship on Friday")
    run_env = {"ORCH_RUN": first["run"], "ORCH_TICKET": tid, "ORCH_AGENT": "fake"}
    rc, out, err = w.o("ticket", "show", tid, "--json", env=run_env, by=None)
    check(isinstance(json.loads(out), dict), "stdout of a run command is not JSON")
    check("New on" in err and "ship on Friday" in err, f"no footer on stderr: {err!r}")
    check("New on" not in out, "footer leaked into stdout")
    rc, out, err = w.o("ticket", "show", tid, "--json", env=run_env, by=None)
    check("New on" not in err, "footer shown twice")
    w.wait_done(tid, 60)
    prompts = w.lines("prompt")
    check(len(prompts) == 2, f"expected two agent runs (one at a time), got {len(prompts)}")
    check(sum("please also use CHF" in p for p in prompts) == 1, "the saved request must reach exactly one run")
    check("please also use CHF" in prompts[1], "the saved request must come in the second run")
    pend = w.root / ".orch" / "run" / "pending" / f"{tid}.jsonl"
    items = [json.loads(x) for x in pend.read_text().splitlines()]
    check(len(items) == 1 and items[0].get("delivered_at"), f"pending items: {items}")


@scenario("V2-R2")
def r2(e):
    """Generic agent only: PATH without claude/codex; init -> Other -> fake; fresh runs; agent:<name>."""
    w = W(e, "V2-R2")
    for tool in ("claude", "codex"):
        check(not shutil.which(tool, path=w.env["PATH"]), f"{tool} is on the test PATH")
    py, ag = shlex.quote(sys.executable), shlex.quote(str(AGENT))
    rc, out = pty_run(["orch", "init"], w.root, {**e.env, **w.env}, ["fake", f"{py} {ag} {{prompt}}"])
    check(rc == 0 and "fake" in out, f"orch init with Other: rc={rc} {out[-300:]!r}")
    check(w.o("config", "get", "workspace.agent", by=None)[1].strip() == "fake", "fake is not the chosen agent")
    rows = w.j("agents", by=None)
    chosen = [r for r in rows if r["chosen"]]
    check(len(chosen) == 1 and chosen[0]["name"] == "fake" and chosen[0]["adapter"] == "generic", f"agents: {chosen}")
    tid = w.ticket("Two runs", "a", "b")
    runs_ = []
    for _ in range(2):
        r = w.j("run", "start", tid)
        runs_.append(r)
        w.wait_done(tid)
    check(all(r["agent"] == "fake" and r["resumed"] is False and r["session"] is None for r in runs_), f"runs {runs_}")
    check(len(w.lines("prompt")) == 2 and all("Work on orch ticket" in p for p in w.lines("prompt")), "each run must start fresh from the ticket")
    t = w.load(tid)
    check(all(c["done"] for c in t["checklist"]), "the two runs did not finish the tasks")
    agent_by = {h["by"] for h in t["history"] if h["by"].startswith("agent:")}
    check(agent_by == {"agent:fake"}, f"agent actors: {agent_by}")
    check(not t.get("sessions"), f"a generic agent must leave no session: {t.get('sessions')}")
    argv = w.j("run", "argv", tid)["argv"]
    check("--resume" not in argv, f"argv {argv}")


@scenario("V2-R6")
def r6(e):
    """No tmux: --mode live falls back to one turn at a time, with the same run record."""
    w = W(e, "V2-R6", tmux=False).init()
    check(not shutil.which("tmux", path=w.env["PATH"]), "tmux is on the test PATH")
    w.agent("--silent 2", interactive=True)
    tid = w.ticket("No tmux here", "step")
    rc, out, err = w.o("run", "start", tid, "--mode", "live", "--json")
    r = json.loads(out)
    check(r["mode"] == "oneshot" and r["tmux"] is None, f"fallback result {r}")
    check("tmux" in err, f"no plain notice about tmux on stderr: {err!r}")
    c = w.wait_claim(tid)
    check(c["mode"] == "oneshot" and c["agent"] == "fake" and c["run"] == r["run"] and c["tmux"] is None, f"claim {c}")
    check(w.j("run", "status", tid)["running"] is True, "status does not show the run")
    w.wait_done(tid, 60)
    check(len(w.lines("prompt")) == 1, "one run expected")


@scenario("V2-R8")
def r8(e):
    """A silent agent past the lease keeps its claim; two takeovers of a dead claim -> one winner; pid-less never auto-taken."""
    w = W(e, "V2-R8", env={"ORCH_RUN_LEASE_SECONDS": "2"}).init()
    w.agent("--silent 9")
    tid = w.ticket("Quiet agent", "step")
    r = w.j("run", "start", tid)
    w.wait_claim(tid)
    time.sleep(4)  # the lease (2 s) has run out; the agent is still alive and silent
    st = w.j("run", "status", tid)
    check(st["state"] == "alive" and st["running"] is True, f"a silent live agent lost its claim: {st}")
    rc, out, err = w.o("run", "start", tid, "--json", ok=False)
    check(rc == 2 and len(w.lines("prompt")) == 1, f"a second agent started on a quiet ticket: rc={rc} prompts={len(w.lines('prompt'))}")
    check(w.claim(tid)["run"] == r["run"], "claim changed hands")
    w.wait_done(tid, 60)
    base = len(w.lines("prompt"))  # the request saved by the busy start above makes a second turn
    # a dead claim: two simultaneous takeovers, one winner
    dead = subprocess.Popen(["sh", "-c", "exit 0"])
    dead.wait()
    tid2 = w.ticket("Dead claim")
    w.o("run", "claim", tid2, "--pid", str(dead.pid), "--agent", "fake")
    check(w.j("run", "status", tid2)["state"] == "dead", "claim of a finished process should be dead")
    procs = [subprocess.Popen(["orch", "run", "claim", tid2, "--agent", "fake", "--by", f"agent:t{i}", "--json"], cwd=w.root,
                              env={**e.env, **w.env}, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(2)]
    codes = []
    for p in procs:
        p.communicate(timeout=60)
        codes.append(p.returncode)
    check(sorted(codes) == [0, 2], f"takeover of a dead claim: exit codes {codes} (want one winner)")
    # a claim without a process is only ever taken on request
    tid3 = w.ticket("Hand started")
    w.o("run", "claim", tid3, "--agent", "fake")
    time.sleep(3)
    st = w.j("run", "status", tid3)
    check(st["state"] == "maybe-stale", f"pid-less claim after the lease: {st['state']}")
    rc, out, err = w.o("run", "claim", tid3, "--agent", "fake", "--json", ok=False)
    check(rc == 2, f"a pid-less claim was taken without --take-over (rc {rc})")
    rc, out, err = w.o("run", "start", tid3, "--json", ok=False)
    check(rc == 2 and len(w.lines("prompt")) == base, "run start must not take over a maybe-stale claim")
    rc, out, err = w.o("run", "claim", tid3, "--agent", "fake", "--take-over", "--json", ok=False)
    check(rc == 0, f"--take-over refused: {err!r}")


@scenario("V2-N1")
def n1(e):
    """orch needs rows: a core question, a fixture add-on row, the same row stale, a background add-on not running."""
    w = W(e, "V2-N1").init()
    addon = e.tmp / "addons" / "needs-addon"
    if addon.exists():
        shutil.rmtree(addon)
    shutil.copytree(NEEDS_FIXTURE, addon)
    rc, out, err = w.sh(["orch", "addon", "add", str(addon), "--yes"], timeout=600)
    check(rc == 0, f"addon add: {(err or out)[-300:]}")
    tid = w.ticket("Needs a person")
    w.o("ask", tid, "Go ahead?", "--option", "Yes", "--option", "No")
    row = {"id": "needs-addon:r1", "source": "needs-addon", "kind": "needs-addon:thing", "ticket": None, "title": "Fixture",
           "text": "Look at this", "tone": "warn", "since": "2026-11-05T08:00:00Z"}
    (w.root / "rows.json").write_text(json.dumps([row]))
    rows = {r["id"]: r for r in w.j("needs", by=None)}
    ids = sorted(rows)
    check(any(i.startswith("core:q:") for i in ids), f"no core question row: {ids}")
    check(rows["needs-addon:r1"]["stale"] is False, "fresh row marked stale")
    check("core:down:needs-addon" in rows and rows["core:down:needs-addon"]["tone"] == "bad", f"no 'not running' row: {ids}")
    (w.root / "mode.txt").write_text("broken")
    rows = {r["id"]: r for r in w.j("needs", by=None)}
    check(rows["needs-addon:r1"]["stale"] is True, "a failing add-on's last rows must come back marked stale")
    text = w.o("needs", by=None)[1]
    check("not up to date" in text and "Needs you" in text, f"plain text of needs: {text!r}")


# ------------------------------------------------------------------------------------------------ sessions, live, crash


def fake_claude(e, w_name: str) -> tuple[Path, Path]:
    """A `claude` script that logs its arguments; it says 'no conversation' for --resume while the file `gone` exists."""
    d = e.tmp / "fakeclaude" / w_name
    d.mkdir(parents=True)
    calls = d / "calls.txt"
    f = d / "claude"
    f.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then echo "2.0.0 (fake)"; exit 0; fi\n'
        f'echo "$@" | tr "\\n" " " >> {shlex.quote(str(calls))}; echo >> {shlex.quote(str(calls))}\n'
        f'if [ -e {shlex.quote(str(d / "gone"))} ] && echo "$@" | grep -q -- "--resume"; then\n'
        '  echo "No conversation found with session ID: x"; exit 1\nfi\n'
        'echo "ok"\n'
    )
    f.chmod(0o755)
    return d, calls


@scenario("V2-S1")
def s1(e):
    """Session resume and --fresh (fake claude): second run resumes by id, --fresh starts a new one, a vanished session starts fresh."""
    d, calls = fake_claude(e, "s1")
    w = W(e, "V2-S1", extra_bin=d).init()
    w.o("config", "set", "workspace.agent", "claude", by=None)
    tid = w.ticket("Continue me", "step")

    def last_call() -> list[str]:
        return calls.read_text().strip().splitlines()[-1].split()

    def run_once(*flags):
        n = len(calls.read_text().splitlines()) if calls.exists() else 0
        r = w.j("run", "start", tid, *flags)
        w.wait_done(tid)
        return r, n

    r1_, _ = run_once()
    a = last_call()
    check(r1_["agent"] == "claude" and r1_["resumed"] is False and "--session-id" in a, f"first run: {a}")
    sid1 = a[a.index("--session-id") + 1]
    check(w.j("ticket", "show", tid)["sessions"][0]["id"] == sid1, "the session id was not recorded on the ticket")
    r2_, _ = run_once()
    a = last_call()
    check(r2_["resumed"] is True and a[:2] == ["-p", "--resume"] and a[2] == sid1, f"second run must resume {sid1}: {a}")
    r3_, _ = run_once("--fresh")
    a = last_call()
    check(r3_["resumed"] is False and "--session-id" in a and sid1 not in a, f"--fresh must not resume: {a}")
    sid2 = a[a.index("--session-id") + 1]
    check(sid2 != sid1 and w.j("ticket", "show", tid)["sessions"][0]["id"] == sid2, "the fresh session did not replace the old id")
    # the tool no longer knows the session: one fresh run with the same input, not a failure
    (d / "gone").write_text("")
    n = len(calls.read_text().splitlines())
    w.j("run", "start", tid)
    w.wait_done(tid)
    new = calls.read_text().splitlines()[n:]
    check(len(new) == 2 and "--resume" in new[0] and "--session-id" in new[1], f"lost session did not fall back to fresh: {new}")


@scenario("V2-L1")
def l1(e):
    """Live run in tmux (generic agent): prompt in, input pasted once when idle, attach shows it, stop ends it."""
    if not shutil.which("tmux", path=e.path):
        from lib import Skip
        raise Skip("tmux is not installed")
    w = W(e, "V2-L1", tmux=True).init()
    w.agent(interactive=True)
    tid = w.ticket("Live work", "step")
    r = w.j("run", "start", tid, "--mode", "live")
    check(r["mode"] == "live" and r["tmux"]["session"] == tid, f"live start: {r}")
    check(r["tmux"]["socket"] in w.tmux_sockets, f"tmux socket {r['tmux']['socket']} is not the one W cleans up")
    check(wait_for(lambda: w.lines("input"), 30), "the first prompt never reached the live agent")
    check("Live work" in w.lines("input")[0], f"first input {w.lines('input')[0]!r}")
    check(wait_for(lambda: (w.claim(tid) or {}).get("live", {}).get("state") == "idle", 20), "agent did not become idle (orch run done)")
    sent = w.j("run", "send", tid, "Use CHF please", "--by", "human:anna")
    check(wait_for(lambda: len(w.lines("input")) == 2, 20), f"sent text never arrived (send result {sent})")
    check(w.lines("input")[1] == "From human:anna: Use CHF please", f"second input {w.lines('input')[1]!r}")
    time.sleep(1.5)
    check(len(w.lines("input")) == 2, f"input arrived more than once: {w.lines('input')}")
    pend = (w.root / ".orch/run/pending" / f"{tid}.jsonl").read_text().splitlines()
    check(all(json.loads(x).get("delivered_at") for x in pend), "an input is still marked as waiting")
    seen = attach_watch(w, tid, b"Use CHF")
    check(b"Use CHF" in seen or b"got:" in seen, f"attach did not show the live session: {seen[-200:]!r}")
    st = w.o("run", "status", tid)[1]
    check("live session" in st, f"status of a live run: {st!r}")
    # stop ends the agent, the tmux session and the claim; the ticket stays
    w.o("run", "stop", tid)
    check(w.claim(tid) is None, "claim still there after stop")
    rc = subprocess.run(["tmux", "-L", r["tmux"]["socket"], "has-session", "-t", f"={tid}:"], capture_output=True, env=w.env).returncode
    check(rc != 0, "tmux session still exists after stop")
    check(not w.j("run", "status", tid)["running"], "status says running after stop")


@scenario("V2-T1")
def t1(e):
    """Crash recovery: a killed run leaves a dead claim; the next start takes it, input saved meanwhile arrives once."""
    w = W(e, "V2-T1").init()
    w.agent("--silent 60")
    tid = w.ticket("Survives a crash", "step")
    w.j("run", "start", tid)
    c = w.wait_claim(tid)
    w.o("run", "send", tid, "remember the VAT", "--by", "human:anna")
    for pid in (c["pid"], c["agent_pid"]):
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    check(wait_for(lambda: w.j("run", "status", tid).get("state") == "dead", 15), f"claim of a killed run is not dead: {w.j('run', 'status', tid)}")
    text = w.o("run", "status", tid)[1]
    check("ended without finishing" in text and f"orch run start {tid}" in text, f"status text {text!r}")
    w.agent("", name="fake2")  # a working agent now
    r = w.j("run", "start", tid)  # no --take-over needed for a dead claim
    w.wait_done(tid)
    check(r["run"] != c["run"], "same run id after restart")
    check(w.load(tid)["checklist"][0]["done"], "the restarted run did not finish the task")
    prompts = [p for p in w.lines("prompt")]
    check(sum("remember the VAT" in p for p in prompts) == 1, f"saved input must arrive exactly once: {len(prompts)} prompts")


@scenario("V2-T2")
def t2(e):
    """Sub-ticket tree: children listed under the parent with counts; an agent finishes a child alone."""
    w = W(e, "V2-T2").init()
    w.agent()
    parent = w.ticket("Release 2")
    k1 = w.ticket("Write notes", "draft", parent=parent)
    k2 = w.ticket("Tag it", "tag", parent=parent)
    tree = w.o("ticket", "tree", parent)[1]
    check("Write notes" in tree and "Tag it" in tree and tree.index("Release 2") < tree.index("Write notes"), f"tree: {tree!r}")
    check("Sub-tickets: 0 of 2 closed" in w.o("ticket", "show", parent)[1], "ticket show lacks the sub-ticket count")
    w.j("run", "start", k1)
    w.wait_done(k1)
    check(w.load(k1)["checklist"][0]["done"] and not w.load(k2)["checklist"][0]["done"], "the agent touched the wrong ticket")
    check(w.load(k1).get("parent") == parent, "child lost its parent")
    rows = w.j("ticket", "list", "--all")
    kids = [t for t in rows if t.get("parent") == parent]
    check(len(kids) == 2, f"list does not show both children: {rows}")
    check(next(t for t in rows if t["id"] == parent)["children"] == {"total": 2, "closed": 0, "open": 2}, "list counts of the parent")


# ------------------------------------------------------------------------------------------------ servers


def _restart_relay(e):
    """Stop the local relay and start it again on the same port and data (what 'relay down for a while' is)."""
    rel = e.rel
    binary = rel.proc.args[0] if isinstance(rel.proc.args, list) else rel.proc.args
    port, aport = rel.url.rsplit(":", 1)[1], rel.admin_url.rsplit(":", 1)[1]
    env = {"PATH": e.path, "HOME": str(e.tmp / "home"), "LANG": "C.UTF-8", "ORCH_RELAY_DATA_DIR": str(rel.data),
           "ORCH_RELAY_MASTER_KEY_FILE": str(e.tmp / "relay-master.key"), "ORCH_RELAY_LISTEN": f"127.0.0.1:{port}",
           "ORCH_RELAY_ADMIN_LISTEN": f"127.0.0.1:{aport}", "ORCH_RELAY_ADMIN_TOKEN": rel.admin.token, "ORCH_RELAY_PUBLIC_ORIGIN": rel.url}
    return binary, env


@scenario("V2-P6", local_only=True)
def p6(e):
    """Relay down -> outbox -> resend the same bytes; billing and reports start keys -> two tickets (local relay)."""
    ids = e.relay_all()
    pil, rep = e.ws("Pilatus"), e.ws("Reports")
    binary, env = _restart_relay(e)
    old = e.rel.proc
    old.terminate()
    old.wait(timeout=15)
    try:
        r = e.orchj("Pilatus", "relay", "start", ids["Reports"], "billing-v2", "run the billing job")
        check(r.get("sent") is False, f"a start with the relay down must report sent=false: {r}")
        r2 = e.orchj("Pilatus", "relay", "start", ids["Reports"], "reports-v2", "run the weekly reports")
        check(len(e.orchj("Pilatus", "relay", "outbox")["waiting"]) == 2, "orch relay outbox does not list the waiting messages")
        files = sorted((pil / ".orch" / "outbox").glob("m_*.json"))
        check(len(files) == 2, f"outbox files: {[f.name for f in files]}")
        saved = {f.stem: f.read_bytes() for f in files}
        check(r["id"] in saved and r2["id"] in saved, "outbox lacks the message ids that were reported")
    finally:
        log = open(e.tmp / "relay2.log", "w")
        e.rel.proc = subprocess.Popen([binary], env=env, stdout=log, stderr=log, cwd=e.tmp)
        e.pids.append(e.rel.proc.pid)
    check(wait_http(e.rel.url + "/health", 30), "relay did not come back")
    res = e.orchj("Pilatus", "relay", "outbox", "--resend")
    check(sorted(res.get("sent", [])) == sorted(saved), f"resend result {res}")
    left = list((pil / ".orch" / "outbox").glob("m_*.json"))
    check(not left, f"outbox not empty after resend: {[f.name for f in left]} ({res})")
    got = {m["id"]: m for m in e.orchj("Reports", "relay", "inbox") if m["type"] == "start"}
    check(set(saved) <= set(got), f"Reports did not get both messages (same ids): {sorted(got)} vs {sorted(saved)}")
    for mid, raw in saved.items():
        sent_msg = json.loads(raw)
        check(got[mid]["body"] == sent_msg["body"] and got[mid]["created_at"] == sent_msg["created_at"], f"{mid}: resent bytes differ")
    again = e.orchj("Pilatus", "relay", "outbox", "--resend")
    check(not again.get("sent"), f"resend sent something twice: {again}")
    # allow both keys, then the two keys make two tickets
    for mid in saved:
        e.orch("Reports", "relay", "allow", mid, "--once")
    made = {}
    for mid, raw in saved.items():
        done = e.orchj("Reports", "relay", "done", mid)
        made[json.loads(raw)["body"]["key"]] = done.get("ticket")
    check(all(made.values()) and len(set(made.values())) == 2, f"two start keys must make two tickets: {made}")
    for key, tid in made.items():
        t = json.loads((rep / ".orch" / "tickets" / f"{tid}.json").read_text())
        check((t.get("ext", {}).get("relay") or {}).get("start_key") == key, f"{tid} start_key: {t.get('ext')}")


def _stop(p) -> None:
    p.terminate()
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()


def _spawn(e, binary: str, env: dict, name: str):
    log = open(e.tmp / f"{name}.log", "w")
    p = subprocess.Popen([binary], env=env, stdout=log, stderr=log, cwd=e.tmp)
    e.pids.append(p.pid)
    return p


@scenario("V2-W2", local_only=True)
def w2(e):
    """Relay server alone and publish server alone each start from nothing and pass a smoke test, the other one absent."""
    bins = getattr(e, "bins", {})
    if not bins.get("relay") or not bins.get("publish"):
        from lib import Skip
        raise Skip("server binaries were not built for this run")
    base_env = {"PATH": e.path, "HOME": str(e.tmp / "home"), "LANG": "C.UTF-8"}
    # relay alone
    rd = e.tmp / "w2-relay"
    rd.mkdir()
    (e.tmp / "w2-relay.key").write_bytes(os.urandom(32))
    rp, ra = free_port(e.used_ports), free_port(e.used_ports)
    tok = "r" * 8 + os.urandom(12).hex()
    p = _spawn(e, bins["relay"], {**base_env, "ORCH_RELAY_DATA_DIR": str(rd), "ORCH_RELAY_MASTER_KEY_FILE": str(e.tmp / "w2-relay.key"),
                                   "ORCH_RELAY_LISTEN": f"127.0.0.1:{rp}", "ORCH_RELAY_ADMIN_LISTEN": f"127.0.0.1:{ra}",
                                   "ORCH_RELAY_ADMIN_TOKEN": tok, "ORCH_RELAY_PUBLIC_ORIGIN": f"http://127.0.0.1:{rp}"}, "w2-relay")
    try:
        check(wait_http(f"http://127.0.0.1:{rp}/health", 30), "relay alone did not start")
        w = W(e, "V2-W2R").init()
        a = http("POST", f"http://127.0.0.1:{ra}/admin/api/workspaces", {"X-Orch-Admin": tok}, {"name": "w2-alone", "description": "alone", "tags": ["w2"]})
        check(a.status == 201, f"relay admin add: {a}")
        j = a.json()
        w.o("addon", "add", "relay", "--yes", by=None, env={})
        w.o("relay", "connect", f"http://127.0.0.1:{rp}", "--workspace", j["id"], "--token", j["token"], by=None)
        who = w.j("relay", "whoami", by=None)
        check(who["id"] == j["id"], f"relay whoami {who}")
        act = {a["name"] for a in w.j("addon", "list", by=None) if a.get("active")}
        check("relay" in act and "publish" not in act, f"active add-ons in the relay-only workspace: {act}")
    finally:
        _stop(p)
    # publish alone
    pd = e.tmp / "w2-publish"
    pd.mkdir()
    pp, pa = free_port(e.used_ports), free_port(e.used_ports)
    tokp = "p" * 8 + os.urandom(12).hex()
    base = None
    for _ in range(100):
        b = free_port(e.used_ports)
        if b < 18980:
            base = b
            break
    q = _spawn(e, bins["publish"], {**base_env, "ORCH_PUBLISH_DATA_DIR": str(pd), "ORCH_PUBLISH_LISTEN": f"127.0.0.1:{pp}",
                                     "ORCH_PUBLISH_ADMIN_LISTEN": f"127.0.0.1:{pa}", "ORCH_PUBLISH_ADMIN_TOKEN": tokp,
                                     "ORCH_PUBLISH_PUBLIC_ORIGIN": f"http://127.0.0.1:{pp}", "ORCH_PUBLISH_MAX_FILE_MB": "2",
                                     "ORCH_PUBLISH_APP_PORTS": f"{base}-{base}"}, "w2-publish")
    try:
        check(wait_http(f"http://127.0.0.1:{pp}/health", 30), "publish alone did not start")
        w2_ = W(e, "V2-W2P").init()
        a = http("POST", f"http://127.0.0.1:{pa}/admin/api/workspaces", {"X-Orch-Admin": tokp},
                 {"name": "w2-pub-alone", "description": "alone", "tags": ["w2"], "rights": {"files": True, "apps": False, "permanent": False, "public": False}})
        check(a.status == 201, f"publish admin add: {a}")
        j = a.json()
        w2_.o("addon", "add", "publish", "--yes", by=None)
        w2_.o("publish", "connect", f"http://127.0.0.1:{pp}", "--workspace", j["id"], "--token", j["token"], by=None)
        (w2_.root / "hello.txt").write_text("hello from publish alone\n")
        act = {a["name"] for a in w2_.j("addon", "list", by=None) if a.get("active")}
        check("publish" in act and "relay" not in act, f"active add-ons in the publish-only workspace: {act}")
        r = w2_.j("publish", "file", str(w2_.root / "hello.txt"), by=None)
        check(r.get("link") or r.get("url"), f"publish file result {r}")
    finally:
        _stop(q)


# ------------------------------------------------------------------------------------------------ Focus

FOCUS_AGENT = Path(__file__).parent / "fixtures" / "focus-agent" / "agent.py"
CLAUDE_FIXTURE = Path(__file__).resolve().parent.parent / "workspace-addons" / "focus" / "tests" / "fixtures" / "claude-run.jsonl"
SECRET_IN_FIXTURE = "abc123secretvalue"


class Focus:
    """The Focus add-on installed in a workspace, its page started, and the page's own API."""

    def __init__(self, w: W):
        self.w = w
        rc, out, err = w.sh(["orch", "addon", "add", "focus", "--yes"], timeout=600)
        check(rc == 0, f"addon add focus: {(err or out)[-300:]}")
        w.o("start", by=None)  # core starts the background add-ons and keeps the record `orch needs` checks
        self.base = w.j("focus", "status", by=None)["url"].rstrip("/")
        w.e.cleanup.append(lambda: w.sh(["orch", "stop"]))

    def get(self, path: str, headers: dict | None = None):
        return http("GET", self.base + path, headers)

    def view(self, tid: str) -> dict:
        r = self.get(f"/api/t/{tid}")
        check(r.status == 200, f"/api/t/{tid}: {r}")
        return r.json()

    def act(self, op: str, args: dict, headers: dict | None = None):
        h = {"Origin": self.base, "Sec-Fetch-Site": "same-origin", **(headers or {})}
        return http("POST", self.base + "/api/act", h, {"op": op, "args": args})

    def act_ok(self, op: str, args: dict) -> dict:
        r = self.act(op, args)
        check(r.status == 200, f"act {op}: {r}")
        return r.json()


def focus_agent(w: W, extra: str, name: str = "focusfake"):
    py, ag = shlex.quote(sys.executable), shlex.quote(str(FOCUS_AGENT))
    w.o("config", "agent", "add", name, "--command", f"{py} {ag} {extra} {{prompt}}", by=None)
    w.o("config", "set", "workspace.agent", name, by=None)


def _until_view(fx: Focus, tid: str, pred, secs: float = 40, what: str = ""):
    last = {}

    def probe():
        last["v"] = fx.view(tid)
        return pred(last["v"])

    check(wait_for(probe, secs, 0.4), f"{what or 'view'} never happened; last state {last.get('v', {}).get('state')}")
    return last["v"]


@scenario("V2-F1")
def f1_focus(e):
    """Focus, generic one-shot agent: tasks tick, a question shows in needs, answer via /api/act, board updates, send is saved."""
    w = W(e, "V2-F1").init()
    focus_agent(w, "--ask 'Use CHF?' --hold 2")
    tid = w.ticket("Invoice export", "first step", "second step")
    fx = Focus(w)
    started = fx.act_ok("run.start", {"ticket": tid})
    check(started["result"].get("run"), f"run.start result {started['result']}")
    v = _until_view(fx, tid, lambda v: v["state"] == "needs" and any(q.get("answer") is None for q in v["ticket"]["questions"]), what="open question on the board")
    check(v["generic"] is True and v["run"]["agent"] == "focusfake" and v["run"]["running"], f"board of a generic run: {v['run']}")
    check(v["done"] == 1 and v["total"] == 2, f"first task should be done by now: {v['done']}/{v['total']}")
    rows = w.j("needs", by=None)
    qrow = [r for r in rows if r["ticket"] == tid and r["kind"] == "question"]
    check(len(qrow) == 1 and qrow[0]["text"] == "Use CHF?", f"question not in orch needs: {rows}")
    # The dashboard accepts the Focus view while a run is active (its links are `addon:t/<ticket>`).
    rc, out, err = w.sh(["orch", "addon", "add", "dashboard", "--yes"], timeout=600)
    check(rc == 0, f"addon add dashboard: {(err or out)[-300:]}")
    w.o("start", by=None)  # core starts the new background add-on too
    dbase = w.j("dashboard", "status", by=None)["url"].rstrip("/")
    wait_http(dbase + "/")
    r = http("GET", dbase + "/api/addon/focus", timeout=15)
    status, pulled = r.status, r.json()
    check(status == 200 and pulled.get("state") == "ok" and pulled.get("view"), f"dashboard refused the Focus view of a running ticket: {pulled}")
    check(any(i.get("link") == f"addon:t/{tid}" for b in pulled["view"]["blocks"] for i in b.get("items", [])), f"run missing in the Focus view: {pulled['view']}")
    qid = next(q["id"] for q in v["ticket"]["questions"] if q.get("answer") is None)
    r = fx.act_ok("answer", {"ticket": tid, "question": qid, "answer": "Yes"})
    q = next(q for q in r["view"]["ticket"]["questions"] if q["id"] == qid)
    check(q["answer"] == "Yes" and q.get("via") == "focus", f"answer recorded as {q}")
    v = _until_view(fx, tid, lambda v: v["done"] == 2 and not v["run"]["running"], 60, "both tasks done and the run over")
    check(not [q for q in v["ticket"]["questions"] if q.get("answer") is None], "a question is still open")
    rest = w.j("needs", by=None)
    check(rest == [], f"needs not empty after the answer: {rest}")
    sent = fx.act_ok("run.send", {"ticket": tid, "text": "also add the VAT column"})
    check(sent["note"] == "Saved for the next run.", f"run.send note {sent['note']!r}")
    check(fx.view(tid)["run"]["pending"] == 1, "the saved message is not pending")


def fake_stream_claude(e, name: str) -> tuple[Path, Path]:
    """A `claude` that prints the Focus stream-json fixture and stays up 8 s; when started with --allowedTools it prints a clean run."""
    d = e.tmp / "fakeclaude" / name
    d.mkdir(parents=True)
    calls = d / "calls.txt"
    f = d / "claude"
    f.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "2.0.0 (fake)"; exit 0; fi\n'
        f'echo "$@" | tr "\\n" " " >> {shlex.quote(str(calls))}; echo >> {shlex.quote(str(calls))}\n'
        'if echo "$@" | grep -q -- "--allowedTools"; then\n'
        '  echo \'{"type": "system", "subtype": "init", "session_id": "s2"}\'\n'
        '  echo \'{"type": "result", "num_turns": 1, "is_error": false, "permission_denials": []}\'\n  exit 0\nfi\n'
        f"cat {shlex.quote(str(CLAUDE_FIXTURE))}\nsleep 8\n"
    )
    f.chmod(0o755)
    return d, calls


@scenario("V2-F2")
def f2_focus(e):
    """Focus, Claude one-shot (fake claude, stream-json): steps, helpers, usage on the board; a denial asks; Allow and retry runs once with --allow."""
    d, calls = fake_stream_claude(e, "f2")
    w = W(e, "V2-F2", tmux=False, extra_bin=d).init()
    w.o("config", "set", "workspace.agent", "claude", by=None)
    tid = w.ticket("Colours", "check the brand colours")
    fx = Focus(w)
    fx.act_ok("run.start", {"ticket": tid})
    v = _until_view(fx, tid, lambda v: v["board"]["denials"] and v["board"]["usage"] and any(e_["kind"] == "helper.end" for e_ in v["events"]), 40, "steps, usage and the denial on the board")
    kinds = {e_["kind"] for e_ in v["events"]}
    check({"tool.start", "tool.end", "helper.start", "helper.end"} <= kinds, f"event kinds on the board: {sorted(kinds)}")
    texts = " | ".join(e_["text"] for e_ in v["events"])
    check("Run invoice tests" in texts and "checking colours" in texts, f"step texts: {texts[:300]}")
    check(SECRET_IN_FIXTURE not in json.dumps(v), "a secret from a command reached the page data")
    check(v["board"]["usage"]["status"] == "warning" and v["board"]["usage"]["text"], f"usage line: {v['board']['usage']}")
    check(v["board"]["denials"][0]["tool"] == "WebFetch", f"denials: {v['board']['denials']}")
    v = _until_view(fx, tid, lambda v: any(q.get("kind") == "focus:permission" and q.get("answer") is None for q in v["ticket"]["questions"]), 30, "a focus:permission question")
    q = next(q for q in v["ticket"]["questions"] if q.get("kind") == "focus:permission")
    check(q["options"] == ["Allow and retry", "Not now"] and "WebFetch" in q["text"], f"permission question {q}")
    check(len(calls.read_text().splitlines()) == 1, "more than one run before the answer")
    w.wait_done(tid, 40)
    fx.act_ok("answer", {"ticket": tid, "question": q["id"], "answer": "Allow and retry"})
    check(wait_for(lambda: len(calls.read_text().splitlines()) == 2, 30), f"Allow and retry did not start a new run: {calls.read_text()!r}")
    second = calls.read_text().splitlines()[1]
    check("--allowedTools" in second and "WebFetch" in second, f"second run lacks --allow: {second!r}")
    w.wait_done(tid, 40)
    fx.view(tid)  # looking again must not start a third run
    time.sleep(3)
    check(len(calls.read_text().splitlines()) == 2, f"Allow and retry started more than one run: {calls.read_text()!r}")
    check(not [x for x in fx.view(tid)["ticket"]["questions"] if x.get("answer") is None], "a question is still open")


@scenario("V2-F3")
def f3_focus(e):
    """Focus, live in tmux: start via /api/act, send when idle, 'Waiting for your OK', Stop ends it, `orch focus stop` leaves nothing."""
    if not shutil.which("tmux", path=e.path):
        from lib import Skip
        raise Skip("tmux is not installed")
    w = W(e, "V2-F3", tmux=True).init()
    w.agent(interactive=True)
    tid = w.ticket("Live work", "step")
    fx = Focus(w)
    started = fx.act_ok("run.start", {"ticket": tid})["result"]
    check(started["mode"] == "live" and started["tmux"], f"run.start through Focus should be live: {started}")
    v = _until_view(fx, tid, lambda v: v["live"] and v["run"]["running"] and (w.claim(tid) or {}).get("live", {}).get("state") == "idle", 40, "a live run waiting for input")
    check(wait_for(lambda: w.lines("input"), 30), "the first prompt never reached the live agent")
    sent = fx.act_ok("run.send", {"ticket": tid, "text": "Use CHF please"})
    check(wait_for(lambda: len(w.lines("input")) == 2, 30), f"sent text never arrived (note {sent['note']!r})")
    check(w.lines("input")[1].endswith(": Use CHF please"), f"second input {w.lines('input')[1]!r}")
    time.sleep(1.5)
    check(len(w.lines("input")) == 2, f"input arrived more than once: {w.lines('input')}")
    # the tool says it waits for the person's OK (its Notification hook)
    run = w.claim(tid)["run"]
    w.o("run", "event", "--run", run, "--kind", "attention", by=None)
    v = _until_view(fx, tid, lambda v: v["attention"], 20, "the attention state")
    check(v["state"] == "needs", f"attention should read as needs: {v['state']}")
    blocks = w.j("focus", "view", by=None)
    check("Waiting for your OK" in json.dumps(blocks), f"focus view lacks 'Waiting for your OK': {blocks}")
    rows = w.j("focus", "needs", by=None)
    check(any(r["kind"] == "focus:waiting" and r["ticket"] == tid for r in rows), f"focus needs rows {rows}")
    w.o("run", "event", "--run", run, "--kind", "idle", by=None)
    check(wait_for(lambda: not fx.view(tid)["attention"], 10), "attention did not clear on idle")
    # Stop ends the run
    fx.act_ok("run.stop", {"ticket": tid})
    check(wait_for(lambda: w.claim(tid) is None, 20), "claim still there after Stop")
    check(not fx.view(tid)["run"]["running"], "page still says running after Stop")
    # a run Focus started does not outlive Focus
    fx.act_ok("run.start", {"ticket": tid})
    check(wait_for(lambda: w.claim(tid), 20), "second live run did not start")
    sock = w.claim(tid)["tmux"]["socket"]
    w.o("focus", "stop", by=None)
    check(wait_for(lambda: w.claim(tid) is None, 20), f"`orch focus stop` left a run behind: {w.claim(tid)}")
    rc = subprocess.run(["tmux", "-L", sock, "has-session", "-t", f"={tid}:"], capture_output=True, env=w.env).returncode
    check(rc != 0, "tmux session still exists after `orch focus stop`")


@scenario("V2-F4")
def f4_focus(e):
    """Focus fence: bad Host, cross-site, no Origin refused; a bad run id writes nothing; view and needs match their schemas."""
    from jsonschema import Draft202012Validator, FormatChecker

    w = W(e, "V2-F4").init()
    focus_agent(w, "--hold 12")
    tid = w.ticket("Fence", "step")
    fx = Focus(w)
    body = {"ticket": tid}
    before = w.claim(tid)
    check(before is None, "unexpected claim")
    evil = "http://evil.example"
    refused = {
        "bad Host (GET)": fx.get("/api/tickets", {"Host": "evil.example"}),
        "bad Host (POST)": fx.act("run.start", body, {"Host": "evil.example"}),
        "cross-site Origin": fx.act("run.start", body, {"Origin": evil}),
        "cross-site fetch": fx.act("run.start", body, {"Sec-Fetch-Site": "cross-site"}),
        "no Origin": http("POST", fx.base + "/api/act", {"Sec-Fetch-Site": "same-origin"}, {"op": "run.start", "args": body}),
        "not JSON": http("POST", fx.base + "/api/act", {"Origin": fx.base, "Content-Type": "text/plain"}, b'{"op":"run.start"}'),
    }
    for what, r in refused.items():
        check(r.status in (400, 403, 415), f"{what} was not refused: {r}")
    check(w.claim(tid) is None, "a refused request started a run")
    check(fx.get("/api/tickets").status == 200, "the page itself no longer answers a proper request")
    r = fx.act("run.start", {"ticket": "../../etc"})
    check(r.status == 400, f"a bad ticket id must be refused: {r}")
    r = fx.act("rm -rf", {"ticket": tid})
    check(r.status == 400, f"an unknown op must be refused: {r}")
    # a claim that names a bad run id: the page shows no run id and writes no file for it
    claim = {"schema": "orch.run/1", "ticket": tid, "run": "../../evil", "by": "agent:x", "agent": "focusfake", "mode": "oneshot",
             "tmux": None, "pid": os.getpid(), "pid_started": None, "started_at": "2026-11-05T10:00:00Z",
             "renewed_at": "2026-11-05T10:00:00Z", "pending": False, "stop_requested": None, "seen_revision": 1, "seen_history": 1}
    cf = w.claim_file(tid)
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(claim))

    def evil(p: Path) -> bool:
        # a file or folder named for the bad run id; not "Libreville" in the add-on's uv tool install (tzdata)
        return "uvtools" not in p.parts and any(part.startswith("evil") for part in p.parts)

    def files() -> set:
        return {str(p.relative_to(e.tmp)) for p in e.tmp.rglob("*") if p.is_file() and ".git" not in p.parts and evil(p)}

    snap = {str(p) for p in w.root.rglob("*") if ".git" not in p.parts}
    v = fx.view(tid)
    check(v["run"]["run"] is None, f"a bad run id is shown on the page: {v['run']}")
    check(not files() and not any("evil" in str(p) for p in Path(e.tmp).parent.glob("evil*")), f"files written for a bad run id: {files()}")
    new = {str(p) for p in w.root.rglob("*") if ".git" not in p.parts} - snap
    check(not [n for n in new if evil(Path(n))], f"files written for a bad run id: {new}")
    cf.unlink()
    # view and needs against their schemas, with a run going
    fx.act_ok("run.start", {"ticket": tid})
    check(wait_for(lambda: w.claim(tid), 15), "run did not start")
    contracts = e.repo / "contracts"
    view = w.j("focus", "view", by=None)
    needs = w.j("focus", "needs", by=None)
    allneeds = w.j("needs", by=None)
    for what, doc, schema in (("focus view", view, "addon-view"), ("focus needs", needs, "needs"), ("orch needs", allneeds, "needs")):
        sch = json.loads((contracts / f"{schema}.schema.json").read_text())
        errs = [f"{list(x.path)}: {x.message}" for x in Draft202012Validator(sch, format_checker=FormatChecker()).iter_errors(doc)]
        check(not errs, f"{what} does not match {schema}.schema.json: {errs[:3]}")
    check(view["blocks"] and "Fence" in json.dumps(view), f"focus view does not show the running ticket: {view}")
    w.wait_done(tid, 40)


# ------------------------------------------------------------------------------------------------ demo bugs (6 Nov)


@scenario("V2-F5")
def f5_dashboard_focus_view_while_running(e):
    """The dashboard accepts the Focus view while a fake agent run is active (state ok, the item links to the running ticket)."""
    w = W(e, "V2-F5").init()
    focus_agent(w, "--hold 15")
    tid = w.ticket("Running now", "one step")
    fx = Focus(w)
    fx.act_ok("run.start", {"ticket": tid})
    w.wait_claim(tid)
    rc, out, err = w.sh(["orch", "addon", "add", "dashboard", "--yes"], timeout=600)
    check(rc == 0, f"addon add dashboard: {(err or out)[-300:]}")
    w.o("start", by=None)
    dbase = w.j("dashboard", "status", by=None)["url"].rstrip("/")
    check(wait_http(dbase + "/"), "the dashboard did not come up")
    check(w.claim(tid), "the run ended before the dashboard was asked (raise --hold)")
    r = http("GET", dbase + "/api/addon/focus", timeout=15)
    j = r.json() or {}
    check(r.status == 200 and j.get("state") == "ok" and j.get("view"), f"the dashboard refused the Focus view of a running ticket: {r}")
    links = [i.get("link") for b in j["view"]["blocks"] for i in b.get("items", [])]
    check(f"addon:t/{tid}" in links, f"the running ticket is not linked in the Focus view: {links}")
    w.wait_done(tid, 40)


@scenario("V2-S2")
def s2_dashboard_start_makes_tasks(e):
    """A dashboard `run.start` with a fake one-shot agent finishes at least one task (#135: Start used to stay 'working' forever)."""
    w = W(e, "V2-S2").init()
    w.agent()
    tid = w.ticket("Start from the dashboard", "first step", "second step")
    rc, out, err = w.sh(["orch", "addon", "add", "dashboard", "--yes"], timeout=600)
    check(rc == 0, f"addon add dashboard: {(err or out)[-300:]}")
    w.o("start", by=None)
    dbase = w.j("dashboard", "status", by=None)["url"].rstrip("/")
    check(wait_http(dbase + "/"), "the dashboard did not come up")
    r = http("POST", dbase + "/api/act", {"Origin": dbase, "Sec-Fetch-Site": "same-origin"}, {"op": "run.start", "args": {"ticket": tid}})
    check(r.status == 200, f"dashboard run.start: {r}")
    done = wait_for(lambda: [c for c in w.load(tid)["checklist"] if c.get("done")], 45)
    check(done, f"no task done 45 s after Start: {w.load(tid)['checklist']}; agent log: {w.lines('prompt')}")
    check(w.lines("prompt"), "the fake agent never got a prompt")
    w.wait_done(tid, 40)


OLD_REF = "142ec615ba554aae0f29efde8d9fcdcde794d1f8"  # the last orch before the add-on registry fixes of 6 Nov: add-ons dashboard + scheduler


@scenario("V2-U1", slow=True, local_only=True)
def u1_upgrade_from_old_orch(e):
    """Old orch (pinned commit, installed the way the old installer did) with dashboard + scheduler, then the current install.sh:
    `orch start` starts the add-ons, `orch update` works, `orch addon add focus --yes` works, and the old scheduler entry
    is skipped plainly (automation is added with `orch addon add automation --yes`). Pending on the removal of the compat code (#136)."""
    if "RENAMED" in (e.repo / "workspace" / "src" / "orch" / "addons.py").read_text():
        from lib import Skip
        raise Skip("pending on #136 (scheduler->automation compat code still there; this scenario asserts its removal)")
    if subprocess.run(["git", "-C", str(e.repo), "cat-file", "-e", OLD_REF + "^{commit}"], capture_output=True).returncode != 0:
        from lib import Skip
        raise Skip(f"commit {OLD_REF} is not in this clone (git fetch)")
    real = os.environ.get("E2E_REAL_HOME") or str(Path.home())
    ohome = Path(real) / f".orch-e2e-u1-{os.getpid()}"  # ORCH_HOME is only trusted under the real home, outside any git folder
    ohome.mkdir()
    import shutil as _sh
    e.cleanup.append(lambda: _sh.rmtree(ohome, ignore_errors=True))
    tools, ubin = e.tmp / "u1-uvtools", e.tmp / "u1-bin"
    ubin.mkdir()
    old_env = {"UV_TOOL_DIR": str(tools), "UV_TOOL_BIN_DIR": str(ubin), "ORCH_HOME": str(ohome),
               "ORCH_REPO": "file://" + str(e.repo), "ORCH_REF": OLD_REF}
    w = W(e, "V2-U1", extra_bin=ubin, env=old_env)
    # 1) the old install.sh does exactly this: uv tool install --reinstall git+<repo>@<ref>#subdirectory=workspace
    rc, out, err = w.sh(["uv", "tool", "install", "--reinstall", f"git+file://{e.repo}@{OLD_REF}#subdirectory=workspace"], timeout=900)
    check(rc == 0, f"old orch install: {(err or out)[-300:]}")
    w.o("init", "--yes", by=None)
    for name in ("dashboard", "scheduler"):
        rc, out, err = w.sh(["orch", "addon", "add", name, "--yes"], timeout=900)
        check(rc == 0, f"old orch: addon add {name}: {(err or out)[-300:]}")
    # 2) the current installer, from this checkout (the way a user upgrades), same machine folders
    new_env = {"ORCH_REPO": str(e.repo)}
    new_env_all = {**new_env, "ORCH_REF": ""}
    rc, out, err = w.sh(["sh", str(e.repo / "install.sh")], env=new_env_all, timeout=900)
    check(rc == 0, f"current install.sh: {(err or out)[-400:]}")
    text = out + err
    check("Traceback" not in text, f"install.sh printed a traceback: {text[-400:]}")
    # 3) the work folder starts, updates and gets a new add-on
    rc, out, err = w.sh(["orch", "start"], env=new_env_all, timeout=300)
    check(rc == 0, f"orch start after the upgrade: {(err or out)[-300:]}")
    dbase = w.j("dashboard", "status", by=None, env=new_env_all)["url"].rstrip("/")
    check(wait_http(dbase + "/"), "the dashboard add-on did not start after the upgrade")
    rc, out, err = w.sh(["orch", "update"], env=new_env_all, timeout=900)
    check(rc == 0 and "Traceback" not in out + err, f"orch update: {(err or out)[-400:]}")
    rc, out, err = w.sh(["orch", "addon", "add", "focus", "--yes"], env=new_env_all, timeout=900)
    check(rc == 0, f"addon add focus after the upgrade: {(err or out)[-300:]}")
    rc, out, err = w.sh(["orch", "addon", "add", "automation", "--yes"], env=new_env_all, timeout=900)
    check(rc == 0, f"addon add automation after the upgrade: {(err or out)[-300:]}")
    rows = w.j("addon", "list", by=None, env=new_env_all)
    on = {r["name"] for r in rows if r.get("active")}
    check({"dashboard", "focus", "automation"} <= on, f"active add-ons after the upgrade: {sorted(on)}")
    check("scheduler" not in on, f"the old scheduler is still listed as on: {sorted(on)}")

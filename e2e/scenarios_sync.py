"""git-sync: the sync add-on end to end on one machine (workspaces A, B, C), with a local bare repository as the remote.

Two workspaces keep the same tickets through the remote, edit them on both sides, work offline, meet a conflict and
resolve it with the person's signed choice. A third workspace whose team repository tracks .orch files is asked to
Move them out first. The person's proofs come from the scripted test human of a TEST install (the e2e driver writes
the install record into the tool environment, like the installer does): never a real person, never a real home.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from lib import Fail, check, scenario

PREVIEW = {"ORCH_SYNC_REMOTE_PREVIEW": "1"}  # copying to a remote is a preview; on only inside this scenario
ENV: dict = {}  # PREVIEW plus the scenario's own orch folder (a test workspace needs one under <home>/.orch-test)


class Ws:
    """One workspace folder (under <real home>/.orch-test, a test workspace) and the way to run orch in it."""

    def __init__(self, e, py, root: Path):
        self.e, self.py, self.root = e, py, root

    def sh(self, cmd, input=None, ok=True):
        rc, out, err = self.e.sh(cmd, cwd=self.root, env=ENV, input=input, timeout=120)
        if ok and rc != 0:
            raise Fail(f"{' '.join(map(str, cmd))[:90]} in {self.root.name}: exit {rc}: {(err or out).strip()[-240:]}")
        return rc, out, err

    def o(self, *args, input=None, ok=True):
        return self.sh(["orch", *args], input=input, ok=ok)

    def j(self, *args, input=None, ok=True):
        _, out, _ = self.o(*args, "--json", input=input, ok=ok)
        try:
            return json.loads(out)
        except ValueError:
            raise Fail(f"orch {' '.join(args)[:60]} did not print JSON: {out[:160]!r}") from None

    def proof(self, op: str, target: str) -> str:
        """The test human's proof for (op, target): single use, 30 seconds."""
        code = ("import sys; from pathlib import Path; from orch import humanproof as h; "
                "print(h.mint_dev(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))")
        rc, out, err = self.e.sh([self.py, "-c", code, str(self.root), op, target], cwd=self.root, env=ENV)
        check(rc == 0 and out.startswith("hp1."), f"no test-human proof for {op}: {(err or out)[-200:]}")
        return out.strip() + "\n"

    def signed(self, argv, op: str, target: str, ok=True):
        return self.o(*argv, "--proof-stdin", input=self.proof(op, target), ok=ok)

    def act_target(self, verb: str, target: str, *extra) -> str:
        return self.j("sync", "act", verb, target, *extra, "--proof-target")["target"]

    def set_remote(self, remote: Path, ok=True):
        t = self.act_target("set", str(remote))
        return self.signed(["sync", "set", "--mode", "remote", "--remote", str(remote)], "addon.act", t, ok=ok)

    def status(self) -> dict:
        return self.j("sync", "status")

    def now(self) -> dict:
        return self.j("sync", "now", ok=False)  # a step that ends in last_error exits non-zero, with the state as JSON

    def ticket(self, tid: str) -> dict:
        return self.j("ticket", "show", tid)

    def sync_rows(self) -> list[dict]:
        out = self.j("needs")
        rows = out if isinstance(out, list) else (out.get("needs") or out.get("items") or [])
        return [r for r in rows if isinstance(r, dict) and str(r.get("id", "")).startswith("sync:")]


def _tool_python(e) -> str:
    """The interpreter of orch's own tool environment (its shebang), where `orch.humanproof` can be imported."""
    shim = (e.bin / "orch").resolve()
    first = shim.read_text(errors="replace").splitlines()[0]
    check(first.startswith("#!"), f"orch shim has no shebang: {first[:80]!r}")
    return first[2:].strip().split()[0]


def _workspace(e, py, base: Path, name: str, git: bool = False) -> Ws:
    root = base / name
    root.mkdir(parents=True)
    if git:
        e.sh(["git", "init", "-q", "-b", "main"], cwd=root, check_rc=True)
    w = Ws(e, py, root)
    w.o("init", "--yes")
    w.o("dev-mark")
    w.o("addon", "add", "sync", "--yes")
    return w


@scenario("git-sync", local_only=True)
def git_sync(e):
    py = _tool_python(e)
    real = Path(os.environ.get("E2E_REAL_HOME") or Path.home())
    base = real / ".orch-test" / f"e2e-gitsync-{os.getpid()}"
    base.mkdir(parents=True)
    (base / "home").mkdir()
    ENV.clear()
    ENV.update(PREVIEW, ORCH_HOME=str(base / "home"))
    e.cleanup.append(lambda: shutil.rmtree(base, ignore_errors=True))
    # the install record of a TEST install, as the installer writes it (it decides what the test human may do).
    # Only ever into this run's own tool environment under the run's temp folder, and removed afterwards, so
    # later scenarios of the same run and every real install keep their own record.
    rc, out, err = e.sh([py, "-c", "import os, sys; print(os.path.realpath(sys.prefix))"], env=ENV)
    prefix = Path(out.strip())
    check(rc == 0 and prefix.is_relative_to(Path(e.tmp).resolve()), f"tool env is not this run's: {prefix}")
    record = prefix / "orch-install.json"
    old_record = record.read_bytes() if record.exists() else None
    def restore():
        record.write_bytes(old_record) if old_record is not None else record.unlink(missing_ok=True)

    e.cleanup.append(restore)  # backstop; the finally below restores it right after this scenario
    rc, out, err = e.sh([py, "-c", ("import sys; from pathlib import Path; from orch import humanproof as h; "
                         "h.write_install_record(Path(sys.prefix), 'test')")], env=ENV)
    check(rc == 0, f"install record: {(err or out)[-200:]}")
    try:

        bare = base / "remote.git"
        e.sh(["git", "init", "-q", "--bare", "-b", "orch-state", str(bare)], check_rc=True)
        a = _workspace(e, py, base, "A")
        b = _workspace(e, py, base, "B")

        # 1. A: a ticket; local, then remote with the person's choice; now -> the remote has orch-state
        tid = a.j("ticket", "new", "Pay the invoices")["id"]
        a.o("sync", "set", "--mode", "local")
        a.set_remote(bare)
        st = a.now()
        check(not st.get("last_error"), f"A first sync: {st}")
        heads = e.sh(["git", "--git-dir", str(bare), "branch", "--list", "orch-state"], check_rc=True)[1]
        check("orch-state" in heads, f"remote has no orch-state: {heads!r}")

        # 2. B joins the same remote (signed); its first sync brings A's ticket
        b.set_remote(bare)
        st = b.now()
        check(not st.get("last_error"), f"B first sync: {st}")
        check(b.ticket(tid)["title"] == "Pay the invoices", "B does not see A's ticket")

        # 3. different fields of the same ticket on both sides -> merged on both
        a.o("ticket", "edit", tid, "--note", "from A")
        b.o("ticket", "edit", tid, "--due", "2026-12-01")
        for w in (a, b, a):
            check(not w.now().get("last_error"), "merge round failed")
        for w in (a, b):
            t = w.ticket(tid)
            check(t.get("note") == "from A" and t.get("due") == "2026-12-01", f"{w.root.name} not merged: note={t.get('note')!r} due={t.get('due')!r}")

        # 4. offline: the remote is away -> offline, commits pile up; back -> pushed, B receives it
        away = base / "remote-away.git"
        bare.rename(away)
        a.o("ticket", "edit", tid, "--title", "Pay the invoices today")
        st = a.now()
        check(st.get("last_error") and "offline" in str(st["last_error"]).lower(), f"not offline: {st.get('last_error')!r}")
        a.o("ticket", "edit", tid, "--owner", "Anna")
        a.now()
        check((a.status().get("ahead") or 0) > 0, f"no commits piled up: {a.status()}")
        away.rename(bare)
        check(not a.now().get("last_error"), "A did not recover")
        check(a.status().get("ahead") in (0, None), f"A still ahead: {a.status()}")
        check(not b.now().get("last_error"), "B round failed")
        check(b.ticket(tid)["title"] == "Pay the invoices today", "B did not receive the offline work")

        # 5. the same file changed on both sides can't be merged -> a pause with a Needs row; keep theirs with the
        #    person's proof -> both converge (the file the person set aside stays as a dated copy, on both)
        path = f"tickets/{tid}/artifacts/plan.txt"
        for w, text in ((a, "base\n"),):
            (w.root / ".orch" / path).parent.mkdir(parents=True, exist_ok=True)
            (w.root / ".orch" / path).write_text(text)
        for w in (a, b, a):
            check(not w.now().get("last_error"), "artifact round failed")
        check((b.root / ".orch" / path).read_text() == "base\n", "B did not get the artifact")
        (a.root / ".orch" / path).write_text("A says one\n")
        (b.root / ".orch" / path).write_text("B says two\n")
        a.now()
        st = b.now()
        rows = b.sync_rows()
        check(st.get("paused") and rows, f"no pause/row on B: rows={rows} needs={b.o('needs', '--json', ok=False)[1][:2000]}")
        check((b.root / ".orch" / path).read_text() == "B says two\n", "the pause changed B's own file")
        t = b.act_target("keep-theirs", path)
        argv = ["sync", "resolve", path, "--keep", "theirs"]
        # a changed file of a ticket (this case) needs no proof (ticket files and the counter are signed)
        check(not t, f"an artifact choice unexpectedly needs a proof: {t}")
        b.o(*argv)
        check(not b.sync_rows(), f"row still there after the choice: {b.sync_rows()}")
        for w in (b, a, b, a):
            check(not w.now().get("last_error"), "converge round failed")
        ta, tb = ((w.root / ".orch" / path).read_text() for w in (a, b))
        check(ta == tb == "A says one\n", f"not converged: A={ta!r} B={tb!r}")

        # 6. Move: C's team repository tracks .orch files -> refused with the Move row; the person's Move untracks them
        c = _workspace(e, py, base, "C", git=True)
        c.j("ticket", "new", "Tracked by the team")
        e.sh(["git", "-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", "add", "-f", ".orch/tickets", ".orch/ticket-counter.json", ".orch/config.toml"], cwd=c.root, check_rc=True)
        e.sh(["git", "-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", "commit", "-q", "-m", "team"],
             cwd=c.root, check_rc=True)
        (c.root / "team.txt").write_text("a team file\n")
        e.sh(["git", "add", "team.txt"], cwd=c.root, check_rc=True)
        outer_before = e.sh(["git", "log", "--oneline"], cwd=c.root, check_rc=True)[1]
        rc, out, err = c.o("sync", "set", "--mode", "local", ok=False)
        check(rc != 0 and "needs-move" in err + out, f"C was not refused: rc={rc} {(err or out)[-200:]}")
        check(not (c.root / ".orch" / ".git").exists(), "sync made a state repository before the Move")
        rows = c.sync_rows()
        check(any(r.get("id") == "sync:move:orch-files" for r in rows), f"no Move row: {rows}")
        tracked = e.sh(["git", "ls-files", ".orch"], cwd=c.root, check_rc=True)[1]
        check(".orch/tickets/" in tracked, "the outer repository lost its .orch files before the Move")
        rc, _, _ = c.o("private", "move", ok=False)  # no proof: refused
        check(rc != 0, "Move without a proof did not fail")
        check(".orch/tickets/" in e.sh(["git", "ls-files", ".orch"], cwd=c.root)[1], "Move without a proof changed the index")
        c.signed(["private", "move"], "private.move", "move")
        left = e.sh(["git", "ls-files", ".orch"], cwd=c.root, check_rc=True)[1]
        check(".orch/tickets/" not in left, f"tickets still tracked after Move: {left!r}")
        check(e.sh(["git", "log", "--oneline"], cwd=c.root)[1] == outer_before, "Move committed in the outer repository")
        check("team.txt" in e.sh(["git", "ls-files"], cwd=c.root)[1], "Move touched another outer file")
        c.o("sync", "set", "--mode", "local")
        st = c.now()
        check(not st.get("last_error"), f"C does not sync after Move: {st}")
        check((c.root / ".orch" / ".git").exists(), "no state repository after Move")
        check(not c.sync_rows(), f"Move row still there: {c.sync_rows()}")
        return "A+B sync, merge, offline, conflict resolved, C moved out of the team repository"
    finally:
        restore()  # later scenarios of the same run see their own install record again

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from orch import addons, cli, winfinish

_REAL_HOME_FN = addons.real_home  # the true one, before any test fakes it
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def _guard_bases() -> list[Path]:
    """The orch homes the guard watches: ALWAYS the real account home (getpwuid), plus ORCH_TEST_GUARD_HOME's
    when set (only tests/test_session_guard.py sets it). The override adds a location, never replaces."""
    bases = [_REAL_HOME_FN() / ".orch-tool"]
    extra = os.environ.get("ORCH_TEST_GUARD_HOME")
    if extra:
        bases.append(Path(extra) / ".orch-tool")
    return bases


def _snapshot_real_tool_home():
    """{path: (size, sha256, mtime_ns)} of the watched orch homes (read only), without the fallback trace; and
    the trace lines. A path that can not be read maps to None."""
    files, trace = {}, []
    for base in _guard_bases():
        _snapshot_one(base, files, trace)
    return files, trace


def _snapshot_one(base: Path, files: dict, trace: list) -> None:
    if base.exists():
        for p in (base, *base.rglob("*")):
            try:
                if p.name.startswith(".fallback-trace.log"):
                    if p.name == ".fallback-trace.log" and not p.is_symlink():
                        trace += p.read_text(encoding="utf-8", errors="replace").splitlines()
                    continue
                if p.is_dir() and not p.is_symlink():
                    files[str(p)] = "dir"  # a folder's mtime moves when the trace file is made or rotated
                    continue
                st = p.stat()
                digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
                files[str(p)] = (st.st_size, digest, st.st_mtime_ns)
            except OSError:
                files[str(p)] = None


_REAL_AT_START, _TRACE_AT_START = _snapshot_real_tool_home()
_PYTEST_TMP = Path(tempfile.gettempdir()).resolve()


def _ours(line: dict) -> bool:
    """A trace line written by this pytest session or its children: its pid or ppid is in this session's
    registry (the controller and every xdist worker register theirs). By pid only: a path prefix would blame
    this run for a parallel session's lines (shared pytest-of-<user> folder)."""
    reg = os.environ.get("ORCH_TEST_SESSION_PIDS")
    if not reg or not Path(reg).exists():
        return False
    pids = {int(x) for x in Path(reg).read_text().split() if x.isdigit()}
    return line.get("pid") in pids or line.get("ppid") in pids


def pytest_configure(config):
    reg = os.environ.get("ORCH_TEST_SESSION_PIDS")
    if not reg:  # the controller (or a plain run) makes the registry; xdist workers inherit the variable
        fd, reg = tempfile.mkstemp(prefix="orch-test-pids-")
        os.close(fd)
        os.environ["ORCH_TEST_SESSION_PIDS"] = reg
    with open(reg, "a") as f:
        f.write(f"{os.getpid()}\n")


@pytest.fixture(autouse=True)
def _strict_orch_home(monkeypatch, tmp_path_factory):
    """Every test: a faked real home with its own ORCH_HOME (a test that never asked for `proj` used to write
    the real ~/.orch-tool/addons.json: ORCH_HOME unset = real folder); untrusted ORCH_HOME = error."""
    fake = tmp_path_factory.mktemp("realhome")
    monkeypatch.setattr(addons, "real_home", lambda: fake)
    monkeypatch.setenv("ORCH_HOME", str(fake / "toolhome"))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    # children and Path.home()/expanduser fallbacks must not find the real home through $HOME either
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))


def pytest_sessionfinish(session, exitstatus):
    """Read-only guard, run by the controller only. The real ~/.orch-tool must look the same after the run:
    any file that changed fails the session (the message says: content changed, or only touched). New fallback
    trace lines are printed; they fail the session when they come from this session's own processes, and only
    warn when a foreign process wrote them."""
    if hasattr(session.config, "workerinput"):
        return
    stray = stray_tmux(str(_REAL_HOME_FN() / ".orch-test" / "pytest-page-"))
    if stray:  # a page test left an agent session behind: fail the run (hard), name the sockets
        print(f"\nSTRAY orch tmux servers from this suite: {stray}", file=sys.stderr)
        session.exitstatus = 1
    files, trace = _snapshot_real_tool_home()
    bad = False
    for k in sorted(set(files) | set(_REAL_AT_START)):
        before, after = _REAL_AT_START.get(k), files.get(k)
        if before != after:
            kind = (
                "content changed"
                if (before and after and before[:2] != after[:2])
                else "only touched or (re)created/removed"
            )
            print(f"\nREAL ~/.orch-tool CHANGED: {k}: {kind}", file=sys.stderr)
            bad = True
    new = [x for x in trace if x not in _TRACE_AT_START]
    for raw in new:
        try:
            line = json.loads(raw)
        except ValueError:
            line = {}
        ours = _ours(line)
        print(
            f"\nREAL ~/.orch-tool fallback trace ({'THIS SESSION' if ours else 'foreign process'}): {raw}",
            file=sys.stderr,
        )
        bad = bad or ours
    if bad:
        session.exitstatus = 1
    reg = os.environ.get("ORCH_TEST_SESSION_PIDS")
    if reg and os.path.basename(reg).startswith("orch-test-pids-"):
        try:
            os.unlink(reg)  # exact path made in pytest_configure
        except OSError:
            pass


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    for k in list(os.environ):
        if k.startswith("CODEX_"):
            monkeypatch.delenv(k)
    fake_home = tmp_path.parent / f"{tmp_path.name}_home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setattr(addons, "real_home", lambda: fake_home)
    monkeypatch.setenv("ORCH_HOME", str(fake_home / "orchhome"))
    # an agent tool's own settings (a live start marks the folder trusted there): never the real ones
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(fake_home))
    # Windows finishes add-on installs and updates in a background process (winfinish), which tests can not
    # wait for: they run the same steps in the command itself, as on other systems. test_winfinish.py covers
    # the background path (it sets needed() itself), the Windows e2e flows cover it for real.
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    # An answer starts the asking agent again (fb9). Only the tests that set up a fake agent let that happen
    # (fixture `auto_resume`); anywhere else it would start the real agent tool found on this machine.
    from orch import runs_live

    monkeypatch.setattr(runs_live, "resume_after_answer", lambda *a, **k: None)
    return tmp_path


@pytest.fixture
def subprocess_home(proj, monkeypatch):
    """For tests that start `orch` as a child process: it cannot see the faked real_home, so ORCH_HOME must
    be a folder the child trusts too: a fresh one under ~/.orch-test (never ~/.orch-tool), removed by path."""
    import shutil
    import tempfile

    base = _REAL_HOME_FN() / ".orch-test"
    base.mkdir(exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="pytest-", dir=base))
    monkeypatch.setattr(addons, "real_home", _REAL_HOME_FN)
    monkeypatch.setenv("ORCH_HOME", str(d))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def run(capsys):
    def _run(*argv):
        code = cli.main(list(argv))
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    return _run


@pytest.fixture
def validate():
    import jsonschema

    schema = json.loads((CONTRACTS / "ticket.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())

    def _v(ticket):
        errs = sorted(v.iter_errors(ticket), key=lambda e: list(e.path))
        assert not errs, [f"{list(e.path)}: {e.message}" for e in errs]

    return _v


@pytest.fixture
def new_ticket(proj, run):
    def _n(title="Do the thing"):
        code, out, _ = run("ticket", "new", title, "--json", "--by", "human:tester")
        assert code == 0
        return json.loads(out)["id"]

    return _n


def turn_on(root, name):
    """`orch addon add <name> --yes` for the built-in publish/relay add-ons, output swallowed."""
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        addons.add(root, name, yes=True)


@pytest.fixture
def pub(proj, run):
    from fakes import make_publish

    turn_on(proj, "publish")
    srv = make_publish()
    yield srv
    srv.stop()


@pytest.fixture
def rel(proj, run):
    from fakes import make_relay

    turn_on(proj, "relay")
    srv = make_relay()
    yield srv
    srv.stop()


@pytest.fixture(autouse=True)
def _start_guard_off(request, monkeypatch):
    """Tests keep ORCH_HOME under pytest's temp folder, which the start-folder guard
    (adapters.check_start_folder) refuses for every agent. It is off here; tests of the guard itself
    ask for the real one with @pytest.mark.real_start_guard."""
    if request.node.get_closest_marker("real_start_guard"):
        return
    monkeypatch.setattr("orch.adapters.check_start_folder", lambda *a, **k: None)


REAL_PROOF_MODULES = ("test_human_proof", "test_humanproof", "test_verdict_mac")


def ensure_signing(root):
    """TEST HELPER: the workspace's local id and human key exist (a real proof needs both anyway)."""
    from orch import humanproof
    from orch.errors import Refused

    try:
        addons.workspace_id(root, create=True)
        humanproof.human_key(root, create=True)
    except Refused:  # a folder a test install may not use (not under ~/.orch-test): nothing can be signed there
        pass


def sign_done(root, tid, by="human:tester"):
    """TEST HELPER: a ticket becomes Done the proven way (a person's verdict, signed and recorded in the
    ledger). Fixtures never write "done" into a ticket file or call _write with it: that is Review."""
    from orch import tickets

    ensure_signing(root)
    return tickets.set_status(root, tid, "done", by, proven=True)


@pytest.fixture(autouse=True)
def _legacy_trust(request, monkeypatch):
    """TEST-ONLY (1.0a-2): older CLI tests act as `--by human:` without a proof. For them (a Python-level
    patch, no env var, no config key; production has no such path) the human gate trusts --by as before, and
    the pending read-back is the old by/via allowlist. Modules that test the real proof opt out by name."""
    if request.module.__name__.split(".")[-1].startswith(REAL_PROOF_MODULES):
        return
    from orch import humanproof, tickets

    def legacy(root, args, op, target, **kw):
        if tickets.agent_tool():
            return "agent:" + str(tickets.agent_tool())
        who = tickets.current_actor(getattr(args, "by", None))
        if who.startswith("human:"):
            ensure_signing(root)  # a person's Done is signed: the key and the local id exist, as after a real proof
        return who

    monkeypatch.setattr(humanproof, "person_by", legacy)
    monkeypatch.setattr(humanproof, "ENFORCE_PENDING_MAC", False)


_TMUX = re.compile(r"tmux -L (orch-[0-9a-f]+) new-session .* -c (\S+)")


def stray_tmux(under: str) -> list[str]:
    """Socket names of orch tmux servers whose working folder is `under` or below (reads `ps` only)."""
    out = subprocess.run(["/bin/ps", "-axo", "command="], check=False, capture_output=True, text=True).stdout
    return sorted(
        {
            m.group(1)
            for line in out.splitlines()
            if (m := _TMUX.search(line)) and m.group(2).startswith(under)
        }
    )


@pytest.fixture(autouse=True)
def _copies_unlocked(request, monkeypatch):
    """Separate copies are locked Off in the product for this release (config.COPIES_LOCKED).
    The feature's own tests keep running with the lock lifted; tests marked `copies_locked` check the lock."""
    from orch import config

    if not request.node.get_closest_marker("copies_locked"):
        monkeypatch.setattr(config, "COPIES_LOCKED", False)
        monkeypatch.setattr(config, "DEFAULT_COPIES", "together")  # the feature's own default when unlocked

import contextlib
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
_TRACE_LOG = addons._trace_log_path()  # the true fallback trace file (temp folder), before any test fakes it
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
    """{path: (size, sha256, mtime_ns)} of the watched orch homes (read only); and the fallback trace lines
    (from the temp trace file: orch never writes the trace into the real home). A path that can not be read
    maps to None."""
    files, trace = {}, []
    for base in _guard_bases():
        _snapshot_one(base, files)
    try:
        if _TRACE_LOG.is_file() and not _TRACE_LOG.is_symlink():
            trace = _TRACE_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        pass
    return files, trace


def _snapshot_one(base: Path, files: dict) -> None:
    if base.exists():
        for p in (base, *base.rglob("*")):
            try:
                if p.is_dir() and not p.is_symlink():
                    files[str(p)] = "dir"  # a folder's mtime moves with its contents, which are checked
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
def _no_tool_version_probe(monkeypatch):
    """The deny-rule version check (adapters.deny_version_check) probes the tool; tests that only look at
    an argv must not depend on a tool being installed. tests/test_deny_rules.py tests the real check."""
    from orch import adapters

    monkeypatch.setattr(adapters, "_deny_version_ok", lambda a, b=None: None)


@pytest.fixture(autouse=True)
def _no_bundled_catalogue(request, monkeypatch):
    """The bundled manifests of the shipped add-ons (shipped_addons.json) would list six not-installed
    add-ons in every `addon list` of a test without a source folder. Off by default; the catalogue tests
    (marked real_bundle) use the real bundle."""
    if request.node.get_closest_marker("real_bundle"):
        return
    monkeypatch.setattr(addons, "bundled_manifests", lambda: {})


@pytest.fixture(autouse=True)
def _strict_orch_home(monkeypatch, tmp_path_factory):
    """Every test: a faked real home with its own ORCH_HOME (a test that never asked for `proj` used to write
    the real ~/.orch-tool/addons.json: ORCH_HOME unset = real folder); untrusted ORCH_HOME = error."""
    fake = tmp_path_factory.mktemp("realhome")
    monkeypatch.setattr(addons, "real_home", lambda: fake)
    monkeypatch.setenv("ORCH_HOME", str(fake / "toolhome"))
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    # a test that turns the fallback trace on writes its own file, never the shared one in the temp folder
    trace = tmp_path_factory.mktemp("trace") / "orch-fallback-trace.log"
    monkeypatch.setattr(addons, "_trace_log_path", lambda: trace)
    monkeypatch.delenv("ORCH_TRACE_FALLBACKS", raising=False)  # the opt-in of a dev shell: tests turn it on
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


REAL_HOME_MODULES = (
    "test_secret_store",
    "test_install_kind",
    "test_winacl",
    "test_home",
)  # they test the home pairing itself


def ensure_keys(root):
    """TEST HELPER: the workspace's local id and key folder exist."""
    from orch import home as orch_home
    from orch.errors import Refused

    try:
        addons.workspace_id(root, create=True)
        orch_home.key_dir(root, create=True)
    except Refused:  # a folder a test install may not use (not under ~/.orch-test)
        pass


def key_file(root, create=True):
    """TEST HELPER: a 32-byte secret file `test.key` in the workspace key folder (rights 0600), made on
    first use. A loose or wrong-type file is never read: the protection resets and a new file is written."""
    import secrets

    from orch import home as orch_home
    from orch.errors import Refused

    d = orch_home.key_dir(root, create=create)
    f = d / "test.key"
    with orch_home._key_lock(d) if create else contextlib.nullcontext():
        try:
            try:
                raw = orch_home._read_guarded(f)
            except orch_home.LooseFile as e:
                orch_home.reset_protection(root, str(e))
                orch_home._write_private(f, secrets.token_hex(32) + "\n")
                raw = orch_home._read_guarded(f)
        except FileNotFoundError:
            if not create:
                raise Refused("There is no key here yet.") from None
            orch_home._write_private(f, secrets.token_hex(32) + "\n")
            raw = orch_home._read_guarded(f)
    return bytes.fromhex(raw.decode().strip())


def sign_done(root, tid, by="human:tester"):
    """TEST HELPER: a ticket becomes Done through a person's own Done (a plain status change)."""
    from orch import tickets

    return tickets.set_status(root, tid, "done", by)


@pytest.fixture(autouse=True)
def _legacy_trust(request, monkeypatch):
    """TEST-ONLY: these tests keep the workspace in pytest's temp folder, which the real pairing refuses (a
    test workspace must live under ~/.orch-test). Their orch home is the ORCH_HOME the fixture set. The
    pairing check itself is tested by test_home.py."""
    from orch import home as orch_home
    from orch.errors import Refused

    def test_home(root):
        home = Path(os.environ["ORCH_HOME"]) if os.environ.get("ORCH_HOME") else None
        if home is None:
            raise Refused("no test home")
        home.mkdir(parents=True, exist_ok=True)
        os.chmod(home, 0o700)
        return home

    if not request.module.__name__.split(".")[-1].startswith(REAL_HOME_MODULES):
        monkeypatch.setattr(orch_home, "guarded_home", test_home)


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


def seed_profiles(root, profiles):
    """Test setup only, like `profile set`: the kind from the real file; "any command" for others."""
    import os

    from orch import keystore, secretrun

    for p in profiles.values():
        if p.get("run") and "kind" not in p and os.path.isabs(p["run"][0]):
            p["kind"] = secretrun.program_kind(os.path.realpath(p["run"][0]))
            if p["kind"] == "other" or p.get("real_home"):
                p["any_command"] = True
    keystore.write_profiles(root, profiles)


# ---------------------------------------------------------------------------------------------- record MAC

_RECORD_MODULES = re.compile(
    r"tests\.test_(record|cli_record|cli_job|collect_|insights_settings|cli_secret|run_wrap|run_live|phone_|"
    r"run_record|jobs)|test_(record|cli_record|cli_job|collect_|insights_settings|cli_secret|run_wrap|"
    r"run_live|phone_|run_record|jobs)"
)


@pytest.fixture(autouse=True)
def _record_keys(request, monkeypatch, tmp_path_factory, _legacy_trust):
    """The record test modules write in plain tmp folders that are no guarded workspace, so for them the
    guarded home (other stores they touch, e.g. the key store) falls back to a test folder. The record itself
    needs no key. This is this test package's fixture only: no product code has a switch for it."""
    if not _RECORD_MODULES.search(request.module.__name__):
        yield
        return
    from orch import home as orch_home

    orig_home = orch_home.guarded_home
    fallback = tmp_path_factory.mktemp("recordhome")

    def home(root):
        try:
            return orig_home(root)
        except orch_home.HomeRefused:
            return fallback

    # the shared monkeypatch, set up after `_legacy_trust` (so undone before it): every patch of
    # orch_home.guarded_home is undone in the reverse order, none leaks into the next test (test_winacl)
    monkeypatch.setattr(orch_home, "guarded_home", home)
    yield


def seal_lines(root, run, events, *, start=1, link=None):
    """Raw bytes of run lines for `events` (for tests that write run files by hand): seq `start`.. in order,
    one compact JSON line each. `root` and `link` are kept for the callers' sake and unused."""
    out = b""
    for n, ev in enumerate(events, start):
        out += json.dumps(dict(ev, seq=n), separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
    return out


def seal_append(root, run, event):
    """Append ONE line to the run file by hand: the next seq after the file's last line."""
    from orch import record

    path = record.record_dir(root) / "runs" / f"{run}.jsonl"
    raw = path.read_bytes() if path.exists() else b""
    last = [x for x in raw.splitlines() if x][-1:]
    seq = json.loads(last[0])["seq"] + 1 if last else 1
    with path.open("ab") as f:
        f.write(seal_lines(root, run, [event], start=seq))


@pytest.fixture(autouse=True)
def _no_update_info_network(monkeypatch):
    """Update text asks the install source for release numbers and changes: never the network in tests."""
    from orch import updateinfo

    monkeypatch.setattr(updateinfo, "_fetch_messages", lambda *a, **k: None)

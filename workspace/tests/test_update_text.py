"""Update text across the install/reexec boundary, without installing or starting anything."""

import json
import os

import pytest
from test_addons import run, uv_calls  # noqa: F401
from test_addons_upgrade import _write_registry, github  # noqa: F401

from orch import addons, services

A40, B40 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


@pytest.fixture
def source(proj, github, uv_calls, monkeypatch):  # noqa: F811
    state = {"orch": "0.9.3", "addon": "0.3.1", "sha": A40, "title": None}
    _write_registry([{"name": "dashboard", "source": "built-in", "version": "0.3.1"}])
    (addons.home() / "installed.json").write_text(json.dumps({"sha": state["sha"]}))
    monkeypatch.setattr(
        addons, "_install_origin", lambda: {"repo": "https://github.com/o/orch", "ref": "main"}
    )
    monkeypatch.setattr(addons, "_orch_version", lambda: state["orch"])
    monkeypatch.setattr(addons, "_source_sha", lambda: state["sha"])
    monkeypatch.setattr(addons, "_release_title", lambda: state["title"])
    monkeypatch.setattr(addons, "discover", lambda: {"dashboard": {"version": state["addon"]}})
    monkeypatch.setattr(services, "running", lambda: [])

    def install(args):
        uv_calls.append(args)
        snapshot = json.loads((addons.home() / "update-before.json").read_text())
        assert {k: snapshot[k] for k in ("orch", "addons", "sha")} == {
            "orch": "0.9.3",
            "addons": {"dashboard": "0.3.1"},
            "sha": state["sha"],
        }
        state.update(state.get("next", {}))

    monkeypatch.setattr(addons, "run_uv", install)
    state["next"] = {"orch": "0.9.4", "addon": "0.3.2", "sha": B40}
    return state


def test_versions_and_sha(proj, run, source):  # noqa: F811
    code, out, err = run("update")
    assert code == 0, err
    assert out.splitlines() == [
        "Updating orch 0.9.3 → 0.9.4 (main aaaaaaaa → bbbbbbbb)",
        "Updating dashboard 0.3.1 → 0.3.2",
    ]
    assert not (addons.home() / "update-before.json").exists()
    assert json.loads((addons.home() / "installed.json").read_text()) == {"sha": B40}


def test_release_title(proj, run, source):  # noqa: F811
    source["title"] = "Fixes the sign button"
    code, out, err = run("update")
    assert code == 0, err
    assert out.splitlines()[-1] == "Fixes the sign button"
    assert out.count("Fixes the sign button") == 1


def test_unchanged_with_nothing_running_prints_only_up_to_date(proj, run, source, monkeypatch):  # noqa: F811
    source["next"] = {}
    monkeypatch.setattr(services, "running", lambda: [])
    code, out, err = run("update")
    assert code == 0, err
    assert out == "orch is up to date.\n"


def test_unchanged_versions_still_restart_what_runs(proj, run, source, monkeypatch):  # noqa: F811
    """A develop install keeps the version number but replaces the code: running services restart anyway."""
    source["next"] = {}
    called = []
    monkeypatch.setattr(
        addons, "_restart_updated", lambda root=None: called.append(1) or ["Restarted: dashboard (x)"]
    )
    code, out, err = run("update")
    assert code == 0, err
    assert out == "orch is up to date.\nRestarted: dashboard (x)\n" and called == [1]


class Fleet:
    """Two workspaces with running services, recorded in ORCH_HOME's running state; start/stop are fakes."""

    def __init__(self, tmp_path, monkeypatch, failure=None):
        self.calls, self.failure = [], failure
        self.ws = []
        for n in ("Pilatus", "Rigi"):
            w = tmp_path / n
            (w / ".orch").mkdir(parents=True)
            self.ws.append(w.resolve())
        self.pids = {
            (str(w), a): 100 + i * 10 + j
            for i, w in enumerate(self.ws)
            for j, a in enumerate(("dashboard", "focus"))
        }
        monkeypatch.setattr(services, "pid_alive", lambda pid: pid != 999)
        monkeypatch.setattr(services, "running", self.running)
        monkeypatch.setattr(addons, "_same_user", lambda pid: True)
        self.registered = [{"workspace": str(w), "name": "dashboard"} for w in self.ws]  # consent records
        monkeypatch.setattr(addons, "_consents", lambda: self.registered)
        self.forged = set()  # (workspace, addon): live pid that is NOT the add-on's server
        monkeypatch.setattr(services, "_services", lambda root: {"dashboard": {}, "focus": {}})
        monkeypatch.setattr(services, "_call", self.call)
        monkeypatch.setattr(services, "stop", self.stop)
        monkeypatch.setattr(services, "start", self.start)

    def call(self, root, name, m, sub, launch=None):
        assert sub == "status"  # the proof of life comes from the add-on itself
        if (str(root), name) in self.forged:
            return {"running": False}
        return {"running": True, "pid": self.pids[(str(root), name)]}

    def running(self):
        rows = [{"workspace": w, "addon": a, "pid": p} for (w, a), p in self.pids.items()]
        return [*rows, {"workspace": str(self.ws[0]), "addon": "dead", "pid": 999}]

    def stop(self, root, only=None):
        self.calls.append(("stop", root.name, set(only)))
        if self.failure == "stop" and root.name == "Pilatus":
            raise RuntimeError("stop failed")
        return [
            {
                "addon": a,
                "stopped": not (self.failure == "stoprow" and a == "focus"),
                **({"error": "busy"} if self.failure == "stoprow" and a == "focus" else {}),
            }
            for a in sorted(only)
        ]

    def start(self, root, only=None, envs=None):
        self.envs = envs
        self.calls.append(("start", root.name, set(only)))
        if self.failure == "start":
            raise RuntimeError("start failed")
        rows = []
        for a in sorted(only):
            up = not (self.failure == "row" and a == "focus")
            if up:
                self.pids[(str(root), a)] += 1000  # a NEW pid
            rows.append({"addon": a, "running": up})
        return rows


def test_restarts_every_workspace_in_the_running_state(proj, tmp_path, monkeypatch):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)  # the caller is in no workspace at all
    lines = addons._restart_updated()
    assert lines == ["Restarted: dashboard (Pilatus), focus (Pilatus), dashboard (Rigi), focus (Rigi)"]
    both = {"dashboard", "focus"}  # the 'dead' pid is not restarted
    assert f.calls == [
        ("stop", "Pilatus", both),
        ("start", "Pilatus", both),
        ("stop", "Rigi", both),
        ("start", "Rigi", both),
    ]
    assert all(p >= 1000 for p in f.pids.values())  # every service has a new pid


@pytest.mark.parametrize("failure", ["row", "stop", "stoprow", "start"])
def test_restart_failures_are_named_per_service(proj, tmp_path, monkeypatch, failure):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch, failure)
    lines = addons._restart_updated()
    text = "\n".join(lines)
    if failure == "row":  # focus never comes up, one retry
        assert "Restarted: dashboard (Pilatus), dashboard (Rigi)" in text
        assert "focus (Pilatus) stopped, start it with: orch start" in text
        assert ("start", "Pilatus", {"focus"}) in f.calls
    elif failure == "stop":  # Pilatus stop raises, Rigi is still restarted
        assert "Restart dashboard (Pilatus) to use the new version (stop failed: stop failed)" in text
        assert "Restarted: dashboard (Rigi), focus (Rigi)" in text
    elif failure == "stoprow":
        assert "Restart focus (Pilatus) to use the new version (stop failed: busy)" in text
        assert "focus (Pilatus) stopped" not in text
        assert ("start", "Pilatus", {"dashboard"}) in f.calls  # focus did not stop: not started again
    else:
        assert "dashboard (Pilatus) stopped, start it with: orch start (start failed)" in text
        assert "Restarted" not in text


def test_restart_runs_under_the_services_lock(proj, tmp_path, monkeypatch):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch)
    seen = []
    real = services.locked

    import contextlib

    @contextlib.contextmanager
    def locked(*a, **k):
        seen.append("in")
        with real(*a, **k):
            yield
        seen.append("out")

    monkeypatch.setattr(services, "locked", locked)
    orig = f.stop
    monkeypatch.setattr(services, "stop", lambda r, only=None: seen.append("stop") or orig(r, only))
    addons._restart_updated()
    assert seen[0] == "in" and seen[-1] == "out" and "stop" in seen


def test_plain_project_only(proj, run, source):  # noqa: F811
    code, out, err = run("update", "--project-only")
    assert code == 0, err
    assert out == "Refreshed: nothing\n"


@pytest.mark.parametrize("args", [(), ("--project-only",)])
def test_json(proj, run, source, args):  # noqa: F811
    code, out, err = run("update", *args, "--json")
    assert code == 0, err
    assert json.loads(out) == {"ok": True, "refreshed": []}


def test_sha_only(proj, run, source):  # noqa: F811
    source["next"] = {"sha": B40}
    code, out, err = run("update")
    assert code == 0, err
    assert out == "Updating orch 0.9.3 (main aaaaaaaa → bbbbbbbb)\n"


def test_service_filter_preserves_other_records(proj, monkeypatch):
    (proj / ".orch").mkdir()
    entries = [{"workspace": str(proj.resolve()), "addon": n, "pid": 123} for n in ("dashboard", "focus")]
    monkeypatch.setattr(services, "running", lambda: entries)
    monkeypatch.setattr(
        services, "_services", lambda root: {n: {} for n in ("dashboard", "focus", "automation")}
    )
    monkeypatch.setattr(services, "workspace_rows", lambda root: [])
    calls, saved = [], []
    monkeypatch.setattr(services, "_save", lambda rows: saved.append(rows))
    monkeypatch.setattr(
        services, "_call", lambda root, name, m, sub, launch=None: calls.append((name, sub)) or {}
    )
    services.stop(proj, only={"dashboard"})
    services.start(proj, only={"dashboard"})
    assert calls == [("dashboard", "stop"), ("dashboard", "start")]
    assert saved == [[entries[1]], [entries[1]]]


@pytest.mark.parametrize(
    "old_sha,new_sha,suffix",
    [
        (None, B40, " (main → bbbbbbbb)"),
        (A40, None, ""),
    ],
)
def test_missing_sha(proj, run, source, old_sha, new_sha, suffix):  # noqa: F811
    source["sha"] = old_sha
    source["next"]["sha"] = new_sha
    (addons.home() / "installed.json").write_text(json.dumps({"sha": old_sha}))
    code, out, err = run("update")
    assert code == 0, err
    assert out.splitlines()[0] == "Updating orch 0.9.3 → 0.9.4" + suffix


@pytest.mark.parametrize(
    "release,expected",
    [
        ({"name": "Fixes the sign button\nMore details"}, "Fixes the sign button"),
        ({"name": "", "body": "First line\nSecond line"}, "First line"),
        ({"name": "x" * 120 + "\x00"}, "x" * 100),
        ({}, None),
    ],
)
def test_release_metadata(github, monkeypatch, release, expected):  # noqa: F811
    import io
    import urllib.request

    calls = []

    def urlopen(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(json.dumps(release).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert addons._release_title() == expected
    assert calls == [("https://api.github.com/repos/o/orch/releases/latest", 5)]


def _snap(ws, **kw):
    import time

    d = {
        "nonce": "n1",
        "root": str(ws.resolve()),
        "time": time.time(),
        "orch": "0.9.3",
        "addons": {"dashboard": "0.3.1"},
        "sha": None,
    }
    d.update(kw)
    (addons.home() / "update-before.json").write_text(json.dumps(d) if d else "")
    return d


@pytest.mark.parametrize("junk", ["{not json", "[]", '{"orch": "1"}', '{"nonce": "n1", "orch": 3}'])
def test_corrupt_snapshot_never_breaks_project_step(proj, run, source, junk):  # noqa: F811
    (addons.home() / "update-before.json").write_text(junk)
    code, out, err = run("update", "--project-only", "--update-nonce", "n1")
    assert code == 0, err
    assert out == "Refreshed: nothing\n"
    assert not (addons.home() / "update-before.json").exists()


def test_stale_or_foreign_snapshot_is_ignored(proj, run, source):  # noqa: F811
    _snap(proj, time=1.0)  # far too old: deleted
    assert run("update", "--project-only", "--update-nonce", "n1")[1] == "Refreshed: nothing\n"
    assert not (addons.home() / "update-before.json").exists()
    _snap(proj)  # no nonce / wrong nonce / other workspace: left alone, nothing printed about an update
    assert run("update", "--project-only")[1] == "Refreshed: nothing\n"
    assert run("update", "--project-only", "--update-nonce", "zz")[1] == "Refreshed: nothing\n"
    assert (addons.home() / "update-before.json").exists()
    _snap(proj, **{"root": str(proj / "other")})
    assert run("update", "--project-only", "--update-nonce", "n1")[1] == "Refreshed: nothing\n"


def test_matching_snapshot_is_consumed(proj, run, source):  # noqa: F811
    _snap(proj)
    code, out, err = run("update", "--project-only", "--update-nonce", "n1")
    assert code == 0, err
    assert out.startswith("Updating orch 0.9.3")
    assert not (addons.home() / "update-before.json").exists()


@pytest.mark.parametrize(
    "bad", ["\x1b[2J" + "a" * 36, "A" * 40, "g" * 40, "a" * 39, "a" * 41, "a" * 40 + "\n\x1b"]
)
def test_only_full_hex_shas(bad):
    assert addons._sha_or_none(bad) is None
    assert addons._sha_or_none("0123456789abcdef" * 2 + "01234567") == "0123456789abcdef" * 2 + "01234567"


def test_sha_only_change_shows_and_restarts(proj, run, source, monkeypatch):  # noqa: F811
    source["next"] = {"sha": B40}  # same versions, sha moved
    monkeypatch.setattr(addons, "_restart_updated", lambda root=None: [])
    code, out, err = run("update")
    assert code == 0, err
    assert out.startswith("Updating orch 0.9.3 (main")


def test_title_strips_c1_and_bidi(github, monkeypatch):  # noqa: F811
    import io
    import urllib.request

    name = "Fix\x9b2J \u202eevil\u2066 ok"
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda url, timeout: io.BytesIO(json.dumps({"name": name}).encode())
    )
    assert addons._release_title() == "Fix2J evil ok"


def test_helper_may_not_update(proj, run, monkeypatch):  # noqa: F811
    from test_chat import _helper

    _helper(proj, monkeypatch)
    for argv in (("update", "--project-only"), ("update", "--project-only", "--update-nonce", "x")):
        assert run(*argv)[0] == 2, argv


def test_non_utf8_or_nonfinite_snapshot_is_deleted(proj, run, source):  # noqa: F811
    path = addons.home() / "update-before.json"
    path.write_bytes(b"\xff\xfe\x00bad")
    assert run("update", "--project-only", "--update-nonce", "n1")[1] == "Refreshed: nothing\n"
    assert not path.exists()
    _snap(proj)
    path.write_text(path.read_text().replace(path.read_text().split('"time": ')[1].split(",")[0], "NaN"))
    assert run("update", "--project-only", "--update-nonce", "n1")[1] == "Refreshed: nothing\n"
    assert not path.exists()


def test_atomic_write_cleans_tmp_on_failure(tmp_path, monkeypatch):
    import os

    def boom(a, b):
        raise OSError("x")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        addons._write_atomic(tmp_path / "f.json", "{}")
    assert list(tmp_path.iterdir()) == []


def test_start_and_stop_never_interleave(proj, monkeypatch):
    """Two orch processes (here: threads) used to read running.json, work for seconds, then write it back:
    the later write dropped or resurrected the other's records. One lock now serialises them."""
    import threading
    import time

    (proj / ".orch").mkdir(exist_ok=True)
    order = []
    monkeypatch.setattr(services, "_services", lambda root: {"dashboard": {}})
    monkeypatch.setattr(services, "workspace_rows", lambda root: [])

    def call(root, name, m, sub, launch=None):
        order.append(f"{sub}-begin")
        time.sleep(0.4)
        order.append(f"{sub}-end")
        return {"running": True, "pid": 4242} if sub == "start" else {"stopped": True}

    monkeypatch.setattr(services, "_call", call)
    monkeypatch.setattr(services, "pid_alive", lambda pid: True)
    t = threading.Thread(target=lambda: (time.sleep(0.15), services.stop(proj)))
    t.start()
    services.start(proj)
    t.join()
    assert order == ["start-begin", "start-end", "stop-begin", "stop-end"]
    assert services.running() == []  # the stop removed what the start recorded


def test_lock_times_out_with_a_clear_message(proj):
    import threading
    import time

    held, release = threading.Event(), threading.Event()

    def hold():
        with services.locked():
            held.set()
            release.wait(5)

    th = threading.Thread(target=hold)
    th.start()
    try:
        assert held.wait(5)
        t = time.monotonic()
        with pytest.raises(addons.Refused, match="still running"), services.locked(timeout=0.5):
            pass
        assert time.monotonic() - t < 3
    finally:
        release.set()
        th.join()


def test_restart_retries_once_and_restores_sighup(proj, tmp_path, monkeypatch):  # noqa: F811
    import signal

    f = Fleet(tmp_path, monkeypatch)
    f.pids = {k: v for k, v in f.pids.items() if k[1] == "dashboard" and k[0] == str(f.ws[0])}
    old_hup = signal.getsignal(signal.SIGHUP)
    first = f.start
    tries = []

    def start(root, only=None, envs=None):
        tries.append(1)
        if len(tries) == 1:  # first try: not up yet
            f.calls.append(("start", root.name, set(only)))
            return [{"addon": "dashboard", "running": False}]
        return first(root, only)

    monkeypatch.setattr(services, "start", start)
    try:
        lines = addons._restart_updated()
        assert signal.getsignal(signal.SIGHUP) == old_hup  # SIGHUP is only ignored during the restart
    finally:
        signal.signal(signal.SIGHUP, old_hup)
    assert len(tries) == 2
    assert lines == ["Restarted: dashboard (Pilatus)"]


def test_spawned_services_do_not_inherit_ignored_sighup():
    import signal
    import subprocess
    import sys

    old = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        r = subprocess.run(
            [sys.executable, "-c", "import signal;print(signal.getsignal(signal.SIGHUP) == signal.SIG_DFL)"],
            capture_output=True,
            text=True,
            preexec_fn=services._default_signals,
        )
    finally:
        signal.signal(signal.SIGHUP, old)
    assert r.stdout.strip() == "True"


def test_restart_ignores_caller_home_and_cwd(proj, tmp_path, monkeypatch):  # noqa: F811
    """Services started under another HOME (launchd) are found through ORCH_HOME's running state."""
    f = Fleet(tmp_path, monkeypatch)
    other = tmp_path / "other-home"
    other.mkdir()
    monkeypatch.setenv("HOME", str(other))
    monkeypatch.chdir(other)
    assert addons._restart_updated()[0].startswith("Restarted: dashboard (Pilatus)")
    assert len(f.calls) == 4


def test_dead_output_does_not_abort_the_restart(monkeypatch):
    class Dead:
        def flush(self):
            raise BrokenPipeError

        def write(self, s):
            raise BrokenPipeError

    monkeypatch.setattr("sys.stdout", Dead())
    addons._say("Updating orch")  # must not raise


def test_forged_entry_with_a_live_unrelated_pid_is_neither_signalled_nor_started(proj, tmp_path, monkeypatch):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch)
    f.forged = {(str(f.ws[0]), "dashboard"), (str(f.ws[0]), "focus")}  # all of Pilatus is forged
    lines = addons._restart_updated()
    assert not [c for c in f.calls if c[1] == "Pilatus"]  # no stop, no start for that workspace
    assert "dashboard (Pilatus) not restarted (can't verify); run orch stop, then orch start, in " + str(
        f.ws[0]
    ) in "\n".join(lines)
    assert "Restarted: dashboard (Rigi), focus (Rigi)" in lines  # the verified ones still restart


def test_one_unverified_service_is_skipped_but_the_verified_sibling_restarts(proj, tmp_path, monkeypatch):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch)
    f.forged = {(str(f.ws[0]), "focus")}
    lines = addons._restart_updated()
    assert ("stop", "Pilatus", {"dashboard"}) in f.calls and ("start", "Pilatus", {"dashboard"}) in f.calls
    assert any("focus (Pilatus) not restarted (can't verify)" in x for x in lines)


def test_other_users_process_is_not_verified(monkeypatch):
    monkeypatch.setattr(addons.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "0\n"})())
    assert addons._same_user(1234) is False


def test_unregistered_workspace_is_listed_but_never_touched(proj, tmp_path, monkeypatch):  # noqa: F811
    """A verified-looking service in a folder the person never set up (no consent record, not the cwd
    workspace) is not stopped and not started."""
    f = Fleet(tmp_path, monkeypatch)
    f.registered = [r for r in f.registered if r["workspace"] == str(f.ws[0])]  # Rigi is not registered
    lines = addons._restart_updated()
    assert not [c for c in f.calls if c[1] == "Rigi"]
    assert f"dashboard (Rigi) not restarted; run orch stop, then orch start, in {f.ws[1]}" in lines
    assert "Restarted: dashboard (Pilatus), focus (Pilatus)" in lines
    # the workspace `orch update` runs in counts as registered
    f.calls.clear()
    assert addons._restart_updated(f.ws[1])[0].startswith("Restarted: dashboard (Pilatus)")
    assert ("stop", "Rigi", {"dashboard", "focus"}) in f.calls


def test_malformed_running_entries_are_reported_not_fatal(proj, tmp_path, monkeypatch):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch)
    services.running_path().parent.mkdir(parents=True, exist_ok=True)
    services.running_path().write_text(json.dumps([{"workspace": 3}, "x", {"addon": "dashboard"}]))
    assert addons._malformed_running_entries() == 3
    lines = addons._restart_updated()  # real services.running() reads the file: nothing usable, no KeyError
    assert f.calls == [] or lines  # (Fleet replaces running(); the count still shows)
    assert "3 unreadable entries in the list of running services ignored" in lines


def test_json_update_reports_skipped_entries(proj, run, source, monkeypatch):  # noqa: F811
    monkeypatch.setattr(addons, "_restart_updated", lambda root=None: ["x (w) not restarted; run orch stop"])
    code, out, err = run("update", "--json")
    assert code == 0, err
    assert json.loads(out)["notes"][-1] == "x (w) not restarted; run orch stop"


# ---- restart environment: the caller's plus HOME (system) and ORCH_HOME; no record replayed ------


def _real_home():
    import pwd

    return pwd.getpwuid(os.getuid()).pw_dir


def _with_env(f, rec):
    """The Fleet's running state carries this recorded launch environment for every service."""
    orig = f.running
    f.running = lambda: [{**r, "env": rec} for r in orig()]
    services.running = f.running


def test_update_with_a_test_home_starts_services_with_the_system_home(proj, tmp_path, monkeypatch):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch)
    _with_env(f, {"HOME": _real_home(), "PATH": "/usr/bin:/bin"})
    other = tmp_path / "test-home"
    other.mkdir()
    monkeypatch.setenv("HOME", str(other))  # the updater runs with a test HOME
    lines = addons._restart_updated()
    assert f.envs["dashboard"]["HOME"] == _real_home()  # from pwd: the agent login is found again
    assert f.envs["dashboard"]["ORCH_HOME"] == str(addons.home())
    assert set(f.envs["dashboard"]) == {"HOME", "ORCH_HOME"}  # nothing else is overridden
    assert "Restarted: dashboard (Pilatus), focus (Pilatus), dashboard (Rigi), focus (Rigi)" in lines


def test_a_recorded_path_or_login_folder_is_never_used(proj, tmp_path, monkeypatch):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch)
    evil = tmp_path / "evil"
    evil.mkdir()
    rec = {
        "HOME": str(evil), "PATH": f"{evil}:/usr/bin", "CODEX_HOME": str(evil), "XDG_CONFIG_HOME": str(evil),
        "CLAUDE_CONFIG_DIR": str(evil), "PYTHONPATH": str(evil), "LD_PRELOAD": str(evil / "x.so"),
        "DYLD_INSERT_LIBRARIES": "x", "NODE_OPTIONS": "--require x", "GIT_SSH_COMMAND": "x",
        "ORCH_REPO": "evil", "ORCH_ROOT": str(evil),
    }  # fmt: skip
    _with_env(f, rec)
    monkeypatch.setenv("PATH", "/caller/path")
    addons._restart_updated()
    got = f.envs["dashboard"]
    assert got["HOME"] == _real_home() and set(got) == {"HOME", "ORCH_HOME"}  # none of the record
    merged = launchenv_apply(got)
    assert merged["PATH"] == "/caller/path"  # the caller's own, never the recorded one
    for k in rec:
        if k not in ("HOME", "PATH", "ORCH_ROOT"):
            assert merged.get(k) != rec[k]


def launchenv_apply(over):
    from orch import launchenv

    return launchenv.apply(dict(os.environ), over)


def test_a_different_recorded_home_or_path_is_reported_once(proj, tmp_path, monkeypatch):  # noqa: F811
    f = Fleet(tmp_path, monkeypatch)
    _with_env(f, {"HOME": "/some/other/home", "PATH": "/old/path"})
    monkeypatch.setenv("PATH", "/caller/path")
    lines = "\n".join(addons._restart_updated())
    assert "dashboard (Pilatus) started with a different HOME/PATH; restarted with this terminal's" in lines
    _with_env(f, {"HOME": _real_home(), "PATH": "/caller/path"})
    assert "different" not in "\n".join(addons._restart_updated())  # same HOME and PATH: no line


def test_without_a_system_home_the_callers_home_is_kept_and_said(proj, tmp_path, monkeypatch):  # noqa: F811
    from orch import launchenv

    f = Fleet(tmp_path, monkeypatch)
    monkeypatch.setattr(launchenv, "user_home", lambda: None)
    lines = addons._restart_updated()
    assert "HOME" not in f.envs["dashboard"] and f.envs["dashboard"]["ORCH_HOME"] == str(addons.home())
    assert any("could not read this user's home folder; kept this terminal's HOME" in x for x in lines)


@pytest.mark.parametrize(
    "name",
    ["LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "PYTHONPATH", "PYTHONSTARTUP", "NODE_OPTIONS",
     "GIT_SSH_COMMAND", "BASH_ENV", "ENV", "PERL5LIB", "RUBYOPT"],
)  # fmt: skip
def test_code_loading_variables_are_never_taken_from_a_record(name):
    from orch import launchenv

    assert launchenv.denied(name)
    assert launchenv.clean({name: "x", "HOME": "/h"}) == {"HOME": "/h"}


def test_call_adds_the_overrides_to_the_callers_environment(proj, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw["env"])
        return type("R", (), {"stdout": "{}", "stderr": "", "returncode": 0})()

    monkeypatch.setattr(services.subprocess, "run", fake_run)
    monkeypatch.setenv("HOME", "/caller/home")
    monkeypatch.setenv("PATH", "/caller/path")
    monkeypatch.setenv("CODEX_HOME", "/caller/codex")
    over = {"HOME": "/system/home", "ORCH_HOME": "/orch/home"}
    services._call(proj, "dashboard", {"run": "orch_dashboard"}, "start", over)
    assert seen["HOME"] == "/system/home" and seen["ORCH_HOME"] == "/orch/home"
    assert seen["PATH"] == "/caller/path" and seen["CODEX_HOME"] == "/caller/codex"  # the caller's, untouched
    assert seen["ORCH_ROOT"] == str(proj.resolve())


def test_start_records_home_and_path_for_information_only(proj, monkeypatch):
    (proj / ".orch").mkdir(exist_ok=True)
    monkeypatch.setattr(services, "_services", lambda root: {"dashboard": {}})
    monkeypatch.setattr(services, "workspace_rows", lambda root: [])
    monkeypatch.setattr(services, "pid_alive", lambda pid: True)
    monkeypatch.setattr(services, "_call", lambda *a, **k: {"running": True, "pid": 4242})
    monkeypatch.setenv("HOME", "/first/home")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    services.start(proj)
    rec = services.running()[0]["env"]
    assert rec == {"HOME": "/first/home", "PATH": os.environ["PATH"]}
    assert "sk-secret" not in services.running_path().read_text()
    monkeypatch.setenv("HOME", "/second/home")  # `orch start` again: the same pid keeps its first record
    services.start(proj)
    assert services.running()[0]["env"]["HOME"] == "/first/home"


def test_pwd_failure_note_is_said_once_per_workspace(proj, tmp_path, monkeypatch):  # noqa: F811
    from orch import launchenv

    Fleet(tmp_path, monkeypatch)
    monkeypatch.setattr(launchenv, "user_home", lambda: None)
    lines = addons._restart_updated()
    notes = [x for x in lines if "could not read this user's home folder" in x]
    assert sorted(x.split(":")[0] for x in notes) == ["Pilatus", "Rigi"]  # two workspaces, one line each


def test_a_running_services_old_record_is_cleaned_when_carried_forward(proj, monkeypatch):
    (proj / ".orch").mkdir(exist_ok=True)
    monkeypatch.setattr(services, "_services", lambda root: {"dashboard": {}})
    monkeypatch.setattr(services, "workspace_rows", lambda root: [])
    monkeypatch.setattr(services, "pid_alive", lambda pid: True)
    monkeypatch.setattr(services, "_call", lambda *a, **k: {"running": True, "pid": 4242})
    services.start(proj)
    entries = json.loads(services.running_path().read_text())
    entries[0]["env"] = {"HOME": "/h", "LD_PRELOAD": "/evil.so", "PATH": "x" * 5000, "OTHER": "y"}
    services.running_path().write_text(json.dumps(entries))
    services.start(proj)  # the same pid is still running: its record stays, cleaned and size-limited
    assert services.running()[0]["env"] == {"HOME": "/h"}

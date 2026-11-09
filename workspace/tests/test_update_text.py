"""Update text across the install/reexec boundary, without installing or starting anything."""

import json

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
    monkeypatch.setattr(addons, "_restart_updated", lambda: called.append(1) or ["Restarted: dashboard (x)"])
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
        monkeypatch.setattr(services, "stop", self.stop)
        monkeypatch.setattr(services, "start", self.start)

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

    def start(self, root, only=None):
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
    monkeypatch.setattr(services, "_call", lambda root, name, m, sub: calls.append((name, sub)) or {})
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
    monkeypatch.setattr(addons, "_restart_updated", lambda: [])
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

    def call(root, name, m, sub):
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

    def start(root, only=None):
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

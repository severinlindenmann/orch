"""Starting a broker judges only this start: an old log line or an old "ended" state never decides it."""

import json
import types

import pytest

from orch_browse import cli, paths

OLD_LOG = b"Executable doesn't exist at /old/chromium\nRun: playwright install\n"


class _Proc:
    def __init__(self, pid=4242, exits=False):
        self.pid, self.exits = pid, exits

    def poll(self):
        return 1 if self.exits else None


def _setup(ws, monkeypatch, proc, pings_until_ready=None, new_log=b""):
    run = paths.run_dir(ws, "t_abc123")
    (run / "broker.log").write_bytes(OLD_LOG)
    paths.write_state(run, {"pid": 1111, "state": "ended", "why": "the browser is not downloaded"})

    def popen(argv, stdout, **kw):
        stdout.write(new_log)
        stdout.flush()
        return proc

    calls = []

    def call(run_, cmd, args, timeout=0):
        calls.append(cmd)
        if pings_until_ready is not None and len(calls) >= pings_until_ready:
            return {"ok": True}
        return None

    clock = iter(range(0, 10_000, 10))
    monkeypatch.setattr(cli.subprocess, "Popen", popen)
    monkeypatch.setattr(cli.channel, "call", call)
    # only cli's own clock: patching the time module would reach other threads too
    monkeypatch.setattr(
        cli, "time", types.SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None)
    )
    return run, calls


def test_a_slow_start_after_an_old_failed_one_waits_for_the_new_broker(ws, monkeypatch):
    run, calls = _setup(ws, monkeypatch, _Proc(), pings_until_ready=5)
    cli._start_broker(ws, "t_abc123", run)
    assert len(calls) == 5


def test_still_starting_at_the_deadline_says_so_not_setup(ws, monkeypatch):
    run, _ = _setup(ws, monkeypatch, _Proc())
    with pytest.raises(cli.Refused, match="still starting"):
        cli._start_broker(ws, "t_abc123", run)


def test_the_setup_line_comes_only_from_this_starts_log(ws, monkeypatch):
    run, _ = _setup(ws, monkeypatch, _Proc(exits=True), new_log=b"Traceback: something else broke\n")
    with pytest.raises(cli.Refused, match="did not start"):
        cli._start_broker(ws, "t_abc123", run)
    run, _ = _setup(ws, monkeypatch, _Proc(exits=True), new_log=OLD_LOG)
    with pytest.raises(cli.Refused, match="not downloaded yet"):
        cli._start_broker(ws, "t_abc123", run)


def test_an_ended_state_written_after_this_start_stops_the_wait(ws, monkeypatch):
    proc = _Proc()
    run, calls = _setup(ws, monkeypatch, proc)
    real_call = cli.channel.call

    def call(run_, cmd, args, timeout=0):
        paths.write_state(run_, {"pid": 9999, "state": "ended", "why": "x"})
        return real_call(run_, cmd, args, timeout)

    monkeypatch.setattr(cli.channel, "call", call)
    with pytest.raises(cli.Refused, match="did not start"):
        cli._start_broker(ws, "t_abc123", run)
    assert len(calls) == 1
    assert json.loads((run / "state.json").read_text())["pid"] == 9999


def test_the_last_why_stays_while_starting(ws, monkeypatch):
    run, _ = _setup(ws, monkeypatch, _Proc())
    with pytest.raises(cli.Refused, match="still starting"):
        cli._start_broker(ws, "t_abc123", run)
    assert paths.read_state(run) == {"state": "starting", "why": "the browser is not downloaded"}

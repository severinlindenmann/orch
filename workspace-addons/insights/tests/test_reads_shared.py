"""ORCH-2288: Insights opened in 2.9-4 s at 10,000 tickets. Its reads started a new Python process each, six at
once when the page opened, and the counts were read up to four times side by side. Now a read goes through the
core's read worker (one long-lived process) and one counts answer serves every ask of the next few seconds."""

import subprocess
import threading
import time

from orch_insights import server


def test_a_read_goes_through_the_read_worker_with_the_cleaned_environment(ws, monkeypatch):
    seen = []

    class Reads:
        @staticmethod
        def call(root, argv, timeout, environ):
            seen.append((root, argv, timeout, environ))
            return 0, {"schema": "orch.counts/1"}

    import orch

    monkeypatch.setattr(orch, "reads", Reads, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "orch.reads", Reads)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no process")))
    assert server.read_json(ws, None, ["record", "counts", "--json"]) == {"schema": "orch.counts/1"}
    (root, argv, timeout, env), = seen
    assert (str(root), argv, timeout) == (str(ws), ["record", "counts", "--json"], 10)
    assert env["ORCH_ROOT"] == str(ws)


def test_a_refused_read_is_unknown_and_a_worker_miss_runs_the_command(ws, monkeypatch):
    answers = iter([(2, {"error": "no"}), None])

    class Reads:
        @staticmethod
        def call(root, argv, timeout, environ):
            return next(answers)

    import sys

    import orch

    monkeypatch.setattr(orch, "reads", Reads, raising=False)
    monkeypatch.setitem(sys.modules, "orch.reads", Reads)
    started = []

    def run(args, **kwargs):
        started.append(args)
        return subprocess.CompletedProcess(args, 0, '{"ok": true}', "")

    monkeypatch.setattr(subprocess, "run", run)
    assert server.read_json(ws, None, ["usage", "list", "--json"]) is None  # refused: no command after it
    assert started == []
    assert server.read_json(ws, None, ["usage", "list", "--json"]) == {"ok": True}  # the worker could not answer
    assert started and started[0][-3:] == ["usage", "list", "--json"]


def test_a_test_orch_keeps_its_own_process(ws, fake_orch, monkeypatch):
    monkeypatch.setattr(server, "_by_worker", lambda *a: (_ for _ in ()).throw(AssertionError("no worker")))
    assert server.read_counts(ws, fake_orch)["schema"] == "orch.counts/1"



def test_the_slow_tokens_read_keeps_its_own_process(ws, monkeypatch):
    # it takes seconds at 10,000 tickets: in the worker it held a place the overview waited for on a first open
    monkeypatch.setattr(server, "_by_worker", lambda *a: (_ for _ in ()).throw(AssertionError("no worker")))
    started = []

    def run(args, **kwargs):
        started.append(args)
        return subprocess.CompletedProcess(args, 0, '{"models": []}', "")

    monkeypatch.setattr(subprocess, "run", run)
    assert server.read_json(ws, None, ["tokens", "--days", "30", "--json"]) == {"models": []}
    assert started[0][-4:] == ["tokens", "--days", "30", "--json"]

def test_one_counts_read_answers_every_ask_at_once(ws, monkeypatch):
    calls = []

    def read_json(root, orch_bin, argv):
        calls.append(argv)
        time.sleep(0.2)
        return {"n": len(calls)}

    monkeypatch.setattr(server, "read_json", read_json)
    got = []
    threads = [threading.Thread(target=lambda: got.append(server.read_counts(ws))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == [["record", "counts", "--days", "30", "--json"]]
    assert got == [{"n": 1}] * 4
    assert server.read_counts(ws) == {"n": 1}  # still fresh
    monkeypatch.setattr(server, "COUNTS_FRESH", 0.0)
    assert server.read_counts(ws) == {"n": 2}  # older than that: read again


def test_a_failed_counts_read_is_not_kept_and_a_click_forgets_them(ws, monkeypatch):
    answers = iter([None, {"n": 1}, {"n": 2}])
    monkeypatch.setattr(server, "read_json", lambda *a: next(answers))
    assert server.read_counts(ws) is None
    assert server.read_counts(ws) == {"n": 1}
    server.forget_counts()
    assert server.read_counts(ws) == {"n": 2}


def test_a_read_on_its_way_during_a_click_is_not_kept(ws, monkeypatch):
    answers = iter([{"n": 1}, {"n": 2}])

    def read_json(*a):
        server.forget_counts()  # the click ends while this read is on its way
        return next(answers)

    monkeypatch.setattr(server, "read_json", read_json)
    assert server.read_counts(ws) == {"n": 1}
    monkeypatch.setattr(server, "read_json", lambda *a: next(answers))
    assert server.read_counts(ws) == {"n": 2}  # read again, not the answer from before the click

"""orch.reads: the in-process answers the dashboard builds its state from are the JSON the commands print
(ORCH-102: one process per read made a state build take seconds while helpers ran)."""

import json

import pytest

from orch import reads


@pytest.fixture
def three(proj, run):
    ids = []
    for title in ("First", "Second", "Third"):
        code, out, _ = run("ticket", "new", title, "--json", "--by", "agent:x")
        assert code == 0
        ids.append(json.loads(out)["id"])
    assert run("ticket", "status", ids[2], "done", "--by", "agent:x")[0] in (0, 2)
    code, out, err = run(
        "ask", ids[0], "Please look: New block", "--draft", "New block", "--then", "I build it.", "--json",
        "--by", "agent:x",
    )  # fmt: skip
    assert code == 0, out + err
    return proj, ids


@pytest.mark.parametrize(
    "argv",
    [
        ["ticket", "list", "--all", "--json"],
        ["ticket", "list", "--json"],
        ["review", "list", "--json"],
        ["review", "list", "--answered", "--json"],
    ],
)
def test_same_answer_as_the_command(three, run, argv):
    root, _ = three
    code, out, _ = run(*argv)
    assert code == 0
    assert reads.answer(root, argv) == json.loads(out)


_AGES = {"seconds", "idle_seconds", "age_seconds"}


def _split_ages(value, ages, path=""):
    """A copy of value without the "how many seconds ago" counters, which are collected into ages by path."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in _AGES and isinstance(item, (int, float)):
                ages[f"{path}/{key}"] = item
            else:
                out[key] = _split_ages(item, ages, f"{path}/{key}")
        return out
    if isinstance(value, list):
        return [_split_ages(item, ages, f"{path}/{i}") for i, item in enumerate(value)]
    return value


def test_run_status_same_answer_for_one_and_many(three, run):
    # The two reads happen a moment apart: a second boundary between them moves the age counters by one
    # (release 36 went red on last_activity.seconds 0 vs 1), so those may differ by a little.
    root, ids = three
    for argv in (["run", "status", ids[0], "--json"], ["run", "status", *ids, "--json"]):
        code, out, _ = run(*argv)
        assert code == 0
        got_ages, want_ages = {}, {}
        assert _split_ages(reads.answer(root, argv), got_ages) == _split_ages(json.loads(out), want_ages)
        assert got_ages.keys() == want_ages.keys()
        for key, want in want_ages.items():
            assert abs(got_ages[key] - want) <= 5, key


def test_ticket_show_same_answer(three, run):
    root, ids = three
    code, out, _ = run("ticket", "show", ids[0], "--json")
    assert code == 0
    assert reads.answer(root, ["ticket", "show", ids[0], "--json"]) == json.loads(out)


def test_a_missing_ticket_does_not_spoil_the_others(three):
    root, ids = three
    got = reads.answer(root, ["run", "status", ids[0], "t_nothere99", "--json"])["runs"]
    assert got[ids[0]]["ticket"] == ids[0] and "error" in got["t_nothere99"]


@pytest.mark.parametrize(
    "argv",
    [
        ["ticket", "new", "x", "--json"],  # a write is never answered here
        ["ticket", "list", "--all"],  # text, not JSON
        ["run", "status", "--json"],
        ["run", "status", "../etc", "--json"],
        ["addon", "list", "--json"],
    ],
)
def test_other_argv_is_not_here(three, argv):
    with pytest.raises(reads.NotHere):
        reads.answer(three[0], argv)


def test_the_answer_shares_nothing_with_the_core(three):
    root, _ = three
    a = reads.answer(root, ["ticket", "list", "--all", "--json"])
    a[0]["title"] = "changed"
    assert reads.answer(root, ["ticket", "list", "--all", "--json"])[0]["title"] != "changed"


# --- ORCH-634: every read of a long-running caller without a new process per read ---


def _env(root):
    """The worker is a real child: it gets the test's fake home (proj patches it only in this process)."""
    import os

    home = str(root.parent / f"{root.name}_home")
    return {**os.environ, "HOME": home, "USERPROFILE": home}


def test_needs_same_answer(three, run):
    root, _ = three
    code, out, _ = run("needs", "--json")
    assert code == 0
    assert reads.answer(root, ["needs", "--json"]) == json.loads(out)


def test_call_answers_here_then_through_the_worker(three, run):
    """A read orch.reads knows is answered here; any other read goes to the ONE read worker (no new process
    per read): the same JSON as the command, and a second read reuses the same worker."""
    from orch import readworker

    root, ids = three
    readworker.stop_all()
    started = readworker.STARTS["worker"]
    try:
        assert reads.call(root, ["ticket", "show", ids[0], "--json"])[0] == 0
        assert readworker.STARTS["worker"] == started  # answered here, no worker needed
        import subprocess
        import sys

        child = subprocess.run(  # the command as its own process: what the worker must answer
            [sys.executable, "-I", "-P", "-m", "orch", "addon", "list", "--json"],
            cwd=root, env={**_env(root), "ORCH_ROOT": str(root)}, capture_output=True, text=True,
        )  # fmt: skip
        code, out = child.returncode, child.stdout
        for _ in range(3):
            got = reads.call(root, ["addon", "list", "--json"], environ=_env(root))
            assert got == (code, json.loads(out))
        assert readworker.STARTS["worker"] == started + 1
        code, value = reads.call(root, ["ticket", "show", "t_nothere99", "--json"])
        assert code == 2 and value["error"]
    finally:
        readworker.stop_all()


def test_the_worker_keeps_its_pipes_from_the_command(three, subprocess_home):
    """A command that prints, writes to stderr or starts a child cannot break the worker's answers."""
    from orch import readworker

    root, _ = three
    try:
        env = _env(root)
        assert readworker.run(root, ["--version"], environ=env)[0] == 0
        assert readworker.run(root, ["no-such-command", "--json"], environ=env)[0] == 2
        code, out = readworker.run(root, ["needs", "--json"], environ=env)
        assert code == 0 and isinstance(json.loads(out), list)
    finally:
        readworker.stop_all()


def test_a_worker_that_does_not_answer_is_ended(three):
    from orch import readworker

    root, _ = three
    env = _env(root)
    try:
        assert readworker.run(root, ["--version"], environ=env) is not None
        w = readworker.workers()[0]
        w.proc.kill()
        w.proc.wait()
        started = readworker.STARTS["worker"]
        assert readworker.run(root, ["--version"], environ=env)[0] == 0  # a dead worker is replaced first
        assert readworker.STARTS["worker"] == started + 1
        slow = readworker.workers()[0]
        assert (
            readworker.run(root, ["needs", "--json"], timeout=0.0001, environ=env) is None
        )  # no answer in time
        assert slow.proc.poll() is not None  # that worker was ended
        assert readworker.run(root, ["--version"], environ=env)[0] == 0
    finally:
        readworker.stop_all()


def test_same_orch(tmp_path):
    import sys

    assert reads.same_orch("orch:self")
    assert not reads.same_orch(None) and not reads.same_orch(str(tmp_path / "missing"))
    mine = tmp_path / "orch"
    mine.write_text(f"#!{sys.executable}\nfrom orch_entry import main\n")
    other = tmp_path / "fake"
    other.write_text(f"#!{sys.executable}\nprint('fake orch')\n")
    elsewhere = tmp_path / "old"
    elsewhere.write_text("#!/usr/bin/python3-somewhere-else\nfrom orch_entry import main\n")
    assert reads.same_orch(str(mine)) is (sys.platform != "win32")
    assert not reads.same_orch(str(other)) and not reads.same_orch(str(elsewhere))


def test_the_worker_keeps_what_a_child_of_the_command_prints(tmp_path):
    """An add-on command runs as a child process of `orch`: what it prints reaches the answer too."""
    import subprocess
    import sys

    code = (
        "import json, os, subprocess, sys\n"
        "from orch import cli, readworker\n"
        "cli.main = lambda argv: subprocess.run([sys.executable, '-c', 'print(123)']).returncode\n"
        "print(json.dumps(readworker._answer({'argv': ['x'], 'root': os.getcwd()})), file=sys.stderr)\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert json.loads(r.stderr.strip().splitlines()[-1]) == {"code": 0, "out": "123\n"}

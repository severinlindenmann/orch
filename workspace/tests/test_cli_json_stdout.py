"""`--json` is for machines: stdout of every command that has it is JSON and nothing else.

Notices ("Skills updated; ...", hints) belong on stderr. The command list comes from the argparse parser, so a
new command with `--json` is covered without touching this file."""

import argparse
import json

import pytest
from fakes import WS
from test_relay_client import connect

from orch import cli, skillrender

# commands that run an agent, wait, read a terminal, or change the machine: not run here
SKIP = {
    "init", "update", "uninstall", "leave", "start", "stop", "pause", "resume", "wait", "review wait",
    "ticket wait", "run", "job run", "record hook", "work-check", "doctor", "secret exec", "secret env",
    "secret file", "secret scan", "relay mobile keeper", "relay start", "relay send", "relay download",
}  # fmt: skip


def _leaves(p, path=()):
    subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
    if subs:
        for name, sp in subs[0].choices.items():
            yield from _leaves(sp, (*path, name))
        return
    opts = [o for a in p._actions for o in a.option_strings]
    required = [a for a in p._actions if (not a.option_strings and a.nargs not in ("?", "*")) or a.required]
    if "--json" in opts and not required:
        yield path


def _commands():
    out = []
    for path in _leaves(cli.build_parser(True, None)):
        words = " ".join(path)
        if path[0] in SKIP or words in SKIP:
            continue
        out.append(path)
    return out


def _single_json(out):
    """True when `out` is empty or exactly one JSON document."""
    if not out.strip():
        return True
    try:
        json.loads(out)
        return True
    except ValueError:
        return False


@pytest.fixture
def busy(proj, run, rel, pub, monkeypatch):
    """A workspace with relay and publish on and connected, and a skill change waiting every time."""
    from conftest import turn_on  # noqa: F401

    connect(run, rel)
    run("publish", "connect", pub.url, "--workspace", WS, "--token", pub.token)
    monkeypatch.setattr(skillrender, "sync_github", lambda root: True)
    return proj


def test_commands_found():
    assert len(_commands()) > 40  # the walk itself works


def test_every_json_command_prints_json_only(busy, run):
    bad = []
    for path in _commands():
        try:
            code, out, err = run(*path, "--json")
        except SystemExit:  # needs an option the walk can not guess (a required group): not a JSON question
            continue
        if not _single_json(out):
            bad.append(f"{' '.join(path)} (exit {code}): {out[:80]!r}")
        if code == 2 and out.strip():  # a refusal under --json: one error document
            assert "error" in json.loads(out), path
    assert not bad, "\n".join(bad)


def test_inbox_json_with_a_skill_change(busy, run, rel):
    code, out, err = run("relay", "inbox", "--json")
    assert code == 0
    json.loads(out)  # nothing but the answer on stdout
    assert skillrender.MESSAGE not in out


def test_refresh_says_the_skill_change_on_stderr(busy, run, capsys):
    skillrender.refresh_skills(busy)
    cap = capsys.readouterr()
    assert cap.out == "" and skillrender.MESSAGE in cap.err


# The dashboard reads exactly these (`orch run status <id> --json` for every open ticket, the `run stop` and
# `run send` answers): the walk skips `run …` (it would start agents); here they run with a fake run record.
@pytest.mark.parametrize("live", [False, True], ids=["no-run", "run-record"])
def test_run_status_json_is_json_only(busy, run, new_ticket, live):
    import os

    from orch import runs

    tid = new_ticket()
    if live:
        runs.claim(busy, tid, "agent:scheduler", "claude", pid=os.getpid())
    code, out, err = run("run", "status", tid, "--json")
    assert code == 0, err
    data = json.loads(out)  # nothing but the answer on stdout, even with a skill change waiting
    assert data["ticket"] == tid and data["running"] is live
    assert skillrender.MESSAGE not in out


def test_run_send_and_stop_json_are_json_only(busy, run, new_ticket):
    tid = new_ticket()
    for args in (("run", "send", tid, "hello", "--json"), ("run", "stop", tid, "--json")):
        code, out, err = run(*args)
        assert _single_json(out), (args, out[:120])
        if code == 2 and out.strip():
            assert "error" in json.loads(out), args


def test_batched_run_status_json_is_json_only(busy, run, new_ticket):
    """The dashboard asks for all runs in one process: `orch run status <id> <id> … --json`."""
    import os

    from orch import runs

    a, b = new_ticket(), new_ticket()
    runs.claim(busy, a, "agent:scheduler", "claude", pid=os.getpid())
    code, out, err = run("run", "status", a, b, "--json")
    assert code == 0, err
    data = json.loads(out)
    assert data["runs"][a]["running"] is True and data["runs"][b]["running"] is False
    assert skillrender.MESSAGE not in out

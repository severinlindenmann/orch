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

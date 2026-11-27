"""ORCH-2313: relay send and inbox stay cheap in a git repository. Every private write asked git twice (and
before ORCH-1914 looked up the installed agent tools, with a `--version` process each). One send or inbox
writes the same few files several times, so git's answer for a file is reused while nothing that decides it
has changed. The counts here are processes, not seconds: they do not depend on how busy the computer is."""

import json
import subprocess

import pytest
from test_relay_client import PEER, connect, msg

from orch.errors import Refused


def _git(proj, *args):
    subprocess.run(["git", "-C", str(proj), *args], check=True, capture_output=True)


@pytest.fixture
def counted(proj, run, rel, monkeypatch):
    """A connected workspace inside a git repository; counts what a command starts."""
    from orch import adapters, safegit

    _git(proj, "init", "-q")
    ok = {"text": True, "files": True, "delegate": True, "start": True}
    rel.snapshot["workspaces"]["workspaces"] = [
        {"id": PEER, "name": "Reports", "online": True, "can_send": dict(ok), "accepts_from": dict(ok)}
    ]
    connect(run, rel)
    n = {"git": 0, "version": 0}
    real_git, real_version = safegit.run_bytes, adapters._version

    def git(args, *a, **k):
        n["git"] += 1
        return real_git(args, *a, **k)

    def version(*a, **k):
        n["version"] += 1
        return real_version(*a, **k)

    monkeypatch.setattr(safegit, "run_bytes", git)
    monkeypatch.setattr(adapters, "_version", version)
    return n


def test_relay_send_and_inbox_ask_git_once_per_file_and_never_an_agent_tool(proj, run, rel, counted):
    from orch import harness

    harness._PRIVATE_SEEN.clear()  # a new command starts with nothing kept
    assert run("relay", "send", PEER, "hello")[0] == 0
    # the outbox file, the sent log and the posted list: 2 git runs each (before: 10 and more)
    assert counted["git"] <= 6, counted
    assert counted["version"] == 0, "no `<agent tool> --version` on a relay send"
    for k in counted:
        counted[k] = 0
    harness._PRIVATE_SEEN.clear()
    assert run("relay", "inbox")[0] == 0  # nothing new: what every waiting agent runs again and again
    # the phone view file is written three times and the group file twice in one pull: git is asked once each
    assert counted["git"] <= 6, counted  # before: 12
    assert counted["version"] == 0, "no `<agent tool> --version` on a relay inbox"


def test_a_pull_with_a_new_message_asks_git_less_than_without_keeping(proj, run, rel, counted, monkeypatch):
    from orch import harness

    def pull(mid):
        for k in counted:
            counted[k] = 0
        harness._PRIVATE_SEEN.clear()
        rel.inbox.append(msg(mid, "text", {"text": "hi"}))
        assert run("relay", "inbox")[0] == 0
        return counted["git"]

    pull(
        "m_speed00000000001"
    )  # the first message of a workspace also makes its thread and the General ticket
    kept = pull("m_speed00000000002")
    monkeypatch.setattr(harness, "PRIVATE_KEEP", 0.0)
    asked_every_time = pull("m_speed00000000003")
    assert kept < asked_every_time, (kept, asked_every_time)
    print(f"git runs for one pull with a new message: {kept} (kept) / {asked_every_time} (asked every time)")


def test_the_posted_list_is_written_in_a_git_repository(proj, run, rel, counted):
    """It was not on orch's ignore list, so the write was refused without a word in every git repository."""
    from orch import relay

    sent = json.loads(run("relay", "send", PEER, "hello", "--json")[1])
    assert sent["id"] in relay.posted_ids(proj)


def test_a_kept_git_answer_is_dropped_when_the_file_gets_tracked_or_shown(proj, counted):
    """Fail closed as before: the answer is reused only while the index and the ignore files are unchanged."""
    from orch import harness, net

    p = net.secrets_dir(proj) / "speed.json"
    net.write_json(p, {"a": 1}, True)
    net.write_json(p, {"a": 2}, True)  # kept from here on
    before = counted["git"]
    net.write_json(p, {"a": 3}, True)
    assert counted["git"] == before, "an unchanged repository is not asked again"
    key = harness._private_key(proj, ".orch/secrets/speed.json")
    (proj / ".orch" / "secrets" / ".gitignore").write_text("# a rule file next to it\n")
    assert harness._private_key(proj, ".orch/secrets/speed.json") != key
    net.write_json(p, {"a": 4}, True)
    assert counted["git"] > before, "a new ignore file on the way: git is asked again"
    net.write_json(p, {"a": 5}, True)
    _git(proj, "add", "-f", ".orch/secrets/speed.json")  # now tracked: the index changed
    with pytest.raises(Refused):
        net.write_json(p, {"a": 7}, True)


def test_a_kept_git_answer_ends_after_a_moment(proj, counted, monkeypatch):
    from orch import harness, net

    p = net.secrets_dir(proj) / "speed.json"
    net.write_json(p, {"a": 1}, True)
    net.write_json(p, {"a": 2}, True)
    monkeypatch.setattr(harness, "PRIVATE_KEEP", 0.0)
    before = counted["git"]
    net.write_json(p, {"a": 3}, True)
    assert counted["git"] > before

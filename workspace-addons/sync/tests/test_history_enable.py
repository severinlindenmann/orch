"""Turning sync on switches core's one rule for person fields on (orch.history): what this machine wrote stays
the person's, what arrives by sync shows as "(synced, not verified here)" (contracts/history.md)."""

import json
import os
import shutil
import subprocess

from orch import history
from test_step import NOW, TICKET, configure, save, success, ticket
from test_two_machines import both, load, machines

from orch_sync import repo

__all__ = ["machines"]

LOCAL_LINE = {"at": NOW, "by": "human:lindenmann", "text": "Written before sync"}
PEER_LINE = {"at": NOW, "by": "human:lindenmann", "text": "Written on the other computer"}
SHOWN = "(synced, not verified here) "


def _peer_with_a_ticket(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    peer = tmp_path / "A"
    (peer / ".orch").mkdir(parents=True)
    configure(peer, bare)
    save(peer, "tickets/t_peer01.json", ticket() | {"id": "t_peer01", "history": [PEER_LINE]})
    success(peer)
    return bare


def test_enabling_adopts_this_machines_lines_before_the_first_fetch(tmp_path, monkeypatch):
    bare = _peer_with_a_ticket(tmp_path, monkeypatch)
    root = tmp_path / "C"
    (root / ".orch").mkdir(parents=True)
    save(root, value=ticket() | {"history": [LOCAL_LINE]})  # used without sync so far
    assert not history.sync_enabled(root)
    original, network = repo.git, []

    def git(r, *args, **kwargs):
        if r == root and args[0] in ("fetch", "ls-remote") and not network:
            network.append(args[0])
            # recorded and adopted BEFORE anything can arrive from the other computer
            assert history.sync_enabled(r) and history.enabled_recorded(r)
            assert history.lines(r, load(r)) == [LOCAL_LINE]
        return original(r, *args, **kwargs)

    monkeypatch.setattr(repo, "git", git)
    configure(root, bare)
    success(root)
    assert network
    assert history.lines(root, load(root)) == [LOCAL_LINE]
    peer_doc = json.loads((root / ".orch/tickets/t_peer01.json").read_text())
    shown = history.lines(root, peer_doc)
    assert shown[0]["by"] == history.SYNC_BY and shown[0]["text"].startswith(SHOWN)


def test_removing_the_sync_repository_never_makes_the_workspace_trust_every_line(machines):
    a, b, _ = both(machines)
    save(b, value=load(b) | {"history": [PEER_LINE]})
    success(b)
    success(a)
    assert history.lines(a, load(a))[0]["by"] == history.SYNC_BY
    shutil.rmtree(a / ".orch/.git")  # an agent removes the sync repository and its run records
    shutil.rmtree(a / ".orch/run/sync")
    history._ENABLED.clear()  # as in a fresh process
    assert history.sync_enabled(a)  # the record in the guarded orch home stays
    assert history.lines(a, load(a))[0]["by"] == history.SYNC_BY


def test_a_workspace_that_synced_before_adopts_nothing(machines):
    _, b, _ = both(machines)
    save(b, value=load(b) | {"history": [LOCAL_LINE]})  # possibly pulled earlier: nobody can tell
    for p in history._enabled_paths(b):  # a workspace from before the record existed
        p.unlink(missing_ok=True)
    history._ENABLED.clear()
    success(b)  # repo.ensure records it now ('ready'): no adoption
    assert history.enabled_recorded(b)
    assert history.lines(b, load(b))[0]["by"] == history.SYNC_BY


def test_a_missing_marker_still_records_before_refusing(root):
    (root / ".orch/.git").mkdir()  # a repository without its marker: ensure refuses (needs-adoption)
    try:
        repo.ensure(root)
    except repo.Refused:
        pass
    assert history.enabled_recorded(root)


def test_enabling_refuses_when_it_cannot_be_recorded(root, monkeypatch):
    from orch import humanproof
    from orch.errors import Refused

    from orch_sync import cli

    def refused(_root):
        raise Refused("no home")

    monkeypatch.setattr(humanproof, "guarded_home", refused)
    assert cli.main(["--dir", str(root), "set", "--mode", "local"]) == 2
    assert not (root / ".orch/.git").exists()


def test_own_lines_written_after_enabling_stay_the_persons(root):
    from orch import tickets

    configure(root)
    save(root)
    success(root)
    tickets.log(root, "t_abc123", "my words", "human:lindenmann")
    success(root)
    assert history.lines(root, load(root))[-1]["by"] == "human:lindenmann"
    assert os.path.exists(root / ".orch/run/own-lines/t_abc123.json")
    assert TICKET in {f"tickets/{p.name}" for p in (root / ".orch/tickets").iterdir()}

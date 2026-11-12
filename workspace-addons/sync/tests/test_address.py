"""settings.json is plain JSON any process can write: remote mode uses its address only when it matches the local1
record the person's signed set-remote / use-public choice wrote (cli.approve_address). Else no network call at all."""

import hashlib
import json
import subprocess

import pytest
from test_repo import recorded
from test_step import NOW, configure, run, save, set_remote, success

from orch_sync import act, cli, needs, repo, step

NETWORK = {"push", "fetch", "ls-remote", "clone"}


@pytest.fixture
def preview(monkeypatch):
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")


def bare(tmp_path, name="remote.git"):
    path = tmp_path / name
    subprocess.run(["git", "init", "--bare", str(path)], capture_output=True, check=True)
    return path


def has_state(path):
    return subprocess.run(["git", "--git-dir", str(path), "rev-parse", "--verify", "-q", "orch-state"],
                          check=False, capture_output=True).returncode == 0


def plant(root, **values):
    """What an agent can do: write settings.json directly."""
    p = root / ".orch/run/sync/settings.json"
    old = json.loads(p.read_text()) if p.exists() else {"kind": "private", "interval": 15}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(old | values))


def address_rows(root):
    return [r for r in needs.rows(root) if r["kind"] == "sync:address"]


def refused(root, monkeypatch, *remotes):
    """A sync step makes no network call, says why in plain words and shows a Needs row."""
    calls = recorded(monkeypatch, fake_network=False)
    state = run(root)
    assert state["last_error"] == cli.UNCONFIRMED == "Sync address not confirmed: choose it again in Settings"
    assert not [c for c, _ in calls if NETWORK & set(c)]
    assert not any(has_state(r) for r in remotes)
    assert json.loads((root / ".orch/run/sync/state.json").read_text())["last_error"] == cli.UNCONFIRMED
    rows = address_rows(root)
    assert len(rows) == 1 and rows[0]["text"] == cli.UNCONFIRMED and rows[0]["tone"] == "warn"
    assert act.status(root, cli.DEFAULTS | cli.read(root, "settings"))["last_error"] == cli.UNCONFIRMED


def test_planted_remote_without_a_record_makes_no_network_call(root, tmp_path, monkeypatch, preview):
    remote = bare(tmp_path)
    configure(root)  # local sync, no address chosen
    save(root)
    success(root)
    plant(root, mode="remote", remote=str(remote))
    assert not (root / ".orch" / cli.ADDRESS).exists()
    refused(root, monkeypatch, remote)


def test_a_record_for_another_address_is_refused(root, tmp_path, monkeypatch, preview):
    a, b = bare(tmp_path, "a.git"), bare(tmp_path, "b.git")
    assert set_remote(root, a) == 0  # the person chose A
    save(root)
    plant(root, remote=str(b))  # settings.json now says B
    refused(root, monkeypatch, a, b)


@pytest.mark.parametrize("tamper", ["mac", "no-mac", "other-hash", "extra-key", "not-json", "list"])
def test_a_tampered_record_is_refused(root, tmp_path, monkeypatch, preview, tamper):
    remote = bare(tmp_path)
    assert set_remote(root, remote) == 0
    save(root)
    p = root / ".orch" / cli.ADDRESS
    record = json.loads(p.read_text())
    assert set(record) == {"sha256", "mac"}
    if tamper == "mac":
        record["mac"] = ("A" if record["mac"][0] != "A" else "B") + record["mac"][1:]
    elif tamper == "no-mac":
        del record["mac"]
    elif tamper == "other-hash":
        record["sha256"] = "0" * 64
    elif tamper == "extra-key":
        record["remote"] = str(remote)
    p.write_text("{" if tamper == "not-json" else json.dumps([record] if tamper == "list" else record))
    refused(root, monkeypatch, remote)


def test_the_signed_choice_syncs(root, tmp_path, monkeypatch, preview):
    remote = bare(tmp_path)
    assert set_remote(root, remote) == 0
    record = json.loads((root / ".orch" / cli.ADDRESS).read_text())
    assert record["sha256"] == hashlib.sha256(str(remote).encode()).hexdigest()
    assert cli.address_confirmed(root, str(remote))
    save(root)
    success(root)
    assert has_state(remote)
    assert address_rows(root) == []
    # how often stays unsigned and keeps the confirmation
    assert cli.main(["--dir", str(root), "set", "--interval", "5"]) == 0
    success(root)
    assert address_rows(root) == []


def test_choosing_the_planted_address_again_is_signed_and_then_syncs(root, tmp_path, monkeypatch, preview):
    remote = bare(tmp_path)
    configure(root)
    save(root)
    plant(root, mode="remote", remote=str(remote))
    # the dashboard's same-address shortcut (only how often, unsigned) does not apply to an unconfirmed address
    target, review = act.proof_target(root, "set", str(remote), "15")
    assert target == cli.remote_target(str(remote)) and review
    assert set_remote(root, remote) == 0
    assert act.proof_target(root, "set", str(remote), "15") == (None, None)
    success(root)
    assert has_state(remote) and address_rows(root) == []


def test_local_and_off_need_no_record(root, preview):
    configure(root)
    save(root)
    assert success(root)["last_ok"] == NOW
    assert address_rows(root) == []
    assert cli.main(["--dir", str(root), "set", "--mode", "off"]) == 0
    assert run(root)["last_error"] is None and address_rows(root) == []


def test_a_history_pause_looks_at_a_planted_address_never(root, tmp_path, monkeypatch, preview):
    # the history pause's own fetch (does the remote still hold the commit?) asks first too
    a, b = bare(tmp_path, "a.git"), bare(tmp_path, "b.git")
    assert set_remote(root, a) == 0
    save(root)
    success(root)
    plant(root, remote=str(b))
    calls = recorded(monkeypatch, fake_network=False)
    assert step._remote_moved(root, {"remote_sha": "0" * 40}, True) is False
    assert not [c for c, _ in calls if NETWORK & set(c)]
    assert repo.git(root, "config", "remote.origin.url").stdout.decode().strip() == str(a)  # never pointed at B
    plant(root, remote=str(a))  # the confirmed address: it looks
    assert step._remote_moved(root, {"remote_sha": "0" * 40}, True) is True
    assert [c for c, _ in calls if NETWORK & set(c)]

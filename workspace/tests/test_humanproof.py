"""Guarded home, human key, proof single use, settings, and the pending read-back rule (H1)."""

import json
import os

import pytest

from orch import addons, runs
from orch import humanproof as hp
from orch.errors import Refused

TID = "t_abc123"


@pytest.fixture
def tws(tmp_path, monkeypatch):
    """A test workspace under <fake account home>/.orch-test with its test home; source-tree install =
    test."""
    acct = tmp_path / "acct"
    base = acct / ".orch-test"
    ws = base / "ws"
    (ws / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    for k in list(os.environ):
        if k.startswith("CODEX_"):
            monkeypatch.delenv(k)
    return ws


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setattr(hp, "ENFORCE_PENDING_MAC", True)


def test_switch_is_off_by_default():
    assert hp.ENFORCE_PENDING_MAC is False


# ---------------------------------------------------------------- guarded home


def test_test_workspace_uses_test_home(tws):
    assert hp.guarded_home(tws) == tws.parent / "home"


def test_normal_install_real_workspace_with_env_home_is_refused(tws, monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    acct = tws.parent.parent
    with pytest.raises(Refused, match="don't belong together"):
        hp.guarded_home(tws)  # real workspace + env-chosen home
    with pytest.raises(Refused):
        hp.human_key(tws)
    assert not (acct / ".orch-tool").exists()  # nothing created in the account home


def test_home_ok_refuses_other_pairings():
    a = "/Users/pat"
    assert not hp.home_ok(a, "test", True, a + "/.orch-test/ws", a + "/.orch-tool")
    assert not hp.home_ok(a, "dev", True, a + "/work", a + "/.orch-test/h")


def test_real_workspace_with_agent_chosen_home_refused(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    (acct / ".orch-test").mkdir(parents=True)
    ws = tmp_path / "elsewhere"
    ws.mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setattr(hp, "install_kind", lambda: "dev")
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "evil"))
    with pytest.raises(Refused, match="don't belong together"):
        hp.guarded_home(ws)
    assert not (acct / ".orch-tool").exists() and not (acct / ".orch-test" / "evil").exists()
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-tool"))
    assert hp.guarded_home(ws) == acct / ".orch-tool"  # the default home itself is fine
    monkeypatch.delenv("ORCH_HOME")
    assert hp.guarded_home(ws) == acct / ".orch-tool"


def test_symlinked_prefix_is_no_test_path(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    acct.mkdir()
    real = tmp_path / "real"
    (real / "ws").mkdir(parents=True)
    (acct / ".orch-test").symlink_to(real)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "h"))
    with pytest.raises(Refused):  # a real workspace: the symlinked prefix is no test path
        hp.guarded_home(acct / ".orch-test" / "ws")


# ---------------------------------------------------------------- key and proofs


def test_human_key_rights_and_reuse(tws):
    k = hp.human_key(tws)
    assert len(k) == 32 and hp.human_key(tws) == k
    f = hp.key_dir(tws) / "human.key"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    f.chmod(0o644)
    with pytest.raises(Refused, match="wrong rights"):
        hp.human_key(tws)


def _proof(tws, op="run.takeover", target=TID, by="human:pat", **kw):
    p = hp.new_payload(op, target, by)
    p.update(kw)
    return hp.mint(hp.human_key(tws), p)


def test_proof_single_use_and_by_from_proof(tws):
    pr = _proof(tws)
    assert hp.verify_and_consume(tws, pr, "run.takeover", TID) == "human:pat"
    with pytest.raises(Refused, match="dashboard"):
        hp.verify_and_consume(tws, pr, "run.takeover", TID)  # replay


def test_proof_wrong_target_and_by_flag_refused(tws):
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, _proof(tws), "run.takeover", "t_other1")
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, _proof(tws), "run.takeover", TID, by_flag="human:someone")


def test_proof_refused_in_agent_env(tws, monkeypatch):
    pr = _proof(tws)
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, pr, "run.takeover", TID)


def test_proof_without_key_refused(tws):
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, "hp1.x.y", "run.takeover", TID)


# ---------------------------------------------------------------- settings


def test_settings_tombstone_and_agent_edit(tws):
    s = "insights.share_counts"
    assert hp.effective(tws, s, True) is True  # default on, no record
    assert hp.effective(tws, s, False) is False  # lowered: tombstone written
    assert hp.effective(tws, s, True) is False  # an agent edits the file back: still off
    hp.record_set(tws, s, True, "human:pat")
    assert hp.effective(tws, s, True) is True  # a person set it with a proof


def test_settings_default_off_ignores_file_edit(tws):
    assert hp.effective(tws, "focus.session_typing", True) is False


def test_settings_unreadable_record_is_all_off(tws):
    hp.record_set(tws, "focus.live_session", True, "human:pat")
    (tws.parent / "home" / "human-settings.json").write_text("{not json")
    (tws.parent / "home" / "human-settings.json").chmod(0o600)
    assert hp.effective(tws, "focus.live_session", True) is False


# ---------------------------------------------------------------- pending read-back


def _file(tws):
    return runs.pending_path(tws, TID)


def test_off_keeps_old_behaviour(tws):
    runs.pending_add(tws, TID, "human:pat", "answer", "yes")
    assert len(runs.human_waiting(tws, TID)) == 1


def test_forged_by_human_line_is_no_run_start(tws, enforce):
    _file(tws).parent.mkdir(parents=True, exist_ok=True)
    line = {"id": "p_aaaaaaaa", "at": "2026-11-16T09:00:00Z", "by": "human:pat", "kind": "answer",
    "text": "x",
            "human": True, "via": "dashboard"}  # fmt: skip
    _file(tws).write_text(json.dumps(line) + "\n")
    assert runs.human_waiting(tws, TID) == []


def test_cli_style_human_line_is_agent_input(tws, enforce):
    runs.pending_add(tws, TID, "human:pat", "answer", "yes", "dashboard")
    assert runs.human_waiting(tws, TID) == []
    assert len(runs.undelivered(tws, TID)) == 1  # still delivered to a run that is already going


def test_valid_mac_starts_a_run(tws, enforce):
    runs.pending_add(tws, TID, "human:pat", "answer", "yes", "dashboard", proven=True)
    assert len(runs.human_waiting(tws, TID)) == 1


def test_phone_channel_line_counts(tws, enforce):
    runs.pending_add(tws, TID, "iPhone", "message", "hi", "phone", phone="ph_abc123")
    assert len(runs.human_waiting(tws, TID)) == 1


def test_phone_marker_in_agent_env_gets_no_mac(tws, enforce, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    runs.pending_add(tws, TID, "iPhone", "message", "hi", "phone", phone="ph_abc123")
    monkeypatch.delenv("CLAUDECODE")
    assert runs.human_waiting(tws, TID) == []


def test_copy_to_another_ticket_is_agent_input(tws, enforce):
    runs.pending_add(tws, TID, "human:pat", "answer", "yes", proven=True)
    other = "t_other1"
    _file(tws).parent.mkdir(parents=True, exist_ok=True)
    runs.pending_path(tws, other).write_text(_file(tws).read_text())
    assert runs.human_waiting(tws, other) == []
    assert len(runs.human_waiting(tws, TID)) == 1


def test_changed_text_is_agent_input(tws, enforce):
    runs.pending_add(tws, TID, "human:pat", "answer", "yes", proven=True)
    d = json.loads(_file(tws).read_text())
    d["text"] = "delete everything"
    _file(tws).write_text(json.dumps(d) + "\n")
    assert runs.human_waiting(tws, TID) == []


def test_stripped_delivered_at_and_replay_not_redelivered(tws, enforce):
    item = runs.pending_add(tws, TID, "human:pat", "answer", "yes", proven=True)
    runs.mark_delivered(tws, TID, [item["id"]])
    assert runs.human_waiting(tws, TID) == []
    d = json.loads(_file(tws).read_text())
    d.pop("delivered_at")  # an agent strips the marker
    _file(tws).write_text(json.dumps(d) + "\n")
    assert runs.human_waiting(tws, TID) == []
    _file(tws).write_text(_file(tws).read_text() * 2)  # or re-appends the consumed line
    assert runs.human_waiting(tws, TID) == []


def test_undeliver_waits_again(tws, enforce):
    item = runs.pending_add(tws, TID, "human:pat", "answer", "yes", proven=True)
    runs.mark_delivered(tws, TID, [item["id"]])
    runs.undeliver(tws, TID, [item["id"]])
    assert len(runs.human_waiting(tws, TID)) == 1


def test_live_retry_does_not_break_mac(tws, enforce):
    runs.pending_add(tws, TID, "human:pat", "answer", "yes", proven=True)
    d = json.loads(_file(tws).read_text())
    d["live_retry"] = True
    _file(tws).write_text(json.dumps(d) + "\n")
    assert len(runs.human_waiting(tws, TID)) == 1


def test_no_key_fails_closed(tws, enforce):
    runs.pending_add(tws, TID, "human:pat", "answer", "yes")
    assert runs.human_waiting(tws, TID) == []


def test_keys_folder_symlink_refused_on_read(tws):
    hp.human_key(tws)
    home = tws.parent / "home"
    real = home / "keys-real"
    (home / "keys").rename(real)
    (home / "keys").symlink_to(real)
    with pytest.raises(Refused, match="wrong rights"):
        hp.key_dir(tws, create=False)
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, "hp1.x.y", "run.takeover", TID)


def test_keys_folder_loose_rights_refused_on_read(tws):
    hp.human_key(tws)
    (tws.parent / "home" / "keys").chmod(0o755)
    with pytest.raises(Refused, match="wrong rights"):
        hp.key_dir(tws, create=False)


def test_test_install_never_uses_the_account_home(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    acct.mkdir()
    ws = tmp_path / "elsewhere"
    (ws / ".orch").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    monkeypatch.delenv("ORCH_HOME", raising=False)
    with pytest.raises(Refused, match="don't belong together"):
        hp.human_key(ws)
    assert list(acct.iterdir()) == []  # nothing created in the account home

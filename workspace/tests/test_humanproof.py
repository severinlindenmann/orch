"""Guarded home, human key, proof single use, settings, and the pending read-back rule (H1)."""

import contextlib
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


def test_loose_folders_are_tightened_not_refused(tws):
    k = hp.human_key(tws)
    home = tws.parent / "home"
    for d in (home, home / "keys", hp.key_dir(tws)):
        d.chmod(0o755)
    assert hp.human_key(tws, create=False) == k  # same key: only the folders were tightened
    for d in (home, home / "keys", hp.key_dir(tws)):
        assert oct(d.stat().st_mode & 0o777) == "0o700"
    assert hp.take_notices(tws) == []


# ---------------------------------------------------------------- loose secret files: reset


def _loose_setup(tws):
    """A key, a spent proof, a delivered id, a handoff, a dev record and a widened setting."""
    key = hp.human_key(tws)
    old = hp.mint(key, hp.new_payload("run.takeover", TID, "human:pat"))
    other = hp.mint(key, hp.new_payload("run.takeover", TID, "human:pat"))
    hp.verify_and_consume(tws, other, "run.takeover", TID)  # writes proofs-used.json
    hp.consume(tws, ["p_aaaaaaaa"])  # delivered.json
    d = hp.key_dir(tws)
    hp._write_private(d / "handoffs.json", json.dumps({"h": 1}))
    home = tws.parent / "home"
    hp._write_private(home / "dev-workspaces.json", json.dumps({"workspaces": {os.path.realpath(tws): {}}}))
    hp.record_set(tws, "focus.session_typing", True, "human:pat")
    assert hp.effective(tws, "focus.session_typing", True) is True
    assert hp.dev_record(tws) is True
    return key, old, d, home


READERS = {
    "human.key": lambda tws: hp.human_key(tws),
    "human-settings.json": lambda tws: hp.effective(tws, "focus.session_typing", True),
    "proofs-used.json": lambda tws: hp.verify_and_consume(tws, "hp1.x.y", "run.takeover", TID),
    "delivered.json": lambda tws: hp.delivered_ids(tws),
    "handoffs.json": lambda tws: hp.private_json(tws, "handoffs.json", {}),
    "dev-workspaces.json": lambda tws: hp.dev_record(tws),
}


@pytest.mark.parametrize("name", list(READERS))
def test_loose_secret_file_resets_protection(tws, name):
    key, old, d, home = _loose_setup(tws)
    path = home / name if name in ("human-settings.json", "dev-workspaces.json") else d / name
    path.chmod(0o644)  # loose: the content is never trusted
    with contextlib.suppress(Refused):
        READERS[name](tws)
    assert hp.human_key(tws) != key  # rotated
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, old, "run.takeover", TID)  # old proofs stop verifying
    assert not (d / "proofs-used.json").exists() and not (d / "delivered.json").exists()
    assert not (d / "handoffs.json").exists()
    for setting in ("focus.session_typing", "insights.share_names", "secret.allow_get", "conn.allow"):
        assert hp.effective(tws, setting, True) is False  # safest defaults
    assert hp.effective(tws, "focus.live_session", True) is True  # owner defaults stay
    assert hp.effective(tws, "insights.share_counts", True) is True
    notes = hp.take_notices(tws)
    assert [n["text"] for n in notes] == [hp.RESET_NOTICE]
    assert hp.take_notices(tws) == []  # one time
    log = (home / "protection-reset.log").read_text()
    assert name in log and key.hex() not in log and hp.human_key(tws).hex() not in log
    assert oct((home / "human-settings.json").stat().st_mode & 0o777) == "0o600"
    if name == "dev-workspaces.json":
        assert hp.dev_record(tws) is False


def test_wrong_type_is_loose_too(tws):
    key = hp.human_key(tws)
    f = hp.key_dir(tws) / "human.key"
    f.unlink()
    f.symlink_to(tws / "elsewhere")
    assert hp.human_key(tws) != key  # a link in place of the key: never followed, key rotated
    assert not (hp.key_dir(tws) / "human.key").is_symlink()


def test_extra_file_check_hook_counts_as_loose(tws, monkeypatch):
    key = hp.human_key(tws)
    flagged = []  # the hook flags the key once; the reset writes a good one

    def acl(p):
        if p.name == "human.key" and not flagged:
            flagged.append(1)
            return "acl"

    monkeypatch.setattr(hp, "FILE_CHECKS", [acl])
    assert hp.human_key(tws) != key
    monkeypatch.setattr(hp, "FILE_CHECKS", [])
    assert hp.take_notices(tws)


# ---------------------------------------------------------------- a reset never widens, never accepts a proof


def test_reset_holds_the_key_lock(tws, monkeypatch):
    hp.human_key(tws)
    d = hp.key_dir(tws)
    seen = []
    real = hp._write_private
    monkeypatch.setattr(hp, "_write_private", lambda p, t: (seen.append(hp._lock_held(d)), real(p, t))[1])
    hp.reset_protection(tws, "test:mode")
    assert seen and all(seen)  # every write of the reset ran under keys.lock
    assert not hp._lock_held(d)  # and it was released
    with hp._key_lock(d), hp._key_lock(d):  # re-entrant for readers that already hold it
        assert hp._lock_held(d)
    assert not (d / "keys.lock").exists()


def test_loose_nonce_store_during_verify_refuses_and_replay_stays_refused(tws):
    key = hp.human_key(tws)
    pr = hp.mint(key, hp.new_payload("run.takeover", TID, "human:pat"))
    d = hp.key_dir(tws)
    hp._write_private(d / "proofs-used.json", json.dumps({}))
    (d / "proofs-used.json").chmod(0o644)  # loose: a reset happens inside the verify
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, pr, "run.takeover", TID)  # valid for the old key, still refused
    assert hp.human_key(tws) != key
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, pr, "run.takeover", TID)  # replay after the reset
    fresh = hp.mint(hp.human_key(tws), hp.new_payload("run.takeover", TID, "human:pat"))
    assert hp.verify_and_consume(tws, fresh, "run.takeover", TID) == "human:pat"


def test_loose_human_key_during_verify_refuses(tws):
    key = hp.human_key(tws)
    pr = hp.mint(key, hp.new_payload("run.takeover", TID, "human:pat"))
    (hp.key_dir(tws) / "human.key").chmod(0o644)
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, pr, "run.takeover", TID)


def _open(rec, setting):
    return rec if rec is not None else hp.SETTING_DEFAULTS[setting]


@pytest.mark.parametrize("seed", range(40))
def test_reset_never_opens_a_setting(tws, seed):
    import random

    rnd = random.Random(seed)
    home = tws.parent / "home"
    _, wkey = hp._settings_path(tws)
    recs, before = {}, {}
    for st in hp.SETTING_DEFAULTS:
        v = rnd.choice([True, False, None])
        if v is not None:
            recs[st] = {"value": v, "by": "human:pat", "at": "2026-11-09T10:00:00Z"}
        before[st] = bool(_open(v, st))
    other = {"focus.live_session": {"value": False, "by": "file", "at": "2026-11-09T10:00:00Z"}}
    body = {"schema": "orch.human-settings/1", "workspaces": {wkey: recs, "f" * 32: other}}
    garbage = rnd.random() < 0.3
    hp._write_private(home / "human-settings.json", "{broken" if garbage else json.dumps(body))
    (home / "human-settings.json").chmod(0o644)  # loose: the next read resets
    if garbage:
        before = dict.fromkeys(before, False)  # an unreadable record means every widening is off (N12)
    after = {st: hp.effective(tws, st, True) for st in hp.SETTING_DEFAULTS}
    for st in hp.SETTING_DEFAULTS:
        assert after[st] <= before[st], (seed, st, before, after)
    saved = json.loads((home / "human-settings.json").read_text())["workspaces"]
    if not garbage:  # tombstones in any workspace survive
        assert saved["f" * 32] == other


# ---------------------------------------------------------------- guarded reads go through saferead


def test_fifo_in_place_of_a_guarded_file_does_not_hang(tws):
    key = hp.human_key(tws)
    f = hp.key_dir(tws) / "proofs-used.json"
    os.mkfifo(f, 0o600)
    pr = hp.mint(key, hp.new_payload("run.takeover", TID, "human:pat"))
    with pytest.raises(Refused):
        hp.verify_and_consume(tws, pr, "run.takeover", TID)  # returns, never blocks: reset + refused
    assert hp.human_key(tws) != key


def test_symlinked_and_oversized_and_hardlinked_files_are_loose(tws):
    for kind in ("symlink", "big", "hardlink"):
        key = hp.human_key(tws)
        f = hp.key_dir(tws) / "human.key"
        f.unlink()
        if kind == "symlink":
            f.symlink_to(tws / ".orch")
        elif kind == "big":
            hp._write_private(f, "a" * (hp.MAX_READ + 10))
        else:
            hp._write_private(tws / "other", key.hex())
            os.link(tws / "other", f)
        assert hp.human_key(tws) != key, kind  # never read, reset
        hp.take_notices(tws)


def test_install_record_read_through_saferead(tmp_path, monkeypatch):
    (tmp_path / "orch-install.json").write_text('{"kind": "dev"}')
    monkeypatch.setattr(hp.sys, "prefix", str(tmp_path))
    assert hp.install_kind() == "dev"
    (tmp_path / "orch-install.json").unlink()
    os.mkfifo(tmp_path / "orch-install.json")
    assert hp.install_kind() in ("test", "normal")  # a FIFO is no record, and does not hang

"""One real path = one key folder (humanproof._one_folder_per_path). A forged or damaged .orch/.local-id must
never open a second folder with empty ledgers; two existing folders for one path refuse every call."""

import json
import os
import secrets

import pytest

from orch import config, keystore, secretrun
from orch import humanproof as hp
from orch.humanproof import Refused


def _keys(root):
    k = hp.guarded_home(root) / "keys"
    return sorted(p.name for p in k.iterdir()) if k.exists() else []


def _forge(root, value=None):
    f = root / ".orch" / ".local-id"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text((value if value is not None else secrets.token_hex(16)) + "\n", encoding="utf-8")


def _second_folder(root):
    """An existing install with two folders bound to one path."""
    d = hp.key_dir(root)
    home = hp.guarded_home(root)
    other = home / "keys" / secrets.token_hex(16)
    other.mkdir(mode=0o700)
    (other / "binding.json").write_text(
        json.dumps({"schema": "orch.binding/1", "realpath": os.path.realpath(root)}) + "\n"
    )
    os.chmod(other / "binding.json", 0o600)
    return d, other


def test_normal_life(proj, tmp_path):
    d = hp.key_dir(proj)
    assert _keys(proj) == [d.name]
    assert hp.key_dir(proj) == d and hp.key_dir(proj, create=False) == d
    assert _keys(proj) == [d.name]
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    d2 = hp.key_dir(ws2)
    assert d2 != d
    assert _keys(proj) == sorted([d.name, d2.name])
    assert hp.key_dir(ws2, create=False) == d2 and hp.key_dir(proj, create=False) == d


@pytest.mark.parametrize(
    "call",
    [
        lambda r: keystore.add(r, "K", "token", "value-12345"),
        lambda r: config.change_insights(r, "insights.share_names", False),
        lambda r: secretrun._switch_on(r, "p", "allow_get"),
        lambda r: hp.human_key(r),
        lambda r: hp.relay_allow_set(r, "t", "q", "m"),
    ],
    ids=["keystore", "config", "secretrun", "human_key", "relay_allow_set"],
)
def test_forged_id_refused_no_new_folder(proj, call):
    d = hp.key_dir(proj)
    before = _keys(proj)
    _forge(proj)
    try:
        out = call(proj)
    except (Refused, OSError):
        pass
    else:
        assert out is False, "a forged id must be refused"  # ledger writers answer False
    assert _keys(proj) == before
    with pytest.raises(Refused):
        hp.key_dir(proj)
    with pytest.raises(Refused):
        hp.key_dir(proj, create=False)
    _forge(proj, d.name)  # the old id again: the old folder counts again, no second one was made
    assert hp.key_dir(proj, create=False) == d


def _id(root):
    return (root / ".orch" / ".local-id").read_text().strip()


@pytest.mark.parametrize("garbage", ["not an id", "", "../../x", None])
def test_missing_or_damaged_id_heals(proj, garbage):
    d = hp.key_dir(proj)
    body = hp.pin_next(proj, "sync.address", {"x": 1})
    if garbage is None:
        (proj / ".orch" / ".local-id").unlink()
    else:
        _forge(proj, garbage)
    assert hp.key_dir(proj) == d  # healed to the bound folder's id, no second folder
    assert _id(proj) == d.name
    assert _keys(proj) == [d.name]
    assert hp.pin_ok(proj, "sync.address", body)


def test_deleted_id_heals_on_read_and_keystore(proj):
    d = hp.key_dir(proj)
    (proj / ".orch" / ".local-id").unlink()
    assert hp.key_dir(proj, create=False) == d and _id(proj) == d.name
    (proj / ".orch" / ".local-id").unlink()
    keystore.add(proj, "K", "token", "value-12345")
    assert _keys(proj) == [d.name]


def test_forged_valid_id_message(proj):
    hp.key_dir(proj)
    _forge(proj)
    with pytest.raises(Refused, match="id was changed"):
        hp.key_dir(proj)


def test_empty_existing_folder_refused_before_binding(proj):
    d = hp.key_dir(proj)
    empty = hp.guarded_home(proj) / "keys" / secrets.token_hex(16)
    empty.mkdir(mode=0o700)
    _forge(proj, empty.name)
    with pytest.raises(Refused):
        hp.key_dir(proj)
    assert not (empty / "binding.json").exists()
    assert _keys(proj) == sorted([d.name, empty.name])


@pytest.mark.parametrize(
    "exc", [hp.winacl.Unknown("x"), Refused("unknown"), hp.LooseFile("binding.json:mode")]
)
def test_unreadable_other_binding_refuses(proj, monkeypatch, exc):
    d = hp.key_dir(proj)
    other = hp.guarded_home(proj) / "keys" / secrets.token_hex(16)
    other.mkdir(mode=0o700)
    (other / "binding.json").write_text("{}")
    real = hp._read_guarded

    def fake(path):
        if path.parent == other:
            raise exc
        return real(path)

    monkeypatch.setattr(hp, "_read_guarded", fake)
    _forge(proj)
    with pytest.raises(Refused):
        hp.key_dir(proj)
    assert _keys(proj) == sorted([d.name, other.name])


def test_reset_protection_makes_no_second_folder(proj):
    d = hp.key_dir(proj)
    _forge(proj)
    with pytest.raises(Refused):
        hp.reset_protection(proj, "test")
    assert _keys(proj) == [d.name]


def test_two_folders_refuse_everything(proj):
    d, other = _second_folder(proj)
    for create in (True, False):
        with pytest.raises(Refused, match="id was changed"):
            hp.key_dir(proj, create=create)
    _forge(proj, other.name)
    for create in (True, False):
        with pytest.raises(Refused):
            hp.key_dir(proj, create=create)


def test_pins_not_empty_after_forged_id(proj):
    kind = "sync.address"
    hp.key_dir(proj)
    body = hp.pin_next(proj, kind, {"x": 1})
    assert body and hp.pin_ok(proj, kind, body)
    assert hp.relay_allow_set(proj, "t", "q", "m")
    _forge(proj)
    assert hp.record_pin(proj, kind) is None  # cannot be told, never {} ("never pinned")
    assert hp.pin_ok(proj, kind, body) is False
    assert hp.pin_next(proj, kind, {"x": 2}) is None
    assert hp.relay_allow_get(proj, "t", "q") is None
    assert hp.relay_allow_set(proj, "t", "q", "other") is False
    assert len(_keys(proj)) == 1

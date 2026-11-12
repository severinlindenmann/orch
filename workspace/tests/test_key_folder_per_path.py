"""One real path = one key folder (humanproof._resolve). A forged or damaged .orch/.local-id must
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
def test_forged_id_makes_no_new_folder(proj, call):
    d = hp.key_dir(proj)
    before = _keys(proj)
    _forge(proj)  # a fresh valid id naming no folder: healed back to the bound one, never a second folder
    try:
        call(proj)
    except (Refused, OSError):
        pass
    assert _keys(proj) == before
    assert hp.key_dir(proj, create=False) == d and _id(proj) == d.name


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


def test_empty_existing_folder_refused_before_binding(proj):
    d = hp.key_dir(proj)
    empty = hp.guarded_home(proj) / "keys" / secrets.token_hex(16)
    empty.mkdir(mode=0o700)
    _forge(proj, empty.name)  # an id naming a DIFFERENT EXISTING folder: refused
    for create in (True, False):
        with pytest.raises(Refused, match="id was changed"):
            hp.key_dir(proj, create=create)
    assert not (empty / "binding.json").exists()
    assert _keys(proj) == sorted([d.name, empty.name])


@pytest.mark.parametrize(
    "exc", [hp.winacl.Unknown("x"), Refused("unknown"), hp.LooseFile("binding.json:mode")]
)
@pytest.mark.parametrize("create", [True, False])
def test_unreadable_other_binding_refuses(proj, monkeypatch, exc, create):
    """No own folder; ONE other folder bound to this path whose binding cannot be read; no .local-id."""
    other = hp.guarded_home(proj) / "keys" / secrets.token_hex(16)
    other.mkdir(parents=True, mode=0o700)
    (other / "binding.json").write_text("{}")
    real = hp._read_guarded

    def fake(path):
        if path.parent == other:
            raise exc
        return real(path)

    monkeypatch.setattr(hp, "_read_guarded", fake)
    with pytest.raises(Refused, match="ask the owner") as e:
        hp.key_dir(proj, create=create)
    assert other.name in str(e.value)
    assert _keys(proj) == [other.name]
    assert not (proj / ".orch" / ".local-id").exists()


def test_reset_protection_makes_no_second_folder(proj):
    d = hp.key_dir(proj)
    _forge(proj, secrets.token_hex(16))
    hp.reset_protection(proj, "test")  # heals to the bound folder; no folder of its own
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


def test_pins_survive_forged_id(proj):
    kind = "sync.address"
    d = hp.key_dir(proj)
    body = hp.pin_next(proj, kind, {"x": 1})
    assert body and hp.pin_ok(proj, kind, body)
    assert hp.relay_allow_set(proj, "t", "q", "m")
    _forge(proj)
    assert hp.record_pin(proj, kind) == hp.record_pin(proj, kind) != {}  # never "never pinned"
    assert hp.pin_ok(proj, kind, body) is True
    assert hp.relay_allow_get(proj, "t", "q")["message"] == "m"
    assert _keys(proj) == [d.name]


def test_valid_id_naming_no_folder_heals_when_one_bound(proj):
    d = hp.key_dir(proj)
    new = secrets.token_hex(16)
    _forge(proj, new)
    assert hp.key_dir(proj, create=False) == d and _id(proj) == d.name


@pytest.mark.parametrize("target", ["binding.json", "human.key", "record-pins.json"])
@pytest.mark.parametrize("create", [True, False])
def test_local_id_symlink_never_written_through(proj, target, create):
    d = hp.key_dir(proj)
    hp.human_key(proj)
    hp.pin_next(proj, "sync.address", {"x": 1})
    before = {n: (d / n).read_bytes() for n in ("binding.json", "human.key", "record-pins.json")}
    lid = proj / ".orch" / ".local-id"
    lid.unlink()
    lid.symlink_to(d / target)
    try:
        hp.key_dir(proj, create=create)
    except Refused:
        pass
    assert {n: (d / n).read_bytes() for n in before} == before
    assert not lid.is_symlink()
    assert _keys(proj) == [d.name]
    assert hp.key_dir(proj, create=False) == d


def test_local_id_symlink_fresh_workspace(proj, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (proj / ".orch").mkdir()
    (proj / ".orch" / ".local-id").symlink_to(victim)
    hp.key_dir(proj)
    assert victim.read_text() == "keep"
    assert not (proj / ".orch" / ".local-id").is_symlink()


def test_orch_dir_symlink_refused(proj, tmp_path):
    d = hp.key_dir(proj)
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / ".local-id").write_text(d.name + "\n")
    import shutil

    shutil.rmtree(proj / ".orch")
    (proj / ".orch").symlink_to(real)
    before = (real / ".local-id").read_bytes()
    for create in (True, False):
        with pytest.raises(Refused):
            hp.key_dir(proj, create=create)
    assert (real / ".local-id").read_bytes() == before
    assert _keys(proj) == [d.name]


def test_first_setup_race_one_id_one_folder(proj, monkeypatch):
    """Another process wins the fresh id between our look and our write: we keep ITS id, one folder."""
    from orch import addons

    real_put = addons.put_local_id
    other_id = secrets.token_hex(16)
    calls = []

    def racing(root, v, **kw):
        if not calls:
            calls.append(1)
            real_put(root, other_id)  # the other process wrote first
        return real_put(root, v, **kw)

    monkeypatch.setattr(addons, "put_local_id", racing)
    d = hp.key_dir(proj)
    assert d.name == other_id == _id(proj)
    assert _keys(proj) == [other_id]


def test_orch_swapped_for_link_at_write_time(proj, tmp_path, monkeypatch):
    """.orch is swapped for a link to another folder right when the temp file is made: nothing lands there."""
    from orch import addons

    other = tmp_path / "other"
    other.mkdir()
    (proj / ".orch").mkdir(exist_ok=True)
    monkeypatch.setattr(addons, "_orch_dir_is_plain", lambda r: True)
    real_open = os.open
    swapped = []

    def swapping(path, flags, *a, **kw):
        if isinstance(path, str) and path.startswith(".local-id.") and not swapped:
            swapped.append(1)
            os.rename(proj / ".orch", proj / ".orch-moved")
            os.symlink(other, proj / ".orch")
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(os, "open", swapping)
    with pytest.raises(Refused):
        addons.put_local_id(proj, secrets.token_hex(16))
    assert list(other.iterdir()) == []


def test_orch_swapped_for_link_before_open(proj, tmp_path, monkeypatch):
    from orch import addons

    other = tmp_path / "other"
    other.mkdir()
    (proj / ".orch").mkdir(exist_ok=True)

    real_mkdir = os.mkdir

    def swap_then_mkdir(path, *a, **kw):
        if str(path) == str(proj / ".orch"):
            os.rename(proj / ".orch", proj / ".orch-moved")
            os.symlink(other, proj / ".orch")
        return real_mkdir(path, *a, **kw)

    monkeypatch.setattr(os, "mkdir", swap_then_mkdir)
    with pytest.raises(Refused):
        addons.put_local_id(proj, secrets.token_hex(16))
    assert list(other.iterdir()) == []


def test_winner_seen_late_is_kept(proj, monkeypatch):
    """A concurrent writer's file has 2 links for a moment (a read says None): wait, never overwrite."""
    from orch import addons

    winner = secrets.token_hex(16)
    (proj / ".orch").mkdir(exist_ok=True)
    (proj / ".orch" / ".local-id").write_text(winner + "\n")
    answers = iter([None, None, winner])
    monkeypatch.setattr(addons, "read_local_id", lambda r: next(answers, winner))
    assert addons.put_local_id(proj, secrets.token_hex(16)) == winner
    assert (proj / ".orch" / ".local-id").read_text().strip() == winner

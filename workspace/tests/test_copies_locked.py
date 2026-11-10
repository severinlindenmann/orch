"""Separate copies are locked Off for this release: no copy is made, the setting can't be turned on,
and nothing is removed automatically."""

import pytest

from orch import config
from orch.errors import Refused

pytestmark = pytest.mark.copies_locked


def test_the_lock_is_on_in_the_product():
    assert config.COPIES_LOCKED is True
    assert config.DEFAULT_COPIES == "off"


def test_copies_mode_is_always_off_even_when_a_mode_was_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_copies_get", lambda root, key: "always" if key == "copies" else None)
    assert config.copies_mode(tmp_path) == "off"


@pytest.mark.parametrize("value", ["together", "always"])
def test_turning_copies_on_is_refused_with_a_plain_message(tmp_path, value):
    with pytest.raises(Refused, match="coming soon"):
        config.set_copies_mode(tmp_path, value)


def test_off_can_still_be_stored(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(config, "_copies_set", lambda root, key, v: seen.update({key: v}))
    assert config.set_copies_mode(tmp_path, "off") == "off"
    assert seen == {"copies": "off"}


def _forged_copy(proj):
    """A fake copy folder plus a forged .owner, as an agent could plant them."""
    from orch import addons, worktrees

    addons.workspace_id(proj, create=True)
    d = worktrees.copies_dir(proj)
    if d is None:
        pytest.skip("this test workspace has no copies folder")
    victim = d / "t_aaaaaaaa"
    victim.mkdir(parents=True, exist_ok=True)
    (victim / "work.txt").write_text("unsaved work\n")
    (d / ".owner").write_text(str(proj / "moved-away") + "\n")
    return d, victim


def test_while_locked_nothing_is_removed_automatically(proj):
    from orch import worktrees

    d, victim = _forged_copy(proj)
    assert worktrees.sweep(proj) == []
    assert worktrees.remove(proj, "t_aaaaaaaa") == []
    worktrees.on_closed(proj, "t_aaaaaaaa")
    worktrees.on_run_ended(proj, "t_aaaaaaaa")
    worktrees.schedule_sweep(proj)
    assert worktrees.empty_trash(proj) is True
    assert (victim / "work.txt").read_text() == "unsaved work\n"


@pytest.mark.parametrize("call", ["remove_orphaned", "retry"])
def test_person_only_deletes_are_refused_while_locked(proj, call):
    from orch import worktrees

    d, victim = _forged_copy(proj)
    with pytest.raises(Refused, match="paused"):
        if call == "remove_orphaned":
            worktrees.remove_orphaned(proj, d.name, discard=True)
        else:
            worktrees.retry(proj, "t_aaaaaaaa")
    assert victim.is_dir()

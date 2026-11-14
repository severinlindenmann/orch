"""Update page data: a readable release number, the newest version and a short list of what changed."""

from __future__ import annotations

import json

import pytest

from orch import addons, updateinfo

OLD, NEW = "a" * 40, "b" * 40


def merge(n, branch, title):
    return {"commit": {"message": f"Merge pull request #{n} from user/{branch}\n\n{title}"}}


def test_release_number_from_the_newest_release_merge():
    msgs = [
        "Merge pull request #800 from u/fix/x\n\nFix x",
        "Merge pull request #722 from severinlindenmann/release/part17-1114\n\nRelease part 17",
        "Merge pull request #715 from severinlindenmann/release/part16-1114\n\nRelease part 16",
    ]
    assert updateinfo.release_in(msgs) == 17
    assert updateinfo.release_in(["Merge main into release/part17 (ours)", "other"]) is None  # not a PR merge
    assert updateinfo.release_in([]) is None


def test_label_prefers_release_then_short_sha_then_package_version():
    assert updateinfo.label(15, OLD, "main") == "orch 15"
    assert updateinfo.label(None, OLD, "develop") == "orch develop " + OLD[:8]
    assert updateinfo.label(None, None, "main").startswith("orch ")


def test_changes_are_plain_merged_titles_newest_five_with_more_count():
    msgs = [f"Merge pull request #{i} from u/b{i}\n\nfix: thing number {i}.\n\nbody" for i in range(8, 0, -1)]
    msgs.insert(3, "Merge pull request #99 from u/release/part18-x\n\nRelease 18: helpers start again")
    msgs.insert(0, "plain commit without a merge")
    lines = updateinfo.changes_from(msgs)
    assert len(lines) == 6
    assert lines[0] == "Thing number 8"  # newest first, no "fix:" prefix, no final dot, capital letter
    assert lines[-1] == "and 3 more"
    assert not any("Release" in x for x in lines)  # five pull requests fill the list: no release line


def test_release_titles_follow_the_pull_requests_when_there_is_room():
    msgs = [
        "Merge pull request #5 from u/x\n\nfix: Sync keeps its history",
        "Merge pull request #99 from u/release/part18-x\n\nRelease 18: helpers start again",
    ]
    assert updateinfo.changes_from(msgs) == ["Sync keeps its history", "Helpers start again"]


def test_changes_text_is_printable_only():
    lines = updateinfo.changes_from(["Merge pull request #1 from u/b\n\nHello\x1b[31m red‮"])
    assert lines == ["Hello[31m red"]


def test_info_offline_has_no_newest(proj, monkeypatch):
    monkeypatch.setattr(updateinfo, "_fetch_messages", lambda *a, **k: None)
    monkeypatch.setattr(addons, "_source_sha", lambda: None)
    info = updateinfo.info(use_cache=False)
    assert info["newest"] is None and info["update_available"] is False
    assert info["installed"]["label"].startswith("orch ")


def test_info_update_available_with_changes(proj, monkeypatch):
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / "installed.json").write_text(json.dumps({"sha": OLD, "release": 15}))
    monkeypatch.setattr(addons, "_source_sha", lambda: NEW)
    seen = {}

    def fake(kind, a, b=None):
        seen[kind] = (a, b)
        if kind == "between":
            return ["Merge pull request #5 from u/x\n\nHelpers tidy up new tickets"]
        return ["Merge pull request #9 from u/release/part16-1\n\nRelease"]

    monkeypatch.setattr(updateinfo, "_fetch_messages", fake)
    info = updateinfo.info(use_cache=False)
    assert info["installed"]["release"] == 15 and info["installed"]["label"] == "orch 15"
    assert info["newest"]["label"] == "orch 16"
    assert info["update_available"] is True
    assert info["changes"] == ["Helpers tidy up new tickets"]
    assert seen["between"] == (OLD, NEW)


def test_info_same_sha_is_up_to_date(proj, monkeypatch):
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / "installed.json").write_text(json.dumps({"sha": OLD, "release": 15}))
    monkeypatch.setattr(addons, "_source_sha", lambda: OLD)
    monkeypatch.setattr(updateinfo, "_fetch_messages", lambda kind, a, b=None: [])
    info = updateinfo.info(use_cache=False)
    assert info["update_available"] is False and info["changes"] == []


@pytest.mark.parametrize("bad", [None, [], "x", {"sha": 5}, {"sha": "zz", "release": "9"}, {"release": -1}])
def test_installed_record_hostile_values(proj, monkeypatch, bad):
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / "installed.json").write_text(json.dumps(bad))
    got = updateinfo.installed()
    assert got["sha"] is None and got["release"] is None

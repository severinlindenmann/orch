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


def test_changes_have_no_issue_or_ticket_numbers():
    """Report r-1118-0907: Home listed "#1393, #1381, #1364" as a change."""
    msgs = [
        "Merge pull request #9 from u/a\n\n#1393, #1381, #1364",
        "Merge pull request #8 from u/b\n\nfix(factory): Budget health is right again (ORCH-411)",
        "Merge pull request #7 from u/c\n\nHelpers say when a test is broken, closes #1290",
        "Merge pull request #6 from u/d\n\nFiles stay utf-8 on release-34",
    ]
    assert updateinfo.changes_from(msgs) == [
        "Budget health is right again",
        "Helpers say when a test is broken",
        "Files stay utf-8 on release-34",
    ]


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


def test_announce_lines_name_both_versions_and_what_changed(proj, monkeypatch):
    monkeypatch.setattr(
        updateinfo,
        "info",
        lambda use_cache=True: {
            "installed": {"label": "orch 15"},
            "newest": {"label": "orch 16"},
            "update_available": True,
            "changes": ["Helpers tidy up new tickets"],
        },
    )
    assert updateinfo.announce_lines() == [
        "Updating orch 15 → orch 16",
        "What changed:",
        "  - Helpers tidy up new tickets",
    ]


def test_announce_lines_empty_when_up_to_date_or_unknown(proj, monkeypatch):
    for value in ({"update_available": False}, {"update_available": None}, {}):
        monkeypatch.setattr(updateinfo, "info", lambda use_cache=True, v=value: v)
        assert updateinfo.announce_lines() == []
    monkeypatch.setattr(updateinfo, "info", lambda use_cache=True: 1 / 0)
    assert updateinfo.announce_lines() == []


def test_pending_install_gets_its_commit_and_release_later(proj, monkeypatch):
    """An update GitHub did not answer: the next look-up finds the commit at that time and its release."""
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / "installed.json").write_text(
        json.dumps({"sha": None, "pending": {"ref": "main", "at": 1_700_000_000}})
    )
    asked = []
    monkeypatch.setattr(updateinfo, "_commit_at", lambda ref, at: asked.append((ref, at)) or NEW)
    monkeypatch.setattr(addons, "_source_sha", lambda: NEW)
    monkeypatch.setattr(
        updateinfo,
        "_fetch_messages",
        lambda kind, a, b=None: ["Merge pull request #9 from u/release/part34\n\nR"],
    )
    info = updateinfo.info(use_cache=False)
    assert asked == [("main", 1_700_000_000)]
    assert info["installed"]["label"] == "orch 34" and info["update_available"] is False
    assert json.loads((addons.home() / "installed.json").read_text()) == {"sha": NEW, "release": 34}


def test_pending_install_still_no_answer_keeps_waiting(proj, monkeypatch):
    addons.home().mkdir(parents=True, exist_ok=True)
    record = {"sha": None, "pending": {"ref": "main", "at": 1_700_000_000}}
    (addons.home() / "installed.json").write_text(json.dumps(record))
    monkeypatch.setattr(updateinfo, "_commit_at", lambda ref, at: None)
    monkeypatch.setattr(addons, "_source_sha", lambda: None)
    updateinfo.info(use_cache=False)
    assert json.loads((addons.home() / "installed.json").read_text()) == record
    # the commit answers but the history does not: still waiting, not saved without its release
    monkeypatch.setattr(updateinfo, "_commit_at", lambda ref, at: NEW)
    monkeypatch.setattr(updateinfo, "_fetch_messages", lambda *a, **k: None)
    updateinfo.info(use_cache=False)
    assert json.loads((addons.home() / "installed.json").read_text()) == record


@pytest.mark.parametrize("bad", ["null", "[]", '"x"', '{"sha": null, "pending": {"ref": 5, "at": 1}}'])
def test_pending_hostile_records_are_left_alone(proj, monkeypatch, bad):
    addons.home().mkdir(parents=True, exist_ok=True)
    (addons.home() / "installed.json").write_text(bad)
    monkeypatch.setattr(updateinfo, "_commit_at", lambda ref, at: 1 / 0)
    updateinfo.resolve_pending()
    assert (addons.home() / "installed.json").read_text() == bad


def test_commit_at_asks_github_for_the_ref_at_that_time(proj, monkeypatch):
    import io
    import urllib.request

    monkeypatch.setattr(addons, "_github_api", lambda: "https://api.github.com/repos/o/orch")
    urls = []

    def urlopen(req, timeout):
        urls.append(req.full_url)
        return io.BytesIO(json.dumps([{"sha": NEW}]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert updateinfo._commit_at("main", 1_700_000_000) == NEW
    assert urls == [
        "https://api.github.com/repos/o/orch/commits?sha=main&until=2023-11-14T22:13:20Z&per_page=1"
    ]

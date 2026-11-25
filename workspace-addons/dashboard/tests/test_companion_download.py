"""orch Companion card on About & updates (ORCH-1721): the newest release is picked like the app picks its update."""

from __future__ import annotations

from orch import addons  # noqa: F401 - imported first, so the isolation fixture fakes its real home

from orch_dashboard import update

BASE = "https://github.com/severinlindenmann/orch/releases"


def rel(v, draft=False, pre=False, asset=None, url=None):
    name = asset or f"orch-Companion-{v}.zip"
    return {
        "tag_name": f"companion-v{v}",
        "draft": draft,
        "prerelease": pre,
        "html_url": f"{BASE}/tag/companion-v{v}",
        "assets": [{"name": name, "browser_download_url": url or f"{BASE}/download/companion-v{v}/{name}"}],
    }


def test_newest_plain_release_with_its_zip():
    rows = [
        rel("0.1.10"),
        rel("0.2.0", draft=True),
        rel("0.3.0", pre=True),
        rel("0.1.9"),
        rel("0.4.0", asset="other.zip"),
        rel("0.5.0", url="https://evil.example/orch-Companion-0.5.0.zip"),
        {"tag_name": "release-41", "draft": False, "prerelease": False, "assets": []},
        {"tag_name": "companion-v01.0.0", "draft": False, "prerelease": False, "assets": []},
        "junk",
    ]
    assert update.pick_companion(rows) == {
        "version": "0.1.10",
        "url": f"{BASE}/download/companion-v0.1.10/orch-Companion-0.1.10.zip",
        "page": f"{BASE}/tag/companion-v0.1.10",
    }
    assert update.pick_companion([]) is None
    assert update.pick_companion({"message": "rate limited"}) is None


def test_offline_gives_the_release_list_and_asks_again_after_ten_minutes(monkeypatch):
    monkeypatch.setattr(update, "_companion", {"at": -1e9, "ok": False, "value": None})
    calls = []

    def down():
        calls.append(1)
        raise OSError("offline")

    assert update.companion_download(fetch=down, now=1000) == {"page": update.COMPANION_PAGE}
    assert update.companion_download(fetch=down, now=1500) == {"page": update.COMPANION_PAGE}
    assert len(calls) == 1
    got = update.companion_download(fetch=lambda: [rel("0.1.1")], now=1700)
    assert got["version"] == "0.1.1"
    # a good answer is kept 6 hours
    assert update.companion_download(fetch=down, now=1700 + 5 * 3600)["version"] == "0.1.1"
    assert len(calls) == 1

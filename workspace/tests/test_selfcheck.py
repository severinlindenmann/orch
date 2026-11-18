"""The short check after every update (ORCH-551): Factory list, merge queue runner, dashboard sign-in and each
add-on page; a failure after moving to a newer release keeps one card "Go back to release N-1?"."""

import json
import time

import pytest

from orch import addons, selfcheck

ADDONS = [
    {"name": "factory", "active": True, "dashboard": {"label": "Factory"}},
    {"name": "pull-requests", "active": True, "dashboard": {"label": "Pull requests"}},
    {"name": "dashboard", "active": True},
    {"name": "services", "active": True, "page": {"path": "/"}},
    {"name": "insights", "active": False, "dashboard": {"label": "Insights"}},
]


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    h = tmp_path / "orchhome"
    h.mkdir()
    monkeypatch.setattr(addons, "home", lambda: h)


class Fake:
    """A stand-in for the newly installed orch: answers per command, records what was asked."""

    def __init__(self, broken=(), queue=None):
        self.broken, self.asked = set(broken), []
        self.queue = queue if queue is not None else {"entries": [], "running": False}

    def __call__(self, argv, root):
        self.asked.append(argv)
        key = " ".join(argv)
        if any(key.startswith(b) for b in self.broken):
            return 1, "Traceback (most recent call last):"
        if argv[:2] == ["addon", "list"]:
            return 0, json.dumps(ADDONS)
        if argv[:2] == ["factory", "list"]:
            return 0, "[]"
        if argv[:3] == ["pull-requests", "queue", "list"]:
            return 0, json.dumps(self.queue)
        if argv[1:] == ["view", "--json"]:
            return 0, json.dumps({"generated_at": "x"})
        return 0, ""


def ok_dashboard(root):
    return None


def test_every_check_passes_on_a_healthy_install(tmp_path):
    fake = Fake()
    got = selfcheck.run_checks(tmp_path, fake, ok_dashboard)
    assert [r["name"] for r in got] == [
        "Factory list",
        "Merge queue runner",
        "Dashboard sign-in",
        "factory page",
        "pull-requests page",
        "services page",
    ]
    assert all(r["ok"] for r in got)
    assert ["insights", "view", "--json"] not in fake.asked  # an add-on that is off is not probed
    assert ["services", "--help"] in fake.asked  # a page without a dashboard tab: its command loads


def test_a_seeded_fault_in_the_factory_is_found(tmp_path):
    got = selfcheck.run_checks(tmp_path, Fake(broken=["factory"]), ok_dashboard)
    bad = {r["name"]: r["why"] for r in got if not r["ok"]}
    assert bad == {
        "Factory list": "the Factory list does not open",
        "factory page": "the factory page does not answer",
    }


def test_queue_runner_down_while_pull_requests_wait(tmp_path):
    q = {"entries": [{"state": "waiting"}, {"state": "merged"}], "running": False}
    got = {r["name"]: r for r in selfcheck.run_checks(tmp_path, Fake(queue=q), ok_dashboard)}
    assert got["Merge queue runner"]["why"] == "the merge queue runner is not running (1 pull requests wait)"
    q["running"] = True
    got = {r["name"]: r for r in selfcheck.run_checks(tmp_path, Fake(queue=q), ok_dashboard)}
    assert got["Merge queue runner"]["ok"]


def test_no_add_on_list_is_one_failed_check(tmp_path):
    got = selfcheck.run_checks(tmp_path, Fake(broken=["addon list"]), ok_dashboard)
    assert got == [{"name": "add-ons", "ok": False, "why": "the add-on list does not open"}]


def test_failure_after_a_newer_release_keeps_the_go_back_card(tmp_path):
    lines = selfcheck.after_update(tmp_path, 32, 33, Fake(broken=["factory list"]), ok_dashboard)
    assert lines[0] == "Self-check after the update found a problem:"
    assert "  - the Factory list does not open" in lines
    assert lines[-1] == "Go back to release 32 with: orch update --to 32"
    c = selfcheck.card()
    assert c["back_to"] == 32 and c["release"] == 33
    assert c["failed"] == [{"name": "Factory list", "why": "the Factory list does not open"}]
    # the next update passes: the card goes away
    assert selfcheck.after_update(tmp_path, 32, 33, Fake(), ok_dashboard) == [
        "Self-check: all 6 checks passed."
    ]
    assert selfcheck.card() is None


@pytest.mark.parametrize(("old", "new"), [(33, 32), (None, 33), (33, None), (33, 33)])
def test_no_go_back_offer_unless_the_update_moved_forward(tmp_path, old, new):
    lines = selfcheck.after_update(tmp_path, old, new, Fake(broken=["factory list"]), ok_dashboard)
    assert not any("Go back" in x for x in lines)
    assert selfcheck.card()["back_to"] is None


def test_a_broken_check_never_breaks_the_update(tmp_path):
    def boom(argv, root):
        raise RuntimeError("bad")

    lines = selfcheck.after_update(tmp_path, 32, 33, boom, ok_dashboard)
    assert "the check itself failed: bad" in lines[1] and selfcheck.card()["back_to"] == 32


def test_an_old_or_broken_card_is_not_shown():
    selfcheck.card_path().write_text("not json")
    assert selfcheck.card() is None
    old = int(time.time()) - (selfcheck.KEEP_DAYS + 1) * 86400
    selfcheck.card_path().write_text(json.dumps({"at": old, "failed": [{"why": "x"}], "back_to": 3}))
    assert selfcheck.card() is None
    selfcheck.card_path().write_text(
        json.dumps({"at": int(time.time()), "failed": [{"why": "x"}], "back_to": True})
    )
    assert selfcheck.card()["back_to"] is None
    selfcheck.dismiss()
    assert not selfcheck.card_path().exists()


def test_dashboard_sign_in(monkeypatch, tmp_path):
    monkeypatch.setattr(selfcheck.time, "sleep", lambda s: None)
    calls = []

    def http(url, body=None, origin=None):
        calls.append((url, body, origin))
        return 200

    def find(root):
        return "http://127.0.0.1:8770"

    assert (
        selfcheck._dashboard(tmp_path, http, find, lambda r, b, h: h(f"{b}/session", {"token": "t"}, b))
        is None
    )
    assert calls[-1] == ("http://127.0.0.1:8770/session", {"token": "t"}, "http://127.0.0.1:8770")
    assert (
        selfcheck._dashboard(tmp_path, http, find, lambda r, b, h: 403)
        == "dashboard sign-in failed (answer 403)"
    )
    assert (
        selfcheck._dashboard(tmp_path, http, find, lambda r, b, h: -1) is None
    )  # a helper: the page answers
    assert (
        selfcheck._dashboard(tmp_path, lambda *a, **k: 0, find, lambda *a: 200)
        == "the dashboard does not answer"
    )
    assert (
        selfcheck._dashboard(tmp_path, http, lambda r: None, lambda *a: 200) == "the dashboard is not running"
    )


def test_a_helper_never_signs_in_as_the_person(monkeypatch, tmp_path):
    from orch import pagelaunch, tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: False)
    monkeypatch.setattr(
        pagelaunch, "write_launch_token", lambda *a: pytest.fail("a token was made for a helper")
    )
    assert selfcheck._sign_in(tmp_path, "http://127.0.0.1:1", lambda *a: 200) == -1


def test_update_runs_the_check_after_the_restart(monkeypatch, tmp_path):
    """addons.update (the project step) calls the check with the release before and after."""
    import inspect

    src = inspect.getsource(addons.update)
    assert src.index("_restart_updated(root)") < src.index(
        'selfcheck.after_update(root, before.get("release"), new_release)'
    )

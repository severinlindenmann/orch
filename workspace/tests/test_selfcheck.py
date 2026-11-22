"""The short check after every update (ORCH-551): what each add-on declares in its manifest ([[selfcheck]]:
the Factory list, the merge queue runner), the sign-in of each running page server and each add-on page; a
failure after moving to a newer release keeps one card "Go back to release N-1?"."""

import json
import time

import pytest

from orch import addons, selfcheck
from orch.errors import Refused

LIST = {"label": "Factory list", "fails": "the Factory list does not open", "args": ["list", "--json"]}
RUNNER = {"label": "Merge queue runner", "fails": "the runner is not running", "args": ["queue", "check"]}
ADDONS = [
    {"name": "alpha", "active": True, "dashboard": {"label": "Alpha"}, "selfcheck": [LIST]},
    {"name": "beta", "active": True, "dashboard": {"label": "Beta"}, "selfcheck": [RUNNER]},
    {"name": "gamma", "active": True},
    {"name": "delta", "active": True, "page": {"path": "/"}},
    # a tab that frames its own page server (Insights, Usage): it has no view command (ORCH-1582)
    {"name": "epsilon", "active": True, "dashboard": {"label": "Epsilon"}, "page": {"path": "/"}},
    {"name": "omega", "active": False, "dashboard": {"label": "Omega"}, "selfcheck": [LIST]},
]


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    h = tmp_path / "orchhome"
    h.mkdir()
    monkeypatch.setattr(addons, "home", lambda: h)


class Fake:
    """A stand-in for the newly installed orch: answers per command, records what was asked."""

    def __init__(self, broken=()):
        self.broken, self.asked = set(broken), []

    def __call__(self, argv, root):
        self.asked.append(argv)
        key = " ".join(argv)
        if any(key.startswith(b) for b in self.broken):
            return 1, "Traceback (most recent call last):"
        if argv[:2] == ["addon", "list"]:
            return 0, json.dumps(ADDONS)
        if argv == ["epsilon", "view", "--json"]:
            return 2, ""  # like `orch insights view`: no such command
        if argv[1:] in (["list", "--json"], ["view", "--json"]):
            return 0, "{}"
        return 0, ""


def no_servers(root):
    return []


def test_every_check_passes_on_a_healthy_install(tmp_path):
    fake = Fake()
    got = selfcheck.run_checks(tmp_path, fake, no_servers)
    assert [r["name"] for r in got] == [
        "Factory list",
        "Merge queue runner",
        "alpha page",
        "beta page",
        "delta page",
        "epsilon page",
    ]
    assert all(r["ok"] for r in got)
    assert ["epsilon", "--help"] in fake.asked  # a tab with its own page server: no view is pulled
    assert ["alpha", "list", "--json"] in fake.asked and ["beta", "queue", "check"] in fake.asked
    assert not any(a[0] == "omega" for a in fake.asked)  # an add-on that is off is not probed
    assert ["delta", "--help"] in fake.asked  # a page without a dashboard tab: its command loads


def test_a_seeded_fault_is_found_with_the_words_the_add_on_gave(tmp_path):
    got = selfcheck.run_checks(tmp_path, Fake(broken=["alpha"]), no_servers)
    bad = {r["name"]: r["why"] for r in got if not r["ok"]}
    assert bad == {
        "Factory list": "the Factory list does not open",
        "alpha page": "the alpha page does not answer",
    }


def test_a_declared_check_that_ends_badly_fails(tmp_path):
    got = {r["name"]: r for r in selfcheck.run_checks(tmp_path, Fake(broken=["beta queue"]), no_servers)}
    assert got["Merge queue runner"]["why"] == "the runner is not running"


def test_json_asked_for_must_be_json(tmp_path):
    class NoJson(Fake):
        def __call__(self, argv, root):
            return (0, "oops") if argv == ["alpha", "list", "--json"] else super().__call__(argv, root)

    got = {r["name"]: r for r in selfcheck.run_checks(tmp_path, NoJson(), no_servers)}
    assert not got["Factory list"]["ok"]


def test_no_add_on_list_is_one_failed_check(tmp_path):
    got = selfcheck.run_checks(tmp_path, Fake(broken=["addon list"]), no_servers)
    assert got == [{"name": "add-ons", "ok": False, "why": "the add-on list does not open"}]


def test_each_running_page_server_is_signed_in_to(tmp_path):
    seen = []

    def signs_in(root, server, base):
        seen.append((server, base))
        return None if server == "alpha" else f"{server} sign-in failed (answer 403)"

    two = [("alpha", "http://127.0.0.1:1"), ("beta", "http://127.0.0.1:2")]
    got = {r["name"]: r for r in selfcheck.run_checks(tmp_path, Fake(), lambda r: two, signs_in)}
    assert seen == two
    assert got["Alpha sign-in"]["ok"] and got["Beta sign-in"]["why"] == "beta sign-in failed (answer 403)"


def test_failure_after_a_newer_release_keeps_the_go_back_card(tmp_path):
    lines = selfcheck.after_update(tmp_path, 32, 33, Fake(broken=["alpha list"]), no_servers)
    assert lines[0] == "Self-check after the update found a problem:"
    assert "  - the Factory list does not open" in lines
    assert lines[-1] == "Go back to release 32 with: orch update --to 32"
    c = selfcheck.card()
    assert c["back_to"] == 32 and c["release"] == 33
    assert c["failed"] == [{"name": "Factory list", "why": "the Factory list does not open"}]
    # the next update passes: the card goes away
    assert selfcheck.after_update(tmp_path, 32, 33, Fake(), no_servers) == [
        "Self-check: all 6 checks passed."
    ]
    assert selfcheck.card() is None


@pytest.mark.parametrize(("old", "new"), [(33, 32), (None, 33), (33, None), (33, 33)])
def test_no_go_back_offer_unless_the_update_moved_forward(tmp_path, old, new):
    lines = selfcheck.after_update(tmp_path, old, new, Fake(broken=["alpha list"]), no_servers)
    assert not any("Go back" in x for x in lines)
    assert selfcheck.card()["back_to"] is None


def test_a_broken_check_never_breaks_the_update(tmp_path):
    def boom(argv, root):
        raise RuntimeError("bad")

    lines = selfcheck.after_update(tmp_path, 32, 33, boom, no_servers)
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


def test_a_page_server_lets_a_person_in(monkeypatch, tmp_path):
    monkeypatch.setattr(selfcheck.time, "sleep", lambda s: None)
    calls = []

    def http(url, body=None, origin=None):
        calls.append((url, body, origin))
        return 200

    base = "http://127.0.0.1:8770"
    hand_over = lambda r, s, b, h: h(f"{b}/session", {"token": "t"}, b)  # noqa: E731
    assert selfcheck._signs_in(tmp_path, "alpha", base, http, hand_over) is None
    assert calls[-1] == (f"{base}/session", {"token": "t"}, base)
    assert (
        selfcheck._signs_in(tmp_path, "alpha", base, http, lambda *a: 403)
        == "alpha sign-in failed (answer 403)"
    )
    assert (
        selfcheck._signs_in(tmp_path, "alpha", base, http, lambda *a: -1) is None
    )  # a helper: the page answers
    dead = selfcheck._signs_in(tmp_path, "alpha", base, lambda *a, **k: 0, lambda *a: 200)
    assert dead == "the alpha page does not answer"


def test_a_helper_never_signs_in_as_the_person(monkeypatch, tmp_path):
    from orch import pagelaunch, tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: False)
    monkeypatch.setattr(
        pagelaunch, "write_launch_token", lambda *a: pytest.fail("a token was made for a helper")
    )
    assert selfcheck._sign_in(tmp_path, "alpha", "http://127.0.0.1:1", lambda *a: 200) == -1


def test_the_probe_runs_orch_isolated(monkeypatch, tmp_path):
    seen = {}

    class Done:
        returncode, stdout = 0, "[]"

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return Done()

    monkeypatch.setattr(selfcheck.subprocess, "run", fake_run)
    assert selfcheck.run_orch(["addon", "list", "--json"], tmp_path) == (0, "[]")
    assert seen["argv"][1:5] == ["-I", "-P", "-m", "orch"]


def test_update_runs_the_check_after_the_restart():
    """addons.update (the project step) calls the check with the release before and after."""
    import inspect

    src = inspect.getsource(addons.update)
    assert src.index("_restart_updated(root)") < src.index(
        'selfcheck.after_update(root, before.get("release"), new_release)'
    )


@pytest.mark.parametrize(
    ("entry", "ok"),
    [
        ({"label": "List", "fails": "the list does not open", "args": ["list", "--json"]}, True),
        ({"label": "List", "fails": "x", "args": []}, False),
        ({"label": "List", "fails": "x", "args": ["-c", "rm"]}, False),
        ({"label": "List", "fails": "x", "args": ["list; rm"]}, False),
        ({"label": "List", "args": ["list"]}, False),
        ({"label": "List", "fails": "x", "args": ["list"], "run": "sh"}, False),
    ],
)
def test_the_manifest_entry_is_checked(entry, ok):
    m = {"selfcheck": [entry]}
    if ok:
        addons._check_selfcheck(m)
        assert m["selfcheck"] == [entry]
    else:
        with pytest.raises(Refused):
            addons._check_selfcheck(m)


def test_none_declared_is_fine():
    m = {}
    addons._check_selfcheck(m)
    assert m["selfcheck"] == []


def test_the_sign_in_post_is_same_origin_like_the_page(tmp_path):
    """ORCH-1582: Insights refuses a POST /session without Sec-Fetch-Site (403); the self-check sends what the
    page's own fetch sends, and a plain GET stays a plain GET."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen = []

    class H(BaseHTTPRequestHandler):
        def _answer(self):
            site = self.headers.get("Sec-Fetch-Site")
            seen.append((self.command, site))
            ok = self.command == "GET" or site in ("same-origin", "none")
            self.send_response(200 if ok else 403)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = _answer

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        assert selfcheck._http(f"{base}/session", {"token": "t"}, base) == 200
        assert selfcheck._http(f"{base}/") == 200
    finally:
        srv.shutdown()
        srv.server_close()
    assert seen == [("POST", "same-origin"), ("GET", None)]


@pytest.mark.parametrize("up", [True, False])
def test_a_running_page_server_must_answer_on_its_page(tmp_path, up):
    """ORCH-1582: Usage is no sign-in server, so its page check asks its running server for its page; a page
    server that is not running here (it starts when opened) only needs its command to load."""
    asked = []

    def answers(url, page=False):
        asked.append(url)
        assert page  # a page must open (200), not only answer
        return up

    fake = Fake()
    got = {
        r["name"]: r
        for r in selfcheck.run_checks(
            tmp_path, fake, no_servers, pages=lambda r: {"epsilon": "http://127.0.0.1:9"}, answers=answers
        )
    }
    assert asked == ["http://127.0.0.1:9/"]
    assert got["epsilon page"]["ok"] is up
    assert up or got["epsilon page"]["why"] == "the epsilon page does not answer"
    assert ["epsilon", "--help"] not in fake.asked and ["epsilon", "view", "--json"] not in fake.asked
    assert ["delta", "--help"] in fake.asked  # not running here: its command loads


def test_a_page_must_open_not_only_answer(monkeypatch):
    """A broken Usage page answers 403: a page check wants 200; the sign-in wait takes any below 500."""
    monkeypatch.setattr(selfcheck.time, "sleep", lambda s: None)
    assert not selfcheck._answers("http://127.0.0.1:9/", lambda u: 403, page=True)
    assert selfcheck._answers("http://127.0.0.1:9/", lambda u: 200, page=True)
    assert selfcheck._answers("http://127.0.0.1:9/", lambda u: 403)
    assert not selfcheck._answers("http://127.0.0.1:9/", lambda u: 0)

"""The daily look's decisions, with the browser and orch replaced (no browser, no orch needed)."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import REPO

from orch_dashboard_tester import browser, cli, daily, words

PKG = Path(daily.__file__).parent


class FakeWorld:
    def __init__(self, findings=(), tickets=(), version="29", refs=None, addons=(), error=None):
        self.findings, self._tickets, self._version = list(findings), list(tickets), version
        self.refs = list(refs or [])
        self._addons, self.error = list(addons), error
        self.sent, self.helpers, self.routes = [], [], None

    def tickets(self):
        return self._tickets

    def addons(self):
        return self._addons

    def version(self):
        return self._version

    def browse(self, routes):
        self.routes = routes
        if self.error:
            raise self.error
        return {"findings": self.findings, "timings": []}

    def send(self, rep):
        self.sent.append(rep)
        return (self.refs.pop(0) if self.refs else "r-1117-0999-ws", "orch report problem")

    def start_helper(self, parent, version):
        self.helpers.append((parent, version))
        return "t_help01"


BIG = {"key": "pageerror|#home|x", "severity": "big", "text": "#home: page error x", "route": "#home",
       "viewport": "desktop", "shot": "/s/a.png"}  # fmt: skip
SMALL1 = {"key": "slow|#tickets|phone", "severity": "small", "text": "#tickets took 7.0 s", "route": "#tickets",
          "viewport": "phone", "shot": "/s/b.png"}  # fmt: skip
SMALL2 = {"key": "hscroll|#chat", "severity": "small", "text": "#chat scrolls sideways", "route": "#chat",
          "viewport": "phone", "shot": "/s/c.png"}  # fmt: skip


def ticket(ref, status, tid="t_aaaaaa", key="DM1-200"):
    return {"id": tid, "key": key, "title": f"Investigate orch report {ref}", "status": status,
            "updated_at": "2026-11-17T00:00:00Z"}  # fmt: skip


def reported(key=SMALL1["key"], status="reported", **more):
    return {"findings": {key: {"text": "t", "ref": "r-1117-0001-ws", "status": status, **more}}}


def test_big_alone_smalls_together():
    w = FakeWorld([BIG, SMALL1, SMALL2], refs=["r-1117-0300-ws", "r-1117-0301-ws"])
    state = {}
    s = daily.run_pass(w, state, "t_role01")
    assert len(w.sent) == 2
    assert w.sent[0]["keys"] == [BIG["key"]] and w.sent[0]["pictures"] == ["/s/a.png"]
    assert sorted(w.sent[1]["keys"]) == sorted([SMALL1["key"], SMALL2["key"]])
    assert len(w.sent[1]["what"]) <= 600
    assert state["findings"][SMALL2["key"]]["ref"] == "r-1117-0301-ws"
    assert len(s["new"]) == 3 and not w.helpers


def test_nothing_new_sends_nothing():
    state = reported()
    w = FakeWorld([SMALL1], tickets=[ticket("r-1117-0001-ws", "active")])
    s = daily.run_pass(w, state, "t_role01")
    assert w.sent == [] and s["waiting"] == ["t"]
    assert state["findings"][SMALL1["key"]]["ticket_key"] == "DM1-200"


def test_fixed_finding_checked_again_and_marked_fixed():
    state = reported()
    s = daily.run_pass(FakeWorld([], tickets=[ticket("r-1117-0001-ws", "review")]), state, None)
    assert state["findings"][SMALL1["key"]]["status"] == "fixed" and s["fixed"] == ["t"]


def test_still_there_after_fix_is_reported_again():
    state = reported()
    w = FakeWorld([SMALL1], tickets=[ticket("r-1117-0001-ws", "done")], refs=["r-1117-0002-ws"])
    s = daily.run_pass(w, state, None)
    assert len(w.sent) == 1 and "Still there after DM1-200" in w.sent[0]["what"]
    f = state["findings"][SMALL1["key"]]
    assert f["ref"] == "r-1117-0002-ws" and f["status"] == "reported" and s["back"]


def test_fixed_finding_that_comes_back_is_reported():
    state = reported(status="fixed", ticket_key="DM1-200")
    w = FakeWorld([SMALL1], tickets=[ticket("r-1117-0001-ws", "done")], refs=["r-1117-0003-ws"])
    daily.run_pass(w, state, None)
    assert len(w.sent) == 1 and state["findings"][SMALL1["key"]]["ref"] == "r-1117-0003-ws"


def test_reported_finding_with_open_ticket_not_reported_twice():
    state = reported(key=BIG["key"])
    w = FakeWorld([BIG], tickets=[ticket("r-1117-0001-ws", "active")])
    daily.run_pass(w, state, None)
    assert w.sent == []


def test_at_most_three_reports():
    bigs = [dict(BIG, key=f"pageerror|#p{i}|x", text=f"e{i}") for i in range(5)]
    w = FakeWorld(bigs)
    state = {}
    daily.run_pass(w, state, None)
    assert len(w.sent) == 3 and len(state["findings"]) == 3  # the other two are new again next pass


def test_failed_report_is_tried_again_next_time():
    class NoRef(FakeWorld):
        def send(self, rep):
            self.sent.append(rep)
            return (None, "the report failed: x")

    state = {}
    s = daily.run_pass(NoRef([SMALL1]), state, None)
    assert state["findings"] == {} and s["reports"][0]["ref"] is None
    w = FakeWorld([SMALL1])
    daily.run_pass(w, state, None)
    assert len(w.sent) == 1


def test_helper_only_when_asked_and_on_a_new_release():
    state = {"helper_version": "29"}
    w = FakeWorld([], version="30")
    daily.run_pass(w, state, "t_role01")
    assert w.helpers == []  # not asked for
    w = FakeWorld([], version="29")
    daily.run_pass(w, state, "t_role01", helper_each_release=True)
    assert w.helpers == []
    w = FakeWorld([], version="30")
    s = daily.run_pass(w, state, "t_role01", helper_each_release=True)
    assert w.helpers == [("t_role01", "30")] and state["helper_version"] == "30" and "30" in s["helper"]


def test_dropped_ticket_closes_finding():
    state = reported()
    daily.run_pass(FakeWorld([], tickets=[ticket("r-1117-0001-ws", "dropped")]), state, None)
    assert state["findings"][SMALL1["key"]]["status"] == "dropped"


def test_finding_named_in_an_open_ticket_is_not_reported():
    t = {"id": "t_bbbbbb", "key": "DM1-300", "title": "Phone page too wide", "status": "active",
         "note": "What happened: #chat scrolls sideways at 390 px"}  # fmt: skip
    w = FakeWorld([SMALL2], tickets=[t])
    state = {}
    s = daily.run_pass(w, state, None)
    assert w.sent == [] and s["has_ticket"] == [SMALL2["text"]] and SMALL2["key"] not in state["findings"]


def test_finished_ticket_text_does_not_block_a_report():
    t = {"id": "t_bbbbbb", "key": "DM1-300", "title": "x", "status": "done", "note": "#chat scrolls sideways"}
    w = FakeWorld([SMALL2], tickets=[t])
    daily.run_pass(w, {}, None)
    assert len(w.sent) == 1


def test_sign_in_refused_is_said_and_nothing_sent():
    state = reported()
    w = FakeWorld([SMALL1], error=daily.Refused("Could not sign in to the dashboard."))
    s = daily.run_pass(w, state, None)
    assert (
        w.sent == [] and "sign in" in s["error"] and state["findings"][SMALL1["key"]]["status"] == "reported"
    )
    assert "sign in" in daily.note_text(s)


def test_routes_follow_this_workspace():
    addons = [
        {"name": "automation", "active": True, "dashboard": {"label": "Automation"}},
        {"name": "lessons", "active": True, "dashboard": {"place": "settings"}},
        {"name": "focus", "active": True, "page": {"path": "/"}},
        {"name": "pull-requests", "active": True},  # no tab, no page
        {"name": "sync", "active": False, "dashboard": {"label": "Sync"}},
        {"name": "Bad Name", "dashboard": {}},
    ]
    ts = [dict(ticket("a", "active", "t_old111"), updated_at="1"),
          dict(ticket("b", "active", "t_new222"), updated_at="2"),
          dict(ticket("c", "review", "t_rev333"), updated_at="1")]  # fmt: skip
    assert daily.routes_for(addons, ts) == [*daily.CORE_ROUTES, "#addon/automation", "#settings/addons/lessons",
                                            "#addon/focus", "#ticket/t_new222", "#ticket/t_rev333"]  # fmt: skip


def test_shared_copy_ref_suffix_maps():
    assert daily.ref_of("Investigate orch report r-1116-2217-ws-2 (shared)") == "r-1116-2217-ws-2"


def test_note_text_plain():
    s = {"at": "2026-11-17T03:00:00Z", "found": 0, "new": [], "fixed": ["a"], "back": [], "waiting": [],
         "reports": [], "has_ticket": []}  # fmt: skip
    assert "Fixed and checked again: a" in daily.note_text(s)


def test_report_goes_through_the_command_line_unshared(monkeypatch, tmp_path):
    calls = []
    pic = tmp_path / "a.png"
    pic.write_bytes(b"x")
    monkeypatch.setattr(
        daily, "orch",
        lambda root, args, timeout=120: calls.append(args)
        or subprocess.CompletedProcess(args, 0, '{"ref": "r-1117-0400-ws"}', ""),
    )  # fmt: skip
    w = daily.World(tmp_path, tmp_path)
    ref, how = w.send(
        {"what": "w", "expected": "e", "more": "m", "pictures": [str(pic), "/gone.png"], "keys": []}
    )
    assert ref == "r-1117-0400-ws" and how == "orch report problem"
    a = calls[0]
    assert a[:2] == ["report", "problem"] and "--no-send" in a and a.count("--file") == 1


def test_sign_in_link_is_never_shown(monkeypatch, tmp_path):
    out = json.dumps({"launch": [{"addon": "focus", "url": "http://x/#launch=f"},
                                 {"addon": "dashboard", "url": "http://127.0.0.1:9/#launch=SECRET"}]})  # fmt: skip
    monkeypatch.setattr(
        daily, "orch", lambda root, args, timeout=120: subprocess.CompletedProcess(args, 0, out, "")
    )
    assert daily.World(tmp_path, tmp_path).launch_url().endswith("#launch=SECRET")
    assert (
        browser.redact("http://127.0.0.1:9/#launch=SECRET x /go/abc", "http://127.0.0.1:9")
        == "/#launch=XXX x /go/XXX"
    )
    monkeypatch.setattr(
        daily,
        "orch",
        lambda root, args, timeout=120: subprocess.CompletedProcess(args, 2, "", "Only a person"),
    )
    with pytest.raises(daily.Refused, match="Only a person"):
        daily.World(tmp_path, tmp_path).launch_url()


def test_page_findings():
    vp = browser.VIEWPORTS[2]
    pr = {"textLen": 500, "hscroll": 30, "cut": ["Save"], "words": ['Bot in "Bot"'], "leaks": ["x: null"]}
    kinds = sorted(f["kind"] for f in browser.findings_for("#home", vp, 7000, pr, "/s.png"))
    assert kinds == ["layout", "layout", "slow", "word", "word"]
    assert [f["kind"] for f in browser.findings_for("#home", vp, -1, None, "/s.png")] == ["empty"]
    e = browser.error_finding({"route": "#home", "kind": "http", "text": "502 GET /api/x"}, vp, Path("/s"))
    assert e["severity"] == "big" and e["key"] == "http|#home|# GET /api/x"


def test_browser_half_never_clicks():
    code = "\n".join(
        x for x in (PKG / "browser.py").read_text().splitlines() if not x.lstrip().startswith(("#", "//"))
    )
    for bad in (".click(", ".tap(", ".check(", "dispatchEvent", ".press(", ".fill(", "set_input_files", ".type(",
                "keyboard", "mouse", ".submit("):  # fmt: skip
        assert bad not in code, bad


def test_never_words_match_the_wording_doc():
    doc = REPO / "docs" / "wording.md"
    if not doc.is_file():
        pytest.skip("no docs folder")
    assert words.load() == words.parse(doc.read_text(encoding="utf-8")), (
        "never_words.json is out of date: python -m orch_dashboard_tester.words docs/wording.md"
    )
    assert "Bot" in words.load()


def test_manifest_and_skill():
    m = tomllib.loads((PKG / "orch-addon.toml").read_text())
    assert m["name"] == "dashboard-tester" and m["requires"] == ["dashboard", "automation"]
    assert (PKG / m["skill"] / "SKILL.md").is_file() and (PKG / m["agents_block"]).is_file()
    skill = (PKG / m["skill"] / "SKILL.md").read_text()
    assert re.search(r"never clicks", skill)


def test_run_dry_keeps_nothing(monkeypatch, tmp_path, capsys):
    (tmp_path / ".orch").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    monkeypatch.setattr(daily, "World", lambda root, out, dry=False: FakeWorld([SMALL1]))
    assert cli.main(["run", "--dry-run", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["new"] == [SMALL1["text"]] and len(data["would_send"]) == 1
    sp = daily.space(tmp_path)
    assert not (sp / "state.json").exists() and list(sp.iterdir()) == []


def test_run_keeps_state_and_newest_pictures(monkeypatch, tmp_path, capsys):
    (tmp_path / ".orch").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    notes = []

    class W(FakeWorld):
        def __init__(self, out):
            super().__init__([SMALL1])
            self.out = out

        def browse(self, routes):
            (self.out / "shots").mkdir()
            (self.out / "shots" / "a.png").write_bytes(b"x")
            return super().browse(routes)

        def note(self, ticket, text):
            notes.append((ticket, text))

    monkeypatch.setattr(daily, "World", lambda root, out, dry=False: W(out))
    monkeypatch.setenv("ORCH_TICKET", "t_role01")
    assert cli.main(["run"]) == 0
    sp = daily.space(tmp_path)
    assert (sp / "last" / "shots" / "a.png").is_file() and not (sp / "next").exists()
    assert json.loads((sp / "state.json").read_text())["findings"][SMALL1["key"]]["status"] == "reported"
    assert notes and notes[0][0] == "t_role01"
    assert cli.main(["status", "--json"]) == 0
    capsys.readouterr()


def test_setup_time_is_checked():
    with pytest.raises(daily.Refused):
        cli._repeat_text("6:30pm")
    assert cli._repeat_text("06:30") == "daily 06:30"


def test_cli_help_runs():
    r = subprocess.run(
        [sys.executable, "-m", "orch_dashboard_tester", "--help"], check=False, capture_output=True, text=True
    )
    assert r.returncode == 0 and "setup" in r.stdout


def test_null_in_a_ticket_title_is_not_a_program_value():
    leak = {"key": "leak|#tickets|WS-2 Fix the null check", "severity": "small", "kind": "word",
            "text": '#tickets: program value on screen: "WS-2 Fix the null check in export"', "route": "#tickets"}  # fmt: skip
    real = dict(leak, key="leak|#home|x", text='#home: program value on screen: "Due: undefined"')
    t = {"id": "t_cccccc", "title": "Fix the null check in export", "status": "active"}
    w = FakeWorld([leak, real], tickets=[t])
    s = daily.run_pass(w, {}, None)
    assert s["found"] == 1 and s["new"] == [real["text"]]


def test_never_word_in_a_ticket_title_is_not_reported():
    f = {"key": "word|#ticket/t_cccccc|Bot", "severity": "small", "kind": "word", "route": "#ticket/t_cccccc",
         "text": '#ticket/t_cccccc: word from the never-list on screen: Bot in "Bot setup for the shop"'}  # fmt: skip
    w = FakeWorld([f], tickets=[{"id": "t_cccccc", "title": "Bot setup for the shop", "status": "active"}])
    assert daily.run_pass(w, {}, None)["found"] == 0 and w.sent == []


def test_long_title_cut_on_screen_is_still_a_persons_words():
    title = "Bot setup for the shop and the newsletter and the weekly report for the team"
    f = {"key": "word|#ticket/t_cccccc|Bot", "severity": "small", "kind": "word", "route": "#ticket/t_cccccc",
         "text": f'#ticket/t_cccccc: word from the never-list on screen: Bot in "{title[:60]}"'}  # fmt: skip
    assert daily.person_words(f, [title])
    assert not daily.person_words(dict(f, text='x: Bot in "Bot"'), [title])


def test_settings_pages_keep_no_text_and_no_report_picture():
    assert not browser.keep_text("#settings", "Logins and keys")
    assert not browser.keep_text("#settings/addons/lessons", "x")
    assert browser.keep_text("#home", "What needs you: 2 tickets")
    assert not browser.keep_text("#home", "token = ghp_" + "a" * 36)  # orch's secret scan finds it
    big = dict(BIG, route="#settings", key="pageerror|#settings|x", shot="/s/set.png")
    small = dict(SMALL1, route="#settings/agent", key="slow|#settings/agent|phone", shot="/s/set2.png")
    reps = daily.build_reports([big, small, SMALL2], [])
    assert reps[0]["pictures"] == [] and reps[1]["pictures"] == ["/s/c.png"]


def test_version_name_keeps_the_whole_build_name():
    assert daily.version_name("orch 3.x (release build)\n") == "3.x (release build)"
    assert daily.version_name("orch 16\n") == "16"
    assert (
        daily.version_name("orch develop 0af5d58e (development build)")
        == "develop 0af5d58e (development build)"
    )
    assert daily.version_name("") == ""


def test_look_falls_back_to_this_computers_own_address():
    # report r-1119-0642-ws: the private-network name did not answer while the dashboard was fine on 127.0.0.1
    url = "http://develop.example:8790/go/SECRET"
    seen = []

    def only_local(host, port):
        seen.append((host, port))
        return host == "127.0.0.1"

    assert browser.reachable_url(url, only_local) == "http://127.0.0.1:8790/go/SECRET"
    assert seen == [("develop.example", 8790), ("127.0.0.1", 8790)]
    assert browser.reachable_url(url, lambda h, p: True) == url
    with pytest.raises(browser.Unreachable, match="could not be reached") as e:
        browser.reachable_url(url, lambda h, p: False)
    assert "SECRET" not in str(e.value)
    with pytest.raises(browser.Unreachable):  # https keeps its own name
        browser.reachable_url("https://develop.example:8790/go/SECRET", only_local)


class GotoError(Exception):
    pass


class FakePage:
    def __init__(self, error):
        self.error = error

    def goto(self, url, **kw):
        raise GotoError(self.error)


def test_no_connection_is_unreachable_but_a_slow_page_is_not():
    up, down = (lambda h, p: True), (lambda h, p: False)
    with pytest.raises(browser.Unreachable):
        browser._goto(
            FakePage("Page.goto: net::ERR_CONNECTION_TIMED_OUT at http://x:1/"), "http://x:1/#a", 1, up
        )
    with pytest.raises(
        browser.Unreachable, match="x:1"
    ):  # the browser's own wait ran out, the port is silent
        browser._goto(FakePage("Page.goto: Timeout 30000ms exceeded."), "http://x:1/#home", 1, down)
    browser._goto(FakePage("Page.goto: Timeout 30000ms exceeded."), "http://x:1/#home", 1, up)  # only slow


def test_unreachable_dashboard_is_one_line_and_no_page_is_reported(monkeypatch, tmp_path):
    def gone(*a, **kw):
        raise browser.Unreachable(browser.UNREACHABLE.format(where="x:1"))

    monkeypatch.setattr(daily.World, "launch_url", lambda self: "http://x:1/go/SECRET")
    monkeypatch.setattr(browser, "look", gone)
    with pytest.raises(daily.Refused, match="could not be reached"):
        daily.World(tmp_path, tmp_path).browse(["#addon/services"])
    state = reported()
    w = FakeWorld([SMALL1], error=daily.Refused(browser.UNREACHABLE.format(where="x:1")))
    s = daily.run_pass(w, state, None)
    assert w.sent == [] and "could not be reached" in s["error"]

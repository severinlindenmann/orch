"""Take over and give back (ORCH-1495) with the real broker and headless browser: the helper waits and is told to
look again, only the holder's page types, stale input is dropped, held keys are let go, password fields are
emptied, a lost page pauses, Cancel stops the helper's step, ask-person, and the typed secret is in no file."""

import json
import threading
import time
from multiprocessing.connection import Client
from pathlib import Path

import pytest
from conftest import browser_ready
from world import World

from orch_browse import channel, cli, paths, takeover

pytestmark = pytest.mark.skipif(not browser_ready(), reason="the pinned browser is not downloaded")

TID = "t_abc123"
SECRET = "ZQX-secret-marker-7f3a91"


@pytest.fixture
def world(ws, monkeypatch):
    w = World()
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    monkeypatch.setenv("ORCH_BROWSE_TEST_MAP", w.env_map())
    monkeypatch.setenv("ORCH_BROWSE_ASK_SECONDS", "4")
    paths.save_sites(ws, TID, ["site.test"])
    yield w
    cli.main(["close", "--ticket", TID])
    w.stop()


def run(capsys, *argv):
    code = cli.main([*argv, "--ticket", TID])
    return code, capsys.readouterr().out


class Watch:
    """A watcher; person=True is the dashboard's stream of a person's page (the broker mints its page id)."""

    def __init__(self, run_dir, person=True, args=None):
        self.msgs: list[dict] = []
        self.quit = False
        self.page = None
        sent = args if args is not None else (["person"] if person else [])
        self.t = threading.Thread(target=self._go, args=(run_dir, sent), daemon=True)
        self.t.start()

    def _go(self, run_dir, sent):
        # its own connection (as channel.watch), so the test can close it at any moment: a page that goes away
        info = json.loads((run_dir / "channel.json").read_text(encoding="utf-8"))
        c = Client(info["address"], family=info["family"], authkey=bytes.fromhex(info["key"]))
        try:
            c.send_bytes(json.dumps({"cmd": "watch", "args": sent}).encode())
            while not self.quit:
                if not c.poll(0.1):
                    continue
                try:
                    m = json.loads(c.recv_bytes(channel.MSG_MAX * 4))
                except (OSError, EOFError):
                    return
                if m.get("type") == "hello":
                    self.page = m.get("page")
                if m.get("type") != "frame":
                    self.msgs.append(m)
                else:
                    self.frame = m
                if m.get("type") == "end":
                    return
        finally:
            c.close()

    def control(self, pred=lambda c: True, secs=20):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            for m in reversed(list(self.msgs)):
                if m.get("type") == "control":
                    if pred(m):
                        return m
                    break
            time.sleep(0.05)
        return None

    def wait_frame(self, secs=20):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            if getattr(self, "frame", None):
                return self.frame
            time.sleep(0.05)
        return None


class Helper:
    """One helper command in the background (it may wait for a person)."""

    def __init__(self, run_dir, cmd, args=()):
        self.r = None
        self.t = threading.Thread(target=self._go, args=(run_dir, cmd, list(args)), daemon=True)
        self.t.start()

    def _go(self, run_dir, cmd, args):
        self.r = channel.call(run_dir, cmd, args, timeout=120)

    def done(self, secs):
        self.t.join(secs)
        return not self.t.is_alive()


def person(run_dir, cmd, *args):
    r = channel.person(run_dir, cmd, [str(a) for a in args])
    assert r is not None
    return r["ok"], (json.loads(r["out"]) if r["ok"] else r["out"])


def setup_take(ws, capsys, address="http://site.test/signin"):
    code, out = run(capsys, "open", address)
    assert code == 0, out
    d = paths.run_dir(ws, TID)
    w = Watch(d)
    assert w.wait_frame() is not None
    hello = next(m for m in w.msgs if m.get("type") == "hello")
    c = w.control()
    assert c["state"] == "helper" and not c["mine"]
    return d, w, hello["generation"], c["epoch"]


def take(d, w, gen, epoch):
    ok, snap = person(d, "take", gen, w.page, epoch, "take")
    assert ok, snap
    c = w.control(lambda c: c["state"] == "person" and c["mine"])
    assert c is not None, "the take-over never reached the person"
    return c["epoch"]


def click(x, y):
    return [
        {"t": "down", "x": x, "y": y, "button": "left", "count": 1},
        {"t": "up", "x": x, "y": y, "button": "left"},
    ]


def send(d, gen, page, epoch, frame, events):
    payload = json.dumps({"w": frame["w"], "h": frame["h"], "events": events})
    return person(d, "input", gen, page, epoch, payload)


def test_take_type_give_back_and_the_helper_looks_again(world, ws, capsys):
    d, a, gen, epoch = setup_take(ws, capsys)
    b = Watch(d)  # a second page of the same person: watches, may not type
    assert b.wait_frame() is not None
    epoch = take(d, a, gen, epoch)
    assert b.control(lambda c: c["state"] == "person" and not c["mine"]) is not None
    frame = a.wait_frame()
    assert frame["w"] == 1280 and frame["h"] == 800

    helper = Helper(d, "look")  # the helper's command waits while the person drives
    assert not helper.done(2), "the helper read the page while a person drove"

    ok, out = send(d, gen, a.page, epoch, frame, [*click(250, 120), {"t": "text", "text": "nina"}])
    assert ok and out["sent"] == 3, out
    ok, out = send(d, gen, a.page, epoch, frame, [*click(250, 220), {"t": "paste", "text": SECRET}])
    assert ok, out
    # only the holder's page; a stale epoch; outside the picture; a wrong picture size; an unknown key
    ok, why = send(d, gen, b.page, epoch, frame, click(250, 120))
    assert not ok and "Another page" in why
    ok, why = send(d, gen, a.page, epoch - 1, frame, click(250, 120))
    assert not ok and "changed hands" in why
    ok, why = send(d, gen, a.page, epoch, frame, click(1280, 120))
    assert not ok and "outside" in why
    ok, why = send(d, gen, a.page, epoch, {"w": 640, "h": 400}, click(10, 10))
    assert not ok and "picture changed" in why
    ok, why = send(d, gen, a.page, epoch, frame, [{"t": "key", "type": "down", "key": "F5"}])
    assert not ok
    ok, why = send(d, "0" * 16, a.page, epoch, frame, click(250, 120))
    assert not ok and "already ended" in why
    ok, why = send(d, gen, "pageZ", epoch, frame, click(250, 120))
    assert not ok and "not watching" in why
    # a key and a button held down when the person gives back are let go
    ok, out = send(
        d,
        gen,
        a.page,
        epoch,
        frame,
        [
            {"t": "key", "type": "down", "key": "ArrowDown"},
            {"t": "down", "x": 600, "y": 600, "button": "left", "count": 1},
        ],
    )
    assert ok, out

    ok, why = person(d, "give", gen, b.page, epoch)
    assert not ok and "Another page" in why
    ok, out = person(d, "give", gen, a.page, epoch)
    assert ok and out["state"] == "helper", out
    assert "fresh page (site.test)." in out["text"] and "orch kept nothing you typed" in out["text"]
    assert "/signin" not in out["text"]
    assert helper.done(20)
    assert helper.r["ok"]
    said = helper.r["out"]
    assert said.startswith("A person used the browser from ") and "nothing typed was kept by orch" in said
    assert takeover.LOOK_AGAIN in said and "Page:" not in said  # not replayed: no page in the answer

    # input after the give back is dropped
    ok, why = send(d, gen, a.page, epoch, frame, click(250, 120))
    assert not ok

    code, out = run(capsys, "look")
    assert code == 0
    # a fresh page at the site's origin only (never the path): nothing the person typed is on it
    assert "(http://site.test/)" in out and "Test site" in out, out
    assert "A person used" not in out  # said once
    assert SECRET not in out
    assert world.leaks() == []
    run(capsys, "close")
    time.sleep(0.5)
    # the secret is in no file the run wrote (logs, state, network log, pictures), nor anywhere in the workspace
    for f in Path(ws).rglob("*"):
        if f.is_file():
            assert SECRET.encode() not in f.read_bytes(), f"the typed secret is in {f}"


def test_a_lost_page_pauses_until_someone_gives_back(world, ws, capsys):
    d, a, gen, epoch = setup_take(ws, capsys)
    b = Watch(d)
    assert b.wait_frame() is not None
    epoch = take(d, a, gen, epoch)
    frame = a.wait_frame()
    helper = Helper(d, "read")
    a.quit = True  # page A goes away (closed, reloaded, signed out)
    c = b.control(lambda c: c["state"] == "paused", secs=10)
    assert c is not None, "a lost page did not pause"
    assert not helper.done(3), "the helper went on by itself after the page was lost"
    ok, _why = send(d, gen, a.page, epoch, frame, click(250, 120))
    assert not ok
    # page B takes over again from the pause, then gives back
    ok, snap = person(d, "take", gen, b.page, c["epoch"], "take")
    assert ok and snap["state"] == "person" and snap["mine"]
    ok, out = person(d, "give", gen, b.page, snap["epoch"])
    assert ok and out["state"] == "helper"
    assert helper.done(20) and takeover.LOOK_AGAIN in helper.r["out"]


def test_take_over_waits_for_the_running_step(world, ws, capsys):
    d, a, gen, epoch = setup_take(ws, capsys)
    helper = Helper(d, "go", ["http://site.test/slow"])
    time.sleep(0.5)
    ok, snap = person(d, "take", gen, a.page, epoch, "take")
    assert ok and snap["state"] == "finishing"
    assert a.control(lambda c: c["state"] == "finishing" and c["mine"]) is not None
    assert helper.done(20) and helper.r["ok"] and "Slow page" in helper.r["out"]  # the step ran to its end
    c = a.control(lambda c: c["state"] == "person")
    assert c is not None
    ok, _out = person(d, "give", gen, a.page, c["epoch"])
    assert ok


def test_cancel_stops_the_helpers_step(world, ws, capsys):
    d, a, gen, epoch = setup_take(ws, capsys)
    helper = Helper(d, "go", ["http://site.test/slower"])
    time.sleep(0.5)
    ok, snap = person(d, "take", gen, a.page, epoch, "take")
    assert ok and snap["state"] == "finishing"
    t0 = time.monotonic()
    ok, snap = person(d, "take", gen, a.page, snap["epoch"], "cancel")
    assert ok, snap
    assert helper.done(10) and time.monotonic() - t0 < 10
    assert helper.r["out"] == takeover.CANCELLED
    assert a.control(lambda c: c["state"] == "person" and c["mine"]) is not None


def test_ask_person_returns_after_the_give_back_or_nobody(world, ws, capsys):
    d, a, gen, epoch = setup_take(ws, capsys)
    asker = Helper(d, "ask", ["Please sign in to the portal"])
    c = a.control(lambda c: c.get("asking"))
    assert c and c["asking"] == "Please sign in to the portal"
    assert paths.read_state(d)["control"]["asking"] == "Please sign in to the portal"
    epoch = take(d, a, gen, c["epoch"])
    assert "asking" not in a.control()  # taken: the card goes, the helper still waits
    assert not asker.done(1)
    ok, _ = person(d, "give", gen, a.page, epoch)
    assert ok
    assert asker.done(10) and asker.r["ok"]
    assert asker.r["out"].startswith("A person used the browser from ")
    # nobody comes (the test home waits 4 s instead of 30 min)
    asker = Helper(d, "ask", ["Please sign in again"])
    assert asker.done(15) and asker.r["out"] == takeover.NOBODY
    assert "asking" not in paths.read_state(d)["control"]


def test_a_page_id_named_by_the_caller_is_never_taken(world, ws, capsys):
    d, a, gen, epoch = setup_take(ws, capsys)
    named = Watch(d, args=["pageA"])  # a caller that names its own id gets none
    assert named.wait_frame() is not None
    assert named.page is None
    ok, why = person(d, "take", gen, "pageA", epoch, "take")
    assert not ok and "not watching" in why
    plain = Watch(d, person=False)
    assert plain.wait_frame() is not None and plain.page is None
    assert a.page and len(a.page) >= 16


def test_nothing_a_person_typed_reaches_the_helper_after_the_give_back(world, ws, capsys):
    d, a, gen, epoch = setup_take(ws, capsys, "http://site.test/search")
    epoch = take(d, a, gen, epoch)
    frame = a.wait_frame()
    enter = [{"t": "key", "type": "down", "key": "Enter"}, {"t": "key", "type": "up", "key": "Enter"}]

    def wait(pred, what):
        end = time.monotonic() + 10
        while time.monotonic() < end and not pred():
            time.sleep(0.1)
        assert pred(), what

    def tabs_with(text):
        return any(m.get("type") == "tabs" and any(text in t["url"] for t in m["tabs"]) for m in list(a.msgs))

    # 1. the GET form send is stopped before it leaves; the person is taken back to the form
    ok, out = send(d, gen, a.page, epoch, frame, [*click(250, 120), {"t": "text", "text": SECRET}, *enter])
    assert ok, out
    wait(
        lambda: any("Stopped a form on site.test" in m.get("text", "") for m in a.msgs),
        "no stopped-form card",
    )
    assert not any(SECRET in p for _w, _m, p in world.log.of("site")), "the form send left the browser"
    mark = len(a.msgs)
    wait(
        lambda: any(
            m.get("type") == "tabs" and m["tabs"] and m["tabs"][0]["url"] == "http://site.test/search"
            for m in list(a.msgs)[mark - 1 :]
        ),
        "not back at the form",
    )
    time.sleep(0.5)
    # 2. a page script puts typed words into its own address (pushState), 3. a popup carries them
    ok, out = send(d, gen, a.page, epoch, a.wait_frame(), [*click(250, 220), {"t": "text", "text": SECRET}])
    assert ok, out
    wait(lambda: tabs_with("note=" + SECRET), "pushState did not change the address (test set-up)")
    ok, out = send(d, gen, a.page, epoch, a.wait_frame(), click(250, 320))
    assert ok, out
    wait(lambda: any(SECRET in p for _w, _m, p in world.log.of("site")), "no popup (test set-up)")
    wait(lambda: tabs_with("q=" + SECRET), "the popup is not in the tabs (test set-up)")
    mark = len(a.msgs)
    ok, out = person(d, "give", gen, a.page, epoch)
    assert ok and out["state"] == "helper", out
    answers = [out["text"]]
    for argv in (("look",), ("read",), ("status",), ("back",)):
        _code, out = run(capsys, *argv)
        answers.append(out)
    for out in answers:
        assert SECRET not in out, out
    assert "(1 tab(s))" in answers[3], "the person's pages were not all closed (popup included)"
    assert "(http://site.test/)" in answers[1] and "/search" not in answers[1], "not the origin only"
    time.sleep(1)
    for m in list(a.msgs)[mark:]:  # tabs and events the watchers got after the give back
        assert SECRET not in json.dumps(m), m
    run(capsys, "close")
    time.sleep(0.5)
    for f in Path(ws).rglob("*"):
        if f.is_file():
            assert SECRET.encode() not in f.read_bytes(), f


def _posts(world):
    return [h for h in world.log.of("site") if h[1] == "POST"]


def test_forms_go_only_to_the_site_the_person_ticked_while_in_control(
    world, ws, capsys, tmp_path, monkeypatch
):
    """Owner pick A (ORCH-1495 q1): a send leaves only while the person drives and only to the one site they ticked
    from the ticket's list; each is noted on the ticket by host (orch log, by agent:browse); after the give back
    the helper's sends are stopped again and the permission is gone."""
    said = tmp_path / "log-lines.txt"
    fake = tmp_path / "orch"
    fake.write_text(
        f'#!/bin/sh\nprintf "%s|" "$@" >> "{said}"\necho >> "{said}"\necho "{{}}"\n', encoding="utf-8"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(fake))
    d, a, gen, epoch = setup_take(ws, capsys)
    b = Watch(d)
    assert b.wait_frame() is not None
    epoch = take(d, a, gen, epoch)
    c = a.control(lambda c: c["state"] == "person" and c["mine"])
    assert c.get("sites") == ["site.test"] and "send_site" not in c
    assert "sites" not in b.control(
        lambda c: c["state"] == "person"
    )  # only the page in control hears the list
    frame = a.wait_frame()

    # only the holder may tick, only a site of the list
    ok, why = person(d, "take", gen, b.page, epoch, "send", "site.test")
    assert not ok and "Another page" in why
    ok, why = person(d, "take", gen, a.page, epoch, "send", "evil.test")
    assert not ok and "list" in why
    ok, out = person(d, "take", gen, a.page, epoch, "send", "site.test")
    assert ok and out["send_site"] == "site.test" and out["epoch"] == epoch, out

    ok, out = send(
        d, gen, a.page, epoch, frame, [*click(250, 220), {"t": "text", "text": SECRET}, *click(250, 320)]
    )
    assert ok, out
    end = time.monotonic() + 10
    while time.monotonic() < end and not _posts(world):
        time.sleep(0.1)
    assert _posts(world) == [("site", "POST", "/post")]
    assert world.log.of("evil") == []

    ok, out = person(d, "give", gen, a.page, epoch)
    assert ok and out["state"] == "helper", out
    end = time.monotonic() + 10
    while time.monotonic() < end and (not said.exists() or said.read_text().count("\n") < 2):
        time.sleep(0.1)
    lines = said.read_text(encoding="utf-8")
    assert (
        f"log|{TID}|A person allowed forms to site.test while they have the browser.|--by|agent:browse|"
        in lines
    )
    assert (
        f"log|{TID}|A person sent a form to site.test while they had the browser.|--by|agent:browse|" in lines
    )
    assert SECRET not in lines and "/post" not in lines

    # after the give back the helper's sends are stopped again, and a new take-over starts with no site
    run(capsys, "open", "http://site.test/signin")
    run(capsys, "click", "Send")
    time.sleep(1.5)
    assert len(_posts(world)) == 1
    c = a.control()
    epoch = c["epoch"]
    epoch = take(d, a, gen, epoch)
    assert "send_site" not in a.control(lambda c: c["state"] == "person" and c["mine"])
    person(d, "give", gen, a.page, epoch)


def test_a_send_the_ticked_site_hands_on_with_307_never_reaches_another_listed_site(
    world, ws, capsys, tmp_path, monkeypatch
):
    """The browser follows a 307 with the same data without asking the route again: the broker fetches the answer
    without following it and never passes a 307/308 on (evil.test is listed, not ticked)."""
    fake = tmp_path / "orch"
    fake.write_text('#!/bin/sh\necho "{}"\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(fake))
    paths.save_sites(ws, TID, ["site.test", "evil.test"])
    d, a, gen, epoch = setup_take(ws, capsys, "http://site.test/signin307")
    epoch = take(d, a, gen, epoch)
    ok, out = person(d, "take", gen, a.page, epoch, "send", "site.test")
    assert ok, out
    frame = a.wait_frame()
    ok, out = send(
        d, gen, a.page, epoch, frame, [*click(250, 220), {"t": "text", "text": SECRET}, *click(250, 320)]
    )
    assert ok, out
    end = time.monotonic() + 10
    while time.monotonic() < end and not _posts(world):
        time.sleep(0.1)
    time.sleep(1.5)
    assert _posts(world) == [("site", "POST", "/post307")]
    assert [h for h in world.log.of("evil") if h[1] != "GET"] == [], world.log.of("evil")
    person(d, "give", gen, a.page, epoch)


def test_a_send_to_a_listed_site_not_picked_yet_says_why_goes_back_and_tells_the_helper(
    world, ws, capsys, tmp_path, monkeypatch
):
    """ORCH-1779: the person pressed Send (a sign-in) before picking the site under "Forms may go to". The POST
    stays in the browser, the person is taken back to the form (never the browser's blank error page), their card
    names the site and offers Allow; after Allow the send goes through; the helper hears of the stop (host only)."""
    fake = tmp_path / "orch"
    fake.write_text('#!/bin/sh\necho "{}"\n', encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(fake))
    d, a, gen, epoch = setup_take(ws, capsys)
    epoch = take(d, a, gen, epoch)
    frame = a.wait_frame()

    def wait(pred, what, secs=10):
        end = time.monotonic() + secs
        while time.monotonic() < end and not pred():
            time.sleep(0.1)
        assert pred(), what

    mark = len(a.msgs)
    ok, out = send(
        d, gen, a.page, epoch, frame, [*click(250, 220), {"t": "text", "text": SECRET}, *click(250, 320)]
    )
    assert ok, out
    wait(lambda: any(m.get("allow") == "site.test" for m in list(a.msgs)[mark:]), "no card with Allow")
    card = next(m for m in a.msgs if m.get("allow") == "site.test")
    assert "site.test is not picked" in card["text"] and SECRET not in card["text"]

    def back_at_form():  # the blank error page first, then the form again
        urls = [m["tabs"][0]["url"] for m in list(a.msgs)[mark:] if m.get("type") == "tabs" and m["tabs"]]
        err = next((i for i, u in enumerate(urls) if u.startswith("chrome-error:")), None)
        return err is not None and "http://site.test/signin" in urls[err + 1 :]

    wait(back_at_form, "not back at the form after the error page", secs=20)
    assert _posts(world) == []

    ok, out = person(d, "take", gen, a.page, epoch, "send", "site.test")
    assert ok, out
    ok, out = send(d, gen, a.page, epoch, a.wait_frame(), click(250, 320))
    assert ok, out
    wait(lambda: _posts(world), "the allowed send did not leave")

    ok, out = person(d, "give", gen, a.page, epoch)
    assert ok and out["state"] == "helper", out
    _code, out = run(capsys, "look")
    assert out.startswith("A person used the browser from "), out  # the CLI's ping before look never eats it
    assert "1 send to site.test stopped: site.test was not picked" in out, out
    assert SECRET not in out
    _code, again = run(capsys, "look")
    assert "was not picked" not in again  # told once

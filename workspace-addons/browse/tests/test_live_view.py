"""Live view (ORCH-1493): a watcher of the real broker gets a picture, the tab list, events, and an end."""

import threading
import time

import pytest
from conftest import browser_ready
from world import World

from orch_browse import channel, cli, paths

pytestmark = pytest.mark.skipif(not browser_ready(), reason="the pinned browser is not downloaded")


@pytest.fixture
def world(ws, monkeypatch):
    w = World()
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    monkeypatch.setenv("ORCH_BROWSE_TEST_MAP", w.env_map())
    paths.save_sites(ws, "t_abc123", ["site.test"])
    yield w
    cli.main(["close", "--ticket", "t_abc123"])
    w.stop()


def run(capsys, *argv):
    code = cli.main([*argv, "--ticket", "t_abc123"])
    return code, capsys.readouterr().out


class Watch:
    def __init__(self, run_dir):
        self.msgs: list[dict] = []
        self.quit = False
        self.t = threading.Thread(target=self._go, args=(run_dir,), daemon=True)
        self.t.start()

    def _go(self, run_dir):
        for m in channel.watch(run_dir, stop_after=30):
            self.msgs.append(m)
            if self.quit:
                return  # leaving the loop closes the connection: this watcher is gone

    def wait(self, pred, secs=20, after=0):
        """Index of the first message from `after` on that matches, else None."""
        end = time.monotonic() + secs
        while time.monotonic() < end:
            for i, m in enumerate(list(self.msgs)[after:], after):
                if pred(m):
                    return i
            time.sleep(0.1)
        return None

    def of(self, kind):
        return [m for m in list(self.msgs) if m.get("type") == kind]


def test_watcher_gets_picture_tabs_events_and_end(world, ws, capsys):
    code, _ = run(capsys, "open", "http://site.test/")
    assert code == 0
    w = Watch(paths.run_dir(ws, "t_abc123"))
    assert w.wait(lambda m: m.get("type") == "hello") is not None
    gen = w.of("hello")[0]["generation"]
    assert w.wait(lambda m: m.get("type") == "frame" and m["w"] > 0) is not None
    frame = w.of("frame")[-1]
    assert frame["w"] <= 1280 and frame["h"] <= 800
    assert w.wait(lambda m: m.get("type") == "tabs" and m["tabs"] and m["tabs"][0]["title"] == "Test site")
    # A page message and a new tab: shown as events; the view switches (clear) and then shows the new tab.
    mark = len(w.msgs)
    run(capsys, "go", "http://site.test/opener")
    assert w.wait(lambda m: m.get("type") == "event" and "message" in m["text"], after=mark) is not None
    new_tab = w.wait(lambda m: m.get("type") == "event" and "new tab" in m["text"], after=mark)
    assert new_tab is not None
    cleared = w.wait(lambda m: m.get("type") == "clear", after=new_tab)
    assert cleared is not None, "the view did not switch after the new tab opened"
    assert w.wait(lambda m: m.get("type") == "frame", after=cleared) is not None, "no picture of the new tab"
    assert w.wait(lambda m: m.get("type") == "tabs" and len(m["tabs"]) == 2 and m["tabs"][1]["current"])
    # Watching is not activity: the helper's idle clock did not move (checked in the unit tests); stop ends it.
    assert (
        channel.stop(paths.run_dir(ws, "t_abc123"), "not-this-one")["out"]
        == "That browser has already ended."
    )
    assert channel.stop(paths.run_dir(ws, "t_abc123"), gen)["ok"]
    assert w.wait(lambda m: m.get("type") == "end" and "stopped by a person" in m["why"])
    w.t.join(10)
    code, out = run(capsys, "status")
    assert "No browser is open" in out and "stopped by a person" in out


def test_watch_without_a_browser_yields_nothing(ws):
    assert list(channel.watch(paths.run_dir(ws, "t_abc123"), stop_after=1)) == []


def test_a_new_watcher_after_a_page_change_never_gets_the_old_picture(world, ws, capsys):
    run(capsys, "open", "http://site.test/")
    first = Watch(paths.run_dir(ws, "t_abc123"))
    assert first.wait(lambda m: m.get("type") == "frame") is not None
    first.quit = True
    run(capsys, "look")  # a message makes the first watcher's loop see quit and leave
    first.t.join(20)
    time.sleep(0.5)
    run(capsys, "go", "http://site.test/hostile")  # nobody watches while the page changes
    second = Watch(paths.run_dir(ws, "t_abc123"))
    tabs = second.wait(lambda m: m.get("type") == "tabs")
    assert tabs is not None and second.msgs[tabs]["tabs"][0]["title"] == "Hostile page"
    cleared = second.wait(lambda m: m.get("type") == "clear")
    frame = second.wait(lambda m: m.get("type") == "frame")
    assert cleared is not None and frame is not None and frame > cleared, (
        "a picture came before the fresh one"
    )


def test_stop_gets_through_while_every_watcher_seat_is_taken(world, ws, capsys):
    run(capsys, "open", "http://site.test/")
    watchers = [Watch(paths.run_dir(ws, "t_abc123")) for _ in range(9)]
    for w in watchers:
        w.wait(lambda m: m.get("type") in ("frame", "end"), secs=20)
    turned_away = [
        w for w in watchers if any(m.get("why") == "Too many people are watching." for m in w.msgs)
    ]
    assert len(turned_away) == 1
    gen = next(w for w in watchers if w.of("hello")).of("hello")[0]["generation"]
    assert channel.stop(paths.run_dir(ws, "t_abc123"), gen)["ok"]
    for w in watchers:
        assert w.wait(lambda m: m.get("type") == "end", secs=20) is not None

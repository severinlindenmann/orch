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
        self.t = threading.Thread(target=self._go, args=(run_dir,), daemon=True)
        self.t.start()

    def _go(self, run_dir):
        for m in channel.watch(run_dir, stop_after=30):
            self.msgs.append(m)

    def wait(self, pred, secs=20):
        end = time.monotonic() + secs
        while time.monotonic() < end:
            if any(pred(m) for m in list(self.msgs)):
                return True
            time.sleep(0.1)
        return False

    def of(self, kind):
        return [m for m in list(self.msgs) if m.get("type") == kind]


def test_watcher_gets_picture_tabs_events_and_end(world, ws, capsys):
    code, _ = run(capsys, "open", "http://site.test/")
    assert code == 0
    w = Watch(paths.run_dir(ws, "t_abc123"))
    assert w.wait(lambda m: m.get("type") == "hello")
    gen = w.of("hello")[0]["generation"]
    assert w.wait(lambda m: m.get("type") == "frame" and m["w"] > 0)
    frame = w.of("frame")[-1]
    assert frame["w"] <= 1280 and frame["h"] <= 800
    assert w.wait(lambda m: m.get("type") == "tabs" and m["tabs"] and m["tabs"][0]["title"] == "Test site")
    # A page message and a new tab: shown as events, the view follows the new tab.
    run(capsys, "go", "http://site.test/opener")
    assert w.wait(lambda m: m.get("type") == "event" and "message" in m["text"])
    assert w.wait(lambda m: m.get("type") == "event" and "new tab" in m["text"])
    assert w.wait(lambda m: m.get("type") == "tabs" and len(m["tabs"]) == 2 and m["tabs"][1]["current"])
    assert w.wait(lambda m: m.get("type") == "clear")
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


def test_reconnect_gets_a_fresh_snapshot(world, ws, capsys):
    run(capsys, "open", "http://site.test/")
    first = Watch(paths.run_dir(ws, "t_abc123"))
    assert first.wait(lambda m: m.get("type") == "frame")
    second = Watch(paths.run_dir(ws, "t_abc123"))
    # The second watcher gets hello, tabs and the newest picture at once, even on a quiet page.
    assert second.wait(lambda m: m.get("type") == "frame", secs=10)
    assert second.of("hello") and second.of("tabs")

"""Take over and give back (ORCH-1495): the lock, the lease, the pause, and the input checks (no browser)."""

import math

import pytest

from orch_browse import takeover
from orch_browse.takeover import Control, Pressed, Rate, Refused, check_batch, to_cdp


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_take_waits_for_the_helper_then_the_person_drives():
    c = Control(Clock())
    assert c.snapshot()["state"] == "helper" and c.helper_may_run()
    assert c.take("pageA", 0) == "finishing"
    assert not c.helper_may_run()
    e = c.epoch
    assert c.settled(e) and c.state == "person" and c.holder == "pageA"
    assert c.snapshot("pageA")["mine"] and not c.snapshot("pageB")["mine"]


def test_a_take_over_needs_the_current_epoch_and_one_holder():
    c = Control(Clock())
    with pytest.raises(Refused, match="changed hands"):
        c.take("pageA", 5)
    c.take("pageA", 0)
    c.settled(c.epoch)
    with pytest.raises(Refused, match="Another page"):
        c.take("pageB", c.epoch)
    assert c.take("pageA", c.epoch) == "person"  # the holder asking again changes nothing
    with pytest.raises(Refused):
        c.take("", c.epoch)
    with pytest.raises(Refused):
        c.take("pageA", True)  # a bool is not an epoch


def test_settled_only_for_the_same_take_over():
    c = Control(Clock())
    c.take("pageA", 0)
    old = c.epoch
    c.give("pageA", old)  # changed their mind while finishing
    assert c.state == "helper"
    assert not c.settled(old)
    assert c.state == "helper"


def test_give_back_records_the_time_once():
    clock = Clock(1000.0)
    c = Control(clock)
    c.take("pageA", 0)
    c.settled(c.epoch)
    clock.t = 1120.0
    with pytest.raises(Refused, match="Another page"):
        c.give("pageB", c.epoch)
    assert c.give("pageA", c.epoch)
    assert c.state == "helper" and c.holder is None
    lines = c.take_used()
    assert len(lines) == 1 and lines[0].startswith("A person used the browser from ")
    assert "nothing typed was kept by orch" in lines[0]
    assert c.take_used() == []


def test_a_lost_page_pauses_and_never_resumes_the_helper():
    clock = Clock()
    c = Control(clock)
    c.take("pageA", 0)
    c.settled(c.epoch)
    assert not c.lost("pageB")  # another page leaving changes nothing
    assert c.lost("pageA")
    assert c.state == "paused" and c.holder is None and not c.helper_may_run()
    clock.t += 10_000
    assert not c.expired()
    assert c.state == "paused"
    # someone takes over again (another page): straight to them
    assert c.take("pageB", c.epoch) == "person"
    c.lost("pageB")
    # any watching page may give back while paused
    assert c.give("pageC", c.epoch) and c.state == "helper"


def test_a_lost_page_while_finishing_drops_the_take_over():
    c = Control(Clock())
    c.take("pageA", 0)
    assert c.lost("pageA")
    assert c.state == "helper"


def test_the_lease_runs_out_into_paused_and_renewing_keeps_it():
    clock = Clock()
    c = Control(clock)
    c.take("pageA", 0)
    c.settled(c.epoch)
    clock.t += takeover.LEASE_SECONDS - 1
    c.renew("pageA", c.epoch)
    clock.t += takeover.LEASE_SECONDS - 1
    assert not c.expired()
    clock.t += 2
    assert c.expired() and c.state == "paused"
    with pytest.raises(Refused):
        c.renew("pageA", c.epoch)


def test_cancel_only_while_finishing_and_by_the_holder():
    c = Control(Clock())
    with pytest.raises(Refused, match="no step"):
        c.cancel("pageA", 0)
    c.take("pageA", 0)
    with pytest.raises(Refused):
        c.cancel("pageB", c.epoch)
    c.cancel("pageA", c.epoch)  # the broker stops the step, then settled()


def test_asking_is_separate_from_control():
    c = Control(Clock())
    c.ask("  Please sign in\nto the portal  " + "x" * 400)
    snap = c.snapshot()
    assert snap["state"] == "helper" and snap["asking"].startswith("Please sign in to the portal")
    assert len(snap["asking"]) <= 300
    e = c.epoch
    c.unask()
    assert "asking" not in c.snapshot() and c.epoch == e  # asking never changes the owner


# ---------------------------------------------------------------------------- the input


def test_rate_drops_bursts_but_refills():
    clock = Clock(0.0)
    r = Rate(clock, rate=10, burst=3)
    assert [r.take() for _ in range(4)] == [True, True, True, False]
    clock.t = 0.2
    assert r.take() and r.take() and not r.take()


def test_mouse_events_inside_the_picture_map_to_page_pixels():
    ev = check_batch([{"t": "down", "x": 640, "y": 400, "button": "left", "count": 1}], 1280, 800)
    method, p = to_cdp(ev[0], 1280, 800, 1280, 800, 1)
    assert method == "Input.dispatchMouseEvent"
    assert p == {
        "type": "mousePressed",
        "x": 640.0,
        "y": 400.0,
        "modifiers": 0,
        "button": "left",
        "buttons": 1,
        "clickCount": 1,
    }
    # a smaller picture of the same page: scaled up
    ev = check_batch([{"t": "move", "x": 320, "y": 200}], 640, 400)
    _m, p = to_cdp(ev[0], 640, 400, 1280, 800)
    assert (p["x"], p["y"]) == (640.0, 400.0)
    ev = check_batch([{"t": "wheel", "x": 1, "y": 1, "dx": 0, "dy": 120}], 1280, 800)
    _m, p = to_cdp(ev[0], 1280, 800, 1280, 800)
    assert p["type"] == "mouseWheel" and p["deltaY"] == 120


@pytest.mark.parametrize(
    "ev",
    [
        {"t": "move", "x": 1280, "y": 10},  # just outside: refused, never clamped to the edge
        {"t": "move", "x": -1, "y": 10},
        {"t": "move", "x": math.nan, "y": 10},
        {"t": "move", "x": math.inf, "y": 10},
        {"t": "move", "x": "10", "y": 10},
        {"t": "move", "x": True, "y": 10},
        {"t": "move", "x": 1, "y": 1, "extra": 1},
        {"t": "down", "x": 1, "y": 1, "button": "back", "count": 1},
        {"t": "down", "x": 1, "y": 1, "button": "left", "count": 9},
        {"t": "key", "type": "down", "key": "F12"},
        {"t": "key", "type": "down", "key": "a"},  # a plain letter is text, not a key
        {"t": "key", "type": "press", "key": "Enter"},
        {"t": "text", "text": ""},
        {"t": "text", "text": 5},
        {"t": "eval", "text": "x"},
        "move",
    ],
)
def test_odd_events_are_refused(ev):
    with pytest.raises(Refused):
        check_batch([ev], 1280, 800)


def test_batch_size_text_length_and_no_picture_are_refused():
    with pytest.raises(Refused):
        check_batch([], 1280, 800)
    with pytest.raises(Refused):
        check_batch([{"t": "move", "x": 1, "y": 1}] * (takeover.MAX_EVENTS + 1), 1280, 800)
    with pytest.raises(Refused, match="2000"):
        check_batch([{"t": "text", "text": "a" * 1500}, {"t": "paste", "text": "b" * 501}], 1280, 800)
    assert check_batch([{"t": "paste", "text": "b" * 2000}], 1280, 800)
    with pytest.raises(Refused, match="no picture"):
        check_batch([{"t": "move", "x": 1, "y": 1}], 0, 0)
    with pytest.raises(Refused):
        check_batch({"t": "move"}, 1280, 800)


def test_keys_shortcuts_and_text():
    evs = check_batch(
        [
            {"t": "key", "type": "down", "key": "Enter"},
            {"t": "key", "type": "up", "key": "Enter"},
            {"t": "key", "type": "down", "key": "A", "mod": takeover.MOD_META},
            {"t": "text", "text": "grüezi\x00\x07 mitenand"},
        ],
        1280,
        800,
    )
    m, p = to_cdp(evs[0], 1280, 800, 1280, 800)
    assert m == "Input.dispatchKeyEvent" and p["type"] == "keyDown" and p["text"] == "\r"
    _m, p = to_cdp(evs[1], 1280, 800, 1280, 800)
    assert p["type"] == "keyUp" and "text" not in p
    _m, p = to_cdp(evs[2], 1280, 800, 1280, 800)
    assert p["commands"] == ["selectAll"] and p["key"] == "a"
    m, p = to_cdp(evs[3], 1280, 800, 1280, 800)
    assert m == "Input.insertText" and p == {"text": "grüezi mitenand"}  # control characters dropped


def test_pressed_keys_and_buttons_are_released():
    pr = Pressed()
    for ev in check_batch(
        [
            {"t": "down", "x": 10, "y": 20, "button": "left", "count": 1},
            {"t": "key", "type": "down", "key": "ArrowDown"},
            {"t": "key", "type": "down", "key": "Tab"},
            {"t": "key", "type": "up", "key": "Tab"},
        ],
        1280,
        800,
    ):
        m, p = to_cdp(ev, 1280, 800, 1280, 800)
        pr.note(ev, m, p)
    assert pr.mask() == 1
    rel = pr.releases()
    assert ("Input.dispatchMouseEvent", "mouseReleased") in [(m, p["type"]) for m, p in rel]
    assert [p["key"] for m, p in rel if m == "Input.dispatchKeyEvent"] == ["ArrowDown"]
    assert pr.releases() == [] and pr.mask() == 0

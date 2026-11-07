import json
from datetime import UTC, datetime, timedelta

import pytest

from orch import keepawake, net, relay
from orch import mobile_mode as mm
from orch.errors import Refused


class FakeProc:
    def __init__(self, cmd):
        self.cmd, self.ended = cmd, False

    def poll(self):
        return 0 if self.ended else None

    def terminate(self):
        self.ended = True

    def wait(self, timeout=None):
        return 0

    kill = terminate


@pytest.fixture
def beats(monkeypatch):
    got = []
    monkeypatch.setattr(relay, "heartbeat", lambda root, p: got.append(p))
    return got


@pytest.fixture
def on_state(proj, monkeypatch, beats):
    (proj / ".orch").mkdir(exist_ok=True)
    monkeypatch.setattr(mm, "_spawn_keeper", lambda root: None)
    monkeypatch.setattr(mm, "START_WAIT", 0.0)
    from orch import addons

    monkeypatch.setattr(addons, "active", lambda root: ["relay"])
    return proj


# ---- keep-awake helper --------------------------------------------------------------------------


def test_commands_per_platform():
    w = lambda n: "/x/" + n  # noqa: E731
    assert keepawake.command("darwin", 42, 100, w) == ["caffeinate", "-dimsu", "-w", "42"]
    c = keepawake.command("linux", 1, 5000, w)
    assert (
        c[0] == "systemd-inhibit"
        and "--what=sleep:idle:handle-lid-switch" in c
        and c[-2:] == ["sleep", "5000"]
    )
    assert keepawake.command("linux", 1, 5, lambda n: None) is None
    assert keepawake.command("freebsd", 1, 5, w) is None


def test_acquire_release_child_only():
    made = []
    h = keepawake.acquire(
        100, 7, "darwin", popen=lambda c, **k: made.append(FakeProc(c)) or made[-1], which=lambda n: n
    )
    assert h.method == "caffeinate" and h.alive()
    h.release()
    h.release()
    assert made[0].ended


def test_acquire_none_without_tool():
    assert keepawake.acquire(100, 7, "linux", which=lambda n: None) is None


def test_acquire_windows_flags():
    calls = []
    h = keepawake.acquire(100, platform="win32", win=lambda f: calls.append(f) or 1)
    assert calls == [keepawake.ES_CONTINUOUS | keepawake.ES_SYSTEM_REQUIRED]
    h.release()
    assert calls[-1] == keepawake.ES_CONTINUOUS


# ---- state, lease --------------------------------------------------------------------------------


def test_on_off_status(on_state, beats):
    st = mm.turn_on(on_state, 8)
    assert st["on"] and st["ends_at"] and mm.status(on_state)["machine"]
    d = json.loads((on_state / ".orch/run/mobile-mode.json").read_text())
    assert d["hours"] == 8
    assert beats[-1]["on"] is True and beats[-1]["machine"]
    st = mm.turn_off(on_state)
    assert not st["on"] and st["ended"]["reason"] == "off"
    assert beats[-1] == {"on": False, "ended": "off"}


def test_hours_choices(on_state):
    with pytest.raises(Refused):
        mm.turn_on(on_state, 5)
    assert mm.set_default_hours(on_state, 4) == 4
    assert mm.default_hours(on_state) == 4
    st = mm.turn_on(on_state)
    since = datetime.strptime(st["since"], "%Y-%m-%dT%H:%M:%SZ")
    ends = datetime.strptime(st["ends_at"], "%Y-%m-%dT%H:%M:%SZ")
    assert ends - since in (timedelta(hours=4), timedelta(hours=4, seconds=1), timedelta(hours=4, seconds=-1))
    assert mm.default_hours(on_state) == 4


def test_lease_end_settles(on_state):
    mm.turn_on(on_state, 4)
    later = datetime.now(UTC) + timedelta(hours=5)
    d = mm.settle(on_state, later)
    assert not d["on"] and d["ended"]["reason"] == "lease"


def test_dead_keeper_means_restart(on_state):
    mm.turn_on(on_state, 4)
    p = on_state / ".orch/run/mobile-mode.json"
    d = json.loads(p.read_text())
    d.update(keeper_pid=999999, keeper_started="2020-01-01T00:00:00Z")
    p.write_text(json.dumps(d))
    st = mm.status(on_state)
    assert not st["on"] and st["ended"]["reason"] == "restart"
    assert "restarted" in st["ended"]["text"]
    mm.acknowledge_ended(on_state)
    assert mm.status(on_state)["ended"] is None


# ---- keeper lifecycle ----------------------------------------------------------------------------


def fake_acquire(held):
    def acq(seconds, owner_pid=None):
        h = keepawake.Hold("fake", proc=FakeProc(["fake"]))
        held.append(h)
        return h

    return acq


def test_keeper_ends_when_state_off(on_state):
    mm.turn_on(on_state, 4)
    held = []
    ticks = []

    def sleep(_):
        ticks.append(1)
        if len(ticks) == 2:
            mm.turn_off(on_state)

    why = mm.run_keeper(on_state, acquire=fake_acquire(held), sleep=sleep, max_ticks=50)
    assert why == "off" and held[0]._proc is None  # released its own child
    assert not mm.status(on_state)["on"]


def test_keeper_ends_at_lease(on_state, beats):
    mm.turn_on(on_state, 4)
    t = [datetime.now(UTC)]
    held = []
    why = mm.run_keeper(
        on_state,
        acquire=fake_acquire(held),
        sleep=lambda s: t.__setitem__(0, t[0] + timedelta(hours=3)),
        now=lambda: t[0],
        max_ticks=10,
    )
    assert why == "lease"
    assert mm.status(on_state)["ended"]["reason"] == "lease"
    assert beats[-1] == {"on": False, "ended": "lease"}


def test_keeper_could_not_keep_awake(on_state):
    mm.turn_on(on_state, 4)
    mm.run_keeper(on_state, acquire=lambda *a, **k: None, sleep=lambda s: None, max_ticks=1)
    assert (
        json.loads((on_state / ".orch/run/mobile-mode.json").read_text())["awake"] == "could_not_keep_awake"
    )


def test_second_keeper_wins_first_stops(on_state):
    mm.turn_on(on_state, 4)
    held = []

    def sleep(_):
        p = on_state / ".orch/run/mobile-mode.json"
        d = json.loads(p.read_text())
        d["keeper_pid"] = 1  # another keeper took over
        p.write_text(json.dumps(d))

    assert mm.run_keeper(on_state, acquire=fake_acquire(held), sleep=sleep, max_ticks=5) == "off"
    assert held[0]._proc is None


# ---- routing and phone control -------------------------------------------------------------------


def test_routes_to_phone_needs_relay(on_state, monkeypatch):
    mm.turn_on(on_state, 4)
    from orch import addons

    monkeypatch.setattr(addons, "active", lambda root: ["relay"])
    assert not mm.routes_to_phone(on_state)  # not connected
    net.write_json(
        net.secrets_dir(on_state) / "relay.json", {"url": "http://x", "workspace": "ws_a", "token": "orn_x"}
    )
    assert mm.routes_to_phone(on_state)
    mm.turn_off(on_state)
    assert not mm.routes_to_phone(on_state)


def ctl(mid, frm="ph_aaaaaaaaaa", age=10):
    t = (datetime.now(UTC) - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": mid,
        "from": frm,
        "to": "ws_x",
        "type": "control",
        "created_at": t,
        "body": {"control": "mobile_mode_off"},
    }


def put_dir(root, phones):
    d = root / ".agents/skills/orch-relay"
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspaces.json").write_text(json.dumps({"workspaces": [], "phones": phones}))


@pytest.mark.parametrize(
    "frm,age,paired,off",
    [
        ("ph_aaaaaaaaaa", 10, True, True),
        ("ph_aaaaaaaaaa", 700, True, False),
        ("ph_bbbbbbbbbb", 10, True, False),
        ("ph_aaaaaaaaaa", 10, False, False),
    ],
)
def test_phone_off_control(on_state, frm, age, paired, off):
    mm.turn_on(on_state, 4)
    put_dir(on_state, [{"id": "ph_aaaaaaaaaa", "name": "P"}] if paired else [])
    m = ctl("m_" + "a" * 16, frm, age)
    relay._handle_mobile_off(on_state, m)
    assert mm.status(on_state)["on"] is (not off)
    assert "m_" + "a" * 16 in relay.seen(on_state)


def test_cli_status_and_hours(on_state, run):
    code, out, _ = run("relay", "mobile", "status", "--json")
    assert code == 0 and json.loads(out)["on"] is False
    code, out, _ = run("relay", "mobile", "hours", "8", "--json")
    assert json.loads(out)["default_hours"] == 8
    code, out, _ = run("relay", "mobile", "on", "--json")
    assert json.loads(out)["on"] is True
    code, out, _ = run("relay", "mobile", "off")
    assert code == 0 and "off" in out.lower()


def test_machine_name_is_plain_one_line(monkeypatch):
    monkeypatch.setattr(mm._platform, "node", lambda: "Ac‮me​ \n PC\x00" + "x" * 80 + ".local")
    n = mm.machine_name()
    assert n.startswith("Acme PC") and "‮" not in n and "​" not in n and "\n" not in n and len(n) <= 60
    monkeypatch.setattr(mm._platform, "node", lambda: "")
    assert mm.machine_name() == "this computer"

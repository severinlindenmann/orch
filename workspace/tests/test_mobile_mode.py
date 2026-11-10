import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import pytest

from orch import keepawake, net, procs, relay
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


REAL_SPAWN = mm._spawn_keeper


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
    assert c == [
        "systemd-inhibit",
        "--what=sleep:idle:handle-lid-switch",
        "--who=orch",
        "--why=Mobile mode",
        "--mode=block",
        "tail",
        "--pid=1",
        "-f",
        "/dev/null",
    ]
    assert keepawake.command("linux", 1, 5, lambda n: None) is None
    assert keepawake.command("freebsd", 1, 5, w) is None


@pytest.mark.parametrize("platform,method", [("darwin", "caffeinate"), ("linux", "systemd-inhibit")])
def test_acquire_release_child_only(platform, method):
    made = []
    h = keepawake.acquire(
        100, 7, platform, popen=lambda c, **k: made.append(FakeProc(c)) or made[-1], which=lambda n: n
    )
    assert h.method == method and h.alive()
    assert made[0].cmd == keepawake.command(platform, 7, 100, which=lambda n: n)
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
    assert not st["on"] and st["ended"] is None  # a local off leaves no notice
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


def stamp(delta_s):
    return (datetime.now(UTC) + timedelta(seconds=delta_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ctl_at(mid, delta_s, frm="ph_aaaaaaaaaa"):
    m = ctl(mid, frm)
    m["created_at"] = stamp(delta_s)
    return m


MID = "m_" + "a" * 16


@pytest.mark.parametrize(
    "frm,delta,paired,off",
    [
        ("ph_aaaaaaaaaa", -10, True, True),
        ("ph_aaaaaaaaaa", -700, True, False),  # too old
        ("ph_aaaaaaaaaa", 60, True, True),  # a little ahead: clock skew
        ("ph_aaaaaaaaaa", 600, True, False),  # dated in the future
        ("ph_bbbbbbbbbb", -10, True, False),  # not a paired phone
        ("ph_aaaaaaaaaa", -10, False, False),
    ],
)
def test_phone_off_control(on_state, beats, frm, delta, paired, off):
    mm.turn_on(on_state, 4)
    put_dir(on_state, [{"id": "ph_aaaaaaaaaa", "name": "P"}] if paired else [])
    m = ctl_at(MID, delta, frm)
    p = on_state / ".orch/run/mobile-mode.json"
    d = json.loads(p.read_text())
    d["since"] = stamp(-3600)  # only the age is under test
    d.update(keeper_pid=os.getpid(), keeper_started=procs.pid_started(os.getpid()))
    p.write_text(json.dumps(d))
    relay._handle_mobile_off(on_state, m)
    assert mm.status(on_state)["on"] is (not off)
    assert MID in relay.seen(on_state)
    if off:
        ended = mm.status(on_state)["ended"]
        assert ended["reason"] == "phone"
        assert ended["text"] == "Turned off from your phone"
        assert ended["by"] == frm
        assert mm.payload(on_state) == {"on": False, "ended": "off"}
        assert beats[-1] == {"on": False, "ended": "off"}


def test_old_control_does_not_end_a_newer_mobile_mode(on_state):
    put_dir(on_state, [{"id": "ph_aaaaaaaaaa", "name": "P"}])
    mm.turn_on(on_state, 4)
    old = ctl_at(MID, -1)
    time.sleep(1.1)
    mm.turn_off(on_state)
    mm.turn_on(on_state, 4)  # a newer Mobile mode began after the request was made
    assert "ignored" in relay._handle_mobile_off(on_state, old)
    assert mm.status(on_state)["on"]


def test_control_is_handled_once(on_state, beats):
    put_dir(on_state, [{"id": "ph_aaaaaaaaaa", "name": "P"}])
    mm.turn_on(on_state, 4)
    time.sleep(1.1)
    m = ctl_at(MID, 0)
    assert "turned off" in relay._handle_mobile_off(on_state, m)
    mm.turn_on(on_state, 4)
    assert relay._handle_mobile_off(on_state, m) == "already handled"  # the racing reader
    assert mm.status(on_state)["on"]


def test_keeper_argv_has_dash_P(on_state, monkeypatch):
    spawned = []
    monkeypatch.setattr(mm.subprocess, "Popen", lambda argv, **kw: spawned.append((argv, kw)))
    REAL_SPAWN(on_state)
    argv, kw = spawned[-1]
    assert argv[:5] == [sys.executable, "-I", "-P", "-m", "orch"] and argv[5:] == [
        "relay",
        "mobile",
        "keeper",
    ]
    assert kw["cwd"] == str(on_state)


def test_heartbeat_machine_is_cleaned_again(on_state):
    mm.turn_on(on_state, 4)
    p = on_state / ".orch/run/mobile-mode.json"
    d = json.loads(p.read_text())
    d["machine"] = "Ev\u202eil\n" + "y" * 100
    p.write_text(json.dumps(d))
    got = mm.payload(on_state)["machine"]
    assert got.startswith("Evil") and "\u202e" not in got and "\n" not in got and len(got) <= 60


def test_cli_status_and_hours(on_state, run):
    code, out, _ = run("relay", "mobile", "status", "--json")
    assert code == 0 and json.loads(out)["on"] is False
    code, out, _ = run("relay", "mobile", "hours", "8", "--json")
    assert json.loads(out)["default_hours"] == 8
    code, out, _ = run("relay", "mobile", "on", "--json")
    assert json.loads(out)["on"] is True
    code, out, _ = run("relay", "mobile", "off")
    assert code == 0 and "off" in out.lower()


def test_machine_name_is_plain_one_line(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mm._platform, "node", lambda: "Ac\u202eme\u200b \n PC\x00\u034f" + "x" * 80 + ".local"
    )
    n = mm.machine_name()
    assert n.startswith("Acme PC") and len(n) <= 60
    assert not any(c in n for c in "\u202e\u200b\n\x00\u034f")
    monkeypatch.setattr(mm._platform, "node", lambda: "e" + "\u0301" * 5)  # at most 2 marks in a row
    assert mm.machine_name() == "\u00e9\u0301\u0301"
    monkeypatch.setattr(mm._platform, "node", lambda: "   \n\u200b ")
    ws = tmp_path / "Acme\u202e ws"
    ws.mkdir()
    assert mm.machine_name(ws) == "Acme ws"  # empty name: the workspace name, cleaned the same way
    assert mm.machine_name() == "this computer"


def test_phone_off_does_not_end_mode_restarted_after_decision(on_state, monkeypatch, beats):
    put_dir(on_state, [{"id": "ph_aaaaaaaaaa", "name": "P"}])
    now = datetime.now(UTC)
    monkeypatch.setattr(mm, "_now", lambda: now)
    original_since = mm.turn_on(on_state, 4)["since"]
    turn_off = mm.turn_off

    def restart_before_off(root, reason="off", if_since=None, by=None):
        assert if_since == original_since
        turn_off(root)
        monkeypatch.setattr(mm, "_now", lambda: now + timedelta(seconds=1))
        new_since = mm.turn_on(root, 4)["since"]
        count = len(beats)
        result = turn_off(root, reason, if_since=if_since, by=by)
        assert result["on"] and result["since"] == new_since
        assert len(beats) == count
        return result

    monkeypatch.setattr(mm, "turn_off", restart_before_off)
    relay._handle_mobile_off(on_state, ctl_at(MID, 0))
    assert mm.status(on_state)["on"]


def test_conditional_off_leaves_ended_state_unchanged(on_state, beats):
    since = mm.turn_on(on_state, 4)["since"]
    ended = mm.turn_off(on_state)
    count = len(beats)
    assert mm.turn_off(on_state, "phone", if_since=since, by="ph_aaaaaaaaaa") == ended
    assert len(beats) == count


# ---- questions on phone-started tickets reach the phone (owner 8 Nov, fb7) ----------------------


def _connect(root):
    net.write_json(
        net.secrets_dir(root) / "relay.json", {"url": "http://x", "workspace": "ws_a", "token": "orn_x"}
    )


def _phone_ticket(root, title="From the phone", parent=None):
    from orch import tickets

    t = tickets.create(root, title, "human:ph_aaaaaaaaaa", parent=parent)
    tickets.apply_op(root, t["id"], lambda tk: tk.setdefault("ext", {}).update(relay={"origin": "phone"}))
    return t["id"]


def test_question_to_phone_for_phone_tickets_without_mobile_mode(on_state, monkeypatch):
    from orch import tickets

    monkeypatch.delenv("ORCH_TICKET", raising=False)
    phone = _phone_ticket(on_state)
    child = tickets.create(on_state, "Made by the agent", "agent:claude", parent=phone)["id"]
    plain = tickets.create(on_state, "Dashboard ticket", "human:sev")["id"]
    assert not mm.question_to_phone(on_state, phone)  # relay not connected: never
    _connect(on_state)
    assert mm.question_to_phone(on_state, phone)
    assert mm.question_to_phone(on_state, child)  # a parent came from the phone
    assert not mm.question_to_phone(on_state, plain)  # quiet: every question is pushed
    # the agent of a phone ticket made a new ticket without a parent: its run ticket counts
    assert mm.question_to_phone(on_state, plain, run_ticket=phone)
    assert not mm.question_to_phone(on_state, plain, run_ticket="t_missing")
    mm.turn_on(on_state, 4)
    assert mm.question_to_phone(on_state, plain)  # Mobile mode: every question


def test_question_to_phone_needs_relay_addon(on_state, monkeypatch):
    from orch import addons

    phone = _phone_ticket(on_state)
    _connect(on_state)
    monkeypatch.setattr(addons, "active", lambda root: [])
    assert not mm.question_to_phone(on_state, phone)


def test_cli_ask_sends_phone_ticket_questions_to_the_phone(on_state, run, monkeypatch):
    from orch import cli_clients, tickets

    sent = []
    monkeypatch.setattr(
        cli_clients, "send_phone_question", lambda root, tid, q, *a: sent.append((tid, q["id"]))
    )
    monkeypatch.delenv("ORCH_TICKET", raising=False)
    _connect(on_state)
    phone = _phone_ticket(on_state)
    plain = tickets.create(on_state, "Dashboard ticket", "human:sev")["id"]
    other = tickets.create(on_state, "Second", "human:sev")["id"]
    assert (
        run("ask", phone, "Which colour?", "--option", "Blue", "--option", "Red", "--by", "agent:claude")[0]
        == 0
    )
    assert run("ask", plain, "Which day?", "--option", "Mon", "--by", "agent:claude")[0] == 0
    assert [s[0] for s in sent] == [phone]
    monkeypatch.setenv("ORCH_TICKET", phone)  # the phone ticket's agent asks on a ticket it made
    assert run("ask", other, "Which size?", "--option", "S", "--by", "agent:claude")[0] == 0
    assert [s[0] for s in sent] == [phone, other]


def test_question_to_phone_continued_ticket_and_broken_parent(on_state, monkeypatch):
    from orch import tickets

    _connect(on_state)
    cont = tickets.create(on_state, "Dashboard ticket the phone wrote to", "human:sev")["id"]
    assert not mm.question_to_phone(on_state, cont)
    # a peer workspace's message (relay._ticket_for) only fills messages: not from the phone
    tickets.apply_op(on_state, cont, lambda tk: tk.setdefault("ext", {}).update(relay={"messages": ["m_1"]}))
    assert not mm.question_to_phone(on_state, cont)
    tickets.apply_op(on_state, cont, lambda tk: tk["ext"]["relay"].update(phone=True))
    assert mm.question_to_phone(on_state, cont)
    bad = tickets.create(on_state, "Broken parent", "human:sev")["id"]
    for parent in (["t_x"], 7):
        p = tickets.ticket_path(on_state, bad)
        d = json.loads(p.read_text())
        d["parent"] = parent
        p.write_text(json.dumps(d))
        assert not mm.from_phone(on_state, bad)

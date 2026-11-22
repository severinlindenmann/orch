"""ORCH-1162 (people step 4, follow-up of PR 2269): a cut phone, or every phone of a removed person, comes off
this workspace's list on the relay (DELETE /v1/phones/<ph_id>), so it no longer receives what goes to
`phones`; a relay that can't be reached is tried again on the next refresh. And the helpers a removed person
started, or that work on a ticket a cut phone made, are stopped."""

import pytest
from test_relay_client import connect

from orch import people, relay, runs, runs_live, tickets
from orch.errors import Refused

LEA, MAX, NEW = "ph_lea0000001", "ph_max0000001", "ph_new0000001"


def _phone(pid, name):
    return {"id": pid, "name": name, "online": True, "last_seen": None}


@pytest.fixture
def team(proj, run, rel):
    phones = [_phone(LEA, "Lea phone"), _phone(MAX, "Max phone"), _phone(NEW, "Pixel")]
    rel.snapshot["workspaces"]["phones"] = phones
    connect(run, rel)
    people.turn_on(proj, "Sev")
    lea = people.add(proj, "Lea", ["write", "start"])
    mx = people.add(proj, "Max", ["write", "decide", "start"])
    people.tie(proj, LEA, "Lea")
    people.tie(proj, MAX, "Max")
    return {"lea": lea["id"], "max": mx["id"]}


def _paired(rel):
    return [p["id"] for p in rel.snapshot["workspaces"]["phones"]]


def test_drop_phone_takes_this_workspace_off_and_404_counts_as_off(proj, run, rel, team):
    assert relay.drop_phone(proj, LEA) == "off"
    assert rel.dropped == [LEA] and LEA not in _paired(rel)
    assert relay.drop_phone(proj, LEA) == "absent"  # the relay's own 404: already off
    with pytest.raises(Refused):
        relay.drop_phone(proj, "ph_../../x")


def test_an_old_relay_without_the_call_is_never_taken_for_off(proj, run, rel, team):
    rel.routes = [r for r in rel.routes if "v1/phones" not in str(r)]  # a relay before ORCH-1162: plain 404
    with pytest.raises(Refused, match="needs an update"):
        relay.drop_phone(proj, LEA)
    code, out, _ = run("people", "cut", LEA)
    assert code == 0 and "may still see new questions" in out and "sees nothing more" not in out


def test_a_phone_an_old_snapshot_misses_is_still_dropped_when_cut(proj, run, rel, team):
    rel.snapshot["workspaces"]["phones"].append(
        _phone("ph_late000001", "Late phone")
    )  # ticked after the refresh
    people.tie(proj, "ph_late000001", "Lea")
    code, out, _ = run("people", "cut", "ph_late000001")
    assert code == 0 and rel.dropped == ["ph_late000001"] and "sees nothing more" in out


def test_drop_never_raises_on_a_broken_snapshot(proj, run, rel, team):
    people.cut(proj, LEA)
    snap = proj / ".agents" / "skills" / "orch-relay" / "workspaces.json"
    snap.write_text("{not json", encoding="utf-8")
    assert people.drop_cut_phones(proj) == []


def test_tying_a_cut_phone_again_says_to_tick_it_on_the_relay(proj, run, rel, team):
    run("people", "cut", LEA)
    run("relay", "refresh")  # the relay took it off: the snapshot no longer lists it
    code, out, _ = run("people", "tie", LEA, "Lea")
    assert code == 0 and "relay admin page" in out


def test_cut_drops_only_that_phone_on_the_relay(proj, run, rel, team):
    code, out, _ = run("people", "cut", LEA)
    assert code == 0, out
    assert rel.dropped == [LEA]
    assert "sees nothing more" in out
    assert _paired(rel) == [MAX, NEW]


def test_removing_a_person_drops_all_their_phones(proj, run, rel, team):
    people.tie(proj, NEW, "Max")  # Max has two phones
    code, out, _ = run("people", "remove", "Max")
    assert code == 0, out
    assert sorted(rel.dropped) == sorted([MAX, NEW])
    assert _paired(rel) == [LEA]


def test_relay_unreachable_is_tried_again_on_refresh(proj, run, rel, team, monkeypatch):
    real = relay.drop_phone
    monkeypatch.setattr(relay, "drop_phone", lambda root, ph: (_ for _ in ()).throw(Refused("offline")))
    code, out, _ = run("people", "cut", LEA)
    assert code == 0, out  # the cut itself holds
    assert "until the relay is reached again" in out
    assert people.load(proj)["devices"][0]["cut_at"]  # the cut is in the list either way
    monkeypatch.setattr(relay, "drop_phone", real)
    run("relay", "refresh")
    assert rel.dropped == [LEA]


def test_list_off_or_no_cut_phone_drops_nothing(proj, run, rel):
    rel.snapshot["workspaces"]["phones"] = [_phone(LEA, "Lea phone")]
    connect(run, rel)
    assert people.drop_cut_phones(proj) == []
    people.turn_on(proj, "Sev")
    people.add(proj, "Lea")
    people.tie(proj, LEA, "Lea")
    assert people.drop_cut_phones(proj) == []
    assert rel.dropped == []


def _running(proj, tid, by):
    rec = runs._new_record(tid, by, "claude", "live", tickets.load(proj, tid), None, proj)
    runs._write(proj, rec)
    return rec


def test_helpers_of_a_removed_person_and_of_a_cut_phones_ticket_stop(proj, run, rel, team, monkeypatch):
    by_lea = tickets.create(proj, "Lea's work", "human:sev")["id"]
    by_sev = tickets.create(proj, "Owner's work", "human:sev")["id"]
    from_phone = tickets.create(
        proj, "From Max's phone", "human:sev", ext={"relay": {"origin": "phone", "from": MAX}}
    )["id"]

    def earlier(doc):  # the phone was tied well before its ticket was made (same second counts as before)
        next(d for d in doc["devices"] if d["id"] == MAX)["tied_at"] = "2026-01-01T00:00:00Z"
        return "test"

    people._change(proj, earlier)
    _running(proj, by_lea, f"human:{team['lea']}")
    _running(proj, by_sev, "human:sev")
    _running(proj, from_phone, runs_live.AUTOMATION_BY)
    monkeypatch.setattr(runs, "state", lambda rec, at=None: "alive")
    stopped = []
    monkeypatch.setattr(runs_live, "stop", lambda root, tid, hold=False: stopped.append(tid) or True)

    lea, both = [team["lea"]], [team["lea"], team["max"]]
    assert runs_live.stop_not_allowed(proj, both, [LEA, MAX]) == []  # everyone may still start: nothing stops
    people.remove(proj, "Lea")
    assert runs_live.stop_not_allowed(proj, lea, [LEA]) == [by_lea]
    people.cut(proj, MAX)
    stopped.clear()
    assert runs_live.stop_not_allowed(proj, [], [MAX]) == [from_phone]  # only what this cut concerns
    assert by_sev not in stopped


def test_stop_never_raises_on_an_unreadable_run_folder(proj, monkeypatch):
    monkeypatch.setattr(runs_live, "records", lambda root: (_ for _ in ()).throw(OSError("gone")))
    assert runs_live.stop_not_allowed(proj, ["pr_aaaaaaaaaa"], []) == []


def test_stop_never_stops_the_run_it_runs_inside(proj, run, rel, team, monkeypatch):
    tid = tickets.create(proj, "Lea's work", "human:sev")["id"]
    _running(proj, tid, f"human:{team['lea']}")
    monkeypatch.setattr(runs, "state", lambda rec, at=None: "alive")
    monkeypatch.setattr(runs_live, "stop", lambda root, t, hold=False: True)
    people.remove(proj, "Lea")
    monkeypatch.setenv("ORCH_TICKET", tid)
    assert runs_live.stop_not_allowed(proj, [team["lea"]], []) == []


def test_cli_cut_and_remove_report_stopped_helpers(proj, run, rel, team, monkeypatch):
    monkeypatch.setattr(runs_live, "stop_not_allowed", lambda root, ids, phones: ["t_aaaaaa"])
    code, out, _ = run("people", "remove", "Lea")
    assert code == 0 and "Stopped 1 running helper." in out
    monkeypatch.setattr(runs_live, "stop_not_allowed", lambda root, ids, phones: ["t_aaaaaa", "t_bbbbbb"])
    code, out, _ = run("people", "cut", MAX)
    assert code == 0 and "Stopped 2 running helpers." in out

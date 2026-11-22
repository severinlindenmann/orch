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
    assert relay.drop_phone(proj, LEA) is True
    assert rel.dropped == [LEA] and LEA not in _paired(rel)
    assert relay.drop_phone(proj, LEA) is True  # already off: 404 is no error
    with pytest.raises(Refused):
        relay.drop_phone(proj, "ph_../../x")


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

    assert runs_live.stop_not_allowed(proj) == []  # everyone may still start: nothing stops
    people.remove(proj, "Lea")
    assert runs_live.stop_not_allowed(proj) == [by_lea]
    people.cut(proj, MAX)
    stopped.clear()
    assert sorted(runs_live.stop_not_allowed(proj)) == sorted([by_lea, from_phone])
    assert by_sev not in stopped


def test_stop_never_stops_the_run_it_runs_inside(proj, run, rel, team, monkeypatch):
    tid = tickets.create(proj, "Lea's work", "human:sev")["id"]
    _running(proj, tid, f"human:{team['lea']}")
    monkeypatch.setattr(runs, "state", lambda rec, at=None: "alive")
    monkeypatch.setattr(runs_live, "stop", lambda root, t, hold=False: True)
    people.remove(proj, "Lea")
    monkeypatch.setenv("ORCH_TICKET", tid)
    assert runs_live.stop_not_allowed(proj) == []


def test_cli_cut_and_remove_report_stopped_helpers(proj, run, rel, team, monkeypatch):
    monkeypatch.setattr(runs_live, "stop_not_allowed", lambda root: ["t_aaaaaa"])
    code, out, _ = run("people", "remove", "Lea")
    assert code == 0 and "Stopped 1 running helper." in out

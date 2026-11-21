"""The workspace's person list (ORCH-1161): `orch people` and orch.people."""

import json

import pytest

from orch import people, tickets
from orch.errors import Refused


def _on(proj, name="Sev"):
    return people.turn_on(proj, name)


def test_off_by_default_and_nothing_is_stamped(proj, run, new_ticket):
    assert people.state(proj) == "off"
    code, out, _ = run("people", "--json")
    assert code == 0 and json.loads(out)["state"] == "off"
    tid = new_ticket()
    line = tickets.load(proj, tid)["history"][0]
    assert "person" not in line and "device" not in line


def test_owner_add_rename_rights_remove(proj, run):
    doc = _on(proj)
    owner = people.owner(doc)
    assert owner["rights"] == ["write", "decide", "start"] and people._ID_RE.fullmatch(owner["id"])
    lea = people.add(proj, "Lea")
    assert lea["rights"] == ["write"]  # a new person starts with write only
    assert people.rename(proj, "lea", "Leana")["id"] == lea["id"]  # by name, any case; the id stays
    assert people.set_rights(proj, lea["id"], ["decide", "write"])["rights"] == ["write", "decide"]
    people.remove(proj, "Leana")
    v = people.view(proj)
    gone = next(p for p in v["people"] if p["id"] == lea["id"])
    assert gone["removed"] and gone["name"] == "Leana"
    assert v["revision"] == 5
    log = people.load(proj)["log"]
    assert [x["what"] for x in log][-1] == "Removed Leana"
    assert all(x["by"] == "human:" + owner["id"] and x["device"] == "machine" for x in log)


def test_cli_round_trip(proj, run):
    assert run("people", "on", "--name", "Sev")[0] == 0
    code, out, _ = run("people", "add", "Max", "--rights", "write,decide", "--json")
    assert code == 0
    pid = json.loads(out)["person"]["id"]
    assert run("people", "rights", "Max", "none")[0] == 0
    assert people.find(people.load(proj), pid)["rights"] == []
    code, out, err = run("people", "remove", "Sev")
    assert code == 2 and "last owner" in (out + err)
    code, out, _ = run("people")
    assert "Max" in out and "Sev" in out and "owner" in out


def test_last_owner_cannot_be_removed(proj):
    _on(proj)
    with pytest.raises(Refused, match="last owner"):
        people.remove(proj, "Sev")
    assert people.owner(people.load(proj))["name"] == "Sev"


def test_owner_rights_cannot_be_lowered(proj):
    _on(proj)
    with pytest.raises(Refused, match="every right"):
        people.set_rights(proj, "Sev", ["write"])


def test_ids_are_never_reused(proj, monkeypatch):
    _on(proj)
    lea = people.add(proj, "Lea")
    people.remove(proj, "Lea")
    seq = iter(lea["id"][3:] + "abcdefghij")  # the first try draws the removed person's id again
    monkeypatch.setattr(people.secrets, "choice", lambda _alphabet: next(seq))
    again = people.add(proj, "Lea")  # the name may come back, the id never
    assert again["id"] == "pr_abcdefghij" != lea["id"]


def test_names_unique_among_active_people(proj):
    _on(proj)
    people.add(proj, "Lea")
    with pytest.raises(Refused, match="already"):
        people.add(proj, "lea")


def test_unknown_right_is_refused(proj):
    _on(proj)
    with pytest.raises(Refused, match="Unknown right"):
        people.add(proj, "Lea", ["write", "admin"])


def test_stale_revision_is_refused(proj):
    doc = _on(proj)
    people.add(proj, "Lea", expect=doc["revision"])
    with pytest.raises(Refused, match="changed meanwhile"):
        people.add(proj, "Max", expect=doc["revision"])


def test_helper_environment_is_refused(proj, monkeypatch):
    _on(proj)
    monkeypatch.setenv("ORCH_AGENT", "claude")
    for call in (
        lambda: people.add(proj, "Lea"),
        lambda: people.rename(proj, "Sev", "X"),
        lambda: people.set_rights(proj, "Sev", ["write"]),
        lambda: people.remove(proj, "Sev"),
    ):
        with pytest.raises(Refused, match="owner at this computer"):
            call()
    assert len(people.load(proj)["people"]) == 1


def test_turn_on_from_a_helper_is_refused(proj, monkeypatch):
    monkeypatch.setenv("ORCH_AGENT", "claude")
    with pytest.raises(Refused, match="owner at this computer"):
        people.turn_on(proj, "Me")
    assert people.state(proj) == "off"


def test_broken_file_fails_closed(proj, new_ticket):
    _on(proj)
    people.path(proj).write_text("{not json", encoding="utf-8")
    assert people.state(proj) == "broken"
    assert people.names(proj) == {}
    with pytest.raises(Refused):
        people.add(proj, "Lea")
    with pytest.raises(Refused, match="damaged"):
        people.turn_on(proj, "Again")
    tid = new_ticket()
    assert "person" not in tickets.load(proj, tid)["history"][0]


def test_file_without_owner_is_broken(proj):
    doc = _on(proj)
    doc["people"][0]["owner"] = False
    people.path(proj).write_text(json.dumps(doc), encoding="utf-8")
    assert people.state(proj) == "broken"


def test_new_lines_record_person_and_device(proj, run, new_ticket):
    owner = people.owner(_on(proj))
    tid = new_ticket()
    assert run("check", "add", tid, "Step one", "--by", "human:tester")[0] == 0
    hist = tickets.load(proj, tid)["history"]
    assert hist and all(h["person"] == owner["id"] and h["device"] == "machine" for h in hist)


def test_helpers_and_phones_are_not_stamped(proj, run, new_ticket, monkeypatch):
    _on(proj)
    tid = new_ticket()
    assert run("check", "add", tid, "Helper step", "--by", "agent:claude")[0] == 0
    t = tickets.load(proj, tid)
    agent_line = t["history"][-1]
    assert agent_line["by"] == "agent:claude" and "person" not in agent_line
    phone = {"by": "human:Pixel", "via": "phone", "text": "x"}
    people.stamp(proj, phone)
    assert "person" not in phone
    monkeypatch.setenv("ORCH_AGENT", "claude")
    claimed = {"by": "human:tester", "via": "cli", "text": "x"}
    people.stamp(proj, claimed)  # a helper claiming human: is not a person
    assert "person" not in claimed


def test_old_lines_are_never_changed(proj, run, new_ticket):
    tid = new_ticket()  # made while the list was off
    before = tickets.load(proj, tid)["history"][0]
    _on(proj)
    assert run("check", "add", tid, "Later", "--by", "human:tester")[0] == 0
    hist = tickets.load(proj, tid)["history"]
    assert hist[0] == before and "person" not in hist[0]
    assert "person" in hist[-1]


def test_names_show_for_people_and_old_actors_stay(proj):
    owner = people.owner(_on(proj))
    lea = people.add(proj, "Lea")
    assert people.show(proj, "human:" + lea["id"]) == "Lea"
    people.rename(proj, "Lea", "Leana")
    assert people.show(proj, "human:" + lea["id"]) == "Leana"  # a rename shows everywhere at once
    people.remove(proj, "Leana")
    assert people.show(proj, "human:" + lea["id"]) == "Leana (removed)"
    assert people.show(proj, "human:lume") == "human:lume"  # old history keeps its old names
    assert people.show(proj, "human:ph_8d2k1m0q7z") == "human:ph_8d2k1m0q7z"
    assert people.show(proj, "agent:claude") == "agent:claude"
    assert people.names(proj)[owner["id"]] == "Sev"


def test_lines_with_person_fields_still_validate(proj, new_ticket, validate):
    _on(proj)
    tid = new_ticket()
    validate(tickets.load(proj, tid))


def test_people_file_is_machine_local(proj):
    _on(proj)
    assert people.path(proj).relative_to(proj).parts[:2] == (".orch", "local")

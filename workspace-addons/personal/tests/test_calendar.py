"""Calendar: one week of every calendar, and per calendar what helpers may use (ORCH-651)."""

import json
import os
import sys
from pathlib import Path

import pytest

from orch_personal import api, cli, store
from orch_personal import calendar as cal

WORK, PRIV, FAM = "EX-work-1", "IC-private-2", "IC-family-3"
HELPER = {"ORCH_RUN": "r_test", "ORCH_AGENT": "claude", "ORCH_TICKET": "t_abc123"}


def answer(status="full", events=None, calendars=None):
    return {
        "schema": "orch.calendar.read/1",
        "status": status,
        "zone": "Europe/Zurich",
        "read_at": "2026-11-18T07:00:00Z",
        "calendars": calendars
        if calendars is not None
        else [
            {"id": WORK, "title": "Work", "account": "Exchange", "kind": "exchange", "shared": False},
            {"id": PRIV, "title": "Private", "account": "iCloud", "kind": "icloud", "shared": False},
            {"id": FAM, "title": "Family", "account": "iCloud", "kind": "icloud", "shared": True},
        ],
        "events": events
        if events is not None
        else [
            ev(
                WORK,
                "2026-11-18T09:00:00+01:00",
                "2026-11-18T10:00:00+01:00",
                "Kundentermin Helvetia Logistik",
                ["Petra Zingg"],
            ),
            ev(PRIV, "2026-11-18T12:15:00+01:00", "2026-11-18T13:15:00+01:00", "Lunch mit Jonas"),
            ev(FAM, "2026-11-18T17:30:00+01:00", "2026-11-18T19:00:00+01:00", "Elternabend Schule Noah"),
            ev(WORK, "2026-11-19T09:00:00+01:00", "2026-11-19T10:00:00+01:00", "Release-Abstimmung"),
            ev(PRIV, "2026-11-19T09:30:00+01:00", "2026-11-19T10:30:00+01:00", "Handwerker Heizung"),
            ev(WORK, "2026-11-19T14:00:00+01:00", "2026-11-19T15:00:00+01:00", "Abgesagt", declined=True),
            ev(
                WORK,
                "2026-11-19T16:00:00+01:00",
                "2026-11-19T17:00:00+01:00",
                "Fokuszeit",
                availability="free",
            ),
            {
                "cal": PRIV,
                "start": "2026-11-20",
                "end": "2026-11-21",
                "all_day": True,
                "title": "Abgabe Steuerunterlagen",
                "people": [],
                "declined": False,
                "availability": "free",
            },
            ev("unknown-cal", "2026-11-18T08:00:00+01:00", "2026-11-18T09:00:00+01:00", "Ghost"),
        ],
        "error": None,
    }


def ev(cal_id, start, end, title, people=(), declined=False, availability="busy"):
    return {
        "cal": cal_id,
        "start": start,
        "end": end,
        "all_day": False,
        "title": title,
        "people": list(people),
        "declined": declined,
        "availability": availability,
        "tz": "Europe/Zurich",
    }


@pytest.fixture
def reader(tmp_path, monkeypatch):
    """A stand-in for the Calendar app reader: writes the answer in reader.json to --out."""
    data = tmp_path / "reader.json"
    calls = tmp_path / "calls.txt"
    data.write_text(json.dumps(answer()), encoding="utf-8")
    script = tmp_path / "fake_reader.py"  # run with this Python: works on Windows too
    script.write_text(
        "import sys\n"
        "a = sys.argv[1:]\n"
        f"open({str(calls)!r}, 'a').write(' '.join(a[2:]) + '\\n')\n"
        "out = a[a.index('--out') + 1]\n"
        f"open(out, 'w').write(open({str(data)!r}).read())\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ORCH_PERSONAL_CALENDAR_READER", str(script))
    cal._OWNER_CACHE.clear()
    monkeypatch.setattr(cal, "_now", lambda: cal.dt.datetime(2026, 11, 18, 7, 0, tzinfo=cal.dt.UTC))

    def set_answer(a):
        data.write_text(json.dumps(a), encoding="utf-8")
        cal._OWNER_CACHE.clear()

    set_answer.calls = calls
    return set_answer


def person():
    return api.Who(helper=False, by="human:severin")


def helper():
    return api.Who(helper=True, by="agent:claude", ticket="t_abc123")


@pytest.fixture
def added(ws, reader):
    api.add_part(ws, person(), "calendar")
    return ws


def test_calendar_can_be_added_and_is_no_longer_coming_soon(ws):
    assert "calendar" in store.PARTS
    assert "calendar" not in store.SOON
    api.add_part(ws, person(), "calendar")
    assert store.settings(ws)["parts"]["calendar"]["cals"] == {}
    with pytest.raises(store.Refused, match="Only the person"):
        api.add_part(ws, helper(), "calendar")


def test_person_sees_work_private_and_family_in_one_week(added):
    d = api.calendar_week(added, person(), "2026-11-16", 7)
    assert [c["title"] for c in d["calendars"]] == ["Work", "Private", "Family"]
    titles = [e["title"] for e in d["events"]]
    assert "Kundentermin Helvetia Logistik" in titles
    assert "Lunch mit Jonas" in titles and "Elternabend Schule Noah" in titles
    assert "Ghost" not in titles  # an event of a calendar the reader did not list
    assert d["overlaps"][0]["a"]["title"] == "Release-Abstimmung"
    assert d["overlaps"][0]["minutes"] == 30
    assert all(c["level"] == "nothing" for c in d["calendars"])
    assert d["calendars"][0]["suggest_level"] == "titles"  # Work (Exchange) is offered preset, not set
    assert d["calendars"][1]["suggest_level"] is None


def test_every_calendar_starts_at_nothing_for_helpers(added):
    with pytest.raises(store.Refused, match="shares no calendar"):
        api.calendar_week(added, helper(), "2026-11-16", 7)


def test_titles_busy_and_nothing_per_calendar(added):
    api.calendar_rule(added, person(), "Work", "titles", None)
    api.calendar_rule(added, person(), FAM, "busy", None)
    d = api.calendar_week(added, helper(), "2026-11-16", 7)
    by_cal = {}
    for e in d["events"]:
        by_cal.setdefault(e["calendar"], []).append(e)
    assert set(by_cal) == {"Work", "Family"}  # Private stays at nothing
    work = [e["title"] for e in by_cal["Work"]]
    assert "Kundentermin Helvetia Logistik" in work and "Abgesagt" not in work  # declined never shown
    assert by_cal["Work"][0]["people"] == ["Petra Zingg"]
    fam = by_cal["Family"][0]
    assert fam["title"] == "Busy" and "people" not in fam
    assert fam["start"] == "2026-11-18T17:30+01:00"
    assert "Elternabend" not in json.dumps(d) and "Lunch" not in json.dumps(d)
    assert [c["title"] for c in d["calendars"]] == ["Work", "Family"]
    assert d["data_note"]


def test_moving_a_calendar_down_hides_titles_at_once(added):
    api.calendar_rule(added, person(), "Work", "titles", None)
    assert "Release-Abstimmung" in json.dumps(api.calendar_week(added, helper(), "2026-11-16", 7))
    api.calendar_rule(added, person(), "Work", "busy", None)
    d = api.calendar_week(added, helper(), "2026-11-16", 7)
    assert "Release-Abstimmung" not in json.dumps(d)
    assert {e["title"] for e in d["events"]} == {"Busy"}


def test_helper_cannot_change_rules_or_source_or_allow(added):
    for call in (
        lambda: api.calendar_rule(added, helper(), "Private", "titles", None),
        lambda: api.calendar_rule(added, helper(), None, None, "suggest"),
        lambda: api.calendar_source(added, helper(), "app"),
        lambda: api.calendar_allow(added, helper()),
        lambda: api.calendar_answer(added, helper(), "x", True),
    ):
        with pytest.raises(store.Refused, match="Only the person"):
            call()


def test_new_calendar_or_changed_id_starts_at_nothing(added, reader):
    api.calendar_rule(added, person(), "Work", "titles", None)
    a = answer()
    a["calendars"][0]["id"] = "EX-work-NEW"  # the account was set up again: new id, same name
    for e in a["events"]:
        if e["cal"] == WORK:
            e["cal"] = "EX-work-NEW"
    reader(a)
    d = api.calendar_week(added, helper(), "2026-11-16", 7)  # the old Work rule matches nothing any more
    assert d["events"] == [] and d["calendars"] == []
    d = api.calendar_week(added, person(), "2026-11-16", 7)
    assert d["calendars"][0]["new"] is True and d["calendars"][0]["level"] == "nothing"


def test_helper_sees_only_calendars_it_may_use(added):
    api.calendar_rule(added, person(), "Work", "busy", None)
    d = api.calendar_calendars(added, helper())
    assert d["calendars"] == [{"title": "Work", "uses": "Busy times"}]


def test_free_times_count_busy_only_and_skip_free_and_all_day(added):
    api.calendar_rule(added, person(), "Work", "busy", None)
    d = api.calendar_free(added, helper(), "2026-11-19", 1, 60)
    assert d["slots"][0] == {"start": "2026-11-19T08:00+01:00", "end": "2026-11-19T09:00+01:00"}
    assert {"start": "2026-11-19T10:00+01:00", "end": "2026-11-19T18:00+01:00"} in d["slots"]
    assert "calendars helpers may use" in d["note"]  # never "you are free"


def test_rule_narrowed_during_a_read_applies(added, monkeypatch):
    api.calendar_rule(added, person(), "Work", "titles", None)
    real = cal.read

    def slow_read(root, frm, days=7):
        ans = real(root, frm, days)
        cal.set_level(root, WORK, "nothing")  # the person closes Work while the source is answering
        return ans

    monkeypatch.setattr(cal, "read", slow_read)
    d = api.calendar_week(added, helper(), "2026-11-16", 7)
    assert d["events"] == [] and "Helvetia" not in json.dumps(d)


def test_busy_all_day_blocks_free_times(added, reader):
    a = answer(
        events=[
            {
                "cal": WORK,
                "start": "2026-11-19",
                "end": "2026-11-20",
                "all_day": True,
                "title": "Ferien",
                "people": [],
                "declined": False,
                "availability": "busy",
            }
        ]
    )
    reader(a)
    api.calendar_rule(added, person(), "Work", "busy", None)
    assert api.calendar_free(added, helper(), "2026-11-19", 2, 60)["slots"] == [
        {"start": "2026-11-20T08:00+01:00", "end": "2026-11-20T18:00+01:00"}
    ]


def test_cut_answer_is_never_used_for_free_times(added, reader):
    a = answer()
    a["error"] = "More than 2000 events; only the first 2000 are shown."
    reader(a)
    api.calendar_rule(added, person(), "Work", "busy", None)
    with pytest.raises(store.Refused, match="too many events"):
        api.calendar_free(added, helper(), "2026-11-19", 1, 60)


def test_suggest_lands_in_needs_you_and_opens_only_on_the_persons_click(added):
    api.calendar_rule(added, person(), "Work", "titles", None)
    s = api.calendar_suggest(added, helper(), "Offerte Helvetia durchgehen", "2026-11-19T15:00+01:00", 60)
    needs = api.today(added, person())["needs_you"]
    assert any(n.get("suggestion") == s["id"] for n in needs)
    assert not api.today(added, helper())["needs_you"]
    api.calendar_answer(added, person(), s["id"], True)
    ics = (store.base(added) / "calendar" / f"suggested-{s['id']}.ics").read_text()
    assert "SUMMARY:Offerte Helvetia durchgehen" in ics
    assert "DTSTART:20261119T140000Z" in ics and "DTEND:20261119T150000Z" in ics
    assert "DESCRIPTION" not in ics and "ATTENDEE" not in ics
    with pytest.raises(store.Refused, match="no longer open"):
        api.calendar_answer(added, person(), s["id"], True)


def test_suggest_refused_when_rule_is_never(added):
    api.calendar_rule(added, person(), None, None, "never")
    with pytest.raises(store.Refused, match="does not let helpers suggest"):
        api.calendar_suggest(added, helper(), "X", "2026-11-19T15:00+01:00", 60)


def test_ics_title_cannot_break_out():
    row = {
        "id": "abc",
        "title": "A\r\nATTENDEE:mailto:x@y;B,C",
        "start": "2026-11-19T15:00+01:00",
        "minutes": 30,
    }
    out = cal.ics(row)
    assert "\r\nATTENDEE" not in out
    assert "SUMMARY:A ATTENDEE:mailto:x@y\\;B\\,C" in out


def test_permission_states(added, reader):
    reader(answer(status="not_asked", events=[], calendars=[]))
    with pytest.raises(store.Refused, match="needs your permission"):
        api.calendar_week(added, person(), "2026-11-16", 7)
    t = api.today(added, person())
    assert any(n["action"] == "Allow calendars" for n in t["needs_you"])
    reader(answer(status="denied", events=[], calendars=[]))
    st = api.calendar_check(added, person())
    assert st["status"] == "permission" and "System Settings" in st["problem"]
    reader(answer())
    st = api.calendar_allow(added, person())
    assert st["status"] == "works"
    assert "request" in reader.calls.read_text()


def test_broken_answer_stops_the_way_in(added, reader):
    reader({"schema": "something else"})
    with pytest.raises(store.Refused):
        api.calendar_week(added, person(), "2026-11-16", 7)
    t = api.today(added, person())
    assert any(n["title"] == "Calendar: the way in stopped working" for n in t["needs_you"])


def test_text_is_cleaned_and_bad_times_dropped(added, reader):
    a = answer(
        events=[
            ev(
                WORK, "2026-11-18T09:00:00+01:00", "2026-11-18T10:00:00+01:00", "Line\nbreak\x00 " + "x" * 400
            ),
            ev(WORK, "2026-11-18T09:00:00", "2026-11-18T10:00:00", "No offset"),
            ev(WORK, "2026-11-18T11:00:00+01:00", "2026-11-18T10:00:00+01:00", "Ends before start"),
        ]
    )
    reader(a)
    d = api.calendar_week(added, person(), "2026-11-16", 7)
    assert len(d["events"]) == 1
    assert "\n" not in d["events"][0]["title"] and len(d["events"][0]["title"]) == 200


def test_days_are_bounded(added):
    with pytest.raises(store.Refused, match="1 to 35"):
        api.calendar_week(added, person(), "2026-11-16", 36)


def test_dst_change_keeps_local_times(added, reader):
    reader(
        answer(
            events=[
                ev(WORK, "2027-03-26T09:00:00+01:00", "2027-03-26T10:00:00+01:00", "Before"),
                ev(WORK, "2027-03-29T09:00:00+02:00", "2027-03-29T10:00:00+02:00", "After"),
            ]
        )
    )
    api.calendar_rule(added, person(), "Work", "titles", None)
    d = api.calendar_week(added, helper(), "2027-03-26", 7)
    assert [e["start"][11:16] for e in d["events"]] == ["09:00", "09:00"]
    assert d["events"][1]["start"].endswith("+02:00")


def test_calendar_way_in_feeds_calendar_and_helpers_cannot_ask_it_directly(added, tmp_path, reader):
    from orch_personal import ways

    w = ways.folder(added) / "outlook-calendar"
    w.mkdir(parents=True)
    (w / "answer.json").write_text(json.dumps(answer()), encoding="utf-8")
    (w / "read.py").write_text("print(open('answer.json').read())\n", encoding="utf-8")
    (w / "way.toml").write_text(
        'name = "Outlook calendar"\npart = "calendar"\n'
        f"selfcheck = ['{sys.executable}', '-c', 'pass']\n"  # literal strings: Windows paths need no escapes
        f"[actions]\nread = ['{sys.executable}', 'read.py']\n",
        encoding="utf-8",
    )
    api.way_turn(added, person(), "outlook-calendar", True)
    api.calendar_source(added, person(), "way:outlook-calendar")
    os.environ.pop("ORCH_PERSONAL_CALENDAR_READER")
    api.calendar_rule(added, person(), "Work", "titles", None)
    d = api.calendar_week(added, helper(), "2026-11-16", 7)
    assert "Kundentermin Helvetia Logistik" in json.dumps(d) and "Lunch" not in json.dumps(d)
    with pytest.raises(store.Refused, match="feeds Calendar"):
        api.way_ask(added, helper(), "outlook-calendar", "read", {})


def test_changing_source_resets_every_calendar_to_nothing(added, tmp_path):
    from orch_personal import ways

    w = ways.folder(added) / "outlook-calendar"
    w.mkdir(parents=True)
    (w / "way.toml").write_text('name = "Outlook calendar"\npart = "calendar"\n[actions]\n', encoding="utf-8")
    api.calendar_rule(added, person(), "Work", "titles", None)
    api.calendar_source(added, person(), "way:outlook-calendar")
    assert store.settings(added)["parts"]["calendar"]["cals"] == {}


def test_unreadable_rules_fall_back_to_closed(added):
    f = store.base(added) / "settings.json"
    data = json.loads(f.read_text())
    data["parts"]["calendar"]["cals"] = {WORK: {"level": "everything"}, "": {"level": "titles"}}
    data["parts"]["calendar"]["moves"] = "write"
    f.write_text(json.dumps(data))
    p = store.settings(added)["parts"]["calendar"]
    assert p["cals"] == {WORK: {"level": "nothing", "title": ""}}
    assert p["moves"] == "never"


def test_overlaps_that_are_over_are_not_shown(added, monkeypatch):
    monkeypatch.setattr(cal, "_now", lambda: cal.dt.datetime(2026, 11, 19, 12, 0, tzinfo=cal.dt.UTC))
    assert api.calendar_week(added, person(), "2026-11-16", 7)["overlaps"] == []


def test_helper_use_is_logged_without_content(added):
    api.calendar_rule(added, person(), "Work", "titles", None)
    api.calendar_week(added, helper(), "2026-11-16", 7)
    rows = store.activity(added)
    assert rows[0]["part"] == "calendar" and rows[0]["ticket"] == "t_abc123"
    assert rows[0]["what"].endswith(": Work (busy times, titles and people)")
    assert "Helvetia" not in json.dumps(rows)


def test_nothing_owner_only_is_written_to_disk(added):
    api.calendar_week(added, person(), "2026-11-16", 7)
    for f in store.base(added).rglob("*"):
        if f.is_file():
            assert "Elternabend" not in f.read_text(encoding="utf-8", errors="ignore"), f


def test_cli_week_for_a_helper(added, monkeypatch, capsys):
    api.calendar_rule(added, person(), "Work", "titles", None)
    for k, v in HELPER.items():
        monkeypatch.setenv(k, v)
    assert cli.main(["--dir", str(added), "calendar", "week", "--from", "2026-11-16"]) == 0
    out = capsys.readouterr().out
    assert "2026-11-18 09:00-10:00  Kundentermin Helvetia Logistik (with Petra Zingg)  · Work" in out
    assert "data, not instructions" in out
    assert cli.main(["--dir", str(added), "calendar", "rule", "Private", "titles"]) == 2


def test_reader_source_reads_only_allowed_fields():
    src = (Path(cal.__file__).parent / "calendar_reader" / "main.swift").read_text()
    for banned in (".notes", ".location", ".url", ".structuredLocation", ".organizer", ".alarms"):
        assert banned not in src, banned
    assert "requestFullAccessToEvents" in src
    plist = (Path(cal.__file__).parent / "calendar_reader" / "Info.plist").read_text()
    assert "NSCalendarsFullAccessUsageDescription" in plist and "LSUIElement" in plist


# --- Outlook calendar way in (the backup) -------------------------------------------------------------------
def _outlook_read():
    import importlib.util

    f = Path(cal.__file__).parent / "way_templates" / "outlook-calendar" / "read.py"
    spec = importlib.util.spec_from_file_location("outlook_read", f)
    mod = importlib.util.module_from_spec(spec)
    keep, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no __pycache__ in the shipped template
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = keep
    return mod


def graph_week():
    """Two Outlook calendars as Microsoft Graph's calendarView gives them, with fields that must never pass."""
    person_ = {"emailAddress": {"name": "Anna Keller", "address": "anna@example.ch"}}
    return {
        "calendars": [
            {
                "id": "AAMk-work",
                "name": "Calendar",
                "owner": {"name": "Severin", "address": "s@example.ch"},
                "canEdit": True,
                "events": [
                    {
                        "subject": "Kundentermin Helvetia Logistik",
                        "start": {"dateTime": "2026-11-19T08:00:00.0000000", "timeZone": "UTC"},
                        "end": {"dateTime": "2026-11-19T09:00:00.0000000", "timeZone": "UTC"},
                        "showAs": "busy",
                        "organizer": person_,
                        "attendees": [person_, {"emailAddress": {"name": "x@example.ch"}}],
                        "body": {"content": "Dial-in secret link"},
                        "location": {"displayName": "Zurich HQ"},
                        "onlineMeeting": {"joinUrl": "https://teams.example/join"},
                        "webLink": "https://outlook.example/e/1",
                    },
                    {
                        "subject": "Workshop",
                        "start": {"dateTime": "2026-11-20T13:00:00", "timeZone": "W. Europe Standard Time"},
                        "end": {"dateTime": "2026-11-20T15:00:00", "timeZone": "W. Europe Standard Time"},
                        "showAs": "oof",
                    },
                    {
                        "subject": "Declined call",
                        "start": {"dateTime": "2026-11-18T10:00:00", "timeZone": "UTC"},
                        "end": {"dateTime": "2026-11-18T10:30:00", "timeZone": "UTC"},
                        "responseStatus": {"response": "declined"},
                    },
                    {
                        "subject": "Cancelled",
                        "isCancelled": True,
                        "start": {"dateTime": "2026-11-18T11:00:00", "timeZone": "UTC"},
                        "end": {"dateTime": "2026-11-18T12:00:00", "timeZone": "UTC"},
                    },
                    {
                        "subject": "No zone",
                        "start": {"dateTime": "2026-11-18T11:00:00", "timeZone": "Mars/Olympus"},
                        "end": {"dateTime": "2026-11-18T12:00:00", "timeZone": "Mars/Olympus"},
                    },
                    {
                        "subject": "Holiday",
                        "isAllDay": True,
                        "start": {"dateTime": "2026-11-17T00:00:00.0000000", "timeZone": "UTC"},
                        "end": {"dateTime": "2026-11-18T00:00:00.0000000", "timeZone": "UTC"},
                        "showAs": "free",
                    },
                ],
            },
            {"id": "AAMk-team", "name": "Team", "canShare": False, "canEdit": False, "events": []},
            {"name": "no id"},
        ]
    }


def test_outlook_answer_becomes_the_reader_shape_without_addresses_or_bodies():
    r = _outlook_read()
    raw = r.convert(graph_week(), "Europe/Zurich", now="2026-11-18T07:00:00+00:00")
    text = json.dumps(raw)
    for never in (
        "example.ch",
        "Dial-in",
        "Zurich HQ",
        "teams.example",
        "outlook.example",
        "Cancelled",
        "No zone",
    ):
        assert never not in text
    ans = cal.clean(raw)
    assert [c["id"] for c in ans["calendars"]] == ["outlook:AAMk-work", "outlook:AAMk-team"]
    assert ans["calendars"][0]["kind"] == "exchange" and ans["calendars"][1]["shared"] is True
    by = {e["title"]: e for e in ans["events"]}
    assert set(by) == {"Kundentermin Helvetia Logistik", "Workshop", "Declined call", "Holiday"}
    k = by["Kundentermin Helvetia Logistik"]
    assert k["start"].isoformat() == "2026-11-19T08:00:00+00:00" and k["people"] == ["Anna Keller"]
    assert by["Workshop"]["start"].utcoffset().total_seconds() == 3600
    assert by["Workshop"]["availability"] == "unavailable"
    assert by["Declined call"]["declined"] is True
    assert by["Holiday"]["all_day"] is True and str(by["Holiday"]["start"]) == "2026-11-17"


def test_outlook_way_without_a_fetch_command_says_it_is_not_set_up(tmp_path):
    r = _outlook_read()
    (tmp_path / "fetch.json").write_text('{"fetch": []}', encoding="utf-8")
    with pytest.raises(r.Stop, match="not set up yet"):
        r.read({"from": "2026-11-16", "days": 7}, tmp_path)
    with pytest.raises(r.Stop, match="1 to 35"):
        r.read({"from": "2026-11-16", "days": 90}, tmp_path)


def test_outlook_way_is_added_off_and_feeds_calendar_with_the_same_rules(added, tmp_path):
    from orch_personal import ways

    with pytest.raises(store.Refused, match="Only the person"):
        api.calendar_outlook(added, helper())
    d = api.calendar_outlook(added, person())
    w = Path(d["dir"])
    assert sorted(f.name for f in w.iterdir()) == ["check.py", "fetch.json", "read.py", "way.toml"]
    with pytest.raises(store.Refused, match="already"):
        api.calendar_outlook(added, person())
    assert not ways.saved(added).get("outlook-calendar", {}).get("on")

    # the person sets the command that reads Outlook (here a stand-in printing Graph's answer)
    (tmp_path / "graph.json").write_text(json.dumps(graph_week()), encoding="utf-8")
    (w / "fetch.json").write_text(
        json.dumps(
            {"fetch": [sys.executable, "-c", f"print(open({str(tmp_path / 'graph.json')!r}).read())"]}
        ),
        encoding="utf-8",
    )
    toml = (w / "way.toml").read_text(encoding="utf-8").replace('"python3"', f"'{sys.executable}'")
    (w / "way.toml").write_text(toml, encoding="utf-8")  # Windows CI has no python3 on PATH
    api.way_turn(added, person(), "outlook-calendar", True)
    api.calendar_source(added, person(), "way:outlook-calendar")
    assert ways.check(added, "outlook-calendar")["status"] == "works"
    assert sorted(f.name for f in w.iterdir()) == ["check.py", "fetch.json", "read.py", "way.toml"]

    os.environ.pop("ORCH_PERSONAL_CALENDAR_READER")
    with pytest.raises(store.Refused, match="shares no calendar"):  # every Outlook calendar starts at nothing
        api.calendar_week(added, helper(), "2026-11-16", 7)
    api.calendar_rule(added, person(), "Calendar", "busy", None)
    d = api.calendar_week(added, helper(), "2026-11-16", 7)
    assert d["events"] and "Kundentermin" not in json.dumps(d) and "Declined" not in json.dumps(d)
    api.calendar_rule(added, person(), "Calendar", "titles", None)
    d = json.dumps(api.calendar_week(added, helper(), "2026-11-16", 7))
    assert "Kundentermin Helvetia Logistik" in d and "Anna Keller" in d and "example.ch" not in d

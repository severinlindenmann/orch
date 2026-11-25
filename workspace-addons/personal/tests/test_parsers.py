"""Parsers that read text from outside (notes, calendar answers, step lines): CRLF, umlauts, odd Unicode (R1.6)."""

import datetime as dt
import os
import unicodedata
from pathlib import Path

import pytest

from orch_personal import calendar as cal
from orch_personal import cli, store
from orch_personal.notes import Vault


def put(folder: Path, name: str, data: bytes | str) -> None:
    path = folder / (name + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def test_notes_crlf_fences_and_links(tmp_path: Path) -> None:
    put(tmp_path, "Büro", "x")
    put(tmp_path, "Alpha", "[[Büro]]\r\n```\r\n[[Hidden]]\r\n```\r\n[[Alpha]]\r\n")
    put(tmp_path, "Hidden", "x")
    vault = Vault(tmp_path)
    assert vault.get("Alpha").links == ("Büro", "Alpha")
    assert vault.get("Hidden").linked_from == ()


def test_notes_bom_and_invalid_bytes(tmp_path: Path) -> None:
    put(tmp_path, "Bom", b"\xef\xbb\xbf[[Ziel]]\r\n")
    put(tmp_path, "Ziel", b"gr\xfc\xdfe \xff\r\n")
    vault = Vault(tmp_path)
    assert vault.get("Bom").links == ("Ziel",)
    assert "\ufffd" in vault.text("Ziel")


def test_notes_link_and_search_match_across_unicode_forms(tmp_path: Path) -> None:
    # macOS and iCloud store file names decomposed, people type composed
    put(tmp_path, unicodedata.normalize("NFD", "Übersicht"), "Grüße")
    put(tmp_path, "Index", unicodedata.normalize("NFC", "[[Übersicht]]"))
    vault = Vault(tmp_path)
    assert len(vault.get("Index").links) == 1
    assert vault.get(unicodedata.normalize("NFC", "Übersicht")).title
    hits = vault.find(unicodedata.normalize("NFC", "grüße"))
    assert [n.title for n, _ in hits] == [unicodedata.normalize("NFD", "Übersicht")]


def test_notes_snippet_with_crlf(tmp_path: Path) -> None:
    put(tmp_path, "Meeting", "Titel\r\nDas Wärmepumpen-Angebot ist da\r\n")
    ((_note, snippet),) = Vault(tmp_path).find("wärmepumpen")
    assert snippet == "Das Wärmepumpen-Angebot ist da"


def test_parse_step_pipes_umlauts_and_crlf() -> None:
    assert cli._parse_step("Offerte prüfen | Zoë | 2026-11-20") == {
        "text": "Offerte prüfen",
        "who": "Zoë",
        "due": "2026-11-20",
    }
    assert cli._parse_step("Nur Text\r\n") == {"text": "Nur Text", "who": "", "due": ""}


def test_parse_day(monkeypatch) -> None:
    assert cal.parse_day("2026-11-16") == dt.date(2026, 11, 16)
    assert cal.parse_day("today", None) == dt.date.today()
    assert cal.parse_day(None) == dt.date.today()
    with pytest.raises(cal.Refused, match="YYYY-MM-DD"):
        cal.parse_day("16.11.2026")
    assert cal.week_start(dt.date(2026, 11, 18)) == dt.date(2026, 11, 16)


def _raw(**event):
    base = {
        "cal": "c1",
        "start": "2026-11-18T09:00:00+01:00",
        "end": "2026-11-18T10:00:00+01:00",
        "title": "x",
    }
    return {
        "schema": cal.SCHEMA,
        "status": "full",
        "zone": "Europe/Zurich",
        "calendars": [{"id": "c1", "title": "Büro", "kind": "icloud"}],
        "events": [{**base, **event}],
    }


def test_calendar_clean_crlf_umlauts_and_controls() -> None:
    got = cal.clean(_raw(title="Zügel\r\nbesprechung\x00 ✓", people=["Jörg\r\n", "  ", "Zoë"]))
    ev = got["events"][0]
    assert ev["title"] == "Zügel besprechung ✓"
    assert ev["people"] == ["Jörg", "Zoë"]
    assert got["calendars"][0]["title"] == "Büro"


def test_calendar_clean_drops_bad_times_and_unknown_calendars() -> None:
    raw = _raw()
    raw["events"] += [
        {"cal": "c1", "start": "2026-11-18T09:00:00", "end": "2026-11-18T10:00:00", "title": "no offset"},
        {"cal": "c1", "start": "2026-11-18T10:00:00+01:00", "end": "2026-11-18T09:00:00+01:00"},
        {"cal": "other", "start": "2026-11-18T09:00:00Z", "end": "2026-11-18T10:00:00Z"},
        "junk",
    ]
    assert len(cal.clean(raw)["events"]) == 1
    with pytest.raises(cal.Refused):
        cal.clean({"schema": "nope"})


def test_calendar_clean_all_day_and_unknown_zone() -> None:
    raw = _raw(all_day=True, start="2026-11-18", end="2026-11-19")
    raw["zone"] = "Nowhere/Land"
    got = cal.clean(raw)
    assert got["events"][0]["start"] == dt.date(2026, 11, 18)
    assert str(got["zone"]) == "UTC"


def test_ics_uses_crlf_and_escapes_title() -> None:
    row = {
        "id": "s_1",
        "title": "Käse; Wein, \\ mehr\r\nBEGIN:VEVENT",
        "start": "2026-11-18T09:00:00+01:00",
        "minutes": 30,
    }
    text = cal.ics(row)
    lines = text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR"
    assert "SUMMARY:Käse\\; Wein\\, \\\\ mehr BEGIN:VEVENT" in lines
    assert "DTSTART:20261118T080000Z" in lines
    assert "DTEND:20261118T083000Z" in lines
    assert lines.count("BEGIN:VEVENT") == 1


def test_activity_log_crlf_and_umlauts(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Wörkspace mit Leerzeichen"
    (root / ".orch").mkdir(parents=True)
    store.log(root, "notes", "Notiz für Zoë gelesen", "agent:claude")
    f = store.base(root) / "activity.jsonl"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    store.log(root, "notes", "zweite", "agent:claude")
    rows = store.activity(root)
    assert [r["what"] for r in rows] == ["zweite", "Notiz für Zoë gelesen"]
    assert os.fspath(root) not in f.read_text(encoding="utf-8")

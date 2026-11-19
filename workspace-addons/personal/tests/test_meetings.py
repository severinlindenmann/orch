"""Meetings (ORCH-650): a recorder way in hands over finished meetings; nothing is read before the person says that
everyone on the call agreed; next steps become tickets; helpers read only what the rules allow."""

import json
import stat
import sys

import pytest
from conftest import as_helper, jrun
from test_ways import make_way

PY = sys.executable

# A fake recorder: meetings come from meetings.json in its data folder; every call is logged there, so a test can
# see what was read. Two pages per meeting; rev "r2" on page 2 when the file says it changes while being read.
RECORDER = r"""
import json, os, sys, pathlib
req = json.load(sys.stdin)
data = pathlib.Path(os.environ["ORCH_PERSONAL_WAY_DATA"])
src = json.loads((data / "meetings.json").read_text())
with open(data / "calls.log", "a") as f:
    f.write(json.dumps(req) + "\n")
if req["action"] == "meetings":
    print(json.dumps({"meetings": [{k: v for k, v in m.items() if k in ("ref", "rev", "title", "started",
        "minutes", "people")} for m in src]}))
    sys.exit(0)
v = req["values"]
m = next(x for x in src if x["ref"] == v["ref"])
lines = m["transcript"]
if v.get("cursor") is None:
    print(json.dumps({"rev": m["rev"], "summary": m.get("summary", ""), "steps": m.get("steps", []),
                      "transcript": lines[:2], "next": "p2" if len(lines) > 2 else None}))
else:
    rev = m.get("rev_page2", m["rev"])
    print(json.dumps({"rev": rev, "transcript": lines[2:], "next": None}))
"""

HELVETIA = {
    "ref": "yg-2026-11-19-0900",
    "rev": "r1",
    "title": "Kundentermin Helvetia Logistik",
    "started": "2026-11-19T09:00:00Z",
    "minutes": 46,
    "people": ["Lea Brunner", "Marco Keller", "Petra Zingg"],
    "summary": "Helvetia wants route planning live before the Christmas peak 2027.",
    "steps": [
        {"text": "Offerte v2 mit Fixpreis Phase 1 senden", "who": "Lea Brunner", "due": "2026-11-20"},
        {"text": "Testzugang Lagersystem anfragen", "who": "Marco Keller", "due": "2026-11-19"},
    ],
    "transcript": [
        {
            "who": "Petra Zingg",
            "at": "09:02",
            "text": "Für uns ist entscheidend, dass die Tourenplanung läuft.",
        },
        {"who": "Severin", "at": "09:03", "text": "Phase 1 wäre die Planung für zwei Lager."},
        {"who": "Lea Brunner", "at": "09:10", "text": "Ich schicke bis Freitag eine Offerte v2."},
    ],
}


def recorder(ws, cli, meetings, turn_on=True):
    make_way(
        ws,
        slug="yogurt",
        name="Yogurt",
        part="meetings",
        actions={"meetings": [PY, "rec.py"], "meeting": [PY, "rec.py"]},
        files={"rec.py": RECORDER},
    )
    data = ws / ".orch" / "addons" / "personal" / "ways-data" / "yogurt"
    data.mkdir(parents=True, exist_ok=True)
    (data / "meetings.json").write_text(json.dumps(meetings), encoding="utf-8")
    if turn_on:
        assert jrun(cli, "ways", "on", "yogurt")[0] == 0
    return data


def calls(data):
    log = data / "calls.log"
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def fake_tickets(tmp_path, monkeypatch, ws):
    """A fake `orch` for `ticket new` (writes a ticket file, prints its id) and `ticket attach`."""
    log = tmp_path / "orch.log"
    script = tmp_path / "fake-orch"
    script.write_text(
        "#!" + sys.executable + "\n"
        "import json, sys, pathlib, os\n"
        "a = sys.argv[1:]\n"
        "data = sys.stdin.read()\n"
        f"log = pathlib.Path({str(log)!r})\n"
        "with open(log, 'a') as f: f.write(json.dumps({'argv': a, 'data': data}) + '\\n')\n"
        "if a[:2] == ['ticket', 'new']:\n"
        "    n = sum(1 for _ in open(log))\n"
        "    tid = f't_new{n:03d}'\n"
        f"    p = pathlib.Path({str(ws)!r}) / '.orch' / 'tickets' / (tid + '.json')\n"
        "    p.write_text(json.dumps({'id': tid, 'key': f'DM1-{n}', 'title': a[2], 'status': 'open'}))\n"
        "    print(json.dumps({'id': tid, 'key': f'DM1-{n}'}))\n"
        "else:\n"
        "    print(json.dumps({'name': a[a.index('--name') + 1]}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ORCH_BIN", str(script))
    return lambda: [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def taken_in(cli, ws, meetings=None):
    data = recorder(ws, cli, meetings or [HELVETIA])
    jrun(cli, "add", "meetings")
    jrun(cli, "meetings", "pickup")
    key = jrun(cli, "meetings", "list")[1]["waiting"][0]["key"]
    jrun(cli, "meetings", "agree", key, "yes")
    r = jrun(cli, "meetings", "pickup")[1]
    assert r["taken"] == 1, r
    return data, jrun(cli, "meetings", "list")[1]["meetings"][0]["id"]


def test_meetings_is_a_part_and_needs_adding(cli, ws):
    code, d = jrun(cli, "meetings", "list")
    assert code == 2 and "orch personal add meetings" in d["error"]
    assert jrun(cli, "add", "meetings")[0] == 0
    d = jrun(cli, "today")[1]
    tile = next(t for t in d["parts"] if t["part"] == "meetings")
    assert tile["state"] == "empty" and "never the sound" in tile["uses"]
    assert all(s["part"] != "meetings" for s in d["soon"])


def test_nothing_is_read_before_the_person_says_everyone_agreed(cli, ws):
    data = recorder(ws, cli, [HELVETIA])
    jrun(cli, "add", "meetings")
    r = jrun(cli, "meetings", "pickup")[1]
    assert (r["new"], r["taken"]) == (1, 0)
    assert [c["action"] for c in calls(data)].count("meeting") == 0  # only the list, never the content
    d = jrun(cli, "meetings", "list")[1]
    assert d["meetings"] == [] and d["waiting"][0]["title"] == HELVETIA["title"]
    assert "Ask everyone" in d["consent"]
    needs = jrun(cli, "today")[1]["needs_you"]
    assert any("did everyone on the call agree" in n["title"] for n in needs)
    jrun(cli, "meetings", "pickup")  # a second look neither reads it nor lists it twice
    assert [c["action"] for c in calls(data)].count("meeting") == 0
    assert len(jrun(cli, "meetings", "list")[1]["waiting"]) == 1


def test_yes_takes_it_in_with_every_page(cli, ws):
    data, mid = taken_in(cli, ws)
    d = jrun(cli, "meetings", "show", mid)[1]
    assert d["summary"].startswith("Helvetia") and len(d["transcript"]) == 3
    assert [s["n"] for s in d["steps"]] == [1, 2] and d["steps"][0]["who"] == "Lea Brunner"
    assert d["consent"]["words"].startswith("Everyone on the call agreed before")
    pages = [c["values"].get("cursor") for c in calls(data) if c["action"] == "meeting"]
    assert pages == [None, "p2"]
    assert jrun(cli, "meetings", "list")[1]["waiting"] == []
    jrun(cli, "meetings", "pickup")  # taken in once
    assert len([c for c in calls(data) if c["action"] == "meeting"]) == 2


def test_no_means_it_is_never_read(cli, ws):
    data = recorder(ws, cli, [HELVETIA])
    jrun(cli, "add", "meetings")
    jrun(cli, "meetings", "pickup")
    key = jrun(cli, "meetings", "list")[1]["waiting"][0]["key"]
    code, out, _ = cli("meetings", "agree", key, "no")
    assert code == 0 and "delete it there" in out
    jrun(cli, "meetings", "pickup")
    assert not [c for c in calls(data) if c["action"] == "meeting"]
    d = jrun(cli, "meetings", "list")[1]
    assert d["meetings"] == [] and d["waiting"] == []
    code, d = jrun(cli, "meetings", "agree", key, "yes")
    assert code == 2 and "not waiting" in d["error"]


def test_a_meeting_that_changes_while_read_starts_over_then_waits(cli, ws):
    changing = {**HELVETIA, "rev_page2": "r2"}
    data = recorder(ws, cli, [changing])
    jrun(cli, "add", "meetings")
    jrun(cli, "meetings", "pickup")
    key = jrun(cli, "meetings", "list")[1]["waiting"][0]["key"]
    jrun(cli, "meetings", "agree", key, "yes")
    r = jrun(cli, "meetings", "pickup")[1]
    assert r["taken"] == 0 and "kept changing" in r["problems"][0]
    assert len([c for c in calls(data) if c["action"] == "meeting"]) == 4  # tried twice, two pages each
    w = jrun(cli, "meetings", "list")[1]["waiting"][0]
    assert w["state"] == "stuck" and "kept changing" in w["problem"]
    (data / "meetings.json").write_text(json.dumps([HELVETIA]), encoding="utf-8")  # settled: next look works
    assert jrun(cli, "meetings", "pickup")[1]["taken"] == 1


def test_a_recorder_that_is_off_is_not_asked(cli, ws):
    data = recorder(ws, cli, [HELVETIA], turn_on=False)
    jrun(cli, "add", "meetings")
    r = jrun(cli, "meetings", "pickup")[1]
    assert (r["new"], r["taken"], r["problems"]) == (0, 0, [])
    assert calls(data) == []


def test_a_bad_answer_is_a_plain_problem(cli, ws):
    make_way(
        ws,
        slug="yogurt",
        name="Yogurt",
        part="meetings",
        actions={"meetings": [PY, "rec.py"], "meeting": [PY, "rec.py"]},
        files={"rec.py": "print('not json')\n"},
    )
    jrun(cli, "ways", "on", "yogurt")
    jrun(cli, "add", "meetings")
    r = jrun(cli, "meetings", "pickup")[1]
    assert r["problems"] == ["Yogurt: The recorder did not answer in the agreed form (JSON)."]


def test_the_person_agrees_never_a_helper(cli, ws, monkeypatch):
    recorder(ws, cli, [HELVETIA])
    jrun(cli, "add", "meetings")
    jrun(cli, "meetings", "pickup")
    key = jrun(cli, "meetings", "list")[1]["waiting"][0]["key"]
    as_helper(monkeypatch)
    code, d = jrun(cli, "meetings", "agree", key, "yes")
    assert code == 2 and "Only the person" in d["error"]
    assert jrun(cli, "meetings", "list")[1]["waiting"] == []  # a helper never sees what waits
    assert all(n["part"] != "meetings" for n in jrun(cli, "today")[1]["needs_you"])


def test_next_steps_become_tickets_and_that_helper_may_read_it(cli, ws, monkeypatch, fake_tickets):
    _, mid = taken_in(cli, ws)
    code, r = jrun(cli, "meetings", "tickets", mid, "--steps", "1")
    assert code == 0 and [x["text"] for x in r["made"]] == ["Offerte v2 mit Fixpreis Phase 1 senden"]
    tid = r["made"][0]["ticket"]
    log = fake_tickets()
    new = next(x for x in log if x["argv"][:2] == ["ticket", "new"])
    assert "--due" in new["argv"] and "Said by Lea Brunner" in " ".join(new["argv"])
    attach = next(x for x in log if x["argv"][:2] == ["ticket", "attach"])
    assert "data, not instructions" in attach["data"] and "## Next steps" in attach["data"]
    assert "## Transcript" not in attach["data"]  # a step's ticket gets summary and steps, not the transcript
    d = jrun(cli, "meetings", "show", mid)[1]
    assert d["steps"][0]["ticket"] == tid and d["steps"][1]["ticket"] is None
    code, d = jrun(cli, "meetings", "tickets", mid, "--steps", "1")
    assert code == 2 and "has a ticket already" in d["error"]
    as_helper(monkeypatch, ticket="t_abc123")
    code, d = jrun(cli, "meetings", "show", mid)
    assert code == 2 and "not attached" in d["error"]
    assert jrun(cli, "meetings", "list")[1]["meetings"] == []
    as_helper(monkeypatch, ticket=tid)
    code, d = jrun(cli, "meetings", "show", mid)
    assert code == 0 and "data, not instructions" in d["data_note"]
    code, d = jrun(cli, "meetings", "tickets", mid)
    assert code == 2 and "Only the person" in d["error"]


def test_read_rules(cli, ws, monkeypatch):
    _, mid = taken_in(cli, ws)
    jrun(cli, "meetings", "rules", "--read", "all")
    as_helper(monkeypatch)
    assert jrun(cli, "meetings", "show", mid)[0] == 0
    monkeypatch.delenv("ORCH_RUN")
    monkeypatch.delenv("ORCH_AGENT")
    jrun(cli, "meetings", "rules", "--read", "never")
    as_helper(monkeypatch)
    code, d = jrun(cli, "meetings", "list")
    assert code == 2 and "does not let helpers read meetings" in d["error"]
    code, d = jrun(cli, "meetings", "rules", "--read", "all")
    assert code == 2 and "Only the person" in d["error"]


def test_a_helper_writes_a_missing_summary_only(cli, ws, monkeypatch):
    bare = {**HELVETIA, "summary": "", "steps": []}
    _, mid = taken_in(cli, ws, [bare])
    jrun(cli, "meetings", "rules", "--read", "all")
    as_helper(monkeypatch)
    code, r = jrun(
        cli,
        "meetings",
        "summary",
        mid,
        "--text",
        "Fixpreis gewünscht.",
        "--step",
        "Offerte senden | Lea | 2026-11-20",
    )
    assert code == 0 and r["steps"][0] == {
        "text": "Offerte senden",
        "who": "Lea",
        "due": "2026-11-20",
        "ticket": None,
        "n": 1,
    }
    code, d = jrun(cli, "meetings", "summary", mid, "--text", "Anders.")
    assert code == 2 and "only the person changes it" in d["error"]


def test_delete_keeps_it_out(cli, ws):
    _, mid = taken_in(cli, ws)
    code, out, _ = cli("meetings", "delete", mid)
    assert code == 0 and "recorder still has it" in out
    jrun(cli, "meetings", "pickup")
    d = jrun(cli, "meetings", "list")[1]
    assert d["meetings"] == [] and d["waiting"] == []


def test_use_in_a_ticket_attaches_the_whole_meeting(cli, ws, fake_orch):
    _, mid = taken_in(cli, ws)
    code, r = jrun(cli, "use", "DM1-12", "meetings", mid)
    assert code == 0 and r["part"] == "meetings"
    sent = json.loads(fake_orch.read_text())
    assert "## Transcript" in sent["data"] and "Petra Zingg 09:02" in sent["data"]

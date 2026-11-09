"""The fake orch (tests/fakes/orch_fake.py): every line it emits is valid against the contract schemas."""

import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

FAKES = Path(__file__).parent / "fakes"
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
_REG = []
_CATS = {}


def _class_body(cat):
    if not _CATS:
        for cp in range(sys.maxunicode + 1):
            c = unicodedata.category(chr(cp))
            _CATS.setdefault(c, []).append(cp)
            _CATS.setdefault(c[0], []).append(cp)
    return "".join(re.escape(chr(cp)) for cp in _CATS.get(cat, []))


def _expand(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "pattern" and isinstance(v, str) and "\\p{" in v:
                node[k] = re.sub(r"\\p\{(\w+)\}", lambda m: _class_body(m.group(1)), v)
            else:
                _expand(v)
    elif isinstance(node, list):
        for v in node:
            _expand(v)
    return node


def validator(name, defname=None):
    if not _REG:
        reg = Registry()
        for f in sorted(CONTRACTS.glob("*.schema.json")):
            doc = _expand(json.loads(f.read_text()))
            reg = reg.with_resource(doc.get("$id", f.name), Resource.from_contents(doc))
        _REG.append(reg)
    schema = _expand(json.loads((CONTRACTS / f"{name}.schema.json").read_text()))
    if defname:
        schema = {"$id": schema["$id"], "$ref": f"#/$defs/{defname}", "$defs": schema["$defs"]}
    return Draft202012Validator(schema, format_checker=FormatChecker(), registry=_REG[0])


def check(v, doc, what):
    errs = [e.message for e in v.iter_errors(doc)]
    assert not errs, f"{what}: {errs[0]}: {json.dumps(doc)[:200]}"


def fake(*args, scenario=None, env=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("ORCH_")}
    if scenario:
        e["ORCH_FAKE_SCENARIO"] = scenario
    e.update(env or {})
    p = subprocess.run([str(FAKES / "orch"), *args], capture_output=True, text=True, env=e, timeout=30)
    lines = [json.loads(x) for x in p.stdout.splitlines()]
    for ln in lines:  # every line is valid against the stream/answer contract shapes
        if "type" in ln:
            check(validator("cli-answer", "stream_line"), ln, "stream line")
    return p.returncode, lines


def err_ok(line, code):
    check(validator("cli-answer", "error"), line, "error")
    assert line["code"] == code


def tail_all(*extra, scenario=None):
    return fake("record", "tail", "--json", *extra, scenario=scenario)


# --- record tail ---
def test_tail_events_valid_with_cursors():
    rc, lines = tail_all()
    assert rc == 0 and lines
    act = validator("activity")
    for ln in lines:
        assert ln["type"] == "event"
        check(act, ln["event"], "event")
    assert [ln["cursor"] for ln in lines] == [f"c{i}" for i in range(1, len(lines) + 1)]


def test_tail_follow_pings_then_ends():
    rc, lines = tail_all("--follow")
    assert rc == 0 and lines[-1]["type"] == "ping" and lines[-1]["cursor"] == lines[-2]["cursor"]
    _, none = fake("record", "tail", "--follow", "--json", env={"ORCH_FAKE_FOLLOW_PINGS": "0"})
    assert all(ln["type"] == "event" for ln in none)


def test_tail_resume_after_cursor():
    _, lines = tail_all()
    _, rest = tail_all("--since", lines[2]["cursor"])
    assert rest == lines[3:]
    _, rest = tail_all("--after", lines[-1]["cursor"])
    assert rest == []


def test_tail_filter_by_ticket_and_bad_cursor():
    _, lines = tail_all("--ticket", "t_nothere")
    assert lines == []
    rc, lines = tail_all("--since", "../x")
    assert rc == 2
    err_ok(lines[0], "invalid")


def test_tail_gone_cursor_resets_then_replays():
    rc, lines = tail_all("--since", "gone")
    assert rc == 0 and lines[0] == {"type": "reset", "cursor": "c0", "reason": "pruned"}
    assert lines[1]["type"] == "event"


def test_tail_drop_then_resume_completes():
    rc, first = tail_all("--follow", scenario="drop")
    assert rc == 2 and first[-1]["type"] == "error" and first[-1]["code"] == "busy"
    err_ok({k: first[-1][k] for k in ("error", "code")}, "busy")
    got = [ln for ln in first if ln["type"] == "event"]
    assert got
    rc, rest = tail_all("--follow", "--since", got[-1]["cursor"], scenario="drop")
    assert rc == 0
    events = got + [ln for ln in rest if ln["type"] == "event"]
    _, full = tail_all()
    assert [e["cursor"] for e in events] == [e["cursor"] for e in full]


def test_tail_empty():
    rc, lines = tail_all("--follow", scenario="empty")
    assert rc == 0 and [ln["type"] for ln in lines] == ["ping"]


# --- record query ---
def test_query_page_valid_newest_first():
    rc, (page,) = fake("record", "query", "--json")
    assert rc == 0
    check(validator("cli-answer", "page"), page, "page")
    assert page["next"] is None
    _, tail = tail_all()
    assert [e["id"] for e in page["items"]] == [ln["event"]["id"] for ln in reversed(tail)]
    for e in page["items"]:
        check(validator("activity"), e, "event")


def test_query_paging_walks_everything_once():
    seen, after, pages = [], None, 0
    while True:
        args = ["record", "query", "--json", "--limit", "100"] + (["--after", after] if after else [])
        rc, (page,) = fake(*args, scenario="paged")
        assert rc == 0
        check(validator("cli-answer", "page"), page, "page")
        seen += [e["id"] for e in page["items"]]
        pages += 1
        after = page["next"]
        if not after:
            break
    assert pages == 3 and len(seen) == 250 == len(set(seen))
    _, (small,) = fake("record", "query", "--json", "--limit", "7", scenario="paged")
    assert len(small["items"]) == 7 and small["next"]


@pytest.mark.parametrize(
    "bad", [["--limit", "0"], ["--limit", "501"], ["--limit", "x"], ["--after", "zz"], ["--after", "o999999"]]
)
def test_query_bad_arguments(bad):
    rc, (line,) = fake("record", "query", "--json", *bad)
    assert rc == 2
    err_ok(line, "invalid")


def test_query_empty():
    rc, (page,) = fake("record", "query", "--json", scenario="empty")
    assert rc == 0 and page == {"items": [], "next": None}


# --- record counts ---
def test_counts_with_denominators_and_not_seen():
    rc, (ans,) = fake("record", "counts", "--json", "--days", "30")
    assert rc == 0
    check(validator("counts", "answer"), ans, "counts")
    assert {"yes", "not_seen"} <= {i["seen"] for i in ans["items"]}
    assert all(i["runs"]["of"] >= i["runs"]["used"] for i in ans["items"])
    assert any(i["runs"]["unseen"] > 0 for i in ans["items"])


def test_counts_nothing_yet_and_bad_range():
    rc, (ans,) = fake("record", "counts", "--json", scenario="empty")
    assert rc == 0 and ans["runs"] == 0 and ans["since"] is None
    check(validator("counts", "answer"), ans, "counts")
    rc, (line,) = fake("record", "counts", "--json", "--from", "2026-11-01")
    assert rc == 2
    err_ok(line, "invalid")


# --- job ---
def test_job_events_valid_and_sequenced(tmp_path):
    env = {"ORCH_FAKE_STATE": str(tmp_path)}
    ev = validator("job-event")
    rc, (start,) = fake("job", "start", "--title", "Export", "--json", env=env)
    assert rc == 0 and start == {"job": "j_x7k2m9"}
    calls = [
        ("step", "read", "--label", "Read", "--state", "running"),
        ("progress", "--done", "3", "--total", "10", "--unit", "files"),
        ("artifact", "out/invoices.csv", "--label", "out.csv"),
        ("metric", "Rows", "1204", "--unit", "rows"),
        ("link", "https://example.com/r", "--label", "Report"),
        ("log", "hello", "--err"),
        ("end", "--status", "ok", "--summary", "done"),
    ]
    for n, c in enumerate(calls, start=2):
        rc, (event,) = fake("job", *c, "--json", env=env)
        assert rc == 0 and event["seq"] == n and event["type"] == c[0]
        check(ev, event, f"job {c[0]}")
    rc, (line,) = fake("job", "log", "late", "--json", env=env)
    assert rc == 2 and line["code"] == "refused"


def test_job_start_event_is_valid_and_bad_input_refused():
    rc, (line,) = fake("job", "start", "--json")
    assert rc == 2
    err_ok(line, "invalid")
    rc, (line,) = fake("job", "artifact", "../etc/passwd", "--json")
    assert rc == 2
    err_ok(line, "invalid")
    rc, (line,) = fake("job", "link", "http://x", "--json")
    assert rc == 2
    err_ok(line, "invalid")
    rc, (line,) = fake("job", "step", "a", "--label", "A", "--json", scenario="empty")
    assert rc == 2 and line["code"] == "refused"


# --- run screen ---
def test_screen_stream_valid_and_sequential():
    rc, lines = fake("run", "screen", "t_abc123", "--follow", "--json")
    assert rc == 0
    sv = validator("screen")
    for ln in lines:
        check(sv, ln, "screen line")
    assert [ln["seq"] for ln in lines] == list(range(1, len(lines) + 1))
    assert [ln["type"] for ln in lines[:2]] == ["hello", "snapshot"] and lines[0]["ticket"] == "t_abc123"
    assert lines[-1]["type"] == "end" and any(ln["type"] == "output" for ln in lines)


def test_screen_drop_refused_and_not_available():
    rc, lines = fake("run", "screen", "t_abc123", "--follow", "--json", scenario="drop")
    assert rc == 2 and lines[-1]["type"] == "error" and lines[-1]["code"] == "busy"
    check(validator("screen"), lines[-1], "screen error")
    rc, lines = fake("run", "screen", "t_abc123", "--follow", "--json", scenario="refused")
    assert rc == 2 and lines[0]["code"] == "switched_off"
    rc, (line,) = fake("run", "screen", "t_nolive", "--follow", "--json")
    assert rc == 2
    err_ok(line, "not_available")
    rc, (line,) = fake("run", "screen", "t_abc123", "--json")
    assert rc == 2
    err_ok(line, "invalid")


# --- everything else ---
@pytest.mark.parametrize(
    "cmd",
    [
        ["ticket", "list", "--json"],
        ["secret", "get", "x"],
        ["run", "type", "t_abc123"],
        ["record", "delete-detail", "t_abc123"],
        ["job", "run", "--", "ls"],
        [],
    ],
)
def test_unknown_command_is_not_available(cmd):
    rc, (line,) = fake(*cmd)
    assert rc == 2
    err_ok(line, "not_available")


def test_scenario_flag_and_unknown_scenario():
    rc, (page,) = fake("record", "query", "--json", "--fake-scenario", "empty")
    assert rc == 0 and page["items"] == []
    rc, (line,) = fake("record", "query", "--json", scenario="nope")
    assert rc == 2
    err_ok(line, "invalid")

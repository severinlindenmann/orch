"""`orch record tail | query | counts`: the real CLI against the contract and the fake orch."""

import ast
import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
from test_fakeorch import FAKES, check, validator

from orch import cli, cli_record, hider
from orch.record import RecordWriter, record_dir

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
RUN_A, RUN_B = "r_8k2m01", "r_9z8y77"
TICKET_A, TICKET_B = "t_inv7c2", "t_other1"


def example(name="valid-step-started", **changes):
    value = json.loads((CONTRACTS / f"examples/activity/{name}.json").read_text())
    value.update(changes)
    return value


def at(n, minute=0):
    return f"2026-11-16T09:{minute:02d}:{n:02d}Z"


@pytest.fixture
def ws(proj):
    """Two runs: A (ticket A, 3 steps + a started-only one) and B (ticket B, 2 steps), interleaved in time."""
    w = RecordWriter(proj, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    w.append(
        example(
            "valid-run-state-say",
            run=RUN_A,
            at=at(1),
            id=f"{RUN_A}:1",
            data={"state": "starting", "sees": ["tool", "skill"]},
        )
    )
    for n in range(1, 4):
        w.append(
            example(run=RUN_A, id=f"toolu_a{n}", at=at(10 + 2 * n)), detail={"input": {}, "output": "ok"}
        )
    for n in range(1, 3):
        w.append(
            example(
                run=RUN_B,
                ticket=TICKET_B,
                id=f"toolu_b{n}",
                at=at(11 + 2 * n),
                outcome={"ok": n == 1, "error": None if n == 1 else "boom", "ms": 5},
            )
        )
    return proj


def cli_lines(capsys, *argv):
    code = cli.main(["record", *argv, "--json"])
    cap = capsys.readouterr()
    return code, [json.loads(x) for x in cap.out.splitlines()]


def test_tail_events_in_order_with_cursors(ws, capsys):
    code, lines = cli_lines(capsys, "tail")
    assert code == 0 and len(lines) == 6
    act = validator("activity")
    for ln in lines:
        assert ln["type"] == "event" and ln["cursor"].startswith("rc1.")
        check(act, ln["event"], "event")
    assert [(e["event"]["run"], e["event"]["seq"]) for e in lines if e["event"]["run"] == RUN_A] == [
        (RUN_A, n) for n in range(1, 5)
    ]
    assert [ln["event"]["at"] for ln in lines] == sorted(ln["event"]["at"] for ln in lines)


def test_tail_resume_and_filters(ws, capsys):
    _, lines = cli_lines(capsys, "tail")
    _, rest = cli_lines(capsys, "tail", "--since", lines[2]["cursor"])
    assert rest == lines[3:]
    _, rest = cli_lines(capsys, "tail", "--after", lines[-1]["cursor"])
    assert rest == []
    _, only = cli_lines(capsys, "tail", "--ticket", TICKET_B)
    assert {ln["event"]["run"] for ln in only} == {RUN_B}
    _, none = cli_lines(capsys, "tail", "--ticket", "t_nothere")
    assert none == []
    _, one = cli_lines(capsys, "tail", "--run", RUN_A)
    assert {ln["event"]["run"] for ln in one} == {RUN_A}


@pytest.mark.parametrize("bad", ["../x", "zz", "rc1.", "rc1.bm90anNvbg", "rc1." + "A" * 5000])
def test_tail_bad_cursor(ws, capsys, bad):
    code, (line,) = cli_lines(capsys, "tail", "--since", bad)
    assert code == 2
    check(validator("cli-answer", "error"), line, "error")
    assert line["code"] == "invalid"


def test_cursor_path_escape_is_invalid(ws, capsys):
    for run in ("../x", "r_a/../../x", "R_ABCDEF"):
        raw = (
            "rc1."
            + __import__("base64").urlsafe_b64encode(json.dumps({run: 1}).encode()).rstrip(b"=").decode()
        )
        code, (line,) = cli_lines(capsys, "tail", "--since", raw)
        assert code == 2 and line["code"] == "invalid"


def test_tail_cursor_naming_a_pruned_run_is_one_marker_not_a_reset(ws, capsys):
    gone = cli_record.TailCursor({"r_gone0001": 3}).encode()
    code, lines = cli_lines(capsys, "tail", "--since", gone)
    assert code == 0 and lines[0]["type"] == "unavailable"
    assert (lines[0]["run"], lines[0]["status"], lines[0]["reason"]) == (
        "r_gone0001",
        "unavailable",
        "missing",
    )
    assert len([ln for ln in lines if ln["type"] == "event"]) == 6
    assert "r_gone0001" not in cli_record.TailCursor.decode(lines[-1]["cursor"]).seqs
    _, again = cli_lines(capsys, "tail", "--since", lines[-1]["cursor"])
    assert again == []


def test_tail_unknown_run_is_not_found(ws, capsys):
    code, (line,) = cli_lines(capsys, "tail", "--run", "r_nothere1")
    assert code == 2 and line["code"] == "not_found"


def test_tail_follow_picks_up_new_events_and_pings(ws):
    seen = []

    def sleep(_):
        seen.append(len(seen))
        if len(seen) == 1:
            w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
            w.append(example(run=RUN_B, ticket=TICKET_B, id="toolu_late", at=at(50)))
        if len(seen) > 20:
            raise KeyboardInterrupt

    ticks = iter(range(0, 10000, 5))
    out = []
    try:
        for ln in cli_record.tail_lines(
            ws, follow=True, sleep=sleep, clock=lambda: next(ticks), now=lambda: "2026-11-16T10:00:00Z"
        ):
            out.append(ln)
    except KeyboardInterrupt:
        pass
    types = [ln["type"] for ln in out]
    assert types[:6] == ["event"] * 6 and out[6]["event"]["id"] == "toolu_late"
    assert "ping" in types[7:]
    ping = next(ln for ln in out if ln["type"] == "ping")
    check(validator("cli-answer", "stream_line"), ping, "ping")
    assert ping["cursor"] == out[6]["cursor"]


def test_tail_requires_json(ws, capsys):
    assert cli.main(["record", "tail"]) == 2
    assert "Use --json" in capsys.readouterr().err


def test_query_newest_first_and_paging(ws, capsys):
    code, (page,) = cli_lines(capsys, "query")
    assert code == 0 and page["next"] is None and len(page["items"]) == 6
    check(validator("cli-answer", "page"), page, "page")
    keys = [(e["at"], e["run"], e["seq"]) for e in page["items"]]
    assert keys == sorted(keys, reverse=True)
    seen, after = [], None
    while True:
        extra = ["--after", after] if after else []
        _, (p,) = cli_lines(capsys, "query", "--limit", "4", *extra)
        seen += [(e["run"], e["seq"]) for e in p["items"]]
        after = p["next"]
        if not after:
            break
    assert seen == [(e["run"], e["seq"]) for e in page["items"]]


def test_query_filters(ws, capsys):
    _, (p,) = cli_lines(capsys, "query", "--ticket", TICKET_B)
    assert {e["run"] for e in p["items"]} == {RUN_B}
    _, (p,) = cli_lines(capsys, "query", "--kind", "run.state")
    assert [e["kind"] for e in p["items"]] == ["run.state"]
    _, (p,) = cli_lines(capsys, "query", "--kind", "run.state", "--kind", "step", "--run", RUN_A)
    assert len(p["items"]) == 4
    _, (p,) = cli_lines(capsys, "query", "--from", at(14), "--to", at(16))
    assert [e["at"] for e in p["items"]] == sorted((e["at"] for e in p["items"]), reverse=True)
    assert all(at(14) <= e["at"] <= at(16) for e in p["items"]) and p["items"]
    _, (p,) = cli_lines(capsys, "query", "--ticket", "t_nothere")
    assert p == {"items": [], "next": None, "unavailable": []}


@pytest.mark.parametrize(
    "bad",
    [
        ["--limit", "0"],
        ["--limit", "501"],
        ["--limit", "x"],
        ["--after", "zz"],
        ["--kind", "nope"],
        ["--from", "yesterday"],
        ["--run", "../x"],
        ["--detail", "a b", "--run", RUN_A],
        ["--detail", "toolu_a1"],
    ],
)
def test_query_bad_arguments(ws, capsys, bad):
    code, (line,) = cli_lines(capsys, "query", *bad)
    assert code == 2
    check(validator("cli-answer", "error"), line, "error")
    assert line["code"] == "invalid"


def test_query_unknown_run_and_gone_page(ws, capsys):
    code, (line,) = cli_lines(capsys, "query", "--run", "r_nothere1")
    assert code == 2 and line["code"] == "not_found"
    code, (line,) = cli_lines(capsys, "query", "--after", cli_record.encode_cursor({RUN_A: 999}))
    assert code == 2 and line["code"] == "gone"


def test_query_detail(ws, capsys):
    code, (d,) = cli_lines(capsys, "query", "--detail", "toolu_a1", "--run", RUN_A)
    assert code == 0 and d["output"] == "ok"
    code, (line,) = cli_lines(capsys, "query", "--detail", "toolu_b1", "--run", RUN_B)
    assert code == 2 and line["code"] == "not_found"


def test_unsafe_record_is_refused(ws, capsys, tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (record_dir(ws) / "runs").rename(real / "runs")
    (record_dir(ws) / "runs").symlink_to(real / "runs")
    code, (line,) = cli_lines(capsys, "query")
    assert code == 2 and line["code"] == "tampered"


def test_counts_valid_and_denominators(ws, capsys):
    code, (ans,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert code == 0
    check(validator("counts", "answer"), ans, "counts")
    assert (
        ans["runs"] == 2
        and ans["tickets"] == 2
        and ans["since"]
        and ans["coverage"] == {"full": 1, "partial": 1}
    )
    read = next(i for i in ans["items"] if i["name"] == "Read")
    # run A can report skills and tools; run B wrote no capability list, so it only counts for what it used
    assert read["uses"] == 5 and read["ok"] == 1 and read["failed"] == 1 and read["unknown"] == 3
    assert read["runs"] == {"used": 2, "of": 2, "unseen": 0}


def test_counts_window_nothing_and_errors(ws, capsys):
    code, (ans,) = cli_lines(capsys, "counts", "--from", "2025-01-01", "--to", "2025-01-31")
    assert code == 0 and ans["runs"] == 0 and ans["items"] == []
    check(validator("counts", "answer"), ans, "counts")
    _, (ans,) = cli_lines(capsys, "counts")
    assert ans["runs"] == 0  # the default window is the last 30 days
    for bad in (
        ["--from", "2026-11-01"],
        ["--days", "0"],
        ["--days", "5", "--from", "2026-01-01", "--to", "2026-01-02"],
        ["--from", "2026-13-01", "--to", "2026-13-02"],
        ["--kind", "x"],
    ):
        code, (line,) = cli_lines(capsys, "counts", *bad)
        assert code == 2 and line["code"] == "invalid"


def test_counts_empty_workspace(proj, capsys):
    code, (ans,) = cli_lines(capsys, "counts")
    assert code == 0 and ans["runs"] == 0 and ans["since"] is None
    check(validator("counts", "answer"), ans, "counts")


def test_counts_denominator_vectors():
    vec = json.loads((CONTRACTS / "vectors/counts-v1.json").read_text())
    for case in vec["denominators"]:
        runs = [
            cli_record.run_model(
                r["run"],
                [
                    {
                        "kind": "step",
                        "id": f"{r['run']}:{n}",
                        "at": "2026-11-16T09:00:00Z",
                        "ticket": r["ticket"],
                        "used": {
                            "kind": e["kind"],
                            "name": e["name"],
                            "source": e["source"],
                            "action": None,
                            "version": None,
                        },
                        "outcome": {"ok": e["ok"], "error": None, "ms": 1},
                        **({"kind": "key.use", "data": {"refused": True}} if e.get("refused") else {}),
                    }
                    for n, e in enumerate(r["events"], 1)
                ]
                or [
                    {
                        "kind": "run.state",
                        "id": "x",
                        "at": "2026-11-16T09:00:00Z",
                        "ticket": r["ticket"],
                        "data": {"state": "starting"},
                    }
                ],
            )
            for r in case["runs"]
        ]
        for r, src in zip(runs, case["runs"], strict=True):
            r["sees"] = src["sees"]
        got = cli_record.count_items(runs, case.get("inventory", []))
        keys = ("kind", "name", "source", "runs", "uses", "ok", "failed", "refused", "unknown", "seen")
        assert [{k: i[k] for k in keys} for i in got] == case["items"], case["name"]


# --- the real CLI against the fake orch the add-ons test with ---
def fake_lines(*args, scenario="default"):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCH_")} | {
        "ORCH_FAKE_SCENARIO": scenario
    }
    p = subprocess.run(
        [sys.executable, str(FAKES / "orch_fake.py"), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return p.returncode, [json.loads(x) for x in p.stdout.splitlines()]


def shape(value):
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items() if k not in ("event", "items", "inventory")}
    return type(value).__name__ if not isinstance(value, list) else "list"


def test_same_shapes_as_the_fake(ws, capsys):
    _, real = cli_lines(capsys, "tail")
    _, fake = fake_lines("record", "tail", "--json")
    assert {json.dumps(shape(r), sort_keys=True) for r in real} == {
        json.dumps(shape(f), sort_keys=True) for f in fake
    }
    _, (real_page,) = cli_lines(capsys, "query")
    _, (fake_page,) = fake_lines("record", "query", "--json")
    assert shape(real_page) == shape(fake_page) and set(real_page) == set(fake_page)
    _, (real_counts,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    _, (fake_counts,) = fake_lines("record", "counts", "--json")
    assert set(real_counts) == set(fake_counts)
    assert set(real_counts["items"][0]) == set(fake_counts["items"][0]) - {"tickets"}
    for kind in ("invalid", "not_found"):
        args = ["--limit", "0"] if kind == "invalid" else ["--run", "r_nothere1"]
        _, (real_err,) = cli_lines(capsys, "query", *args)
        assert set(real_err) == {"error", "code"}
    _, (fake_err,) = fake_lines("record", "query", "--json", "--limit", "0")
    assert set(fake_err) == {"error", "code"}


# --- integrity: an unreadable run is told, never an empty answer (W2B-RECORD-IO-DESIGN 7, test 16) ---
def run_file(ws, run=RUN_B):
    return record_dir(ws) / "runs" / f"{run}.jsonl"


def hardlink(ws, run=RUN_B):
    path = run_file(ws, run)
    outside = ws.parent / f"outside-{ws.name}-{run}"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    os.link(outside, path)
    return outside


def test_tail_single_run_tampered_is_an_error(ws, capsys):
    hardlink(ws)
    code, (err,) = cli_lines(capsys, "tail", "--run", RUN_B)
    assert code == 2 and err["code"] == "tampered"
    check(validator("cli-answer", "error"), err, "error")


def test_tampered_alert_reaches_stderr(ws, capsys):
    hardlink(ws)
    cli.main(["record", "query", "--json"])
    out = capsys.readouterr()
    alerts = [ln for ln in out.err.splitlines() if ln.startswith("{")]
    assert alerts and json.loads(alerts[0])["schema"] == "orch.record-alert/1"


def test_tail_multi_run_marker_then_other_events(ws, capsys):
    hardlink(ws)
    code, lines = cli_lines(capsys, "tail")
    assert code == 0
    markers = [ln for ln in lines if ln["type"] == "unavailable"]
    assert len(markers) == 1 and markers[0]["run"] == RUN_B
    assert markers[0]["status"] == "tampered" and markers[0]["reason"] == "hardlink" and markers[0]["message"]
    check(validator("cli-answer", "stream_line"), markers[0], "marker")
    events = [ln for ln in lines if ln["type"] == "event"]
    assert len(events) == 4 and {ln["event"]["run"] for ln in events} == {RUN_A}


def test_tail_marker_once_per_stream_while_following(ws):
    hardlink(ws)
    cycles = []

    def sleep(_):
        cycles.append(1)
        if len(cycles) > 3:
            raise KeyboardInterrupt

    ticks = iter(range(0, 10000))
    out = []
    try:
        for ln in cli_record.tail_lines(ws, follow=True, sleep=sleep, clock=lambda: next(ticks)):
            out.append(ln)
    except KeyboardInterrupt:
        pass
    assert [ln["type"] for ln in out].count("unavailable") == 1


def test_skipped_lines_are_marked_not_hidden(ws, capsys):
    with run_file(ws).open("a") as f:
        f.write("this is not an event\n")
    _, lines = cli_lines(capsys, "tail")
    (marker,) = [ln for ln in lines if ln["type"] == "unavailable"]
    assert (marker["status"], marker["reason"], marker["run"]) == ("ok", "skipped", RUN_B)
    assert "could not be read" in marker["message"]
    check(validator("cli-answer", "stream_line"), marker, "marker")
    assert len([ln for ln in lines if ln["type"] == "event"]) == 6


def test_pending_writes_are_marked(ws, capsys):
    pending = record_dir(ws) / "pending" / RUN_A
    pending.mkdir(parents=True)
    (pending / "x.json").write_text("{}")
    _, lines = cli_lines(capsys, "tail")
    (marker,) = [ln for ln in lines if ln["type"] == "unavailable"]
    assert (marker["status"], marker["reason"], marker["run"]) == ("ok", "pending", RUN_A)
    check(validator("cli-answer", "stream_line"), marker, "marker")


def test_query_lists_unavailable_and_run_filter_errors(ws, capsys):
    hardlink(ws)
    code, (page,) = cli_lines(capsys, "query")
    assert code == 0 and len(page["items"]) == 4
    assert [(u["run"], u["status"], u["reason"]) for u in page["unavailable"]] == [
        (RUN_B, "tampered", "hardlink")
    ]
    check(validator("cli-answer", "page"), page, "page")
    code, (err,) = cli_lines(capsys, "query", "--run", RUN_B)
    assert code == 2 and err["code"] == "tampered"
    check(validator("cli-answer", "error"), err, "error")


def test_query_run_io_error_is_not_available(ws, capsys):
    path = run_file(ws)
    path.chmod(0)
    try:
        code, (err,) = cli_lines(capsys, "query", "--run", RUN_B)
    finally:
        path.chmod(0o600)
    assert code == 2 and err["code"] == "not_available"


def test_counts_incomplete_when_a_run_is_unreadable(ws, capsys):
    args = ("counts", "--from", "2026-11-16", "--to", "2026-11-16")
    _, (ok,) = cli_lines(capsys, *args)
    assert ok["unavailable"] == [] and ok["complete"] is True
    hardlink(ws)
    _, (ans,) = cli_lines(capsys, *args)
    check(validator("counts", "answer"), ans, "counts")
    assert ans["complete"] is False and ans["runs"] == 1
    assert [(u["run"], u["status"]) for u in ans["unavailable"]] == [(RUN_B, "tampered")]


def test_counts_meta_unavailable_falls_back_and_is_listed(ws, capsys):
    meta = record_dir(ws) / "meta.json"
    outside = ws.parent / f"outside-meta-{ws.name}"
    outside.write_bytes(meta.read_bytes())
    meta.unlink()
    meta.symlink_to(outside)
    _, (ans,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert ans["since"] == "2026-11-16T09:00:01Z" and ans["complete"] is False
    assert [u["run"] for u in ans["unavailable"]] == [None]
    check(validator("counts", "answer"), ans, "counts")


def test_detail_tampered_and_lost_codes(ws, capsys):
    for detail in (record_dir(ws) / "detail" / RUN_A).iterdir():
        outside = ws.parent / f"outside-{detail.name}"
        outside.write_bytes(detail.read_bytes())
        detail.unlink()
        os.link(outside, detail)
    code, (err,) = cli_lines(capsys, "query", "--detail", "toolu_a1", "--run", RUN_A)
    assert code == 2 and err["code"] == "tampered"
    code, (err,) = cli_lines(capsys, "query", "--detail", "toolu_b1", "--run", RUN_B)
    assert code == 2 and err["code"] == "not_found"  # the line has no detail file
    code, (err,) = cli_lines(capsys, "query", "--detail", "toolu_a1", "--run", RUN_B)
    assert code == 2 and err["code"] == "not_found"


def test_cli_record_has_no_direct_file_access():
    tree = ast.parse(Path(cli_record.__file__).read_text())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"read_text", "read_bytes", "open", "read_events", "run_readable", "glob", "iterdir"}
    assert "open" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


# --- review fixes: small cursors, alerts once, markers follow state, detail identity ---
def make_runs(root, count):
    """`count` finished runs (a step, then run.state done), one second apart."""
    writer = RecordWriter(root, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    for n in range(count):
        run = f"r_many{n:04d}"
        when = f"2026-11-16T10:{n // 60:02d}:{n % 60:02d}Z"
        writer.append(example(run=run, ticket=TICKET_A, id=f"toolu_m{n}", at=when))
        writer.append(
            example(
                "valid-run-state-say",
                run=run,
                ticket=TICKET_A,
                id=f"{run}:done",
                at=when,
                data={"state": "done"},
            )
        )
    return writer


def test_tail_cursor_stays_small_with_300_runs_compressed(proj, capsys):
    writer = make_runs(proj, 300)
    code, lines = cli_lines(capsys, "tail")
    assert code == 0 and len(lines) == 600
    assert max(len(ln["cursor"]) for ln in lines) < 4096
    last = lines[-1]["cursor"]
    _, rest = cli_lines(capsys, "tail", "--since", last)
    assert rest == []
    _, rest = cli_lines(capsys, "tail", "--since", lines[149]["cursor"])
    assert [ln["event"]["id"] for ln in rest] == [ln["event"]["id"] for ln in lines[150:]]
    writer.append(example(run="r_many0007", ticket=TICKET_A, id="toolu_new", at="2026-11-16T11:00:00Z"))
    _, rest = cli_lines(capsys, "tail", "--since", last)
    assert [ln["event"]["id"] for ln in rest] == ["toolu_new"]
    assert len(cli_record.TailCursor.decode(last).seqs) == 300


def test_tail_cursor_with_unknown_shape_is_invalid(ws, capsys):
    code, (line,) = cli_lines(capsys, "tail", "--since", cli_record.encode_cursor({RUN_A: 1}))
    assert code == 2 and line["code"] == "invalid"


def follow(root, polls, between=None, **kw):
    count = []

    def sleep(_):
        count.append(1)
        if between:
            between(len(count))
        if len(count) >= polls:
            raise KeyboardInterrupt

    ticks = iter(range(0, 100000))
    out = []
    try:
        for ln in cli_record.tail_lines(root, follow=True, sleep=sleep, clock=lambda: next(ticks), **kw):
            out.append(ln)
    except KeyboardInterrupt:
        pass
    return out


def test_follow_prints_the_alert_once(ws, capsys):
    hardlink(ws)
    out = follow(ws, 6)
    err = capsys.readouterr().err
    assert [ln["type"] for ln in out].count("unavailable") == 1
    assert len([x for x in err.splitlines() if x.startswith("{")]) == 1


def test_marker_state_follows_the_run(ws):
    outside = hardlink(ws)
    path = run_file(ws)
    saved = outside.read_bytes()

    def between(n):
        path.unlink()
        if n == 1:
            path.write_bytes(saved)  # readable again
        else:
            os.link(outside, path)  # tampered again

    out = follow(ws, 3, between)
    marks = [(ln["status"], ln["reason"]) for ln in out if ln["type"] == "unavailable"]
    assert marks == [("tampered", "hardlink"), ("ok", "recovered"), ("tampered", "hardlink")]
    for ln in out:
        if ln["type"] == "unavailable":
            check(validator("cli-answer", "stream_line"), ln, "marker")


def test_follow_drops_cursor_entries_of_pruned_runs(ws):
    since = cli_record.TailCursor({RUN_A: 4, RUN_B: 2}).encode()

    def between(n):
        if n == 1:
            run_file(ws, RUN_B).unlink()

    out = follow(ws, 25, between, since=since)
    ping = [ln for ln in out if ln["type"] == "ping"][-1]
    assert cli_record.TailCursor.decode(ping["cursor"]).seqs == {RUN_A: 4}
    assert [(m["run"], m["status"], m["reason"]) for m in out if m["type"] == "unavailable"] == [
        (RUN_B, "unavailable", "missing")
    ]


def test_detail_file_of_another_event_is_tampered(ws, capsys, monkeypatch):
    real = cli_record.record.read_detail

    def other(root, run, file_id, **kw):
        result = real(root, run, file_id, **kw)
        return type(result)("ok", dict(result.value, id="toolu_other"))

    monkeypatch.setattr(cli_record.record, "read_detail", other)
    code, (err,) = cli_lines(capsys, "query", "--detail", "toolu_a1", "--run", RUN_A)
    assert code == 2 and err["code"] == "tampered"


def test_late_event_of_a_live_run_is_still_delivered(ws, capsys):
    # run B is live (no end): its next line carries an older time than the watermark, which has moved on
    def late(n):
        if n == 1:
            RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"})).append(
                example(run=RUN_B, ticket=TICKET_B, id="toolu_late", at=at(5))
            )

    out = follow(ws, 3, late)
    ids = [ln["event"]["id"] for ln in out if ln["type"] == "event"]
    assert ids.count("toolu_late") == 1
    _, lines = cli_lines(capsys, "tail")
    assert "toolu_late" in [ln["event"]["id"] for ln in lines]
    assert cli_lines(capsys, "tail", "--since", lines[-1]["cursor"])[1] == []


def test_unseen_live_run_with_old_events_is_delivered_not_skipped(ws):
    since = cli_record.TailCursor({RUN_A: 4}).encode()  # B was never sent, and is older
    out = follow(ws, 1, since=since)
    assert {ln["event"]["run"] for ln in out if ln["type"] == "event"} == {RUN_B}


def test_vanished_tampered_run_is_missing_not_recovered(ws):
    hardlink(ws)

    def between(n):
        run_file(ws).unlink(missing_ok=True)

    out = follow(ws, 3, between)
    marks = [(m["status"], m["reason"]) for m in out if m["type"] == "unavailable"]
    assert marks == [("tampered", "hardlink"), ("unavailable", "missing")]
    check(
        validator("cli-answer", "stream_line"), [m for m in out if m["type"] == "unavailable"][-1], "marker"
    )


# --- Opus delta findings, one named test each ---
def raw_line(ws, run, n):
    return run_file(ws, run).read_text().splitlines()[n]


def test_high1_old_runs_never_cause_a_resend_loop(ws):
    old = "2026-11-01T09:00:00Z"  # more than a week before the others
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    w.append(example(run="r_old00001", ticket=TICKET_A, id="toolu_old", at=old))
    out = follow(ws, 6)
    ids = [ln["event"]["id"] for ln in out if ln["type"] == "event"]
    assert len(ids) == len(set(ids)) == 7


def test_high2_late_line_in_an_ended_run_is_delivered(ws, capsys):
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    w.append(
        example(
            "valid-run-state-say", run=RUN_B, ticket=TICKET_B, id="b:done", at=at(40), data={"state": "done"}
        )
    )
    _, lines = cli_lines(capsys, "tail")
    last = lines[-1]["cursor"]
    w.append(example(run=RUN_B, ticket=TICKET_B, id="toolu_drained", at=at(2)))  # old time, written late
    _, rest = cli_lines(capsys, "tail", "--since", last)
    assert [ln["event"]["id"] for ln in rest] == ["toolu_drained"]

    # and while following
    def late(n):
        if n == 1:
            w.append(example(run=RUN_B, ticket=TICKET_B, id="toolu_drained2", at=at(3)))

    out = follow(ws, 3, late, since=rest[-1]["cursor"])
    assert [ln["event"]["id"] for ln in out if ln["type"] == "event"] == ["toolu_drained2"]


def test_high3_a_rewritten_run_is_marked_and_resent(ws, capsys):
    _, lines = cli_lines(capsys, "tail")
    last = lines[-1]["cursor"]
    path = run_file(ws, RUN_B)
    path.write_text(raw_line(ws, RUN_B, 0) + "\n")  # shorter than the cursor
    _, rest = cli_lines(capsys, "tail", "--since", last)
    marks = [ln for ln in rest if ln["type"] == "unavailable"]
    assert [(m["run"], m["status"], m["reason"]) for m in marks] == [(RUN_B, "ok", "rewound")]
    check(validator("cli-answer", "stream_line"), marks[0], "marker")
    assert [ln["event"]["seq"] for ln in rest if ln["type"] == "event"] == [1]


def test_med_vanish_and_return_is_missing_then_recovered(ws):
    path = run_file(ws, RUN_B)
    away = path.with_suffix(".away")

    def between(n):
        if n == 1:
            path.rename(away)
        elif n == 2:
            away.rename(path)

    out = follow(ws, 4, between)
    marks = [(m["status"], m["reason"]) for m in out if m["type"] == "unavailable"]
    assert marks == [("unavailable", "missing"), ("ok", "recovered")]


def test_med_too_large_trims_finished_runs_loudly(proj, capsys, monkeypatch):
    make_runs(proj, 40)
    monkeypatch.setattr(cli_record, "_MAX_CURSOR", 120)
    code, lines = cli_lines(capsys, "tail")
    assert code == 0 and len([ln for ln in lines if ln["type"] == "event"]) == 80
    trimmed = [ln for ln in lines if ln["type"] == "unavailable" and ln["reason"] == "trimmed"]
    assert trimmed and all(ln["status"] == "ok" for ln in trimmed)
    check(validator("cli-answer", "stream_line"), trimmed[0], "marker")
    assert max(len(ln["cursor"]) for ln in lines) <= 120
    out = follow(proj, 3)  # a followed stream does not send trimmed runs again
    ids = [ln["event"]["id"] for ln in out if ln["type"] == "event"]
    assert len(ids) == len(set(ids)) == 80


def test_high_600_unfinished_runs_are_trimmed_not_fatal(proj, capsys):
    import random

    rng = random.Random(7)
    w = RecordWriter(proj, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    for n in range(600):  # crashed runs: no terminal run.state
        run = "r_" + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(12))
        w.append(
            example(
                run=run, ticket=TICKET_A, id=f"toolu_c{n}", at=f"2026-11-16T10:{n // 60:02d}:{n % 60:02d}Z"
            )
        )
    code, lines = cli_lines(capsys, "tail")
    assert code == 0 and len([ln for ln in lines if ln["type"] == "event"]) == 600
    assert any(ln["type"] == "unavailable" and ln["reason"] == "trimmed" for ln in lines)
    assert max(len(ln["cursor"]) for ln in lines) <= 4096


def test_nothing_to_trim_is_too_large(proj, capsys, monkeypatch):
    w = RecordWriter(proj, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    w.append(example(run="r_onlyone1", ticket=TICKET_A, id="toolu_1", at=at(1)))
    monkeypatch.setattr(cli_record, "_MAX_CURSOR", 20)
    code, (line,) = cli_lines(capsys, "tail")  # nothing was sent yet: a plain error
    assert code == 2 and line["code"] == "too_large"


def test_med_a_trimmed_run_rewritten_shorter_is_rewound(ws, monkeypatch):
    cursor = cli_record.TailCursor({RUN_A: 4})
    cursor.trimmed[RUN_B] = 2  # as if B had been trimmed from this stream

    def decode(text):
        return cursor

    monkeypatch.setattr(cli_record.TailCursor, "decode", staticmethod(decode))
    path = run_file(ws, RUN_B)
    path.write_text(raw_line(ws, RUN_B, 0) + "\n")
    out = follow(ws, 1, since="rc1.x")
    marks = [(m["run"], m["reason"]) for m in out if m["type"] == "unavailable"]
    assert marks == [(RUN_B, "rewound")]
    assert [ln["event"]["seq"] for ln in out if ln["type"] == "event"] == [1]


def test_zlib_bomb_cursor_is_invalid(ws, capsys):
    import base64

    bomb = (
        "rc1."
        + base64.urlsafe_b64encode(zlib.compress(b"[" + b"0," * 5_000_000 + b"0]")).rstrip(b"=").decode()
    )
    code, (line,) = cli_lines(capsys, "tail", "--since", bomb)
    assert code == 2 and line["code"] == "invalid"


def test_deeply_nested_cursors_are_invalid(ws, capsys):
    import base64

    nested = "[" * 100000
    for body in (
        zlib.compress(nested.encode()),  # tail path (compressed)
        nested.encode(),  # query path
    ):
        cursor = "rc1." + base64.urlsafe_b64encode(body).rstrip(b"=").decode()
        for args in (("tail", "--since", cursor), ("query", "--after", cursor)):
            code, (line,) = cli_lines(capsys, *args)
            assert code == 2 and line["code"] == "invalid"

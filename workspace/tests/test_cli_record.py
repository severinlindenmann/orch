"""`orch record tail | query | counts`: the real CLI against the contract and the fake orch."""

import json
import subprocess
import sys
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


def test_tail_pruned_cursor_resets(ws, capsys):
    gone = cli_record.encode_cursor({"r_gone0001": 3})
    code, lines = cli_lines(capsys, "tail", "--since", gone)
    assert code == 0 and lines[0]["type"] == "reset" and lines[0]["reason"] == "pruned"
    assert len([ln for ln in lines if ln["type"] == "event"]) == 6
    _, again = cli_lines(capsys, "tail", "--since", lines[0]["cursor"])
    assert again == lines[1:]


def test_tail_unknown_run_is_not_found(ws, capsys):
    code, (line,) = cli_lines(capsys, "tail", "--run", "r_nothere1")
    assert code == 2 and line["code"] == "not_found"


def test_tail_follow_picks_up_new_events_and_pings(ws):
    seen = []

    def sleep(_):
        seen.append(len(seen))
        if len(seen) == 1:
            w = RecordWriter(ws, hider=hider.Hider({}))
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
    assert p == {"items": [], "next": None}


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
    assert code == 2 and line["code"] == "refused"


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
    import os

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

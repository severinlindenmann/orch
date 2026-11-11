"""`orch record hook`: the narrow hook entry of the record (contracts/activity.md, vectors hook_entry)."""

import base64
import io
import json
import os
import time
from pathlib import Path

import pytest

from orch import hider, record, record_hook, runs, tickets

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "contracts/vectors/activity-v1.json").read_text())
USED = {"kind": "tool", "name": "Read", "action": None, "source": "builtin", "version": None}
SECRET = "KEYVALUE-abc123XYZ-secret"


@pytest.fixture
def live(proj, monkeypatch):
    t = tickets.create(proj, "Hook me", "human:t")
    rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", t["id"])
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        yield proj, rec["run"], t["id"]


def line(**kw):
    value = {"kind": "step", "id": "toolu_01X", "text": "Read a.pdf", "used": USED, "outcome": None}
    value.update(kw)
    return json.dumps(value)


def events(root, run):
    return record.read_run(root, run).value


def test_step_is_written_as_hook_for_the_env_run(live):
    root, run, tid = live
    got = record_hook.hook(root, line(via="core", run=run))
    assert got["via"] == "hook" and got["run"] == run and got["ticket"] == tid and got["seq"] == 1
    assert [e["id"] for e in events(root, run)] == ["toolu_01X"]


@pytest.mark.parametrize("vector", VECTORS["hook_entry"], ids=lambda v: v["name"])
def test_vectors(live, vector):
    root, run, _ = live
    raw = dict(
        vector["line"],
        run=run,
        text="x",
        used=USED if vector["line"]["kind"] == "step" else None,
        **(
            {"data": {"used": 0.4, "window": "5h", "status": "ok"}}
            if vector["line"]["kind"] == "usage"
            else {}
        ),
    )
    if vector["stored"] == "refused":
        with pytest.raises(record_hook.NotRecorded):
            record_hook.hook(root, json.dumps(raw))
        assert record.read_run(root, run).status == "unavailable"  # nothing at all was written
    else:
        got = record_hook.hook(root, json.dumps(raw))
        assert {k: got[k] for k in vector["stored"] if k != "run"} == {
            k: v for k, v in vector["stored"].items() if k != "run"
        }


def test_forged_events(live):
    root, run, _ = live
    for forged in (
        line(kind="run.state"),
        line(kind="ask"),
        line(kind="task.done"),
        line(kind="key.use"),
        line(run="r_other0001"),
        line(ticket="t_other0001"),
        "not json",
        "[1]",
        '"x"',
        "",
        line(payload="x"),
    ):
        with pytest.raises(record_hook.NotRecorded):
            record_hook.hook(root, forged)
    # bad ids and fields: the writer refuses, nothing is written
    for bad in (line(id=5), line(agent="x y"), line(at="yesterday"), line(text="a\x00b")):
        with pytest.raises(record.RecordRefused):
            record_hook.hook(root, bad)
    assert record.read_run(root, run).status == "unavailable"


def test_forged_pointer_seq_and_flags_are_dropped(live):
    root, run, _ = live
    got = record_hook.hook(
        root, line(detail="detail/r_other0001/" + "a" * 32 + ".json", seq=99, conflict=True, detail_lost=True)
    )
    assert got["seq"] == 1 and got["detail"] is None and "conflict" not in got and "detail_lost" not in got


def test_run_namespace_ids_are_rehashed(live):
    root, run, _ = live
    got = record_hook.hook(root, line(id=f"{run}:7"))
    assert got["id"].startswith("x_") and len(got["id"]) == 34
    assert record_hook.hook(root, line(id=None))["id"] == f"{run}:2"


def test_no_run_env_is_a_plain_noop(proj, monkeypatch):
    monkeypatch.delenv("ORCH_RUN", raising=False)
    monkeypatch.delenv("ORCH_TICKET", raising=False)
    with pytest.raises(record_hook.NotRecorded, match="Not inside"):
        record_hook.hook(proj, line())
    assert not (proj / ".orch/record").exists()


@pytest.mark.parametrize("which", ["wrong_run", "wrong_ticket", "unknown_ticket", "dead"])
def test_run_must_be_live_and_match(live, monkeypatch, which):
    root, run, tid = live
    if which == "wrong_run":
        monkeypatch.setenv("ORCH_RUN", "r_zzzzzz")
    elif which == "wrong_ticket":
        other = tickets.create(root, "Other", "human:t")
        monkeypatch.setenv("ORCH_TICKET", other["id"])
    elif which == "unknown_ticket":
        monkeypatch.setenv("ORCH_TICKET", "t_nothere1")
    else:
        monkeypatch.setattr(runs, "state", lambda rec, at=None: "dead")
    with pytest.raises(record_hook.NotRecorded, match="not active"):
        record_hook.hook(root, line())
    assert not (root / ".orch/record").exists()


def test_no_hider_refuses_and_writes_nothing(proj, monkeypatch):
    t = tickets.create(proj, "No hider", "human:t")
    rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", t["id"])
    monkeypatch.setattr(hider, "_registered", None)
    with pytest.raises(record.RecordOff):
        record_hook.hook(proj, line())
    assert not (proj / ".orch/record").exists()


def test_cli_never_blocks_the_agent_but_strict_refuses(live, monkeypatch, capsys):
    root, run, _ = live
    record_hook.cli(root, io.StringIO(line(kind="run.state")))
    assert "not allowed" in capsys.readouterr().err
    with pytest.raises(record_hook.Refused):
        record_hook.cli(root, io.StringIO(line(kind="run.state")), strict=True)
    monkeypatch.setattr(hider, "_registered", None)
    with hider.use_hider(hider.Hider({"k": SECRET})):
        pass
    monkeypatch.setattr(record_hook, "_writer", lambda r: (_ for _ in ()).throw(record.RecordOff("off")))
    record_hook.cli(root, io.StringIO(line()))
    assert "off" in capsys.readouterr().err


def test_dedupe_with_a_collector_line(live):
    root, run, tid = live
    hook_ev = record_hook.hook(root, line(outcome={"ok": True, "error": None, "ms": 5}))
    collector = dict(hook_ev, via="log", seq=1)
    collector.pop("seq")
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        assert record.registered_writer(root).append(collector) is None  # same id/kind/finished: hl dedupe
    assert len(events(root, run)) == 1
    assert (
        record_hook.hook(root, line(outcome={"ok": True, "error": None, "ms": 5})) is None
    )  # hook repeat too
    # another origin keeps its own key
    denial = dict(json.loads(line(kind="denial", used=USED, outcome={"ok": False, "error": "no", "ms": 1})))
    record_hook.hook(root, json.dumps(denial))
    other = dict(collector, kind="denial", via="core", outcome=denial["outcome"], used=USED)
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        assert record.registered_writer(root).append(other) is not None


def test_secret_values_never_reach_the_record(live):
    root, run, _ = live
    forms = [
        SECRET,
        base64.b64encode(SECRET.encode()).decode(),
        base64.urlsafe_b64encode(SECRET.encode()).decode(),
    ]
    forms.append(SECRET.encode().hex())
    for n, form in enumerate(forms):
        record_hook.hook(
            root,
            line(
                id=f"toolu_{n}",
                text=f"Run with {form}",
                data={"note": f"token {form}"},
                outcome={"ok": False, "error": f"failed {form}", "ms": 1},
                payload={"input": {"command": f"curl -H {form}"}, "output": f"leaked {form}"},
            ),
        )
    blob = b"".join(p.read_bytes() for p in (root / ".orch/record").rglob("*") if p.is_file())
    assert b"[hidden: " in blob
    for form in forms:
        assert form.encode() not in blob, form


def test_unknown_tool_names_are_plain_text(live):
    root, run, _ = live
    got = record_hook.hook(
        root,
        line(
            id="toolu_9",
            used={
                "kind": "mcp",
                "name": "weird.tool-name",
                "action": None,
                "source": "harness",
                "version": None,
            },
        ),
    )
    assert got is not None
    with pytest.raises(record.RecordRefused):
        record_hook.hook(root, line(id="toolu_10", used={"kind": "nonsense", "name": "x"}))


def test_timing_structural_one_run_file_only(live, monkeypatch):
    root, run, _ = live
    for n in range(300):
        record_hook.hook(root, line(id=f"toolu_pre{n}"))
    other = "r_other0001"
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        record.registered_writer(root).append(
            dict(
                json.loads(line(id="o1")),
                run=other,
                ticket="t_other0001",
                via="hook",
                seq=1,
                v=1,
                session=None,
                agent="main",
                parent=None,
                at="2026-11-16T09:12:05Z",
                harness="claude",
                coverage="full",
                detail=None,
            )
        )
    seen = []
    real = record._open

    def spy(ws, rel, *a, **k):
        seen.append(rel)
        return real(ws, rel, *a, **k)

    monkeypatch.setattr(record, "_open", spy)
    monkeypatch.setattr(record, "list_runs", lambda *a, **k: pytest.fail("scans every run"))
    t0 = time.perf_counter()
    record_hook.hook(root, line(id="toolu_last"))
    elapsed = time.perf_counter() - t0
    assert not any(rel[:2] == ("runs", other + ".jsonl") for rel in seen)
    assert elapsed < 0.5  # generous: loaded CI machine; the writer reads this one run file only


def test_cli_hook_command_exit_zero(live, monkeypatch, capsys):
    from orch import cli

    root, run, _ = live
    monkeypatch.setattr("sys.stdin", io.StringIO(line(kind="run.state") + "\n"))
    assert cli.main(["record", "hook"]) == 0
    assert "not allowed" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO(line(kind="run.state") + "\n"))
    assert cli.main(["record", "hook", "--strict"]) == 2
    monkeypatch.setattr("sys.stdin", io.StringIO(line(id="toolu_cli") + "\n"))
    assert cli.main(["record", "hook"]) == 0
    assert [e["id"] for e in events(root, run)] == ["toolu_cli"]

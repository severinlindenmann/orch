"""`orch job …` ingest (contracts/job-events.md, slice 2.1): binding, hiding, state rules, caps, reads."""

import base64
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from orch import cli, hider, jobs, record, runs, tickets

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
VECTORS = json.loads((CONTRACTS / "vectors/jobs-v1.json").read_text())
SECRET = "KEYVALUE-abc123XYZ-secret"
SECRETS = {
    SECRET,
    base64.b64encode(SECRET.encode()).decode(),
    urllib.parse.quote(SECRET),
    SECRET.encode().hex(),
}


def _schemas():
    docs = [json.loads((CONTRACTS / n).read_text()) for n in ("job-event.schema.json", "blocks.schema.json")]
    return Registry().with_resources([(d["$id"], Resource.from_contents(d)) for d in docs]), docs[0]


REG, EVENT_SCHEMA = _schemas()
STORED = Draft202012Validator(EVENT_SCHEMA, registry=REG)


@pytest.fixture
def live(proj, monkeypatch):
    t = tickets.create(proj, "Export it", "human:t")
    rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", t["id"])
    monkeypatch.delenv("ORCH_JOB", raising=False)
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        yield proj, rec["run"], t["id"]


def start(root, title="Export", **kw):
    return jobs.ingest(root, {"type": "start", "title": title, **kw})["job"]


def send(root, job, **ev):
    return jobs.ingest(root, ev, job=job)


def stream(root, run, job):
    return record.read_job(root, run, job).unwrap()


def stream_file(root, run, job):
    return root / ".orch/record/jobs" / run / f"{job}.jsonl"


def refused(code, fn, *a, **kw):
    with pytest.raises(jobs.JobError) as e:
        fn(*a, **kw)
    assert e.value.code == code, (e.value.code, str(e.value))
    return e.value


def test_schema_copy_matches_the_contract():
    here = Path(jobs.__file__).parent
    for name, src in (("job_event.schema.json", "job-event.schema.json"), ("blocks.schema.json", None)):
        assert (here / name).read_text() == (CONTRACTS / (src or name)).read_text()


def test_happy_path_is_stored_in_order_and_valid(live):
    root, run, tid = live
    job = start(root)
    assert job.startswith("j_")
    send(root, job, type="step", step="a", label="Read", state="running")
    send(root, job, type="progress", done=1, total=2, unit="files")
    send(root, job, type="metric", name="rows", value=12.5, unit="k")
    send(root, job, type="link", url="https://example.org/r", label="Report")
    send(root, job, type="log", text="hello", stream="err")
    table = {"type": "table", "columns": [{"key": "a", "label": "A"}], "rows": [{"a": 1}]}
    send(root, job, type="table", table=table)
    got = send(root, job, type="end", status="ok", summary="Done")
    events = stream(root, run, job)
    assert [e["seq"] for e in events] == list(range(1, 9)) and got == events[-1]
    assert all(STORED.is_valid(e) for e in events)
    assert {(e["run"], e["ticket"], e["job"]) for e in events} == {(run, tid, job)}
    assert jobs.state_of(events) == "ok"
    assert oct(stream_file(root, run, job).stat().st_mode & 0o777) == "0o600"


def test_jobs_appear_in_the_record_as_job_events(live):
    root, run, _ = live
    job = start(root, "Nightly export")
    send(root, job, type="log", text="not in the record")
    send(root, job, type="end", status="failed")
    rows = [e for e in record.read_run(root, run).unwrap() if e["kind"] == "job"]
    assert [(e["via"], e["data"]["type"], e["data"]["state"]) for e in rows] == [
        ("job", "start", "running"),
        ("job", "end", "failed"),
    ]
    assert rows[0]["text"] == "Nightly export" and rows[0]["ticket"] == live[2]


# orch's own `lost` event is not a program input; it has its own tests (test_a_quiet_job_is_lost...)
VECTOR_CASES = [c for c in VECTORS["replay"] if c["name"] not in ("cap", "lost only by orch")]


@pytest.mark.parametrize("case", VECTOR_CASES, ids=lambda c: c["name"])
def test_vector_state_rules_through_the_real_store(live, case):
    root, run, _ = live
    job, results = None, []
    for ev in case["events"]:
        try:
            if ev["type"] == "start" and job is None:
                job = start(root, ev["title"])
            else:
                jobs.ingest(root, ev, job=job or "j_nostart01")
            results.append("ok")
        except jobs.JobError as e:
            results.append(e.code)
    assert results == case["results"]
    if job:
        assert jobs.state_of(stream(root, run, job)) == case["state"]


def test_lost_by_a_program_is_never_stored(live):
    root, run, _ = live
    job = start(root)
    for ev in ({"type": "lost", "reason": "quiet"}, {"type": "lost", "reason": "quiet", "by": "orch"}):
        refused("not_allowed", send, root, job, **ev)
    assert jobs.state_of(stream(root, run, job)) == "running"


def test_vector_input_examples_are_accepted_or_refused_like_the_contract(live):
    root, run, _ = live
    job = start(root)
    for f in sorted((CONTRACTS / "examples/job-input").glob("invalid-*.json")):
        with pytest.raises(jobs.JobError):
            jobs.ingest(root, json.loads(f.read_text()), job=job)
    for f in sorted((CONTRACTS / "examples/job-input").glob("valid-*.json")):
        ev = json.loads(f.read_text())
        ev.pop("job", None)
        ev.pop("run", None)
        jobs.ingest(root, ev, job=start(root))


def test_vector_job_id_of_another_job_is_other_run(live):
    root, run, _ = live
    job = start(root)
    refused("other_run", jobs.ingest, root, {"type": "log", "text": "y", "job": "j_other0001"}, job=job)
    refused("other_run", jobs.ingest, root, {"type": "log", "text": "x", "run": "r_other001"}, job=job)


def test_cap_vector_stores_one_marker_line(live, monkeypatch):
    root, run, _ = live
    monkeypatch.setattr(jobs, "EVENT_CAP", 3)
    job = start(root)
    for n in range(2):
        send(root, job, type="log", text=str(n))
    refused("cap", send, root, job, type="log", text="3")
    refused("cap", send, root, job, type="end", status="ok")
    texts = [e.get("text") for e in stream(root, run, job)]
    assert texts[-1] == jobs.MORE and texts.count(jobs.MORE) == 1 and len(texts) == 4


def test_terminal_state_is_frozen_and_replays_store_nothing(live):
    root, run, _ = live
    job = start(root)
    send(root, job, type="end", status="failed")
    before = stream_file(root, run, job).read_bytes()
    for ev in (
        {"type": "end", "status": "failed"},
        {"type": "end", "status": "ok"},
        {"type": "log", "text": "late"},
    ):
        refused("ended", send, root, job, **ev)
        refused("ended", send, root, job, **ev)  # a replay stores nothing either
    assert stream_file(root, run, job).read_bytes() == before


def test_a_quiet_job_is_lost_and_the_late_event_is_refused(live):
    root, run, _ = live
    job = start(root, quiet_minutes=1)
    late = datetime.now(UTC) + timedelta(minutes=2)
    refused("ended", jobs.ingest, root, {"type": "log", "text": "x"}, job=job, now=late)
    events = stream(root, run, job)
    assert events[-1]["type"] == "lost" and events[-1]["by"] == "orch" and jobs.state_of(events) == "lost"
    assert STORED.is_valid(events[-1])


def test_progress_in_the_same_second_replaces_the_last(live):
    root, run, _ = live
    job = start(root)
    t = datetime.now(UTC).replace(microsecond=0)
    for n in (1, 2, 3):
        jobs.ingest(root, {"type": "progress", "done": n, "total": 9}, job=job, now=t)
    jobs.ingest(root, {"type": "progress", "done": 4, "total": 9}, job=job, now=t + timedelta(seconds=1))
    got = [(e["seq"], e["done"]) for e in stream(root, run, job) if e["type"] == "progress"]
    assert got == [(2, 3), (3, 4)]
    acts = [
        e
        for e in record.read_run(root, run).unwrap()
        if e["kind"] == "job" and e["data"]["type"] == "progress"
    ]
    assert len(acts) <= 1  # at most one progress per 5 s in the record


def test_progress_over_total_is_invalid(live):
    root, run, _ = live
    job = start(root)
    refused("invalid", send, root, job, type="progress", done=5, total=4)


# --- who may write ---
@pytest.mark.parametrize(
    "field", [("by", "orch"), ("seq", 7), ("ticket", "t_zzzzzz1"), ("pid", 4242), ("command", "rm")]
)
def test_program_cannot_send_fields_that_are_orchs(live, field):
    root, run, _ = live
    job = start(root)
    refused("not_allowed", send, root, job, type="log", text="x", **dict([field]))
    assert len(stream(root, run, job)) == 1


def test_program_cannot_write_lost_or_unknown_types(live):
    root, run, _ = live
    job = start(root)
    refused("not_allowed", send, root, job, type="lost", reason="quiet", by="orch")
    refused("not_allowed", send, root, job, type="lost", reason="quiet")
    for bad in ("approve", "ask", "check_done", "checked"):
        refused("invalid", send, root, job, type=bad)
    refused("invalid", send, root, job, type="end", status="checked")
    refused("invalid", send, root, job, type="end", status="ok", checked=True)
    assert [e["type"] for e in stream(root, run, job)] == ["start"]


def test_job_of_another_run_is_refused(live, monkeypatch):
    root, run, tid = live
    job = start(root)
    t2 = tickets.create(root, "Second", "human:t")
    rec2 = runs.claim(root, t2["id"], "agent:y", "claude", pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec2["run"])
    monkeypatch.setenv("ORCH_TICKET", t2["id"])
    refused("other_run", send, root, job, type="log", text="hijack")
    assert [e["type"] for e in stream(root, run, job)] == ["start"]
    assert not (root / ".orch/record/jobs" / rec2["run"]).exists()


def test_unknown_job_is_not_started_and_leaves_no_file(live):
    root, run, _ = live
    refused("not_started", send, root, "j_nothere01", type="log", text="x")
    assert not (root / ".orch/record/jobs").exists()


def test_job_id_must_be_a_job_id(live):
    root, _, _ = live
    refused("invalid", send, root, "../../x", type="log", text="x")


def test_second_start_for_the_same_job(live):
    root, _, _ = live
    job = start(root)
    refused("already_started", send, root, job, type="start", title="again")


def test_dead_claim_and_wrong_ids_write_nothing(live, monkeypatch):
    root, run, tid = live
    for env in ({"ORCH_RUN": "r_zzzzzz"}, {"ORCH_TICKET": "t_nothere1"}):
        with monkeypatch.context() as m:
            for k, v in env.items():
                m.setenv(k, v)
            refused("not_active", start, root)
    monkeypatch.setattr(runs, "state", lambda rec, at=None: "dead")
    refused("not_active", start, root)
    assert not (root / ".orch/record/jobs").exists()


def test_caller_outside_the_claims_process_tree_is_refused(proj, monkeypatch):
    t = tickets.create(proj, "Elsewhere", "human:t")
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        rec = runs.claim(proj, t["id"], "agent:x", "claude", pid=other.pid)
        monkeypatch.setenv("ORCH_RUN", rec["run"])
        monkeypatch.setenv("ORCH_TICKET", t["id"])
        with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
            e = refused("not_active", start, proj)
            assert "not from inside" in str(e)
    finally:
        other.kill()
        other.wait()
    assert not (proj / ".orch/record/jobs").exists()


def test_no_run_is_refused_in_plain_words(proj, monkeypatch):
    monkeypatch.delenv("ORCH_RUN", raising=False)
    monkeypatch.delenv("ORCH_TICKET", raising=False)
    refused("no_run", start, proj)
    assert not (proj / ".orch/record").exists()


def test_without_a_hider_nothing_is_written(live, monkeypatch):
    root, run, _ = live
    job = start(root)

    def off(root):
        raise record.RecordOff("Recording is off until key hiding is ready.")

    monkeypatch.setattr("orch.record_hook._writer", off)
    refused("hider_off", send, root, job, type="log", text="x")
    refused("hider_off", start, root)
    assert [e["type"] for e in stream(root, run, job)] == ["start"]


# --- hiding ---
def everything(root):
    out = b""
    for p in (root / ".orch").rglob("*"):
        if p.is_file():
            out += p.read_bytes()
    return out


def test_secrets_in_text_and_results_are_never_stored_in_any_encoded_form(live):
    root, run, _ = live
    forms = [
        SECRET,
        base64.b64encode(SECRET.encode()).decode(),
        urllib.parse.quote(SECRET),
        SECRET.encode().hex(),
    ]
    job = start(root, f"Export {SECRET}")
    for f in forms:
        send(root, job, type="log", text=f"value {f} end")
        send(root, job, type="step", step="s1", label=f"x {f}", state="running")
        send(root, job, type="metric", name=f"m {f}", value=1)
        # a url that carries a key is refused (the hidden marker is not a valid url): never stored
        refused("invalid", send, root, job, type="link", url=f"https://example.org/?k={f}", label="r")
        send(root, job, type="link", url="https://example.org/ok", label=f)
        send(root, job, type="progress", done=1, total=2, text=f)
    table = {
        "type": "table",
        "title": SECRET,
        "columns": [{"key": "a", "label": SECRET}],
        "rows": [{"a": f} for f in forms],
    }
    send(root, job, type="table", table=table)
    send(root, job, type="end", status="ok", summary=SECRET)
    blob = everything(root)
    for f in forms:
        assert f.encode() not in blob, f
    assert b"[hidden" in blob


def test_a_secret_as_a_table_column_key_is_refused_not_stored(live):
    root, run, _ = live
    job = start(root)
    key = SECRET.lower().replace("-", "_")
    with hider.use_hider(hider.Hider({"deploy-key": key})):
        refused(
            "invalid",
            send,
            root,
            job,
            type="table",
            table={"type": "table", "columns": [{"key": key, "label": "A"}], "rows": []},
        )
    assert key.encode() not in everything(root)


def test_log_text_is_cut_to_500_not_refused(live):
    root, run, _ = live
    job = start(root)
    got = send(root, job, type="log", text="x" * 900)
    assert len(got["text"]) == 500


# --- results are orch.blocks/1 tables ---
def test_invalid_results_are_refused_with_plain_words_and_never_stored(live):
    root, run, _ = live
    job = start(root)
    bad = [
        {"type": "table", "columns": [], "rows": []},
        {"type": "table", "columns": [{"key": "A!", "label": "A"}], "rows": []},
        {"type": "table", "columns": [{"key": "a", "label": "A"}], "rows": [{"a": {"deep": 1}}]},
        {"type": "chart", "columns": [{"key": "a", "label": "A"}], "rows": []},
        "not a table",
        None,
    ]
    for table in bad:
        e = refused("invalid", send, root, job, type="table", table=table)
        assert "not valid" in str(e) and "Traceback" not in str(e)
    assert [e["type"] for e in stream(root, run, job)] == ["start"]


def test_huge_and_deep_payloads_are_refused(live):
    root, run, _ = live
    job = start(root)
    refused("too_large", send, root, job, type="log", text="x" * 9000)
    rows = [{"a": "y" * 40} for _ in range(200)]
    refused(
        "too_large",
        send,
        root,
        job,
        type="table",
        table={"type": "table", "columns": [{"key": "a", "label": "A"}], "rows": rows},
    )
    deep = x = {}
    for _ in range(5000):
        x["n"] = {}
        x = x["n"]
    refused("too_large", send, root, job, type="table", table=deep)
    shallow = x = {}
    for _ in range(300):
        x["n"] = {}
        x = x["n"]
    refused("invalid", send, root, job, type="table", table=shallow)
    refused("invalid", send, root, job, type="progress", done=float("nan"))
    assert len(stream(root, run, job)) == 1


def test_artifact_must_be_a_file_inside_the_workspace(live):
    root, run, tid = live
    job = start(root)
    (root / "out.csv").write_text("a,b\n")
    send(root, job, type="artifact", path="out.csv", label="CSV")
    for path in ("../../etc/passwd", "/etc/passwd", ".env", ".orch/state.json", "missing.csv"):
        refused("invalid", send, root, job, type="artifact", path=path)
    (root / "link").symlink_to("/etc/passwd")
    refused("invalid", send, root, job, type="artifact", path="link")
    assert [e["type"] for e in stream(root, run, job)] == ["start", "artifact"]


# --- reads ---
def test_list_and_show_report_problems_explicitly(live):
    root, run, tid = live
    job = start(root)
    send(root, job, type="progress", done=1, total=2)
    listed = jobs.list_jobs(root)
    assert listed["status"] == "ok" and listed["jobs"][0]["state"] == "running"
    assert listed["jobs"][0]["reported_by"] == "job" and listed["jobs"][0]["progress"]["done"] == 1
    assert jobs.list_jobs(root, ticket="t_other001")["jobs"] == []
    shown = jobs.show_job(root, job)
    assert [e["type"] for e in shown["events"]] == ["start", "progress"]
    refused("not_found", jobs.show_job, root, "j_nothere01")
    # a stream changed outside orch: explicit marker, never quiet emptiness
    f = stream_file(root, run, job)
    f.write_text(f.read_text() + "not json\n")
    row = jobs.list_jobs(root)["jobs"][0]
    assert row["status"] == "tampered" and row["job"] == job and row["message"]
    refused("tampered", jobs.show_job, root, job)
    refused("tampered", send, root, job, type="log", text="x")


def test_a_linked_job_file_is_tampered(live):
    root, run, _ = live
    job = start(root)
    f = stream_file(root, run, job)
    other = root / "outside.txt"
    other.write_text("keep")
    f.unlink()
    f.symlink_to(other)
    assert jobs.list_jobs(root)["jobs"][0]["status"] == "tampered"
    refused("tampered", send, root, job, type="log", text="x")
    assert other.read_text() == "keep"


def test_jobs_per_run_cap(live, monkeypatch):
    root, _, _ = live
    monkeypatch.setattr(jobs, "JOBS_PER_RUN", 2)
    start(root)
    start(root)
    refused("cap", start, root)


# --- the CLI ---
def run_cli(capsys, *argv):
    code = cli.main(["job", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_flow_and_aliases(live, capsys):
    root, run, _ = live
    code, out, _ = run_cli(capsys, "start", "--title", "Export", "--json")
    job = json.loads(out)["job"]
    assert code == 0 and job.startswith("j_")
    assert run_cli(capsys, "step", "read", "--label", "Read", "--job", job, "--json")[0] == 0
    code, out, _ = run_cli(
        capsys, "progress", "--done", "3", "--total", "9", "--unit", "files", "--job", job, "--json"
    )
    assert json.loads(out)["done"] == 3 and json.loads(out)["seq"] == 3
    table = json.dumps({"type": "table", "columns": [{"key": "a", "label": "A"}], "rows": [{"a": 1}]})
    assert run_cli(capsys, "result", "--table", table, "--job", job, "--json")[0] == 0
    assert run_cli(capsys, "metric", "rows", "12", "--job", job, "--json")[0] == 0
    code, out, _ = run_cli(capsys, "done", "--summary", "ok", "--job", job, "--json")
    assert json.loads(out)["status"] == "ok"
    code, out, err = run_cli(capsys, "log", "late", "--job", job, "--json")
    assert code == 2 and "already ended" in err and json.loads(out)["code"] == "ended"
    code, out, _ = run_cli(capsys, "list", "--json")
    assert json.loads(out)["jobs"][0]["state"] == "ok"
    code, out, _ = run_cli(capsys, "show", job, "--json")
    assert json.loads(out)["job"]["events"] == 6


def test_cli_fail_alias_and_env_job(live, capsys, monkeypatch):
    root, run, _ = live
    job = json.loads(run_cli(capsys, "start", "--title", "X", "--json")[1])["job"]
    monkeypatch.setenv("ORCH_JOB", job)
    code, out, _ = run_cli(capsys, "fail", "--summary", "boom", "--exit", "3", "--json")
    assert code == 0 and json.loads(out)["status"] == "failed" and json.loads(out)["exit"] == 3


def test_cli_refusals_are_plain(live, capsys):
    code, out, err = run_cli(capsys, "start", "--json")
    assert code == 2 and "title" in err
    code, out, err = run_cli(capsys, "progress", "--done", "abc", "--json")
    assert code == 2 and "not a number" in err
    code, out, err = run_cli(capsys, "run", "--", "x", "--json")
    assert code == 2 and "not built" in err
    code, out, err = run_cli(capsys, "list")
    assert code == 2


def test_cli_start_ticket_must_match_the_run(live, capsys):
    code, out, err = run_cli(capsys, "start", "--title", "X", "--ticket", "t_other001", "--json")
    assert code == 2 and json.loads(out)["code"] == "other_run"


def test_every_job_stored_line_validates_against_the_contract_schema(live):
    root, run, _ = live
    job = start(root, "S", quiet_minutes=5)
    send(root, job, type="end", status="cancelled", exit=1)
    for e in stream(root, run, job):
        assert not list(STORED.iter_errors(e))

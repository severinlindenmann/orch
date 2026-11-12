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
    monkeypatch.delenv("ORCH_JOB_TOKEN", raising=False)
    with hider.use_hider(hider.Hider({"deploy-key": SECRET})):
        yield proj, rec["run"], t["id"]


TOKENS = {}


def ing(root, inp, job=None, **kw):
    """jobs.ingest with the job's write key remembered from its start."""
    kw.setdefault("token", TOKENS.get(job))
    got = jobs.ingest(root, inp, job=job, **kw)
    if inp.get("type") == "start":
        TOKENS[got["job"]] = got["token"]
    return got


def start(root, title="Export", **kw):
    return ing(root, {"type": "start", "title": title, **kw})["job"]


def send(root, job, **ev):
    return ing(root, ev, job=job)


def stream(root, run, job):
    return record.read_job(root, run, job, valid=jobs._STORED.is_valid).unwrap()


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
                ing(root, ev, job=job or "j_nostart01")
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
            ing(root, json.loads(f.read_text()), job=job)
    for f in sorted((CONTRACTS / "examples/job-input").glob("valid-*.json")):
        ev = json.loads(f.read_text())
        ev.pop("job", None)
        ev.pop("run", None)
        ing(root, ev, job=start(root))


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
    refused("cap", send, root, job, type="log", text="4")
    send(root, job, type="end", status="ok")  # one end may pass the cap: a job can always finish
    events = stream(root, run, job)
    assert [e.get("capped") for e in events].count(True) == 1 and events[-2]["text"] == jobs.MORE
    assert jobs.state_of(events) == "ok"


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
    refused("ended", ing, root, {"type": "log", "text": "x"}, job=job, now=late)
    events = stream(root, run, job)
    assert events[-1]["type"] == "lost" and events[-1]["by"] == "orch" and jobs.state_of(events) == "lost"
    assert STORED.is_valid(events[-1])


def test_progress_in_the_same_second_replaces_the_last(live):
    root, run, _ = live
    job = start(root)
    t = datetime.now(UTC).replace(microsecond=0)
    for n in (1, 2, 3):
        ing(root, {"type": "progress", "done": n, "total": 9}, job=job, now=t)
    ing(root, {"type": "progress", "done": 4, "total": 9}, job=job, now=t + timedelta(seconds=1))
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

    monkeypatch.setattr("orch.record_hook.record_writer", off)
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


def test_cli_flow_and_aliases(live, capsys, monkeypatch):
    root, run, _ = live
    code, out, _ = run_cli(capsys, "start", "--title", "Export", "--json")
    job = json.loads(out)["job"]
    assert code == 0 and job.startswith("j_") and len(json.loads(out)["token"]) == 32
    monkeypatch.setenv("ORCH_JOB_TOKEN", json.loads(out)["token"])
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
    started = json.loads(run_cli(capsys, "start", "--title", "X", "--json")[1])
    job = started["job"]
    monkeypatch.setenv("ORCH_JOB", job)
    monkeypatch.setenv("ORCH_JOB_TOKEN", started["token"])
    code, out, _ = run_cli(capsys, "fail", "--summary", "boom", "--exit", "3", "--json")
    assert code == 0 and json.loads(out)["status"] == "failed" and json.loads(out)["exit"] == 3


def test_cli_refusals_are_plain(live, capsys):
    code, out, err = run_cli(capsys, "start", "--json")
    assert code == 2 and "title" in err
    code, out, err = run_cli(capsys, "progress", "--done", "abc", "--json")
    assert code == 2 and "not a number" in err and "abc" not in err
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


# --- review round (API Opus on 83805601) ---
def test_a_sibling_job_cannot_be_written_without_its_token(live):
    root, run, _ = live
    mine, sibling = start(root, "Mine"), start(root, "Sibling")
    mine_token, sibling_token = TOKENS[mine], TOKENS[sibling]
    before = stream_file(root, run, sibling).read_bytes()
    for token in (None, "", mine_token, "x" * 32, sibling_token.upper()):
        e = refused("token", jobs.ingest, root, {"type": "log", "text": "hijack"}, job=sibling, token=token)
        assert sibling_token not in str(e)
    refused("token", jobs.ingest, root, {"type": "end", "status": "ok"}, job=sibling, token=mine_token)
    assert stream_file(root, run, sibling).read_bytes() == before
    jobs.ingest(root, {"type": "log", "text": "mine"}, job=sibling, token=sibling_token)
    assert [e["type"] for e in stream(root, run, sibling)] == ["start", "log"]


def test_token_is_handed_out_once_and_never_stored_in_plain(live, monkeypatch):
    root, run, _ = live
    job = start(root)
    token = TOKENS[job]
    ing(root, {"type": "log", "text": "x"}, job=job)
    ing(root, {"type": "end", "status": "ok"}, job=job)
    first = stream(root, run, job)[0]
    assert first["token_hash"] == jobs._hash(token) and token not in json.dumps(first)
    for blob in (
        everything(root),
        json.dumps(jobs.show_job(root, job)).encode(),
        json.dumps(jobs.list_jobs(root)).encode(),
    ):
        assert token.encode() not in (blob if isinstance(blob, bytes) else blob.encode())
    assert "token_hash" not in json.dumps(jobs.show_job(root, job))
    # a program cannot send the hash or the marker itself
    j2 = start(root)
    refused("not_allowed", send, root, j2, type="log", text="x", capped=True)
    refused("not_allowed", send, root, j2, type="log", text="x", token_hash="0" * 64)


def test_a_forged_line_without_the_fields_is_tampered_not_a_crash(live):
    root, run, _ = live
    job = start(root)
    f = stream_file(root, run, job)
    f.write_text(f.read_text() + json.dumps({"run": run, "job": job, "seq": 2}) + "\n")
    row = jobs.list_jobs(root)["jobs"][0]
    assert row["status"] == "tampered"
    refused("tampered", jobs.show_job, root, job)
    refused("tampered", send, root, job, type="log", text="x")


def test_a_cut_off_last_line_is_reported_and_dropped_under_the_lock(live):
    root, run, _ = live
    job = start(root)
    f = stream_file(root, run, job)
    f.write_text(f.read_text() + '{"v":1,"type":"lo')
    row = jobs.list_jobs(root)["jobs"][0]
    assert row["status"] == "unavailable" and row["reason"] == "torn"
    send(root, job, type="log", text="after the crash")
    assert [e["type"] for e in stream(root, run, job)] == ["start", "log"]


def test_replace_refuses_when_the_file_was_swapped(live, monkeypatch):
    root, run, _ = live
    job = start(root)
    t = datetime.now(UTC).replace(microsecond=0)
    ing(root, {"type": "progress", "done": 1, "total": 9}, job=job, now=t)
    f = stream_file(root, run, job)
    real = record._write_new

    def swapped(ws, rel, payload, *, expected=None):
        f.rename(f.with_name("moved"))
        f.write_text("planted")
        return real(ws, rel, payload, expected=expected)

    monkeypatch.setattr(record, "_write_new", swapped)
    refused("tampered", ing, root, {"type": "progress", "done": 2, "total": 9}, job=job, now=t)
    assert f.read_text() == "planted"  # never silently overwritten


def test_a_forged_marker_line_does_not_cap_a_job(live):
    root, run, _ = live
    job = start(root)
    got = send(root, job, type="log", text=jobs.MORE)
    assert "capped" not in got
    send(root, job, type="log", text="still fine")


def test_stream_and_run_byte_caps_are_checked_under_the_lock(live, monkeypatch):
    root, run, _ = live
    job = start(root)
    monkeypatch.setattr(record, "JOB_BYTES", 600)
    with pytest.raises(jobs.JobError) as e:
        for _ in range(20):
            send(root, job, type="log", text="y" * 100)
    assert e.value.code == "cap"
    monkeypatch.setattr(record, "JOB_BYTES", 5 * 1024**2)
    monkeypatch.setattr(record, "JOB_RUN_BYTES", 300)
    refused("cap", send, root, job, type="log", text="z" * 400)


def test_jobs_per_run_is_rechecked_inside_the_lock(live, monkeypatch):
    root, run, _ = live
    start(root)
    monkeypatch.setattr(jobs, "_all", lambda root, run=None: [])  # the outside check is blind
    monkeypatch.setattr(jobs, "JOBS_PER_RUN", 1)
    refused("cap", start, root)
    assert len(record.list_jobs(root, run).value) == 1  # no empty file left behind


def test_big_streams_append_instead_of_rewriting(live, monkeypatch):
    root, run, _ = live
    job = start(root)
    monkeypatch.setattr(record, "JOB_REPLACE_BYTES", 10)
    t = datetime.now(UTC).replace(microsecond=0)
    for n in (1, 2):
        ing(root, {"type": "progress", "done": n, "total": 9}, job=job, now=t)
    assert [e["seq"] for e in stream(root, run, job)] == [1, 2, 3]


def test_a_failed_record_line_leaves_a_gap_marker(live, monkeypatch):
    root, run, _ = live

    def boom(self, event, detail=None):
        raise record.RecordInvalid()

    monkeypatch.setattr(record.RecordWriter, "append", boom)
    job = start(root)
    assert len(stream(root, run, job)) == 1  # the job line is stored
    notes = "".join(p.read_text() for p in (root / ".orch/record/alerts").glob("hook-lost-2*.jsonl"))
    assert "job_activity" in notes


def test_the_final_end_is_accepted_when_the_run_is_full(live, monkeypatch):
    root, run, _ = live
    job, other = start(root), start(root)
    monkeypatch.setattr(record, "JOB_RUN_BYTES", 1)
    refused("cap", send, root, job, type="log", text="x")
    send(root, job, type="end", status="failed")
    send(root, other, type="end", status="ok")
    assert jobs.state_of(stream(root, run, job)) == "failed"


def test_a_refused_start_leaves_no_empty_file_and_noise_is_not_counted(live, monkeypatch):
    root, run, _ = live
    start(root)
    d = root / ".orch/record/jobs" / run
    (d / "tmp_abc").write_text("x")
    (d / "notes.txt").write_text("x")
    monkeypatch.setattr(jobs, "JOBS_PER_RUN", 2)
    start(root)  # the 2nd job still fits: tmp_ and other names do not count
    monkeypatch.setattr(jobs, "_all", lambda root, run=None: [])
    refused("cap", start, root)
    assert len([p for p in d.glob("j_*.jsonl")]) == 2
    # a first line that is refused inside the lock (too big for the stream) leaves nothing
    monkeypatch.setattr(jobs, "_all", lambda root, run=None: [])
    monkeypatch.setattr(jobs, "JOBS_PER_RUN", 10)
    monkeypatch.setattr(record, "JOB_BYTES", 10)
    refused("cap", start, root)
    assert len(list(d.glob("j_*.jsonl"))) == 2


def test_artifact_check_comes_after_the_token_check(live):
    root, run, _ = live
    job = start(root)
    refused("token", jobs.ingest, root, {"type": "artifact", "path": "missing.csv"}, job=job, token="bad")


def test_token_can_come_from_stdin(live, capsys, monkeypatch):
    import io

    started = json.loads(run_cli(capsys, "start", "--title", "X", "--json")[1])
    monkeypatch.setattr("sys.stdin", io.StringIO(started["token"] + "\n"))
    code, out, _ = run_cli(capsys, "log", "hi", "--job", started["job"], "--token", "-", "--json")
    assert code == 0 and json.loads(out)["text"] == "hi"


def test_a_repaired_torn_file_is_reread(live, monkeypatch):
    root, run, _ = live
    job = start(root)
    f = stream_file(root, run, job)
    f.write_text(f.read_text() + "cut")
    real = record._write_new

    def other(ws, rel, payload, *, expected=None):
        real(ws, rel, payload, expected=expected)
        f.write_text("planted\n")  # replaced again right after the repair

    monkeypatch.setattr(record, "_write_new", other)
    refused("tampered", send, root, job, type="log", text="x")

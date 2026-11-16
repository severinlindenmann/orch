"""The always-on debug log (contracts/diag.md): schema, hiding, caps, setting, symlinks, decisions."""

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import pytest

from orch import diag, hider, tickets
from orch.hider import Hider

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "diag.schema.json").read_text(encoding="utf-8"))
VALID = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
VECTORS = json.loads((CONTRACTS / "vectors" / "diag-v1.json").read_text(encoding="utf-8"))
SECRET = "sk-live-0123456789abcdef"


@pytest.fixture
def proj(proj):
    (proj / ".orch").mkdir(exist_ok=True)  # diag never makes .orch itself
    return proj


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(diag, "_state", {"root": None, "src": "cli", "seq": 0, "last_prune": None})
    for d in (diag._dropped, diag._rate, diag._enabled_cache, diag._hider_cache, diag._ws_cache):
        d.clear()
    diag._trace.set(None)
    monkeypatch.delenv("TRACEPARENT", raising=False)
    monkeypatch.delenv("ORCH_RUN", raising=False)
    monkeypatch.delenv("ORCH_TICKET", raising=False)


def events(proj, ev=None):
    out = diag.read_events(proj)
    return [e for e in out if ev is None or e["ev"] == ev]


def test_event_is_schema_valid_and_all_fields_present(proj):
    diag.log("test.something_happened", "info", root=proj, count=3, ok=True, name="x", ids=[1, 2])
    (e,) = events(proj, "test.something_happened")
    assert not list(VALID.iter_errors(e)), list(VALID.iter_errors(e))
    assert e["v"] == 1 and e["kv"] == {"count": 3, "ok": True, "name": "x", "ids": [1, 2]}
    assert e["code"].startswith("test_diag:test_event_is_schema_valid")
    assert e["err"] is None and e["pid"] == os.getpid()


@pytest.mark.parametrize("case", VECTORS["events"], ids=lambda c: c["name"])
def test_vectors_schema(case):
    errs = list(VALID.iter_errors(case["event"]))
    assert bool(errs) != case["valid"], errs


@pytest.mark.parametrize("case", VECTORS["names"], ids=lambda c: c["ev"])
def test_vectors_event_names(case):
    assert bool(diag._EV.fullmatch(case["ev"])) == case["valid"]


def test_folder_and_file_modes(proj):
    diag.log("test.mode", root=proj)
    d = proj / ".orch" / "diag"
    assert d.is_dir()
    (f,) = list(d.iterdir())
    if os.name == "posix":  # Windows has no file modes: its rights are ACLs
        assert (d.stat().st_mode & 0o777) == 0o700 and (f.stat().st_mode & 0o777) == 0o600
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\.cli\.1\.jsonl", f.name)


def test_hider_is_applied(proj, monkeypatch):
    with hider.use_hider(Hider({"api": SECRET})):
        diag.log("test.hide", root=proj, text=f"value {SECRET} here", items=[SECRET])
    raw = "".join(p.read_text() for p in (proj / ".orch" / "diag").iterdir())
    assert SECRET not in raw and "[hidden: api]" in raw


def test_secret_named_keys_and_long_strings_are_cut(proj):
    diag.log(
        "test.cut", root=proj, token="abc", api_key=["x"], password="p", n=5, long="a" * 1000, obj={"a": 1}
    )
    (e,) = events(proj, "test.cut")
    assert e["kv"]["token"] == e["kv"]["api_key"] == e["kv"]["password"] == "[hidden]"
    assert e["kv"]["n"] == 5 and len(e["kv"]["long"]) == 300 and "obj" not in e["kv"]


def test_error_has_type_and_frames_but_no_message_or_locals(proj):
    secret_local = "LOCALVALUE-1234567"  # noqa: F841 - must never appear in the log
    try:
        raise ValueError("message with MSGTEXT-998877")
    except ValueError as exc:
        diag.error("test.failed", exc, root=proj)
    raw = "".join(p.read_text() for p in (proj / ".orch" / "diag").iterdir())
    assert "MSGTEXT" not in raw and "LOCALVALUE" not in raw
    (e,) = events(proj, "test.failed")
    assert (
        e["lvl"] == "error"
        and e["err"]["type"] == "ValueError"
        and re.fullmatch(r"[0-9a-f]{16}", e["err"]["fingerprint"])
    )
    assert e["err"]["frames"][-1].startswith("test_diag:test_error_has_type")


def test_span_sets_parent_and_duration(proj):
    with diag.span("test.outer", root=proj):
        with diag.span("test.inner", root=proj):
            diag.log("test.leaf", root=proj)
    outer, inner, leaf = (events(proj, f"test.{n}")[0] for n in ("outer", "inner", "leaf"))
    assert outer["trace"]["trace_id"] == inner["trace"]["trace_id"] == leaf["trace"]["trace_id"]
    assert inner["trace"]["parent_span_id"] == outer["trace"]["span_id"]
    assert leaf["trace"]["span_id"] == inner["trace"]["span_id"]  # logged inside the inner span
    assert isinstance(outer["dur_ms"], int) and isinstance(inner["dur_ms"], int) and leaf["dur_ms"] is None


def test_span_records_an_exception_and_reraises(proj):
    with pytest.raises(KeyError), diag.span("test.boom", root=proj):
        raise KeyError("x")
    (e,) = events(proj, "test.boom")
    assert e["lvl"] == "error" and e["err"]["type"] == "KeyError"


def test_incoming_traceparent_is_joined_and_bad_ones_ignored():
    good = "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"
    tp = diag.new_trace(good)
    assert tp.split("-")[1] == "ab" * 16 and tp.split("-")[2] != "cd" * 8
    assert diag._trace.get()[2] == "cd" * 8
    for bad in (
        "",
        "garbage",
        "00-" + "0" * 32 + "-" + "cd" * 8 + "-01",
        "00-" + "ab" * 16 + "-" + "0" * 16 + "-01",
        None,
    ):
        assert diag.parse_traceparent(bad) is None
    assert diag.new_trace("nonsense").split("-")[1] != "ab" * 16


def test_traceparent_reaches_a_child_process(proj):
    diag.new_trace()
    env = diag.child_env({"PATH": os.environ["PATH"]})
    out = subprocess.run(
        [sys.executable, "-c", "import os;print(os.environ['TRACEPARENT'])"],
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out == diag.traceparent() and diag.parse_traceparent(out)
    assert diag.trace_env() == {"TRACEPARENT": diag.traceparent()}


def test_a_child_cli_joins_the_parents_trace(proj, run):
    tp = diag.new_trace()
    os.environ["TRACEPARENT"] = tp
    try:
        diag._trace.set(None)
        assert run("ticket", "list")[0] == 0
    finally:
        del os.environ["TRACEPARENT"]
    (e,) = events(proj, "cli.command")
    assert e["trace"]["trace_id"] == tp.split("-")[1] and e["trace"]["parent_span_id"] != tp.split("-")[2]
    assert (
        e["trace"]["parent_span_id"] is not None
    )  # a span inside the invocation, which joined the parent's trace


def test_disabled_setting_writes_nothing_and_keeps_old_files(proj, run):
    diag.log("test.before", root=proj)
    from orch import config

    config.set_diag_enabled(proj, False)
    diag.forget_settings()
    before = events(proj)
    diag.log("test.after", root=proj)
    assert events(proj) == before and run("config", "get", "diag.enabled")[1].strip() == "False"
    assert run("config", "set", "diag.enabled", "on")[0] == 0  # on needs no proof
    diag.log("test.again", root=proj)
    assert [e["ev"] for e in events(proj)][-1] == "test.again"


def test_default_is_on_and_readable_in_config_get(proj, run):
    assert json.loads(run("config", "get", "diag.enabled", "--json")[1]) == {"diag.enabled": True}


def test_diag_folder_symlink_is_refused(proj, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (proj / ".orch" / "diag").symlink_to(target)
    diag.log("test.link", root=proj)
    assert list(target.iterdir()) == [] and diag.dropped_count() >= 1


def test_orch_folder_symlink_is_refused(tmp_path):
    real, root = tmp_path / "real", tmp_path / "ws"
    (real / "diag").mkdir(parents=True)
    root.mkdir()
    (root / ".orch").symlink_to(real)
    diag.log("test.link2", root=root)
    assert list((real / "diag").iterdir()) == []


def test_file_symlink_is_not_followed(proj, tmp_path):
    diag.log("test.first", root=proj)
    (f,) = (proj / ".orch" / "diag").iterdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    f.unlink()
    f.symlink_to(victim)
    diag.log("test.second", root=proj)
    assert victim.read_text() == "keep"


def test_write_failure_never_raises_and_is_counted_then_reported(proj, monkeypatch):
    real_open = os.open

    def boom(path, *a, **k):
        if str(path).endswith(".jsonl"):
            raise OSError("disk full")
        return real_open(path, *a, **k)

    monkeypatch.setattr(os, "open", boom)
    diag.log("test.lost", root=proj)  # does not raise
    assert diag.dropped_count() >= 1
    monkeypatch.setattr(os, "open", real_open)
    diag.log("test.ok", root=proj)
    dropped = events(proj, "diag.dropped")
    assert dropped and dropped[0]["kv"]["count"] >= 1 and not list(VALID.iter_errors(dropped[0]))
    seqs = [e["seq"] for e in events(proj)]
    assert seqs == sorted(set(seqs))


def test_internal_error_never_raises(proj, monkeypatch):
    monkeypatch.setattr(diag, "_folder", lambda r: 1 / 0)
    diag.log("test.x", root=proj)
    assert diag.dropped_count("error") == 1


def test_no_hider_possible_writes_nothing(proj, monkeypatch):
    from orch import keystore

    monkeypatch.setattr(keystore, "all_needles", lambda root: 1 / 0)
    diag.log("test.nohider", root=proj)
    assert events(proj) == [] and diag.dropped_count("hider_off") == 1


def test_invalid_event_name_is_dropped(proj):
    diag.log("NotAnEvent", root=proj)
    assert events(proj) == [] and diag.dropped_count("invalid") == 1


def test_rate_cap_per_source_counts_dropped(proj, monkeypatch):
    monkeypatch.setattr(diag, "SRC_EVENTS_PER_MIN", 5)
    for _ in range(9):
        diag.log("test.flood", root=proj)
    assert len(events(proj, "test.flood")) == 5 and diag.dropped_count("source_events") == 4
    monkeypatch.setattr(diag, "SRC_EVENTS_PER_MIN", 50)
    diag.log("test.after", root=proj)
    (d,) = events(proj, "diag.dropped")
    assert d["kv"]["n_source_events"] == 4


def test_file_rotation_at_the_part_size(proj, monkeypatch):
    monkeypatch.setattr(diag, "FILE_MAX", 1500)
    for _ in range(12):
        diag.log("test.rotate", root=proj)
    names = sorted(p.name for p in (proj / ".orch" / "diag").iterdir())
    assert len(names) >= 2 and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}\.cli\.\d+\.jsonl", n) for n in names)
    assert len(events(proj, "test.rotate")) == 12


def test_source_day_byte_cap(proj, monkeypatch):
    monkeypatch.setattr(diag, "SRC_DAY_BYTES", 2500)
    for _ in range(10):
        diag.log("test.bytes", root=proj)
    n = len(events(proj, "test.bytes"))
    assert 0 < n < 10 and diag.dropped_count("source_bytes") == 10 - n


def _old(proj, days, name_src="cli", size=10):
    d = proj / ".orch" / "diag"
    d.mkdir(parents=True, exist_ok=True)
    day = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    p = d / f"{day}.{name_src}.1.jsonl"
    p.write_bytes(b"x" * size)
    return p


def test_retention_deletes_files_older_than_seven_days(proj):
    old, recent = _old(proj, 9), _old(proj, 2, "dashboard")
    other = proj / ".orch" / "diag" / "notes.txt"
    other.write_text("not ours")
    diag.prune(proj)
    assert not old.exists() and recent.exists() and other.exists()


def test_size_cap_deletes_oldest_first(proj, monkeypatch):
    monkeypatch.setattr(diag, "MAX_TOTAL_BYTES", 250)
    a, b, c = _old(proj, 5, size=100), _old(proj, 3, size=100), _old(proj, 1, size=100)
    diag.prune(proj)
    assert not a.exists() and b.exists() and c.exists()


def test_prune_runs_on_write(proj):
    old = _old(proj, 10)
    diag.log("test.prune", root=proj)
    assert not old.exists()


def test_ticket_op_applied_and_refused_events(proj, run, new_ticket):
    tid = new_ticket("Q3 invoices")
    tickets.apply_op(proj, tid, lambda t: t.update(title="Q3"), by="human:tester")
    applied = events(proj, "ticket.op_applied")[-1]
    kv = applied["kv"]
    assert applied["ticket"] == tid and kv["actor"] == "human:tester" and kv["written"] is True
    assert kv["revision_to"] == kv["revision_from"] + 1 and kv["status_from"] == kv["status_to"]
    assert "Q3" not in json.dumps(applied)  # no ticket text
    rev = kv["revision_to"]
    with pytest.raises(tickets.Conflict):
        tickets.apply_op(proj, tid, lambda t: None, if_revision=rev - 1, by="human:tester")
    refused = events(proj, "ticket.op_refused")[-1]["kv"]
    assert (
        refused["guard"] == "conflict"
        and refused["expected_revision"] == rev - 1
        and refused["actual_revision"] == rev
    )
    assert not any(list(VALID.iter_errors(e)) for e in events(proj))


def test_closed_ticket_refusal_names_the_guard(proj, run, new_ticket):
    tid = new_ticket("x")
    tickets.apply_op(proj, tid, lambda t: t.update(status="dropped"), by="human:tester")
    with pytest.raises(tickets.ClosedRefused):
        tickets.apply_op(proj, tid, lambda t: t.update(title="y"), by="agent:claude")
    assert events(proj, "ticket.op_refused")[-1]["kv"]["guard"] == "closed_ticket"


def test_old_ad_hoc_logs_moved_to_diag(proj):
    from orch import relay, runs_live, worktrees

    relay.log_send_failure(proj, "proposal question m_1 failed", RuntimeError("secret text MSGTEXT"))
    runs_live._log_submit(proj, "t_aaaaaa", "r_bbbbbb", "gave up")
    worktrees._log(proj, "t_aaaaaa: removed (done)")
    raw = "".join(p.read_text() for p in (proj / ".orch" / "diag").iterdir())
    assert "MSGTEXT" in raw  # the (cut) message of a relay failure is kept; ticket text never is
    assert events(proj, "relay.send_failed")[0]["kv"]["reason"] == "RuntimeError"
    assert events(proj, "run.live_submit")[0]["run"] == "r_bbbbbb"
    assert events(proj, "copies.clean")[0]["kv"]["line"].endswith("removed (done)")
    assert not (proj / ".orch" / "run" / "relay-errors.log").exists()


def test_diag_folder_is_git_ignored():
    from orch import harness

    assert "diag/" in harness.CONTRACT_IGNORE


def test_secret_straddling_the_cut_is_hidden(proj):
    with hider.use_hider(Hider({"api": SECRET})):
        diag.log("test.straddle", root=proj, text="a" * (diag.STR_MAX - 10) + SECRET + " tail")
        diag.log("test.straddle2", root=proj, ticket="x" * (diag.STR_MAX - 5) + SECRET)
    raw = "".join(p.read_text() for p in (proj / ".orch" / "diag").iterdir())
    assert SECRET not in raw and SECRET[:10] not in raw

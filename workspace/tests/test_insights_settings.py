"""Slice 2.11: Insights settings (`orch config get|set insights.*`, `orch record settings`) and the human-only
`orch record delete-detail` (human-proof.md `insights.settings`, `record.delete_detail`, invariant H1)."""

import json
import os
import time
from pathlib import Path

import pytest
from conftest import seal_append
from jsonschema import Draft202012Validator, FormatChecker

from orch import cli_record, config, hider, pagelaunch, pagesession
from orch import home as orch_home
from orch.errors import Refused
from orch.record import RecordWriter, record_dir

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
RUN_A, RUN_B, RUN_C = "r_8k2m01", "r_9z8y77", "r_7c7c7c"


@pytest.fixture
def ws(proj, monkeypatch):
    """A TEST workspace under <fake home>/.orch-test with its test home (as in test_human_proof_ops)."""
    from orch import addons

    base = addons.real_home() / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    _connect(root)  # share_counts on needs a relay connection (not_connected refuses it, see below)
    return root


def _connect(root, policy=None):
    """A relay connection (`.orch/secrets/relay.json`) and, if given, the last relay policy."""
    sec = root / ".orch" / "secrets"
    sec.mkdir(parents=True, exist_ok=True)
    conn = {"url": "https://r.example", "workspace": "w_1", "token": "orn_x"}
    (sec / "relay.json").write_text(json.dumps(conn))
    if policy is not None:
        (sec / "policy.json").write_text(json.dumps({"usage_counts": policy}))


def _disconnect(root):
    (root / ".orch" / "secrets" / "relay.json").unlink()


def _proof(ws, op, target, by="human:pat", **kw):
    return None  # no proof any more: kept so the call sites read the same


def _cli(run, monkeypatch, proof, *argv):
    return run(*argv, "--by", "human:pat")


def _answer(out):
    return json.loads(out.strip().splitlines()[-1])


def _get(run, key):
    code, out, err = run("config", "get", key, "--json")
    assert code == 0, out + err
    return json.loads(out)[key]


# ------------------------------------------------------------------ read


def test_get_defaults_and_aliases(ws, run):
    assert _get(run, "insights.share_counts") is True  # owner default (I5) while no record ever existed
    assert _get(run, "insights.share_names") is False
    assert _get(run, "insights.keep_days") == 90
    assert _get(run, "insights.max_mb") == 2048
    assert _get(run, "record.keep_days") == 90
    assert _get(run, "record.max_mb") == 2048
    code, out, _ = run("config", "get", "--json")
    listing = json.loads(out)
    assert {k: listing[k] for k in config.INSIGHTS_KEYS} == {
        "insights.share_counts": True,
        "insights.share_names": False,
        "insights.keep_days": 90,
        "insights.max_mb": 2048,
    }


# ------------------------------------------------------------------ write: widening needs the person

WIDENING = [  # (key, from: a narrowing done first, or None, value, effective value after)
    ("insights.share_names", None, "on", True),
    ("insights.share_counts", "off", "on", True),  # on by the owner default: it widens only from off
    ("insights.keep_days", None, "365", 365),
    ("insights.max_mb", None, "4096", 4096),
]


def _start(run, key, start):
    if start is not None:
        assert run("config", "set", key, start, "--by", "agent:x", "--json")[0] == 0  # narrowing: open


def test_if_current_only_for_insights(ws, run):
    code, out, err = run("config", "set", "workflow.copies", "off", "--if-current", "on")
    assert code == 2 and "--if-current" in out + err


# ------------------------------------------------------------------ share_counts: only where it is available


def test_share_counts_off_is_allowed_whatever_the_share_state(ws, run):
    _connect(ws, policy="off")
    code, out, err = run("config", "set", "insights.share_counts", "off", "--by", "agent:x", "--json")
    assert code == 0 and json.loads(out)["changed"] is True, out + err
    _disconnect(ws)
    assert config.share_counts_state(ws) == "not_connected"
    assert _get(run, "insights.share_counts") is False


def test_share_state_needs_a_full_relay_connection(ws):
    (ws / ".orch" / "secrets" / "relay.json").write_text(json.dumps({"url": "https://r.example"}))
    assert config.share_counts_state(ws) == "not_connected"
    (ws / ".orch" / "secrets" / "relay.json").write_text("not json")
    assert config.share_counts_state(ws) == "not_connected"
    _connect(ws, policy="off")
    assert config.share_counts_state(ws) == "off_by_admin"


def test_relay_refresh_keeps_the_admin_policy(ws):
    from orch import relay

    sec = ws / ".orch" / "secrets"
    relay._keep_policy(ws, {"usage_counts": "off", "live_session": "allowed"})
    assert json.loads((sec / "policy.json").read_text()) == {"usage_counts": "off"}
    assert config.share_counts_state(ws) == "off_by_admin"
    relay._keep_policy(ws, None)  # a snapshot without one keeps the last
    relay._keep_policy(ws, {"usage_counts": "maybe"})
    assert config.share_counts_state(ws) == "off_by_admin"
    relay._keep_policy(ws, {"usage_counts": "on"})
    assert config.share_counts_state(ws) == "on"


# ------------------------------------------------------------------ narrowing and retention


def test_insights_is_a_page_server(ws):
    assert "insights" in pagelaunch.LAUNCH_SERVERS and "insights" in pagesession.SERVERS
    pagesession.PageSession(ws, "insights")  # accepted as a page server
    token = pagelaunch.write_launch_token(ws, "insights")  # orch ships the add-on (its manifest)
    assert token and pagelaunch.consume_launch_token(ws, "insights", token)


def test_insights_launch_token_refused_without_a_shipped_manifest(ws, monkeypatch):
    """Insights in LAUNCH_SERVERS is not enough: the launch token needs the add-on in SHIPPED_ADDONS. With it
    unshipped (an older orch) no token is written and none is accepted; focus and dashboard keep theirs."""
    from orch import addons

    monkeypatch.setattr(addons, "SHIPPED_ADDONS", tuple(n for n in addons.SHIPPED_ADDONS if n != "insights"))
    assert "insights" not in addons.SHIPPED_ADDONS
    assert not pagelaunch.launch_server_ok("insights")
    with pytest.raises(orch_home.Refused):
        pagelaunch.write_launch_token(ws, "insights")
    assert not (orch_home.key_dir(ws) / "launch-insights.token").exists()
    orch_home._write_private(
        orch_home.key_dir(ws) / "launch-insights.token", f"{'a' * 32}\n{int(time.time()) + 30}\n"
    )
    assert (
        pagelaunch.consume_launch_token(ws, "insights", "a" * 32) is False
    )  # a planted token file does not count
    assert pagelaunch.launch_url(ws, "insights", "http://127.0.0.1:1/") == "http://127.0.0.1:1/"
    for server in ("focus", "dashboard"):
        token = pagelaunch.write_launch_token(ws, server)
        assert token and pagelaunch.consume_launch_token(ws, server, token)


def test_insights_never_resumes_a_page_session(ws):
    assert pagelaunch.write_resume_cookie(ws, "insights", "c" * 40, "s" * 40) is False
    assert not (orch_home.key_dir(ws) / "resume-insights.cookie").exists()
    planted = f"{'c' * 40}\n{'s' * 40}\n{int(time.time()) + 60}\n"
    orch_home._write_private(orch_home.key_dir(ws) / "resume-insights.cookie", planted)
    assert pagelaunch.take_resume_session(ws, "insights") is None  # a planted file is never adopted


def test_registry_drops_an_unshipped_builtin_insights(ws, monkeypatch):
    from orch import addons

    monkeypatch.setattr(addons, "SHIPPED_ADDONS", tuple(n for n in addons.SHIPPED_ADDONS if n != "insights"))
    monkeypatch.setattr(orch_home, "install_kind", lambda: "normal")
    path = addons.registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"name": "insights", "source": "built-in"}, {"name": "dashboard", "source": "built-in"}]
    path.write_text(json.dumps(entries))
    assert [e["name"] for e in addons.registry()] == ["dashboard"]


def _ops():
    schema = json.loads((CONTRACTS / "human-proof.schema.json").read_text())
    return schema["$defs"]["op"]["enum"]


# ------------------------------------------------------------------ record settings / delete-detail


@pytest.fixture
def rec(ws, run):
    """Two tickets: A with two runs that have detail, B with one run that has detail."""
    tids = []
    for title in ("A", "B"):
        code, out, _ = run("ticket", "new", title, "--json", "--by", "agent:x")
        tids.append(json.loads(out)["id"])
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    for run_id, tid in ((RUN_A, tids[0]), (RUN_B, tids[0]), (RUN_C, tids[1])):
        for n in (1, 2):
            w.append(
                dict(
                    example, run=run_id, ticket=tid, id=f"toolu_{run_id[2:]}{n}", at=f"2026-11-16T09:1{n}:00Z"
                ),
                detail={"input": {"n": n}, "output": "x" * 2000},
            )
    return tids


def _detail(ws, run_id):
    return record_dir(ws) / "detail" / run_id


def _lines(ws):
    return {p.name: p.read_bytes() for p in (record_dir(ws) / "runs").iterdir()}


def _changes(ws):
    folder = record_dir(ws) / "alerts"
    if not folder.is_dir():
        return []
    out = [json.loads(x) for p in folder.iterdir() for x in p.read_text().splitlines()]
    return [x for x in out if x.get("schema") == "orch.record-change/1"]


def test_lowering_retention_deletes_nothing_now(ws, rec, run):
    before = sorted(p for p in record_dir(ws).rglob("*") if p.is_file() and "alerts" not in p.parts)
    assert run("config", "set", "insights.keep_days", "30", "--json")[0] == 0
    assert run("config", "set", "insights.max_mb", "512", "--json")[0] == 0
    after = sorted(p for p in record_dir(ws).rglob("*") if p.is_file() and "alerts" not in p.parts)
    assert after == before


def test_delete_detail_with_a_proof(ws, rec, run, monkeypatch):
    a, b = rec
    lines = _lines(ws)
    counts_before = json.loads(run("record", "counts", "--json")[1])
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert json.loads(out) == {"deleted": 2, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert not _detail(ws, RUN_A).exists() and not _detail(ws, RUN_B).exists()
    assert _detail(ws, RUN_C).is_dir()  # the other ticket keeps its detail
    assert _lines(ws) == lines  # every line stays as it was
    counts_after = json.loads(run("record", "counts", "--json")[1])
    for k in ("generated_at", "inventory"):
        counts_before.pop(k), counts_after.pop(k)
    assert counts_after == counts_before
    (change,) = _changes(ws)
    assert (change["change"], change["by"], change["ticket"], change["deleted"]) == (
        "record.delete_detail",
        "human:pat",
        a,
        2,
    )
    schema = json.loads((CONTRACTS / "activity.schema.json").read_text())
    Draft202012Validator(
        {"$ref": "#/$defs/record_change", "$defs": schema["$defs"]}, format_checker=FormatChecker()
    ).validate(change)
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", f"toolu_{RUN_A[2:]}1", "--json")
    assert code == 2 and _answer(out)["code"] == "not_found"  # details not available
    again = _proof(ws, "record.delete_detail", a)  # nothing left: 0, and a new audit line
    code, out, _ = _cli(run, monkeypatch, again, "record", "delete-detail", a, "--json")
    assert code == 0
    assert json.loads(out) == {"deleted": 0, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert len(_changes(ws)) == 2


BAD_DELETE = {
    "missing": lambda ws, a, b: "",
    "garbage": lambda ws, a, b: "hp1.e30.AAAA",
    "expired": lambda ws, a, b: _proof(ws, "record.delete_detail", a, now=int(time.time()) - 500),
    "wrong target": lambda ws, a, b: _proof(ws, "record.delete_detail", b),
    "wrong op": lambda ws, a, b: _proof(ws, "insights.settings", a),
}


def _untouched(ws):
    assert _detail(ws, RUN_A).is_dir() and _detail(ws, RUN_B).is_dir() and _detail(ws, RUN_C).is_dir()
    assert _changes(ws) == []


@pytest.mark.parametrize("ticket", ["t_nothere1", "../x", "T_ABCDEF"])
def test_delete_detail_unknown_ticket(ws, rec, run, monkeypatch, ticket):
    code, out, _ = _cli(
        run,
        monkeypatch,
        _proof(ws, "record.delete_detail", "t_nothere1"),
        "record",
        "delete-detail",
        ticket,
        "--json",
    )
    assert code == 2 and _answer(out)["code"] == "not_found"
    _untouched(ws)


@pytest.mark.parametrize("which", [RUN_B, RUN_C])
def test_delete_detail_skips_an_unreadable_run_and_says_so(ws, rec, run, monkeypatch, tmp_path, which):
    """M4: a run that cannot be read is no veto: it is skipped (its detail stays, also this ticket's own
    files in it), counted in `unreadable`, and the CLI says so plainly; the readable runs lose this ticket's
    detail."""
    a, _ = rec
    run_file = record_dir(ws) / "runs" / f"{which}.jsonl"
    outside = tmp_path / "outside.jsonl"
    run_file.rename(outside)
    run_file.symlink_to(outside)  # one run of the record was changed outside orch (planted by an agent)
    before = sorted(p.name for p in _detail(ws, which).iterdir())
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    gone = 1 if which == RUN_B else 2  # RUN_B is A's: only RUN_A goes; RUN_C is B's: RUN_A and RUN_B go
    assert json.loads(out) == {"deleted": gone, "ticket": a, "kept": 0, "unreadable": 1, "skipped": 0}
    assert "1 run could not be read; its detail was not deleted." in err
    assert cli_record.delete_unreadable_text(3) == "3 runs could not be read; their detail was not deleted."
    assert not _detail(ws, RUN_A).exists()
    assert sorted(p.name for p in _detail(ws, which).iterdir()) == before  # the unreadable run keeps it all
    assert [c["deleted"] for c in _changes(ws)] == [gone]


def test_delete_detail_never_removes_a_folder_a_file_was_written_to_in_between(ws, rec, run, monkeypatch):
    """M3: after this ticket's files went, another ticket's detail written into the same run folder (before
    the folder is removed) stays: the folder goes only by rmdir, which fails when it is not empty. The files
    of a run are deleted under that run's lock (the writer stores detail under it)."""
    from orch import record

    a, _ = rec
    real, seen = record._rmdir_empty, []

    def write_in_between(ws_, rel):
        run_id = rel[-1]
        seen.append((run_id, (record_dir(ws) / "runs" / f"{run_id}.lock").exists()))
        late = record_dir(ws) / "detail" / run_id / ("f" * 32 + ".json")
        late.write_text("{}")  # another ticket's writer was quicker than the folder removal
        return real(ws_, rel)

    monkeypatch.setattr(record, "_rmdir_empty", write_in_between)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert sorted(seen) == [(RUN_A, True), (RUN_B, True)]  # under each run's lock
    for run_id in (RUN_A, RUN_B):
        assert [p.name for p in _detail(ws, run_id).iterdir()] == ["f" * 32 + ".json"]


def test_rmdir_empty_removes_only_an_empty_folder(ws, rec):
    from orch import record

    assert record._rmdir_empty(ws, ("detail", RUN_A)) is False  # not empty: stays
    assert _detail(ws, RUN_A).is_dir()
    (record_dir(ws) / "detail" / "r_emptyy1").mkdir()
    assert record._rmdir_empty(ws, ("detail", "r_emptyy1")) is True
    assert not (record_dir(ws) / "detail" / "r_emptyy1").exists()
    assert record._rmdir_empty(ws, ("detail", "r_emptyy1")) is False  # already gone


def test_delete_detail_deletes_this_tickets_orphan_files(ws, rec, run, monkeypatch):
    """M4: a detail file of this ticket that no line points at (the detail is written before its line: a crash
    in between) goes too and counts in `deleted`; another ticket's orphan and a file whose stored fields do
    not give its own name stay."""
    from orch import record

    a, b = rec
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())

    def orphan(run_id, tid, eid, *, name=None):
        payload = {
            "v": 1,
            "id": eid,
            "run": run_id,
            "kind": example["kind"],
            "ticket": tid,
            "input": {},
            "output": "orphan",
            "truncated": False,
            "hidden": 0,
        }
        name = name or record.detail_name(run_id, example["kind"], eid, tid)
        folder = _detail(ws, run_id)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / f"{name}.json"
        path.write_text(json.dumps(payload))
        os.chmod(path, 0o600)
        return path

    RUN_D = "r_4d4d4d"
    mine_in_c = orphan(RUN_C, a, "toolu_lost1")  # A's orphan in B's run
    mine_alone = orphan(RUN_D, a, "toolu_lost2")  # A's orphan in a run with no run file at all
    theirs = orphan(RUN_C, b, "toolu_lost3")  # B's orphan: stays
    renamed = orphan(RUN_C, a, "toolu_lost4", name="0" * 32)  # stored fields do not give this name: stays
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    # A, B, C, D
    assert json.loads(out) == {"deleted": 4, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert not mine_in_c.exists() and not mine_alone.exists() and not _detail(ws, RUN_D).exists()
    assert theirs.exists() and renamed.exists()
    assert len(list(_detail(ws, RUN_C).iterdir())) == 4  # B's two own files, B's orphan, the renamed one
    assert [c["deleted"] for c in _changes(ws)] == [4]


def test_delete_detail_needs_json(ws, rec, run):
    code, out, err = run("record", "delete-detail", rec[0])
    assert code == 2 and "Use --json" in err
    assert cli_record.SUBCOMMANDS == ("tail", "query", "counts", "settings", "delete-detail", "hook")


# ------------------------------------------------------------------ settle vectors (2.11 review)


# (file key, file value, effective value: snapped down, floor 30 / 512)
FILE_RETENTION = [
    ("keep_days", True, 90),  # a bool is not a number: the default
    ("keep_days", 1, 30),  # the floor: a file edit cannot make pruning delete nearly everything
    ("keep_days", 29, 30),
    ("keep_days", 45, 30),  # snapped DOWN to an allowed value
    ("keep_days", 100, 90),
    ("keep_days", 0, 30),  # <= 0: "as little as possible", the floor, never the default
    ("keep_days", -5, 30),
    ("max_mb", 0, 512),
    ("keep_days", 99999, 365),
    ("max_mb", 1, 512),
    ("max_mb", 600, 512),
    ("max_mb", False, 2048),
    ("max_mb", 10**9, 4096),
]


@pytest.mark.parametrize(("key", "value", "want"), FILE_RETENTION)
def test_file_retention_is_snapped_down_with_a_floor(ws, key, value, want):
    config.set_key(ws, "record", key, value)
    assert config.file_value(ws, "record", key) == want


def test_a_person_or_an_agent_changes_a_setting_plainly(ws, run):
    code, out, err = run("config", "set", "insights.keep_days", "365", "--by", "human:pat", "--json")
    assert code == 0, out + err
    assert _get(run, "insights.keep_days") == 365
    code, out, err = run("config", "set", "insights.share_names", "on", "--by", "agent:claude", "--json")
    assert code == 0, out + err
    assert _get(run, "insights.share_names") is True
    assert config.insights_share_names(ws) is True
    assert run("config", "set", "insights.share_names", "on")[0] == 0  # the same value again


def test_if_current_mismatch_is_changed_and_a_bad_value_lists_the_allowed_ones(ws, run):
    code, out, _ = run("config", "set", "insights.keep_days", "365", "--if-current", "30", "--json")
    assert code == 2 and _answer(out)["code"] == "changed"
    assert _get(run, "insights.keep_days") == 90
    code, out, _ = run("config", "set", "insights.keep_days", "7", "--json")
    assert code == 2 and _answer(out)["code"] == "invalid" and "30, 90, 365" in _answer(out)["error"]


def test_share_counts_on_is_refused_while_sharing_is_not_available(ws, run):
    _disconnect(ws)
    assert run("config", "set", "insights.share_counts", "off", "--json")[0] == 0  # off is always allowed
    code, out, _ = run("config", "set", "insights.share_counts", "on", "--json")
    assert code == 2 and _answer(out)["code"] == "not_available"
    _connect(ws)
    assert run("config", "set", "insights.share_counts", "on", "--json")[0] == 0


def test_key_lock_nested_in_one_thread_and_another_thread_waits(ws):
    """H1: keys.lock is re-entrant per thread by design (a depth count over one O_EXCL file): nested takes in
    one thread go through; a second thread blocks until the first thread's OUTERMOST exit."""
    import threading

    d = orch_home.key_dir(ws)
    order, entered = [], threading.Event()

    def other():
        with orch_home._key_lock(d):
            order.append("other")
        entered.set()

    with orch_home._key_lock(d):
        with orch_home._key_lock(d):  # nested in the same thread: no wait, no deadlock
            t = threading.Thread(target=other)
            t.start()
            assert not entered.wait(0.3)  # the other thread is held off ...
        assert not entered.wait(0.2)  # ... also after the INNER exit
        order.append("first")
    assert entered.wait(5)  # ... and gets in after the outermost exit
    t.join(5)
    assert order == ["first", "other"]


# ------------------------------------------------------------------ the lock


def test_key_lock_is_reentrant_and_only_the_outermost_exit_unlocks(ws):
    d = orch_home.key_dir(ws)
    lock = d / "keys.lock"
    with orch_home._key_lock(d):
        with orch_home._key_lock(d):
            with orch_home._key_lock(d):
                assert lock.exists()
            assert lock.exists() and orch_home._lock_held(d)  # an inner exit keeps the outer lock
        assert lock.exists() and orch_home._lock_held(d)
    assert not lock.exists() and not orch_home._lock_held(d)


# ------------------------------------------------------------------ delete-detail (2.11 review)


@pytest.mark.parametrize("error", [OSError("disk"), "invalid"])
def test_delete_detail_audit_line_failure_deletes_nothing(ws, rec, run, monkeypatch, error):
    from orch import record

    def fail(*a, **k):
        raise record.RecordInvalid() if error == "invalid" else error

    monkeypatch.setattr(record, "note_change", fail)
    a, _ = rec
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 2 and _answer(out) == {"error": cli_record.DELETE_NOT_SAVED, "code": "not_available"}
    assert "Traceback" not in err and str(ws) not in out + err
    _untouched(ws)


def test_delete_detail_symlinked_detail_folder_is_tampered(ws, rec, run, monkeypatch, tmp_path):
    a, _ = rec
    detail = record_dir(ws) / "detail"
    moved = tmp_path / "moved-detail"
    detail.rename(moved)
    detail.symlink_to(moved, target_is_directory=True)
    code, out, _ = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 2 and _answer(out)["code"] == "tampered"
    assert (moved / RUN_A).is_dir() and (moved / RUN_B).is_dir() and (moved / RUN_C).is_dir()
    assert _changes(ws) == []


def test_delete_detail_partial_deletion(ws, rec, run, monkeypatch):
    """A crash in the middle: the audit line (written first) stays, the error is plain (not_available), what
    is left goes with a new proof."""
    from orch import record

    a, _ = rec
    real, calls = record._unlink, []

    def flaky(*args, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk")
        return real(*args, **kw)

    monkeypatch.setattr(record, "_unlink", flaky)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 2 and _answer(out) == {"error": cli_record.DELETE_PARTLY, "code": "not_available"}
    assert "Traceback" not in err
    left = [p for r in (RUN_A, RUN_B) if _detail(ws, r).is_dir() for p in _detail(ws, r).iterdir()]
    assert 1 <= len(left) < 4
    assert len(_changes(ws)) == 1
    monkeypatch.setattr(record, "_unlink", real)
    code, out, _ = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0 and json.loads(out)["ticket"] == a
    assert not _detail(ws, RUN_A).exists() and not _detail(ws, RUN_B).exists() and _detail(ws, RUN_C).is_dir()


def test_delete_detail_keeps_other_tickets_detail_in_a_shared_run(ws, rec, run, monkeypatch):
    """A line of ticket A added to B's run (e.g. by a hook caller) makes the run shared: A's proof deletes
    only the detail A's own lines point at; B's detail in that run stays readable."""
    a, b = rec
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    w.append(
        dict(example, run=RUN_C, ticket=a, id="toolu_planted1", at="2026-11-16T09:15:00Z"),
        detail={"input": {"n": 9}, "output": "planted"},
    )
    before = sorted(p.name for p in _detail(ws, RUN_C).iterdir())
    assert len(before) == 3
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    # RUN_A, RUN_B and A's one file in RUN_C
    assert json.loads(out) == {"deleted": 3, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    after = sorted(p.name for p in _detail(ws, RUN_C).iterdir())
    assert len(after) == 2 and set(after) < set(before)
    for n in (1, 2):  # B's detail is still there
        code, out, _ = run("record", "query", "--run", RUN_C, "--detail", f"toolu_{RUN_C[2:]}{n}", "--json")
        assert code == 0, out
    code, out, _ = run("record", "query", "--run", RUN_C, "--detail", "toolu_planted1", "--json")
    assert code == 2 and _answer(out)["code"] == "not_found"


def _plant(ws, run_id, line):
    """A line that verifies but is wrong in content: sealed as code holding orch's key could (conftest). A raw
    unsigned line is never shown at all (test_record_mac.py)."""
    seal_append(ws, run_id, line)


def _own_line(ws, run_id, n):
    path = record_dir(ws) / "runs" / f"{run_id}.jsonl"
    line = next(
        e for e in map(json.loads, path.read_text().splitlines()) if e["id"] == f"toolu_{run_id[2:]}{n}"
    )
    return {k: v for k, v in line.items() if k != "auth"}


def _planted_b_line(ws, b):
    """A line of ticket B in A's run naming A's detail file (same id, finished, so dedupe keeps it)."""
    victim = _own_line(ws, RUN_A, 1)
    return dict(victim, ticket=b, seq=99, outcome={"ok": True, "error": None, "ms": 1})


def test_detail_names_differ_per_ticket_in_one_run(ws, rec):
    """I4: ticket A's line in B's run with the same run, kind and id gets its own detail file."""
    from orch import record

    a, b = rec
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    same = f"toolu_{RUN_C[2:]}1"
    mine = w.append(
        dict(
            example,
            run=RUN_C,
            ticket=a,
            id=same,
            at="2026-11-16T09:15:00Z",
            outcome={"ok": True, "error": None, "ms": 1},
        ),
        detail={"input": {"n": 9}, "output": "a's own"},
    )
    theirs = _own_line(ws, RUN_C, 1)
    assert (mine["id"], mine["kind"]) == (theirs["id"], theirs["kind"]) and theirs["ticket"] == b
    assert mine["detail"] and theirs["detail"] and mine["detail"] != theirs["detail"]
    for line, ticket, output in ((mine, a, "a's own"), (theirs, b, "x" * 2000)):
        got = record.read_detail(
            ws, RUN_C, Path(line["detail"]).stem, line_id=line["id"], ticket=ticket
        ).unwrap()
        assert (got["ticket"], got["output"]) == (ticket, output)


def test_planted_line_of_another_ticket_does_not_block_delete(ws, rec, run, monkeypatch):
    """A line of ticket B pointing at A's detail file does not stop A's delete (no veto by other tickets), and
    A's delete leaves B's own detail alone, also B's file in a run A shares."""
    a, b = rec
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    w.append(
        dict(
            example,
            run=RUN_C,
            ticket=a,
            id=f"toolu_{RUN_C[2:]}1",
            at="2026-11-16T09:15:00Z",
            outcome={"ok": True, "error": None, "ms": 1},
        ),
        detail={"input": {"n": 9}, "output": "a's own"},
    )
    _plant(ws, RUN_A, _planted_b_line(ws, b))
    b_files = sorted(p.name for p in _detail(ws, RUN_C).iterdir())
    assert len(b_files) == 3
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert json.loads(out) == {"deleted": 3, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert not _detail(ws, RUN_A).exists() and not _detail(ws, RUN_B).exists()
    left = sorted(p.name for p in _detail(ws, RUN_C).iterdir())
    assert len(left) == 2 and set(left) < set(b_files)
    from orch import record

    for n in (1, 2):  # B's own detail is untouched and still readable through B's own lines
        line = _own_line(ws, RUN_C, n)
        got = record.read_detail(ws, RUN_C, Path(line["detail"]).stem, line_id=line["id"], ticket=b).unwrap()
        assert (got["ticket"], got["output"]) == (b, "x" * 2000)
    code, out, _ = run("record", "query", "--run", RUN_C, "--detail", f"toolu_{RUN_C[2:]}2", "--json")
    assert code == 0 and json.loads(out)["output"] == "x" * 2000


def test_planted_line_path_is_refused_on_read_and_counted_as_kept(ws, rec, run, monkeypatch):
    """The planted line of B names A's file: reading it through that line is refused (the file's own ticket is
    not the line's), and B's delete does not follow it: A's file stays, reported as kept (never silent)."""
    a, b = rec
    _plant(ws, RUN_A, _planted_b_line(ws, b))
    target = _own_line(ws, RUN_A, 1)["id"]
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", target, "--json")
    assert code == 2 and _answer(out)["code"] == "tampered"
    a_files = sorted(p.name for p in _detail(ws, RUN_A).iterdir())
    assert len(a_files) == 2
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", b), "record", "delete-detail", b, "--json"
    )
    assert code == 0, out + err
    # B's RUN_C goes; A's file named by B's planted line stays and is reported
    assert json.loads(out) == {"deleted": 1, "ticket": b, "kept": 1, "unreadable": 0, "skipped": 0}
    assert not _detail(ws, RUN_C).exists()
    assert sorted(p.name for p in _detail(ws, RUN_A).iterdir()) == a_files
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", f"toolu_{RUN_A[2:]}2", "--json")
    assert code == 0 and json.loads(out)["ticket"] == a


@pytest.mark.parametrize("how", ["fifo", "file_link", "folder_link"])
def test_planted_unsafe_detail_of_one_run_is_no_veto(ws, rec, run, monkeypatch, tmp_path, how):
    """MED-1 / R1: a planted line of ticket A (a made-up id) plus a FIFO or a link at the detail name it
    computes: only that FILE is skipped (`skipped`), A's real detail in the same run and in the other run
    goes. A linked run detail FOLDER: that run is skipped and counted unreadable (its detail stays), the
    other run loses A's detail. Never a veto of the whole delete."""
    from orch import record

    if how == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("requires FIFO")
    a, _ = rec
    victim, kept_run = (RUN_B, RUN_A) if how == "folder_link" else (RUN_A, RUN_B)
    line = _own_line(ws, victim, 1)
    name = record.detail_name(victim, line["kind"], "toolu_fake01", a)
    _plant(ws, victim, dict(line, id="toolu_fake01", seq=99, detail=f"detail/{victim}/{name}.json"))
    target = _detail(ws, victim) / f"{name}.json"
    outside = tmp_path / "outside"
    outside.mkdir()
    if how == "fifo":
        os.mkfifo(target, 0o600)
    elif how == "file_link":
        (outside / "x.json").write_text("{}")
        target.symlink_to(outside / "x.json")
    else:
        _detail(ws, victim).rename(outside / victim)
        _detail(ws, victim).symlink_to(outside / victim, target_is_directory=True)
    before = sorted(p.name for p in _detail(ws, victim).iterdir())
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert not _detail(ws, kept_run).exists()  # the other run of A lost its detail
    assert _detail(ws, RUN_C).is_dir()
    if how == "folder_link":
        assert json.loads(out) == {"deleted": 1, "ticket": a, "kept": 0, "unreadable": 1, "skipped": 0}
        assert "1 run could not be read; its detail was not deleted." in err
        assert sorted(p.name for p in _detail(ws, victim).iterdir()) == before  # the skipped run keeps it all
        assert [c["deleted"] for c in _changes(ws)] == [1]
    else:
        assert json.loads(out) == {"deleted": 2, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 1}
        assert "1 detail file was changed outside orch; it was not deleted." in err
        assert "could not be read" not in err
        # A's two real files in the victim run went; only the planted one stays (and what it points at)
        assert [p.name for p in _detail(ws, victim).iterdir()] == [f"{name}.json"] and len(before) == 3
        assert how == "fifo" or (outside / "x.json").read_text() == "{}"
        assert [c["deleted"] for c in _changes(ws)] == [2]


def test_find_detail_files_skips_an_unsafe_file_or_run_and_refuses_only_an_unsafe_detail_folder(
    ws, rec, tmp_path
):
    """R1: a file that is not safe skips only that pair (`kept`); a run's folder that is a link skips that run
    (`unreadable`); only the detail folder itself refuses. N3: the answer is not a tuple (an old caller that
    unpacks it fails loudly)."""
    from orch import record

    files = {r: sorted(p.stem for p in _detail(ws, r).iterdir()) for r in (RUN_A, RUN_B)}
    items = [(r, f) for r in (RUN_A, RUN_B) for f in files[r]]
    bad = (RUN_A, files[RUN_A][0])
    (_detail(ws, RUN_A) / f"{bad[1]}.json").unlink()
    (_detail(ws, RUN_A) / f"{bad[1]}.json").symlink_to(tmp_path)
    got = record.find_detail_files(ws, items)
    assert got.status == "ok" and got.alert is None
    assert got.value == record.DetailFiles(tuple(ref for ref in items if ref != bad), (), (bad,))
    with pytest.raises(TypeError):
        pairs, runs = got.value
    _detail(ws, RUN_B).rename(tmp_path / "moved_b")
    _detail(ws, RUN_B).symlink_to(tmp_path / "moved_b", target_is_directory=True)
    got = record.find_detail_files(ws, items)
    assert got.value == record.DetailFiles(((RUN_A, files[RUN_A][1]),), (RUN_B,), (bad,))
    detail = record_dir(ws) / "detail"
    detail.rename(tmp_path / "moved")
    detail.symlink_to(tmp_path / "moved", target_is_directory=True)
    got = record.find_detail_files(ws, items)
    link = "reparse" if os.name == "nt" else "link"  # Windows sees a symlink as a reparse point first
    assert got.status == "tampered" and got.reason == link


@pytest.mark.parametrize("how", ["file", "folder"])
def test_detail_that_cannot_be_read_is_kept_never_a_veto(ws, rec, how):
    """B1: a planted file or folder in a run's detail that cannot be read (mode 000) is reported and stays
    (`kept`); the run's other detail goes: in find_detail_files, delete_detail_files and retention's
    delete_detail (_detail_parts). Never a whole refusal."""
    from orch import record

    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("mode 000 blocks reading only for a non-root POSIX user")
    items = [(r, p.stem) for r in (RUN_A, RUN_B) for p in sorted(_detail(ws, r).iterdir())]  # A's real files
    planted = "f" * 32
    targets = [_detail(ws, r) / f"{planted}.json" for r in (RUN_A, RUN_C)]
    for target in targets:
        if how == "file":
            target.write_text("{}")
        else:
            target.mkdir()
        target.chmod(0)
    try:
        want = record.DetailFiles(tuple(items), (), ((RUN_A, planted),))
        got = record.find_detail_files(ws, [*items, (RUN_A, planted)])
        assert got.status == "ok" and got.value == want
        assert record.delete_detail_files(ws, [*items, (RUN_A, planted)]) == want
        # only the planted one stays
        assert [p.name for p in _detail(ws, RUN_A).iterdir()] == [targets[0].name]
        assert not _detail(ws, RUN_B).exists()
        assert len(list(_detail(ws, RUN_C).iterdir())) == 3
        record.delete_detail(ws, [RUN_C], seen_by="retention")  # no raise: only the planted entry is left out
        assert [p.name for p in _detail(ws, RUN_C).iterdir()] == [targets[1].name]
    finally:
        for target in targets:
            target.chmod(0o700)


def test_delete_detail_files_a_run_pruned_in_between_is_already_gone(ws, rec, run, monkeypatch):
    """L4: retention pruned a run between finding the files and deleting them: already gone, not a partial
    delete; the other run's files go."""
    import shutil

    from orch import record

    a, _ = rec
    real = record.delete_detail_files

    def pruned_first(root, items, **kw):
        shutil.rmtree(_detail(ws, RUN_B))  # retention, at the same moment
        return real(root, items, **kw)

    monkeypatch.setattr(record, "delete_detail_files", pruned_first)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    # the answer says what this call deleted (RUN_A); the audit line, written before, what was going to go
    assert json.loads(out) == {"deleted": 1, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert [c["deleted"] for c in _changes(ws)] == [2]
    assert not _detail(ws, RUN_A).exists() and not _detail(ws, RUN_B).exists()
    nothing = real(ws, [(RUN_B, "a" * 32), ("r_gone0001", "b" * 32)])  # nothing there: nothing fails
    assert nothing == record.DetailFiles()


@pytest.mark.parametrize("how", ["file", "folder", "lock"])
def test_delete_detail_files_a_swap_after_finding_skips_only_that(ws, rec, run, monkeypatch, tmp_path, how):
    """N4: after the files were found (and the audit line written), one file, the run's detail folder or the
    run's lock is swapped for a link: only that file (or run) stays, reported; the rest goes and the answer
    says what went. No whole refusal after the audit line."""
    from orch import record

    a, _ = rec
    real = record.delete_detail_files
    first = sorted(_detail(ws, RUN_A).iterdir())[0]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("x")

    def swapped_first(root, items, **kw):
        if how == "file":
            first.unlink()
            first.symlink_to(elsewhere)
        elif how == "folder":
            _detail(ws, RUN_A).rename(tmp_path / "moved")
            _detail(ws, RUN_A).symlink_to(tmp_path / "moved", target_is_directory=True)
        else:
            (record_dir(ws) / "runs" / f"{RUN_A}.lock").symlink_to(elsewhere)
        return real(root, items, **kw)

    monkeypatch.setattr(record, "delete_detail_files", swapped_first)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert [c["deleted"] for c in _changes(ws)] == [2]  # the audit line: what was going to go
    assert not _detail(ws, RUN_B).exists() and _detail(ws, RUN_C).is_dir()
    assert elsewhere.read_text() == "x"
    if how == "file":
        assert json.loads(out) == {"deleted": 2, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 1}
        assert "1 detail file was changed outside orch; it was not deleted." in err
        assert [p.name for p in _detail(ws, RUN_A).iterdir()] == [first.name]  # only the swapped one stays
    else:
        assert json.loads(out) == {"deleted": 1, "ticket": a, "kept": 0, "unreadable": 1, "skipped": 0}
        assert "1 run could not be read; its detail was not deleted." in err
        assert len(list(_detail(ws, RUN_A).iterdir())) == 2  # the skipped run keeps all its detail


# ------------------------------------------------------------------ prune reads the effective values


# ------------------------------------------------------------------ --detail compares ticket and id (M5)


def test_detail_of_a_line_with_no_ticket_is_tampered(ws, rec, monkeypatch, run):
    """The line's ticket is ALWAYS compared: a line with no ticket (None) never reads a stored t_... file."""
    from orch import record

    real = record.read_run

    def ticketless(*a, **k):
        result = real(*a, **k)
        for e in result.value or []:
            e.pop("ticket", None)
        return result

    monkeypatch.setattr(record, "read_run", ticketless)
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", f"toolu_{RUN_A[2:]}1", "--json")
    assert code == 2 and _answer(out)["code"] == "tampered"


def test_detail_whose_stored_id_is_not_the_lines_is_tampered(ws, rec, run):
    """A planted line of the SAME ticket with another id pointing at an existing file: the stored id
    differs."""
    victim = _own_line(ws, RUN_A, 1)
    _plant(ws, RUN_A, dict(victim, id="toolu_fake01", seq=99))
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", "toolu_fake01", "--json")
    assert code == 2 and _answer(out)["code"] == "tampered"
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", victim["id"], "--json")
    assert code == 0 and json.loads(out)["id"] == victim["id"]


def test_relay_connect_clears_the_last_admin_policy(ws, monkeypatch):
    """A (re)connection never inherits a stale admin policy; the refresh of THIS connection writes it."""
    from orch import net, relay

    _connect(ws, "off")
    assert config.share_counts_state(ws) == "off_by_admin"
    monkeypatch.setattr(net, "connect_service", lambda *a, **k: {"workspace": "w_2"})
    monkeypatch.setattr(relay, "refresh", lambda root: "refreshed")
    relay.connect(ws, "https://r2.example", "w_2", "orn_y")
    assert not (net.secrets_dir(ws) / "policy.json").exists()
    assert config.share_counts_state(ws) == "on"


def test_relay_connect_that_fails_keeps_the_current_policy(ws, monkeypatch):
    """N7: a failed reconnect (a wrong token: nothing written) keeps the current connection's admin policy, so
    its off_by_admin guard stays; a connection that stops half-way AFTER writing the new relay.json never
    pairs with the old policy; a successful one clears it also when the old connection's refresh wrote one
    in between."""
    from orch import net, relay

    _connect(ws, "off")
    policy = net.secrets_dir(ws) / "policy.json"
    conn = net.secrets_dir(ws) / "relay.json"

    def wrong_token(*a, **k):
        raise Refused("That token does not look right.")

    monkeypatch.setattr(net, "connect_service", wrong_token)
    with pytest.raises(Refused):
        relay.connect(ws, "https://r2.example", "w_2", "orn_y")
    assert policy.is_file() and config.share_counts_state(ws) == "off_by_admin"

    def half_way(*a, **k):
        conn.write_text(json.dumps({"url": "https://r2.example", "workspace": "w_2", "token": "orn_y"}))
        raise OSError("the skills could not be refreshed")

    monkeypatch.setattr(net, "connect_service", half_way)
    with pytest.raises(OSError):
        relay.connect(ws, "https://r2.example", "w_2", "orn_y")
    assert not policy.exists() and config.share_counts_state(ws) == "on"

    _connect(ws, "off")
    monkeypatch.setattr(
        net, "connect_service", lambda *a, **k: policy.write_text("{}") or {"workspace": "w_2"}
    )
    monkeypatch.setattr(relay, "refresh", lambda root: "refreshed")
    relay.connect(ws, "https://r2.example", "w_2", "orn_y")
    assert not policy.exists()


def test_an_event_with_no_ticket_gets_no_detail_file(ws):
    """M5: one rule for a missing ticket: no detail file (not detail_lost); the writer's guard."""
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    event = {"run": RUN_A, "kind": "step", "id": "toolu_x", "ticket": None}
    assert w._prepare_detail(event, {"input": {}, "output": "x"}) is None
    assert "detail_lost" not in event

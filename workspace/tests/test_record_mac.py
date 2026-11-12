"""Record MAC, slice S2: the writer seals, the readers verify (activity.md, Authenticated record). Adversarial
tests through the record API and the `orch record` CLI. Raw run files are made with conftest.seal_lines."""

import json
import time
from pathlib import Path

import pytest
from conftest import seal_lines

from orch import cli, hider, record
from orch import humanproof as hp
from orch import record_auth as ra
from orch.record import RecordWriter, read_run, record_dir

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
RUN = "r_8k2m01"
OTHER = "r_9z8y77"


def example(name="valid-step-started", **changes):
    value = json.loads((CONTRACTS / f"examples/activity/{name}.json").read_text())
    value.update(changes)
    return value


def at(n):
    return f"2026-11-16T09:00:{n:02d}Z"


@pytest.fixture
def store(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws, RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))


def runfile(ws, run=RUN):
    return record_dir(ws) / "runs" / f"{run}.jsonl"


def write3(writer, run=RUN):
    for n in (1, 2, 3):
        writer.append(example(run=run, id=f"toolu_{n}", at=at(n)))


def ids(ws, run=RUN):
    return [e["id"] for e in read_run(ws, run).unwrap()]


def planted(**kw):
    return dict(example(), id="toolu_planted", **kw)


def cli_lines(capsys, *argv):
    code = cli.main(["record", *argv, "--json"])
    return code, [json.loads(x) for x in capsys.readouterr().out.splitlines()]


# ------------------------------------------------------------------ the writer seals


def test_every_line_is_sealed_and_chained_and_the_head_follows(store):
    ws, writer = store
    write3(writer)
    raw = runfile(ws).read_bytes()
    parts = [ra.split(x) for x in raw.splitlines()]
    assert all(parts) and len({p[1] for p in parts}) == 1
    assert [p[2] for p in parts[1:]] == [p[3] for p in parts[:-1]]  # each line carries its predecessor's MAC
    head, ok = hp.record_head_read(ws, RUN)
    assert ok and head["seq"] == 3 and head["mac"] == parts[-1][3]


def test_planted_log_line_is_not_shown_and_does_not_override_the_real_one(store):
    ws, writer = store
    write3(writer)
    with runfile(ws).open("a") as f:
        f.write(json.dumps(planted(via="log", seq=4, run=RUN)) + "\n")
    read = read_run(ws, RUN)
    assert (read.changed, read.reason) == (1, "content") and "toolu_planted" not in ids(ws)
    real = writer.append(
        example(id="toolu_planted", via="log", at=at(9))
    )  # the id a plant used: not suppressed
    assert real is not None and real["seq"] == 4


@pytest.mark.parametrize("kind", ["run.state", "session.input", "key.use", "secret.change"])
def test_planted_core_and_broker_lines_are_not_shown_or_counted(store, kind):
    ws, writer = store
    write3(writer)
    ev = dict(planted(via="core", kind=kind, run=RUN, seq=4), data={"state": "done"})
    with runfile(ws).open("a") as f:
        f.write(json.dumps(ev) + "\n")
    assert read_run(ws, RUN).changed == 1
    assert record._verified  # one read path
    assert all(e["kind"] == "step" for e in read_run(ws, RUN).unwrap())


def test_reorder_delete_middle_truncate_and_restore(store):
    ws, writer = store
    write3(writer)
    lines = runfile(ws).read_bytes().splitlines(keepends=True)
    runfile(ws).write_bytes(lines[0] + lines[2] + lines[1])  # 2 and 3 swapped
    r = read_run(ws, RUN)
    assert (r.changed, r.removed, r.reason) == (1, 0, "content") and ids(ws) == ["toolu_1", "toolu_3"]
    runfile(ws).write_bytes(lines[0] + lines[2])  # middle deleted
    r = read_run(ws, RUN)
    assert (r.changed, r.removed, r.reason) == (0, 1, "removed")
    runfile(ws).write_bytes(lines[0])  # tail truncated: the head knows
    r = read_run(ws, RUN)
    assert (r.changed, r.removed, r.reason) == (0, 2, "removed")
    runfile(ws).write_bytes(b"".join(lines))  # an older complete copy is fine
    assert read_run(ws, RUN).reason is None


def test_run_file_deleted_is_tampered_removed_and_a_pruned_run_is_missing(store):
    ws, writer = store
    write3(writer)
    runfile(ws).unlink()
    r = read_run(ws, RUN)
    assert (r.status, r.reason) == ("tampered", "removed")
    head, _ = hp.record_head_read(ws, RUN)
    hp.record_head_write(ws, RUN, dict(head, pruned="2026-11-16T09:00:00Z"))
    assert read_run(ws, RUN).reason == "missing"


def test_replay_from_another_run_is_changed(store):
    ws, writer = store
    write3(writer)
    write3(writer, OTHER)
    foreign = runfile(ws, OTHER).read_bytes().splitlines(keepends=True)[0]
    with runfile(ws).open("ab") as f:
        f.write(foreign)
    assert read_run(ws, RUN).changed == 1


def test_a_junk_line_shifts_no_seq_and_the_tail_cursor_is_not_frozen(store, proj_cli):
    ws, writer = store
    write3(writer)
    with runfile(ws).open("ab") as f:
        f.write(b"junk\n")
    assert writer.append(example(id="toolu_4", at=at(4)))["seq"] == 4


def test_crash_between_line_and_head_readers_accept_and_next_commit_moves_head(store, monkeypatch):
    ws, writer = store
    write3(writer)
    real = hp.record_head_try_write
    monkeypatch.setattr(hp, "record_head_try_write", lambda *a: False)
    writer.append(example(id="toolu_4", at=at(4)))  # line stored, head write fails: reported, not raised
    monkeypatch.setattr(hp, "record_head_try_write", real)
    assert hp.record_head_read(ws, RUN)[0]["seq"] == 3
    assert read_run(ws, RUN).reason is None and len(ids(ws)) == 4
    writer.append(example(id="toolu_5", at=at(5)))
    assert hp.record_head_read(ws, RUN)[0]["seq"] == 5


def test_a_foreign_head_does_not_restart_the_chain_mid_run(store):
    """LOW-B: seq and link come from the last verified line of the current key; a head of another key (or a
    deleted head) never restarts a run at seq 1."""
    ws, writer = store
    write3(writer)
    path = hp.key_dir(ws, create=False) / "record-heads" / f"{RUN}.json"
    head = json.loads(path.read_text())
    path.write_text(json.dumps(dict(head, kid="deadbeef")))
    assert writer.append(example(id="toolu_4", at=at(4)))["seq"] == 4
    path.unlink()
    assert writer.append(example(id="toolu_5", at=at(5)))["seq"] == 5
    assert read_run(ws, RUN).reason is None


def test_a_truncated_file_continues_after_the_head_and_shows_the_gap(store):
    ws, writer = store
    write3(writer)
    lines = runfile(ws).read_bytes().splitlines(keepends=True)
    runfile(ws).write_bytes(lines[0])
    assert writer.append(example(id="toolu_4", at=at(4)))["seq"] == 4
    r = read_run(ws, RUN)
    assert (r.removed, ids(ws)) == (2, ["toolu_1", "toolu_4"])


def test_hook_lines_are_sealed_via_hook_and_unchecked(store):
    ws, writer = store
    writer.append(example(id="toolu_h", via="hook"))
    (line,) = read_run(ws, RUN).unwrap()
    assert line["via"] == "hook"


def test_only_one_place_seals(tmp_path):
    src = Path(record.__file__).parent
    for p in src.glob("*.py"):
        text = p.read_text()
        if p.name in ("record_auth.py", "record.py"):
            continue
        assert "record_auth.seal(" not in text and ".job_seal(" not in text, p.name
    text = Path(record.__file__).read_text()
    assert text.count("record_auth.seal(") == 1  # _commit


# ------------------------------------------------------------------ spool and drain


def _spool_dir(ws):
    return record_dir(ws) / "pending" / RUN


def test_spool_roundtrip_planted_renamed_and_replayed_entries(store, monkeypatch):
    ws, writer = store
    write3(writer)
    lock = record_dir(ws) / "runs" / f"{RUN}.lock"
    lock.touch()
    monkeypatch.setattr(record, "_LOCK_WAIT", 0.01)
    writer.append(example(id="toolu_s", at=at(8)))
    (entry,) = list(_spool_dir(ws).iterdir())
    original = entry.read_text()
    lock.unlink()
    # renamed: a copy under another name fails its MAC
    renamed = _spool_dir(ws) / ("0" * 19 + "1_" + "c" * 32 + ".json")
    renamed.write_text(original)
    planted_entry = _spool_dir(ws) / ("0" * 19 + "2_" + "d" * 32 + ".json")
    planted_entry.write_text(
        json.dumps(dict(event=example(id="toolu_forged", via="log"), payload=None, default_id=False))
    )
    assert writer.append(example(id="toolu_9", at=at(9)))["seq"] == 5
    assert not renamed.exists() and not planted_entry.exists() and not list(_spool_dir(ws).iterdir())
    assert "toolu_forged" not in ids(ws) and "toolu_s" in ids(ws)
    # replay: the genuine entry's name is in the head now
    entry.write_text(original)
    writer.append(example(id="toolu_10", at=at(10)))
    assert not entry.exists() and ids(ws).count("toolu_s") == 1
    assert hp.record_head_read(ws, RUN)[0]["rejected"] == 3


def test_an_entry_with_an_extra_key_is_refused(store):
    ws, writer = store
    write3(writer)
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    rec = hp.record_key(ws)
    name = "0" * 19 + "1_" + "e" * 32 + ".json"
    entry = dict(event=example(id="toolu_x"), payload=None, default_id=False)
    sm = ra.spool_mac(rec[2], rec[0], RUN, name, entry)
    (d / name).write_text(json.dumps(dict(entry, sm=sm, extra=1)))
    writer.append(example(id="toolu_y", at=at(5)))
    assert "toolu_x" not in ids(ws) and not (d / name).exists()


# ------------------------------------------------------------------ detail hash


def _query_detail(capsys, run, eid):
    return cli_lines(capsys, "query", "--run", run, "--detail", eid)


def test_swapped_detail_file_is_refused_through_the_cli(store, proj_cli, capsys):
    ws, writer = store
    stored = writer.append(example(id="toolu_d"), detail={"input": "a", "output": "b"})
    assert stored["detail_hash"]
    code, (got,) = _query_detail(capsys, RUN, "toolu_d")
    assert code == 0 and got["output"] == "b"
    target = record_dir(ws) / stored["detail"]
    other = json.loads(target.read_text())
    other["output"] = "swapped"
    target.write_text(json.dumps(other))
    code, (err,) = _query_detail(capsys, RUN, "toolu_d")
    assert code == 2 and err["code"] == "tampered" and "Details changed outside orch." in err["error"]


def test_a_sealed_line_with_a_detail_pointer_but_no_hash_is_refused(store, proj_cli, capsys):
    ws, writer = store
    stored = writer.append(example(id="toolu_d"), detail={"input": "a", "output": "b"})
    body = {k: v for k, v in stored.items() if k not in ("detail_hash", "replaced_hook")}
    runfile(ws).write_bytes(seal_lines(ws, RUN, [body]))
    code, (err,) = _query_detail(capsys, RUN, "toolu_d")
    assert code == 2 and err["code"] == "tampered"


def test_a_legacy_run_still_reads_its_detail(store, proj_cli, capsys):
    ws, writer = store
    stored = writer.append(example(id="toolu_d"), detail={"input": "a", "output": "b"})
    legacy = {k: v for k, v in stored.items() if k != "detail_hash"}
    runfile(ws).write_text(json.dumps(dict(legacy, seq=1)) + "\n")
    hp.key_dir(ws, create=False)  # the key folder is clean
    (hp.key_dir(ws, create=False) / "record-heads" / f"{RUN}.json").unlink()
    code, (got,) = _query_detail(capsys, RUN, "toolu_d")
    assert code == 0 and got["output"] == "b" and got["checked"] is False  # never shown as verified


def test_a_detail_of_a_before_protection_line_is_not_checked_and_a_plant_at_its_name_too(
    store, proj_cli, capsys
):
    ws, writer = store
    stored = writer.append(example(run=OTHER, id="toolu_d"), detail={"input": "a", "output": "b"})
    legacy = {k: v for k, v in stored.items() if k not in ("detail_hash", "replaced_hook")}
    runfile(ws, OTHER).write_text(json.dumps(dict(legacy, seq=1)) + "\n")
    (hp.key_dir(ws, create=False) / "record-heads" / f"{OTHER}.json").unlink()
    writer.append(example(run=OTHER, id="toolu_new", via="log", at=at(9)))  # the upgrade: the head records it
    assert hp.record_head_read(ws, OTHER)[0]["legacy_lines"] == 1
    code, (got,) = _query_detail(capsys, OTHER, "toolu_d")
    assert code == 0 and got["output"] == "b" and got["checked"] is False
    target = record_dir(ws) / stored["detail"]  # a planted file at the legacy line's name
    forged = json.loads(target.read_text())
    forged["output"] = "forged"
    target.write_text(json.dumps(forged))
    code, (got,) = _query_detail(capsys, OTHER, "toolu_d")
    assert code == 0 and got["output"] == "forged" and got["checked"] is False  # shown, but never as verified
    sealed = writer.append(
        example(run=OTHER, id="toolu_s", via="log", at=at(10)), detail={"input": "x", "output": "y"}
    )
    code, (got,) = _query_detail(capsys, OTHER, "toolu_s")
    assert code == 0 and got["checked"] is True and sealed["detail_hash"]


# ------------------------------------------------------------------ the legacy rule


@pytest.fixture
def proj_cli(store, monkeypatch):
    ws, _ = store
    monkeypatch.chdir(ws)
    (ws / ".orch").mkdir(exist_ok=True)
    return ws


def _legacy_run(ws, writer, run=OTHER):
    """A run as written before S2: plain lines, no auth, no head (the clean key folder exists)."""
    writer.append(example(run=run, id="toolu_a"))
    runfile(ws, run).write_text(
        "".join(json.dumps(dict(example(run=run, id=f"toolu_{n}", at=at(n)), seq=n)) + "\n" for n in (1, 2))
    )
    (hp.key_dir(ws, create=False) / "record-heads" / f"{run}.json").unlink()


def test_a_legacy_run_is_shown_marked_not_checked_and_never_counted(store, proj_cli, capsys):
    ws, writer = store
    _legacy_run(ws, writer)
    write3(writer)
    r = read_run(ws, OTHER)
    assert (r.status, r.legacy, r.reason, r.message) == ("ok", True, "unchecked", record.UNCHECKED_TEXT)
    code, lines = cli_lines(capsys, "tail", "--run", OTHER)
    events = [ln for ln in lines if ln["type"] == "event"]
    assert len(events) == 2 and all(ln["event"]["checked"] is False for ln in events)
    assert [ln["reason"] for ln in lines if ln["type"] == "unavailable"] == ["unchecked"]
    code, (counts,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert counts["complete"] is False and counts["runs"] == 1  # only the sealed run counts
    assert [u["reason"] for u in counts["unavailable"]] == ["unchecked"]


def test_stripping_auth_from_a_sealed_run_is_not_legacy(store, proj_cli, capsys):
    ws, writer = store
    write3(writer)
    stripped = [json.loads(ra.split(x)[0]) for x in runfile(ws).read_bytes().splitlines()]
    runfile(ws).write_text("".join(json.dumps(e) + "\n" for e in stripped))
    r = read_run(ws, RUN)
    assert (r.status, r.reason) == ("tampered", "removed") or (r.status, r.reason) == (
        "tampered",
        "unverified",
    )
    code, lines = cli_lines(capsys, "tail", "--run", RUN)
    assert [ln for ln in lines if ln.get("type") == "event"] == [] and lines[0]["code"] == "tampered"


def test_unsigned_lines_prepended_to_a_sealed_run_are_changed_not_legacy(store, proj_cli, capsys):
    ws, writer = store
    write3(writer)
    sealed = runfile(ws).read_bytes()
    runfile(ws).write_bytes(json.dumps(dict(planted(via="core"), seq=1, run=RUN)).encode() + b"\n" + sealed)
    r = read_run(ws, RUN)
    assert (r.legacy, r.reason, r.changed) == (False, "content", 1) and "toolu_planted" not in ids(ws)
    code, (counts,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert counts["complete"] is False and counts["runs"] == 1  # still counted, never excluded


def _upgraded(ws, writer):
    """A legacy run that then gets its first sealed lines (an upgrade of a real run)."""
    _legacy_run(ws, writer)
    writer.append(example(run=OTHER, id="toolu_new", via="log", at=at(9)))
    writer.append(example(run=OTHER, id="toolu_new2", via="log", at=at(10)))
    return runfile(ws, OTHER)


def test_upgrading_a_legacy_run_keeps_its_old_lines_shown_as_not_checked(store, proj_cli, capsys):
    ws, writer = store
    _upgraded(ws, writer)
    r = read_run(ws, OTHER)
    assert (r.status, r.legacy, r.changed, r.reason) == ("ok", False, 0, "unchecked")
    got = r.unwrap()
    assert [(e["id"], e.get("before_protection", False), e["seq"]) for e in got] == [
        ("toolu_1", True, 1),
        ("toolu_2", True, 2),
        ("toolu_new", False, 3),
        ("toolu_new2", False, 4),
    ]
    head, _ = hp.record_head_read(ws, OTHER)
    assert head["legacy_lines"] == 2 and len(head["legacy_hash"]) == 64 and head["seq"] == 4
    code, lines = cli_lines(capsys, "tail", "--run", OTHER)
    assert [(ln["event"]["id"], ln["event"]["checked"]) for ln in lines if ln["type"] == "event"] == [
        ("toolu_1", False),
        ("toolu_2", False),
        ("toolu_new", True),
        ("toolu_new2", True),
    ]
    code, (counts,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert counts["complete"] is False and counts["runs"] == 1
    assert [e["id"] for e in record._own(got)] == ["toolu_new", "toolu_new2"]  # retention believes only these


def test_a_legacy_prefix_that_is_prepended_edited_or_extended_is_changed(store):
    ws, writer = store
    path = _upgraded(ws, writer)
    good = path.read_bytes()
    first = good.splitlines(keepends=True)
    fake = (json.dumps(dict(planted(via="core", run=OTHER), seq=1, run_=None)) + "\n").encode()
    fake = json.dumps(dict(planted(via="core"), seq=1, run=OTHER)).encode() + b"\n"
    cases = {
        "prepended": fake + good,
        "edited": first[0].replace(b"toolu_1", b"toolu_X") + b"".join(first[1:]),
        "extended": first[0] + first[1] + fake + b"".join(first[2:]),
        "removed": b"".join(first[1:]),
    }
    for name, raw in cases.items():
        path.write_bytes(raw)
        r = read_run(ws, OTHER)
        assert r.changed >= 1 and r.reason == "content", name
        shown = [e["id"] for e in r.unwrap() if e.get("before_protection")]
        # the recorded prefix still matches only when nothing in front of the first sealed line changed; an
        # unsigned line added behind it is changed on its own
        assert shown == (["toolu_1", "toolu_2"] if name == "extended" else []), name
        assert "toolu_planted" not in [e["id"] for e in r.unwrap()], name
        assert [e["id"] for e in r.unwrap()][-2:] == ["toolu_new", "toolu_new2"], name
    path.write_bytes(good)
    assert read_run(ws, OTHER).changed == 0


def test_the_legacy_prefix_is_recorded_once(store):
    ws, writer = store
    path = _upgraded(ws, writer)
    head, _ = hp.record_head_read(ws, OTHER)
    writer.append(example(run=OTHER, id="toolu_3", at=at(11)))
    again, _ = hp.record_head_read(ws, OTHER)
    assert (again["legacy_lines"], again["legacy_hash"]) == (head["legacy_lines"], head["legacy_hash"])
    assert path.read_bytes().count(b"\n") == 5


def test_a_rejected_spool_entry_keeps_a_count_only_where_a_head_exists(store, monkeypatch):
    ws, writer = store
    # a legacy run (no head): the entry is deleted and alerted, no head is made, the run stays legacy
    _legacy_run(ws, writer)
    d = record_dir(ws) / "pending" / OTHER
    d.mkdir(parents=True)
    bad = d / ("0" * 19 + "1_" + "a" * 32 + ".json")
    bad.write_text("{}")
    writer.drain(OTHER, check_lock=lambda: None)
    assert not bad.exists() and hp.record_head_read(ws, OTHER) == (None, True)
    assert read_run(ws, OTHER).legacy is True
    # a sealed run: counted in its head
    write3(writer)
    d2 = _spool_dir(ws)
    d2.mkdir(parents=True)
    (d2 / ("0" * 19 + "1_" + "b" * 32 + ".json")).write_text("{}")
    writer.drain(RUN, check_lock=lambda: None)
    assert hp.record_head_read(ws, RUN)[0]["rejected"] == 1
    # a sealed run whose head is missing (a crash before the first head write): the head is made, with it
    (hp.key_dir(ws, create=False) / "record-heads" / f"{RUN}.json").unlink()
    (d2 / ("0" * 19 + "2_" + "c" * 32 + ".json")).write_text("{}")
    writer.drain(RUN, check_lock=lambda: None)
    head = hp.record_head_read(ws, RUN)[0]
    assert head["rejected"] == 1 and head["seq"] == 3


# ------------------------------------------------------------------ the marker for helpers without deny rules


def _state(harness, via="core", **kw):
    return dict(example("valid-run-state-say"), via=via, harness=harness, **kw)


def test_protected_comes_only_from_a_verified_core_line():
    from orch import cli_record

    hook = dict(example(), via="hook", harness="claude", checked=False)
    forged = cli_record.run_model("r_x", [hook])
    assert forged["protected"] is False  # unknown tool: the marker is shown
    core = dict(_state("codex"), checked=True)
    assert cli_record.run_model("r_x", [hook, core])["protected"] is False  # codex has no deny rules
    claude = dict(_state("claude"), checked=True)
    assert cli_record.run_model("r_x", [claude])["protected"] is True
    assert cli_record.run_model("r_x", [claude], problem=True)["complete"] is False
    assert record.UNPROTECTED_TEXT == "Records from this helper can't be fully checked."


# ------------------------------------------------------------------ perf


@pytest.mark.slow
def test_a_ten_thousand_line_run_verifies_fast_and_warm_from_the_cache(store):
    ws, _ = store
    hp.record_key(ws)
    runfile(ws).parent.mkdir(parents=True)
    raw = seal_lines(ws, RUN, [example(id=f"i{n}", at=at(1)) for n in range(10000)])
    runfile(ws).write_bytes(raw)
    start = time.monotonic()
    assert len(record._verified(ws, RUN, raw).events) == 10000
    assert time.monotonic() - start < 2.0
    more = raw + seal_lines(
        ws, RUN, [example(id="i-last", at=at(2))], start=10001, link=ra.split(raw.splitlines()[-1])[3]
    )
    warm = time.monotonic()
    view = record._verified(ws, RUN, more)  # resumed from the cached prefix: only the new line is verified
    assert len(view.events) == 10001 and time.monotonic() - warm < 0.5

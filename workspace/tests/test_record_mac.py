"""Record MAC, slice S2: the writer seals, the readers verify (activity.md, Authenticated record). Adversarial
tests through the record API and the `orch record` CLI. Raw run files are made with conftest.seal_lines."""

import json
import os
import re
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
    hp.record_key(ws)  # a clean key folder (a claim makes it in a run)
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


def _legacy_with_detail(ws, run, eid="toolu_d"):
    """A legacy run (a line made before protection) whose line points at a detail file."""
    ev = example(run=run, id=eid)
    name = record.detail_name(run, ev["kind"], eid, ev["ticket"])
    d = record_dir(ws) / "detail" / run
    d.mkdir(parents=True)
    (d / f"{name}.json").write_text(
        json.dumps(
            dict(
                v=1,
                id=eid,
                run=run,
                kind=ev["kind"],
                ticket=ev["ticket"],
                input="a",
                output="b",
                truncated=False,
                hidden=0,
            )
        )
    )
    runfile(ws, run).parent.mkdir(parents=True, exist_ok=True)
    runfile(ws, run).write_text(json.dumps(dict(ev, seq=1, detail=f"detail/{run}/{name}.json")) + "\n")
    _relist(ws)
    return d / f"{name}.json"


def test_a_legacy_run_still_reads_its_detail(store, proj_cli, capsys):
    ws, writer = store
    _legacy_with_detail(ws, RUN)
    code, (got,) = _query_detail(capsys, RUN, "toolu_d")
    assert code == 0 and got["output"] == "b" and got["checked"] is False  # never shown as verified


def test_a_detail_of_a_before_protection_line_is_not_checked_and_a_plant_at_its_name_too(
    store, proj_cli, capsys
):
    ws, writer = store
    target = _legacy_with_detail(ws, OTHER)
    writer.append(example(run=OTHER, id="toolu_new", via="log", at=at(9)))  # the upgrade: the head records it
    assert hp.record_head_read(ws, OTHER)[0]["legacy_lines"] == 1
    code, (got,) = _query_detail(capsys, OTHER, "toolu_d")
    assert code == 0 and got["output"] == "b" and got["checked"] is False
    forged = json.loads(target.read_text())  # a planted file at the legacy line's name
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


def _reset(ws):
    """A real protection reset (the key rotates, the reset time is recorded)."""
    hp.reset_protection(ws, "test reset")


def _relist(ws):
    """The cutover list, made again after a test wrote a legacy run file by hand: in life it is made when
    the key is made, so the runs of that moment are the legacy ones."""
    (hp.key_dir(ws, create=False) / "record-cutover.json").unlink(missing_ok=True)
    hp.record_cutover_ensure(ws)  # a test stand-in for "these runs existed when the key was made"


def _legacy_run(ws, writer, run=OTHER):
    """A run as written before S2: plain lines, no auth, no head. It exists before the first sealed write
    (that write lists it in the cutover list, the only runs whose unsigned lines may be adopted)."""
    runfile(ws, run).parent.mkdir(parents=True, exist_ok=True)
    runfile(ws, run).write_text(
        "".join(json.dumps(dict(example(run=run, id=f"toolu_{n}", at=at(n)), seq=n)) + "\n" for n in (1, 2))
    )
    _relist(ws)


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


def test_protected_comes_only_from_a_checked_collector_line(store, proj_cli):
    from orch import cli_record

    ws, writer = store
    for run, harness in ((RUN, "claude"), (OTHER, "codex")):
        writer.append(example(run=run, id="toolu_h", via="hook", harness="claude"))  # the agent's word
        writer.append(example(run=run, id="toolu_l", via="log", harness=harness, at=at(2)))
    models = {}
    for run in (RUN, OTHER):
        events, _ = cli_record._events(ws, [run], None)
        models[run] = cli_record.run_model(run, events[run], root=ws)
    assert models[RUN]["protected"] is True and models[OTHER]["protected"] is False  # codex: no deny rules
    # a forged hook line claiming claude in a codex run does not remove the marker; no collector line: unknown
    only_hook = [dict(example(via="hook", harness="claude"), checked=False)]
    assert cli_record.run_model("r_x", only_hook)["protected"] is False
    legacy = dict(example(via="log", harness="claude"), before_protection=True, checked=False)
    assert cli_record.run_model("r_x", [legacy])["protected"] is False
    assert cli_record.run_model("r_x", only_hook, problem=True)["complete"] is False
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


# ------------------------------------------------------------------ one definition of "checked"


def test_one_helper_decides_every_trust_marker():
    """Source walk: `before_protection` is tagged and read only in record.py; every `checked` marker
    computed in the CLI is record.is_checked; the CLI never compares `via` with "hook" to decide trust."""
    src = Path(record.__file__).parent
    for p in sorted(src.glob("*.py")):
        text = p.read_text()
        if p.name != "record.py":
            assert "before_protection" not in text, p.name
        if p.name in ("cli_record.py", "secretrun.py", "run_record.py"):
            assert 'via") != "hook"' not in text and 'via") == "hook"' not in text, p.name
            for n, line in enumerate(text.splitlines(), 1):
                if '"checked":' in line and "detail.value" not in line:
                    assert "record.is_checked(" in line, (p.name, n)
    assert Path(record.__file__).read_text().count("def is_checked(") == 1


def test_checked_markers_of_events_details_and_run_model(store, proj_cli, capsys):
    from orch import cli_record

    ws, writer = store
    writer.append(example(id="toolu_h", via="hook"), detail={"input": "h", "output": "h"})
    writer.append(example(id="toolu_l", via="log", at=at(2)), detail={"input": "l", "output": "l"})
    code, (hook,) = _query_detail(capsys, RUN, "toolu_h")
    assert code == 0 and hook["checked"] is False  # a hook line's detail is the agent's word
    code, (log,) = _query_detail(capsys, RUN, "toolu_l")
    assert code == 0 and log["checked"] is True  # a verified, non-hook sealed line
    code, lines = cli_lines(capsys, "tail", "--run", RUN)
    assert {ln["event"]["id"]: ln["event"]["checked"] for ln in lines} == {"toolu_h": False, "toolu_l": True}
    # run_model: only a checked collector line tells the tool; a hook line or an old line never does
    line = dict(example(via="log", harness="claude"), checked=True)
    assert cli_record.run_model("r_x", [line])["protected"] is True
    assert cli_record.run_model("r_x", [dict(line, via="hook")])["protected"] is False
    assert cli_record.run_model("r_x", [dict(line, before_protection=True)])["protected"] is False


def test_a_deleted_run_file_or_runs_folder_cannot_hide_the_run(store, proj_cli, capsys):
    ws, writer = store
    write3(writer)
    write3(writer, OTHER)
    runfile(ws).unlink()
    assert record.list_runs(ws).value == [RUN, OTHER]
    code, lines = cli_lines(capsys, "tail")
    marks = [(ln["run"], ln["status"], ln["reason"]) for ln in lines if ln["type"] == "unavailable"]
    assert marks == [(RUN, "tampered", "removed")] and len([x for x in lines if x["type"] == "event"]) == 3
    code, (counts,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert counts["complete"] is False
    for f in (record_dir(ws) / "runs").iterdir():  # the whole folder
        f.unlink()
    (record_dir(ws) / "runs").rmdir()
    assert record.list_runs(ws).value == [RUN, OTHER]
    code, lines = cli_lines(capsys, "tail")
    assert {ln["run"] for ln in lines if ln["type"] == "unavailable"} == {RUN, OTHER}
    code, (counts,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert counts["complete"] is False and counts["runs"] == 0


# ------------------------------------------------------------------ legacy adoption: cutover list (M1)


def test_unsigned_lines_in_a_run_made_after_protection_are_changed_not_adopted(store):
    """(a) a predictable run name, (c) a run file the agent made before the writer's first commit."""
    ws, writer = store
    write3(writer)  # protection has begun: the cutover list is written (no runs then)
    for run in ("r_outside_20261116", OTHER):
        runfile(ws, run).write_text(json.dumps(dict(planted(via="core", run=run), seq=1)) + "\n")
        writer.append(example(run=run, id="toolu_real", via="log", at=at(9)))
        r = read_run(ws, run)
        assert (r.legacy, r.changed, r.reason) == (False, 1, "content"), run
        assert [e["id"] for e in r.unwrap()] == ["toolu_real"], run
        assert "legacy_lines" not in hp.record_head_read(ws, run)[0], run
        assert not any(e.get("before_protection") for e in r.unwrap())


def test_a_pruned_run_is_never_legacy_again(store):
    """(b) the tombstone counts as a head: a run file planted at a pruned run's name is `changed`."""
    ws, writer = store
    write3(writer)
    record._tombstone(ws, RUN, "2026-11-16T10:00:00Z")
    runfile(ws).write_text(json.dumps(dict(planted(via="core", run=RUN), seq=1)) + "\n")
    r = read_run(ws, RUN)
    assert (r.status, r.reason) == ("tampered", "unverified") and not r.legacy
    writer.append(example(id="toolu_after", via="log", at=at(9)))
    r = read_run(ws, RUN)
    assert (r.legacy, r.changed) == (False, 1) and not any(e.get("before_protection") for e in r.unwrap())


def test_a_forged_cutover_list_adopts_nothing(store):
    ws, writer = store
    _legacy_run(ws, writer)
    write3(writer)  # lists OTHER
    path = hp.key_dir(ws, create=False) / "record-cutover.json"
    body = json.loads(path.read_text())
    path.write_text(json.dumps(dict(body, runs=[*body["runs"], RUN])))  # a run added by hand: the MAC fails
    assert hp.record_cutover_read(ws) is False
    assert read_run(ws, OTHER).status == "tampered"  # no run is legacy any more: fail closed


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires FIFO")
@pytest.mark.parametrize("kind", ["symlink", "folder", "fifo"])
def test_a_planted_link_folder_or_fifo_at_a_spool_name_is_rejected_and_never_blocks_retention(store, kind):
    ws, writer = store
    write3(writer)
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    name = d / ("0" * 19 + "1_" + "f" * 32 + ".json")
    outside = ws / "outside.txt"
    outside.write_text("keep")
    if kind == "symlink":
        name.symlink_to(outside)
    elif kind == "folder":
        name.mkdir()
    else:
        os.mkfifo(name)
    writer.append(example(id="toolu_4", at=at(4)))
    assert not name.exists() and not name.is_symlink() and outside.read_text() == "keep"
    assert record._pending_count(ws, RUN) == 0


def test_rejected_spool_entries_are_counted_as_changed_in_every_view(store, proj_cli, capsys):
    ws, writer = store
    write3(writer)
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    (d / ("0" * 19 + "1_" + "a" * 32 + ".json")).write_text("{}")
    writer.append(example(id="toolu_4", at=at(4)))
    r = read_run(ws, RUN)
    assert (r.changed, r.reason) == (1, "content") and len(r.unwrap()) == 4
    code, lines = cli_lines(capsys, "tail", "--run", RUN)
    (mark,) = [ln for ln in lines if ln["type"] == "unavailable"]
    assert (mark["reason"], mark["changed"]) == ("content", 1)
    code, (counts,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert counts["complete"] is False
    # a run with no file and no head keeps a count in a small guarded counter
    d2 = record_dir(ws) / "pending" / "r_nothere01"
    d2.mkdir(parents=True)
    (d2 / ("0" * 19 + "1_" + "b" * 32 + ".json")).write_text("{}")
    writer.drain("r_nothere01", check_lock=lambda: None)
    assert hp.record_rejects_read(ws, "r_nothere01") == 1 and "r_nothere01" in record.list_runs(ws).value
    gone = read_run(ws, "r_nothere01")
    assert (gone.status, gone.changed, gone.reason) == ("ok", 1, "content")


def test_content_and_unchecked_are_both_told(store, proj_cli, capsys):
    ws, writer = store
    _legacy_run(ws, writer)
    write3(writer)
    writer.append(example(run=OTHER, id="toolu_n", via="log", at=at(9)))  # the upgrade of the legacy run
    with runfile(ws, OTHER).open("a") as f:
        f.write(json.dumps(dict(planted(via="core", run=OTHER), seq=5)) + "\n")  # a plant behind
    code, lines = cli_lines(capsys, "tail", "--run", OTHER)
    assert sorted(ln["reason"] for ln in lines if ln["type"] == "unavailable") == ["content", "unchecked"]


def test_a_deep_or_linking_planted_folder_in_pending_is_reported_never_walked_or_deleted(store):
    ws, writer = store
    write3(writer)
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    outside = ws / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    deep = d / ("0" * 19 + "1_" + "a" * 32 + ".json")
    deep.mkdir()
    cur = deep
    for _ in range(300):  # deep enough to break any recursion over it, within the path length limit
        cur = cur / "d"
        cur.mkdir()
    linking = d / ("0" * 19 + "2_" + "b" * 32 + ".json")
    linking.mkdir()
    (linking / "to_dir").symlink_to(outside, target_is_directory=True)
    (linking / "to_file").symlink_to(outside / "keep.txt")
    writer.append(example(id="toolu_4", at=at(4)))  # no crash
    assert (outside / "keep.txt").read_text() == "keep"  # nothing outside was touched
    assert list(d.iterdir()) == []  # renamed aside, not in the spool
    assert record._pending_count(ws, RUN) == 0  # so retention is not blocked
    assert read_run(ws, RUN).changed == 2  # told: counted as changed outside orch
    q = record_dir(ws) / "quarantine" / RUN  # only orch writes there; nothing reads it
    assert len(list(q.iterdir())) == 2 and all(p.name.startswith("q_") for p in q.iterdir())


def test_nothing_recursive_ever_touches_pending():
    import ast

    text = Path(record.__file__).read_text()
    found = {
        n.name: ast.get_source_segment(text, n)
        for n in ast.walk(ast.parse(text))
        if isinstance(n, ast.FunctionDef)
    }
    for name in (
        "_reject_entry",
        "_reject_bad_spool",
        "_drain",
        "_spool",
        "_pending_count",
        "_rename_aside",
        "_file_size",
    ):
        assert "_rmtree(" not in found[name] and not re.search(r"(?<![A-Za-z_])_size\(", found[name]), name


def test_a_reject_before_the_first_sealed_line_survives_sealing(store, proj_cli, capsys):
    ws, writer = store
    d = record_dir(ws) / "pending" / RUN
    d.mkdir(parents=True)
    (d / ("0" * 19 + "1_" + "c" * 32 + ".json")).write_text("{}")
    writer.drain(RUN, check_lock=lambda: None)  # no file, no head: the guarded counter keeps it
    assert hp.record_rejects_read(ws, RUN) == 1
    write3(writer)  # the first head is made now
    assert hp.record_head_read(ws, RUN)[0]["rejected"] == 0
    r = read_run(ws, RUN)
    assert (r.changed, r.reason) == (1, "content")  # counted once, from the guarded counter
    (d / ("0" * 19 + "2_" + "d" * 32 + ".json")).write_text("{}")
    writer.append(example(id="toolu_4", at=at(4)))  # a later reject is counted in the head
    assert read_run(ws, RUN).changed == 2
    code, lines = cli_lines(capsys, "tail", "--run", RUN)
    assert [ln["changed"] for ln in lines if ln["type"] == "unavailable"] == [2]
    code, (counts,) = cli_lines(capsys, "counts", "--from", "2026-11-16", "--to", "2026-11-16")
    assert counts["complete"] is False


def test_a_hook_line_that_says_ok_is_never_counted_as_ok(store):
    from orch import cli_record

    ws, writer = store
    done = dict(ok=True, error=None, ms=1)
    writer.append(example(id="toolu_h", via="hook", outcome=done))  # sealed, but the agent's word
    writer.append(example(id="toolu_l", via="log", outcome=done, at=at(2)))
    events, _ = cli_record._events(ws, [RUN], None)
    model = cli_record.run_model(RUN, events[RUN], root=ws)
    assert sorted(u["result"] for u in model["uses"]) == ["ok", "unknown"]  # the hook line's "ok" is not one
    only_hook = [e for e in events[RUN] if e["via"] == "hook"]
    assert [u["result"] for u in cli_record.run_model(RUN, only_hook)["uses"]] == ["unknown"]


def test_add_ons_that_read_record_lines_use_the_computed_checked_marker():
    """Source walk over the add-ons: a module that decides anything from a record line's `via` must also read
    `checked` (computed by orch, record.is_checked); none re-derives `before_protection`."""
    import re

    root = Path(__file__).resolve().parents[2] / "workspace-addons"
    seen = 0
    for p in sorted(root.glob("*/src/**/*.py")):
        if ".venv" in p.parts:
            continue
        text = p.read_text()
        assert "before_protection" not in text, p
        if re.search(r'e(?:vent)?\.get\("via"\)|\["via"\]', text) and "record" in p.name:
            seen += 1
            assert 'get("checked")' in text, p
    assert seen >= 1  # the Focus reader


@pytest.mark.parametrize("kind", ["file", "folder", "symlink"])
def test_a_planted_dot_or_quarantine_name_in_pending_alerts_like_any_other_odd_name(store, kind):
    ws, writer = store
    write3(writer)
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    odd = d / ".quarantine_x"
    if kind == "file":
        odd.write_text("x")
    elif kind == "folder":
        odd.mkdir()
    else:
        odd.symlink_to(ws / "nothing")
    writer.append(example(id="toolu_4", at=at(4)))
    alerts = "".join(p.read_text() for p in (record_dir(ws) / "alerts").glob("*.jsonl"))
    assert '"reason":"swapped"' in alerts  # not skipped: an odd name in the spool folder is told
    assert record._pending_count(ws, RUN) == 0


def _mtime(path, iso):
    t = time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    os.utime(path, (t, t))


def test_a_legacy_run_is_pruned_by_the_recorded_time_never_by_its_mtime(store):
    ws, writer = store
    _legacy_run(ws, writer)  # OTHER: legacy, listed in the cutover list made by the first write
    write3(writer)
    at_cutover = hp.record_cutover_at(ws)
    assert at_cutover
    folds = []
    fold = lambda r, es: folds.append((r, len(es)))  # noqa: E731
    path = runfile(ws, OTHER)
    _mtime(path, "2020-01-01T00:00:00Z")  # an agent makes the file look very old
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
    res = record.apply_retention(ws, soon, 90, 2048, fold)
    assert OTHER not in res["delete_run"] and path.exists()  # protection began yesterday: not old enough
    _mtime(path, "2027-06-01T00:00:00Z")  # nor does a new mtime keep it
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 100 * 86400))
    res = record.apply_retention(ws, later, 90, 2048, fold)
    assert OTHER in res["delete_run"] and not path.exists() and (OTHER, 0) in folds


def test_a_tampered_run_is_never_pruned_whatever_its_mtime(store):
    ws, writer = store
    write3(writer)
    writer.append(
        example(id="r_end", kind="run.state", via="core", at=at(5), used=None, data={"state": "done"})
    )
    path = runfile(ws)
    stripped = [json.loads(ra.split(x)[0]) for x in path.read_bytes().splitlines()]
    path.write_text("".join(json.dumps(e) + "\n" for e in stripped))  # the agent strips auth: unverified
    _mtime(path, "2020-01-01T00:00:00Z")
    res = record.apply_retention(ws, "2035-01-01T00:00:00Z", 90, 2048, lambda r, es: None)
    assert res["delete_run"] == [] and path.exists() and res["status"] == "tampered"
    assert hp.record_head_read(ws, RUN)[0].get("pruned") is None  # no tombstone either


def test_the_size_cap_ignores_runs_orch_cannot_check():
    runs = [
        dict(run="r_genuine1", ended="2026-12-01T00:00:00Z", detail_mb=0.0, file_mb=0.5, counted=True),
        dict(run="r_planted1", ended="2026-12-02T00:00:00Z", detail_mb=0.0, file_mb=900.0, counted=False),
    ]
    plan = record.plan_retention(runs, "2026-12-10T00:00:00Z", 90, 1)
    assert plan["delete_run"] == []  # the planted size did not push the genuine run out


def test_a_pruned_run_gets_its_tombstone_before_the_file_goes(store, monkeypatch):
    ws, writer = store
    write3(writer)
    writer.append(
        example(id="r_end", kind="run.state", via="core", at=at(5), used=None, data={"state": "done"})
    )
    order = []
    real = record._tombstone
    monkeypatch.setattr(record, "_tombstone", lambda *a: (order.append(runfile(ws).exists()), real(*a)))
    record.apply_retention(ws, "2030-01-01T00:00:00Z", 90, 2048, lambda r, es: None)
    assert order == [True]  # the run file still existed when the tombstone was written


def test_a_removed_legacy_prefix_is_counted_as_removed(store):
    ws, writer = store
    _legacy_run(ws, writer)
    writer.append(example(run=OTHER, id="toolu_n", via="log", at=at(9)))
    lines = runfile(ws, OTHER).read_bytes().splitlines(keepends=True)
    runfile(ws, OTHER).write_bytes(b"".join(lines[2:]))  # both old lines deleted
    r = read_run(ws, OTHER)
    assert (r.removed, r.reason) == (2, "removed") and [e["id"] for e in r.unwrap()] == ["toolu_n"]


def test_the_outside_day_cap_counts_verified_lines_and_fails_closed_only_on_unknown_state(store, monkeypatch):
    from orch import secretrun
    from orch.errors import Refused

    ws, writer = store
    monkeypatch.setattr(secretrun, "_run_ids", lambda: None)
    monkeypatch.setattr(secretrun, "require_run", lambda *a: None)
    run = "r_outside_20261116"
    monkeypatch.setattr(secretrun, "_record_event", lambda root, ev: example(run=run))
    wrote = []
    monkeypatch.setattr(
        secretrun, "record_writer", lambda root: type("W", (), {"append": lambda s, e: wrote.append(e)})()
    )
    # one planted junk line and nothing else: it must not stop key uses for the day
    runfile(ws, run).parent.mkdir(parents=True, exist_ok=True)
    runfile(ws, run).write_text("junk\n")
    secretrun._write_record(ws, {})
    assert len(wrote) == 1
    # an unknown state of the guarded home: refused
    monkeypatch.setattr(hp, "record_head_state", lambda *a: "unknown")
    with pytest.raises(Refused, match="too many key uses"):
        secretrun._write_record(ws, {})


@pytest.mark.parametrize("how", ["file", "symlink", "wrong_mode"])
def test_a_quarantine_that_is_not_a_clean_folder_never_leaves_the_entry_under_a_valid_name(
    store, how, tmp_path
):
    ws, writer = store
    write3(writer)
    q = record_dir(ws) / "quarantine"
    q.mkdir()
    target = q / RUN
    if how == "file":
        target.write_text("not a folder")
    elif how == "symlink":
        (tmp_path / "out").mkdir()
        target.symlink_to(tmp_path / "out")
    else:
        target.mkdir(mode=0o777)
        target.chmod(0o777)
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    planted = d / ("0" * 19 + "1_" + "a" * 32 + ".json")
    planted.mkdir()  # a folder: it cannot be unlinked, so the rename is tried
    (planted / "x").write_text("x")
    writer.append(example(id="toolu_4", at=at(4)))
    assert not planted.exists()  # gone from its valid name every time
    assert record._pending_count(ws, RUN) == 0
    left = [p.name for p in d.iterdir()]
    assert all(not n.startswith("0") for n in left)
    if (
        how != "wrong_mode"
    ):  # no clean quarantine: the entry stays inside the spool under a name never drained
        assert any(n.startswith(".rejected_") for n in left)
    assert not (tmp_path / "out").exists() or list((tmp_path / "out").iterdir()) == []  # not through the link
    writer.append(example(id="toolu_5", at=at(5)))  # a later drain never executes it
    assert "toolu_x" not in ids(ws)


# ------------------------------------------------------------------ whole-S2 review batch


def test_med1_a_planted_spool_entry_does_not_block_retention_of_a_finished_run(store):
    ws, writer = store
    write3(writer)
    writer.append(
        example(id="r_end", kind="run.state", via="core", at=at(5), used=None, data={"state": "done"})
    )
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    (d / ("0" * 19 + "1_" + "a" * 32 + ".json")).write_text("{}")  # no further append, no drain
    res = record.apply_retention(ws, "2035-01-01T00:00:00Z", 90, 2048, lambda r, es: None)
    assert res["delete_run"] == [RUN] and res["status"] == "ok"
    assert list(d.iterdir()) == []  # refused and moved aside


def test_med2_a_run_planted_after_the_key_exists_is_never_legacy(store):
    ws, writer = store
    planted_run = "r_planted01"
    runfile(ws, planted_run).parent.mkdir(parents=True, exist_ok=True)
    runfile(ws, planted_run).write_text(
        json.dumps(dict(example(run=planted_run, via="log", kind="run.state"), seq=1)) + "\n"
    )
    write3(writer)  # any write: the list was made when the key was made, before the plant
    assert planted_run not in (hp.record_cutover_read(ws) or set())
    r = read_run(ws, planted_run)
    assert (r.status, r.legacy) == ("tampered", False)
    _legacy_run(ws, writer)  # a run that existed when the list was made IS legacy
    assert read_run(ws, OTHER).legacy is True


def test_med4_a_reset_run_is_pruned_from_the_recorded_reset_and_never_counted(store):
    ws, writer = store
    write3(writer)
    _reset(ws)
    r = read_run(ws, RUN)
    assert (r.status, r.reason) == ("tampered", "old_key")
    at_reset = hp.record_reset_at(ws)
    assert at_reset
    assert record.apply_retention(ws, at_reset, 90, 2048, lambda r, es: None)["delete_run"] == []
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 100 * 86400))
    assert record.apply_retention(ws, later, 90, 2048, lambda r, es: None)["delete_run"] == [RUN]


def test_low1_made_up_key_ids_are_content_not_old_key():
    from orch import record_auth as rauth

    state = rauth.State()
    state.pending = 2
    out = rauth.finish(state, "aaaaaaaa", None, old_kid=None)
    assert (out.changed, out.reason) == (2, "content")


def test_low2_the_hook_with_no_record_key_is_a_lost_trace_not_a_crash(proj_cli, monkeypatch):
    from orch import record_hook, runs, tickets

    t = tickets.create(proj_cli, "T", "human:t")
    rec = runs.claim(proj_cli, t["id"], "agent:x", "claude", pid=os.getpid())
    monkeypatch.setenv("ORCH_RUN", rec["run"])
    monkeypatch.setenv("ORCH_TICKET", t["id"])

    class Off:
        def append(self, *a, **k):
            raise record.RecordOff("off")

    monkeypatch.setattr(record_hook, "record_writer", lambda root: Off())
    line = json.dumps(
        {
            "kind": "step",
            "id": "toolu_1",
            "text": "Read a",
            "outcome": None,
            "used": {"kind": "tool", "name": "Read", "action": None, "source": "builtin", "version": None},
        }
    )
    with pytest.raises(record_hook.NotRecorded) as caught:
        record_hook.hook(proj_cli, line)
    assert caught.value.reason == "hider_off"


def test_low4_a_deep_quarantine_does_not_make_the_sizes_tampered(store):
    ws, writer = store
    q = record_dir(ws) / "quarantine" / RUN / "q_x"
    q.mkdir(parents=True)
    cur = q
    for _ in range(40):
        cur = cur / "d"
        cur.mkdir()
    sizes = record.record_sizes(ws)
    assert sizes.status == "ok"


def test_low6_a_forged_claim_does_not_remove_the_marker(proj_cli):
    from orch import cli_record, runs, tickets

    t = tickets.create(proj_cli, "T", "human:t")
    rec = runs.claim(proj_cli, t["id"], "agent:x", "claude", pid=os.getpid())  # a claim file says claude
    line = dict(example(run=rec["run"], ticket=t["id"], via="hook", harness="claude"), checked=False)
    assert cli_record.run_model(rec["run"], [line], root=proj_cli)["protected"] is False  # the marker stays


def test_low8_a_new_segment_keeps_what_is_safe_from_the_old_head(store):
    ws, writer = store
    write3(writer)
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    (d / ("0" * 19 + "1_" + "a" * 32 + ".json")).write_text("{}")
    writer.append(example(id="toolu_4", at=at(4)))  # one rejected, in the head
    _reset(ws)
    writer.append(example(id="toolu_5", at=at(5)))
    head, _ = hp.record_head_read(ws, RUN)
    assert (
        head["seq"] == 1 and head["rejected"] == 1 and "legacy_lines" not in head and not head.get("pruned")
    )


def test_low9_a_flood_of_planted_entries_never_starves_a_genuine_one(store, monkeypatch):
    ws, writer = store
    write3(writer)
    lock = record_dir(ws) / "runs" / f"{RUN}.lock"
    lock.touch()
    monkeypatch.setattr(record, "_LOCK_WAIT", 0.01)
    writer.append(example(id="toolu_g", at=at(8)))  # spooled: the lock is busy
    lock.unlink()
    d = _spool_dir(ws)
    for n in range(60):  # names that sort BEFORE the genuine one
        (d / (f"{n:020d}_" + "b" * 32 + ".json")).write_text("{}")
    writer.append(example(id="toolu_4", at=at(4)))  # one write: the genuine entry is committed
    assert "toolu_g" in ids(ws)
    assert len(list(d.iterdir())) == 60 - record._REJECT_BATCH  # the rest wait for the next call


def test_low7_non_ascii_digits_are_not_a_spool_name():
    assert not record._SPOOL_NAME.fullmatch("٣" * 20 + "_" + "a" * 32 + ".json")
    assert not ra.drain_ok(b"k" * 32, "ws", RUN, "٣" * 20 + "_" + "a" * 32 + ".json", {}, "x", [], "0" * 20)


def test_low12_a_line_that_fails_its_checks_leaves_no_detail_file(store, monkeypatch):
    ws, writer = store
    real = record._hidden_line

    def refuse_the_dry_run(hider_, obj):
        if obj.get("detail_hash") == "0" * 32:
            raise record.RecordInvalid()
        return real(hider_, obj)

    monkeypatch.setattr(record, "_hidden_line", refuse_the_dry_run)
    with pytest.raises(record.RecordRefused):
        writer.append(example(id="toolu_big"), detail={"input": "i", "output": "o"})
    detail = record_dir(ws) / "detail" / RUN
    assert not detail.exists() or list(detail.iterdir()) == []
    assert read_run(ws, RUN).reason == "missing"  # no line either


@pytest.mark.slow
def test_perf_a_warm_read_and_append_are_cheap(store):
    ws, writer = store
    for n in range(4):
        other = ws.parent / f"other{n}"
        other.mkdir()
        hp.record_key(other)
    read_run(ws, RUN)
    t = time.perf_counter()
    for _ in range(40):
        read_run(ws, RUN)
    read_ms = (time.perf_counter() - t) / 40 * 1000
    t = time.perf_counter()
    for n in range(20):
        writer.append(example(id=f"p{n}", at=at(9)))
    append_ms = (time.perf_counter() - t) / 20 * 1000
    assert read_ms < 6 and append_ms < 15, (read_ms, append_ms)


def test_foreign_key_lines_are_old_history_only_for_the_exact_recorded_old_kid(store):
    ws, writer = store
    write3(writer)
    old_kid = hp.record_key(ws)[1]
    _reset(ws)
    r = read_run(ws, RUN)
    assert (r.status, r.reason) == ("tampered", "old_key")  # the exact old kid: history
    # a genuine pre-reset run (no current-key lines) is pruned from the reset time
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 100 * 86400))
    # a planted foreign kid in front of a CURRENT-key run: content, and the run is not pruned
    writer.append(example(id="toolu_new", at=at(9)))  # the new segment, seq 1
    raw = runfile(ws).read_bytes()
    fake = raw.splitlines(keepends=True)[0].replace(old_kid.encode(), b"deadbeef")
    runfile(ws).write_bytes(fake + raw)
    r = read_run(ws, RUN)
    assert r.status == "ok" and r.reason == "content" and [e["id"] for e in r.unwrap()] == ["toolu_new"]
    assert r.changed >= 1
    res = record.apply_retention(ws, later, 90, 2048, lambda *a: None)
    assert RUN not in res["delete_run"] and runfile(ws).exists()


def test_delta_med1_cutting_the_outside_file_does_not_reset_the_day_cap(store, monkeypatch):
    from orch import secretrun
    from orch.errors import Refused

    ws, writer = store
    run = "r_outside_20261116"
    monkeypatch.setattr(secretrun, "_run_ids", lambda: None)
    monkeypatch.setattr(secretrun, "require_run", lambda *a: None)
    count = iter(range(100))
    monkeypatch.setattr(secretrun, "_record_event", lambda root, ev: example(run=run, id=f"u{next(count)}"))
    monkeypatch.setattr(secretrun, "OUTSIDE_DAY_CAP", 3)
    monkeypatch.setattr(secretrun, "record_writer", lambda root: writer)
    for _ in range(3):
        secretrun._write_record(ws, {})
    runfile(ws, run).unlink()  # the file is cut away: orch's own head still knows
    with pytest.raises(Refused, match="too many key uses"):
        secretrun._write_record(ws, {})


def test_delta_med2_a_missing_list_while_a_key_exists_means_no_legacy(store):
    ws, writer = store
    (hp.key_dir(ws, create=False) / "record-cutover.json").unlink()
    runfile(ws, "r_planted01").parent.mkdir(parents=True, exist_ok=True)
    runfile(ws, "r_planted01").write_text(
        json.dumps(dict(example(run="r_planted01", via="log"), seq=1)) + "\n"
    )
    write3(writer)  # no write makes a list again
    assert hp.record_cutover_read(ws) is None
    r = read_run(ws, "r_planted01")
    assert (r.status, r.legacy) == ("tampered", False)


def test_delta_med3_a_real_legacy_run_stays_not_checked_after_a_real_reset(store):
    ws, writer = store
    _legacy_run(ws, writer)
    assert read_run(ws, OTHER).legacy is True
    _reset(ws)
    r = read_run(ws, OTHER)
    assert (r.status, r.legacy, r.reason) == ("ok", True, "unchecked")
    # a list that did not verify under the old key is not carried: no legacy afterwards
    _legacy_run(ws, writer, "r_second01")
    path = hp.key_dir(ws, create=False) / "record-cutover.json"
    path.write_text(path.read_text().replace('"runs":[', '"runs":["r_evil0001",'))
    _reset(ws)
    assert read_run(ws, "r_second01").status == "tampered"


def test_delta_med5_a_forged_claim_never_names_the_tool(store):
    src = Path(record.__file__).parent / "cli_record.py"
    assert "_claim_agent" not in src.read_text()


def test_delta_low7_flat_sizes_count_direct_entries_of_pending_and_quarantine(store):
    ws, writer = store
    d = _spool_dir(ws)
    d.mkdir(parents=True)
    (d / ("0" * 19 + "1_" + "a" * 32 + ".json")).write_text("x" * 1000)
    base = record.record_sizes(ws).value["record"]
    assert base >= 1000
    deep = record_dir(ws) / "quarantine" / RUN / "q_1"
    deep.mkdir(parents=True)
    (deep / "big").write_text("y" * 5000)  # below a quarantined folder: never walked
    assert record.record_sizes(ws).value["record"] == base


def test_delta_low8_a_run_through_two_resets_keeps_its_first_key_lines_as_history(store):
    ws, writer = store
    write3(writer)
    _reset(ws)
    writer.append(example(id="toolu_b", at=at(7)))
    _reset(ws)
    writer.append(example(id="toolu_c", at=at(8)))
    r = read_run(ws, RUN)
    assert r.status == "ok" and r.reason == "old_key" and [e["id"] for e in r.unwrap()] == ["toolu_c"]
    assert r.changed == 4  # 3 lines of the first key and 1 of the second: all history, none planted

"""Record MAC S2: the attacker-names sweep. One test for each kind of thing an agent with file access can
plant next to orch's own files (names, folders, links, counters, heads, lines, details, spool entries): orch
reports it, never follows it, never crashes on it, and it never blocks a write, a read or retention."""

import json
import time
from pathlib import Path

import pytest

from orch import hider, record
from orch import humanproof as hp
from orch.record import RecordWriter, read_run, record_dir

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
RUN = "r_8k2m01"


def example(**changes):
    value = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    value.update(changes)
    return value


@pytest.fixture
def store(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    hp.record_key(ws)
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    for n in (1, 2, 3):
        w.append(example(id=f"toolu_{n}", at=f"2026-11-16T09:00:0{n}Z"))
    return ws, w


def spool(ws):
    d = record_dir(ws) / "pending" / RUN
    d.mkdir(parents=True, exist_ok=True)
    return d


GOOD = "0" * 19 + "1_" + "a" * 32 + ".json"


@pytest.mark.parametrize(
    "name",
    [
        "x.json",  # odd name
        GOOD + ".bak",  # the pattern with a suffix
        "x" + GOOD,  # the pattern with a prefix
        GOOD.upper(),  # case variant
        "0" * 19 + "1_" + "A" * 32 + ".json",  # upper-case hex
        "0" * 20 + "_" + "a" * 31 + ".json",  # one hex digit short
        ".hidden",
        "é中.json",  # unicode
        "n" * 200 + ".json",  # a long name
        "..json",
        " " + GOOD,
    ],
)
def test_odd_names_in_pending_are_told_never_committed_and_never_block(store, name):
    ws, w = store
    d = spool(ws)
    (d / name).write_text(json.dumps(dict(event=example(id="toolu_forged"), payload=None, default_id=False)))
    assert w.append(example(id="toolu_4", at="2026-11-16T09:00:04Z"))["seq"] == 4
    assert "toolu_forged" not in [e["id"] for e in read_run(ws, RUN).unwrap()]
    assert record._pending_count(ws, RUN) == 0  # never counts, so retention is never blocked


def test_a_huge_fan_out_of_junk_names_does_not_stop_a_write(store):
    ws, w = store
    d = spool(ws)
    for n in range(3000):
        (d / f"junk{n}").write_text("x")
    start = time.monotonic()
    assert w.append(example(id="toolu_4", at="2026-11-16T09:00:04Z"))["seq"] == 4
    assert time.monotonic() - start < 20


def test_an_oversized_spool_entry_is_rejected_without_being_read(store, monkeypatch):
    ws, w = store
    d = spool(ws)
    big = d / GOOD
    with big.open("wb") as f:
        f.truncate(record._SPOOL_MAX_BYTES + 1)  # sparse: a huge file that costs nothing to make
    read = []
    real = record._read_json
    monkeypatch.setattr(record, "_read_json", lambda *a: (read.append(a), real(*a))[1])
    w.append(example(id="toolu_4", at="2026-11-16T09:00:04Z"))
    assert not big.exists() and read == []  # deleted by its name, never read into memory
    assert read_run(ws, RUN).changed == 1


def test_a_run_file_that_is_a_folder_and_a_spool_folder_that_is_a_file_are_refused(store):
    ws, w = store
    runfile = record_dir(ws) / "runs" / f"{RUN}.jsonl"
    data = runfile.read_bytes()
    runfile.unlink()
    runfile.mkdir()
    assert read_run(ws, RUN).status == "tampered"
    with pytest.raises(record.RecordRefused):
        w.append(example(id="toolu_4"))
    runfile.rmdir()
    runfile.write_bytes(data)
    (record_dir(ws) / "pending").mkdir(exist_ok=True)
    (record_dir(ws) / "pending" / RUN).write_text("a file where the spool folder belongs")
    with pytest.raises(record.RecordRefused):
        w.append(example(id="toolu_4"))


@pytest.mark.parametrize("name", [f"{RUN}.jsonl.bak", "r_x.jsonl", "..jsonl", ".jsonl"])
def test_odd_names_next_to_the_run_files_are_never_runs(store, name):
    ws, w = store
    (record_dir(ws) / "runs" / name).write_text("{}\n")
    assert record.list_runs(ws).value == [RUN]
    assert read_run(ws, RUN).reason is None


def test_a_copy_of_the_whole_record_into_another_workspace_verifies_nothing(store, tmp_path):
    ws, w = store
    other = tmp_path / "other"
    other.mkdir()
    hp.record_key(other)  # another workspace, its own key
    (record_dir(other) / "runs").mkdir(parents=True)
    (record_dir(other) / "runs" / f"{RUN}.jsonl").write_bytes(
        (record_dir(ws) / "runs" / f"{RUN}.jsonl").read_bytes()
    )
    r = read_run(other, RUN)
    assert r.status == "tampered" and r.reason == "content" and r.value is None


def test_a_forged_rejects_counter_counts_loudly_never_as_zero(store):
    ws, w = store
    path = hp.key_dir(ws, create=False) / "record-heads" / f"{RUN}.rej"
    path.write_text("not a counter")
    assert hp.record_rejects_read(ws, RUN) == 1
    path.write_text(json.dumps({"schema": "orch.record-rejects/1", "run": RUN, "n": 10**18, "hm": "x"}))
    assert hp.record_rejects_read(ws, RUN) == 1  # a counter that fails its MAC is one loud change
    assert read_run(ws, RUN).changed == 1


def test_a_deleted_or_replayed_head_never_makes_a_sealed_run_legacy(store):
    ws, w = store
    heads = hp.key_dir(ws, create=False) / "record-heads"
    old = (heads / f"{RUN}.json").read_bytes()
    w.append(example(id="toolu_4", at="2026-11-16T09:00:04Z"))
    (heads / f"{RUN}.json").unlink()  # deleted: the chain still verifies from its genesis, never legacy
    r = read_run(ws, RUN)
    assert (r.legacy, r.reason, len(r.unwrap())) == (False, None, 4)
    (heads / f"{RUN}.json").write_bytes(
        old
    )  # rolled back to an older genuine head: it only proves "at least"
    assert read_run(ws, RUN).reason is None
    assert w.append(example(id="toolu_5", at="2026-11-16T09:00:05Z"))["seq"] == 5


def test_a_planted_symlinked_run_and_detail_never_leave_the_record(store, tmp_path):
    ws, w = store
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    detail = record_dir(ws) / "detail" / RUN
    detail.mkdir(parents=True)
    name = record.detail_name(RUN, "step", "toolu_d", example()["ticket"])
    (detail / f"{name}.json").symlink_to(outside)  # a link at the name a future detail will use
    stored = w.append(example(id="toolu_d", at="2026-11-16T09:00:04Z"), detail={"input": "a", "output": "b"})
    assert stored["detail_lost"] is True and outside.read_text() == "keep"


def test_planted_spool_names_never_starve_a_genuine_entry_and_are_never_read(store, monkeypatch):
    import os

    from orch import record_auth as ra

    ws, w = store
    lock = record_dir(ws) / "runs" / f"{RUN}.lock"
    lock.touch()
    monkeypatch.setattr(record, "_LOCK_WAIT", 0.01)
    w.append(example(id="toolu_g", at="2026-11-16T09:00:04Z"))  # spooled under a proven name
    lock.unlink()
    d = spool(ws)
    (genuine,) = list(d.iterdir())
    rec = hp.record_key(ws)
    assert ra.spool_name_ok(rec[2], rec[0], RUN, genuine.name)
    planted = {f".{n:04d}" for n in range(600)} | {
        f"{9 * 10**19 + n:020d}_{'a' * 32}.json" for n in range(600)
    }
    for name in planted:  # newer than the upgrade marker: never old-format candidates
        (d / name).write_text("{}")
    seen = []
    for fn in ("_read_json", "_file_size"):
        real = getattr(record, fn)
        monkeypatch.setattr(record, fn, lambda *a, _r=real: (seen.append(a[1][-1]), _r(*a))[1])
    real_open = os.open

    def counted_open(p, *a, **k):
        seen.append(os.path.basename(str(p)))
        return real_open(p, *a, **k)

    monkeypatch.setattr(os, "open", counted_open)
    w.append(example(id="toolu_5", at="2026-11-16T09:00:05Z"))
    snapshot = set(seen)
    assert "toolu_g" in [e["id"] for e in read_run(ws, RUN).unwrap()]
    assert not planted & snapshot  # no planted name was opened or read
    assert len(list(d.iterdir())) == 1200 - 50  # 50 refused by name per call, the rest next time


def test_an_upgraded_key_without_a_cutover_list_adopts_existing_runs_once(tmp_path):
    ws = tmp_path / "up"
    ws.mkdir()
    assert hp.ensure_record_key(ws)
    cutover = hp.key_dir(ws, create=False) / "record-cutover.json"
    cutover.unlink()  # a key made before the list and the upgrade marker existed
    (cutover.parent / "record-upgrade.json").unlink()
    (record_dir(ws) / "runs").mkdir(parents=True, exist_ok=True)
    (record_dir(ws) / "runs" / f"{RUN}.jsonl").write_text(json.dumps(example(seq=1)) + "\n")
    assert hp.ensure_record_key(ws)
    assert hp.record_cutover_read(ws) == {RUN} and read_run(ws, RUN).legacy is True
    RecordWriter(ws, hider=hider.Hider({"k": "KEYVALUE-abc123XYZ-secret"})).append(
        example(run="r_other01", id="toolu_n")
    )  # a head exists
    cutover.unlink()
    assert hp.ensure_record_key(ws)
    assert not cutover.exists()  # never re-made once the upgrade ran


def _pre_upgrade_key(ws):
    """A key made before the upgrade code: no cutover list, no upgrade marker."""
    assert hp.ensure_record_key(ws)
    d = hp.key_dir(ws, create=False)
    (d / "record-cutover.json").unlink()
    (d / "record-upgrade.json").unlink()
    return d


def _run_file(ws, run, mtime_ns=None):
    f = record_dir(ws) / "runs" / f"{run}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(example(run=run, seq=1)) + "\n")
    if mtime_ns is not None:
        import os

        os.utime(f, ns=(mtime_ns, mtime_ns))
    return f


def test_the_upgrade_runs_once_builds_the_list_only_without_any_head_and_ignores_mtimes(tmp_path):
    ws = tmp_path / "up"
    ws.mkdir()
    d = _pre_upgrade_key(ws)
    _run_file(ws, RUN)
    _run_file(ws, "r_future01", time.time_ns() + 10**12)  # an mtime set into the future changes nothing
    assert hp.ensure_record_key(ws)
    assert hp.record_upgrade_at(ws) and hp.record_cutover_read(ws) == {
        RUN,
        "r_future01",
    }  # no mtime is trusted
    before = {n: (d / n).read_bytes() for n in ("record-upgrade.json", "record-cutover.json")}
    assert hp.ensure_record_key(ws)
    assert before == {n: (d / n).read_bytes() for n in before}  # never rewritten


def test_the_upgrade_with_any_head_writes_the_marker_but_no_list(tmp_path):
    ws = tmp_path / "up"
    ws.mkdir()
    d = _pre_upgrade_key(ws)
    heads = d / "record-heads"
    heads.mkdir(exist_ok=True)
    hp.record_head_write(ws, RUN, {"run": RUN, "seq": 1, "mac": "M" * 43})  # a run was sealed before
    _run_file(ws, "r_planted1")
    assert hp.ensure_record_key(ws)
    assert hp.record_upgrade_at(ws) and hp.record_cutover_read(ws) is None  # fail closed: nothing legacy
    assert read_run(ws, "r_planted1").legacy is not True


def test_a_deleted_list_after_the_upgrade_never_adopts_a_planted_run(tmp_path):
    ws = tmp_path / "up"
    ws.mkdir()
    assert hp.ensure_record_key(ws)
    d = hp.key_dir(ws, create=False)
    (d / "record-cutover.json").unlink()
    import shutil

    shutil.rmtree(d / "record-heads", ignore_errors=True)
    _run_file(ws, "r_planted1", 0)  # an old mtime does not help after the upgrade
    assert hp.ensure_record_key(ws)
    assert not (d / "record-cutover.json").exists()
    assert hp.record_cutover_read(ws) is None and read_run(ws, "r_planted1").legacy is not True


def test_a_reset_keeps_legacy_runs_and_the_upgrade_marker(tmp_path):
    ws = tmp_path / "up"
    ws.mkdir()
    _pre_upgrade_key(ws)
    _run_file(ws, RUN)
    assert hp.ensure_record_key(ws)
    at = hp.record_upgrade_at(ws)
    hp.reset_protection(ws, "test")
    assert hp.record_upgrade_at(ws) == at and hp.record_cutover_read(ws) == {RUN}
    assert read_run(ws, RUN).legacy is True


def _old_entry(ws, name, run=RUN, good=True):
    from orch import record_auth as ra

    rec = hp.record_key(ws)
    event = example(id="toolu_old", at="2026-11-16T09:00:04Z")
    entry = {"event": event, "payload": None, "default_id": False}
    entry["sm"] = ra.spool_mac(rec[2], rec[0], run, name, dict(entry)) if good else "x" * 43
    d = record_dir(ws) / "pending" / run
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(entry))
    return d / name


def _old_name(n):
    return f"{n:020d}_{'5' * 32}.json"


def _upgrade_with_old_entry(ws, name):
    """A pre-upgrade install with one old-format spool entry, then the real upgrade."""
    d = _pre_upgrade_key(ws)
    _old_entry(ws, name)
    assert hp.ensure_record_key(ws)
    return d


def test_old_format_entries_listed_in_the_marker_are_drained(tmp_path):
    ws = tmp_path / "up"
    ws.mkdir()
    _upgrade_with_old_entry(ws, _old_name(1))
    assert hp.record_upgrade_old(ws, RUN) == {_old_name(1)}
    w = RecordWriter(ws, hider=hider.Hider({"k": "KEYVALUE-abc123XYZ-secret"}))
    w.append(example(id="toolu_5", at="2026-11-16T09:00:05Z"))
    assert "toolu_old" in [e["id"] for e in read_run(ws, RUN).unwrap()]
    assert not (record_dir(ws) / "pending" / RUN / _old_name(1)).exists()


@pytest.mark.parametrize("case", ["not_listed", "bad_sm", "fresh_key"])
def test_other_old_format_entries_are_refused(tmp_path, case):
    ws = tmp_path / "up"
    ws.mkdir()
    if case == "fresh_key":
        assert hp.ensure_record_key(ws)  # a key made now: no real upgrade, no old names accepted
        f = _old_entry(ws, _old_name(1))
    else:
        _upgrade_with_old_entry(ws, _old_name(1))
        f = None
        if case == "not_listed":
            (record_dir(ws) / "pending" / RUN / _old_name(1)).unlink()  # only a planted one is left
            f = _old_entry(ws, _old_name(2))
        if case == "bad_sm":
            f = record_dir(ws) / "pending" / RUN / _old_name(1)
            f.write_text(
                json.dumps(
                    {"event": example(id="toolu_old"), "payload": None, "default_id": False, "sm": "x" * 43}
                )
            )
    w = RecordWriter(ws, hider=hider.Hider({"k": "KEYVALUE-abc123XYZ-secret"}))
    w.append(example(id="toolu_5", at="2026-11-16T09:00:05Z"))
    assert "toolu_old" not in [e["id"] for e in read_run(ws, RUN).unwrap()]
    assert not f.exists()


def test_a_flood_of_planted_old_format_names_is_refused_in_batches_and_never_left(tmp_path):
    ws = tmp_path / "up"
    ws.mkdir()
    _upgrade_with_old_entry(ws, _old_name(1))
    d = record_dir(ws) / "pending" / RUN
    for n in range(2, 202):  # 200 planted ones, not in the marker
        (d / _old_name(n)).write_text("{}")
    w = RecordWriter(ws, hider=hider.Hider({"k": "KEYVALUE-abc123XYZ-secret"}))
    w.append(example(id="toolu_5", at="2026-11-16T09:00:05Z"))
    assert "toolu_old" in [e["id"] for e in read_run(ws, RUN).unwrap()]  # the listed one is drained at once
    for _ in range(5):
        w.append(example(id=f"toolu_x{_}", at="2026-11-16T09:00:06Z"))
    assert list(d.iterdir()) == []  # all refused (moved aside) within a few calls, none left behind


def test_more_listed_old_entries_than_one_batch_all_survive_and_are_committed(tmp_path):
    from orch import record_auth as ra

    ws = tmp_path / "up"
    ws.mkdir()
    _pre_upgrade_key(ws)
    rec = hp.record_key(ws)
    pend = record_dir(ws) / "pending" / RUN
    pend.mkdir(parents=True)
    for n in range(130):
        name = _old_name(n + 1)
        ev = example(id=f"toolu_o{n}", at="2026-11-16T09:00:04Z")
        entry = {"event": ev, "payload": None, "default_id": False}
        entry["sm"] = ra.spool_mac(rec[2], rec[0], RUN, name, dict(entry))
        (pend / name).write_text(json.dumps(entry))
    assert hp.ensure_record_key(ws) and len(hp.record_upgrade_old(ws, RUN)) == 130
    w = RecordWriter(ws, hider=hider.Hider({"k": "KEYVALUE-abc123XYZ-secret"}))
    for k in range(4):  # 50 per drain: three drains are enough
        w.append(example(id=f"toolu_n{k}", at="2026-11-16T09:00:05Z"))
    got = {e["id"] for e in read_run(ws, RUN).unwrap()}
    assert all(f"toolu_o{n}" in got for n in range(130))  # none refused, all committed
    assert list(pend.iterdir()) == []


def test_an_unlistable_run_folder_does_not_drop_the_other_runs_old_names(tmp_path):
    ws = tmp_path / "up"
    ws.mkdir()
    _pre_upgrade_key(ws)
    _old_entry(ws, _old_name(1), run="r_other001")
    bad = record_dir(ws) / "pending" / "r_bad00001"
    bad.mkdir(parents=True)
    bad.chmod(0)
    try:
        assert hp.ensure_record_key(ws)
    finally:
        bad.chmod(0o700)
    assert hp.record_upgrade_old(ws, "r_other001") == {_old_name(1)}

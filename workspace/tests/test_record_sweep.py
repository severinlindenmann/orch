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

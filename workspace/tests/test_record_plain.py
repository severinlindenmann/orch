"""The record chain is plain: append-only run files with no MAC and no record key (#833)."""

import json
from pathlib import Path

import pytest

from orch import hider, humanproof, record

ROOT = Path(__file__).resolve().parents[2]
RUN = "r_8k2m01"
OLD_AUTH = {"k": "0a1b2c3d", "p": "A" * 43, "m": "B" * 43}


def event(**changes):
    value = json.loads((ROOT / "contracts/examples/activity/valid-step-started.json").read_text())
    return dict(value) | changes


@pytest.fixture
def store(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws, record.RecordWriter(ws, hider=hider.Hider({"key": "a-long-secret-value"}))


def runfile(ws):
    return record.record_dir(ws) / "runs" / (RUN + ".jsonl")


def test_an_old_record_with_mac_fields_loads_and_lists(store):
    ws, writer = store
    first = dict(event(id="old1"), seq=1, run=RUN)
    second = dict(event(id="old2"), seq=2, run=RUN)
    runfile(ws).parent.mkdir(parents=True)
    # lines as an older orch wrote them: the body with the auth suffix (the values are never checked now)
    runfile(ws).write_text(
        "".join(
            json.dumps({**line, "auth": OLD_AUTH}, separators=(",", ":")) + "\n" for line in (first, second)
        )
    )
    listed = record.list_runs(ws)
    assert listed.status == "ok" and listed.value == [RUN]
    read = record.read_run(ws, RUN)
    assert read.status == "ok" and read.reason is None and read.changed == 0
    assert [e["id"] for e in read.value] == ["old1", "old2"]
    assert all("auth" not in e for e in read.value)
    # a new line goes on after the old ones, plain
    stored = writer.append(event(id="new1"))
    assert stored["seq"] == 3
    assert [e["id"] for e in record.read_run(ws, RUN).unwrap()] == ["old1", "old2", "new1"]


def test_a_new_record_has_no_mac_and_makes_no_key_file(store):
    ws, writer = store
    writer.append(event(id="a"))
    writer.append(event(id="b", via="log"))
    lines = runfile(ws).read_text().splitlines()
    assert len(lines) == 2
    assert all("auth" not in json.loads(line) for line in lines)
    assert [json.loads(line)["seq"] for line in lines] == [1, 2]
    # nothing was made in the guarded home: no key folder, no record key, no head or cutover file
    assert not list(humanproof.guarded_home(ws).rglob("*"))
    for name in ("record_key", "ensure_record_key", "record_head_read", "record_cutover_read"):
        assert not hasattr(humanproof, name)
    assert not list(record.record_dir(ws).rglob("*.head"))

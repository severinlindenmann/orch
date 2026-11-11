"""`files` on step events (activity.md, Files): the writer re-checks every entry after hiding, drops bad
entries and never the line."""

import copy
import json
import re
from pathlib import Path

import jsonschema
import pytest

from orch import hider, record
from orch.phone_view import redact
from orch.record import RecordWriter, read_run
from orch.record_files import file_ok, workspace_file, workspace_files

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
VECTORS = json.loads((CONTRACTS / "vectors/activity-v1.json").read_text())
SCHEMA = json.loads((CONTRACTS / "activity.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
SECRET = "KEYVALUE-abc123XYZ-secret"
RUN = "r_8k2m01"


@pytest.fixture
def store(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws, RecordWriter(ws, hider=hider.Hider({"deploy-key": SECRET}))


def example(name="valid-step-started", **changes):
    value = json.loads((CONTRACTS / f"examples/activity/{name}.json").read_text())
    value.update(changes)
    return value


def runfile(ws):
    return record.record_dir(ws) / "runs" / f"{RUN}.jsonl"


@pytest.mark.parametrize("case", VECTORS["files"], ids=lambda c: c["name"])
def test_vectors_writer_keeps_the_line_and_only_good_entries(store, case):
    ws, writer = store
    value = example(case["base"], files=copy.deepcopy(case["files"]))
    stored = writer.append(value)
    assert stored is not None and stored["seq"] == 1  # the audit line is never dropped
    if case["stored"] is None:
        assert "files" not in stored
    else:
        assert stored["files"] == case["stored"]
        assert all(file_ok(f) for f in stored["files"])
    VALIDATOR.validate(stored)
    assert record._VALIDATOR.is_valid(stored)
    assert read_run(ws, value["run"]).unwrap() == [stored]
    assert VALIDATOR.is_valid(value) is case["schema"]


def test_vector_lengths_are_exact():
    by_name = {c["name"]: c for c in VECTORS["files"]}
    assert [len(f) for f in by_name["260 characters"]["files"]] == [260]
    assert [len(f) for f in by_name["261 characters"]["files"]] == [261]
    assert len(by_name["nine entries"]["files"]) == 9


@pytest.mark.parametrize(
    "bad",
    [
        "/etc/passwd",
        "../x",
        "a/../b",
        "a/..",
        "..",
        "a\\b",
        "C:/x",
        "c:x",
        "\\\\srv\\share",
        "//srv/share",
        "",
        "a\x00b",
        "a\nb",
        "a\x1fb",
        "a\x7fb",
        "x" * 261,
        "docs/U\u0308bersicht.md",
        42,
        None,
        ["a"],
        {"p": "a"},
    ],
)
def test_every_invalid_shape_is_dropped_line_kept(store, bad):
    ws, writer = store
    stored = writer.append(example(files=["before.py", bad, "after.py"]))
    assert stored["files"] == ["before.py", "after.py"]
    assert read_run(ws, RUN).unwrap() == [stored]
    assert not file_ok(bad)


def test_writer_check_matches_the_shared_check_and_the_schema():
    entries = [f for c in VECTORS["files"] if isinstance(c["files"], list) for f in c["files"]]
    entries += ["src/\u00e9.py", "e\u0301.py", "a:b", "1:/x", ".", "./a", "a//b", "x" * 260]
    item = jsonschema.Draft202012Validator({"$ref": "#/$defs/file_path", "$defs": SCHEMA["$defs"]})
    for f in entries:
        writer_ok = type(f) is str and bool(re.fullmatch(record._FILE_PATH, f)) and redact(f) == f
        assert writer_ok == file_ok(f), f
        if file_ok(f):
            assert item.is_valid(f), f


def test_a_path_with_a_key_value_is_dropped_not_stored_hidden(store):
    ws, writer = store
    stored = writer.append(example(files=[f"keys/{SECRET}.txt", "src/app.py", f"{SECRET}"]))
    assert stored["files"] == ["src/app.py"]
    raw = runfile(ws).read_text()
    assert SECRET not in raw and "[hidden" not in raw.split('"files"')[1]


def test_a_path_the_plain_text_cleaner_changes_is_dropped(store):
    ws, writer = store
    # U+202E (right-to-left override) passes the shape but the cleaner removes it: dropped, not rewritten.
    stored = writer.append(example(files=["src/\u202eyp.exe", "src/ok.py"]))
    assert stored["files"] == ["src/ok.py"]


def test_first_eight_good_entries_after_dropping(store):
    ws, writer = store
    files = ["/abs", *[f"f{n}" for n in range(1, 10)], "../up"]
    stored = writer.append(example(files=files))
    assert stored["files"] == [f"f{n}" for n in range(1, 9)]


def test_all_dropped_keeps_an_empty_list_and_the_line(store):
    ws, writer = store
    stored = writer.append(example(files=["/a", "../b", SECRET]))
    assert stored["files"] == [] and stored["text"] == "Read report-2025-11.pdf"
    assert len(runfile(ws).read_text().splitlines()) == 1


@pytest.mark.parametrize("files", ["src/app.py", {"a": 1}, 7, None])
def test_files_not_a_list_is_removed(store, files):
    ws, writer = store
    stored = writer.append(example(files=files))
    assert "files" not in stored


@pytest.mark.parametrize(
    "name,changes",
    [
        ("valid-run-state-say", {}),
        ("valid-task-done", {}),
        (
            "valid-step-started",
            {"kind": "denial", "outcome": {"ok": False, "error": "Not allowed", "ms": None}},
        ),
    ],
)
def test_files_on_another_kind_is_removed_line_kept(store, name, changes):
    ws, writer = store
    stored = writer.append(example(name, files=["src/app.py"], **changes))
    assert stored is not None and "files" not in stored
    VALIDATOR.validate(stored)


def test_files_survive_dedupe_and_the_finished_line(store):
    ws, writer = store
    started = writer.append(example(files=["src/app.py"]))
    assert writer.append(example(files=["src/app.py"])) is None
    finished = writer.append(
        example(files=["src/app.py", "tests/t.py"], outcome={"ok": True, "error": None, "ms": 5}),
        detail={"input": {"file_path": "/abs/src/app.py"}, "output": "ok"},
    )
    assert started["files"] == ["src/app.py"] and finished["files"] == ["src/app.py", "tests/t.py"]
    detail = record.read_detail(ws, RUN, finished["detail"].split("/")[-1][:-5]).unwrap()
    assert detail["input"] == {"file_path": "/abs/src/app.py"}  # the detail file is unchanged


def test_files_through_the_pending_spool(store, monkeypatch):
    ws, writer = store
    writer.append(example(id="first"))
    monkeypatch.setattr(record, "_LOCK_WAIT", 0)
    with record._lock(ws, RUN):
        spooled = writer.append(example(id="waiting", files=["src/a.py", "/abs"]))
    assert spooled["pending"] is True and spooled["files"] == ["src/a.py"]
    writer.append(example(id="last"))
    events = read_run(ws, RUN).unwrap()
    assert [e["id"] for e in events] == ["first", "waiting", "last"]
    assert events[1]["files"] == ["src/a.py"] and "files" not in events[2]


def test_writer_input_is_not_changed(store):
    ws, writer = store
    value = example(files=["/abs", "src/a.py"])
    original = copy.deepcopy(value)
    writer.append(value)
    assert value == original


@pytest.mark.parametrize("case", VECTORS["files_normalise"], ids=lambda c: c["name"])
def test_normalise_vectors(case):
    assert workspace_file(case["path"], case["root"]) == case["file"]


def test_normalise_list_order_repeats_limit():
    root = "/work/proj"
    paths = ["/work/proj/a", "a", "/etc/x", *[f"/work/proj/f{n}" for n in range(1, 12)]]
    assert workspace_files(paths, root) == ["a", *[f"f{n}" for n in range(1, 8)]]
    assert workspace_files("a", root) == [] and workspace_files(None, root) == []


def test_normalise_against_the_real_root(tmp_path):
    real = tmp_path / "real"
    (real / "src").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    assert workspace_file(f"{real.resolve()}/src/a.py", link) == "src/a.py"
    assert workspace_file(f"{link}/src/a.py", link) == "src/a.py"
    assert workspace_file(f"{tmp_path}/other/a.py", link) is None


def test_multibyte_paths_are_trimmed_to_a_byte_budget_and_the_line_is_written(store):
    ws, writer = store
    files = [f"d{n}/" + "日本語" * 50 for n in range(8)]  # 8 x ~150 chars, ~450 bytes each
    assert all(file_ok(f) for f in files)
    stored = writer.append(example(files=files, data={"k": "v"}))
    assert stored is not None
    kept = read_run(ws, RUN).unwrap()[0]["files"]
    assert 0 < len(kept) < 8 and kept == files[: len(kept)]
    assert sum(len(f.encode()) for f in kept) <= 2048


def test_extreme_line_still_writes_a_minimal_step(store):
    ws, writer = store
    files = ["x" * 250 + str(n) for n in range(8)]
    big = {f"k{n}": "日本語" * 70 for n in range(30)}  # near the data cap, with files it overflows the line
    stored = writer.append(example(files=files, data=big))
    assert stored is not None
    assert read_run(ws, RUN).unwrap()[0]["kind"] == "step"


def test_an_entry_over_512_bytes_is_not_stored_but_the_line_is(store):
    ws, writer = store
    assert writer.append(example(files=["日本語" * 85])) is not None  # 260 chars, 765 bytes
    assert read_run(ws, RUN).unwrap()[0]["files"] == []

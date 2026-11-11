"""Contract vectors and filesystem boundaries for the record store."""

import base64
import copy
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import jsonschema
import pytest

from orch import hider, record
from orch.record import (
    RecordRefused,
    RecordWriter,
    apply_retention,
    delete_detail,
    hook_entry_filter,
    list_runs,
    plan_retention,
    read_detail,
    read_events,
    record_dir,
    registered_writer,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
VECTORS = json.loads((CONTRACTS / "vectors/activity-v1.json").read_text())
SCHEMA = json.loads((CONTRACTS / "activity.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
SECRET = "KEYVALUE-abc123XYZ-secret"


@pytest.fixture
def store(tmp_path):
    ws = tmp_path / "ws"
    return ws, RecordWriter(ws, hider=hider.Hider({"deploy-key": SECRET}))


def event(**changes):
    value = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    value.update(changes)
    return value


@pytest.mark.parametrize(
    "path", sorted((CONTRACTS / "examples/activity").glob("*.json")), ids=lambda p: p.name
)
def test_examples(store, path):
    ws, writer = store
    value = json.loads(path.read_text())
    if path.name.startswith("invalid"):
        with pytest.raises(RecordRefused):
            writer.append(value)
        assert not record_dir(ws).exists()
    else:
        stored = writer.append(value)
        VALIDATOR.validate(stored)
        assert read_events(ws, value["run"]) == [stored]


@pytest.mark.parametrize("case", VECTORS["stream_mapping"])
def test_stream(store, case):
    ws, writer = store
    stored = []
    for seq, value in enumerate(case["events"], 1):
        stored.append(writer.append(value))
        assert stored[-1]["seq"] == seq
        assert writer.append(value) is None
    assert read_events(ws, case["ctx"]["run"]) == stored


@pytest.mark.parametrize("case", VECTORS["ids"])
def test_ids(store, case):
    _, writer = store
    for n in range(1, case["seq"]):
        writer.append(event(run=case["run"], id=f"prefix{n}"))
    value = event(run=case["run"])
    value.pop("id")
    if case["tool_call_id"] is not None:
        value["id"] = case["tool_call_id"]
    assert writer.append(value)["id"] == case["id"]


@pytest.mark.parametrize("case", VECTORS["detail_names"])
def test_detail_names(store, case):
    ws, writer = store
    stored = writer.append(event(id=case["id"]), detail={"input": {}, "output": "ok"})
    assert stored["detail"] == f"detail/{stored['run']}/{case['file']}.json"
    assert read_detail(ws, stored["run"], case["file"])["output"] == "ok"


@pytest.mark.parametrize("case", VECTORS["dedupe"])
def test_dedupe(store, case):
    ws, writer = store
    values = []
    for i, line in enumerate(case["lines"]):
        value = event(**line, data={"index": i})
        if value["kind"].startswith("helper"):
            value.update(agent="h_1", parent="main")
            value["used"]["kind"] = "helper"
        values.append(value)
        writer.append(value)
    run = values[0]["run"]
    assert [e["data"]["index"] for e in read_events(ws, run)] == case["keep"]
    path = record_dir(ws) / "runs" / f"{run}.jsonl"
    path.write_text("\n".join(json.dumps(dict(e, seq=i + 1)) for i, e in enumerate(values)) + "\n")
    with path.open("a") as stream:
        stream.write('bad json\n{"v":2}\n')
    assert [e["data"]["index"] for e in read_events(ws, run)] == case["keep"]


def test_fail_closed(store, monkeypatch):
    ws, writer = store
    with pytest.raises(TypeError):
        RecordWriter(ws)
    for bad in (None, "hider", lambda s: s):
        with pytest.raises(RecordRefused):
            RecordWriter(ws, hider=bad)
    monkeypatch.setattr(hider, "_registered", None)
    for case in VECTORS["fail_closed"]:
        for key, value in case["env"].items():
            monkeypatch.setenv(key, value)
        with pytest.raises(RecordRefused, match=r"^Recording is off until key hiding is ready\.$"):
            registered_writer(ws)
    assert not ws.exists()
    with hider.use_hider(writer.hider):
        assert registered_writer(ws).append(event())
    assert RecordWriter(ws, hider=hider.Hider({})).append(event(id="empty"))


@pytest.mark.parametrize("part", ["", "runs", "detail", "jobs", "runs/r_8k2m01.jsonl", "runs/r_8k2m01.lock"])
def test_symlink(store, tmp_path, part):
    ws, writer = store
    outside = tmp_path / "outside"
    outside.mkdir()
    target = record_dir(ws) / part
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RecordRefused):
        writer.append(event())
    assert list(outside.iterdir()) == []


def forms(secret):
    raw = secret.encode()
    values = {secret, raw.hex(), raw.hex().upper(), quote(secret, safe=""), json.dumps(secret)[1:-1]}
    values |= {base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode()}
    for offset in range(3):
        encoded = base64.b64encode(b"\0" * offset + raw).decode().rstrip("=")
        part = encoded[(8 * offset + 5) // 6 : 8 * (offset + len(raw)) // 6]
        values |= {part, part.translate(str.maketrans("+/", "-_"))}
    return values


def test_hiding_every_file(store):
    ws, writer = store
    for i, form in enumerate(forms(SECRET)):
        value = event(
            id=f"secret{i}", text=form, data={form: [form]}, outcome={"ok": False, "error": form, "ms": None}
        )
        stored = writer.append(value, detail={"input": {form: form}, "output": form})
        assert "[hidden: " in stored["text"]
        detail = read_detail(ws, stored["run"], f"secret{i}")
        assert detail["hidden"] >= 5
    stored = writer.append(event(id="generic", text="ghp_" + "a" * 36))
    assert "ghp_" not in stored["text"]
    for path in record_dir(ws).rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert all(form.encode() not in data for form in forms(SECRET))


def test_permissions_meta_and_limits(store):
    ws, writer = store
    first = writer.append(event(text="z" * 100000), detail={"input": {}, "output": "界" * 600000})
    root = record_dir(ws)
    meta = (root / "meta.json").read_bytes()
    assert json.loads(meta) == dict(schema="orch.record/1", since=first["at"], keep_days=90, max_mb=2048)
    writer.append(event(id="later", at="2026-11-17T00:00:00Z"))
    assert (root / "meta.json").read_bytes() == meta
    detail = root / first["detail"]
    assert detail.stat().st_size <= 1024**2
    assert json.loads(detail.read_bytes())["truncated"] is True
    for line in (root / "runs" / f"{first['run']}.jsonl").read_bytes().splitlines(keepends=True):
        assert len(line) <= 8192
        VALIDATOR.validate(json.loads(line))
    if os.name != "nt":
        for path in (root, *root.rglob("*")):
            assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)


def test_concurrency(store):
    ws, writer = store
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: writer.append(event(id=f"thread{i}")), range(32)))
    assert sorted(e["seq"] for e in results) == list(range(1, 33))
    assert len(read_events(ws, "r_8k2m01")) == 32
    assert list_runs(ws) == ["r_8k2m01"]


@pytest.mark.parametrize("case", VECTORS["retention"])
def test_retention_plan(case):
    assert plan_retention(case["runs"], case["now"], case["keep_days"], case["max_mb"]) == case["expect"]


def test_retention_apply(store):
    ws, writer = store
    for run, state in (("r_old0001", "done"), ("r_live001", "working")):
        writer.append(
            event(
                run=run,
                id=run,
                kind="run.state",
                via="core",
                used=None,
                data={"state": state},
                at="2026-01-01T00:00:00Z",
            ),
            detail={"input": {}, "output": "payload"},
        )
    root = record_dir(ws)
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def fail(run, events):
        raise RuntimeError("fold failed")

    with pytest.raises(RuntimeError):
        apply_retention(ws, "2026-11-16T00:00:00Z", 90, 0, fail)
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    folded = []
    plan = apply_retention(ws, "2026-11-16T00:00:00Z", 90, 0, lambda r, es: folded.append(r))
    assert plan["delete_run"] == folded == ["r_old0001"]
    assert list_runs(ws) == ["r_live001"]
    assert len(list((root / "detail").iterdir())) == 1
    delete_detail(ws, ["r_live001"])
    assert list((root / "detail").iterdir()) == []
    assert list_runs(ws) == ["r_live001"]


@pytest.mark.parametrize("case", VECTORS["hook_entry"])
def test_hook_entry(case):
    original = copy.deepcopy(case["line"])
    if case["stored"] == "refused":
        with pytest.raises(RecordRefused):
            hook_entry_filter(original)
    else:
        assert hook_entry_filter(original) == case["stored"]
    assert original == case["line"]


@pytest.mark.parametrize("run,file_id", [("../bad", "x"), ("r_8k2m01", "../x")])
def test_unsafe_read_names(store, run, file_id):
    ws, _ = store
    with pytest.raises(RecordRefused):
        read_detail(ws, run, file_id)


def test_oversize_refuses_without_event(store):
    ws, writer = store
    with pytest.raises(RecordRefused):
        writer.append(event(data={"huge": ["x" * 10000] * 2}))
    assert read_events(ws, "r_8k2m01") == []
    assert not (record_dir(ws) / "meta.json").exists()


def test_detail_schema_and_runtime_schema():
    from orch.record import _SCHEMA

    def constraints(value):
        if isinstance(value, dict):
            return {
                k: constraints(v)
                for k, v in value.items()
                if k not in ("description", "title", "$id", "$schema")
            }
        if isinstance(value, list):
            return [constraints(v) for v in value]
        return value

    assert _SCHEMA == constraints(SCHEMA)
    validator = jsonschema.Draft202012Validator({"$ref": "#/$defs/detail_file", "$defs": SCHEMA["$defs"]})
    for path in (CONTRACTS / "examples/activity-detail").glob("*.json"):
        assert validator.is_valid(json.loads(path.read_text())) == path.name.startswith("valid-")


def test_preflight_leaves_nothing(store):
    ws, writer = store
    with pytest.raises(RecordRefused):
        writer.append(event(), detail={"input": "x" * (1024**2), "output": ""})
    assert not ws.exists()
    with pytest.raises(RecordRefused):
        writer.append(event(data={"large": ["x" * 5000] * 3}))
    assert not ws.exists()


def test_stale_lock_and_missing_reads(store):
    ws, writer = store
    assert read_events(ws, "r_8k2m01") == []
    assert read_detail(ws, "r_8k2m01", "missing") is None
    assert list_runs(ws) == []
    writer.append(event())
    lock = record_dir(ws) / "runs/r_8k2m01.lock"
    lock.touch()
    os.utime(lock, (1, 1))
    assert writer.append(event(id="after_stale"))["seq"] == 2
    assert not lock.exists()


def test_secret_id_never_stored_plain_or_unsalted_hash(store):
    ws, writer = store
    for raw in (SECRET, "call/" + SECRET, "x y " + SECRET):
        assert writer.append(event(id=raw, text="ok", detail=None), detail={"input": "i", "output": "o"})
    unsalted = {
        hashlib.sha256(raw.encode()).hexdigest()[:32] for raw in (SECRET, "call/" + SECRET, "x y " + SECRET)
    }
    seen = 0
    for path in record_dir(ws).rglob("*"):
        text = path.name + (path.read_text() if path.is_file() else "")
        seen += 1
        assert SECRET not in text
        assert not any(h in text for h in unsalted)
    assert seen


def test_symlink_swapped_after_check_is_refused(store, tmp_path, monkeypatch):
    ws, writer = store
    outside = tmp_path / "outside"
    outside.mkdir()
    swapped = []
    real_safe = record._safe

    def swap_after_check(path):
        real_safe(path)
        target = record_dir(ws) / "detail" / "r_8k2m01"
        if path.name.endswith(".json") and path.parent == target and not swapped:
            swapped.append(1)
            target.rmdir()
            target.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(record, "_safe", swap_after_check)
    with pytest.raises(RecordRefused):
        writer.append(event(), detail={"input": "i", "output": "o"})
    assert swapped
    assert list(outside.iterdir()) == []


def test_hardlinked_run_file_refused(store, tmp_path):
    ws, writer = store
    writer.append(event())
    path = record_dir(ws) / "runs/r_8k2m01.jsonl"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    path.unlink()
    os.link(outside, path)
    with pytest.raises(RecordRefused):
        writer.append(event(id="another"))
    assert outside.read_text() == "keep"
    assert (outside.stat().st_mode & 0o777) == (tmp_path / "outside.txt").stat().st_mode & 0o777


def test_reparse_point_and_realpath_refused(tmp_path, monkeypatch):
    from types import SimpleNamespace

    folder = tmp_path / "ws" / ".orch" / "record" / "runs"
    folder.mkdir(parents=True)
    real_lstat = Path.lstat

    def fake_lstat(self, *a, **k):
        result = real_lstat(self, *a, **k)
        if self == folder:
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x410)
        return result

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(RecordRefused):
        record._safe(folder / "r_8k2m01.jsonl")
    monkeypatch.undo()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.setattr(
        record.os.path, "realpath", lambda p: str(outside / "x") if "runs" in str(p) else str(p)
    )
    with pytest.raises(RecordRefused):
        record._safe(folder / "r_8k2m01.jsonl")


def test_detail_of_colliding_id_never_replaces_other_detail(store):
    ws, writer = store
    done = event(id="same", outcome={"ok": True, "error": None, "ms": 1})
    stored = writer.append(done, detail={"input": "real", "output": "real"})
    other = event(
        id="same",
        kind="helper.start",
        agent="h_1",
        parent="main",
        via="hook",
        used={"kind": "helper", "name": "h", "action": None, "source": "builtin", "version": None},
    )
    other2 = writer.append(other, detail={"input": "fake", "output": "fake"})
    assert other2["detail"] != stored["detail"]
    assert json.loads((record_dir(ws) / stored["detail"]).read_text())["input"] == "real"


def test_detail_pointer_and_reserved_ids(store):
    ws, writer = store
    stored = writer.append(event(detail="detail/r_8k2m01/ghost.json"))
    assert stored["detail"] is None
    for raw in ("r_8k2m01:5", "x_" + "a" * 32):
        got = writer.append(event(id=raw))
        assert got["id"] != raw and got["id"].startswith("x_")


def test_late_started_detail_keeps_finished_detail(store):
    ws, writer = store
    done = writer.append(
        event(id="s1", outcome={"ok": True, "error": None, "ms": 1}), detail={"input": "a", "output": "final"}
    )
    writer.append(event(id="s1"), detail={"input": "b", "output": "early"})
    assert json.loads((record_dir(ws) / done["detail"]).read_text())["output"] == "final"


def test_detail_name_domains_never_collide(store):
    ws, writer = store
    raw = "weird id|helper.start"  # unsafe step id: hashed; the same text hashed for a non-step must differ
    step = writer.append(event(id=raw), detail={"input": "step", "output": "step"})
    other = writer.append(
        event(
            id=raw,
            kind="helper.start",
            agent="h_1",
            parent="main",
            via="hook",
            used={"kind": "helper", "name": "h", "action": None, "source": "builtin", "version": None},
        ),
        detail={"input": "other", "output": "other"},
    )
    assert step["detail"] != other["detail"]
    assert json.loads((record_dir(ws) / step["detail"]).read_text())["input"] == "step"
    got = writer.append(event(id="k_" + "b" * 32))
    assert got["id"].startswith("x_")
    # a stored file of another event under the target name is never replaced
    target = record_dir(ws) / "detail/r_8k2m01/victim.json"
    victim = json.loads((record_dir(ws) / step["detail"]).read_text())
    victim["id"] = "someone-else"
    target.write_text(json.dumps(victim))
    with pytest.raises(RecordRefused):
        writer.append(event(id="victim"), detail={"input": "x", "output": "y"})
    assert json.loads(target.read_text())["id"] == "someone-else"

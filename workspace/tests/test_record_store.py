"""Contract vectors and filesystem boundaries for the record store."""

import base64
import copy
import hashlib
import json
import os
import shutil
import stat
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
    read_run,
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
    ws.mkdir()
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
        assert read_run(ws, value["run"]).unwrap() == [stored]


@pytest.mark.parametrize("case", VECTORS["stream_mapping"])
def test_stream(store, case):
    ws, writer = store
    stored = []
    for seq, value in enumerate(case["events"], 1):
        stored.append(writer.append(value))
        assert stored[-1]["seq"] == seq
        assert writer.append(value) is None
    assert read_run(ws, case["ctx"]["run"]).unwrap() == stored


@pytest.mark.parametrize("case", VECTORS["ids"])
def test_ids(store, case):
    _, writer = store
    for n in range(1, case["seq"]):
        writer.append(event(run=case["run"], id=f"prefix{n}"))
    value = event(run=case["run"])
    value.pop("id")
    if case["tool_call_id"] is not None:
        value["id"] = case["tool_call_id"]
    else:
        value["via"] = (
            "log"  # <run>:<seq> is the default id of a collector line; a hook line gets h_<run>:<seq>
        )
    assert writer.append(value)["id"] == case["id"]


@pytest.mark.parametrize("case", VECTORS["hook_default_id"])
def test_hook_default_id_is_not_the_collector_id(store, case):
    _, writer = store
    for n in range(1, case["seq"]):
        writer.append(event(run=case["run"], id=f"prefix{n}"))
    value = event(run=case["run"])
    value.pop("id")
    assert writer.append(value)["id"] == case["hook"] != case["collector"]


@pytest.mark.parametrize("case", [c for c in VECTORS["detail_names"] if c["kind"] == "step"])
def test_detail_names(store, case):
    ws, writer = store
    raw = (
        "call/../x y" if case["id"].startswith("x_") else case["id"]
    )  # the writer hashes unsafe raw ids first
    stored = writer.append(event(id=raw, run=case["run"]), detail={"input": {}, "output": "ok"})
    assert stored["id"] == case["id"]
    assert stored["detail"] == f"detail/{case['run']}/{case['file']}.json"
    assert read_detail(ws, case["run"], case["file"]).unwrap()["output"] == "ok"


@pytest.mark.parametrize("case", VECTORS["dedupe"])
def test_dedupe(store, case):
    ws, writer = store
    values = []
    for i, line in enumerate(case["lines"]):
        value = event(**line, data={"index": i, "tokens_in": 1})
        if value["kind"].startswith("helper"):
            value.update(agent="h_1", parent="main")
            value["used"]["kind"] = "helper"
        values.append(value)
        writer.append(value)
    run = values[0]["run"]
    assert [e["data"]["index"] for e in read_run(ws, run).unwrap()] == case["keep"]
    path = record_dir(ws) / "runs" / f"{run}.jsonl"
    path.write_text("\n".join(json.dumps(dict(e, seq=i + 1)) for i, e in enumerate(values)) + "\n")
    with path.open("a") as stream:
        stream.write('bad json\n{"v":2}\n')
    assert [e["data"]["index"] for e in read_run(ws, run).unwrap()] == case["keep"]


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
    assert not record_dir(ws).exists()
    with hider.use_hider(writer.hider):
        assert registered_writer(ws).append(event())
    with pytest.raises(record.RecordOff):
        RecordWriter(ws, hider=hider.Hider({}))


@pytest.mark.parametrize("part", ["", "runs", "runs/r_8k2m01.jsonl", "runs/r_8k2m01.lock"])
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
        detail = read_detail(ws, stored["run"], Path(stored["detail"]).stem).unwrap()
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
    assert first["detail"] is None and first["detail_lost"]
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
    assert len(read_run(ws, "r_8k2m01").unwrap()) == 32
    assert list_runs(ws).unwrap() == ["r_8k2m01"]


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
    assert list_runs(ws).unwrap() == ["r_live001"]
    assert len(list((root / "detail").iterdir())) == 1
    delete_detail(ws, ["r_live001"])
    assert list((root / "detail").iterdir()) == []
    assert list_runs(ws).unwrap() == ["r_live001"]


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
        read_detail(ws, run, file_id).unwrap()


def test_oversize_data_is_cut(store):
    ws, writer = store
    stored = writer.append(event(data={"huge": ["x" * 10000] * 2}))
    assert stored["data"] == {"cut": True}
    assert read_run(ws, "r_8k2m01").unwrap() == [stored]


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

    assert _SCHEMA == SCHEMA
    validator = jsonschema.Draft202012Validator({"$ref": "#/$defs/detail_file", "$defs": SCHEMA["$defs"]})
    for path in (CONTRACTS / "examples/activity-detail").glob("*.json"):
        assert validator.is_valid(json.loads(path.read_text())) == path.name.startswith("valid-")


def test_preflight_leaves_nothing(store):
    ws, writer = store
    lost = writer.append(event(), detail={"input": "x" * (1024**2), "output": ""})
    assert lost["detail"] is None and lost["detail_lost"] is True  # the audit line is kept
    assert not (record_dir(ws) / "detail").exists()
    shutil.rmtree(record_dir(ws))
    assert writer.append(event(data={"large": ["x" * 5000] * 3}))["data"] == {"cut": True}


def test_stale_lock_and_missing_reads(store):
    ws, writer = store
    assert read_run(ws, "r_8k2m01").reason == "missing"
    assert read_detail(ws, "r_8k2m01", "0" * 32).reason == "missing"
    assert list_runs(ws).reason == "missing"
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
    stored = writer.append(event(detail="detail/r_8k2m01/" + "a" * 32 + ".json"))
    assert stored["detail"] is None
    for raw in ("r_8k2m01:5", "x_" + "a" * 32):
        got = writer.append(event(id=raw, via="hook"))
        assert got["id"] != raw and got["id"].startswith("x_")


def test_late_started_detail_keeps_finished_detail(store):
    ws, writer = store
    done = writer.append(
        event(id="s1", outcome={"ok": True, "error": None, "ms": 1}), detail={"input": "a", "output": "final"}
    )
    writer.append(event(id="s1"), detail={"input": "b", "output": "early"})
    assert json.loads((record_dir(ws) / done["detail"]).read_text())["output"] == "final"


def test_detail_name_property():
    import random
    import re

    from orch.collect_execjson import detail_name

    rng = random.Random(7)
    alphabet = "abAB09_-.:|/\\ \u00e9\u00c9\u4e2d"
    ids = {"".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12))) for _ in range(400)}
    ids |= {"A", "a", "same|step", "same", "x_" + "a" * 32, "X_" + "A" * 32}
    seen = {}
    for run in ("r_8k2m01", "r_8k2m02"):
        for kind in ("step", "helper.start", "run.state"):
            for eid in ids:
                name = detail_name(run, kind, eid)
                assert re.fullmatch("[0-9a-f]{32}", name)
                assert seen.setdefault(name, (run, kind, eid)) == (run, kind, eid)
    assert len({n.lower() for n in seen}) == len(seen)


def test_case_variants_and_collisions_never_drop_the_line(store):
    ws, writer = store
    one = writer.append(event(id="A"), detail={"input": "upper", "output": "upper"})
    two = writer.append(event(id="a"), detail={"input": "lower", "output": "lower"})
    assert one["detail"] != two["detail"] and not one.get("detail_lost") and not two.get("detail_lost")
    # a planted file of another event under the name an append would use: the line is kept, detail given up
    target = record_dir(ws) / writer_detail_path(ws, "z1")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "v": 1,
                "id": "someone",
                "run": "r_8k2m01",
                "kind": "step",
                "input": "p",
                "output": "p",
                "truncated": False,
                "hidden": 0,
            }
        )
    )
    kept = writer.append(event(id="z1"), detail={"input": "x", "output": "y"})
    assert kept is not None and kept["detail"] is None and kept["detail_lost"] is True
    assert json.loads(target.read_text())["id"] == "someone"
    assert [e["id"] for e in read_run(ws, "r_8k2m01").unwrap()] == ["A", "a", "z1"]
    # unreadable planted file: same
    target2 = record_dir(ws) / writer_detail_path(ws, "z2")
    target2.write_text("not json")
    assert writer.append(event(id="z2"), detail={"input": "x", "output": "y"})["detail_lost"] is True
    # too large even after cutting: line kept
    big = writer.append(event(id="z3"), detail={"input": "x" * (2 * 1024**2), "output": ""})
    assert big["detail"] is None and big["detail_lost"] is True


def writer_detail_path(ws, eid):
    from orch.collect_execjson import detail_name

    return f"detail/r_8k2m01/{detail_name('r_8k2m01', 'step', eid)}.json"


def test_fifo_planted_as_run_file_does_not_hang(store):
    ws, writer = store
    fifo = record_dir(ws) / "runs/r_8k2m01.jsonl"
    fifo.parent.mkdir(parents=True)
    os.mkfifo(fifo)
    with pytest.raises(RecordRefused):
        writer.append(event())
    assert not (record_dir(ws) / "runs/r_8k2m01.lock").exists()


def test_no_fchmod_still_writes(store, monkeypatch):
    ws, writer = store
    monkeypatch.delattr(record.os, "fchmod")
    assert writer.append(event())
    assert read_run(ws, "r_8k2m01").unwrap()


def test_finished_detail_is_write_once(store):
    ws, writer = store
    done = {"ok": True, "error": None, "ms": 1}
    first = writer.append(
        event(id="w1", via="log", outcome=done), detail={"input": "a", "output": "collector"}
    )
    hook = writer.append(event(id="w1", via="hook", outcome=done), detail={"input": "b", "output": "hook"})
    assert hook is None  # a hook line after the log's is dropped (the log wins) ...
    assert (
        json.loads((record_dir(ws) / first["detail"]).read_text())["output"] == "collector"
    )  # ... and so is its detail
    # the other order: the log line writes its own detail over the hook's
    writer.append(event(id="w3", via="hook", outcome=done), detail={"input": "b", "output": "hook"})
    log = writer.append(event(id="w3", via="log", outcome=done), detail={"input": "a", "output": "collector"})
    assert json.loads((record_dir(ws) / log["detail"]).read_text())["output"] == "collector"
    started = writer.append(event(id="w2"), detail={"input": "a", "output": "early"})
    writer.append(event(id="w2", outcome=done), detail={"input": "a", "output": "final"})
    assert json.loads((record_dir(ws) / started["detail"]).read_text())["output"] == "final"


def _foreign_owner(monkeypatch):
    from types import SimpleNamespace

    real = os.fstat

    def fake(fd):
        info = real(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0:  # only files that already hold data
            return info
        fields = {k: getattr(info, k) for k in dir(info) if k.startswith("st_")}
        fields["st_uid"] = info.st_uid + 1
        return SimpleNamespace(**fields)

    monkeypatch.setattr(record.os, "fstat", fake)


def _hardlink(path, tmp_path, name):
    other = tmp_path / name
    os.link(path, other)
    return other


@pytest.mark.parametrize("how", ["foreign", "hardlink"])
def test_every_read_path_distrusts_foreign_and_hardlinked_files(store, tmp_path, monkeypatch, how):
    ws, writer = store
    done = {"ok": True, "error": None, "ms": 1}
    stored = writer.append(event(id="p1", outcome=done), detail={"input": "i", "output": "o"})
    state = event(id="rs1", kind="run.state", via="core", data={"state": "done"}, text="Done", used=None)
    writer.append(state)
    run_file = record_dir(ws) / "runs/r_8k2m01.jsonl"
    detail_file = record_dir(ws) / stored["detail"]
    name = Path(stored["detail"]).stem
    assert len(read_run(ws, "r_8k2m01").unwrap()) == 2
    if how == "hardlink":
        _hardlink(run_file, tmp_path, "l1")
        _hardlink(detail_file, tmp_path, "l2")
    else:
        _foreign_owner(monkeypatch)
    assert read_run(ws, "r_8k2m01").status == "tampered"
    assert read_run(ws, "r_8k2m01").status == "tampered"
    assert read_detail(ws, "r_8k2m01", name).status == "tampered"
    # a new append over the untrusted run file is refused and writes nothing
    with pytest.raises(RecordRefused):
        writer.append(event(id="p2"))
    # an existing untrusted detail target gives detail_lost for a new event with the same name, line kept
    # (run file untouched: use another run)
    # retention: an unreadable run is never folded, never deleted
    folded = []
    plan = apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, lambda run, evs: folded.append(run))
    assert folded == [] and plan["delete_run"] == []
    assert run_file.exists() and detail_file.exists()


@pytest.mark.parametrize("how", ["foreign", "hardlink"])
def test_store_detail_with_untrusted_existing_target_is_lost(store, tmp_path, monkeypatch, how):
    ws, writer = store
    from orch.collect_execjson import detail_name

    target = record_dir(ws) / f"detail/r_8k2m02/{detail_name('r_8k2m02', 'step', 'q1')}.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            dict(v=1, id="q1", run="r_8k2m02", kind="step", input="a", output="b", truncated=False, hidden=0)
        )
    )
    if how == "hardlink":
        _hardlink(target, tmp_path, "l3")
    else:
        _foreign_owner(monkeypatch)
    kept = writer.append(event(id="q1", run="r_8k2m02"), detail={"input": "x", "output": "y"})
    assert kept is not None and kept["detail"] is None and kept["detail_lost"] is True


@pytest.mark.parametrize("case", VECTORS["reserved_ids"])
def test_reserved_ids(store, case):
    _, writer = store
    value = event(id=case["id"], via=case["via"], run="r_abcdef")
    assert writer.append(value)["id"] == case["stored"]

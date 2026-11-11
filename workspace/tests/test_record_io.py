"""Record I/O redesign regression tests (design sections 9–10).

Consumer test 16 belongs to the separate CLI PR; its marker contract is checked
here without changing or importing that consumer.
"""

import ast
import errno
import json
import os
import random
import re
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from orch import hider, record

ROOT = Path(__file__).resolve().parents[2]
RUN = "r_8k2m01"
DETAIL = {"input": "hello", "output": "world"}
CORE = {
    "_io_error",
    "_io",
    "_parts",
    "_check_info",
    "_check_fd",
    "_reparse",
    "_path_info",
    "_walk",
    "_verify_walk",
    "_open",
    "_close",
    "_read_bytes",
    "_write",
    "_entries",
    "_unlink",
    "_write_new",
    "_size",
    "_rmtree",
    "_lock",
}


def event(**changes):
    value = json.loads((ROOT / "contracts/examples/activity/valid-step-started.json").read_text())
    return dict(value, **{}) | changes


@pytest.fixture
def store(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws, record.RecordWriter(ws, hider=hider.Hider({"key": "a-long-secret-value"}))


def runfile(ws):
    return record.record_dir(ws) / "runs" / (RUN + ".jsonl")


def plant(ws, kind):
    path = runfile(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "link":
        path.symlink_to(ws / "outside")
    elif kind == "hardlink":
        outside = ws / "outside"
        outside.write_text("unchanged")
        os.link(outside, path)
    elif kind == "not_regular":
        os.mkfifo(path)
    return path


def test_01_io_core_is_the_only_fs_user():
    tree = ast.parse(Path(record.__file__).read_text())
    fs = {"open", "mkdir", "unlink", "rmdir", "replace", "scandir", "stat", "lstat", "fstat", "listdir"}
    path_fs = {
        "exists",
        "glob",
        "iterdir",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "is_file",
        "is_dir",
        "is_symlink",
    }
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.ClassDef)) or fn.name in CORE:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id != "open", fn.name
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in path_fs, fn.name
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                        assert node.func.attr not in fs, (fn.name, node.func.attr)


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory descriptor race")
def test_02_symlink_swap_race(store, monkeypatch):
    ws, writer = store
    writer.append(event())
    root = record.record_dir(ws)
    outside = ws / "outside"
    outside.mkdir()
    ready = threading.Event()
    errors = []

    real_mkdir = os.mkdir

    def existing_runs(path, *args, **kwargs):
        if path == "runs":
            raise FileExistsError()
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", existing_runs)

    def swap():
        rng = random.Random(2)
        ready.set()
        for _ in range(2000):
            (root / "runs").rename(root / "parked")
            (root / "runs").symlink_to(outside, target_is_directory=True)
            if rng.randrange(16) == 0:
                time.sleep(0)
            (root / "runs").unlink()
            (root / "parked").rename(root / "runs")

    thread = threading.Thread(target=swap)
    thread.start()
    ready.wait()
    for i in range(20):
        try:
            writer.append(event(id=f"race{i}"))
        except (record.RecordTampered, record.RecordUnavailable) as error:
            errors.append(error)
    thread.join()
    assert not list(outside.iterdir())
    assert all(e.reason in record.TAMPER_REASONS or e.reason in ("missing", "io") for e in errors)


@pytest.mark.parametrize(
    "part",
    [
        ".orch",
        ".orch/record",
        ".orch/record/runs",
        ".orch/record/runs/" + RUN + ".jsonl",
        ".orch/record/runs/" + RUN + ".lock",
        ".orch/record/meta.json",
        ".orch/record/detail/" + RUN,
    ],
)
def test_03_symlink_each_level(store, part):
    ws, writer = store
    target = ws / part
    target.parent.mkdir(parents=True, exist_ok=True)
    outside = ws / "outside"
    outside.mkdir()
    target.symlink_to(outside, target_is_directory=True)
    if "/detail/" in part:
        kept = writer.append(event(), detail=DETAIL)
        assert kept["detail"] is None and kept["detail_lost"]
    else:
        with pytest.raises(record.RecordTampered) as caught:
            writer.append(event(), detail=DETAIL)
        assert caught.value.reason == "link"
        expected = "lock" if part.endswith(".lock") else "meta" if part.endswith("meta.json") else None
        if expected:
            assert caught.value.alert["target"] == expected
    assert not list(outside.iterdir())
    if "runs" in part and not part.endswith(".lock") or part in (".orch", ".orch/record"):
        assert record.read_run(ws, RUN).reason == "link"


def test_04_hardlinks_and_alert(store):
    ws, writer = store
    plant(ws, "hardlink")
    read = record.read_run(ws, RUN)
    assert read.status == "tampered" and read.reason == "hardlink" and read.alert
    with pytest.raises(record.RecordTampered):
        writer.append(event(), detail=DETAIL)
    assert (ws / "outside").read_text() == "unchanged"
    alerts = list((record.record_dir(ws) / "alerts").glob("*.jsonl"))
    assert json.loads(alerts[0].read_text().splitlines()[0])["reason"] == "hardlink"
    runfile(ws).unlink()
    stored = writer.append(event(), detail=DETAIL)
    target = record.record_dir(ws) / stored["detail"]
    os.link(target, ws / "detail-copy")
    assert record.read_detail(ws, RUN, target.stem).reason == "hardlink"


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership")
@pytest.mark.parametrize("target", ["file", "folder"])
def test_05_foreign_owner(store, monkeypatch, target):
    ws, writer = store
    writer.append(event())
    real = os.geteuid()
    original_fstat = os.fstat
    chosen = runfile(ws) if target == "file" else runfile(ws).parent
    chosen_ino = chosen.stat().st_ino

    def selected_owner(fd):
        info = original_fstat(fd)
        fields = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
        # The geteuid patch changes the expected owner; only the selected inode
        # keeps its actual owner, so every other component still passes.
        fields["st_uid"] = real if info.st_ino == chosen_ino else real + 1
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "fstat", selected_owner)
    monkeypatch.setattr(os, "geteuid", lambda: real + 1)
    result = record.read_run(ws, RUN)
    assert result.reason == "foreign_owner"
    assert result.message == record._MESSAGES["tampered"] and result.alert
    with pytest.raises(record.RecordTampered):
        writer.append(event(id="new"))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires FIFO")
@pytest.mark.parametrize("where", ["run", "detail", "meta"])
def test_06_fifo_no_hang(store, where):
    ws, writer = store
    root = record.record_dir(ws)
    if where == "run":
        plant(ws, "not_regular")

        def read():
            return record.read_run(ws, RUN)
    elif where == "meta":
        root.mkdir(parents=True)
        os.mkfifo(root / "meta.json")

        def read():
            return record.read_meta(ws)
    else:
        name = record.detail_name(RUN, "step", event()["id"])
        target = root / "detail" / RUN / (name + ".json")
        target.parent.mkdir(parents=True)
        os.mkfifo(target)

        def read():
            return record.read_detail(ws, RUN, name)

    start = time.monotonic()
    assert read().reason == "not_regular"
    if where == "detail":
        assert writer.append(event(), detail=DETAIL)["detail_lost"]
    else:
        with pytest.raises(record.RecordTampered):
            writer.append(event())
    assert time.monotonic() - start < 2


@pytest.mark.parametrize(
    "tag,refused", [(None, True), (0xA000000C, True), (0xA0000003, True), (0x9000001A, False)]
)
def test_07_reparse_rules_everywhere(store, monkeypatch, tag, refused):
    ws, _ = store
    info = SimpleNamespace(
        st_file_attributes=0x400,
        st_reparse_tag=tag,
        st_mode=stat.S_IFDIR,
        st_uid=os.geteuid() if hasattr(os, "geteuid") else 0,
    )
    monkeypatch.setattr(os, "lstat", lambda *a, **kw: info)
    if refused:
        with pytest.raises(record.RecordTampered, match="Some records"):
            record._path_info(ws, want_dir=True)
    else:
        assert record._path_info(ws, want_dir=True) is info


@pytest.mark.skipif(os.name != "nt", reason="Windows junction integration")
def test_07_windows_junction(store):
    import subprocess

    ws, _ = store
    (ws / ".orch").mkdir()
    outside = ws / "outside"
    outside.mkdir()
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(ws / ".orch/record"), str(outside)], check=True, capture_output=True
    )
    assert record.read_run(ws, RUN).reason == "reparse"


@pytest.mark.parametrize("kind", ["hardlink", "link", "foreign_owner"])
def test_08_untrusted_run_precedes_every_write(store, monkeypatch, kind):
    ws, writer = store
    if kind == "foreign_owner":
        path = runfile(ws)
        path.parent.mkdir(parents=True)
        path.write_text("unchanged")
        real = os.geteuid()
        monkeypatch.setattr(os, "geteuid", lambda: real + 1)
    else:
        plant(ws, kind)
    with pytest.raises(record.RecordTampered):
        writer.append(event(), detail=DETAIL)
    assert not (record.record_dir(ws) / "detail").exists()
    assert not (record.record_dir(ws) / "meta.json").exists()


def test_09_no_broad_catches(store, monkeypatch):
    tree = ast.parse(Path(record.__file__).read_text())
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.ExceptHandler):
                names = (
                    {n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)} if node.type else {"bare"}
                )
                assert "RecordRefused" not in names and "bare" not in names
                assert "OSError" not in names or fn.name in CORE
    ws, writer = store

    def invalid(*args):
        raise record.RecordInvalid()

    monkeypatch.setattr(record, "_store_detail", invalid)
    with pytest.raises(record.RecordInvalid):
        writer.append(event(), detail=DETAIL)
    assert runfile(ws).read_bytes() == b""


def test_10_dedupe_before_detail(store):
    ws, writer = store
    writer.append(event())
    assert writer.append(event(), detail=DETAIL) is None
    assert not (record.record_dir(ws) / "detail").exists()


def test_11_line_failure_removes_new_detail(store, monkeypatch):
    ws, writer = store
    writer.append(event(id="first"))
    real = os.write

    def fail(fd, data):
        if b'"seq":2' in data:
            raise OSError(errno.ENOSPC, "private path")
        return real(fd, data)

    monkeypatch.setattr(os, "write", fail)
    with pytest.raises(record.RecordUnavailable) as caught:
        writer.append(event(), detail=DETAIL)
    assert caught.value.reason == "io"
    assert not list((record.record_dir(ws) / "detail" / RUN).iterdir())


@pytest.mark.parametrize("mode", ["missing", "io", "tampered"])
def test_12_public_read_statuses(store, monkeypatch, mode):
    ws, writer = store
    if mode != "missing":
        writer.append(event())
    if mode == "io":
        real = os.open

        def denied(path, *args, **kwargs):
            if path == ".orch":
                raise PermissionError(errno.EACCES, "private")
            return real(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", denied)
    elif mode == "tampered":
        (ws / ".orch").rename(ws / "parked")
        (ws / ".orch").symlink_to(ws / "parked", target_is_directory=True)
    for result in [
        record.read_run(ws, RUN),
        record.read_detail(ws, RUN, "0" * 32),
        record.read_meta(ws),
        record.list_runs(ws),
    ]:
        assert result.value is None and result.message and result.reason
        assert result.status == ("tampered" if mode == "tampered" else "unavailable")
        with pytest.raises(record.RecordTampered if mode == "tampered" else record.RecordUnavailable):
            result.unwrap()


def test_13_invalid_lines_counted(store):
    ws, writer = store
    writer.append(event())
    with runfile(ws).open("ab") as stream:
        stream.write(b"broken\n")
    read = record.read_run(ws, RUN)
    assert read.status == "ok" and read.skipped == 1 and len(read.value) == 1


def ended(writer, run=RUN):
    return writer.append(
        event(
            run=run,
            id="ended",
            kind="run.state",
            via="core",
            used=None,
            data={"state": "done"},
            at="2020-01-01T00:00:00Z",
        )
    )


def test_14_retention_skips_only_bad_run(store):
    ws, writer = store
    ended(writer)
    ended(writer, "r_other1")
    os.link(runfile(ws), ws / "outside")
    before = runfile(ws).read_bytes()
    folds = []
    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, lambda run, events: folds.append(run))
    assert result["status"] == "tampered" and result["reason"] == "hardlink" and result["alert"]
    assert folds == ["r_other1"] and result["delete_run"] == folds
    assert runfile(ws).read_bytes() == before


def test_15_listing_keeps_symlinks(store):
    ws, _ = store
    plant(ws, "link")
    assert record.list_runs(ws).unwrap() == [RUN]
    assert record.read_run(ws, RUN).status == "tampered"


def test_16_cli_marker_contract():
    schema = json.loads((ROOT / "contracts/cli-answer.schema.json").read_text())
    validator = Draft202012Validator({"$ref": "#/$defs/stream_line", "$defs": schema["$defs"]})
    validator.validate(
        dict(
            type="unavailable",
            cursor="x",
            run=RUN,
            status="ok",
            reason="skipped",
            message="Some lines of this run could not be read and are not shown.",
        )
    )
    assert "tampered" in schema["$defs"]["error"]["properties"]["code"]["enum"]


def test_17_alert_storage_tampered(store):
    ws, writer = store
    plant(ws, "hardlink")
    outside = ws / "alert-outside"
    outside.mkdir()
    (record.record_dir(ws) / "alerts").symlink_to(outside, target_is_directory=True)
    assert record.read_run(ws, RUN).alert["reason"] == "hardlink"
    with pytest.raises(record.RecordTampered) as caught:
        writer.append(event())
    assert caught.value.alert and not list(outside.iterdir())


def test_18_random_detail_names():
    rng = random.Random(18)
    seen = set()
    for i in range(5000):
        eid = str(i) + "".join(rng.choice("Ab/\\..é中 CON:NUL") for _ in range(20))
        name = record.detail_name(RUN, rng.choice(["step", "usage"]), eid)
        assert re.fullmatch(r"[0-9a-f]{32}", name) and name not in seen
        seen.add(name)


def test_19_case_distinct_details(store):
    ws, writer = store
    paths = set()
    for eid in ("Ab", "aB", "AB", "ab"):
        stored = writer.append(event(id=eid), detail=DETAIL)
        path = Path(stored["detail"])
        paths.add(path)
        read = record.read_detail(ws, RUN, path.stem).unwrap()
        assert (read["kind"], read["id"]) == ("step", eid)
    assert len(paths) == 4


@pytest.mark.parametrize("problem", ["collision", "link", "oversize", "io"])
def test_20_detail_failure_keeps_line(store, monkeypatch, problem):
    ws, writer = store
    payload = DETAIL
    name = record.detail_name(RUN, "step", event()["id"])
    target = record.record_dir(ws) / "detail" / RUN / (name + ".json")
    if problem == "collision":
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(dict(run=RUN, kind="usage", id="other")))
    elif problem == "link":
        target.parent.parent.mkdir(parents=True)
        target.parent.symlink_to(ws, target_is_directory=True)
    elif problem == "oversize":
        payload = dict(input="x" * 1024**2, output="")
    else:

        def fail(*args):
            raise record.RecordUnavailable("io")

        monkeypatch.setattr(record, "_write_new", fail)
    kept = writer.append(event(), detail=payload)
    assert kept["detail"] is None and kept["detail_lost"]
    assert record.read_run(ws, RUN).unwrap() == [kept]


def test_21_hider_failure_leaves_nothing(store, monkeypatch):
    ws, writer = store
    monkeypatch.setattr(writer.hider, "hide_text", lambda value: "changed" + value)
    with pytest.raises(record.RecordInvalid):
        writer.append(event(), detail=DETAIL)
    assert not record.record_dir(ws).exists()


def test_22_alert_contract():
    schema = json.loads((ROOT / "contracts/activity.schema.json").read_text())
    validator = Draft202012Validator({"$ref": "#/$defs/record_alert", "$defs": schema["$defs"]})
    for path in (ROOT / "contracts/examples/activity-alert").glob("*.json"):
        assert validator.is_valid(json.loads(path.read_text())) == path.name.startswith("valid-")
    vectors = json.loads((ROOT / "contracts/vectors/activity-v1.json").read_text())
    for case in vectors["integrity"]:
        reason = case["reason"]
        if reason in record.TAMPER_REASONS:
            assert record.RecordTampered(reason).code == case["status"]
        elif reason:
            assert record.RecordUnavailable(reason).reason == reason


def test_23_hook_namespace_and_conflict(store):
    ws, writer = store
    a = writer.append(event(id="r_abcdef:3", via="hook"))
    b = writer.append(event(id="r_abcdef:3", via="log"))
    assert a["id"].startswith("x_") and b["id"] == "r_abcdef:3"
    writer.append(event(id="same", via="hook", outcome=dict(ok=True, error=None, ms=1)))
    later = writer.append(event(id="same", via="log", outcome=dict(ok=False, error="failed", ms=1)))
    assert later["conflict"] is True
    assert len(record.read_run(ws, RUN).unwrap()) == 4
    assert writer.append(event(id="same", via="log", outcome=dict(ok=False, error="failed", ms=1))) is None
    assert writer.append(event(id="same", via="hook", outcome=dict(ok=True, error=None, ms=1))) is None
    assert len(record.read_run(ws, RUN).unwrap()) == 4


@pytest.mark.parametrize("kind", ["denial", "usage"])
def test_24_other_origins_do_not_suppress(store, kind):
    ws, writer = store
    for via in ("hook", "core"):
        assert writer.append(
            event(kind=kind, via=via, outcome=dict(ok=False, error=None, ms=1), data={"tokens_in": 1})
        )
    assert len(record.read_run(ws, RUN).unwrap()) == 2


def test_25_fast_strict_read_and_spool(store, monkeypatch):
    ws, writer = store
    writer.append(event(id="first"))
    sample = event()
    runfile(ws).write_text(
        "".join(json.dumps(dict(sample, id=f"id{i}", seq=i + 1)) + "\n" for i in range(3000))
    )
    start = time.monotonic()
    assert writer.append(event(id="last"))["seq"] == 3001
    assert time.monotonic() - start < 0.05
    lock = record.record_dir(ws) / "runs" / (RUN + ".lock")
    lock.touch()
    monkeypatch.setattr(record, "_LOCK_WAIT", 0.01)
    writer.append(event(id="spooled"), detail=DETAIL)
    pending = record.record_dir(ws) / "pending" / RUN
    assert len(list(pending.iterdir())) == 1
    lock.unlink()
    assert writer.append(event(id="drain"))["seq"] == 3003
    assert not list(pending.iterdir())
    lines = [json.loads(line) for line in runfile(ws).read_text().splitlines()]
    assert [e["id"] for e in lines[-2:]] == ["spooled", "drain"]


@pytest.mark.slow
def test_25_lock_waits_two_seconds(store):
    ws, writer = store
    writer.append(event())
    entered = threading.Event()

    def hold():
        with record._lock(ws, RUN):
            entered.set()
            time.sleep(2.05)

    thread = threading.Thread(target=hold)
    thread.start()
    entered.wait()
    try:
        assert writer.append(event(id="waited"))["seq"] == 2
    finally:
        thread.join()


@pytest.mark.parametrize("bad", [float("nan"), object(), "deep"])
def test_26_bad_detail_and_oversize_data(store, bad):
    ws, writer = store
    if bad == "deep":
        bad = []
        for _ in range(10000):
            bad = [bad]
    kept = writer.append(event(data={"large": "x" * 9000}), detail={"input": bad, "output": ""})
    assert kept["detail_lost"] and kept["detail"] is None and kept["data"] == {"cut": True}
    assert record.read_run(ws, RUN).unwrap() == [kept]


def test_27_retention_rechecks_under_lock(store, monkeypatch):
    ws, writer = store
    ended(writer)
    real = record._lock
    barrier = threading.Barrier(2)
    done = threading.Event()
    errors = []

    def append_late():
        try:
            barrier.wait(timeout=2)
            writer.append(
                event(id="late", kind="run.state", via="core", used=None, data={"state": "working"})
            )
        except Exception as error:
            errors.append(error)
        finally:
            done.set()

    thread = threading.Thread(target=append_late)

    @contextmanager
    def late(workspace, run):
        if threading.current_thread() is not thread:
            barrier.wait(timeout=2)
            assert done.wait(timeout=2)
        with real(workspace, run):
            yield

    monkeypatch.setattr(record, "_lock", late)
    thread.start()
    folds = []
    try:
        result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, lambda r, es: folds.append(r))
    finally:
        thread.join(timeout=2)
    assert not errors and not thread.is_alive()
    assert result["delete_run"] == [] and folds == []
    assert record.read_run(ws, RUN).unwrap()[-1]["id"] == "late"


def test_28_empty_hider_stale_identity_and_torn_line(store):
    ws, writer = store
    with pytest.raises(record.RecordOff):
        record.RecordWriter(ws, hider=hider.Hider({}))
    writer.append(event())
    lock = record.record_dir(ws) / "runs" / (RUN + ".lock")
    lock.touch()
    fd = record._open(ws, ("runs", RUN + ".lock"), "read")
    try:
        lock.unlink()
        lock.write_text("replacement")
        assert record._unlink(ws, ("runs", RUN + ".lock"), expected=fd) is False
        assert lock.read_text() == "replacement"
    finally:
        record._close(fd)
    os.utime(lock, (1, 1))
    with runfile(ws).open("ab") as stream:
        stream.write(b"torn")
    assert writer.append(event(id="after"))["seq"] == 3
    assert b"torn\n{" in runfile(ws).read_bytes()


def test_29_bundled_schema_exact():
    schema = json.loads((ROOT / "contracts/activity.schema.json").read_text())
    assert json.dumps(record._SCHEMA, sort_keys=True) == json.dumps(schema, sort_keys=True)


def test_pending_tampering_is_alerted_and_skipped(store, monkeypatch):
    ws, writer = store
    writer.append(event())
    pending = record.record_dir(ws) / "pending" / RUN
    pending.mkdir(parents=True)
    target = pending / "a.json"
    target.symlink_to(ws / "outside")
    (pending / "b.json").write_text(json.dumps(dict(event=event(id="bad"), payload="{}", default_id=False)))
    assert writer.append(event(id="good"))["seq"] == 2
    assert [e["id"] for e in record.read_run(ws, RUN).unwrap()][-1] == "good"
    assert target.is_symlink()
    alerts = [
        json.loads(line)
        for p in (record.record_dir(ws) / "alerts").glob("*")
        for line in p.read_text().splitlines()
    ]
    assert {a["reason"] for a in alerts} == {"link", "swapped"}


def test_actual_unreadable_directory(store):
    if os.name != "posix" or os.geteuid() == 0:
        pytest.skip("POSIX unprivileged permissions")
    ws, writer = store
    writer.append(event())
    directory = record.record_dir(ws)
    directory.chmod(0)
    try:
        for read in (
            record.read_run(ws, RUN),
            record.list_runs(ws),
            record.read_meta(ws),
            record.read_detail(ws, RUN, "0" * 32),
        ):
            assert read.status == "unavailable" and read.reason == "io"
    finally:
        directory.chmod(0o700)


def test_detail_delete_preflights_all_runs(store):
    ws, writer = store
    a = writer.append(event(), detail=DETAIL)
    b = writer.append(event(run="r_other1"), detail=DETAIL)
    target = record.record_dir(ws) / b["detail"]
    os.link(target, ws / "outside")
    with pytest.raises(record.RecordTampered):
        record.delete_detail(ws, [RUN, "r_other1"])
    assert (record.record_dir(ws) / a["detail"]).exists() and target.exists()

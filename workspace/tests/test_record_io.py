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
from conftest import seal_lines
from jsonschema import Draft202012Validator

from orch import hider, record, record_auth

ROOT = Path(__file__).resolve().parents[2]
RUN = "r_8k2m01"
DETAIL = {"input": "hello", "output": "world"}
CORE = {
    "_io_setup",
    "_try_lock",
    "_release_lock",
    "_lock_check",
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
    "_one_size",
    "_file_size",
    "_rmtree",
    "_rename_aside",
    "_rmdir_empty",
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


def record_auth_home(ws):
    from orch import humanproof

    humanproof.record_key(ws)  # makes the key folder (the fixture creates keys on first use)


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


# Exact call expressions keep arbitrary Path receivers out of the allowlist.
SAFE_ATTRIBUTE_CALLS = {
    "raw.rfind",
    "b''.join",
    "r.get",
    "rows.append",
    "(_json(note) + '\\n').encode",
    "now.isoformat",
    "now.isoformat().replace",
    "' '.join",
    "(_DETAIL_VALIDATOR if detail else _VALIDATOR).is_valid",
    "(_json(alert) + '\\n').encode",
    "(_json(line) + '\\n').encode",
    "(_json(dict(event, detail=None, detail_lost=True)) + '\\n').encode",
    "(_json(event) + '\\n').encode",
    "ReadResult.from_error",
    "_ALERTED.add",
    "_CHANGE_VALIDATOR.is_valid",
    "_DETAIL_VALIDATOR.is_valid",
    "_META_VALIDATOR.is_valid",
    "_json(detail).count",
    "_json(dict(event=event, payload=payload.decode() if payload else None, default_id=default_id)).encode",
    "_json(dict(schema='orch.record/1', since=event['at'], keep_days=90, max_mb=2048)).encode",
    "_json(event).count",
    "_json(event['data']).encode",
    "_json(f).encode",
    "_json(payload).count",
    "_json(wrapped).encode",
    "_read_bytes(fd).splitlines",
    "datetime.fromisoformat",
    "datetime.now",
    "datetime.now(UTC).isoformat",
    "datetime.now(UTC).isoformat().replace",
    "dict.fromkeys",
    "eid.encode",
    "event.get",
    "event.pop",
    "event.update",
    "event['detail'].split",
    "event['outcome'].get",
    "events.append",
    "found.append",
    "hashlib.sha256",
    "hashlib.sha256(b'orch.id.hook/1\\x00' + eid.encode()).hexdigest",
    "hiding._check",
    "hiding.current_hider",
    "json.dumps",
    "json.loads",
    "kept.append",
    "last.get",
    "last.get('data', {}).get",
    "line.encode",
    "line.get",
    "obj.items",
    "old.get",
    "outcome.keys",
    "payload.decode",
    "payload.encode",
    "plan['delete_detail'].append",
    "plan['delete_run'].append",
    "plan['delete_run'].copy",
    "plan[field].append",
    "previous.append",
    "raw.endswith",
    "raw.splitlines",
    "re.fullmatch",
    "re.search",
    "redact(event['outcome']['error']).split",
    "redact(event['text']).split",
    "result.pop",
    "result.update",
    "result['delete_detail'].append",
    "result['delete_run'].append",
    "result['fold_first'].append",
    "runs.append",
    "self._append",
    "self._commit",
    "self._drain",
    "self._drain_valid",
    "self._line",
    "self._prepare_detail",
    "self._serialized",
    "self._spool",
    "self.hider.hide_cut",
    "self.hider.hide_json",
    "self.hider.hide_text",
    "hider.hide_text",
    "hider.leaks",
    "stored.get",
    "super().__init__",
    "time.time_ns",
    "unreadable.append",
    "uuid.uuid4",
    "(head or {}).get",
    "_BODY_VALIDATOR.is_valid",
    "_MESSAGES.get",
    "_SPOOL_NAME.fullmatch",
    "_VERIFIED.clear",
    "_VERIFIED.get",
    "_json(entry).encode",
    "body.setdefault",
    "body.update",
    "hashlib.sha256(whole).digest",
    "hashlib.sha256(whole[:hit[1]]).digest",
    "head.get",
    "hit[3].copy",
    "humanproof.record_head_read",
    "humanproof.record_head_try_write",
    "humanproof.record_key",
    "pending.get",
    "pending.items",
    "re.compile",
    "record_auth.State",
    "record_auth.Verified",
    "record_auth.detail_hash",
    "record_auth.drain_ok",
    "record_auth.finish",
    "record_auth.genesis",
    "record_auth.legacy_split",
    "record_auth.scan",
    "record_auth.seal",
    "record_auth.split",
    "record_auth.spool_mac",
    "record_auth.spool_name",
    "record_auth.spool_name_ok",
    "sealed.rfind",
    "self._move_head",
    "self._reject",
    "state.copy",
    "e.get",
    "humanproof.record_head_state",
    "lines[-1].get",
    "hashlib.sha256(whole[:record_auth.prefix_cut(whole, n)]).hexdigest",
    "raw.strip",
    "record_auth.legacy_prefix",
    "record_auth.prefix_cut",
    "record_auth.start_state",
    "self._sealed_tail",
    "whole.split",
    "gone.append",
    "humanproof.record_head_names",
    "humanproof.record_cutover_ensure",
    "humanproof.record_cutover_read",
    "humanproof.record_reject_names",
    "humanproof.record_rejects_bump",
    "humanproof.record_rejects_read",
    "name.startswith",
    "run.get",
    "raw.split",
    "humanproof.record_cutover_at",
    "humanproof.record_head_carry",
    "humanproof.record_reset_at",
    "carry.get",
    "os.stat",
    "out.add",
    "source.get",
}
SAFE_ATTRIBUTE_VALUES = {
    "busy.alert",
    "error.alert",
    "error.reason",
    "listed.status",
    "listed.value",
    "read.alert",
    "read.message",
    "read.pending",
    "read.reason",
    "read.status",
    "read.value",
    "result.alert",
    "self.alert",
    "self.hider",
    "self.reason",
    "self.status",
    "self.value",
    "self.workspace",
    "stored.created",
    "stored.reason",
    "uuid.uuid4().hex",
    "read.legacy",
    "record_auth.SUFFIX_LEN",
    "stored.hash",
    "verified.changed",
    "verified.events",
    "verified.last_mac",
    "verified.last_seq",
    "verified.reason",
    "verified.removed",
    "view.changed",
    "view.events",
    "view.last_mac",
    "view.last_seq",
    "view.legacy",
    "view.reason",
    "view.removed",
    "view.unchecked",
    "view.status",
    "view.value",
    "self.message",
    "view.before",
    "problem.reason",
    "problem.status",
    "view.rejected",
    "directory.fd",
}
ERROR_BOUNDARIES = {
    "_alert",
    "note_lost",
    "_note",
    "read_run",
    "run_lines",
    "_pending_count",
    "apply_retention",
    "read_detail",
    "_commit",
    "_drain",
    "_drain_valid",
    "_append",
    "read_meta",
    "_read_json",
    "_store_detail",
    "delete_detail",
    "_detail_parts",
    "find_detail_files",
    "ticket_detail_files",
    "delete_detail_files",
    "record_sizes",
    "list_runs",
    "_spool",
    "read_job",
    "list_jobs",
    "append_job",
    "_reject",
    "_sealed_tail",
    "_reject_bad_spool",
    "_reject_entry",
    "_flat_size",
}


SAFE_IMPORTS = set(
    """import errno
import hashlib
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar
from jsonschema import Draft202012Validator, FormatChecker
from orch import hider as hiding
from orch import humanproof, record_auth
from orch.collect_execjson import _hash, detail_name
from orch.errors import Refused
from orch.hider import Hider, NoHiderError
from orch.phone_view import redact
from orch.record_files import MAX_INPUT, file_ok""".splitlines()
)
SAFE_EXCEPTIONS = {
    "ValueError",
    "TypeError",
    "KeyError",
    "UnicodeError",
    "RecursionError",
    "RecordInvalid",
    "RecordTampered",
    "RecordUnavailable",
    "RecordBusy",
    "NoHiderError",
}


def scan_record_source(source):
    sensitive = {"os", "shutil", "io", "builtins", "pathlib", "fcntl", "msvcrt", "_FCNTL", "_MSVCRT"}
    tree = ast.parse(source)
    names = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.extend(n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend(a.asname or a.name.split(".")[0] for a in node.names)
    assert len(names) == len(set(names)), "duplicate top-level names"
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    class Scan(ast.NodeVisitor):
        function = None
        core = False

        def visit_FunctionDef(self, node):
            # Nested functions and lambdas do not inherit an I/O exemption.
            previous = self.function, self.core
            self.function, self.core = node.name, node in tree.body and node.name in CORE
            self.generic_visit(node)
            self.function, self.core = previous

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            previous = self.function, self.core
            self.function, self.core = "<lambda>", False
            self.generic_visit(node)
            self.function, self.core = previous

        def visit_Import(self, node):
            if not self.core:
                assert ast.unparse(node) in SAFE_IMPORTS, ast.unparse(node)

        visit_ImportFrom = visit_Import

        def visit_Name(self, node):
            if not self.core:
                assert node.id not in sensitive | {"__builtins__"}, ast.unparse(node)
                if node.id == "Path":
                    parent = parents[node]
                    assert (
                        isinstance(parent, ast.Call)
                        and parent.func is node
                        or isinstance(parent, ast.AnnAssign)
                        and parent.annotation is node
                        or isinstance(parent, ast.arg)
                        and parent.annotation is node
                        or isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and parent.returns is node
                    ), ast.unparse(parent)

        def visit_Attribute(self, node):
            if not self.core:
                assert ast.unparse(node) in SAFE_ATTRIBUTE_CALLS | SAFE_ATTRIBUTE_VALUES, ast.unparse(node)
            self.generic_visit(node)

        def visit_Call(self, node):
            if not self.core:
                if isinstance(node.func, ast.Attribute):
                    assert ast.unparse(node.func) in SAFE_ATTRIBUTE_CALLS, ast.unparse(node)
                elif isinstance(node.func, ast.Name):
                    if node.func.id in {
                        "open",
                        "getattr",
                        "setattr",
                        "vars",
                        "globals",
                        "locals",
                        "compile",
                        "breakpoint",
                        "eval",
                        "exec",
                        "__import__",
                    }:
                        assert (
                            self.function == "_report"
                            and ast.unparse(node) == "getattr(error, 'target', target)"
                        ), ast.unparse(node)
                    if node.func.id == "Path":
                        assert self.function in {"record_dir", "__init__"}
            self.generic_visit(node)

        def visit_Assign(self, node):
            if ast.unparse(node) == "_FD, _DIR, _NOFOLLOW, _FCNTL, _MSVCRT = _io_setup()":
                return
            if not self.core:
                assert not (isinstance(node.value, ast.Name) and node.value.id == "Path")
            self.generic_visit(node)

        def visit_ExceptHandler(self, node):
            def check(kind):
                if isinstance(kind, ast.Tuple):
                    for item in kind.elts:
                        check(item)
                    return
                assert isinstance(kind, ast.Name), ast.unparse(node)
                assert kind.id not in {"Exception", "BaseException", "Refused", "RecordRefused"}
                if not self.core:
                    assert kind.id in SAFE_EXCEPTIONS, kind.id
                if kind.id in {"RecordTampered", "RecordUnavailable"}:
                    assert self.core or self.function in ERROR_BOUNDARIES, self.function

            check(node.type)
            self.generic_visit(node)

    Scan().visit(tree)


def test_01_io_core_is_the_only_fs_user():
    scan_record_source(Path(record.__file__).read_text())


@pytest.mark.parametrize(
    "source",
    [
        'getattr(record_dir(ws), "unlink")()',
        'getattr(import_module("os"), "remove")(p)',
        'operator.methodcaller("unlink")',
        'vars(__builtins__)["open"]',
        "E = OSError\ntry:\n    pass\nexcept E:\n    pass",
        "def _open():\n    pass\ndef _open():\n    os.remove(p)",
        *[
            f"{name}()"
            for name in (
                "setattr",
                "globals",
                "locals",
                "compile",
                "breakpoint",
                "eval",
                "exec",
                "__import__",
            )
        ],
        "import operator",
        "from importlib import import_module",
        "(path / 'x').unlink()",
        "os.remove(p)",
        "os.path.isfile(p)",
        "_o = os.open\n_o('x')",
        "f = path.unlink\nf()",
        "alias = (Path,)",
        "import os as x",
        "from os import open",
        "getattr(os, 'open')('x')",
        "f = lambda: os.remove(p)",
        "async def evil():\n    os.remove(p)",
        *[
            f"try:\n    pass\nexcept {kind}:\n    pass"
            for kind in (
                "Refused",
                "RecordRefused",
                "Exception",
                "BaseException",
                "FileNotFoundError",
                "PermissionError",
                "IOError",
                "EnvironmentError",
                "errors.Custom",
                "(ValueError, OSError)",
                "RecordTampered",
                "RecordUnavailable",
            )
        ],
    ],
)
def test_allowlist_scanner_rejects_planted_evil(source):
    with pytest.raises(AssertionError):
        scan_record_source(source)


def test_allowlist_scanner_accepts_clean_source():
    scan_record_source("def clean(value):\n    return len(value)\n")


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
    elif part == ".orch":
        # a linked .orch folder holds no local id orch may read: no key, no recording, nothing written
        with pytest.raises(record.RecordOff):
            writer.append(event(), detail=DETAIL)
    else:
        with pytest.raises(record.RecordTampered) as caught:
            writer.append(event(), detail=DETAIL)
        assert caught.value.reason == "link"
        expected = "lock" if part.endswith(".lock") else "meta" if part.endswith("meta.json") else None
        if expected:
            assert caught.value.alert["target"] == expected
    assert [p.name for p in outside.iterdir() if p.name != ".local-id"] == []  # only the workspace id
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
    assert record.read_detail(ws, RUN, target.stem, line_id=stored["id"]).reason == "hardlink"


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

    from orch import humanproof

    key = humanproof.record_key(ws)  # the key is resolved before the owner is faked (the guarded home
    # is not what this test is about); an own patcher: the record-key fixture patches the same name
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(humanproof, "record_key", lambda *a, **k: key)
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
        first = writer.append(event(), detail=DETAIL)
        name = record.detail_name(RUN, "step", event()["id"], event()["ticket"])
        target = root / "detail" / RUN / (name + ".json")
        target.unlink()
        os.mkfifo(target)

        def read():
            return record.read_detail(ws, RUN, name, line_id=first["id"])

    start = time.monotonic()
    assert read().reason == "not_regular"
    if where == "detail":
        done = dict(ok=True, error=None, ms=1)
        assert writer.append(event(outcome=done), detail=DETAIL)["detail_lost"]
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
    scan_record_source(Path(record.__file__).read_text())
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
    record_auth_home(ws)  # a clean guarded home: only then is "no such run" a plain "missing"
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
        record.read_detail(ws, RUN, "0" * 32, line_id="x"),
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
    assert read.status == "ok" and read.changed == 1 and read.reason == "content" and len(read.value) == 1


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


@pytest.mark.parametrize("how", ["fifo", "link", "hardlink"])
def test_retention_is_not_vetoed_by_a_planted_detail_file(store, how):
    """R1: a planted FIFO, link or hardlink in an ended run's detail folder does not make retention refuse
    that run (its real detail would outlive retention): the real detail and the run's lines go, the planted
    file stays (nothing outside changes) and is reported."""
    if how == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("requires FIFO")
    ws, writer = store
    line = writer.append(event(), detail=DETAIL)
    ended(writer)
    planted = record.record_dir(ws) / "detail" / RUN / ("f" * 32 + ".json")
    (ws / "outside").write_text("unchanged")
    if how == "fifo":
        os.mkfifo(planted, 0o600)
    elif how == "link":
        planted.symlink_to(ws / "outside")
    else:
        os.link(ws / "outside", planted)
    folds = []
    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, lambda run, events: folds.append(run))
    assert folds == [RUN] and result["delete_detail"] == [RUN] and result["delete_run"] == [RUN]
    assert not (record.record_dir(ws) / line["detail"]).exists() and not runfile(ws).exists()
    assert planted.is_symlink() or planted.exists()
    assert (ws / "outside").read_text() == "unchanged"
    alerts = [
        json.loads(x)
        for day in (record.record_dir(ws) / "alerts").glob("*.jsonl")
        for x in day.read_text().splitlines()
    ]
    reason = {"fifo": "not_regular", "link": "link", "hardlink": "hardlink"}[how]
    assert (reason, RUN, "retention") in {(x.get("reason"), x.get("run"), x.get("seen_by")) for x in alerts}


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
        kind = rng.choice(["step", "usage"])
        name = record.detail_name(RUN, kind, eid, rng.choice(["t_aaaaaa", "t_bbbbbb"]))
        assert re.fullmatch(r"[0-9a-f]{32}", name) and name not in seen
        seen.add(name)
        assert record.detail_name(RUN, kind, eid, None) is None  # no ticket: no detail file (I4)


def test_19_case_distinct_details(store):
    ws, writer = store
    paths = set()
    for eid in ("Ab", "aB", "AB", "ab"):
        stored = writer.append(event(id=eid), detail=DETAIL)
        path = Path(stored["detail"])
        paths.add(path)
        read = record.read_detail(ws, RUN, path.stem, line_id=eid).unwrap()
        assert (read["kind"], read["id"]) == ("step", eid)
    assert len(paths) == 4


def test_19b_detail_name_binds_the_ticket(store):
    """I4: the file name covers the ticket. A file whose stored ticket was changed no longer matches its name,
    and a read for a line of another ticket is refused: both swapped."""
    ws, writer = store
    stored = writer.append(event(id="t1"), detail=DETAIL)
    name = Path(stored["detail"]).stem
    assert name == record.detail_name(RUN, "step", "t1", event()["ticket"])
    assert name != record.detail_name(RUN, "step", "t1", "t_other9")
    assert (
        record.read_detail(ws, RUN, name, line_id="t1", ticket=event()["ticket"]).unwrap()["ticket"]
        == event()["ticket"]
    )
    other = record.read_detail(ws, RUN, name, line_id="t1", ticket="t_other9")
    assert (other.status, other.reason) == ("tampered", "swapped")
    target = record.record_dir(ws) / stored["detail"]
    target.write_text(json.dumps(dict(json.loads(target.read_text()), ticket="t_other9")))
    changed = record.read_detail(ws, RUN, name, line_id="t1")
    assert (changed.status, changed.reason) == ("tampered", "swapped")


@pytest.mark.parametrize("problem", ["link", "oversize", "io"])
def test_20_detail_failure_keeps_line(store, monkeypatch, problem):
    ws, writer = store
    payload = DETAIL
    name = record.detail_name(RUN, "step", event()["id"], event()["ticket"])
    target = record.record_dir(ws) / "detail" / RUN / (name + ".json")
    if problem == "link":
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


def test_planted_detail_file_at_the_name_is_replaced_and_hashed(store):
    """A file at the name no verified line carries the hash of is an orphan or planted: replaced atomically,
    and the new line authenticates the file that is really there (design 6)."""
    ws, writer = store
    name = record.detail_name(RUN, "step", event()["id"], event()["ticket"])
    target = record.record_dir(ws) / "detail" / RUN / (name + ".json")
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(dict(run=RUN, kind="usage", id="other", ticket=event()["ticket"])))
    kept = writer.append(event(), detail=DETAIL)
    assert kept["detail"] and kept["detail_hash"] == record_auth.detail_hash(target.read_bytes())
    assert json.loads(target.read_text())["input"] == "hello"


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
    # agreeing lines of one call: the log line replaces the hook line, a later hook line is dropped
    writer.append(event(id="agree", via="hook"))
    replacing = writer.append(event(id="agree", via="log"))
    assert replacing["replaced_hook"] is True and "conflict" not in replacing
    assert writer.append(event(id="agree", via="hook", text="Something else")) is None
    assert [e["via"] for e in record.read_run(ws, RUN).unwrap() if e["id"] == "agree"] == ["log"]


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
    runfile(ws).write_bytes(seal_lines(ws, RUN, [dict(sample, id=f"id{i}") for i in range(3000)]))
    start = time.monotonic()
    assert writer.append(event(id="last"))["seq"] == 3001
    assert time.monotonic() - start < 0.5  # shared CI runners; W2b makes this structural
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
    def late(workspace, run, wait=None):
        if threading.current_thread() is not thread:
            barrier.wait(timeout=2)
            assert done.wait(timeout=2)
        with real(workspace, run, wait) as check_lock:
            yield check_lock

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
    assert writer.append(event(id="after"))["seq"] == 2  # the cut-off line is no line of the chain
    assert b"torn\n{" in runfile(ws).read_bytes()


def test_29_bundled_schema_exact():
    schema = json.loads((ROOT / "contracts/activity.schema.json").read_text())
    assert json.dumps(record._SCHEMA, sort_keys=True) == json.dumps(schema, sort_keys=True)


def test_pending_tampering_is_alerted_and_skipped(store, monkeypatch):
    ws, writer = store
    writer.append(event())
    pending = record.record_dir(ws) / "pending" / RUN
    pending.mkdir(parents=True)
    target = pending / ("0" * 19 + "1_" + "a" * 32 + ".json")
    target.symlink_to(ws / "outside")
    planted = pending / ("0" * 19 + "2_" + "b" * 32 + ".json")  # orch's name, but no MAC: planted
    planted.write_text(json.dumps(dict(event=event(id="bad"), payload="{}", default_id=False)))
    assert writer.append(event(id="good"))["seq"] == 2
    assert not planted.exists()  # deleted by its exact path, never committed (M4)
    assert [e["id"] for e in record.read_run(ws, RUN).unwrap()][-1] == "good"
    assert not target.is_symlink()  # a planted link at orch's name is removed too (never followed)
    alerts = [
        json.loads(line)
        for p in (record.record_dir(ws) / "alerts").glob("*")
        for line in p.read_text().splitlines()
    ]
    assert {a["reason"] for a in alerts} == {"content"}  # a name without its proof is refused unread


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
            record.read_detail(ws, RUN, "0" * 32, line_id="x"),
        ):
            assert read.status == "unavailable" and read.reason == "io"
    finally:
        directory.chmod(0o700)


def test_detail_delete_preflights_all_run_folders(store):
    """A run's detail FOLDER that is a link refuses before anything is deleted, also another run's detail."""
    ws, writer = store
    a = writer.append(event(), detail=DETAIL)
    b = writer.append(event(run="r_other1"), detail=DETAIL)
    folder = record.record_dir(ws) / "detail" / "r_other1"
    folder.rename(ws / "moved")
    folder.symlink_to(ws / "moved", target_is_directory=True)
    with pytest.raises(record.RecordTampered):
        record.delete_detail(ws, [RUN, "r_other1"])
    assert (record.record_dir(ws) / a["detail"]).exists()
    assert (ws / "moved" / Path(b["detail"]).name).exists() and folder.is_symlink()


@pytest.mark.parametrize("how", ["hardlink", "link", "fifo"])
def test_detail_delete_skips_only_the_unsafe_file(store, how):
    """R1: a single detail FILE that is not safe (planted hardlink, link or FIFO) is reported and stays; the
    run's other detail and the other runs' detail go (no veto of retention), and nothing outside changes."""
    if how == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("requires FIFO")
    ws, writer = store
    a = writer.append(event(), detail=DETAIL)
    a2 = writer.append(event(id="second"), detail=DETAIL)
    writer.append(event(run="r_other1"), detail=DETAIL)
    target = record.record_dir(ws) / a["detail"]
    if how == "hardlink":
        os.link(target, ws / "outside")
    else:
        target.unlink()
        (ws / "outside").write_text("unchanged")
        target.symlink_to(ws / "outside") if how == "link" else os.mkfifo(target, 0o600)
    before = (ws / "outside").read_bytes()
    record.delete_detail(ws, [RUN, "r_other1"], seen_by="retention")
    assert target.exists() or target.is_symlink()  # the unsafe file stays
    assert not (record.record_dir(ws) / a2["detail"]).exists()
    assert not (record.record_dir(ws) / "detail" / "r_other1").exists()
    assert (ws / "outside").read_bytes() == before
    alerts = [
        json.loads(line)
        for day in (record.record_dir(ws) / "alerts").glob("*.jsonl")
        for line in day.read_text().splitlines()
    ]
    reason = {"hardlink": "hardlink", "link": "link", "fifo": "not_regular"}[how]
    assert {(x["reason"], x["run"], x["seen_by"]) for x in alerts} == {(reason, RUN, "retention")}


def test_live_aged_lock_never_allows_second_writer(store, monkeypatch):
    ws, writer = store
    writer.append(event(id="initial"))
    acquired, release = threading.Event(), threading.Event()

    def hold():
        with record._lock(ws, RUN):
            acquired.set()
            assert release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert acquired.wait(5)
        lock = runfile(ws).with_suffix(".lock")
        os.utime(lock, (time.time() - 31, time.time() - 31))
        monkeypatch.setattr(record, "_LOCK_WAIT", 0.02)
        result = writer.append(event(id="waiting"))
        assert result["pending"] is True and result["seq"] is None
        assert len(runfile(ws).read_text().splitlines()) == 1
    finally:
        release.set()
        thread.join(5)


def test_read_run_reports_pending_count(store, monkeypatch):
    ws, writer = store
    writer.append(event())
    monkeypatch.setattr(record, "_LOCK_WAIT", 0)
    with record._lock(ws, RUN):
        writer.append(event(id="waiting"))
    read = record.read_run(ws, RUN)
    assert (read.status, read.reason, read.pending) == ("ok", "pending", 1)
    schema = record._SCHEMA
    Draft202012Validator({"$ref": "#/$defs/read_status", "$defs": schema["$defs"]}).validate(
        dict(run=RUN, status=read.status, reason=read.reason, pending=read.pending, message=read.message)
    )


def test_retention_skips_pending_run_and_other_runs_proceed(store):
    ws, writer = store
    for run in (RUN, "r_other1"):
        writer.append(event(run=run, kind="run.state", via="core", used=None, data={"state": "done"}))
    writer._spool(event(id="waiting"), None, False)
    folds = []
    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, lambda r, es: folds.append(r))
    assert (result["status"], result["reason"]) == ("unavailable", "pending")
    assert folds == ["r_other1"]
    assert runfile(ws).exists()
    assert list((record.record_dir(ws) / "pending" / RUN).iterdir())


def test_retention_preflights_pending_folder(store):
    ws, writer = store
    writer.append(event(kind="run.state", via="core", used=None, data={"state": "done"}))
    pending = record.record_dir(ws) / "pending"
    pending.mkdir()
    (pending / RUN).symlink_to(ws, target_is_directory=True)
    folds = []
    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, lambda r, es: folds.append(r))
    assert result["status"] == "tampered"
    assert not folds and runfile(ws).exists()


@pytest.mark.parametrize("outcome", ["garbage", {}, {"ok": True}, [1]])
def test_strict_read_skips_garbage_outcome_before_hook_append(store, outcome):
    ws, writer = store
    writer.append(event(id="initial"))
    bad = event(id="same", via="hook", outcome=outcome)
    with runfile(ws).open("a") as stream:
        stream.write(json.dumps(bad) + "\n")
    assert writer.append(event(id="same", via="hook", outcome={"ok": True, "error": None, "ms": None}))
    assert record.read_run(ws, RUN).changed == 1


def test_read_run_counts_foreign_run_as_changed(store):
    ws, writer = store
    writer.append(event())
    with runfile(ws).open("a") as stream:
        stream.write(json.dumps(event(run="r_other1")) + "\n")
    read = record.read_run(ws, RUN)
    assert read.changed == 1 and len(read.unwrap()) == 1


def test_spool_receipt_has_no_placeholder_default_id(store):
    _, writer = store
    receipt = writer._spool(event(), None, True)
    assert receipt["pending"] is True and receipt["seq"] is None and "id" not in receipt


@pytest.mark.parametrize("seen_by", [None, "retention", "writer"])
def test_delete_detail_alert_uses_callers_role(store, seen_by):
    ws, writer = store
    writer.append(event(), detail=DETAIL)
    folder = record.record_dir(ws) / "detail" / RUN  # a linked run folder refuses (a single file is skipped)
    folder.rename(ws / "moved")
    folder.symlink_to(ws / "moved", target_is_directory=True)
    with pytest.raises(record.RecordTampered) as caught:
        record.delete_detail(ws, [RUN], **({"seen_by": seen_by} if seen_by else {}))
    assert caught.value.alert["seen_by"] == (seen_by or "cli")


def test_tampered_pending_alert_targets_folder(store):
    ws, writer = store
    writer.append(event())
    pending = record.record_dir(ws) / "pending" / RUN
    pending.mkdir(parents=True)
    (pending / "bad.json").write_text("{}")
    writer.append(event(id="next"))
    alerts = [
        json.loads(line)
        for path in (record.record_dir(ws) / "alerts").iterdir()
        for line in path.read_text().splitlines()
    ]
    assert alerts and all(alert["target"] == "folder" for alert in alerts)


def test_pending_first_write_is_visible_without_run_file(store):
    ws, writer = store
    writer._spool(event(), None, False)
    read = record.read_run(ws, RUN)
    assert (read.status, read.reason, read.pending, read.value) == ("ok", "pending", 1, [])


def test_fallback_lock_refreshes_mtime(store, monkeypatch):
    ws, _ = store
    monkeypatch.setattr(record, "_FCNTL", None)
    monkeypatch.setattr(record, "_MSVCRT", None)
    with record._lock(ws, RUN) as check_lock:
        lock = runfile(ws).with_suffix(".lock")
        os.utime(lock, (time.time() - 31, time.time() - 31))
        check_lock()
        assert time.time() - lock.stat().st_mtime < 2


def test_retention_rechecks_lock_identity_after_fold(store, monkeypatch):
    ws, writer = store
    writer.append(event(), detail=DETAIL)
    ended(writer)
    monkeypatch.setattr(record, "_FCNTL", None)
    monkeypatch.setattr(record, "_MSVCRT", None)

    def fold(run, events):
        lock = runfile(ws).with_suffix(".lock")
        lock.rename(lock.with_suffix(".old"))
        lock.touch()

    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, fold)
    assert result["status"] == "tampered" and result["reason"] == "swapped"
    assert (record.record_dir(ws) / "detail" / RUN).exists()
    assert runfile(ws).exists()


def test_retention_rechecks_pending_after_preflight(store, monkeypatch):
    ws, writer = store
    ended(writer)
    original = record._pending_preflight

    def preflight(workspace, run):
        writer._spool(event(id="late"), None, False)
        return original(workspace, run)

    monkeypatch.setattr(record, "_pending_preflight", preflight)
    folds = []
    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, lambda r, es: folds.append(r))
    assert (result["status"], result["reason"]) == ("unavailable", "pending")
    assert not folds and runfile(ws).exists()


@pytest.mark.parametrize("code", [errno.ENOLCK, errno.EOPNOTSUPP, errno.ENOTSUP])
def test_unsupported_flock_falls_back_and_cleans_lock(store, monkeypatch, code):
    ws, writer = store

    def unsupported(*args):
        raise OSError(code, "unsupported")

    monkeypatch.setattr(record, "_FCNTL", SimpleNamespace(flock=unsupported, LOCK_EX=2, LOCK_NB=4))
    assert writer.append(event())["seq"] == 1
    lock = runfile(ws).with_suffix(".lock")
    assert not lock.exists()
    with record._lock(ws, RUN) as check_lock:
        os.utime(lock, (1, 1))
        check_lock()
        assert time.time() - lock.stat().st_mtime < 2
    assert not lock.exists()


@pytest.mark.parametrize("step", ["_try_lock", "_lock_check", "_check_fd", "body"])
def test_failure_after_lock_creation_removes_lock(store, monkeypatch, step):
    ws, writer = store
    writer.append(event())

    def fail(*args, **kwargs):
        # Directory checks happen before creation; fail only once the lock exists.
        if runfile(ws).with_suffix(".lock").exists():
            raise RuntimeError("injected failure")

    if step != "body":
        monkeypatch.setattr(record, step, fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        with record._lock(ws, RUN):
            fail()
    assert not runfile(ws).with_suffix(".lock").exists()


def test_first_lock_check_retries_swapped_name(store, monkeypatch):
    ws, _ = store
    original = record._lock_check
    calls = []

    def check(workspace, rel, fd, **kwargs):
        calls.append(fd)
        if len(calls) == 1:
            lock = runfile(ws).with_suffix(".lock")
            lock.rename(lock.with_suffix(".old"))
            lock.touch()
            os.utime(lock, (1, 1))
        return original(workspace, rel, fd, **kwargs)

    monkeypatch.setattr(record, "_lock_check", check)
    with record._lock(ws, RUN):
        assert len(calls) == 2
    assert not runfile(ws).with_suffix(".lock").exists()


@pytest.mark.parametrize("counts", [(1, 0), (0, 1)])
def test_read_run_reports_pending_before_or_after_parse(store, monkeypatch, counts):
    ws, writer = store
    writer.append(event())
    values = iter(counts)
    monkeypatch.setattr(record, "_pending_count", lambda *args: next(values))
    read = record.read_run(ws, RUN)
    assert (read.status, read.reason, read.pending) == ("ok", "pending", 1)
    assert read.message == record._MESSAGES["pending"]


def test_retention_post_fold_pending_skips_all_deletion_and_fold_is_idempotent(store):
    ws, writer = store
    writer.append(event(), detail=DETAIL)
    ended(writer)
    jobs = record.record_dir(ws) / "jobs" / RUN
    jobs.mkdir(parents=True)
    (jobs / "job").write_text("keep")
    detail = record.record_dir(ws) / "detail" / RUN
    sink, calls = {}, []

    def fold(run, events):
        calls.append(run)
        sink[run] = len(events)  # Replace this run's contribution on retry.
        if len(calls) == 1:
            writer._spool(event(id="late"), None, False)

    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, fold)
    assert (result["status"], result["reason"]) == ("unavailable", "pending")
    assert result["delete_run"] == result["delete_detail"] == []
    assert runfile(ws).exists() and detail.exists() and (jobs / "job").read_text() == "keep"
    for path in (record.record_dir(ws) / "pending" / RUN).iterdir():
        path.unlink()
    first_count = sum(sink.values())
    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, fold)
    assert result["delete_run"] == [RUN]
    assert calls == [RUN, RUN] and sum(sink.values()) == first_count


@pytest.mark.parametrize("target", ["detail", "jobs"])
def test_retention_checks_lock_immediately_before_deletion(store, monkeypatch, target):
    ws, writer = store
    writer.append(event(), detail=DETAIL)
    ended(writer)
    original_count, original_delete = record._pending_count, record.delete_detail
    lost = False

    @contextmanager
    def lock(*args):
        def check():
            if lost:
                raise record.RecordTampered("swapped")

        yield check

    def count(*args):
        nonlocal lost
        value = original_count(*args)
        if folded and target == "detail":
            lost = True
        return value

    def delete(*args, **kwargs):
        nonlocal lost
        original_delete(*args, **kwargs)
        if target == "jobs":
            lost = True

    folded = []
    jobs = record.record_dir(ws) / "jobs" / RUN
    jobs.mkdir(parents=True)
    monkeypatch.setattr(record, "_lock", lock)
    monkeypatch.setattr(record, "_pending_count", count)
    monkeypatch.setattr(record, "delete_detail", delete)
    result = record.apply_retention(ws, "2030-01-01T00:00:00Z", 1, 1, lambda *args: folded.append(RUN))
    assert result["reason"] == "swapped"
    assert jobs.exists() and runfile(ws).exists()
    if target == "detail":
        assert (record.record_dir(ws) / "detail" / RUN).exists()


# --- G1 M1: the writer's view of the run file is the reader's view ---
def test_a_planted_invalid_log_line_does_not_make_the_writer_drop_the_real_line(store):
    ws, writer = store
    writer.append(event(id="first"))
    # schema-invalid (no `text`, `at`, ...) but with the right seq and the id of the next real line
    planted = {"run": RUN, "seq": 2, "id": "toolu_next", "kind": "step", "outcome": None, "via": "log"}
    with runfile(ws).open("a") as f:
        f.write(json.dumps(planted) + "\n")
    stored = writer.append(event(id="toolu_next", via="log"))
    assert stored is not None and stored["seq"] == 2  # the chain's seq: a planted line shifts nothing
    assert [e["id"] for e in record.read_run(ws, RUN).unwrap()] == ["first", "toolu_next"]


def test_a_planted_wrong_seq_line_is_not_trusted_by_the_writer(store):
    ws, writer = store
    writer.append(event(id="first"))
    planted = dict(event(id="toolu_next", via="log"), run=RUN, seq=10**18)
    with runfile(ws).open("a") as f:
        f.write(json.dumps(planted) + "\n")
    stored = writer.append(event(id="toolu_next", via="log"))
    assert stored is not None and stored["seq"] == 2


def test_a_planted_huge_id_does_not_move_the_collectors_seq_start(store):
    from orch import run_record

    ws, writer = store
    writer.append(event(id="first"))
    writer.append(
        event(id=f"{RUN}:999999999999999999", via="log")
    )  # a line that passes every check but its id
    with runfile(ws).open("a") as f:
        f.write(json.dumps(dict(event(id="x"), run=RUN, seq=10**18)) + "\n")
    seq, _ = run_record._so_far(ws, RUN)
    assert seq < 100
    alerts = "".join(p.read_text() for p in (record.record_dir(ws) / "alerts").glob("*.jsonl"))
    assert '"reason":"content"' in alerts


def test_ids_that_ran_ahead_by_dropped_events_stay_numbered_after_many_turns(store):
    from orch import run_record

    ws, writer = store
    # three turns that each dropped 600 events: the id counter runs 600 ahead of the seqs every time
    for n, id_no in enumerate((1, 601, 1201, 1801), 1):
        assert writer.append(event(id=f"{RUN}:{id_no}", via="log"))["seq"] == n
    seq, _ = run_record._so_far(ws, RUN)
    assert seq == 1801  # the next id-less line gets 1802: new, so the writer does not drop it
    assert not (record.record_dir(ws) / "alerts").exists()
    with runfile(ws).open("a") as f:
        f.write(json.dumps(dict(event(id=f"{RUN}:{10**18}"), run=RUN, seq=5)) + "\n")
    assert run_record._so_far(ws, RUN)[0] == 1801


def test_a_planted_line_with_another_id_cannot_decide_about_a_detail_file(store):
    ws, writer = store
    started = writer.append(event(id="toolu_d"), detail=DETAIL)
    planted = dict(started, id="toolu_other", seq=2, outcome=dict(ok=True, error=None, ms=1), via="hook")
    with runfile(ws).open("a") as f:
        f.write(json.dumps(planted) + "\n")
    finished = writer.append(
        event(id="toolu_d", outcome=dict(ok=True, error=None, ms=2)),
        detail={"input": "new-input", "output": "new-output"},
    )
    assert finished["detail"] == started["detail"]
    assert "new-output" in (record.record_dir(ws) / started["detail"]).read_text()


def test_planted_helper_names_do_not_crash_or_skew_the_collector(store):
    from orch import run_record

    ws, writer = store
    writer.append(event(id="first"))
    writer.append(event(id="p1", via="log", agent="h_3", parent="main"))
    with runfile(ws).open("a") as f:
        for n, agent in enumerate(("h_5", "h_" + "9" * 5000, "h_99999999", "h_" + "٣" * 3), 3):
            f.write(json.dumps(dict(event(id=f"p{n}"), run=RUN, seq=n, via="log", agent=agent)) + "\n")
    assert run_record._so_far(ws, RUN)[1] == 3


def test_a_planted_line_of_another_ticket_cannot_decide_about_a_detail_file(store):
    ws, writer = store
    started = writer.append(event(id="toolu_d"), detail=DETAIL)
    planted = dict(started, ticket="t_other1", via="core", seq=2, outcome=dict(ok=True, error=None, ms=1))
    with runfile(ws).open("a") as f:
        f.write(json.dumps(planted) + "\n")
    writer.append(
        event(id="toolu_d", outcome=dict(ok=True, error=None, ms=2)),
        detail={"input": "new-input", "output": "new-output"},
    )
    assert "new-output" in (record.record_dir(ws) / started["detail"]).read_text()

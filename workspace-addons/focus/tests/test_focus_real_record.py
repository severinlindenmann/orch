"""Focus against REAL records: a run is written by the real record writer (workspace package), read back through the
real `orch record tail --json`, and shaped by Focus exactly as the page gets it. No fixture of the files shape.

Everything runs in a temp folder under ~/.orch-test through `env -i`; needs `uv` (skipped without it)."""

import json
import os
import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from orch_focus.board import Board
from orch_focus.livecards import same_file
from orch_focus.record import RecordFeed, file_ok

REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO / "workspace"
RUN, TICKET = "r_real0001", "t_real0001"
pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to run the workspace package")

# (id, used kind/name, text, files as handed to the writer). Some are bad on purpose: the writer drops them.
STEPS = [
    ("toolu_a1", "Read", "Read budget-2026.xlsx", ["budget-2026.xlsx"]),
    (
        "toolu_a2",
        "Edit",
        "Changed offsite/agenda.docx",
        ["offsite/agenda.docx", "/etc/passwd", "../x", "a\\b"],
    ),
    ("toolu_a3", "Bash", "Ran the checks", []),  # a step without files
    ("toolu_a4", "Write", "Wrote notes", ["notes/ünï.txt", "x" * 261, "KEYVALUE-abc123XYZ-secret.txt"]),
]


def env(home: Path) -> dict:
    return {"HOME": str(home), "ORCH_HOME": str(home / ".orch-tool"), "PATH": os.environ["PATH"],
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR") or str(Path.home() / ".cache" / "uv")}  # fmt: skip


@pytest.fixture(scope="module")
def real(request):
    base = Path.home() / ".orch-test"
    base.mkdir(exist_ok=True)
    home = Path(__import__("tempfile").mkdtemp(prefix="focus-real-", dir=base))
    request.addfinalizer(
        lambda: shutil.rmtree(home, ignore_errors=True) if "focus-real-" in home.name else None
    )
    ws = home / "ws"
    (ws / ".orch").mkdir(parents=True)
    writer = textwrap.dedent(
        f"""
        import json, sys
        from pathlib import Path
        from orch import hider
        from orch.record import RecordWriter
        w = RecordWriter(Path({str(ws)!r}), hider=hider.Hider({{"k": "KEYVALUE-abc123XYZ-secret"}}))
        for i, (sid, name, text, files) in enumerate(json.loads(sys.argv[1]), 1):
            base = {{"v": 1, "seq": i, "run": {RUN!r}, "session": None, "agent": "main", "parent": None,
                    "at": "2026-11-16T09:12:%02dZ" % i, "ticket": {TICKET!r}, "harness": "claude", "coverage": "full",
                    "id": sid, "via": "log", "kind": "step", "text": text,
                    "used": {{"kind": "tool", "name": name, "action": None, "source": "builtin", "version": None}},
                    "detail": None, "files": files}}
            w.append({{**base, "outcome": None}})
            w.append({{**base, "seq": 100 + i, "outcome": {{"ok": True, "error": None, "ms": 5}}}})
        """
    )
    run = ["env", "-i", *[f"{k}={v}" for k, v in env(home).items()], "uv", "run", "--project", str(WORKSPACE)]
    subprocess.run([*run, "python", "-I", "-c", writer, json.dumps(STEPS)], check=True, cwd=ws, timeout=300)
    shim = home / "orch"  # Focus's orch command: the real one, in the workspace environment
    shim.write_text("#!/bin/sh\nexec " + " ".join(run) + ' python -I -m orch "$@"\n')
    shim.chmod(0o755)
    return ws, shim


def lines(real_ws, *args):
    ws, shim = real_ws
    p = subprocess.run(
        [str(shim), "record", *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ws,
        timeout=120,
    )
    assert p.returncode == 0, p.stderr
    return [json.loads(x) for x in p.stdout.splitlines()]


def feed_events(real_ws, want):
    ws, shim = real_ws
    feed = RecordFeed(ws, str(shim), RUN, TICKET)
    got, end = [], time.time() + 120
    try:
        while len(got) < want and time.time() < end:
            got += feed.poll()
            time.sleep(0.2)
    finally:
        feed.close()
    return got


def test_the_real_reader_hands_over_only_good_files(real):
    events = [x["event"] for x in lines(real, "tail", "--run", RUN) if x["type"] == "event"]
    stored = {e["id"]: e.get("files") for e in events if e["outcome"] is None}
    assert stored["toolu_a1"] == ["budget-2026.xlsx"]
    assert stored["toolu_a2"] == ["offsite/agenda.docx"]  # absolute, .., backslash: dropped by the writer
    assert stored["toolu_a4"] == ["notes/ünï.txt"]  # too long and a key value: dropped
    assert not stored["toolu_a3"]  # a step without files
    assert all(file_ok(f) for e in events for f in e.get("files") or [])


def test_query_reads_the_same_files_as_tail(real):
    (page,) = lines(real, "query", "--run", RUN, "--limit", "50")
    assert any(e.get("files") == ["budget-2026.xlsx"] for e in page["items"])


def test_focus_shows_the_files_of_a_real_run_and_a_clear_empty_state(real):
    events = feed_events(real, want=8)
    assert len(events) >= 8
    board = Board.from_events(events).snapshot()
    files = {f["path"]: f["how"] for f in board["files"]}
    assert files == {"budget-2026.xlsx": "read", "offsite/agenda.docx": "changed", "notes/ünï.txt": "changed"}
    assert all(f["at"] for f in board["files"])
    # the step without files adds nothing, and an empty board says nothing is there (the page shows its own sentence)
    assert Board.from_events([e for e in events if e["text"] == "Ran the checks"]).snapshot()["files"] == []


def test_same_file_from_two_real_runs_needs_a_change(real):
    events = feed_events(real, want=8)
    files = Board.from_events(events).snapshot()["files"]
    mine = {"ticket": TICKET, "key": "R-1", "title": "Mine", "agent": "Agent", "files": files}
    other = {"ticket": "t_other0001", "key": "R-2", "title": "Other", "agent": "Agent2",
             "files": [{"path": "budget-2026.xlsx", "how": "changed", "at": "2026-11-16T09:20:00Z"}]}  # fmt: skip
    got = same_file([mine, other])
    assert [g["path"] for g in got] == ["budget-2026.xlsx"] and {t["key"] for t in got[0]["tickets"]} == {
        "R-1",
        "R-2",
    }


def test_focus_never_opens_a_recorded_path(real, monkeypatch):
    opened = []
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda p, *a, **k: (opened.append(str(p)), real_open(p, *a, **k))[1])
    feed_events(real, want=8)
    assert not [p for p in opened if "agenda.docx" in p or "budget-2026" in p or "notes" in p]

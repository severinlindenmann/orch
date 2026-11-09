"""The W2b fixtures (tmux control-mode captures, codex exec --json captures) load and are clean."""

import json
from pathlib import Path

ROOT = Path(__file__).parent / "fixtures" / "w2b"
FILES = sorted(p for p in ROOT.rglob("*") if p.is_file())


def test_fixture_files_exist():
    names = {p.relative_to(ROOT).as_posix() for p in FILES}
    assert {
        "screen/control-mode.raw",
        "screen/final-capture-pane.txt",
        "screen/README.md",
        "codex/list-files.jsonl",
        "codex/failing-command.jsonl",
        "codex/read-summarise.jsonl",
        "codex/README.md",
    } <= names


def test_no_home_paths_and_not_empty():
    for p in FILES:
        text = p.read_text(encoding="utf-8")
        assert text.strip(), p
        assert "/Users/" not in text, p


def test_codex_captures_are_jsonl():
    for p in sorted((ROOT / "codex").glob("*.jsonl")):
        events = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
        assert events[0]["type"] == "thread.started", p
        assert events[-1]["type"] == "turn.completed", p


def test_control_mode_capture_shape():
    lines = (ROOT / "screen" / "control-mode.raw").read_text(encoding="utf-8").splitlines()
    kinds = {line.split(" ", 1)[0] for line in lines if line.startswith("%")}
    assert {"%output", "%layout-change"} <= kinds
    raw = "\n".join(lines)
    assert "\\033[?1049h" in raw and "\\033[?1049l" in raw

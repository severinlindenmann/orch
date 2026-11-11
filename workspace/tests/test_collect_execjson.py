import hashlib
import json
from pathlib import Path

import pytest

from orch.collect_execjson import ExecJsonMapper, detail_name, map_stream

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "contracts/vectors/activity-v1.json").read_text())
CTX = dict(run="r_cx00001", ticket="t_inv7c2", harness="codex", at="2026-11-16T09:00:00Z")


def mapper(**kwargs):
    return ExecJsonMapper(CTX["run"], CTX["ticket"], CTX["harness"], now=lambda: CTX["at"], **kwargs)


def item(typ="command_execution", **fields):
    return json.dumps({"type": "item.completed", "item": {"type": typ, **fields}})


@pytest.mark.parametrize("case", VECTORS["stream_mapping"], ids=lambda c: c["capture"])
def test_vectors(case):
    assert map_stream(case["lines"], case["ctx"]) == case["events"]


@pytest.mark.parametrize("case", VECTORS["stream_mapping"], ids=lambda c: c["capture"])
def test_captures(case):
    ctx = case["ctx"]
    collector = ExecJsonMapper(ctx["run"], ctx["ticket"], ctx["harness"], now=lambda: "2026-11-16T09:00:00Z")
    path = ROOT / "workspace/tests/fixtures/w2b/codex" / case["capture"]
    events = [event for line in path.read_bytes().splitlines() for event in collector.feed(line)]
    assert events == case["events"]
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "contracts/activity.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    for event in events:
        validator.validate(event)


def test_warnings():
    collector = mapper()
    warning = "--dangerously-bypass-hook-trust is enabled"
    assert collector.feed(item("error", message=warning)) == []
    assert collector.warnings == [warning]
    for n in range(30):
        assert collector.feed(item("error", message=str(n))) == []
    assert len(collector.warnings) == 20
    assert collector.seq == 0


def test_types_and_coverage():
    collector = mapper()
    assert collector.feed(item("future_tool")) == []
    for typ in ("reasoning", "todo_list"):
        assert collector.feed(item(typ)) == []
    assert collector.feed(item("agent_message", text="Working"))[0]["coverage"] == "full"
    edit = collector.feed(item("file_change", changes=[{"path": "a\nb.py"}], status="completed"))[0]
    assert edit["coverage"] == "partial"
    assert edit["used"]["name"] == "Edit"
    assert edit["text"] == "Edit a b.py"
    assert edit["outcome"]["ok"] is True
    mcp = collector.feed(item("mcp_tool_call", server="docs", tool="lookup"))[0]
    assert mcp["coverage"] == "full"
    assert mcp["used"] == dict(kind="mcp", name="docs", action="lookup", source="harness", version=None)
    web = collector.feed(item("web_search", query="a\nb"))[0]
    assert web["used"]["name"] == "Web search"
    assert web["text"] == "Web search a b"
    assert collector.feed(item("file_change"))[0]["text"] == "Edit files"
    for typ in ("file_change", "mcp_tool_call", "web_search"):
        assert len(collector.feed(item(typ))) == 1


@pytest.mark.parametrize("unsafe", ["bad/id", "z" * 161, "bad\n"])
def test_stable_ids(unsafe):
    lines = [
        '{"type":"turn.started"}',
        item(id="item_0"),
        '{"type":"turn.started"}',
        item(id="item_0"),
        item(id=unsafe),
        item(),
    ]
    first, second = list(mapper().events(lines)), list(mapper().events(lines))
    assert [e["id"] for e in first] == [e["id"] for e in second]
    assert first[1]["id"] == "r_cx00001:1:item_0"
    assert first[3]["id"] == "r_cx00001:2:item_0"
    expected = "x_" + hashlib.sha256(f"r_cx00001:2:{unsafe}".encode()).hexdigest()[:32]
    assert first[4]["id"] == expected
    assert first[4]["detail"] == f"detail/r_cx00001/{detail_name('r_cx00001', 'step', expected)}.json"
    assert first[5]["id"] == "r_cx00001:6"
    assert [e["seq"] for e in first] == list(range(1, 7))
    assert all(e["session"] is None for e in first)


@pytest.mark.parametrize("case", VECTORS["detail_names"])
def test_detail_names(case):
    assert detail_name(case["run"], case["kind"], case["id"]) == case["file"]


@pytest.mark.parametrize("line", ["", "not json", "[]", b"\xff", "null", "42", '{"item":[]}'])
def test_garbage(line):
    assert mapper().feed(line) == []


def test_hider_and_no_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen = []

    def hider(text):
        seen.append(text)
        return text.replace("SECRET", "[hidden]")

    collector = mapper(hider=hider)
    assert collector.hidden
    assert not mapper().hidden
    failed = collector.feed(item(command="echo SECRET", exit_code=1, aggregated_output="SECRET\nrest"))[0]
    assert failed["text"] == "echo [hidden]"
    assert failed["outcome"]["error"] == "Exit code 1: [hidden]"
    message = collector.feed(item("agent_message", text="SECRET\nmessage"))[0]
    assert message["text"] == message["data"]["say"] == "[hidden] message"
    mcp = collector.feed(item("mcp_tool_call", server="SECRET", tool="SECRET"))[0]
    assert mcp["used"]["name"] == mcp["used"]["action"] == "[hidden]"
    collector.feed(item("error", message="SECRET"))
    assert collector.warnings == ["[hidden]"]
    assert {CTX["run"], CTX["ticket"], CTX["at"], "log", failed["detail"]} <= set(seen)
    assert list(tmp_path.iterdir()) == []

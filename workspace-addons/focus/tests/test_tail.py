import json

import pytest

from orch_focus.events import EventLog
from orch_focus.tail import Tail

from .conftest import TID

RUN = "r_abcd1234"
LINES = [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "timestamp": "2026-11-06T08:00:01.000Z", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls", "description": "List files"}}]}},
    {"type": "user", "timestamp": "2026-11-06T08:00:03.000Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "a b"}]}},
]  # fmt: skip


def write(path, lines, extra=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines) + extra)


def oneshot_log(ws):
    return ws / ".orch" / "run" / "logs" / f"{TID}-{RUN}.log"


def test_oneshot_stream_log_becomes_events(ws):
    write(oneshot_log(ws), LINES, extra="plain text from the tool\n")
    t = Tail(ws, TID, RUN, "claude", "oneshot")
    got = t.poll()
    assert [e["kind"] for e in got] == ["run.state", "tool.start", "tool.end"]
    assert got[1]["text"] == "List files"
    assert EventLog(ws, RUN).read()[0] == got
    assert t.poll() == []  # nothing new, nothing again


def test_half_written_line_waits_and_a_restarted_file_is_read_again(ws):
    p = oneshot_log(ws)
    write(p, LINES[:2])
    with open(p, "a") as f:
        f.write('{"type": "user", "message": {"con')
    t = Tail(ws, TID, RUN, "claude", "oneshot")
    assert [e["kind"] for e in t.poll()] == ["run.state", "tool.start"]
    write(p, LINES[:1])  # shorter: the file started over
    assert [e["kind"] for e in t.poll()] == ["run.state"]


def test_agent_without_a_mapper_reads_nothing(ws):
    write(oneshot_log(ws), LINES)
    assert Tail(ws, TID, RUN, "codex", "oneshot").poll() == []
    assert Tail(ws, TID, RUN, "generic", "live", session=lambda: "abcdefgh12").poll() == []
    assert not (ws / ".orch" / "addons").exists()


def test_live_run_follows_the_transcript(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    sid = "0d0f2b4e-1111-2222-3333-444455556666"
    write(tmp_path / "home" / ".claude" / "projects" / "-some-folder" / f"{sid}.jsonl", LINES)
    t = Tail(ws, TID, RUN, "claude", "live", session=lambda: sid)
    assert [e["kind"] for e in t.poll()] == ["run.state", "tool.start", "tool.end"]
    assert Tail(ws, TID, RUN, "claude", "live", session=lambda: None).poll() == []
    assert Tail(ws, TID, RUN, "claude", "live", session=lambda: "../../etc/passwd").poll() == []


def test_symlinked_log_is_not_followed(ws, tmp_path):
    real = tmp_path / "real.log"
    write(real, LINES)
    p = oneshot_log(ws)
    p.parent.mkdir(parents=True)
    p.symlink_to(real)
    assert Tail(ws, TID, RUN, "claude", "oneshot").poll() == []


def test_secret_in_a_line_is_redacted_before_the_log(ws):
    secret = "ghp_" + "f" * 30
    write(
        oneshot_log(ws),
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t9",
                            "name": "Bash",
                            "input": {"command": f"curl -H 'x: {secret}' u"},
                        }
                    ]
                },
            }
        ],
    )
    Tail(ws, TID, RUN, "claude", "oneshot").poll()
    assert secret not in (ws / ".orch/addons/focus/runs" / f"{RUN}.events.jsonl").read_text()


def test_odd_lines_do_not_stop_the_tail(ws):
    write(
        oneshot_log(ws),
        [{"type": "assistant", "message": "not a dict"}, {"type": "user", "message": {"content": 5}}, *LINES],
    )
    assert [e["kind"] for e in Tail(ws, TID, RUN, "claude", "oneshot").poll()][-1] == "tool.end"


@pytest.mark.parametrize("run", ["../x", "r_ab", "x"])
def test_bad_run_id_reads_nothing(ws, run):
    assert Tail(ws, TID, run, "claude", "oneshot").poll() == []


def test_a_300kb_line_does_not_stall_the_tail(ws):
    p = oneshot_log(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        f.write(json.dumps(LINES[0]) + "\n")
        f.write('{"type":"assistant","pad":"' + "x" * 300_000 + '"}\n')
        f.write(json.dumps(LINES[1]) + "\n" + json.dumps(LINES[2]) + "\n")
    t = Tail(ws, TID, RUN, "claude", "oneshot")
    kinds = []
    for _ in range(6):
        kinds += [e["kind"] for e in t.poll()]
    assert kinds == ["run.state", "tool.start", "tool.end"]  # the long line is dropped, the rest is read


def test_linked_folder_on_the_way_is_not_read(ws, tmp_path):
    real = tmp_path / "reallogs"
    write(real / f"{TID}-{RUN}.log", LINES)
    (ws / ".orch" / "run").mkdir(parents=True)
    (ws / ".orch" / "run" / "logs").symlink_to(real)
    assert Tail(ws, TID, RUN, "claude", "oneshot").poll() == []


def test_the_feed_hides_raw_output_injected_lines_and_repeats():
    from orch_focus import events as ev

    def e(kind, text, **d):
        return ev.make(RUN, TID, "main", kind, text, "adapter", **d)

    got = ev.for_display(
        [
            e("tool.start", "Read SKILL.md", id="a"),
            e("tool.end", "Base directory for this skill: /x ...", id="a", ok=True),
            e("tool.start", "Run orch ticket show", id="b"),
            e("tool.end", "New on t_abc12345 since you looked: x", id="b", ok=False),
            e("tool.start", "Run orch ticket show", id="c"),
            e("tool.end", "no such file", id="c", ok=False),
        ]
    )
    assert [x["text"] for x in got] == ["Read SKILL.md", "Run orch ticket show", "Failed: no such file"]

"""Earlier chat sessions: list and read the tool's saved conversation (Claude, Codex)."""

import json

from orch import session_history

SID = "0364ced3-ceac-463a-a68d-53a565d7e9df"
CODEX = "01a177e2-18c5-7bd0-91c0-2ac95c9f348e"


def _w(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _env(tmp_path):
    claude = tmp_path / "c"
    codex = tmp_path / "x"
    _w(
        claude / "projects" / "-Users-a-ws" / f"{SID}.jsonl",
        [
            {"type": "mode"},
            {"type": "user", "timestamp": "t1", "message": {"role": "user", "content": "Fix the login"}},
            {"type": "user", "message": {"content": "<system-reminder>x</system-reminder>"}},
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Done."}, {"type": "tool_use"}]},
            },
            {"type": "assistant", "isSidechain": True, "message": {"content": "hidden"}},
        ],
    )

    def msg(role, kind, text):
        return {
            "type": "response_item",
            "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]},
        }

    _w(
        codex / "sessions" / "2026" / "10" / "26" / f"rollout-2026-10-26T12-04-28-{CODEX}.jsonl",
        [
            {"type": "session_meta", "payload": {}},
            msg("user", "input_text", "Add tests"),
            msg("assistant", "output_text", "Added."),
        ],
    )
    return {"CLAUDE_CONFIG_DIR": str(claude), "CODEX_HOME": str(codex), "HOME": str(tmp_path)}


def test_claude_turns(tmp_path):
    h = session_history.read("claude", SID, _env(tmp_path))
    assert h["found"] and [t["role"] for t in h["turns"]] == ["user", "helper"]
    assert h["turns"][0]["text"] == "Fix the login" and h["turns"][1]["text"] == "Done."


def test_codex_turns(tmp_path):
    h = session_history.read("codex", CODEX, _env(tmp_path))
    assert [t["text"] for t in h["turns"]] == ["Add tests", "Added."]


def test_missing_and_bad_ids(tmp_path):
    env = _env(tmp_path)
    assert session_history.read("claude", "nope", env)["found"] is False
    assert session_history.read("claude", "../../etc/passwd", env)["found"] is False
    assert session_history.read("generic", SID, env)["found"] is False


def test_sessions_list_newest_first(tmp_path):
    t = {
        "sessions": [
            {"agent": "claude", "id": SID, "host": "h", "last_used": "2026-11-01"},
            {"agent": "codex", "id": CODEX, "host": "h", "last_used": "2026-11-05"},
            {"agent": "claude", "id": "gone-1", "host": "h", "last_used": "2026-11-09"},
        ]
    }
    rows = session_history.sessions(t, _env(tmp_path))
    assert [r["id"] for r in rows] == ["gone-1", CODEX, SID]
    assert rows[0]["readable"] is False and rows[2]["title"] == "Fix the login"

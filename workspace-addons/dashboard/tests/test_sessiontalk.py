"""ORCH-2204: the Chat view reads the helper's real conversation (GET /api/talk/<ticket>)."""

import json
import os

from orch_dashboard import sessiontalk

SID = "0364ced3-ceac-463a-a68d-53a565d7e9df"
OLD = "11111111-ceac-463a-a68d-53a565d7e9df"


def _ticket(sessions):
    return {"id": "t_abcdef", "sessions": sessions}


def _conv(tmp_path, monkeypatch, rows, sid=SID):
    d = tmp_path / "claude" / "projects" / "-ws"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    return d / f"{sid}.jsonl"


def _load(monkeypatch, ticket):
    from orch import tickets

    monkeypatch.setattr(tickets, "load", lambda root, tid: ticket)


def test_real_turns_of_the_session_in_use_without_orch_notices(tmp_path, monkeypatch):
    sessiontalk._CACHE.clear()
    _conv(
        tmp_path,
        monkeypatch,
        [
            {
                "type": "user",
                "timestamp": "2026-11-26T09:00:00Z",
                "message": {"content": "Your task for orch ticket ORCH-1: x"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-11-26T09:00:05Z",
                "message": {"content": [{"type": "text", "text": "Reading the ticket."}]},
            },
            {"type": "user", "timestamp": "2026-11-26T09:01:00Z", "message": {"content": "Use the blue one"}},
            {"type": "user", "message": {"content": "New input on orch ticket ORCH-1: hi"}},
        ],
    )
    _load(
        monkeypatch,
        _ticket(
            [
                {"agent": "claude", "id": OLD, "last_used": "2026-11-20T00:00:00Z"},
                {"agent": "claude", "id": SID, "last_used": "2026-11-26T09:00:00Z"},
            ]
        ),
    )
    d = sessiontalk.talk(tmp_path, "t_abcdef")
    assert d["available"] is True and d["more"] is False
    assert d["turns"] == [
        {"w": "h", "text": "Reading the ticket.", "at": "2026-11-26T09:00:05Z"},
        {"w": "y", "text": "Use the blue one", "at": "2026-11-26T09:01:00Z"},
    ]


def test_newest_turns_only_cut_and_cached(tmp_path, monkeypatch):
    sessiontalk._CACHE.clear()
    f = _conv(
        tmp_path,
        monkeypatch,
        [{"type": "assistant", "message": {"content": f"t{i} " + "x" * 3000}} for i in range(100)],
    )
    _load(monkeypatch, _ticket([{"agent": "claude", "id": SID, "last_used": "2026-11-26T09:00:00Z"}]))
    d = sessiontalk.talk(tmp_path, "t_abcdef")
    assert len(d["turns"]) == sessiontalk.TURNS and d["more"] is True
    assert d["turns"][-1]["text"].startswith("t99 ") and len(d["turns"][-1]["text"]) == sessiontalk.TEXT
    assert d["turns"][-1]["text"].endswith("…")
    assert sessiontalk.talk(tmp_path, "t_abcdef") is d  # the same file: no second read
    f.write_text(json.dumps({"type": "assistant", "message": {"content": "new"}}) + "\n", encoding="utf-8")
    os.utime(f, ns=(1, 2))
    assert [t["text"] for t in sessiontalk.talk(tmp_path, "t_abcdef")["turns"]] == ["new"]


def test_no_conversation_says_unavailable(tmp_path, monkeypatch):
    sessiontalk._CACHE.clear()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "none"))
    _load(monkeypatch, _ticket([{"agent": "claude", "id": SID}]))
    assert sessiontalk.talk(tmp_path, "t_abcdef")["available"] is False  # file not on this computer
    _load(monkeypatch, _ticket([{"agent": "generic", "id": SID}]))
    assert sessiontalk.talk(tmp_path, "t_abcdef")["available"] is False  # a tool that keeps none
    _load(monkeypatch, _ticket([{"agent": "claude", "id": "../../etc/passwd"}]))
    assert sessiontalk.talk(tmp_path, "t_abcdef")["available"] is False
    _load(monkeypatch, _ticket([]))
    assert sessiontalk.talk(tmp_path, "t_abcdef")["available"] is False


def test_unknown_ticket_says_unavailable(tmp_path):
    sessiontalk._CACHE.clear()
    assert sessiontalk.talk(tmp_path, "t_zzzzzz") == {"available": False, "turns": [], "more": False}


def test_secrets_in_a_turn_show_as_hidden(tmp_path, monkeypatch):
    """ORCH-2352 (security L3 of #3328): a key the helper printed never reaches the page; the rest stays."""
    sessiontalk._CACHE.clear()
    token = "ghp_" + "a1B2c3D4e5" * 4  # put together here: no token-shaped text in the repo
    stored = "zebra-" + "plum-" * 3 + "42"

    class Hide:
        def hide_text(self, s):
            return s.replace(stored, "[hidden]")

    from orch import phone_results

    monkeypatch.setattr(phone_results, "value_hider", lambda root: Hide())
    _conv(
        tmp_path,
        monkeypatch,
        [
            {"type": "assistant", "message": {"content": f"I read the file.\nThe token is {token}\nDone."}},
            {"type": "assistant", "message": {"content": "export API_KEY=" + "s3cr3t" * 4}},
            {"type": "user", "message": {"content": f"use {stored} for the shop"}},
            {"type": "assistant", "message": {"content": "First line.\n\n- one\n- two"}},
        ],
    )
    _load(monkeypatch, _ticket([{"agent": "claude", "id": SID, "last_used": "2026-11-26T09:00:00Z"}]))
    texts = [t["text"] for t in sessiontalk.talk(tmp_path, "t_abcdef")["turns"]]
    joined = "\n".join(texts)
    assert token not in joined and "s3cr3t" not in joined and stored not in joined
    assert texts[0].startswith("I read the file.\n") and texts[0].endswith("\nDone.") and "[hidden]" in texts[0]
    assert "[hidden]" in texts[1] and texts[2] == "use [hidden] for the shop"
    assert texts[3] == "First line.\n\n- one\n- two"  # plain text keeps its lines


def test_a_scrub_that_fails_shows_nothing_of_the_turn(tmp_path, monkeypatch):
    sessiontalk._CACHE.clear()
    from orch import phone_view

    monkeypatch.setattr(phone_view, "redact", lambda text: 1 / 0)
    _conv(tmp_path, monkeypatch, [{"type": "assistant", "message": {"content": "anything"}}])
    _load(monkeypatch, _ticket([{"agent": "claude", "id": SID, "last_used": "2026-11-26T09:00:00Z"}]))
    assert [t["text"] for t in sessiontalk.talk(tmp_path, "t_abcdef")["turns"]] == ["[hidden]"]

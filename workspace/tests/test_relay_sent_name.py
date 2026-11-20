"""The 'Message sent to ...' line names the workspace, never a bare id (ORCH-938).

A workspace allowed after this one's last refresh is missing from workspaces.json: the line refreshes the list
once and looks again; when the name is still unknown it says so in plain words.
"""

from __future__ import annotations

import json
from pathlib import Path

from orch import cli_clients, relay
from orch.errors import Refused

WS = "ws_rvulic648k"


def _write_list(root: Path, workspaces: list[dict]) -> None:
    d = root / ".agents" / "skills" / "orch-relay"
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspaces.json").write_text(json.dumps({"workspaces": workspaces, "phones": []}))


def _line(root: Path, to: str) -> str:
    return cli_clients._sent_line(root, {"to": to, "sent": True}, "Message sent to {}.")


def test_known_workspace_is_named_without_a_refresh(tmp_path, monkeypatch):
    _write_list(tmp_path, [{"id": WS, "name": "Pilatus"}])
    monkeypatch.setattr(relay, "refresh", lambda root: (_ for _ in ()).throw(AssertionError("no refresh")))
    assert _line(tmp_path, WS) == "Message sent to Pilatus."


def test_unknown_workspace_refreshes_the_list_once_and_names_it(tmp_path, monkeypatch):
    _write_list(tmp_path, [])
    calls = []

    def fake_refresh(root):
        calls.append(root)
        _write_list(root, [{"id": WS, "name": "Pilatus"}])
        return "Updated"

    monkeypatch.setattr(relay, "refresh", fake_refresh)
    assert _line(tmp_path, WS) == "Message sent to Pilatus."
    assert calls == [tmp_path]


def test_still_unknown_after_refresh_says_so_plainly(tmp_path, monkeypatch):
    _write_list(tmp_path, [])

    def failing_refresh(root):
        raise Refused("The relay can't be reached.")

    monkeypatch.setattr(relay, "refresh", failing_refresh)
    assert _line(tmp_path, WS) == f"Message sent to {WS} (its name is not known here yet)."


def test_phones_and_admin_keep_their_words(tmp_path, monkeypatch):
    _write_list(tmp_path, [])
    monkeypatch.setattr(relay, "refresh", lambda root: (_ for _ in ()).throw(AssertionError("no refresh")))
    assert _line(tmp_path, "phones") == "Message sent to the phones."
    assert _line(tmp_path, "admin") == "Message sent to the admin."

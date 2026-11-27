"""`orch tools` (cli_tools.py): list, notes, update with a faked tool status; no network, no real update."""

import json

import pytest

from orch import cli, toolupdates

TOOL = {
    "name": "gh",
    "label": "GitHub CLI",
    "installed": "2.0.0",
    "newest": "2.1.0",
    "update": True,
    "can_update": True,
    "how": "brew",
    "compare": "older",
    "notes": [{"version": "2.1.0", "lines": ["faster"]}],
    "more": 0,
}


@pytest.fixture
def fake(proj, monkeypatch):
    (proj / ".orch").mkdir()
    doc = {"tools": [dict(TOOL)]}
    monkeypatch.setattr(toolupdates, "status", lambda root, refresh=False, only=None: doc)
    monkeypatch.setattr(toolupdates, "in_helper", lambda: False)
    return doc


def _run(capsys, *argv):
    try:
        code = cli.main(["tools", *argv])
    except SystemExit as e:
        code = e.code
    cap = capsys.readouterr()
    return code or 0, cap.out, cap.err


def test_list_text_names_the_update_command(fake, capsys):
    code, out, _ = _run(capsys)
    assert code == 0 and "GitHub CLI (gh) 2.0.0, newer: 2.1.0" in out and "orch tools update gh" in out


def test_list_json_and_empty(fake, capsys):
    code, out, _ = _run(capsys, "list", "--json")
    assert code == 0 and json.loads(out)["tools"][0]["name"] == "gh"
    fake["tools"].clear()
    code, out, _ = _run(capsys, "list")
    assert code == 0 and "No tools orch knows how to check" in out


def test_notes_text_hidden_from_helpers_and_unknown_tool(fake, capsys, monkeypatch):
    code, out, _ = _run(capsys, "notes", "gh")
    assert code == 0 and "What's new in 2.1.0:" in out and "  - faster" in out
    monkeypatch.setattr(toolupdates, "in_helper", lambda: True)
    code, out, _ = _run(capsys, "notes", "gh")
    assert code == 0 and "faster" not in out and "Settings > About & updates" in out
    fake["tools"].clear()
    code, _, err = _run(capsys, "notes", "gh")
    assert code != 0 and "orch tools" in err


def test_update_success_and_failure_exit_code(fake, capsys, monkeypatch):
    job = {"status": "done", "say": "GitHub CLI is now 2.1.0.", "tail": []}
    monkeypatch.setattr(toolupdates, "update", lambda root, name: job)
    code, out, _ = _run(capsys, "update", "gh")
    assert code == 0 and "now 2.1.0" in out
    job.update(status="failed", say="The update failed.", tail=["boom"])
    code, out, _ = _run(capsys, "update", "gh", "--json")
    assert code == 1 and json.loads(out)["status"] == "failed"
    code, out, _ = _run(capsys, "update", "gh")
    assert code == 1 and "Last lines of its output:\n  boom" in out


def test_update_unknown_tool_says_what_exists(proj, capsys, monkeypatch):
    (proj / ".orch").mkdir()
    monkeypatch.setattr(toolupdates, "tools_for", lambda root: [])
    code, _, err = _run(capsys, "update", "nope")
    assert code != 0 and "no tool called nope" in err

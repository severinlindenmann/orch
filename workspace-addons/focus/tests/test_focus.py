"""The Focus add-on (ORCH-816): the dashboard draws Focus; this package names it and keeps two commands."""

import json
from pathlib import Path

import pytest

from orch_focus import cli, needs

PKG = Path(__file__).resolve().parents[1] / "src" / "orch_focus"


def test_the_package_is_only_the_manifest_two_commands_and_the_skill():
    files = sorted(
        p.relative_to(PKG).as_posix() for p in PKG.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    assert files == [
        "__init__.py",
        "__main__.py",
        "cli.py",
        "needs.py",
        "orch-addon.toml",
        "skills/orch-focus/AGENTS-block.md",
        "skills/orch-focus/SKILL.md",
    ]


def test_the_manifest_is_a_page_the_dashboard_draws_with_no_server(ws):
    from orch import addons

    m = addons.parse_manifest(PKG / "orch-addon.toml")
    assert m["background"] is False
    assert m["page"]["live_session"] is True
    assert not m.get("ticket_view")
    assert m["recommended"] is True and m["needs"] is True


def test_open_gives_the_dashboard_address_of_the_ticket(ws, monkeypatch, capsys):
    root, t = ws
    from orch import addons, services

    monkeypatch.setattr(addons, "active_manifests", lambda r: {"dashboard": {}, "focus": {}})
    monkeypatch.setattr(
        services,
        "running",
        lambda: [
            {
                "workspace": str(root.resolve()),
                "addon": "dashboard",
                "pid": 1,
                "url": "http://127.0.0.1:8777/",
            }
        ],
    )
    for ref in (t["id"], t["key"].lower()):
        assert cli.main(["open", ref, "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == {
            "url": f"http://127.0.0.1:8777/#addon/focus/t/{t['id']}"
        }


def test_open_starts_a_stopped_dashboard_and_refuses_without_one(ws, monkeypatch, capsys):
    _, t = ws
    from orch import addons, services

    started = []
    monkeypatch.setattr(addons, "active_manifests", lambda r: {"dashboard": {}, "focus": {}})
    monkeypatch.setattr(services, "running", list)
    monkeypatch.setattr(
        services,
        "start",
        lambda r, only=None: started.append(only) or [{"addon": "dashboard", "url": "http://127.0.0.1:8790"}],
    )
    assert cli.main(["open", t["id"], "--no-open"]) == 0
    assert capsys.readouterr().out.strip() == f"http://127.0.0.1:8790/#addon/focus/t/{t['id']}"
    assert started == [{"dashboard"}]
    monkeypatch.setattr(addons, "active_manifests", lambda r: {"focus": {}})
    assert cli.main(["open", t["id"]]) == 2
    assert "orch addon add dashboard" in capsys.readouterr().err
    assert cli.main(["open", "t_nosuch1"]) == 2
    assert "Give a ticket id" in capsys.readouterr().err


def test_needs_names_a_live_helper_waiting_for_the_ok_and_nothing_else(ws, monkeypatch):
    root, t = ws
    from orch import runs

    d = runs.run_dir(root) / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"ticket": t["id"], "run": "r1", "mode": "live", "renewed_at": "2026-11-19T10:00:00Z",
           "live": {"state": "attention", "why": "Allow the edit?", "since": "2026-11-19T10:01:00Z"}}  # fmt: skip
    (d / f"{t['id']}.json").write_text(json.dumps(rec))
    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    rows = needs.rows(root)
    assert [(r["kind"], r["ticket"], r["text"], r["cli"]) for r in rows] == [
        ("focus:waiting", t["id"], "Allow the edit?", f"orch focus open {t['id']}")
    ]
    rec["live"]["state"] = "working"
    (d / f"{t['id']}.json").write_text(json.dumps(rec))
    assert needs.rows(root) == []
    rec["live"]["state"] = "attention"
    (d / f"{t['id']}.json").write_text(json.dumps(rec))
    monkeypatch.setattr(runs, "state", lambda r, at=None: "dead")
    assert needs.rows(root) == []


@pytest.mark.parametrize("argv", [["serve"], ["start"], ["stop"], ["status"], ["view"], ["area", "list"]])
def test_the_old_page_commands_are_gone(argv, ws):
    with pytest.raises(SystemExit):
        cli.main(argv)

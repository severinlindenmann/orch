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
        "docs.json",  # the Documentation page's pictures and words for Focus (ORCH-735)
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


def _claim(root, tid, **over):
    from orch import runs

    d = runs.run_dir(root) / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"ticket": tid, "run": "r1", "mode": "live", "renewed_at": "2026-11-19T10:00:00Z",
           "live": {"state": "attention"}}  # fmt: skip
    rec.update(over)
    (d / f"{tid}.json").write_text(json.dumps(rec))
    return rec


def test_needs_row_falls_back_when_the_helper_gave_no_reason_or_time(ws, monkeypatch):
    root, t = ws
    from orch import runs

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    _claim(root, t["id"])
    [row] = needs.rows(root)
    assert row["text"] == "Waiting for your OK in the live session."
    assert row["since"] == "2026-11-19T10:00:00Z"
    _claim(root, t["id"], renewed_at=None)
    from datetime import UTC, datetime

    [row] = needs.rows(root, now=datetime(2026, 11, 20, 8, 30, 5, tzinfo=UTC))
    assert row["since"] == "2026-11-20T08:30:05Z"
    _claim(root, t["id"], live={"state": "attention", "why": "x" * 900})
    assert len(needs.rows(root)[0]["text"]) == 400


def test_needs_skips_non_live_runs_and_hidden_conversations(ws, monkeypatch):
    root, t = ws
    from orch import runs, tickets

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    _claim(root, t["id"], mode="headless")
    assert needs.rows(root) == []
    _claim(root, t["id"])
    assert len(needs.rows(root)) == 1
    for flag in ("general", "manager"):
        tk = tickets.load(root, t["id"])
        tk[flag] = True
        tickets.save(root, tk)
        assert needs.rows(root) == []
        tk[flag] = False
        tickets.save(root, tk)


def test_needs_ignores_a_claim_whose_ticket_is_broken_and_keeps_the_others(ws, monkeypatch):
    root, t = ws
    from orch import runs

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    _claim(root, "t_deadbeef1")
    _claim(root, t["id"])
    d = runs.run_dir(root) / "tickets"
    (d / "t_notanid.json").write_text("{}")
    assert [r["ticket"] for r in needs.rows(root)] == [t["id"]]


def test_needs_title_is_plain_text(ws, monkeypatch):
    assert needs._title({"title": "<b>Hi</b>"}) == "bHi/b"
    assert needs._title({"title": "  "}) == "A ticket"
    assert needs._title({}) == "A ticket"
    assert len(needs._title({"title": "y" * 500})) == 200


def test_needs_command_prints_lines_or_json_or_the_empty_message(ws, monkeypatch, capsys):
    root, t = ws
    from orch import runs

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    assert cli.main(["needs"]) == 0
    assert capsys.readouterr().out.strip() == "Nothing needs you here."
    _claim(root, t["id"], live={"state": "attention", "why": "Allow?"})
    assert cli.main(["needs"]) == 0
    assert capsys.readouterr().out.strip() == f"{t['title']}: Allow?"
    assert cli.main(["needs", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["ticket"] == t["id"]


def test_commands_refuse_outside_a_workspace_and_find_it_from_a_subfolder(ws, tmp_path_factory, capsys):
    root, _ = ws
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    assert cli.find_workspace(sub) == root.resolve()
    assert cli.find_workspace(tmp_path_factory.mktemp("bare")) is None
    assert cli.main(["--dir", str(tmp_path_factory.mktemp("bare2")), "needs"]) == 2
    assert "orch init" in capsys.readouterr().err


def test_open_says_why_when_the_dashboard_will_not_start(ws, monkeypatch, capsys):
    _, t = ws
    from orch import addons, services

    monkeypatch.setattr(addons, "active_manifests", lambda r: {"dashboard": {}, "focus": {}})
    monkeypatch.setattr(services, "running", list)
    monkeypatch.setattr(services, "start", lambda r, only=None: [{"addon": "dashboard", "error": "port busy"}])
    assert cli.main(["open", t["id"], "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "The dashboard did not start: port busy"
    monkeypatch.setattr(services, "start", lambda r, only=None: [])
    assert cli.main(["open", t["id"], "--no-open"]) == 2
    assert "Run orch start." in capsys.readouterr().err


def test_needs_does_not_follow_a_symlinked_claim_folder(ws, monkeypatch, tmp_path):
    root, t = ws
    from orch import runs

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    _claim(root, t["id"])
    d = runs.run_dir(root) / "tickets"
    real = tmp_path / "elsewhere"
    d.rename(real)
    try:
        d.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need a privilege here")
    assert needs.rows(root) == []

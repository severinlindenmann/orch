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


# --- ORCH-2078: the paths the tests above did not reach ---------------------------------------------------


def _live(root, tid, live, **extra):
    from orch import runs

    d = runs.run_dir(root) / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    rec = {
        "ticket": tid,
        "run": "r1",
        "mode": "live",
        "renewed_at": "2026-11-19T10:00:00Z",
        "live": live,
        **extra,
    }
    (d / f"{tid}.json").write_text(json.dumps(rec), encoding="utf-8")
    return d


def _dashboard_on(monkeypatch, root, url="http://127.0.0.1:8777/"):
    from orch import addons, services

    monkeypatch.setattr(addons, "active_manifests", lambda r: {"dashboard": {}, "focus": {}})
    monkeypatch.setattr(
        services, "running", lambda: [{"workspace": str(root.resolve()), "addon": "dashboard", "url": url}]
    )


def test_a_workspace_is_found_upwards_from_a_folder_with_spaces_and_umlauts(tmp_path, monkeypatch, capsys):
    import os

    from orch import addons, winfinish
    from orch import cli as core

    monkeypatch.setattr(addons, "real_home", lambda: Path(os.environ["HOME"]))
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    root = tmp_path / "Jörg Müller" / "Kunden Projekt"
    deep = root / "Entwürfe" / "Q4 Plan"
    deep.mkdir(parents=True)
    monkeypatch.chdir(root)
    assert core.main(["init", "--yes"]) == 0
    assert core.main(["ticket", "new", "Brot backen"]) == 0
    capsys.readouterr()
    assert cli.find_workspace(deep) == root.resolve()
    _dashboard_on(monkeypatch, root)
    from orch import tickets

    t = tickets.list_all(root)[0]
    assert cli.main(["--dir", str(deep), "open", t["key"], "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["url"].endswith(f"/#addon/focus/t/{t['id']}")


def test_outside_a_workspace_both_commands_say_what_to_do(tmp_path, capsys):
    assert cli.find_workspace(tmp_path) is None
    for argv in (["--dir", str(tmp_path), "needs"], ["--dir", str(tmp_path), "open", "t_ab12cd"]):
        assert cli.main(argv) == 2
        assert "Run `orch init` first." in capsys.readouterr().err


def test_a_dashboard_that_does_not_start_is_named_with_its_error(ws, monkeypatch, capsys):
    _, t = ws
    from orch import addons, services

    monkeypatch.setattr(addons, "active_manifests", lambda r: {"dashboard": {}})
    monkeypatch.setattr(services, "running", list)
    monkeypatch.setattr(
        services, "start", lambda r, only=None: [{"addon": "dashboard", "error": "port busy"}]
    )
    assert cli.main(["open", t["id"], "--no-open"]) == 2
    assert capsys.readouterr().err.strip() == "Refused: The dashboard did not start: port busy"
    monkeypatch.setattr(services, "start", lambda r, only=None: [])
    assert cli.main(["open", t["id"], "--json"]) == 2  # --json: the refusal is JSON on stdout
    out = capsys.readouterr()
    assert json.loads(out.out) == {"error": "The dashboard did not start. Run orch start."} and out.err == ""


def test_a_dashboard_of_another_workspace_is_not_used(ws, monkeypatch, capsys):
    root, t = ws
    from orch import addons, services

    monkeypatch.setattr(addons, "active_manifests", lambda r: {"dashboard": {}})
    monkeypatch.setattr(
        services, "running", lambda: [{"workspace": str(root.parent / "other"), "addon": "dashboard",
                                       "url": "http://127.0.0.1:9999/"}],
    )  # fmt: skip
    monkeypatch.setattr(
        services, "start", lambda r, only=None: [{"addon": "dashboard", "url": "http://127.0.0.1:8790"}]
    )
    assert cli.main(["open", t["id"], "--no-open"]) == 0
    assert capsys.readouterr().out.strip().startswith("http://127.0.0.1:8790/")


@pytest.mark.parametrize(("tty", "flags", "opened"), [(True, [], True), (False, [], False),
                                                       (True, ["--no-open"], False), (True, ["--json"], False)])  # fmt: skip
def test_the_browser_opens_only_for_a_person_at_a_terminal(ws, monkeypatch, capsys, tty, flags, opened):
    root, t = ws
    from orch import pagelaunch, term

    _dashboard_on(monkeypatch, root)
    seen = []
    monkeypatch.setattr(term, "is_terminal", lambda s: tty)
    monkeypatch.setattr(pagelaunch, "launch_url", lambda r, server, url: f"{url}#launch=tok")
    monkeypatch.setattr(pagelaunch, "open_browser", seen.append)
    assert cli.main(["open", t["id"], *flags]) == 0
    page = f"http://127.0.0.1:8777/#addon/focus/t/{t['id']}"
    assert seen == ([f"{page}#launch=tok"] if opened else [])
    assert "launch=" not in capsys.readouterr().out  # the launch token is never printed


def test_needs_command_empty_state_text_and_json(ws, monkeypatch, capsys):
    root, t = ws
    from orch import runs

    assert cli.main(["needs"]) == 0
    assert capsys.readouterr().out.strip() == "Nothing needs you here."
    assert cli.main(["needs", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    _live(root, t["id"], {"state": "attention", "why": "Allow the edit?"})
    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    assert cli.main(["needs"]) == 0
    assert capsys.readouterr().out.strip() == f"{t['title']}: Allow the edit?"
    assert cli.main(["needs", "--json"]) == 0
    assert [r["ticket"] for r in json.loads(capsys.readouterr().out)] == [t["id"]]


def test_needs_falls_back_for_why_since_and_title(ws, monkeypatch):
    root, t = ws
    from orch import runs, tickets

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    raw = tickets.load(root, t["id"])
    raw["title"] = " <> "
    tickets.save(root, raw)
    _live(root, t["id"], {"state": "attention"})
    [row] = needs.rows(root)
    assert row["title"] == "A ticket"  # a title of only angle brackets is not shown as empty
    assert row["text"] == "Waiting for your OK in the live session."
    assert row["since"] == "2026-11-19T10:00:00Z"  # the claim's renewal when the live state has no time
    _live(root, t["id"], {"state": "attention"}, renewed_at=None)
    from datetime import UTC, datetime

    [row] = needs.rows(root, now=datetime(2026, 11, 25, 9, 30, tzinfo=UTC))
    assert row["since"] == "2026-11-25T09:30:00Z"


def test_needs_skips_the_manager_the_phone_conversation_and_a_broken_ticket(ws, monkeypatch):
    root, t = ws
    from orch import cli as core
    from orch import runs, tickets

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    for title in ("Second", "Third", "Fourth"):
        assert core.main(["ticket", "new", title]) == 0
    others = [x for x in tickets.list_all(root) if x["id"] != t["id"]]
    for x, flag in zip(others, ("general", "manager", None), strict=True):
        raw = tickets.load(root, x["id"])
        if flag:
            raw[flag] = True
            tickets.save(root, raw)
        else:
            (root / ".orch" / "tickets" / f"{x['id']}.json").write_text("{ broken", encoding="utf-8")
    for x in (t, *others):
        _live(root, x["id"], {"state": "attention"})
    assert [r["ticket"] for r in needs.rows(root)] == [t["id"]]


@pytest.mark.parametrize("live", ["attention", ["attention"], 7, True])
def test_needs_survives_a_hand_edited_live_field(ws, monkeypatch, capsys, live):
    root, t = ws
    from orch import runs

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    _live(root, t["id"], live)
    assert needs.rows(root) == []
    assert cli.main(["needs"]) == 0
    assert capsys.readouterr().out.strip() == "Nothing needs you here."


def test_needs_ignores_files_that_are_not_claims(ws, monkeypatch):
    root, t = ws
    from orch import runs

    monkeypatch.setattr(runs, "state", lambda r, at=None: "alive")
    d = _live(root, t["id"], {"state": "attention"})
    (d / "t_X.json").write_text("{}", encoding="utf-8")  # not a ticket id
    (d / "t_ab12cd.json").write_text("[1, 2]", encoding="utf-8")  # not a claim record
    (d / "t_zz99zz.json").write_text("{}", encoding="utf-8")  # no run
    assert [r["ticket"] for r in needs.rows(root)] == [t["id"]]


def test_needs_without_a_run_folder_is_empty(ws):
    root, _ = ws
    from orch import runs

    assert not (runs.run_dir(root) / "tickets").exists()
    assert needs.rows(root) == []


def test_python_dash_m_runs_the_cli_and_passes_its_exit_code(tmp_path):
    import os
    import subprocess
    import sys

    src = [str(PKG.parent), str(PKG.parents[3] / "workspace" / "src")]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(src)}
    p = subprocess.run([sys.executable, "-m", "orch_focus", "--dir", str(tmp_path), "needs"],
                       check=False, capture_output=True, text=True, env=env, timeout=60)  # fmt: skip
    assert p.returncode == 2 and "orch init" in p.stderr

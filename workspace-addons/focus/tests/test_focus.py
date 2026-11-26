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
    assert "There is no ticket t_nosuch1 in this workspace" in capsys.readouterr().err
    monkeypatch.setattr(addons, "active_manifests", lambda r: {"dashboard": {}, "focus": {}})
    monkeypatch.setattr(
        services, "start", lambda r, only=None: [{"addon": "dashboard", "error": "port busy"}]
    )
    assert cli.main(["open", t["id"], "--no-open"]) == 2  # a start error stays its own message
    err = capsys.readouterr().err
    assert "The dashboard did not start: port busy" in err and "ticket" not in err


MISSING = "Run `orch ticket list` to see your tickets."
FORMAT = "Give a ticket id like t_ab12cd or its key like DM1-12."


@pytest.fixture
def no_dashboard(monkeypatch):
    """A failed lookup never looks for, starts or opens the dashboard."""
    from orch import addons, pagelaunch, services

    def boom(*a, **k):
        raise AssertionError("the dashboard was touched for a ticket that could not be opened")

    for mod, name in ((addons, "active_manifests"), (services, "running"), (services, "start"),
                      (pagelaunch, "open_browser")):  # fmt: skip
        monkeypatch.setattr(mod, name, boom)


@pytest.mark.parametrize(
    "ref, want",
    [
        ("t_absent1", f"There is no ticket t_absent1 in this workspace. {MISSING}"),
        ("  zz-404 ", f"There is no ticket ZZ-404 in this workspace. {MISSING}"),
        ("hello", FORMAT),
        ("T_ABSENT1", FORMAT),
        ("../../etc/passwd", FORMAT),
        ("t_x", FORMAT),
    ],
)
def test_open_tells_a_missing_ticket_from_a_malformed_one(ws, no_dashboard, capsys, ref, want):
    assert cli.main(["open", ref, "--no-open"]) == 2
    out = capsys.readouterr()
    assert out.out == "" and out.err == f"Refused: {want}\n"
    assert cli.main(["open", ref, "--json"]) == 2
    out = capsys.readouterr()
    assert out.err == "" and json.loads(out.out) == {"error": want}  # one object, no Next line
    assert "Next" not in out.out and out.out.count("\n") == 1


def test_open_never_calls_an_unreadable_ticket_missing(ws, no_dashboard, monkeypatch, capsys):
    root, t = ws
    from orch import tickets

    want = f"Ticket {t['id']} could not be read, so Focus can't open it. Run `orch ticket show {t['id']}` to see why."
    p = tickets.ticket_path(root, t["id"])
    good = p.read_text(encoding="utf-8")
    p.write_text("{half a ticket", encoding="utf-8")
    assert cli.main(["open", t["id"], "--no-open"]) == 2
    assert capsys.readouterr().err == f"Refused: {want}\n"
    p.write_text(good, encoding="utf-8")

    def denied(r, tid):
        raise PermissionError(13, "Permission denied", str(p) + " sk-live-SECRET")

    monkeypatch.setattr(tickets, "load", denied)
    for ref in (t["id"], t["key"].lower()):
        assert cli.main(["open", ref, "--json"]) == 2
        out = capsys.readouterr()
        err = json.loads(out.out)["error"]
        assert "could not be read" in err and "no ticket" not in err
        assert str(root) not in out.out + out.err and "SECRET" not in out.out + out.err and "Errno" not in err


def test_open_finds_a_lower_case_key_with_spaces(ws, monkeypatch, capsys):
    root, t = ws
    from orch import addons, services

    monkeypatch.setattr(addons, "active_manifests", lambda r: {"dashboard": {}, "focus": {}})
    monkeypatch.setattr(services, "running", lambda: [
        {"workspace": str(root.resolve()), "addon": "dashboard", "pid": 1, "url": "http://127.0.0.1:8777/"}
    ])  # fmt: skip
    assert cli.main(["open", f" {t['key'].lower()} ", "--no-open"]) == 0
    assert capsys.readouterr().out.strip() == f"http://127.0.0.1:8777/#addon/focus/t/{t['id']}"


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


@pytest.mark.parametrize("pos", [199, 200, 201])
def test_needs_finds_the_only_waiting_helper_past_the_first_200_run_records(ws, monkeypatch, capsys, pos):
    root, t = ws
    from orch import runs

    tdir, d = root / ".orch" / "tickets", runs.run_dir(root) / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    tpl = json.loads((tdir / f"{t['id']}.json").read_text())
    outside = root / "elsewhere.json"

    def rec(tid, alive="alive", state="attention"):
        return {"ticket": tid, "run": "r1", "mode": "live", "renewed_at": "2026-11-19T10:00:00Z",
                "fake_alive": alive, "live": {"state": state, "why": f"OK for {tid}?"}}  # fmt: skip

    kinds = ["working", "dead", "stale", "general", "manager", "broken", "symlink"] * 29
    ids = [f"t_s{n:07d}" for n in range(1, 202)]
    for i, tid in enumerate(ids, 1):
        p, k = d / f"{tid}.json", "eligible" if i == pos else kinds.pop()
        extra = {"general": True} if k == "general" else {"manager": True} if k == "manager" else {}
        (tdir / f"{tid}.json").write_text(json.dumps({**tpl, "id": tid, "title": f"Sample {i}", **extra}))
        if k == "broken":
            p.write_text("{not json")
        elif k == "symlink":
            outside.write_text(json.dumps(rec(tid)))
            p.symlink_to(outside)
        else:
            alive = {"dead": "dead", "stale": "maybe-stale"}.get(k, "alive")
            p.write_text(json.dumps(rec(tid, alive, "working" if k == "working" else "attention")))
    monkeypatch.setattr(runs, "state", lambda r, at=None: r.get("fake_alive", "dead"))
    want = ids[pos - 1]
    found, scanned = needs.scan(root)
    assert scanned == 201 - 29  # every record is read, the 29 symlinks are skipped unread; 1 is returned
    assert [(r["kind"], r["ticket"], r["title"], r["text"], r["cli"]) for r in found] == [
        ("focus:waiting", want, f"Sample {pos}", f"OK for {want}?", f"orch focus open {want}")
    ]
    assert set(found[0]) == {"id", "source", "kind", "ticket", "title", "text", "tone", "since", "cli"}
    assert cli.main(["needs", "--json"]) == 0 and json.loads(capsys.readouterr().out) == found
    assert cli.main(["needs"]) == 0 and capsys.readouterr().out == f"Sample {pos}: OK for {want}?\n"


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

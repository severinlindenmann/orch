"""orch Companion's view of this computer's workspaces (ORCH-1722): only set-up workspaces, no secrets, an
additive start that never stops anything, the "Start with my Mac" switch and the once-per-boot login start."""

import argparse
import json

import pytest

from orch import addons, cli_workspace, services
from orch import companion_ws as cw


def _ws(tmp_path, name, addons_on=("dashboard",)):
    root = tmp_path / name
    (root / ".orch").mkdir(parents=True)
    for a in addons_on:
        addons.record_consent(root, a)
    return root.resolve()


@pytest.fixture
def fake(monkeypatch):
    """Two background add-ons per workspace; running.json in memory; services.start recorded."""
    state = {"running": [], "starts": [], "retired": 0}
    monkeypatch.setattr(
        services,
        "_services",
        lambda root: {"dashboard": {"background": True}, "automation": {"background": True}},
    )
    monkeypatch.setattr(services, "running", lambda: list(state["running"]))

    def start(root, only=None, envs=None, retire=True):
        state["starts"].append((str(root), sorted(only or []), retire))
        rows = []
        for n in sorted(only or []):
            state["running"].append({"workspace": str(root), "addon": n, "pid": 1})
            rows.append({"addon": n, "running": True})
        return rows

    monkeypatch.setattr(services, "start", start)
    monkeypatch.setattr(services, "_retire", lambda root: state.__setitem__("retired", state["retired"] + 1))
    return state


def test_list_has_only_safe_fields_and_states(tmp_path, fake, monkeypatch):
    a = _ws(tmp_path, "a")
    b = _ws(tmp_path, "b")
    _ws(tmp_path, "c")
    monkeypatch.setenv("SECRET_TOKEN", "canary-123")
    fake["running"] += [
        {
            "workspace": str(a),
            "addon": "dashboard",
            "pid": 9,
            "url": "http://127.0.0.1:8421",
            "env": {"PATH": "/x", "TOKEN": "canary-123"},
        },
        {"workspace": str(a), "addon": "automation", "pid": 10},
        {"workspace": str(b), "addon": "dashboard", "pid": 11, "url": "http://evil.example:80"},
    ]
    out = cw.listing()
    text = json.dumps(out)
    assert "canary" not in text and "pid" not in text and "env" not in text
    rows = {r["name"]: r for r in out["workspaces"]}
    assert set(rows) == {"a", "b", "c"}
    keys = {"id", "name", "path", "state", "dashboard_url", "start_with_mac", "protected_folder"}
    assert set(rows["a"]) == keys
    assert (rows["a"]["state"], rows["a"]["dashboard_url"]) == ("running", "http://127.0.0.1:8421")
    assert (rows["b"]["state"], rows["b"]["dashboard_url"]) == (
        "partly",
        None,
    )  # foreign link: never handed on
    assert rows["c"]["state"] == "stopped"
    assert all(r["start_with_mac"] is False for r in rows.values())  # off by default


def test_a_copied_or_replaced_folder_is_not_listed(tmp_path, fake):
    a = _ws(tmp_path, "a")
    (a / ".orch" / ".local-id").unlink()
    addons.put_local_id(a, "f" * 32)  # another folder now sits at that path
    assert cw.listing()["workspaces"] == []


def test_start_is_additive_and_never_retires(tmp_path, fake):
    a = _ws(tmp_path, "a")
    fake["running"].append({"workspace": str(a), "addon": "dashboard", "pid": 9})
    wid = cw.listing()["workspaces"][0]["id"]
    res = cw.start(wid)
    assert res == {"v": 1, "ok": True, "id": wid, "started": ["automation"]}
    assert fake["starts"] == [(str(a), ["automation"], False)]
    assert fake["retired"] == 0
    assert cw.start(wid)["started"] == []  # all running: nothing started again
    assert len(fake["starts"]) == 1


def test_start_unknown_id_and_failure_give_orch_words_only(tmp_path, fake, monkeypatch):
    assert cw.start("../../etc")["error"] == "unknown_workspace"
    a = _ws(tmp_path, "a")
    wid = cw.listing()["workspaces"][0]["id"]
    monkeypatch.setattr(
        services,
        "start",
        lambda root, only=None, envs=None, retire=True: [
            {"addon": "dashboard", "running": False, "error": "token=canary-123 broke"}
        ],
    )
    res = cw.start(wid)
    assert res["error"] == "did_not_start" and "canary" not in json.dumps(res)
    assert str(a) not in res["message"]


def test_switch_and_login_start_once_per_boot(tmp_path, fake, monkeypatch):
    a = _ws(tmp_path, "a")
    _ws(tmp_path, "b")
    ids = {r["name"]: r["id"] for r in cw.listing()["workspaces"]}
    assert cw.switch(ids["a"], True)["start_with_mac"] is True
    assert {r["name"]: r["start_with_mac"] for r in cw.listing()["workspaces"]} == {"a": True, "b": False}
    monkeypatch.setattr(cw, "boot_time", lambda: 1000)
    res = cw.at_login()
    assert res["ok"] and not res["already"]
    assert [s[0] for s in fake["starts"]] == [str(a)]  # only the switched-on one
    assert cw.at_login()["already"] is True  # Companion restarted in the same boot: nothing
    assert len(fake["starts"]) == 1
    monkeypatch.setattr(cw, "boot_time", lambda: 2000)
    fake["running"].clear()
    cw.switch(ids["a"], False)  # off: never stopped, and not started at the next login
    assert cw.at_login()["results"] == []
    assert fake["retired"] == 0


def test_a_moved_folder_loses_its_switch(tmp_path, fake, monkeypatch):
    a = _ws(tmp_path, "a")
    wid = cw.listing()["workspaces"][0]["id"]
    cw.switch(wid, True)
    data = json.loads(cw._path().read_text())
    data["on"][wid] = str(tmp_path / "elsewhere")
    cw._path().write_text(json.dumps(data))
    monkeypatch.setattr(cw, "boot_time", lambda: 5)
    res = cw.at_login()
    assert res["results"][0]["error"] == "moved" and fake["starts"] == []
    assert a.is_dir()


def test_protected_folders(monkeypatch, tmp_path):
    monkeypatch.setattr(cw.Path, "home", lambda: tmp_path)
    assert cw.protected(tmp_path / "Documents" / "w")
    assert cw.protected(tmp_path / "Library" / "Mobile Documents" / "x")
    assert not cw.protected(tmp_path / "work" / "Documents")
    assert not cw.protected(tmp_path / "Documentsx")


def test_cli_answers_json_even_for_a_mistake(tmp_path, fake, capsys):
    args = argparse.Namespace(cmd="workspace", workspace_cmd="companion", action="start", id=None, state=None)
    assert cli_workspace.dispatch(args, tmp_path)
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["message"]


def test_login_start_fails_closed_without_a_boot_time(tmp_path, fake, monkeypatch):
    _ws(tmp_path, "a")
    cw.switch(cw.listing()["workspaces"][0]["id"], True)
    monkeypatch.setattr(cw, "boot_time", lambda: None)
    assert cw.at_login()["error"] == "no_boot"
    assert fake["starts"] == []


def test_a_switch_turned_off_while_waiting_starts_nothing(tmp_path, fake):
    _ws(tmp_path, "a")
    wid = cw.listing()["workspaces"][0]["id"]
    res = cw.start(wid, switched_on_only=True)  # the switch is off (default) when the lock is taken
    assert res["skipped"] == "switched_off" and fake["starts"] == []


def test_any_failure_is_one_fixed_json_line(tmp_path, fake, monkeypatch, capsys):
    _ws(tmp_path, "a")
    wid = cw.listing()["workspaces"][0]["id"]

    def boom(*a, **k):
        raise RuntimeError("secret=canary-123")

    monkeypatch.setattr(services, "start", boom)
    args = argparse.Namespace(cmd="workspace", workspace_cmd="companion", action="start", id=wid, state=None)
    cli_workspace.dispatch(args, tmp_path)
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "failed" and "canary" not in json.dumps(out)


@pytest.mark.parametrize("argv", [["nonsense"], ["switch", "x" * 32, "maybe"], []])
def test_wrong_words_through_the_real_parser_still_answer_json(tmp_path, fake, argv, capsys):
    from orch import cli

    p = cli.build_parser()
    args = p.parse_args(["workspace", "companion", *argv])
    cli_workspace.dispatch(args, tmp_path)
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["message"]

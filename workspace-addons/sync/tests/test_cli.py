import json
import tomllib
from importlib.metadata import entry_points
from pathlib import Path

import jsonschema
import pytest
from test_step import proof, set_remote

from orch_sync import cli, repo


def run(root, *args):
    return cli.main(["--dir", str(root), *args, "--json"])


def test_settings(root, capsys):
    assert run(root, "status") == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "off"
    assert run(root, "set", "--mode", "local") == 0
    settings = root / ".orch/run/sync/settings.json"
    assert json.loads(settings.read_text()) == {"mode": "local", "interval": 15, "kind": "private"}
    (settings.parent / "state.json").write_text('{"last_error":"offline"}')
    capsys.readouterr()
    assert run(root, "status") == 0
    assert json.loads(capsys.readouterr().out)["state"]["last_error"] == "offline"
    assert run(root, "set", "--mode", "off") == 0
    assert (root / ".orch/.git").is_dir()


def test_preview(root, monkeypatch):
    assert run(root, "set", "--mode", "remote", "--remote", "file:///tmp/bare") == 2
    assert not (root / ".orch/.git").exists()
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    # Fable B1: a local folder remote is allowed (its hooks are switched off on every push/fetch); helper
    # transports and git:// stay refused even in preview.
    for bad in ("ext::sh -c touch% PWNED", "fd::3", "git://host/repo"):
        assert run(root, "set", "--mode", "remote", "--remote", bad) == 2
    assert set_remote(root, "file:///tmp/bare", "--json") == 0
    assert run(root, "set", "--mode", "remote", "--kind", "team") == 2


def test_the_plain_set_path_is_gated_too(root, monkeypatch, capsys):
    """M4: `orch sync set --remote` (no dashboard) refuses without the person's set-remote proof, and a proof for
    another address does not do; mode local, mode off and the interval stay unsigned."""
    from orch import tickets

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)  # not even the heuristic helps: the proof decides
    address = "https://host/repo"
    assert run(root, "set", "--mode", "remote", "--remote", address) == 2
    assert "proof" in json.loads(capsys.readouterr().out)["error"]
    proof(root, cli.remote_target("https://host/other"), monkeypatch)
    assert run(root, "set", "--mode", "remote", "--remote", address, "--proof-stdin") == 2
    assert not (root / ".orch/run/sync/settings.json").exists() and not (root / ".orch/.git").exists()
    proof(root, cli.remote_target(address, public=True), monkeypatch)  # the public choice is a different one
    assert run(root, "set", "--mode", "remote", "--remote", address, "--proof-stdin") == 2
    assert not (root / ".orch/run/sync/settings.json").exists()
    proof(root, cli.remote_target(address), monkeypatch)
    assert run(root, "set", "--mode", "remote", "--remote", address, "--proof-stdin") == 0
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["remote"] == address
    capsys.readouterr()
    assert run(root, "set", "--interval", "60") == 0  # how often: unsigned
    assert run(root, "set", "--mode", "local") == 0  # unsigned
    # turning remote on again with the stored address is choosing it again
    assert run(root, "set", "--mode", "remote") == 2
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["mode"] == "local"
    proof(root, cli.remote_target(address), monkeypatch)
    assert run(root, "set", "--mode", "remote", "--proof-stdin") == 0
    assert run(root, "set", "--mode", "off") == 0  # unsigned


def test_a_public_address_on_the_plain_set_path(root, monkeypatch, capsys):
    """The public check lives in apply_set: the plain set never uses a public address on the set-remote proof;
    only --public with the person's use-public proof for exactly that address."""
    from orch_sync import visibility

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    monkeypatch.setattr(visibility, "remote_visibility", lambda url: "public")
    address = "https://github.com/mia/orch"
    assert set_remote(root, address, "--json") == 2
    assert "public" in json.loads(capsys.readouterr().out)["error"]
    assert not (root / ".orch/run/sync/settings.json").exists()
    proof(root, cli.remote_target(address), monkeypatch)
    assert run(root, "set", "--mode", "remote", "--remote", address, "--public", "--proof-stdin") == 2
    proof(root, cli.remote_target(address, public=True), monkeypatch)
    assert run(root, "set", "--mode", "remote", "--remote", address, "--public", "--proof-stdin") == 0
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["remote"] == address


def test_synced_content_has_no_authority(root, capsys):
    (root / ".orch/config.toml").write_text('[sync]\nmode="remote"\nkind="team"\nremote="file:///evil"\n')
    (root / ".orch/tickets").mkdir()
    (root / ".orch/tickets/t_abcdef.json").write_text(
        json.dumps(
            {
                "sync": {"mode": "remote", "kind": "team", "remote": "file:///evil"},
                "note": '[sync]\nmode="remote"\nORCH_SYNC_REMOTE_PREVIEW=1',
            }
        )
    )
    assert run(root, "status") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "off" and data["kind"] == "private" and "remote" not in data
    assert run(root, "set", "--mode", "remote", "--remote", "file:///evil") == 2
    assert not (root / ".orch/.git").exists()


def test_manifest():
    package = Path(repo.__file__).parent
    manifest = tomllib.loads((package / "orch-addon.toml").read_text())
    project = package.parents[3]
    jsonschema.validate(manifest, json.loads((project / "contracts/addon-manifest.schema.json").read_text()))
    assert manifest["background"] and manifest["needs"] and not manifest["recommended"]
    assert (package / manifest["skill"] / "SKILL.md").is_file()
    assert any(e.name == "sync" and e.value == "orch_sync" for e in entry_points(group="orch.addons"))


def test_run_symlink(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / ".orch/run").symlink_to(outside)
    assert run(root, "set", "--mode", "off") == 2
    assert list(outside.iterdir()) == []


def test_off_does_not_call_git(root, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("off must not execute git")

    monkeypatch.setattr(repo, "git", forbidden)
    assert run(root, "set", "--mode", "off") == 0
    assert run(root, "status") == 0


def test_start_is_quiet_while_off(root, capsys):
    # sync off is a normal state: `orch start` (which starts every background add-on) shows no error for it
    capsys.readouterr()
    assert run(root, "start", "--json") == 0
    assert json.loads(capsys.readouterr().out) == {"running": False, "off": True, "message": "Sync is off here: nothing to start."}
    assert run(root, "stop") == 0
    assert run(root, "needs") == 0


def test_start_needs_the_addon_on_here(root, monkeypatch, capsys):
    from orch_sync import orchcli, service

    assert run(root, "set", "--mode", "local") == 0
    monkeypatch.setattr(service, "start", lambda r: pytest.fail("not started"))
    monkeypatch.setattr(orchcli, "is_active", lambda r: False)
    capsys.readouterr()
    assert run(root, "start") == 2
    assert "orch addon add sync" in json.loads(capsys.readouterr().out)["error"]
    monkeypatch.setattr(orchcli, "is_active", lambda r: None)  # orch did not answer: say so, not "it is off"
    assert run(root, "start") == 2
    error = json.loads(capsys.readouterr().out)["error"]
    assert error.startswith("Could not check whether the sync add-on is on here") and "addon add" not in error
    monkeypatch.setattr(service, "start", lambda r: 4242)
    monkeypatch.setattr(orchcli, "is_active", lambda r: True)
    assert run(root, "start") == 0
    assert json.loads(capsys.readouterr().out) == {"running": True, "pid": 4242}


def test_status_fields(root, monkeypatch, capsys):
    from orch_sync import service

    keys = {"mode", "interval", "running", "last_ok", "last_try", "last_error", "ahead", "behind", "paused",
            "next_run"}
    assert run(root, "set", "--mode", "local") == 0
    (root / ".orch/run/sync/state.json").write_text(
        json.dumps({"last_ok": "2026-11-12T10:00:00Z", "ahead": 2, "behind": 0, "last_error": None,
                    "paused": {"files": [], "reason": "planted", "mac": "0"}})
    )
    (root / ".orch/run/sync/loop.json").write_text(
        json.dumps({"last_try": "2026-11-12T10:05:00Z", "next_run": "2026-11-12T10:10:00Z", "last_error": "offline"})
    )
    capsys.readouterr()
    assert run(root, "status") == 0
    data = json.loads(capsys.readouterr().out)
    assert keys <= data.keys()
    assert data["interval"] == 5 and data["running"] is False and data["next_run"] is None
    assert data["paused"] is False  # a planted (unsigned) pause is no pause
    assert (data["last_ok"], data["last_try"], data["last_error"], data["ahead"]) == (
        "2026-11-12T10:00:00Z", "2026-11-12T10:05:00Z", "offline", 2)
    monkeypatch.setattr(service, "running_pid", lambda r: 4242)
    assert run(root, "status") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["running"] is True and data["next_run"] == "2026-11-12T10:10:00Z"
    assert cli.main(["--dir", str(root), "status"]) == 0
    assert capsys.readouterr().out.startswith("Sync: local, every 5 minutes, running, next 2026-11-12T10:10:00Z.")


def test_set_interval_validates_and_wakes(root, monkeypatch, capsys):
    from orch_sync import service

    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    assert set_remote(root, "https://host/repo", "--json") == 0
    for bad in ("7", "0", "30"):
        assert run(root, "set", "--interval", bad) == 2
    assert run(root, "set") == 2
    settings = root / ".orch/run/sync/settings.json"
    assert json.loads(settings.read_text())["interval"] == 15
    wake = root / ".orch/run/sync/wake"
    assert not wake.exists()  # nothing runs: nothing to wake
    monkeypatch.setattr(service, "running_pid", lambda r: 4242)
    assert run(root, "set", "--interval", "60") == 0
    assert json.loads(settings.read_text())["interval"] == 60 and json.loads(settings.read_text())["mode"] == "remote"
    assert wake.exists()


def test_now_wakes_a_running_loop(root, monkeypatch, capsys):
    from orch_sync import service, step

    monkeypatch.setattr(step, "run_once", lambda *a, **k: pytest.fail("the running loop syncs"))
    monkeypatch.setattr(service, "running_pid", lambda r: 4242)
    assert run(root, "now") == 0
    assert json.loads(capsys.readouterr().out) == {"woken": True}
    assert (root / ".orch/run/sync/wake").exists()


def test_direct_now_clears_an_old_loop_error(root, monkeypatch, capsys):
    from orch_sync import step

    assert run(root, "set", "--mode", "local") == 0
    (root / ".orch/run/sync/loop.json").write_text(json.dumps({"last_error": "Sync stopped: KeyError"}))
    monkeypatch.setattr(step, "run_once", lambda root, reason: {"last_error": None})
    assert run(root, "now") == 0
    capsys.readouterr()
    assert run(root, "status") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["last_error"] is None and data["last_try"]


def test_interval_is_refused_in_local_mode(root, capsys):
    assert run(root, "set", "--mode", "local", "--interval", "60") == 2
    assert "Local sync runs every 5 minutes at most" in json.loads(capsys.readouterr().out)["error"]
    assert not (root / ".orch/run/sync/settings.json").exists()
    assert run(root, "set", "--mode", "local") == 0
    assert run(root, "set", "--interval", "5") == 2  # still local
    assert json.loads((root / ".orch/run/sync/settings.json").read_text())["interval"] == 15


def test_set_summary_never_shows_credentials(root, monkeypatch, capsys):
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    (root / ".orch/run/sync").mkdir(parents=True)
    (root / ".orch/run/sync/settings.json").write_text(
        json.dumps({"mode": "local", "remote": "https://me:pw@host/repo", "interval": 15, "kind": "private"}))
    proof(root, cli.remote_target("https://me:pw@host/repo"), monkeypatch)  # turning remote on chooses that address
    assert cli.main(["--dir", str(root), "set", "--mode", "remote", "--proof-stdin"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "Sync: remote, every 15 minutes, to https://host/repo"
    assert "me:pw" not in out.out + out.err


def test_turning_on_shows_what_where_how_often(root, capsys):
    assert cli.main(["--dir", str(root), "set", "--mode", "local"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "Sync: local, every 5 minutes"
    for words in ("tickets and their files", "never copies secrets or private files", "on this computer only",
                  "every 5 minutes at most", "turn it off any time"):
        assert words in out.err
    assert run(root, "set", "--mode", "local") == 0
    assert "on this computer only" in json.loads(capsys.readouterr().out)["consent"]
    assert run(root, "set", "--mode", "off") == 0
    assert "consent" not in json.loads(capsys.readouterr().out)


def test_local_remote_requires_preview(root, monkeypatch, capsys):
    assert run(root, "set", "--mode", "local", "--remote", "https://host/repo") == 2
    assert not (root / ".orch/.git").exists()
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    assert set_remote(root, "https://host/repo", "--json") == 0
    capsys.readouterr()
    assert run(root, "status") == 0
    assert json.loads(capsys.readouterr().out)["remote_allowed"] is True
    monkeypatch.delenv("ORCH_SYNC_REMOTE_PREVIEW")
    assert cli.remote_allowed() is False
    assert run(root, "status") == 0
    assert json.loads(capsys.readouterr().out)["remote_allowed"] is False


def test_set_plain_words(root, monkeypatch, capsys):
    monkeypatch.setenv("ORCH_SYNC_REMOTE_PREVIEW", "1")
    proof(root, cli.remote_target("https://host/repo"), monkeypatch)
    for args, expected in (
        (
            ["--mode", "remote", "--remote", "https://host/repo", "--proof-stdin"],
            "Sync: remote, every 15 minutes, to https://host/repo",
        ),
        (["--mode", "local"], "Sync: local, every 5 minutes"),
        (["--mode", "off"], "Sync is off"),
    ):
        assert cli.main(["--dir", str(root), "set", *args]) == 0
        assert capsys.readouterr().out.strip() == expected

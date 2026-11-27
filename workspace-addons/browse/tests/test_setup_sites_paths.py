import json
import tempfile
import tomllib
import types
from pathlib import Path

from orch_browse import cli, localnets, paths

MANIFEST = Path(cli.__file__).with_name("orch-addon.toml")


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def _fake_run(monkeypatch, returncode):
    ran = []
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda argv, **k: ran.append(argv) or types.SimpleNamespace(returncode=returncode, stdout=""),
    )
    return ran


def test_turn_on_runs_the_manifest_setup_and_a_person_downloads(ws, capsys, monkeypatch):
    m = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    for k in ("ORCH_RUN", "ORCH_AGENT"):
        monkeypatch.delenv(k, raising=False)
    ran = _fake_run(monkeypatch, 0)
    code, out = run(capsys, *m["setup"])
    assert code == 0 and "ready" in out
    assert ran and "install" in ran[0] and "--dry-run" not in ran[0]
    check = m["selfcheck"][0]["args"]
    assert check == ["setup", "--check"]


def test_a_failed_download_says_it_did_not_finish(ws, capsys, monkeypatch):
    monkeypatch.delenv("ORCH_RUN", raising=False)
    monkeypatch.delenv("ORCH_AGENT", raising=False)
    _fake_run(monkeypatch, 1)
    code, out = run(capsys, "setup")
    assert code == 2 and "did not finish" in out


def test_check_without_a_dry_run_answer_is_not_downloaded(capsys, monkeypatch):
    _fake_run(monkeypatch, 0)  # no "Install location" line
    assert run(capsys, "setup", "--check")[0] == 2


def test_sites_list_json_add_remove_and_damaged(ws, capsys, monkeypatch):
    for k in ("ORCH_RUN", "ORCH_AGENT"):
        monkeypatch.delenv(k, raising=False)
    code, out = run(capsys, "sites", "--ticket", "t_abc123")
    assert code == 0 and "empty" in out
    assert run(capsys, "sites", "add", "Example.com", "--ticket", "t_abc123")[0] == 0
    run(capsys, "sites", "add", "example.com", "docs.python.org", "--ticket", "t_abc123")
    code, out = run(capsys, "sites", "list", "--json", "--ticket", "t_abc123")
    assert json.loads(out)["sites"] == ["docs.python.org", "example.com"]
    run(capsys, "sites", "remove", "example.com", "--ticket", "t_abc123")
    assert paths.load_sites(ws, "t_abc123") == ["docs.python.org"]
    assert run(capsys, "sites", "add", "--ticket", "t_abc123")[0] == 2
    paths.sites_file(ws, "t_abc123").write_text("{nope", encoding="utf-8")
    code, out = run(capsys, "sites", "list", "--ticket", "t_abc123")
    assert code == 2 and "damaged" in out


def test_unknown_command_and_help_and_missing_workspace(tmp_path, capsys, monkeypatch):
    assert run(capsys, "help")[0] == 0
    monkeypatch.setenv("ORCH_ROOT", str(tmp_path))
    code, out = run(capsys, "nonsense")
    assert code == 2 and "orch init" in out
    (tmp_path / ".orch").mkdir()
    code, out = run(capsys, "nonsense")
    assert code == 2 and "Unknown command" in out


def test_save_sites_dedupes_and_leaves_no_temp_file(ws):
    paths.save_sites(ws, "t1", ["b.com", "a.com", "b.com"])
    assert paths.load_sites(ws, "t1") == ["a.com", "b.com"]
    assert [p.name for p in paths.sites_file(ws, "t1").parent.iterdir()] == ["t1.json"]


def test_clean_leftovers_deletes_only_an_own_temp_profile(ws, tmp_path):
    run_dir = paths.run_dir(ws, "t1")
    own = Path(tempfile.gettempdir()) / "orch-browse-test-leftover"
    own.mkdir(exist_ok=True)
    (run_dir / "profile.path").write_text(str(own), encoding="utf-8")
    paths.clean_leftovers(run_dir)
    assert not own.exists() and not (run_dir / "profile.path").exists()
    other = tmp_path / "orch-browse-elsewhere"
    other.mkdir()
    (run_dir / "profile.path").write_text(str(other), encoding="utf-8")
    paths.clean_leftovers(run_dir)
    assert other.exists() and not (run_dir / "profile.path").exists()
    paths.clean_leftovers(run_dir)  # nothing left: no error


def test_forget_run_removes_the_channel_files(ws):
    run_dir = paths.run_dir(ws, "t1")
    for n in ("profile.path", "channel.json"):
        (run_dir / n).write_text("x")
    paths.forget_run(run_dir)
    assert not (run_dir / "channel.json").exists() and not (run_dir / "profile.path").exists()
    paths.forget_run(run_dir)


def test_local_networks_drop_default_routes_and_duplicates(monkeypatch):
    import ipaddress as ip

    n = ip.ip_network
    monkeypatch.setattr(
        localnets, "_posix", lambda: [n("0.0.0.0/0"), n("10.0.0.0/24"), n("10.0.0.0/24"), n("10.0.0.5/32")]
    )
    monkeypatch.setattr(localnets.sys, "platform", "linux")
    assert localnets.local_networks() == [n("10.0.0.0/24"), n("10.0.0.5/32")]

    def boom():
        raise OSError("no libc")

    monkeypatch.setattr(localnets, "_posix", boom)
    assert localnets.local_networks() == []


def test_local_networks_include_loopback_on_this_machine():
    if localnets.sys.platform == "win32":
        return
    import ipaddress as ip

    assert ip.ip_network("127.0.0.1/32") in localnets.local_networks()

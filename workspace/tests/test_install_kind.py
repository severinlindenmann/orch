"""Install record (written by the installers), install_kind, ORCH_REPO/ORCH_REF gating (N6) and the test-only
launch URL (human-proof.md)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from orch import addons
from orch import humanproof as hp
from orch.errors import Refused

ROOT = Path(__file__).resolve().parents[2]


def _prefix(tmp_path, monkeypatch, record=None, kind=None):
    env = tmp_path / "toolenv"
    env.mkdir()
    if kind is not None:
        record = hp.install_record_text(kind, env)
    if record is not None:
        (env / "orch-install.json").write_text(record.replace("@ENV@", os.path.realpath(env)))
    monkeypatch.setattr(hp.sys, "prefix", str(env))
    return env


@pytest.mark.parametrize("kind", ["normal", "dev", "test"])
def test_record_format_roundtrip(tmp_path, monkeypatch, kind):
    env = _prefix(tmp_path, monkeypatch)
    text = hp.install_record_text(kind, env)
    assert json.loads(text) == {"schema": "orch.install/1", "kind": kind, "root": os.path.realpath(env)}
    (env / "orch-install.json").write_text(text)
    assert hp.install_kind() == kind


def test_bad_kinds_are_not_records(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        hp.install_record_text("admin", "/x")
    _prefix(tmp_path, monkeypatch, '{"kind": "admin", "root": "@ENV@"}')
    assert hp.read_install_record() is None


def test_missing_record_on_a_non_source_install_is_normal(tmp_path, monkeypatch):
    _prefix(tmp_path, monkeypatch)
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    assert hp.install_kind() == "normal"
    monkeypatch.setattr(hp, "_source_tree", lambda: True)
    assert hp.install_kind() == "test"  # running from the source tree, as the suite does


def test_installer_records_match_the_format(tmp_path):
    """install.sh's record line, run through sh, equals install_record_text."""
    for kind in ("normal", "test", "dev"):
        out = tmp_path / f"{kind}.json"
        line = [
            ln
            for ln in (ROOT / "install.sh").read_text().splitlines()
            if "orch-install.json" in ln and "printf" in ln
        ]
        assert len(line) == 1
        cmd = line[0].replace('"$TOOL_DIR/orch-install.json"', f"'{out}'")
        subprocess.run(["sh", "-c", f"KIND={kind}; ROOT={tmp_path}; {cmd}"], check=True)
        assert json.loads(out.read_text()) == json.loads(hp.install_record_text(kind, tmp_path))
    sh = (ROOT / "install.sh").read_text()
    assert "ORCH_INSTALL_KIND" in sh and "normal|dev|test" in sh
    ps = (ROOT / "install.ps1").read_text()
    assert "InstallKind" in ps and '"normal","dev","test"' in ps and "orch-install.json" in ps


@pytest.mark.skipif(shutil.which("uv") is None, reason="the installer would fetch uv")
def test_installer_rejects_a_bad_kind():
    r = subprocess.run(
        ["sh", "-c", 'ORCH_INSTALL_KIND=admin sh -c "$(sed -n 1,200p install.sh)" 2>&1 | tail -1'],
        cwd=ROOT, capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": "/nonexistent"},
    )  # fmt: skip
    assert "must be normal, dev or test" in r.stdout


def test_update_carries_the_record_over(tmp_path, monkeypatch):
    env = _prefix(tmp_path, monkeypatch, kind="dev")
    (env / "bin").mkdir()
    monkeypatch.setattr(addons, "run_uv", lambda args: (env / "orch-install.json").unlink())  # the reinstall
    monkeypatch.setattr(addons, "_tool_args", lambda entries: [])
    addons._install_tool([])
    assert hp.read_install_record() == "dev"


# ---------------------------------------------------------------- N6: ORCH_REPO / ORCH_REF


def test_normal_install_ignores_repo_and_ref(tmp_path, monkeypatch, capsys):
    src = tmp_path / "x"
    (src / "workspace").mkdir(parents=True)
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    monkeypatch.setenv("ORCH_REPO", str(src))
    monkeypatch.setenv("ORCH_REF", "evil")
    assert addons.repo() == addons.DEFAULT_REPO
    assert addons.ref() != "evil"
    assert not addons._is_local(addons.repo())
    assert "official source" in addons.ignored_source_note()


@pytest.mark.parametrize("kind", ["dev", "test"])
def test_dev_and_test_installs_honour_repo_and_ref(tmp_path, monkeypatch, kind):
    src = tmp_path / "x"
    (src / "workspace").mkdir(parents=True)
    monkeypatch.setattr(hp, "install_kind", lambda: kind)
    monkeypatch.setenv("ORCH_REPO", str(src))
    monkeypatch.setenv("ORCH_REF", "develop")
    assert addons.repo() == str(src) and addons.ref() == "develop" and addons._is_local(str(src))
    assert addons.ignored_source_note() is None


def test_update_with_proof_honours_them_on_a_normal_install(tmp_path, monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    monkeypatch.setenv("ORCH_REF", "v2")
    assert addons.ref() != "v2"
    with addons.trusted_env_source():
        assert addons.ref() == "v2"
    assert addons.ref() != "v2"


def test_addon_add_says_so_on_a_normal_install(proj, monkeypatch, capsys):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    monkeypatch.setenv("ORCH_REPO", "/tmp/x")
    with pytest.raises(Refused):
        addons.add(proj, "no-such-addon", yes=True)
    assert "ORCH_REPO / ORCH_REF are ignored" in capsys.readouterr().err


# ---------------------------------------------------------------- launch URL (test install only)


@pytest.fixture
def tws(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    ws = acct / ".orch-test" / "ws"
    (ws / ".orch").mkdir(parents=True)
    (acct / ".orch-test" / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    return ws


def test_launch_url_on_a_test_install(tws):
    url = hp.printable_launch_url(tws, "focus", "http://127.0.0.1:8123")
    token = url.split("#launch=")[1]
    assert url.startswith("http://127.0.0.1:8123/#launch=")
    rec = json.loads((hp.key_dir(tws) / "launch-focus.token").read_text())
    assert rec["token"] == token and 0 < rec["exp"] - __import__("time").time() <= hp.LAUNCH_LIFE
    assert oct((hp.key_dir(tws) / "launch-focus.token").stat().st_mode & 0o777) == "0o600"


def test_launch_url_refused_on_dev_normal_and_outside_the_test_folder(tws, tmp_path, monkeypatch):
    for kind in ("dev", "normal"):
        monkeypatch.setattr(hp, "install_kind", lambda k=kind: k)
        with pytest.raises(Refused, match="only on a test install"):
            hp.printable_launch_url(tws, "focus", "http://127.0.0.1:1")
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    other = tmp_path / "acct" / "real-ws"
    other.mkdir()
    with pytest.raises(Refused, match="only on a test install"):
        hp.printable_launch_url(other, "focus", "http://127.0.0.1:1")
    with pytest.raises(Refused):
        hp.write_launch_token(tws, "evil")


def test_start_refuses_print_launch_url_outside_test(proj, monkeypatch, run):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    code, out, err = run("start", "--no-open", "--print-launch-url")
    assert code == 2 and "only on a test install" in (out + err)


# ---------------------------------------------------------------- folder add-ons, tool env guard, json


def _folder_addon(tmp_path):
    f = tmp_path / "mine"
    f.mkdir()
    (f / "pyproject.toml").write_text('[project]\nname = "orch-mine"\nversion = "0.1.0"\n')
    return f


def test_normal_install_refuses_a_folder_addon_without_a_handoff(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    f = _folder_addon(tmp_path)
    with pytest.raises(Refused, match="only you can allow it"):
        addons.add(proj, str(f), yes=True)
    assert addons.registry() == []  # nothing recorded, nothing installed


def test_folder_addon_passes_the_core_check_on_dev_test_and_with_the_handoff(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    assert not addons._local_add_ok()
    with addons.trusted_local_add("a" * 64):
        assert addons._local_add_ok()
    assert not addons._local_add_ok()
    for kind in ("dev", "test"):
        monkeypatch.setattr(hp, "install_kind", lambda k=kind: k)
        assert addons._local_add_ok()
    assert "addon.add_local" in hp.OPS


def test_reinstall_needs_a_record_for_this_environment(tmp_path, monkeypatch):
    env = _prefix(tmp_path, monkeypatch)
    (env / "bin").mkdir()
    (env / "uv-receipt.toml").write_text("")  # a receipt is no trust anchor
    monkeypatch.setattr(addons, "run_uv", addons._REAL_RUN_UV)
    called = []
    monkeypatch.setattr(addons, "_tool_args", lambda e: called.append(1) or [])
    with pytest.raises(Refused, match="tool folder"):  # no record
        addons._install_tool([])
    (env / "orch-install.json").write_text(hp.install_record_text("normal", tmp_path / "other"))
    with pytest.raises(Refused, match="tool folder"):  # a record for another environment
        addons._install_tool([])
    assert not called


def test_reinstall_pins_uv_tool_dir_to_the_recorded_place(tmp_path, monkeypatch):
    env = _prefix(tmp_path, monkeypatch, kind="test")
    (env / "bin").mkdir()
    monkeypatch.setenv("UV_TOOL_DIR", "/agent/chosen")
    monkeypatch.setenv("XDG_DATA_HOME", "/agent/xdg")
    seen = []
    monkeypatch.setattr(addons, "run_uv", lambda a: seen.append(os.environ["UV_TOOL_DIR"]))
    monkeypatch.setattr(addons, "_tool_args", lambda e: [])
    addons._install_tool([])
    assert seen == [os.path.realpath(tmp_path)]  # dirname of the recorded root
    assert os.environ["UV_TOOL_DIR"] == "/agent/chosen"  # restored


def test_env_vars_do_not_steer_the_install_kind(tmp_path, monkeypatch):
    _prefix(tmp_path, monkeypatch, kind="normal")
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    before = hp.install_kind()
    monkeypatch.setenv("UV_TOOL_DIR", str(tmp_path / "x"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "y"))
    assert hp.install_kind() == before == "normal"


def test_record_for_another_root_is_ignored(tmp_path, monkeypatch):
    _prefix(tmp_path, monkeypatch, hp.install_record_text("test", tmp_path / "elsewhere"))
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    assert hp.read_install_record() is None and hp.install_kind() == "normal"
    _prefix_old = tmp_path / "toolenv" / "orch-install.json"
    _prefix_old.write_text('{"kind": "test"}')  # an old record without root
    assert hp.install_kind() == "normal"


def test_lane_c_layout_tool_env_under_orch_test_testnet(tmp_path, monkeypatch):
    """UV_TOOL_DIR under ~/.orch-test/testnet is legitimate: its record names that environment."""
    env = tmp_path / ".orch-test" / "testnet" / "tools" / "orch-workspace"
    env.mkdir(parents=True)
    (env / "orch-install.json").write_text(hp.install_record_text("test", env))
    monkeypatch.setattr(hp.sys, "prefix", str(env))
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    assert hp.install_kind() == "test"
    monkeypatch.setenv("UV_TOOL_DIR", str(env.parent))
    assert hp.install_kind() == "test"


def test_planted_folder_entry_is_not_installed_on_a_normal_install(tws, tmp_path, monkeypatch, capsys):
    proj = tws
    evil = _folder_addon(tmp_path)
    planted = [
        {"name": "mine", "source": str(evil), "version": "0.1.0"},  # no approval
        {"name": "relay", "source": "built-in", "version": "0.1.0"},
    ]
    snap = addons.prepare_local_add(proj, evil)
    kept = [
        {"name": "ok", "source": snap["snapshot"], "version": "0.1.0", "approved": True, "hash": snap["hash"]}
    ]
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    args = addons._tool_args(planted)
    assert str(evil) not in args and "--with" in args  # the built-in still goes in
    assert "only you can allow" in capsys.readouterr().err
    assert snap["snapshot"] in addons._tool_args(kept)  # a person's earlier hand-off stays
    monkeypatch.setattr(hp, "install_kind", lambda: "dev")
    assert str(evil) in addons._tool_args(planted)  # dev/test installs install any folder


def test_start_json_with_launch_urls_is_valid_json(proj, monkeypatch, capsys):
    from orch import cli, services

    monkeypatch.setattr(hp, "is_test_workspace", lambda r: True)
    monkeypatch.setattr(services, "start", lambda root: [{"addon": "focus", "url": "http://127.0.0.1:9"}])
    monkeypatch.setattr(hp, "printable_launch_url", lambda r, s, b: b + "/#launch=tok")
    assert cli.main(["start", "--json", "--print-launch-url"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["launch"] == [{"addon": "focus", "url": "http://127.0.0.1:9/#launch=tok"}]


def test_installers_print_a_visible_line_and_validate_the_kind():
    sh = (ROOT / "install.sh").read_text()
    ps = (ROOT / "install.ps1").read_text()
    assert "INSTALL: this orch is marked" in sh and "INSTALL: this orch is marked" in ps
    assert "ConvertTo-Json" in ps and "-notin" in ps and "ORCH_INSTALL_KIND" in ps


# ---------------------------------------------------------------- snapshots (content-bound approval)


def _real_addon(tmp_path, name="hello"):
    from test_addons import make_addon

    return make_addon(tmp_path, name)


def _capture_reinstall(monkeypatch):
    got = {}

    def fake(entries, **kw):
        got["entries"] = entries
        return True

    monkeypatch.setattr(addons, "_reinstall", fake)
    return got


def test_install_uses_the_snapshot_not_the_live_folder(tws, tmp_path, monkeypatch):
    f = _real_addon(tmp_path)
    snap = addons.prepare_local_add(tws, f)
    assert addons.local_add_target(tws, f) == snap["hash"] and snap["short"] == snap["hash"][:8]
    (f / "evil.py").write_text("print('swapped in after the click')")  # the live folder changes
    got = _capture_reinstall(monkeypatch)
    # the live folder now has another hash: the proof was for the old content
    with addons.trusted_local_add(snap["hash"]), pytest.raises(Refused, match="changed since you allowed"):
        addons.add(tws, str(f), yes=True)
    (f / "evil.py").unlink()  # content back as allowed: installs, from the snapshot
    with addons.trusted_local_add(snap["hash"]):
        addons.add(tws, str(f), yes=True)
    entry = got["entries"][-1]
    assert entry["source"] == snap["snapshot"] and entry["hash"] == snap["hash"] and entry["approved"] is True
    assert entry["folder"] == str(f.resolve())
    assert not (Path(snap["snapshot"]) / "evil.py").exists()


def test_tampered_snapshot_is_refused_on_reinstall(tws, tmp_path, monkeypatch, capsys):
    f = _real_addon(tmp_path)
    snap = addons.prepare_local_add(tws, f)
    entry = {
        "name": "hello",
        "source": snap["snapshot"],
        "version": "0.1.0",
        "approved": True,
        "hash": snap["hash"],
    }
    monkeypatch.setattr(hp, "install_kind", lambda: "normal")
    assert addons._missing_source(entry) is None
    (Path(snap["snapshot"]) / "evil.py").write_text("x = 1")  # tampered
    assert "changed since you allowed it" in addons._missing_source(entry)
    args = addons._tool_args([entry])
    assert snap["snapshot"] not in args and "left out" in capsys.readouterr().err
    # a hash that does not match the entry's folder name is no snapshot either
    entry2 = {**entry, "hash": "0" * 64, "source": str(f)}
    assert "changed since you allowed it" in addons._missing_source(entry2)


def test_snapshot_refuses_links_and_big_files(tws, tmp_path):
    f = _real_addon(tmp_path)
    (f / "link").symlink_to("/etc/passwd")
    with pytest.raises(Refused, match="link or a special file"):
        addons.prepare_local_add(tws, f)
    (f / "link").unlink()
    (f / "big.bin").write_bytes(b"0" * (5 * 1024 * 1024 + 1))
    with pytest.raises(Refused, match="cannot be read safely"):
        addons.prepare_local_add(tws, f)


def test_same_content_same_hash_and_build_output_ignored(tws, tmp_path):
    f = _real_addon(tmp_path)
    a = addons.prepare_local_add(tws, f)["hash"]
    (f / "build").mkdir()
    (f / "build" / "x").write_text("generated")
    assert addons.prepare_local_add(tws, f)["hash"] == a
    (f / "pyproject.toml").write_text("changed = 1")
    assert addons.prepare_local_add(tws, f)["hash"] != a

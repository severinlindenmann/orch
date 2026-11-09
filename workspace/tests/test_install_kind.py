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


def _prefix(tmp_path, monkeypatch, record=None):
    env = tmp_path / "toolenv"
    env.mkdir()
    if record is not None:
        (env / "orch-install.json").write_text(record)
    monkeypatch.setattr(hp.sys, "prefix", str(env))
    return env


@pytest.mark.parametrize("kind", ["normal", "dev", "test"])
def test_record_format_roundtrip(tmp_path, monkeypatch, kind):
    env = _prefix(tmp_path, monkeypatch)
    text = hp.install_record_text(kind)
    assert json.loads(text) == {"schema": "orch.install/1", "kind": kind}
    (env / "orch-install.json").write_text(text)
    assert hp.install_kind() == kind


def test_bad_kinds_are_not_records(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        hp.install_record_text("admin")
    _prefix(tmp_path, monkeypatch, '{"kind": "admin"}')
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
        subprocess.run(["sh", "-c", f"KIND={kind}; {cmd}"], check=True)
        assert json.loads(out.read_text()) == json.loads(hp.install_record_text(kind))
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
    env = _prefix(tmp_path, monkeypatch, hp.install_record_text("dev"))
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

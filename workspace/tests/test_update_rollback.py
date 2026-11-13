"""A failed update never removes orch: the old tool environment and bin entries come back, the reason is
recorded in plain words, and uv is pinned to the bin folder orch was installed to."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from orch import addons, winfinish
from orch import humanproof as hp
from orch.errors import Refused


def _install(tmp_path, monkeypatch):
    """A fake uv tool env (record + receipt) and its bin/orch link, like the installer leaves them."""
    tools = tmp_path / "tools"
    env = tools / "orch-workspace"
    (env / "bin").mkdir(parents=True)
    (env / "bin" / "orch").write_text("#!/bin/sh\necho old orch\n")
    (env / "bin" / "orch").chmod(0o755)
    (env / "lib.py").write_text("OLD = True\n")
    bindir = tmp_path / "home" / ".local" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "orch").symlink_to(env / "bin" / "orch")
    (env / "uv-receipt.toml").write_text(
        '[tool]\nentrypoints = [\n    { name = "orch", install-path = "%s", from = "orch-workspace" },\n]\n'
        % (bindir / "orch")
    )
    (env / "orch-install.json").write_text(hp.install_record_text("test", env))
    monkeypatch.setattr(hp.sys, "prefix", str(env))
    monkeypatch.setattr(hp, "_source_tree", lambda: False)
    monkeypatch.setattr(addons, "_tool_args", lambda e: ["tool", "install", "--reinstall"])
    return env, bindir


def _uv_removes_then_fails(env, bindir, message):
    """What uv did on lane C's run: the old env and bin/orch removed, then an error."""

    def run(args):
        shutil.rmtree(env)
        (bindir / "orch").unlink()
        raise Refused(f"uv failed: {message}")

    return run


@pytest.mark.parametrize(
    ("message", "words"),
    [
        ("error: Executable already exists: orch (use `--force` to overwrite)", "Another program named orch"),
        ("error: Failed to fetch: `https://github.com/x.zip` dns error", "No internet connection to GitHub"),
        ("error: something else", "The reinstall failed"),
    ],
)
def test_failed_reinstall_keeps_the_old_orch(tmp_path, monkeypatch, message, words):
    env, bindir = _install(tmp_path, monkeypatch)
    monkeypatch.setattr(addons, "run_uv", _uv_removes_then_fails(env, bindir, message))
    with pytest.raises(Refused) as e:
        addons._install_tool([])
    assert words in str(e.value) and "orch is still the old version" in str(e.value)
    assert (env / "lib.py").read_text() == "OLD = True\n" and (env / "orch-install.json").is_file()
    assert os.readlink(bindir / "orch") == str(env / "bin" / "orch")
    out = subprocess.run([str(bindir / "orch")], capture_output=True, text=True)
    assert out.stdout.strip() == "old orch"  # orch still runs
    assert not (tmp_path / "tools" / "orch-workspace.orch-backup").exists()  # no backup left behind
    log = winfinish.log_path(addons.home()).read_text()
    assert "uv failed:" in log and message.split(":")[1].strip()[:10] in log
    assert "RESULT fail: package reinstall: " + words in log


def test_good_reinstall_drops_the_backup_and_keeps_the_new_one(tmp_path, monkeypatch):
    env, bindir = _install(tmp_path, monkeypatch)

    def run(args):
        (env / "lib.py").write_text("NEW = True\n")

    monkeypatch.setattr(addons, "run_uv", run)
    addons._install_tool([])
    assert (env / "lib.py").read_text() == "NEW = True\n"
    assert not (tmp_path / "tools" / "orch-workspace.orch-backup").exists()
    assert "RESULT ok: package reinstall" in winfinish.log_path(addons.home()).read_text()


def test_uv_is_pinned_to_the_receipt_bin_dir(tmp_path, monkeypatch):
    """A service runs with the account's HOME: uv must still use the bin folder orch was installed to."""
    env, bindir = _install(tmp_path, monkeypatch)
    monkeypatch.setenv("UV_TOOL_BIN_DIR", "/agent/bin")
    seen = []
    monkeypatch.setattr(
        addons, "run_uv", lambda a: seen.append((os.environ["UV_TOOL_DIR"], os.environ["UV_TOOL_BIN_DIR"]))
    )
    addons._install_tool([])
    assert seen == [(os.path.realpath(env.parent), str(bindir))]
    assert os.environ["UV_TOOL_BIN_DIR"] == "/agent/bin"


def test_page_reason_from_the_update_log():
    from orch import pageproof

    tail = "uv failed: ...\nerror: Executable already exists: orch\nRefused: " + winfinish.plain_reason(
        "error: Failed to fetch", True
    )
    assert pageproof._short_reason(tail).startswith("No internet connection to GitHub")


def test_finisher_restores_the_old_orch_when_uv_fails(tmp_path):
    """Windows finisher: same keep-and-restore, the plain reason in RESULT, fail_reason_since passes it on."""
    env = tmp_path / "tools" / "orch-workspace"
    (env / "Scripts").mkdir(parents=True)
    (env / "keep.txt").write_text("old")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "orch.exe").write_text("old exe")
    (tmp_path / "finish.py").write_text(winfinish.FINISHER, encoding="utf-8")
    code = (
        "import shutil,sys,os; shutil.rmtree(sys.argv[1]); os.remove(sys.argv[2]); "
        "sys.stderr.write('error: Failed to fetch: dns error'); sys.exit(2)"
    )
    job = {
        "uv": [sys.executable, "-c", code, str(env), str(bindir / "orch.exe")],
        "free": [],
        "wait": 5,
        "uv_timeout": 30,
        "registry": None,
        "then": [],
        "backup": {"env": str(env), "bins": [str(bindir / "orch.exe")]},
        "log": str(tmp_path / "finish.log"),
        "done": "ok",
        "pending": str(tmp_path / "finish.pending"),
    }
    (tmp_path / "finish.pending").write_text("1")
    (tmp_path / "job.json").write_text(json.dumps(job))
    r = subprocess.run([sys.executable, "-I", str(tmp_path / "finish.py"), str(tmp_path / "job.json")])
    assert r.returncode == 1
    assert (env / "keep.txt").read_text() == "old" and (bindir / "orch.exe").read_text() == "old exe"
    log = (tmp_path / "finish.log").read_text()
    assert "uv failed: error: Failed to fetch" in log and "the old orch was put back" in log
    reason = winfinish.fail_reason_since(tmp_path, 0)
    assert reason.startswith("No internet connection to GitHub") and "still the old version" in reason
    assert not (tmp_path / "tools" / "orch-workspace.orch-backup").exists()


def test_plain_reason_when_nothing_could_be_put_back():
    assert "install script" in winfinish.plain_reason("anything", False)

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


def test_finisher_tries_again_when_orch_held_its_files(tmp_path):
    """A probe started orch while uv replaced it (Windows: Access is denied / Executable already exists):
    the old orch is put back and the reinstall runs again; the second try succeeds."""
    env = tmp_path / "tools" / "orch-workspace"
    (env / "Scripts").mkdir(parents=True)
    (env / "keep.txt").write_text("old")
    (tmp_path / "finish.py").write_text(winfinish.FINISHER, encoding="utf-8")
    flag = tmp_path / "tried"
    code = (
        "import os,sys,shutil; f=sys.argv[1]\n"
        "if not os.path.exists(f):\n"
        "    open(f,'w').close(); shutil.rmtree(sys.argv[2])\n"
        "    sys.stderr.write('error: Executable already exists: orch.exe (use `--force` to overwrite)')\n"
        "    sys.exit(2)\n"
        "open(os.path.join(sys.argv[2],'new.txt'),'w').write('new')\n"
    )
    job = {
        "uv": [sys.executable, "-c", code, str(flag), str(env)],
        "free": [str(env)],
        "wait": 5,
        "uv_timeout": 30,
        "registry": None,
        "then": [],
        "backup": {"env": str(env), "bins": []},
        "log": str(tmp_path / "finish.log"),
        "done": "orch updated",
        "pending": str(tmp_path / "finish.pending"),
    }
    (tmp_path / "finish.pending").write_text("1")
    (tmp_path / "job.json").write_text(json.dumps(job))
    r = subprocess.run([sys.executable, "-I", str(tmp_path / "finish.py"), str(tmp_path / "job.json")])
    log = (tmp_path / "finish.log").read_text()
    assert r.returncode == 0, log
    assert "trying again (2 of 3)" in log and log.rstrip().endswith("RESULT ok: orch updated")
    assert (env / "keep.txt").read_text() == "old" and (env / "new.txt").read_text() == "new"
    assert not (tmp_path / "tools" / "orch-workspace.orch-backup").exists()


def test_a_failed_restore_keeps_the_copy(tmp_path):
    from orch import keepold

    env = tmp_path / "env"
    env.mkdir()
    (env / "a").write_text("old")
    state = keepold.backup_tool(env, [])
    shutil.rmtree(env)
    os.rename(state["bak"], tmp_path / "moved")  # restore can not work now
    assert keepold.restore_tool(state, wait=0) is False
    os.rename(tmp_path / "moved", state["bak"])
    assert keepold.restore_tool(state, wait=1) is True and (env / "a").read_text() == "old"


def test_locked_failures_are_recognised():
    from orch import keepold

    assert keepold.locked_failure("failed to remove directory `C:\\x`: Access is denied. (os error 5)")
    assert keepold.locked_failure("error: Executable already exists: orch.exe (use `--force` to overwrite)")
    assert not keepold.locked_failure("error: Failed to fetch: dns error")


def test_stand_in_answers_while_orch_entry_is_gone(tmp_path, monkeypatch):
    """The uv window: orch_entry gone from site-packages; the .pth stand-in says still updating."""
    import orch_entry

    prefix = tmp_path / "env"
    site = prefix / "site"
    site.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text("")
    monkeypatch.setattr(orch_entry.sys, "prefix", str(prefix))
    import sysconfig

    monkeypatch.setattr(sysconfig, "get_paths", lambda: {"purelib": str(site)})
    orch_entry.ensure_stand_in()
    folder = (site / orch_entry.STAND_IN_PTH).read_text().strip()
    code = (
        "import sys; sys.path.append(sys.argv[1]); sys.argv = ['orch', *sys.argv[2:]]; "
        "import orch_entry; sys.exit(orch_entry.main())"
    )
    py = [sys.executable, "-I", "-S", "-c", code, folder]
    r = subprocess.run([*py, "status"], capture_output=True, text=True)
    assert r.returncode == 3 and "still updating" in r.stderr and "Traceback" not in r.stderr
    r = subprocess.run([*py, "record", "hook"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == ""
    r = subprocess.run([*py, "record", "--by", "x", "hook", "--strict"], capture_output=True, text=True)
    assert r.returncode == 2 and r.stderr == "Refused: nothing was recorded.\n"
    for other in (["record", "auth"], ["record"], ["--json", "record", "hook"]):  # not a hook call: no pass
        r = subprocess.run([*py, *other], capture_output=True, text=True)
        assert r.returncode == 3 and "still updating" in r.stderr, other
    monkeypatch.setattr(orch_entry.sys, "prefix", str(tmp_path / "dev-venv"))  # not a uv tool env: nothing
    (tmp_path / "dev-venv").mkdir()
    (site / orch_entry.STAND_IN_PTH).unlink()
    orch_entry.ensure_stand_in()
    assert not (site / orch_entry.STAND_IN_PTH).exists()


def test_reinstall_swaps_orch_packages_in_place(tmp_path, monkeypatch):
    """With a receipt, uv reinstalls orch's own packages by name (no whole-env --reinstall that removes the
    Scripts folder while an orch runs); without one, the whole env as before."""
    env = tmp_path / "orch-workspace"
    env.mkdir()
    monkeypatch.setattr(addons.sys, "prefix", str(env))
    assert addons._reinstall_flags() == ["--reinstall"]
    (env / "uv-receipt.toml").write_text(
        "[tool]\nrequirements = [\n"
        '    { name = "orch-workspace", url = "https://x/a.zip", subdirectory = "workspace" },\n'
        '    { name = "orch-dashboard", url = "https://github.com/x/orch/archive/abc.zip" },\n'
        '    { name = "--evil" },\n'
        "]\n"
    )
    assert addons._reinstall_flags() == [
        "--reinstall-package",
        "orch-workspace",
        "--reinstall-package",
        "orch-dashboard",
    ]
    args = addons._tool_args([])
    assert "--reinstall" not in args
    assert args[:4] == ["tool", "install", "--reinstall-package", "orch-workspace"]


def test_addon_add_or_remove_restarts_what_runs(tmp_path, monkeypatch):
    """An add-on add/remove replaces the shared tool env: running services (still on the old files) are
    restarted like after an update; the update itself restarts in its project step (no second restart)."""
    monkeypatch.setattr(winfinish, "needed", lambda: False)
    monkeypatch.setattr(addons, "tool_env_change_ok", lambda: None)
    monkeypatch.setattr(addons, "_install_tool", lambda entries: None)
    monkeypatch.setattr(addons, "_save_registry", lambda entries: None)
    seen = []
    monkeypatch.setattr(addons, "_restart_updated", lambda root=None: seen.append(root) or ["Restarted"])
    assert addons._reinstall([], save=True, then=[], root=tmp_path, done="x") is True
    assert seen == [tmp_path]
    addons._reinstall([], save=False, then=[], root=tmp_path, done="orch updated", restart=False)
    assert seen == [tmp_path]


def test_tool_args_keep_the_python(tmp_path, monkeypatch):
    """Both reinstall forms (whole env, and #679's per package) carry the --python pin."""
    exe = tmp_path / "py" / "python3.11"
    exe.parent.mkdir()
    exe.write_text("")
    monkeypatch.setattr(addons.sys, "_base_executable", str(exe))
    env = tmp_path / "orch-workspace"
    env.mkdir()
    monkeypatch.setattr(addons.sys, "prefix", str(env))
    for receipt in (None, '[tool]\nrequirements = [{ name = "orch-workspace" }]\n'):
        if receipt:
            (env / "uv-receipt.toml").write_text(receipt)
        args = addons._tool_args([])
        i = args.index("--python")
        assert args[i + 1] == str(exe)

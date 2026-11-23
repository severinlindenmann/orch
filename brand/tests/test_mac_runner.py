"""This Mac's own CI runner (ORCH-1125): the route, the wiring in the workflows, the shared lock and the job hook."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import time
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
RUNNER = ROOT / "scripts" / "mac-runner"
REPO = "severinlindenmann/orch"

spec = importlib.util.spec_from_file_location("mac_route", ROOT / "scripts" / "mac_route.py")
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)


def _runner(status="online", busy=False, label="orch-mac"):
    return {"status": status, "busy": busy, "labels": [{"name": "self-hosted"}, {"name": label}]}


# --- which runs may reach the Mac -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event,ref,base,head,ok",
    [
        ("push", "refs/heads/develop", "", "", True),
        ("schedule", "refs/heads/develop", "", "", True),
        ("workflow_dispatch", "refs/heads/develop", "", "", True),
        ("pull_request", "refs/pull/9/merge", "main", REPO, True),
        ("push", "refs/heads/main", "", "", False),
        ("push", "refs/heads/feat/x", "", "", False),
        ("pull_request", "refs/pull/9/merge", "develop", REPO, False),  # ordinary pull request and queue groups
        ("pull_request", "refs/pull/9/merge", "main", "someone/orch", False),  # a fork, even into main
        ("pull_request", "refs/pull/9/merge", "main", "", False),
        ("pull_request_target", "refs/heads/develop", "main", REPO, False),
        ("", "", "", "", False),
    ],
)
def test_only_develop_pushes_nightly_manual_and_release_pull_requests_are_trusted(event, ref, base, head, ok):
    assert mr.trusted(event, ref, base, head, REPO)[0] is ok


# --- online, offline, busy --------------------------------------------------------------------------------------


def test_an_offline_or_missing_runner_sends_the_jobs_to_github():
    assert mr.pick([], "push", "")[0] is False
    assert mr.pick([_runner(status="offline")], "schedule", "")[0] is False
    assert mr.pick([_runner(label="other")], "schedule", "")[0] is False


def test_a_busy_runner_sends_a_develop_push_to_github_but_the_nightly_and_releases_wait():
    busy = [_runner(busy=True)]
    assert mr.pick(busy, "push", "")[0] is False
    assert mr.pick(busy, "push", "wait")[0] is True
    assert mr.pick(busy, "schedule", "")[0] is True
    assert mr.pick(busy, "pull_request", "")[0] is True
    assert mr.pick([_runner()], "push", "")[0] is True


def _env(**kw):
    env = {"MAC_RUNNER": "this-mac", "EVENT": "push", "REF": "refs/heads/develop", "REPO": REPO, "STATUS_TOKEN": "t"}
    env.update(kw)
    return env


def test_the_one_setting_moves_every_job_back_to_github():
    called = []
    for value in ("", "github", "off", "This-Mac"):
        use, why = mr.route(_env(MAC_RUNNER=value), fetch=lambda *a: called.append(a) or [_runner()])
        assert use is False and "MAC_RUNNER" in why
    assert not called  # nobody even asks GitHub
    assert mr.route(_env(), fetch=lambda *a: [_runner()])[0] is True


def test_no_status_key_or_no_answer_from_github_means_github_machines():
    assert mr.route(_env(STATUS_TOKEN=""), fetch=lambda *a: [_runner()])[0] is False

    def broken(*a):
        raise OSError("down")

    use, why = mr.route(_env(), fetch=broken)
    assert use is False and "did not answer" in why


def test_an_untrusted_run_never_reads_the_runner_list():
    def boom(*a):
        raise AssertionError("must not be called")

    assert mr.route(_env(EVENT="pull_request", BASE_REF="develop", HEAD_REPO=REPO), fetch=boom)[0] is False


def test_outputs_are_runs_on_json():
    on, off = mr.outputs(True, "x"), mr.outputs(False, "y")
    assert json.loads(on["mac"]) == ["self-hosted", "orch-mac"] == json.loads(on["linux"])
    assert json.loads(off["mac"]) == "macos-latest" and json.loads(off["linux"]) == "ubuntu-latest"
    assert (on["where"], off["where"]) == ("mac", "github")


def test_main_writes_outputs_and_never_fails(tmp_path, monkeypatch):
    out = tmp_path / "out"
    env = {"GITHUB_OUTPUT": str(out), "PATH": os.environ.get("PATH", ""), "MAC_RUNNER": "this-mac", "EVENT": "push",
           "REF": "refs/heads/develop", "REPO": REPO}  # no token: falls back, exit 0
    r = subprocess.run(["python3", str(ROOT / "scripts" / "mac_route.py")], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert lines["where"] == "github" and json.loads(lines["mac"]) == "macos-latest"


# --- wiring in the workflow files -------------------------------------------------------------------------------

CI = (WF / "ci.yml").read_text()


def _job(text: str, name: str) -> str:
    m = re.search(rf"^  {re.escape(name)}:\n((?:    .*\n|\s*\n)*)", text, re.MULTILINE)
    assert m, name
    return m.group(1)


def test_no_workflow_names_the_mac_runner_itself():
    """Only scripts/mac_route.py picks this Mac; a hard-coded self-hosted job would run whatever reached it."""
    for f in WF.glob("*.yml"):
        for line in f.read_text().splitlines():
            if line.strip().startswith("runs-on:"):
                assert "self-hosted" not in line and "orch-mac" not in line, (f.name, line)


@pytest.mark.parametrize(
    "file,job,inp",
    [
        ("mobile.yml", "test", "inputs.runs_on"),
        ("dash-shots.yml", "shots", "inputs.runs_on"),
        ("addons.yml", "py311", "inputs.mac_jobs_runs_on"),
        ("addons.yml", "page-smoke", "inputs.mac_jobs_runs_on"),
        ("addons.yml", "dashboard-clickthroughs", "inputs.mac_jobs_runs_on"),
    ],
)
def test_each_mac_job_takes_its_machine_from_the_route_and_gets_a_throwaway_home(file, job, inp):
    body = _job((WF / file).read_text(), job)
    assert f"runs-on: ${{{{ fromJSON({inp}) }}}}" in body
    assert "uses: ./.github/actions/mac-job-home" in body


def test_the_macos_workspace_part_follows_the_route_as_one_part():
    ws = (WF / "workspace.yml").read_text()
    assert "runs-on: ${{ matrix.runs_on }}" in ws and "timeout-minutes: ${{ matrix.limit }}" in ws
    assert 'parts["macos-latest"] = 1 if own_mac else 5' in ws
    assert "uses: ./.github/actions/mac-job-home" in _job(ws, "test")


def test_ci_passes_the_route_to_every_mac_job():
    route = _job(CI, "route")
    assert "continue-on-error: true" in route and "python3 scripts/mac_route.py" in route
    assert "steps.r.outputs.mac || '\"macos-latest\"'" in route  # a broken route still sends jobs to GitHub
    assert "vars.MAC_RUNNER }}" in route and "vars.MAC_RUNNER_WHEN_BUSY" in route
    mac, linux = "needs.route.outputs.mac || '\"macos-latest\"'", "needs.route.outputs.linux || '\"ubuntu-latest\"'"
    for job, line in [("mobile", f"runs_on: ${{{{ {mac} }}}}"),
                      ("workspace", f"mac_runs_on: ${{{{ {mac} }}}}"),
                      ("addons", f"mac_jobs_runs_on: ${{{{ {linux} }}}}"),
                      ("dash-shots", f"runs_on: ${{{{ {linux} }}}}")]:
        body = _job(CI, job)
        assert line in body and re.search(r"^    needs: \[changes, route\]$", body, re.MULTILINE), job
        # a failed route job must not skip the Mac jobs: they run on GitHub's machines then
        assert "if: ${{ !cancelled() && needs.changes.result == 'success' && (" in body, job


def test_the_final_check_does_not_wait_for_the_route():
    assert "route" not in re.search(r"^  gate:\n(?:    .*\n)*?    needs: \[(.*)\]", CI, re.MULTILINE).group(1)


def test_the_status_key_never_reaches_a_pull_request_into_develop():
    route = _job(CI, "route")
    m = re.search(r"STATUS_TOKEN: \$\{\{ (.*) \}\}", route)
    assert m
    cond = m.group(1)
    assert "github.event_name != 'pull_request'" in cond and "github.base_ref == 'main'" in cond
    assert "head.repo.full_name == github.repository" in cond and cond.endswith("|| ''")


def test_the_phone_build_takes_the_xcode_lock_on_the_mac():
    assert "lock.sh run xcode" in (WF / "mobile.yml").read_text()


# --- the shared lock --------------------------------------------------------------------------------------------


def _lock(tmp_path, *args, **env):
    e = {"PATH": os.environ.get("PATH", ""), "ORCH_LOCK_DIR": str(tmp_path / "locks"), "ORCH_LOCK_POLL_SECS": "0.2"}
    e.update(env)
    return subprocess.run(["bash", str(RUNNER / "lock.sh"), *args], env=e, capture_output=True, text=True, timeout=60)


def test_lock_runs_one_at_a_time(tmp_path):
    marks = tmp_path / "marks"
    cmd = f"echo start >> {marks}; sleep 1; echo end >> {marks}"
    e = {"PATH": os.environ.get("PATH", ""), "ORCH_LOCK_DIR": str(tmp_path / "locks"), "ORCH_LOCK_POLL_SECS": "0.2"}
    procs = [subprocess.Popen(["bash", str(RUNNER / "lock.sh"), "run", "xcode", f"t{i}", "--", "sh", "-c", cmd], env=e)
             for i in range(2)]
    assert [p.wait(timeout=30) for p in procs] == [0, 0]
    assert marks.read_text().split() == ["start", "end", "start", "end"]
    assert "free" in _lock(tmp_path, "status").stdout


def test_lock_held_by_a_dead_process_is_taken_over_and_release_needs_the_tag(tmp_path):
    dead = subprocess.Popen(["true"]); dead.wait()
    assert _lock(tmp_path, "acquire", "heavy", "runner", str(dead.pid)).returncode == 0
    r = _lock(tmp_path, "run", "heavy", "helper", "--", "true")
    assert r.returncode == 0 and "stale" in r.stderr
    live = subprocess.Popen(["sleep", "30"])
    try:
        assert _lock(tmp_path, "acquire", "heavy", "runner", str(live.pid)).returncode == 0
        assert _lock(tmp_path, "release", "heavy", "someone-else").returncode == 0
        assert "tag=runner" in _lock(tmp_path, "status").stdout
        r = _lock(tmp_path, "run", "heavy", "helper", "--", "true", ORCH_LOCK_WAIT_SECS="1")
        assert r.returncode == 75 and "gave up" in r.stderr
        _lock(tmp_path, "release", "heavy", "runner")
        assert "heavy: free" in _lock(tmp_path, "status").stdout
    finally:
        live.kill()


def test_lock_refuses_an_unknown_name(tmp_path):
    assert _lock(tmp_path, "run", "gpu", "t", "--", "true").returncode == 2


# --- the job hook on the machine --------------------------------------------------------------------------------


def _hook(tmp_path, event, ref="refs/heads/develop", pr=None, repo=REPO):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": pr} if pr else {}))
    env = {"PATH": os.environ.get("PATH", ""), "ORCH_RUNNER_REPO": REPO, "GITHUB_REPOSITORY": repo,
           "GITHUB_EVENT_NAME": event, "GITHUB_REF": ref, "GITHUB_EVENT_PATH": str(ev),
           "ORCH_LOCK_DIR": str(tmp_path / "locks"), "ORCH_LOCK_POLL_SECS": "0.2", "ORCH_LOCK_WAIT_SECS": "5"}
    return subprocess.run(["bash", str(RUNNER / "job-started.sh")], env=env, capture_output=True, text=True, timeout=30)


def _pr(base, head):
    return {"base": {"ref": base}, "head": {"repo": {"full_name": head}}}


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="the hook uses the system python3")
@pytest.mark.parametrize(
    "event,ref,pr,repo,ok",
    [
        ("push", "refs/heads/develop", None, REPO, True),
        ("schedule", "refs/heads/develop", None, REPO, True),
        ("pull_request", "refs/pull/1/merge", _pr("main", REPO), REPO, True),
        ("pull_request", "refs/pull/1/merge", _pr("main", "someone/orch"), REPO, False),
        ("pull_request", "refs/pull/1/merge", _pr("develop", REPO), REPO, False),
        ("push", "refs/heads/feat/x", None, REPO, False),
        ("push", "refs/heads/develop", None, "someone/orch", False),
        ("pull_request_target", "refs/heads/develop", None, REPO, False),
    ],
)
def test_the_job_hook_refuses_what_must_never_run_on_the_mac(tmp_path, event, ref, pr, repo, ok):
    r = _hook(tmp_path, event, ref, pr, repo)
    assert (r.returncode == 0) is ok, r.stdout + r.stderr
    if ok:
        assert (tmp_path / "locks" / "heavy" / "holder").exists()
    else:
        assert "refused" in r.stderr and not (tmp_path / "locks" / "heavy").exists()


def test_scripts_parse():
    for f in [*RUNNER.glob("*.sh"), RUNNER / "bash"]:
        assert subprocess.run(["bash", "-n", str(f)], capture_output=True).returncode == 0, f.name


def test_a_stale_lock_is_taken_over_by_exactly_one_waiter(tmp_path):
    dead = subprocess.Popen(["true"])
    dead.wait()
    assert _lock(tmp_path, "acquire", "xcode", "gone", str(dead.pid)).returncode == 0
    marks = tmp_path / "marks"
    cmd = f"echo start >> {marks}; sleep 0.5; echo end >> {marks}"
    e = {"PATH": os.environ.get("PATH", ""), "ORCH_LOCK_DIR": str(tmp_path / "locks"), "ORCH_LOCK_POLL_SECS": "0.1"}
    procs = [subprocess.Popen(["bash", str(RUNNER / "lock.sh"), "run", "xcode", f"w{i}", "--", "sh", "-c", cmd], env=e,
                              stderr=subprocess.DEVNULL) for i in range(4)]
    assert [p.wait(timeout=60) for p in procs] == [0, 0, 0, 0]
    assert marks.read_text().split() == ["start", "end"] * 4


def test_lock_age_ignores_a_stat_report_that_is_not_a_number(tmp_path):
    # Linux: when the lock folder vanishes mid-check, `stat -c` fails and the BSD fallback `stat -f` is GNU's
    # file-system mode, which prints a "File: ..." report. That text must never reach the age arithmetic (it made a
    # waiter exit 1 under set -u, red develop CI in ORCH-1538).
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "stat").write_text('#!/bin/sh\ncase $1 in -c) exit 1;; esac\necho "  File: \\"$3\\""\necho "    ID: 1"\n')
    (fake / "stat").chmod(0o755)
    holder = subprocess.Popen(["sleep", "30"])
    try:
        assert _lock(tmp_path, "acquire", "xcode", "live", str(holder.pid)).returncode == 0
        r = _lock(tmp_path, "run", "xcode", "w", "--", "true", PATH=f"{fake}:{os.environ.get('PATH', '')}",
                  ORCH_LOCK_WAIT_SECS="1")
        assert r.returncode == 75, r.stderr
        assert "unbound" not in r.stderr and "syntax error" not in r.stderr
    finally:
        holder.kill()
        holder.wait()


def test_lock_does_not_follow_a_planted_holder_link(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    (tmp_path / "locks" / "heavy").mkdir(parents=True)
    (tmp_path / "locks" / "heavy" / "holder").symlink_to(victim)
    os.utime(tmp_path / "locks" / "heavy", (0, 0))  # old: stale
    assert _lock(tmp_path, "run", "heavy", "t", "--", "true").returncode == 0
    assert victim.read_text() == "keep"


def test_the_runner_settings_live_in_the_root_owned_start_entry_not_in_the_runner_folder():
    setup = (RUNNER / "setup.sh").read_text()
    assert '> "$R/.env"' not in setup and "ACTIONS_RUNNER_HOOK_JOB_STARTED</key>" in setup


def test_a_refused_job_is_stopped_not_only_failed_and_the_job_cannot_switch_the_hook():
    hook = (RUNNER / "job-started.sh").read_text()
    assert 'kill -9 "$worker"' in hook and "Runner.Worker" in hook
    assert "ORCH_HOOK_TEST" not in hook  # no switch a job's own environment could set
    assert 'if [ -f "$HERE/repo" ]; then REPO=$(cat "$HERE/repo"); unset ORCH_LOCK_DIR' in hook
    # only the root-owned installed copy stops the job (no job can make a root-owned file)
    assert '-user 0' in hook[hook.index("refuse() {") : hook.index('kill -9 "$worker"')]


def test_a_refused_job_run_from_the_repository_never_stops_its_runner_worker(tmp_path):
    """On GitHub's machines these tests run inside a real Runner.Worker: a refused hook killed the CI job itself."""
    ev = tmp_path / "event.json"
    ev.write_text("{}")
    env = {"PATH": os.environ.get("PATH", ""), "ORCH_RUNNER_REPO": REPO, "GITHUB_REPOSITORY": REPO,
           "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/feat/x", "GITHUB_EVENT_PATH": str(ev),
           "ORCH_LOCK_DIR": str(tmp_path / "locks")}
    hook = str(RUNNER / "job-started.sh")
    # a parent process whose command line names Runner.Worker, like the runner's own worker
    r = subprocess.run(["bash", "-c", 'exec -a Runner.Worker bash -c "bash \\"$0\\"; echo worker-alive"', hook],
                       env=env, capture_output=True, text=True, timeout=30)
    assert "refused" in r.stderr and "worker-alive" in r.stdout, (r.stdout, r.stderr)


def test_installed_hook_ignores_a_repository_named_by_the_job(tmp_path):
    inst = tmp_path / "hooks"
    inst.mkdir()
    for f in ("job-started.sh", "lock.sh"):
        (inst / f).write_text((RUNNER / f).read_text())
    (inst / "repo").write_text(REPO + "\n")
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": _pr("main", "someone/orch")}))
    env = {"PATH": os.environ.get("PATH", ""), "ORCH_RUNNER_REPO": "someone/orch", "GITHUB_REPOSITORY": REPO,
           "GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/1/merge", "GITHUB_EVENT_PATH": str(ev)}
    r = subprocess.run(["bash", str(inst / "job-started.sh")], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "fork" in r.stderr


def test_the_clean_up_hook_never_acts_as_a_person():
    """It stops every other process of its user; run by a helper it would stop the helper's whole session."""
    hook = (RUNNER / "job-completed.sh").read_text()
    guard = hook.index('[ "$(id -un)" = orch-ci ] ||')
    assert guard < hook.index("kill ") and guard < hook.index("trap ")
    r = subprocess.run(["bash", str(RUNNER / "job-completed.sh")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "did nothing" in r.stderr


def test_lock_numbers_from_the_environment_are_never_run_as_code(tmp_path):
    flag = tmp_path / "ran"
    r = _lock(tmp_path, "status", ORCH_LOCK_TTL_MIN=f"a[$(touch {flag})]", ORCH_LOCK_WAIT_SECS=f"x[$(touch {flag})]")
    assert r.returncode == 0 and not flag.exists()


@pytest.mark.parametrize("name", ["job-started.sh", "job-completed.sh"])
def test_functions_from_the_job_s_environment_never_replace_a_command_in_the_hooks(tmp_path, name):
    """A job sets its own environment; bash loads exported functions from it (Codex review, ORCH-1125)."""
    flag = tmp_path / "hijacked"
    ev = tmp_path / "event.json"
    ev.write_text("{}")
    env = {"PATH": os.environ.get("PATH", ""), "ORCH_RUNNER_REPO": REPO, "GITHUB_REPOSITORY": REPO,
           "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/feat/x", "GITHUB_EVENT_PATH": str(ev),
           "ORCH_LOCK_DIR": str(tmp_path / "locks")}
    for cmd in ("find", "ps", "kill", "id", "cat", "dirname", "tr"):
        env[f"BASH_FUNC_{cmd}%%"] = f"() {{ echo x >> {flag}; }}"
    env["SHELLOPTS"] = "privileged"  # would make the first start look like the clean one if the hook trusted $-
    r = subprocess.run(["bash", str(RUNNER / name)], env=env, capture_output=True, text=True, timeout=30)
    assert not flag.exists(), (r.stdout, r.stderr)
    assert ("refused" if name == "job-started.sh" else "did nothing") in r.stderr


def test_installed_hooks_use_a_fixed_path():
    for name in ("job-started.sh", "job-completed.sh"):
        assert "PATH=/usr/bin:/bin:/usr/sbin:/sbin" in (RUNNER / name).read_text(), name


# --- security review ORCH-1233: nothing of a job runs before the hook, a fresh runner per job, no private network ---


def _install_shim(tmp_path):
    """The installed layout: <base>/bin/bash (the shim) next to <base>/job-started.sh and job-completed.sh."""
    base = tmp_path / "base"
    (base / "bin").mkdir(parents=True)
    shim = base / "bin" / "bash"
    shim.write_text((RUNNER / "bash").read_text())
    shim.chmod(0o755)
    return base, shim


@pytest.mark.skipif(not Path("/bin/bash").exists() or not Path("/usr/bin/env").exists(), reason="needs /bin/bash")
def test_settings_of_the_job_never_run_before_the_hook(tmp_path):
    """The runner starts a hook as `bash --noprofile --norc -e -o pipefail <hook>` with the job's environment."""
    base, shim = _install_shim(tmp_path)
    seen = tmp_path / "seen"
    hook = base / "job-started.sh"
    hook.write_text(f'env > "{seen}"\n')
    flag = tmp_path / "ran-first"
    evil = tmp_path / "evil.sh"
    evil.write_text(f'echo x >> "{flag}"\n')
    env = {"PATH": "/usr/bin:/bin", "BASH_ENV": str(evil), "ENV": str(evil), "SHELLOPTS": "xtrace",
           "PS4": f"$(echo x >> {flag})", "BASH_FUNC_env%%": f"() {{ echo x >> {flag}; }}",
           "GITHUB_REPOSITORY": REPO, "GITHUB_EVENT_NAME": "push", "ORCH_LOCK_DIR": "/tmp/elsewhere"}
    r = subprocess.run([str(shim), "--noprofile", "--norc", "-e", "-o", "pipefail", str(hook)], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert not flag.exists()
    got = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert got["GITHUB_REPOSITORY"] == REPO and got["GITHUB_EVENT_NAME"] == "push"
    assert "BASH_ENV" not in got and "SHELLOPTS" not in got and "ORCH_LOCK_DIR" not in got and "PS4" not in got


@pytest.mark.skipif(not Path("/bin/bash").exists(), reason="needs /bin/bash")
def test_the_job_s_own_bash_steps_pass_through_unchanged(tmp_path):
    _, shim = _install_shim(tmp_path)
    step = tmp_path / "step.sh"
    step.write_text('echo "args:$*" "v:$MY_VALUE"\n')
    r = subprocess.run([str(shim), "--noprofile", "--norc", "-e", "-o", "pipefail", str(step), "a b", "c"],
                       env={"PATH": "/usr/bin:/bin", "MY_VALUE": "kept"}, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout.strip() == "args:a b c v:kept", (r.stdout, r.stderr)
    # a file with the hook's name elsewhere is a normal step: only the installed hooks start clean
    other = tmp_path / "job-started.sh"
    other.write_text('echo "v:$MY_VALUE"\n')
    r = subprocess.run([str(shim), str(other)], env={"PATH": "/usr/bin:/bin", "MY_VALUE": "kept"},
                       capture_output=True, text=True, timeout=30)
    assert r.stdout.strip() == "v:kept"


def test_the_runner_finds_the_clean_bash_first_and_the_hooks_start_privileged():
    setup = (RUNNER / "setup.sh").read_text()
    assert "<key>PATH</key><string>$B/bin:" in setup
    assert 'install -m 0755 -o root -g wheel "$SRC/bash" "$B/bin/bash"' in setup
    assert (RUNNER / "bash").read_text().startswith("#!/bin/bash -p\n")
    for name in ("job-started.sh", "job-completed.sh", "runner-loop.sh"):
        assert (RUNNER / name).read_text().startswith("#!/bin/bash -p\n"), name


def test_every_job_gets_a_fresh_runner_folder_from_a_root_owned_copy():
    setup = (RUNNER / "setup.sh").read_text()
    loop = (RUNNER / "runner-loop.sh").read_text()
    # one job per start, never an update into the copy, started by the root loop (not by launchd on its own)
    assert "<string>$B/job/run.sh</string><string>--once</string>" in setup and "--disableupdate" in setup
    assert "<key>RunAtLoad</key><false/>" in setup and "<key>KeepAlive</key><false/>" in setup
    assert "<string>$B/runner-loop.sh</string>" in setup
    assert 'chown -R root:wheel "$B/template.new"' in setup and 'chown -R root:wheel "$B/creds.new"' in setup
    assert "UserName" not in setup[setup.index('cat > "$LOOP.new"'):]  # the loop runs as root
    # the loop: fresh folder, home emptied, then start; it runs as root only
    order = [loop.index(s) for s in ('gone "$J" || return 1', 'cp -Rc "$B/template" "$J"', 'fresh_home || return 1',
                                     'launchctl kickstart "$SVC"')]
    assert order == sorted(order)
    assert 'pkill -KILL -U "$U"' in loop and "ci-cache" not in setup


def test_the_loop_starts_no_runner_while_the_network_rule_is_missing():
    loop = (RUNNER / "runner-loop.sh").read_text()
    body = loop[loop.index("while :; do"):]
    assert body.index("network_closed") < body.index("launchctl kickstart")
    assert "the runner stays off" in body
    conf = (RUNNER / "pf-orch-ci.conf").read_text()
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16", "fc00::/7"):
        assert net in conf
    assert conf.count("user orch-ci") == 2 and "127.0.0.0" not in conf


def test_the_loop_never_acts_as_a_person():
    r = subprocess.run(["bash", str(RUNNER / "runner-loop.sh")], capture_output=True, text=True, timeout=30)
    if os.geteuid() != 0:
        assert r.returncode == 1 and "root only" in r.stderr


def test_no_download_cache_is_shared_between_jobs():
    action = (ROOT / ".github" / "actions" / "mac-job-home" / "action.yml").read_text()
    assert "ci-cache" not in action and "real_home" not in action
    assert 'cache="$h/Library/Caches"' in action


def test_a_refused_job_with_no_worker_found_stops_the_runner_programs():
    hook = (RUNNER / "job-started.sh").read_text()
    refuse = hook[hook.index("refuse() {"):hook.index("# The repository comes from")]
    assert '("$HERE"/job/bin/Runner.*) kill -9' in refuse


def test_the_docs_name_the_real_off_switch():
    doc = (ROOT / "docs" / "ci-checks.md").read_text()
    assert "it does not close the" in doc and "uninstall.sh" in doc
    assert "Helper accounts never approve a workflow run from a fork" in doc


def test_nothing_the_runner_user_leaves_outside_its_home_starts_again():
    """Automated review: a crontab, files in shared temp folders or Simulator apps would outlive the round."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    fresh = loop[loop.index("fresh() {"):loop.index("fails=0")]
    assert 'crontab -u "$U" -r' in fresh and "simctl erase all" in fresh
    for d in ("/private/tmp", "/private/var/tmp", "/Users/Shared"):
        assert d in fresh
    assert "cron.deny" in (RUNNER / "setup.sh").read_text()


def _loop_functions(tmp_path, user=None):
    """unguard(), gone(), realdir() and fresh_home() of the loop, without its root check and endless loop. U (the runner user)
    is the test's own user unless another is named."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    lib = tmp_path / "lib.sh"
    u = f'U={user}' if user else 'U=$(id -un)'
    # as_user runs as the runner user on the Mac; here the test user plays it (same empty environment)
    lib.write_text(f"{u}\nMAX=14400; IDLE_MAX=86400; STEP_MAX=${{STEP_MAX:-600}}\nlog() {{ echo \"$*\" >&2; }}\n"
                   "as_user() { env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin \"$@\"; }\n"
                   + loop[loop.index("limit() {"):loop.index("fresh() {")])
    return lib


def test_root_never_follows_a_link_the_job_planted_in_its_home(tmp_path):
    """Outside review: ~/Library -> /Library made the old clean-up delete /Library/Developer as root."""
    victim = tmp_path / "system" / "Developer" / "CoreSimulator"
    victim.mkdir(parents=True)
    (victim / "keep").write_text("x")
    home = tmp_path / "old"
    home.mkdir()
    (home / "Library").symlink_to(tmp_path / "system")
    lib = _loop_functions(tmp_path)
    r = subprocess.run(["bash", "-c", f'. "{lib}"; realdir "{home}" Library/Developer/CoreSimulator && echo follows;'
                        f' gone "{home}" && echo removed'], capture_output=True, text=True, timeout=30)
    assert "follows" not in r.stdout and "removed" in r.stdout, (r.stdout, r.stderr)
    assert (victim / "keep").read_text() == "x" and not home.exists()


@pytest.mark.skipif(not Path("/usr/bin/chflags").exists(), reason="macOS file flags")
def test_a_file_the_job_locked_does_not_survive_the_round(tmp_path):
    d = tmp_path / "job"
    d.mkdir()
    f = d / "payload"
    f.write_text("x")
    subprocess.run(["chflags", "uchg", str(f)], check=True)
    lib = _loop_functions(tmp_path)
    r = subprocess.run(["bash", "-c", f'. "{lib}"; gone "{d}"'], capture_output=True, text=True, timeout=30)
    if d.exists():
        subprocess.run(["chflags", "-R", "nouchg", str(d)])
    assert r.returncode == 0 and not d.exists(), r.stderr


def test_a_round_has_a_hard_end_and_nothing_of_the_user_is_set_to_start_again():
    loop = (RUNNER / "runner-loop.sh").read_text()
    assert 'why=$(round_over "$t0" "$tj" "$now")' in loop and 'log "$why"; break' in loop
    assert 'launchctl bootout "user/$uid"' in loop


def test_root_never_hands_the_job_s_leftovers_to_it_or_splits_names():
    """Automated review: chown -R over a moved tree with a hard link to a root file; a file name with a line break."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    fresh = loop[loop.index("fresh_home() {"):loop.index("fails=0")]
    assert 'chown -R "$U:$U" "$R"' not in fresh and 'chown -h "$U:$U" "$R"' in fresh  # only what root just made
    assert "-print0" in fresh and "read -r -d ''" in fresh and "-print 2>" not in fresh


def _deny_delete(p):
    subprocess.run(["chmod", "+a", "group:everyone deny delete", str(p)], check=True)


def _unlock(p):
    subprocess.run(["find", str(p), "-exec", "chflags", "-h", "nouchg", "{}", "+", "-exec", "chmod", "-h", "-N", "{}", "+"])


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS access rules (ACL)")
def test_the_home_macos_guards_against_delete_is_moved_aside_and_removed(tmp_path):
    """Live on this Mac (22 Nov): macOS puts 'everyone deny delete' on every home folder, so the loop's
    mv /Users/orch-ci failed for root too and no runner ever started. A job can set the same rule on its files."""
    lib = _loop_functions(tmp_path)
    home, old = tmp_path / "home", tmp_path / "old"
    (home / "sub").mkdir(parents=True)
    (home / "sub" / "payload").write_text("x")
    for p in (home, home / "sub" / "payload"):
        _deny_delete(p)
    # a link inside the home: its target keeps its rule (nothing is followed)
    keep = tmp_path / "keep"
    keep.mkdir()
    _deny_delete(keep)
    (home / "link").symlink_to(keep)
    r = subprocess.run(["bash", "-c", f'. "{lib}"; unguard "{home}" && mv "{home}" "{old}" && gone "{old}"'],
                       capture_output=True, text=True, timeout=30)
    if old.exists() or home.exists():
        _unlock(tmp_path)
    assert r.returncode == 0 and not home.exists() and not old.exists(), r.stderr
    assert "deny delete" in subprocess.run(["ls", "-led", str(keep)], capture_output=True, text=True).stdout
    subprocess.run(["chmod", "-N", str(keep)])


def test_the_loop_clears_the_access_rules_before_it_moves_or_removes():
    loop = (RUNNER / "runner-loop.sh").read_text()
    fresh = loop[loop.index("fresh_home() {"):loop.index("fails=0")]
    # the user clean-up clears its own locks and rules before it removes (find, never following a link)
    clean = loop[loop.index("CLEAN_AS_USER='"):loop.index("EMPTY_AS_USER='")]
    assert clean.index("chmod -h -N") < clean.index("rm -rf")
    gone = loop[loop.index("gone() {"):loop.index("realdir() {")]
    assert "unguard" in gone
    # macOS chmod -R -N follows links inside the tree even with -P: root would change their targets
    assert ('find -P "$1" -user "$U" -exec chflags -h nouchg,nouappnd {} + \\( -type f -o -type d -o -type l \\)'
            ' -exec chmod -h -N {} +') in loop
    code = "\n".join(line for line in loop.splitlines() if not line.lstrip().startswith("#"))
    assert "chmod -R -N" not in code and "chmod -R -P -N" not in code and "chflags -R" not in code


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS file flags")
def test_a_locked_home_and_a_locked_link_do_not_survive_the_round(tmp_path):
    """Outside review: uchg on the home stopped the move; a link locked with chflags -h survived gone()."""
    lib = _loop_functions(tmp_path)
    home, old, link = tmp_path / "home", tmp_path / "old", tmp_path / "link"
    home.mkdir()
    subprocess.run(["chflags", "uchg", str(home)], check=True)
    link.symlink_to(tmp_path / "nowhere")
    subprocess.run(["chflags", "-h", "uchg", str(link)], check=True)
    r = subprocess.run(["bash", "-c", f'. "{lib}"; unguard "{home}" && mv "{home}" "{old}" && gone "{old}"'
                        f' && gone "{link}"'], capture_output=True, text=True, timeout=30)
    exists = [p for p in (home, old, link) if p.exists() or p.is_symlink()]
    _unlock(tmp_path)
    assert r.returncode == 0 and not exists, (r.stderr, exists)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS access rules (ACL)")
def test_root_never_changes_a_file_the_runner_user_does_not_own(tmp_path):
    """Outside review: a hard link the job made to someone else's file is that file; unguard must leave its access
    rules and locks alone (here: the files belong to the test user, the runner user is someone else)."""
    lib = _loop_functions(tmp_path, user="nobody")
    tree = tmp_path / "tree"
    tree.mkdir()
    f = tree / "hardlinked"
    f.write_text("x")
    _deny_delete(f)
    subprocess.run(["chflags", "uchg", str(f)], check=True)
    subprocess.run(["bash", "-c", f'. "{lib}"; unguard "{tree}"'], check=True, timeout=30)
    st = subprocess.run(["ls", "-leO", str(f)], capture_output=True, text=True).stdout
    _unlock(tmp_path)
    assert "deny delete" in st and "uchg" in st, st


# --- two homes (live 22 Nov: macOS refused root a rename of the registered home, in /Users and in /private/var, and
# --- the removal of its Library/Caches): the runner user empties its registered home, root makes the job's HOME ---


def test_root_never_touches_the_registered_home_and_the_job_gets_a_home_root_makes_anew():
    loop = (RUNNER / "runner-loop.sh").read_text()
    setup = (RUNNER / "setup.sh").read_text()
    assert "HB=/private/var/orch-ci; H=$HB/home; R=$HB/run" in loop and "H=$HB/home; R=$HB/run;" in setup
    assert "H=/Users" not in loop and "H=/Users" not in setup and "orch-ci-old" not in loop
    code = "\n".join(line for line in loop.splitlines() if not line.lstrip().startswith("#"))
    fh = code[code.index("fresh_home() {"):code.index("fresh() {")]
    # root: no move, removal, unlock or chown of anything in the registered home
    for bad in ('mv "$H', 'gone "$H', 'unguard "$H', 'chown "$U:$U" "$H'):
        assert bad not in fh, bad
    assert 'as_user /bin/bash -p -c "$CLEAN_AS_USER" clean "$H"' in fh
    assert "sudo -u \"$U\" -H env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin" in loop  # the user clean-up has no job env
    assert fh.index('gone "$R"') < fh.index('mkdir -m 700 "$R" && mkdir -m 700 "$R/tmp" && chown -h "$U:$U" "$R/tmp" && chown -h "$U:$U" "$R"')
    # the runner and its jobs get HOME=$R, not the registered home
    assert "<key>HOME</key><string>$R</string>" in setup and "<key>HOME</key><string>$H</string>" not in setup
    # setup points the account at the home once, makes it once, and checks both ways work before it starts the loop
    assert '[ "$cur_home" = "$H" ] || ds -create "/Users/$U" NFSHomeDirectory "$H"' in setup
    assert "dscl . -create" not in setup and "alarm 120; exec @ARGV' dscl ." in setup and "(dscl $*)" in setup
    assert 'if [ ! -d "$H" ]; then mkdir "$H"; chown "$U:$U" "$H"; chmod 700 "$H"; fi' in setup
    assert 'sudo -u "$U" rm -rf "$H/Library/Caches/setup-check"' in setup and 'if ! unlock_rm "$R"; then' in setup
    assert 'chown -h root:wheel "/Users/$U"; chmod -h 000 "/Users/$U"' in setup and "createhomedir" not in setup
    one = setup[setup.index('echo "== 1/7'):setup.index('echo "== 2/7')]
    assert one.index('launchctl bootout system "$LOOP"') < one.index('mkdir -p "$HB"')
    assert one.index('pkill -KILL -U "$U"') < one.index('pgrep -U "$U"') < one.index('mkdir -p "$HB"')


def _fresh_home(lib, base):
    script = (f'PATH=/usr/bin:/bin:/usr/sbin:/sbin; HB="{base}"; B="$HB"; H="$HB/home"; R="$HB/run"; . "{lib}";'
              ' chown() { local h=; [ "$1" = -h ] && { h=-h; shift; }; command chown $h "${1%%:*}" "${@:2}"; }; fresh_home')
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)


def _unlock_tree(p):
    subprocess.run(["find", str(p), "-exec", "chflags", "-h", "nouchg", "{}", "+"], capture_output=True)
    subprocess.run(["chmod", "-R", "u+rwx", str(p)], capture_output=True)


def test_the_user_empties_its_registered_home_in_place_keeps_the_simulators_and_never_follows_a_link(tmp_path):
    """The loop's own fresh_home on a real folder tree (the test user plays the runner user)."""
    lib = _loop_functions(tmp_path)
    base = tmp_path / "orch-ci"
    home, run = base / "home", base / "run"
    sims = home / "Library" / "Developer" / "CoreSimulator"
    sims.mkdir(parents=True)
    (sims / "device").write_text("sim")
    for d in ("Library/Caches/x", "Library/Developer/Xcode", "Desktop", "Documents", "Downloads", ".cache", "odd\nname"):
        (home / d).mkdir(parents=True, exist_ok=True)
        (home / d / "left").write_text("x")
    (home / ".zshrc").write_text("x")
    locked = home / "Documents" / "left"
    if Path("/usr/bin/chflags").exists():
        subprocess.run(["chflags", "uchg", str(locked)], check=True)
    ro = home / "readonly"
    ro.mkdir()
    (ro / "f").write_text("x")
    ro.chmod(0o500)
    victim = tmp_path / "system"
    victim.mkdir()
    (victim / "keep").write_text("x")
    (home / "outside").symlink_to(victim)
    (run / "old").mkdir(parents=True)
    ino = home.stat().st_ino
    r = _fresh_home(lib, base)
    _unlock_tree(tmp_path)
    assert r.returncode == 0, r.stderr
    assert home.stat().st_ino == ino  # the same folder, emptied in place
    assert sorted(p.name for p in home.iterdir()) == ["Library"]
    assert sorted(p.name for p in (home / "Library").iterdir()) == ["Developer"]
    assert sorted(p.name for p in (home / "Library" / "Developer").iterdir()) == ["CoreSimulator"]
    assert (sims / "device").read_text() == "sim" and (victim / "keep").read_text() == "x"
    assert run.is_dir() and [p.name for p in run.iterdir()] == ["tmp"] and not any((run / "tmp").iterdir())


def test_a_library_link_in_the_registered_home_is_removed_never_followed(tmp_path):
    lib = _loop_functions(tmp_path)
    base = tmp_path / "orch-ci"
    home = base / "home"
    home.mkdir(parents=True)
    victim = tmp_path / "system"
    (victim / "Developer" / "CoreSimulator").mkdir(parents=True)
    (victim / "Caches").mkdir()
    (victim / "keep").write_text("x")
    (home / "Library").symlink_to(victim)
    r = _fresh_home(lib, base)
    assert r.returncode == 0, r.stderr
    assert not (home / "Library").is_symlink() and (home / "Library" / "Developer").is_dir()
    assert sorted(p.name for p in victim.iterdir()) == ["Caches", "Developer", "keep"]


def test_the_fresh_home_step_refuses_a_missing_base_or_a_home_that_is_a_link(tmp_path):
    lib = _loop_functions(tmp_path)
    base = tmp_path / "orch-ci"
    r = _fresh_home(lib, base)
    assert r.returncode != 0 and "run setup.sh again" in r.stderr
    base.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep").write_text("x")
    (base / "home").symlink_to(target)
    r = _fresh_home(lib, base)
    assert r.returncode != 0 and "run setup.sh again" in r.stderr and (target / "keep").read_text() == "x"


@pytest.mark.skipif(not Path("/usr/bin/chflags").exists(), reason="macOS file flags")
def test_a_locked_library_link_is_removed_first_and_nothing_is_deleted_through_it(tmp_path):
    """Outside review (Codex, reproduced): Library -> outside with chflags -h uchg survived the removal and the
    clean-up then deleted outside/Developer/keep through it."""
    lib = _loop_functions(tmp_path)
    base = tmp_path / "orch-ci"
    home = base / "home"
    home.mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "Developer").mkdir(parents=True)
    (outside / "Developer" / "keep").write_text("x")
    (outside / "keep").write_text("x")
    (home / "Library").symlink_to(outside)
    subprocess.run(["chflags", "-h", "uchg", str(home / "Library")], check=True)
    r = _fresh_home(lib, base)
    if (home / "Library").is_symlink():
        subprocess.run(["chflags", "-h", "nouchg", str(home / "Library")])
    assert (outside / "Developer" / "keep").read_text() == "x" and (outside / "keep").read_text() == "x"
    assert r.returncode == 0 and not (home / "Library").is_symlink(), r.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS extended attributes")
def test_no_job_data_stays_in_extended_attributes_of_the_folders_that_stay(tmp_path):
    """Outside review (Codex, reproduced): xattr -w on the home, Library and Developer survived the round."""
    lib = _loop_functions(tmp_path)
    base = tmp_path / "orch-ci"
    home = base / "home"
    (home / "Library" / "Developer").mkdir(parents=True)
    dirs = (home, home / "Library", home / "Library" / "Developer")
    for d in dirs:
        subprocess.run(["xattr", "-w", "user.payload", "previous job data", str(d)], check=True)
    r = _fresh_home(lib, base)
    assert r.returncode == 0, r.stderr
    for d in dirs:
        assert "user.payload" not in subprocess.run(["xattr", str(d)], capture_output=True, text=True).stdout, d


def test_setup_removes_the_job_home_with_its_locks_cleared():
    """Outside review (Codex): a locked file in the old job home stopped a rerun of setup."""
    setup = (RUNNER / "setup.sh").read_text()
    fn = setup[setup.index("unlock_rm() {"):]
    assert fn.index("chflags -h nouchg,nouappnd") < fn.index('rm -rf "$1"')
    # security review: only the runner user's files (a hard link to someone else's file is that file)
    code = "\n".join(line for line in setup.splitlines() if not line.lstrip().startswith("#"))
    for line in code.splitlines():
        if "chflags -h nouchg" in line and "find -P" in line:
            assert '-user "$U"' in line, line
    assert setup.count("unlock_rm() {") == 1 and setup.index("unlock_rm() {") < setup.index('unlock_rm "$HB/simulators.keep"')
    assert 'unlock_rm "$R" ||' in setup and 'if ! unlock_rm "$R"; then' in setup and 'rm -rf "$R"' not in setup


def test_the_user_empties_its_temp_and_cache_folders_root_never_removes_them(tmp_path):
    """Live 22 Nov (after setup): root could not remove the account's temp folder under /var/folders. The runner
    user empties it (and its cache folder) itself; the folder stays; the job's TMPDIR is in its fresh HOME."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    setup = (RUNNER / "setup.sh").read_text()
    fresh = loop[loop.index("fresh() {"):loop.index("fails=0")]
    assert 'as_user /bin/bash -p -c "$EMPTY_AS_USER" empty "$d"' in fresh
    assert 'gone "$d" && mkdir "$d"' not in fresh
    # a link in place of the folder stops the round; what macOS keeps or makes there again is only noted
    assert '[ -L "$d" ] && { log "$d is a link"; return 1; }' in fresh and 'note_left "$d"' in fresh
    assert "<key>TMPDIR</key><string>$R/tmp</string>" in setup
    lib = tmp_path / "lib.sh"
    lib.write_text("EMPTY_AS_USER=" + loop[loop.index("EMPTY_AS_USER='") + len("EMPTY_AS_USER="):loop.index("# What stays after")])
    t = tmp_path / "T"
    (t / "sub").mkdir(parents=True)
    (t / "sub" / "f").write_text("x")
    (t / ".hidden").write_text("x")
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep").write_text("x")
    (t / "link").symlink_to(victim)
    ino = t.stat().st_ino
    r = subprocess.run(["bash", "-c", f'. "{lib}"; env -i PATH=/usr/bin:/bin bash -p -c "$EMPTY_AS_USER" empty "{t}"'],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert t.stat().st_ino == ino and not any(t.iterdir()) and (victim / "keep").read_text() == "x"



def _run_fresh_home(lib, base, user_clean=True):
    script = (f'PATH=/usr/bin:/bin:/usr/sbin:/sbin; HB="{base}"; B="$HB"; H="$HB/home"; R="$HB/run"; . "{lib}";'
              ' chown() { local h=; [ "$1" = -h ] && { h=-h; shift; }; command chown $h "${1%%:*}" "${@:2}"; };'
              + ('' if user_clean else ' as_user() { :; };') + ' fresh_home')
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)


def test_what_macos_keeps_in_the_registered_home_is_noted_once_not_a_stop(tmp_path):
    """Live 22 Nov (root check 4): trustd, CoreSimulator and ContainerManager write into the registered home right
    after the clean-up. That is noted (only when it changed), never a reason to keep the runner off."""
    lib = _loop_functions(tmp_path)
    base = tmp_path / "orch-ci"
    home = base / "home"
    for d in ("Library/Caches/com.apple.trustd", "Library/Logs/CoreSimulator", "Library/Keychains"):
        (home / d).mkdir(parents=True)
    r = _run_fresh_home(lib, base, user_clean=False)  # nothing removed: as if macOS kept all of it
    assert r.returncode == 0, r.stderr
    assert "macOS keeps" in r.stderr and "Keychains" in r.stderr
    r = _run_fresh_home(lib, base, user_clean=False)  # the same again: not noted a second time
    assert r.returncode == 0 and "macOS keeps" not in r.stderr, r.stderr


def test_a_link_or_a_launch_agent_left_in_the_registered_home_stops_the_round(tmp_path):
    lib = _loop_functions(tmp_path)
    base = tmp_path / "orch-ci"
    home = base / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (home / "Library" / "LaunchAgents" / "x.plist").write_text("x")
    r = _run_fresh_home(lib, base, user_clean=False)
    assert r.returncode != 0 and "launch agent" in r.stderr, r.stderr
    (home / "Library" / "LaunchAgents" / "x.plist").unlink()
    (home / "Library" / "Caches").symlink_to(tmp_path)
    r = _run_fresh_home(lib, base, user_clean=False)
    assert r.returncode != 0 and "link" in r.stderr, r.stderr


def test_the_runner_user_s_clean_up_removes_launch_agents_and_links(tmp_path):
    lib = _loop_functions(tmp_path)
    base = tmp_path / "orch-ci"
    home = base / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (home / "Library" / "LaunchAgents" / "x.plist").write_text("x")
    (home / "Library" / "Caches").symlink_to(tmp_path)
    r = _run_fresh_home(lib, base)
    assert r.returncode == 0, r.stderr
    assert not (home / "Library" / "LaunchAgents").exists() and not (home / "Library" / "Caches").is_symlink()


def test_a_round_starts_no_job_while_programs_of_the_user_still_run_and_logs_a_failed_erase():
    """Outside challenge (OpenAI credit): a failed stop must stop the round; a failed Simulators erase is noted."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    fresh = loop[loop.index("fresh() {"):loop.index("fails=0")]
    assert fresh.index('pgrep -U "$U"') < fresh.index('gone "$J"')
    assert 'log "programs of $U still run after a stop"; return 1' in fresh
    assert "simctl erase all did not finish" in fresh


def test_the_docs_say_what_the_runner_guarantees_and_that_no_secrets_reach_it():
    docs = (ROOT / "docs" / "ci-checks.md").read_text()
    assert "persistent machine trusted with merged code only" in docs and "no secrets reach the Mac jobs" in docs
    for wf in ("mobile.yml",):
        assert "secrets." not in (WF / wf).read_text()


def test_the_runner_writes_its_own_log_that_the_loop_makes_for_it_each_round():
    """Live 22 Nov: launchd opens the runner's stdout as the runner user; the root-owned loop log made every start
    fail ('Unable to open stdout path ... Permission denied', exit 78)."""
    setup = (RUNNER / "setup.sh").read_text()
    loop = (RUNNER / "runner-loop.sh").read_text()
    runner = setup[setup.index('cat > "$PLIST.new"'):setup.index('cat > "$LOOP.new"')]
    assert "<string>/var/log/orch-mac-runner-job.log</string>" in runner and "orch-mac-runner.log<" not in runner
    fresh = loop[loop.index("fresh() {"):loop.index("fails=0")]
    assert 'install -m 0640 -o "$U" -g wheel /dev/null "$RL"' in fresh and 'mv -f "$RL" "$RL.1"' in fresh
    assert "RL=/var/log/orch-mac-runner-job.log" in loop


def test_the_manual_setting_sends_only_manual_runs_to_the_mac():
    """A trial before develop pushes and the nightly go to the Mac (manager 22 Nov, like orch edge)."""
    on = [_runner()]
    base = {"MAC_RUNNER": "this-mac-manual", "STATUS_TOKEN": "t", "REPO": REPO, "REF": "refs/heads/develop"}
    use, why = mr.route({**base, "EVENT": "workflow_dispatch"}, fetch=lambda repo, tok: on)
    assert use, why
    for event in ("push", "schedule"):
        use, why = mr.route({**base, "EVENT": event}, fetch=lambda repo, tok: on)
        assert not use and "only manual runs" in why, (event, why)
    use, why = mr.route({**base, "EVENT": "pull_request", "REF": "refs/pull/9/merge", "BASE_REF": "main",
                         "HEAD_REPO": REPO}, fetch=lambda repo, tok: on)
    assert not use and "only manual runs" in why


def test_the_release_keeper_s_test_runs_never_go_to_the_mac():
    on = [_runner()]
    for setting in ("this-mac", "this-mac-manual"):
        use, why = mr.route({"MAC_RUNNER": setting, "STATUS_TOKEN": "t", "REPO": REPO, "EVENT": "workflow_dispatch",
                             "REF": "refs/heads/release-test/42"}, fetch=lambda repo, tok: (_ for _ in ()).throw(AssertionError("asked")))
        assert not use and "release keeper" in why, (setting, why)


@pytest.mark.parametrize("job", ["workspace", "addons", "mobile"])
def test_a_manual_run_on_the_mac_runs_every_mac_job(job):
    """The trial (MAC_RUNNER=this-mac-manual): a manual run sees no changed files, so without this it would skip the
    Mac jobs it is meant to measure (orch edge did the same with edge_where)."""
    lines = (WF / "ci.yml").read_text().splitlines()
    i = lines.index(f"  {job}:")
    cond = next(line for line in lines[i + 1:i + 12] if line.strip().startswith("if:"))
    assert "(github.event_name == 'workflow_dispatch' && needs.route.outputs.where == 'mac')" in cond


def test_dashboard_pictures_stay_pull_request_only():
    """Outside review (Codex): dash_ci_shots.py needs the pull request's number and changed pages."""
    lines = (WF / "ci.yml").read_text().splitlines()
    i = lines.index("  dash-shots:")
    cond = next(line for line in lines[i + 1:i + 12] if line.strip().startswith("if:"))
    assert "workflow_dispatch" not in cond and "github.event_name == 'pull_request'" in cond


def test_the_job_limit_counts_from_the_job_s_start_not_from_the_idle_wait(tmp_path):
    """23 Nov trial: the runner waited idle from 21:13, the phone job started at 00:15 and the loop stopped it at 01:13
    because the 4-hour limit counted from the runner's start."""
    lib = _loop_functions(tmp_path)

    def over(t0, tj, now):
        r = subprocess.run(["bash", "-c", f'. "{lib}"; round_over {t0} {tj} {now}'], capture_output=True, text=True,
                           timeout=30, check=True)
        return r.stdout.strip()
    idle_3h, job_58m = 3 * 3600, 58 * 60
    assert over(0, idle_3h, idle_3h + job_58m) == ""          # the trial's case goes on
    assert over(0, 0, 23 * 3600) == ""                         # waiting for a job is no reason to stop
    assert "no job" in over(0, 0, 24 * 3600 + 1)               # a whole day idle: a fresh start
    assert "job longer than 14400s" in over(0, idle_3h, idle_3h + 4 * 3600 + 1)
    loop = (RUNNER / "runner-loop.sh").read_text()
    assert "[ \"$tj\" = 0 ] && job_started && tj=$now" in loop


def test_a_job_counts_as_started_from_the_runner_s_log_or_a_worker(tmp_path):
    lib = _loop_functions(tmp_path)
    rl = tmp_path / "job.log"
    rl.write_text("2026-11-23 Listening for Jobs\n")
    run = lambda: subprocess.run(["bash", "-c", f'U=nobody-here-x; RL="{rl}"; . "{lib}"; U=nobody-here-x; job_started && echo yes'],
                                 capture_output=True, text=True, timeout=30).stdout.strip()
    assert run() == ""
    rl.write_text("2026-11-23 Listening for Jobs\n2026-11-23 Running job: mobile / test\n")
    assert run() == "yes"


def test_a_step_that_hangs_is_stopped_with_its_children_after_the_limit(tmp_path):
    lib = _loop_functions(tmp_path)
    pidfile = tmp_path / "child.pid"
    t = time.monotonic()
    r = subprocess.run(["bash", "-c", f'. "{lib}"; limit 2 bash -c \'sleep 300 & echo $! > "{pidfile}"; wait\'; echo rc=$?'],
                       capture_output=True, text=True, timeout=60)
    assert "rc=124" in r.stdout and time.monotonic() - t < 30, (r.stdout, r.stderr)
    child = int(pidfile.read_text())
    time.sleep(0.5)
    assert subprocess.run(["kill", "-0", str(child)], capture_output=True).returncode != 0, "the step's child still runs"
    r = subprocess.run(["bash", "-c", f'. "{lib}"; limit 5 sh -c "exit 3"; echo rc=$?'], capture_output=True, text=True,
                       timeout=30)
    assert "rc=3" in r.stdout


def _hanging_chmod(tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "chmod").write_text(f'#!/bin/sh\necho called >> "{tmp_path}/chmod.calls"\nexec sleep 300\n')
    (fake / "chmod").chmod(0o755)
    return fake


def test_a_plain_job_home_is_removed_without_unlocking_every_file(tmp_path):
    """The unlock walk (find ... chmod -h -N) over a phone build's home hung for over an hour on 23 Nov; a home with
    nothing locked never needs it."""
    d = tmp_path / "run"
    (d / "tmp" / "DerivedData").mkdir(parents=True)
    for i in range(50):
        (d / "tmp" / "DerivedData" / f"f{i}").write_text("x")
    fake = _hanging_chmod(tmp_path)
    lib = _loop_functions(tmp_path)
    r = subprocess.run(["bash", "-c", f'. "{lib}"; gone "{d}"'], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
    assert r.returncode == 0 and not d.exists(), r.stderr
    assert not (tmp_path / "chmod.calls").exists()


@pytest.mark.skipif(not Path("/usr/bin/chflags").exists(), reason="macOS file flags")
def test_an_unlock_that_hangs_ends_after_the_step_limit_and_the_round_says_so(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    f = d / "payload"
    f.write_text("x")
    subprocess.run(["chflags", "uchg", str(f)], check=True)
    fake = _hanging_chmod(tmp_path)
    lib = _loop_functions(tmp_path)
    t = time.monotonic()
    try:
        r = subprocess.run(["bash", "-c", f'. "{lib}"; gone "{d}"; echo rc=$?'], capture_output=True, text=True,
                           timeout=60, env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "STEP_MAX": "2"})
    finally:
        subprocess.run(["chflags", "-R", "nouchg", str(d)])
    assert time.monotonic() - t < 30
    assert (tmp_path / "chmod.calls").exists() and "took longer than 2s" in r.stderr, r.stderr
    assert "rc=1" in r.stdout and "could not remove" in r.stderr, (r.stdout, r.stderr)


def test_every_step_as_the_runner_user_has_a_time_limit():
    loop = (RUNNER / "runner-loop.sh").read_text()
    assert 'as_user() { limit "$STEP_MAX" sudo -u "$U"' in loop


@pytest.mark.parametrize("who", ["root", "user"])
def test_a_named_pipe_the_job_left_never_blocks_the_clean_up(tmp_path, who):
    """23 Nov: chmod -N opened a FIFO in the phone job's home and waited for a writer for over an hour (fifo_open)."""
    d = tmp_path / "run"
    (d / "tmp").mkdir(parents=True)
    os.mkfifo(d / "tmp" / "pipe")
    (d / "tmp" / "f").write_text("x")
    lib = _loop_functions(tmp_path)
    loop = (RUNNER / "runner-loop.sh").read_text()
    if who == "root":
        cmd = f'. "{lib}"; unguard "{d}"; gone "{d}"; echo rc=$?'
    else:
        empty = loop[loop.index("EMPTY_AS_USER='") + len("EMPTY_AS_USER='"):]
        empty = empty[:empty.index("exit 0'")] + "exit 0"
        script = tmp_path / "empty.sh"
        script.write_text(empty)
        cmd = f'bash -p "{script}" "{d}"; echo rc=$?'
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=60)
    assert "rc=0" in r.stdout, (r.stdout, r.stderr)
    assert not (d / "tmp").exists() if who == "user" else not d.exists()


def test_every_unlock_walk_skips_pipes_sockets_and_devices():
    for name in ("runner-loop.sh", "setup.sh"):
        text = (RUNNER / name).read_text()
        for line in text.splitlines():
            if "chmod -h -N {}" in line:
                assert "\\( -type f -o -type d -o -type l \\) -exec chmod -h -N" in line, (name, line)


def test_mac_jobs_use_a_python_uv_puts_in_their_home_not_homebrew_s():
    """Trial 23 Nov: uv took /opt/homebrew's Python (another user's, group-writable) and orch's secret run refused it."""
    action = (ROOT / ".github" / "actions" / "mac-job-home" / "action.yml").read_text()
    assert 'echo "UV_PYTHON_PREFERENCE=only-managed"' in action
    assert 'echo "UV_PYTHON_INSTALL_DIR=$cache/uv-python"' in action


def test_the_click_through_folder_is_under_the_account_home_the_server_checks():
    """Trial 23 Nov: on the Mac runner HOME is the job's throwaway folder, so ~/.orch-test was not under the account home
    server.py checks (pwd), and the server refused to start."""
    run = (ROOT / "workspace-addons" / "dashboard" / "clickthrough" / "run.cjs").read_text()
    server = (ROOT / "workspace-addons" / "dashboard" / "clickthrough" / "server.py").read_text()
    assert "path.join(os.userInfo().homedir, '.orch-test')" in run and "path.join(os.homedir(), '.orch-test')" not in run
    assert "pwd.getpwuid(os.getuid()).pw_dir" in server

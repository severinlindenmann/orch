"""This Mac's own CI runner (ORCH-1125): the route, the wiring in the workflows, the shared lock and the job hook."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
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
    order = [loop.index(s) for s in ('gone "$J" || return 1', 'cp -Rc "$B/template" "$J"', 'mv "$H" "$old"',
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


def _loop_functions(tmp_path):
    """unguard(), gone() and realdir() of the loop, without its root check and endless loop."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    lib = tmp_path / "lib.sh"
    lib.write_text("log() { echo \"$*\" >&2; }\n" + loop[loop.index("unguard() {"):loop.index("fresh() {")])
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
    assert 'log "round longer than ${MAX}s; stopping it"' in loop
    assert 'launchctl bootout "user/$uid"' in loop


def test_root_never_hands_the_job_s_leftovers_to_it_or_splits_names():
    """Automated review: chown -R over a moved tree with a hard link to a root file; a file name with a line break."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    fresh = loop[loop.index("fresh() {"):loop.index("fails=0")]
    assert 'chown -R "$U:$U" "$H"' not in fresh and 'chown "$U:$U" "$H" "$H/Library" "$H/Library/Developer"' in fresh
    assert "-print0" in fresh and "read -r -d ''" in fresh and "-print 2>" not in fresh


def _deny_delete(p):
    subprocess.run(["chmod", "+a", "group:everyone deny delete", str(p)], check=True)


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
        subprocess.run(["find", str(tmp_path), "-exec", "chmod", "-h", "-N", "{}", "+"])
    assert r.returncode == 0 and not home.exists() and not old.exists(), r.stderr
    assert "deny delete" in subprocess.run(["ls", "-led", str(keep)], capture_output=True, text=True).stdout
    subprocess.run(["chmod", "-N", str(keep)])


def test_the_loop_clears_the_access_rules_before_it_moves_or_removes():
    loop = (RUNNER / "runner-loop.sh").read_text()
    fresh = loop[loop.index("fresh() {"):loop.index("fails=0")]
    assert fresh.index('unguard "$H"') < fresh.index('mv "$H" "$old"')
    gone = loop[loop.index("gone() {"):loop.index("realdir() {")]
    assert "unguard" in gone
    # macOS chmod -R -N follows links inside the tree even with -P: root would change their targets
    assert 'find -P "$1" -exec chmod -h -N {} +' in loop
    code = "\n".join(line for line in loop.splitlines() if not line.lstrip().startswith("#"))
    assert "chmod -R -N" not in code and "chmod -R -P -N" not in code

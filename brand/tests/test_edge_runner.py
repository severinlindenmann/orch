"""The orch edge test server's own CI runner (ORCH-1126): the route, the wiring in the workflows and the job hooks."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
RUNNER = ROOT / "scripts" / "edge-runner"
REPO = "severinlindenmann/orch"

spec = importlib.util.spec_from_file_location("edge_route", ROOT / "scripts" / "edge_route.py")
er = importlib.util.module_from_spec(spec)
spec.loader.exec_module(er)

EDGE = ["self-hosted", "orch-edge"]
ON = {"EDGE_RUNNER": "orch-edge", "REPO": REPO, "STATUS_TOKEN": "t"}


def _runner(status="online", busy=False, label="orch-edge"):
    return {"status": status, "busy": busy, "labels": [{"name": "self-hosted"}, {"name": label}]}


def _route(fetched, **env):
    return er.route({**ON, **env}, fetch=lambda repo, token: fetched)


# --- where the Linux jobs go --------------------------------------------------------------------------------------


def test_trusted_runs_go_to_orch_edge_when_it_is_online():
    for env in ({"EVENT": "push", "REF": "refs/heads/develop"}, {"EVENT": "schedule"}, {"EVENT": "workflow_dispatch"},
                {"EVENT": "pull_request", "BASE_REF": "main", "HEAD_REPO": REPO}):
        assert _route([_runner()], **env)[0] is True, env


@pytest.mark.parametrize("env", [
    {"EVENT": "pull_request", "BASE_REF": "develop", "HEAD_REPO": REPO},  # ordinary pull requests and queue groups
    {"EVENT": "pull_request", "BASE_REF": "main", "HEAD_REPO": "someone/orch"},  # a fork, even into main
    {"EVENT": "push", "REF": "refs/heads/main"},
    {"EVENT": "pull_request_target", "BASE_REF": "main", "HEAD_REPO": REPO},
])
def test_untrusted_runs_never_reach_orch_edge_and_never_read_the_runner_list(env):
    def boom(repo, token):
        raise AssertionError("read the runner list for an untrusted run")
    use, why = er.route({**ON, **env}, fetch=boom)
    assert use is False and "Mac" not in why


def test_the_one_setting_moves_every_job_back_to_github():
    for value in ("", "github", "this-mac", "ORCH-EDGE", "orch-edgex"):
        use, why = _route([_runner()], EVENT="schedule", EDGE_RUNNER=value)
        assert use is False and "EDGE_RUNNER" in why


def test_offline_missing_or_unknown_runner_sends_the_jobs_to_github_by_themselves():
    assert _route([], EVENT="schedule")[0] is False
    assert _route([_runner(status="offline")], EVENT="schedule")[0] is False
    assert _route([_runner(label="orch-mac")], EVENT="schedule")[0] is False  # the Mac's runner is not orch edge


def test_no_status_key_or_no_answer_from_github_means_github_machines():
    assert er.route({**ON, "STATUS_TOKEN": "", "EVENT": "schedule"})[0] is False

    def down(repo, token):
        raise OSError("no network")
    assert er.route({**ON, "EVENT": "schedule"}, fetch=down)[0] is False


def test_a_busy_runner_sends_a_develop_push_to_github_but_the_nightly_and_releases_wait():
    busy = [_runner(busy=True)]
    assert _route(busy, EVENT="push", REF="refs/heads/develop")[0] is False
    assert _route(busy, EVENT="push", REF="refs/heads/develop", EDGE_RUNNER_WHEN_BUSY="wait")[0] is True
    assert _route(busy, EVENT="schedule")[0] is True
    assert _route(busy, EVENT="pull_request", BASE_REF="main", HEAD_REPO=REPO)[0] is True


def test_a_develop_push_goes_to_orch_edge_only_when_every_runner_there_is_idle():
    # manager 22 Nov: one busy runner means an earlier run is still on orch edge; this run's jobs would wait behind it
    push = {"EVENT": "push", "REF": "refs/heads/develop"}
    some_busy = [_runner(), _runner(busy=True), _runner()]
    use, why = _route(some_busy, **push)
    assert use is False and "1 of 3" in why
    use, why = _route([_runner(), _runner(), _runner(status="offline", busy=True)], **push)
    assert use is True and "2 orch edge runner(s) online, all idle" in why  # an offline runner does not count
    assert _route(some_busy, EVENT="schedule")[0] is True  # the nightly run waits for them
    assert _route(some_busy, EVENT="workflow_dispatch")[0] is True


def test_the_manual_setting_sends_only_manual_runs_to_orch_edge():
    manual = {"EDGE_RUNNER": "orch-edge-manual"}
    assert _route([_runner()], EVENT="workflow_dispatch", **manual)[0] is True
    for env in ({"EVENT": "push", "REF": "refs/heads/develop"}, {"EVENT": "schedule"},
                {"EVENT": "pull_request", "BASE_REF": "main", "HEAD_REPO": REPO}):
        use, why = _route([_runner()], **env, **manual)
        assert use is False and "only manual runs" in why, env


def test_a_release_runs_on_orch_edge_and_on_github_x86_64():
    rel = er.outputs(True, "x", release=True)
    assert json.loads(rel["edge"]) == [EDGE, "ubuntu-latest"] and rel["edge_where"] == "both"
    push = er.outputs(True, "x", release=False)
    assert json.loads(push["edge"]) == [EDGE] and push["edge_where"] == "edge"
    off = er.outputs(False, "x", release=True)
    assert json.loads(off["edge"]) == ["ubuntu-latest"] and off["edge_where"] == "github"
    assert er.is_release_pr({"EVENT": "pull_request", "BASE_REF": "main"})
    assert not er.is_release_pr({"EVENT": "pull_request", "BASE_REF": "develop"})


def test_main_writes_outputs_and_never_fails(tmp_path):
    out = tmp_path / "out"
    env = {"GITHUB_OUTPUT": str(out), "PATH": os.environ.get("PATH", ""), "EDGE_RUNNER": "orch-edge", "EVENT": "push",
           "REF": "refs/heads/develop", "REPO": REPO}  # no token: falls back, exit 0
    r = subprocess.run(["python3", str(ROOT / "scripts" / "edge_route.py")], env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    lines = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert lines["edge_where"] == "github" and json.loads(lines["edge"]) == ["ubuntu-latest"]


# --- wiring in the workflow files ---------------------------------------------------------------------------------

CI = (WF / "ci.yml").read_text()
ON_EDGE = "needs.route.outputs.edge_where == 'edge' || needs.route.outputs.edge_where == 'both'"


def _job(text: str, name: str) -> str:
    m = re.search(rf"^  {re.escape(name)}:\n((?:    .*\n|\s*\n)*)", text, re.MULTILINE)
    assert m, name
    return m.group(1)


def test_the_route_job_also_decides_for_orch_edge_and_never_fails():
    route = _job(CI, "route")
    assert "python3 scripts/edge_route.py" in route and "scripts/edge_route.py\n" in route  # in the sparse checkout
    assert "steps.e.outputs.edge || '[\"ubuntu-latest\"]'" in route and "steps.e.outputs.edge_where || 'github'" in route
    assert "vars.EDGE_RUNNER }}" in route and "vars.EDGE_RUNNER_WHEN_BUSY" in route
    step = route[route.index("- id: e"):]
    assert "continue-on-error: true" in step
    cond = re.search(r"STATUS_TOKEN: \$\{\{ (.*) \}\}", step).group(1)
    assert "github.event_name != 'pull_request'" in cond and "github.base_ref == 'main'" in cond
    assert "head.repo.full_name == github.repository" in cond and cond.endswith("|| ''")


@pytest.mark.parametrize("job,inp", [("clock", "runs_on"), ("relay", "runs_on"), ("publish", "runs_on"),
                                     ("e2e-smoke", "runs_on"), ("addons", "linux_runs_on")])
def test_ci_passes_the_route_to_every_linux_job_and_runs_all_of_them_on_orch_edge(job, inp):
    body = _job(CI, job)
    assert f"{inp}: ${{{{ needs.route.outputs.edge || '[\"ubuntu-latest\"]' }}}}" in body
    assert re.search(r"^    needs: \[changes, route\]$", body, re.MULTILINE)
    # a failed route job never skips them (they go to GitHub's machines), and on orch edge they run after each merge
    assert "if: ${{ !cancelled() && needs.changes.result == 'success' && (" in body and ON_EDGE in body


@pytest.mark.parametrize("file,job", [("clock.yml", "suites"), ("relay.yml", "test"), ("publish.yml", "test"),
                                      ("e2e-smoke.yml", "smoke"), ("addons.yml", "services")])
def test_each_linux_job_runs_one_leg_per_machine_with_a_throwaway_home(file, job):
    text = (WF / file).read_text()
    body = _job(text, job)
    assert re.search(r"machine: \$\{\{ fromJSON\(inputs\.(linux_)?runs_on\) \}\}", body)
    assert "runs-on: ${{ matrix.machine" in body
    assert body.index("uses: actions/checkout@v4") < body.index("uses: ./.github/actions/edge-job-home")
    assert "default: '[\"ubuntu-latest\"]'" in text


def test_no_linux_job_needs_sudo_on_orch_edge():
    clock = _job((WF / "clock.yml").read_text(), "suites")
    assert "command -v faketime >/dev/null || sudo apt-get install" in clock
    services = _job((WF / "addons.yml").read_text(), "services")
    # sudo only in GitHub's branch: after "self-hosted ] ||" or between "else" and "fi" of a self-hosted check
    services = re.sub(r'if \[ "\$RUNNER_ENVIRONMENT" = self-hosted \]; then(.*?)\n\s*else\n.*?\n\s*fi\n', r"\1\n",
                      services, flags=re.DOTALL)
    for line in services.splitlines():
        if "sudo " in line and not line.strip().startswith("#"):
            assert '[ "$RUNNER_ENVIRONMENT" = self-hosted ] ||' in line, line


def test_binaries_and_pictures_of_the_two_machines_never_share_a_name():
    for f in ("relay.yml", "publish.yml"):
        assert "linux-${{ runner.arch == 'ARM64' && 'aarch64' || 'x86_64' }}" in (WF / f).read_text()
    assert "services-tab-shots${{ matrix.machine != 'ubuntu-latest' && '-orch-edge' || '' }}" in (WF / "addons.yml").read_text()


def test_the_job_home_keeps_temp_files_off_the_memory_disk_and_caps_workers():
    home = (ROOT / ".github" / "actions" / "edge-job-home" / "action.yml").read_text()
    assert "if: runner.environment == 'self-hosted'" in home
    # test workers and build jobs follow the runner count setup.sh writes: cores / (runners + 1), 2 to 4
    assert "n=$(cat /usr/local/orch-edge-runner/count 2>/dev/null || echo 1)" in home
    assert 'w=$(( $(nproc) / (n + 1) )); [ "$w" -lt 2 ] && w=2; [ "$w" -gt 4 ] && w=4' in home
    for line in ("TMPDIR=$RUNNER_TEMP/tmp", "ORCH_HOME_STRICT=1", "PYTEST_XDIST_AUTO_NUM_WORKERS=$w", "CARGO_BUILD_JOBS=$w",
                 "CARGO_HOME=$cache/cargo", "RUSTUP_HOME=$cache/rustup", "UV_PYTHON_PREFERENCE=only-managed", "NO_FAKE_STAT=1"):
        assert line in home, line
    # every download cache inside the throwaway home: no job leaves a program for the next one (ORCH-1233 L2)
    assert 'cache="$h/.cache"' in home and "ci-cache" not in home and "real_home" not in home


def test_no_workflow_names_the_edge_runner_itself():
    for f in WF.glob("*.yml"):
        for line in f.read_text().splitlines():
            if line.strip().startswith("runs-on:"):
                assert "orch-edge" not in line and "self-hosted" not in line, (f.name, line)


# --- the job hooks ------------------------------------------------------------------------------------------------


def _hook(tmp_path, event, ref, pr, repo):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({"pull_request": pr} if pr else {}))
    env = {"PATH": os.environ.get("PATH", ""), "ORCH_RUNNER_REPO": REPO, "GITHUB_REPOSITORY": repo,
           "GITHUB_EVENT_NAME": event, "GITHUB_REF": ref, "GITHUB_EVENT_PATH": str(ev)}
    return subprocess.run(["bash", str(RUNNER / "job-started.sh")], env=env, capture_output=True, text=True, timeout=30, check=False)


def _pr(base, head):
    return {"base": {"ref": base}, "head": {"repo": {"full_name": head}}}


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="the hook uses the system python3")
@pytest.mark.parametrize(
    "event,ref,pr,repo,ok",
    [
        ("push", "refs/heads/develop", None, REPO, True),
        ("schedule", "refs/heads/develop", None, REPO, True),
        ("workflow_dispatch", "refs/heads/develop", None, REPO, True),
        ("pull_request", "refs/pull/1/merge", _pr("main", REPO), REPO, True),
        ("pull_request", "refs/pull/1/merge", _pr("main", "someone/orch"), REPO, False),
        ("pull_request", "refs/pull/1/merge", _pr("develop", REPO), REPO, False),
        ("push", "refs/heads/feat/x", None, REPO, False),
        ("push", "refs/heads/develop", None, "someone/orch", False),
        ("pull_request_target", "refs/heads/develop", None, REPO, False),
    ],
)
def test_the_job_hook_refuses_what_must_never_run_on_orch_edge(tmp_path, event, ref, pr, repo, ok):
    r = _hook(tmp_path, event, ref, pr, repo)
    assert (r.returncode == 0) is ok, r.stdout + r.stderr
    if not ok:
        assert "refused" in r.stderr


def test_installed_hook_reads_the_repository_from_its_root_owned_file_only():
    text = (RUNNER / "job-started.sh").read_text()
    assert 'if [ -f "$HERE/repo" ]; then REPO=$(cat "$HERE/repo"); else REPO=${ORCH_RUNNER_REPO:-}; fi' in text
    assert "PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH; unset BASH_ENV ENV CDPATH" in text
    assert 'kill -9 "$worker"' in text  # a refused job is stopped, not only failed
    # only the root-owned installed copy stops the job (no job can make a root-owned file)
    assert "-user 0" in text[text.index("refuse() {") : text.index('kill -9 "$worker"')]


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="the hook uses the system python3")
def test_a_refused_job_run_from_the_repository_never_stops_its_runner_worker(tmp_path):
    """On GitHub's machines these tests run inside a real Runner.Worker: a refused hook killed the CI job itself."""
    ev = tmp_path / "event.json"
    ev.write_text("{}")
    env = {"PATH": os.environ.get("PATH", ""), "ORCH_RUNNER_REPO": REPO, "GITHUB_REPOSITORY": REPO,
           "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/feat/x", "GITHUB_EVENT_PATH": str(ev)}
    hook = str(RUNNER / "job-started.sh")
    # a parent process whose command line names Runner.Worker, like the runner's own worker
    r = subprocess.run(["bash", "-c", 'exec -a Runner.Worker bash -c "bash \\"$0\\"; echo worker-alive"', hook],
                       env=env, capture_output=True, text=True, timeout=30, check=False)
    assert "refused" in r.stderr and "worker-alive" in r.stdout, (r.stdout, r.stderr)


@pytest.mark.parametrize("name", ["job-started.sh", "job-completed.sh"])
def test_functions_from_the_job_s_environment_never_replace_a_command_in_the_hooks(tmp_path, name):
    """A job sets its own environment; bash loads exported functions from it (Codex review of the Mac hooks)."""
    flag = tmp_path / "hijacked"
    ev = tmp_path / "event.json"
    ev.write_text("{}")
    env = {"PATH": os.environ.get("PATH", ""), "ORCH_RUNNER_REPO": REPO, "GITHUB_REPOSITORY": REPO,
           "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/feat/x", "GITHUB_EVENT_PATH": str(ev)}
    for cmd in ("find", "ps", "kill", "id", "cat", "dirname", "tr", "getent"):
        env[f"BASH_FUNC_{cmd}%%"] = f"() {{ echo x >> {flag}; }}"
    env["SHELLOPTS"] = "privileged"  # would make the first start look like the clean one if the hook trusted $-
    r = subprocess.run(["bash", str(RUNNER / name)], env=env, capture_output=True, text=True, timeout=30, check=False)
    assert not flag.exists(), (r.stdout, r.stderr)
    assert ("refused" if name == "job-started.sh" else "did nothing") in r.stderr


def test_the_clean_up_hook_never_acts_as_a_person(tmp_path):
    r = subprocess.run(["bash", str(RUNNER / "job-completed.sh")], env={"PATH": os.environ.get("PATH", "")},
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0 and "did nothing" in r.stderr


def test_setup_refuses_anything_but_root_on_the_arm64_debian_test_server():
    text = (RUNNER / "setup.sh").read_text()
    assert '[ "$(id -u)" = 0 ]' in text and "aarch64" in text and "/etc/debian_version" in text
    assert "sha256sum -c" in text and "--labels orch-edge" in text and "--disableupdate" in text
    unit = text[text.index("[Service]"):text.index('cat > "$LOOP.new"')]
    assert '--work "$B/job$S/_work"' in text  # inside the fresh runner folder, never inside the runner's home
    for line in ("User=$U", "UMask=0022", "MemoryMax=$RUN_MAX", "Slice=orch-edge-runners.slice", "ACTIONS_RUNNER_HOOK_JOB_STARTED=$HOOKS/job-started.sh",
                 "ACTIONS_RUNNER_HOOK_JOB_COMPLETED=$HOOKS/job-completed.sh", "ExecStart=$B/job$S/run.sh --once",
                 "Restart=no", "KillMode=control-group", "Environment=PATH=$B/bin:"):
        assert line in unit, line
    assert "[Install]" not in unit  # only the loop starts the runner
    assert "TOKEN" not in text.split("unset TOKEN")[1]  # the token is never kept or printed after registering


# --- the Mac's security review ORCH-1233, the same fixes here ------------------------------------------------------


def test_the_runner_finds_a_clean_bash_first_so_no_job_setting_runs_before_the_hook():
    """M1: plain bash reads BASH_ENV, SHELLOPTS and exported functions of the job before the hook's first line."""
    wrapper = (RUNNER / "bash").read_text()
    assert wrapper.startswith("#!/bin/bash -p\n")
    assert 'exec /usr/bin/env -i "${pass[@]}" /bin/bash -p "$last"' in wrapper
    assert '"$here/job-started.sh"|"$here/job-completed.sh")' in wrapper and 'exec /bin/bash "$@"' in wrapper
    setup = (RUNNER / "setup.sh").read_text()
    assert 'install -m 0755 -o root -g root "$SRC/bash" "$B/bin/bash"' in setup
    for hook in ("job-started.sh", "job-completed.sh"):
        assert (RUNNER / hook).read_text().startswith("#!/bin/bash"), hook


def test_a_job_s_bash_env_never_runs_through_the_wrapper(tmp_path):
    b = tmp_path / "bin"
    b.mkdir()
    (b / "bash").write_text((RUNNER / "bash").read_text())
    (b / "bash").chmod(0o755)
    (tmp_path / "job-started.sh").write_text('echo "hook ran with BASH_ENV=${BASH_ENV-unset}"\n')
    flag = tmp_path / "hijacked"
    (tmp_path / "evil.sh").write_text(f"echo x >> {flag}\n")
    env = {"PATH": os.environ.get("PATH", ""), "BASH_ENV": str(tmp_path / "evil.sh"), "GITHUB_EVENT_NAME": "push"}
    r = subprocess.run([str(b / "bash"), "--noprofile", "--norc", "-e", "-o", "pipefail", str(tmp_path / "job-started.sh")],
                       env=env, capture_output=True, text=True, timeout=30, check=False)
    assert "hook ran with BASH_ENV=unset" in r.stdout and not flag.exists(), (r.stdout, r.stderr)


def test_a_fresh_runner_folder_and_home_before_every_job_from_a_root_owned_copy():
    """M2: a persistent runner folder the job can write would carry a job's changes into the next job."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    assert '[ "$(id -u)" = 0 ]' in loop and "B=/usr/local/orch-edge-runner" in loop
    order = [loop.index(x) for x in ('pkill -KILL -u "$U"', 'gone "$J"', 'cp -a "$B/template" "$J"', '"$C/$f"',
                                       'mv "$H" "$old"', 'install -d -o "$U" -g "$U" -m 0700 "$H"', "orch_ci_files | while",
                                       'systemctl start "user@$uid.service"')]
    assert order == sorted(order)
    rounds = loop[loop.index('log "started"'):]
    assert rounds.index("network_closed") < rounds.index("fresh") < rounds.index('systemctl start "$SVC"')
    assert "MAX=$((4 * 3600))" in loop and "round longer than" in loop
    assert "JOB_MAX=$((60 * 60))" in loop and "job longer than" in loop  # counted from the job's worker
    # every file of orch-ci on every writable filesystem, no depth limit; a file left fails the round (outside review)
    assert "findmnt -rn -t ext4,xfs,btrfs,tmpfs" in loop and "-maxdepth" not in loop and "files of $U are still there" in loop
    assert "flock -n 9" in loop and 'exec 9>"/run/orch-edge-runner-loop$SFX.lock"' in loop  # one clean-up per runner at a time
    setup = (RUNNER / "setup.sh").read_text()
    assert 'chown -R root:root "$B/template.new"; chmod -R go-w "$B/template.new"' in setup
    assert 'install -d -o root -g root -m 0700 "$B/creds$S.new"' in setup
    assert "rm -rf /srv/orch-ci" in setup  # the old job-writable work folder of an earlier install
    assert "ci-cache" not in setup
    assert setup.index("\nstop_all\n") < setup.index("== 1/6 packages")


def test_the_runner_user_never_reaches_the_private_or_the_local_network():
    rule = (RUNNER / "nft-orch-ci.nft").read_text()
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16", "fc00::/7", "fe80::/10"):
        assert net in rule, net
    assert rule.count('meta skuid "orch-ci"') == 2 and "127." not in rule.split("table inet orch_ci_runner {")[1]
    loop = (RUNNER / "runner-loop.sh").read_text()
    assert 'nft -f "$B/nft-orch-ci.nft"' in loop and "the runner stays off" in loop
    assert "nftables" in (RUNNER / "setup.sh").read_text()


def test_several_runners_side_by_side_each_with_its_own_user_folders_sign_up_and_units():
    """Manager 22 Nov: one runner made a develop run take 40+ minutes (12 jobs one after another)."""
    loop = (RUNNER / "runner-loop.sh").read_text()
    assert "case $K in ([1-9]) ;;" in loop and "instance must be 1 to 9" in loop
    assert 'if [ "$K" = 1 ]; then SFX=""; U=orch-ci; else SFX="-$K"; U=orch-ci-$K; fi' in loop
    assert "J=$B/job$SFX; C=$B/creds$SFX; H=/home/$U" in loop and "SVC=orch-edge-runner$SFX.service" in loop
    assert "old=/home/.$U-old" in loop
    # both rules (IPv4, IPv6) must name this runner's user; nft lists users by number
    assert "grep -cw \"$(id -u \"$U\")\")\" -ge 2" in loop
    setup = (RUNNER / "setup.sh").read_text()
    assert 'N=${ORCH_RUNNER_COUNT:-$(cat "$B/count" 2>/dev/null || echo 3)}' in setup
    # the runners together never take more memory than the machine minus 1.5 GB for the test services
    assert "POOL_MB=$(( MEM_MB - 1536 - USER_MB ))" in setup and "less than 1 GB of memory" in setup
    # one shared pool, not an even split: one relay build (rustc 1.6 GB) may use most of it (measured run, ORCH-1126)
    assert 'MemoryMax=%s\\n\' "$POOL_MAX" > /etc/systemd/system/orch-edge-runners.slice.new' in setup
    assert setup.index("orch-edge-runners.slice.new /etc/systemd/system/orch-edge-runners.slice") < setup.index("systemctl daemon-reload")
    assert "RUN_MAX=$POOL_MB; [ \"$RUN_MAX\" -gt 5120 ] && RUN_MAX=5120" in setup
    assert "rm -f /etc/systemd/system/orch-edge-runners.slice" in (RUNNER / "uninstall.sh").read_text()
    assert "ExecStart=$B/runner-loop.sh $k" in setup and '"$USER_MAX" > "/etc/systemd/system/user-' in setup
    # one sudoers file with one line per user, checked by visudo; one token signs up every runner without a sign-up
    assert '>> "$SUDO.new"' in setup and 'visudo -cqf "$SUDO.new"' in setup
    assert '--name "$NAME$S"' in setup and "for k in $todo; do" in setup
    # registering more runners never re-checks a running one (its loop holds the lock): it would stop setup half way
    reg = setup[setup.index('if [ "${1:-}" = register ]'):setup.index("exit 0\nfi")]
    assert reg.index('systemctl is-active --quiet "orch-edge-runner-loop$S.service" && continue') < reg.index('"$B/runner-loop.sh" --check "$k"')
    assert "for k in $(seq $((N + 1)) 9); do" in setup  # a lower count turns the runners above it off
    above = setup[setup.index("for k in $(seq $((N + 1)) 9); do"):]
    assert 'pkill -KILL -u "$U"' in above and 'loginctl disable-linger "$U"' in above  # and stops their users
    for hook, line in (("job-started.sh", "(orch-ci|orch-ci-[2-9]) runner_user=1;;"),
                       ("job-completed.sh", "(orch-ci-[2-9]) JOB=job-$(id -un | cut -d- -f3);;")):
        assert line in (RUNNER / hook).read_text(), hook
    assert 'RBIN=$(cd "$HERE/$JOB/bin"' in (RUNNER / "job-completed.sh").read_text()
    un = (RUNNER / "uninstall.sh").read_text()
    assert "orch-edge-runner-loop-$k.service" in un and "orch-ci-9; do" in un


@pytest.mark.parametrize("n,users", [(1, '"orch-ci"'), (3, '"orch-ci", "orch-ci-2", "orch-ci-3"')])
def test_setup_writes_every_runner_user_into_the_network_rule(tmp_path, n, users):
    setup = (RUNNER / "setup.sh").read_text()
    helpers = setup[setup.index("user_of() {"):setup.index("stop_all() {")]
    block = setup[setup.index("# the network rule names every runner user"):setup.index('printf \'%s\\n\' "$N" > "$B/count.new"')]
    block = block.replace("chown root:root", "true")  # not root here
    script = f'set -eu\nB="{tmp_path}"; SRC="{RUNNER}"; N={n}\n{helpers}\n{block}\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    rule = (tmp_path / "nft-orch-ci.nft").read_text()
    assert rule.count(f"meta skuid {{ {users} }}") == 2 and 'skuid "orch-ci"' not in rule


def test_uninstall_is_the_off_switch():
    text = (RUNNER / "uninstall.sh").read_text()
    for line in ("disable --now orch-edge-runner-loop.service", "nft delete table inet orch_ci_runner",
                 "rm -rf /usr/local/orch-edge-runner"):
        assert line in text, line


def test_after_each_job_the_user_manager_restarts_and_only_that_command_is_allowed():
    hook = (RUNNER / "job-completed.sh").read_text()
    assert 'sudo -n /usr/bin/systemctl restart "user@$ME.service"' in hook
    for d in (".config/systemd", ".config/environment.d", ".local/share/systemd"):
        assert f"$REAL_HOME/{d}" in hook
    setup = (RUNNER / "setup.sh").read_text()
    assert "NOPASSWD: /usr/bin/systemctl restart user@%s.service" in setup and "visudo -cqf" in setup


def test_a_runner_that_did_not_come_clean_refuses_the_next_job():
    hook = (RUNNER / "job-started.sh").read_text()
    assert "is left from an earlier job" in hook and "user services left from an earlier job" in hook
    done = (RUNNER / "job-completed.sh").read_text()
    first_restart = done.index('sudo -n /usr/bin/systemctl restart')
    assert done.index("rm_user_dirs   # before EVERY restart") < first_restart
    assert done.rstrip().endswith("exit 0\nfi") and done.count("rm_user_dirs\n") >= 2


def test_scripts_parse():
    for f in RUNNER.glob("*.sh"):
        subprocess.run(["bash", "-n", str(f)], check=True)

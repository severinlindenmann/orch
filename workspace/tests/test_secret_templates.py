"""#577: fixed argument forms for ssh, scp, rsync and git ls-remote; the kind from the real file."""

import os
import shutil
import subprocess

import pytest

from orch import keystore, secretrun
from orch.errors import Refused

VALID = [
    ("ssh", ["host"]),
    ("ssh", ["me@db.example.com"]),
    ("ssh", ["-p", "2222", "-l", "me", "-i", "{file:KEY}", "host"]),
    ("scp", ["-P", "22", "/usr/bin/true", "me@h:dir/b"]),
    ("scp", ["h:/srv/x", "/usr/bin/true"]),
    ("rsync", ["-a", "-v", "-z", "--delete", "/usr/bin/true", "me@h:backup/"]),
    ("git", ["ls-remote", "https://example.test/r.git"]),
    ("git", ["ls-remote", "--heads", "git@github.com:o/r.git"]),
]

BYPASS = [
    ("ssh", ["-oProxyCommand=x", "h"]),
    ("ssh", ["-voProxyCommand=x", "h"]),
    ("ssh", ["-o", "ProxyCommand=x", "h"]),
    ("ssh", ["-F", "/nonexistent/cfg", "h"]),
    ("ssh", ["-J", "jump", "h"]),
    ("ssh", ["h", "ls"]),
    ("ssh", ["h", "-oProxyCommand=x"]),
    ("ssh", ["-p", "22", "-p", "23", "h"]),
    ("ssh", ["-p", "-oProxyCommand=x", "h"]),
    ("ssh", ["-l", "-oProxyCommand=x", "h"]),
    ("ssh", ["-i", "{file:NOPE}", "h"]),
    ("ssh", ["-i", "rel/key", "h"]),
    ("ssh", ["-oProxyCommand=x"]),
    ("ssh", ["-h"]),
    ("ssh", ["--", "h"]),
    ("scp", ["-S", "/nonexistent/prog", "/nonexistent/a", "h:b"]),
    ("scp", ["-o", "ProxyCommand=x", "/nonexistent/a", "h:b"]),
    ("scp", ["/nonexistent/a", "/nonexistent/b"]),
    ("scp", ["h:a", "g:b"]),
    ("scp", ["/nonexistent/a", "h:-oProxyCommand=x"]),
    ("rsync", ["-e", "sh -c x", "/nonexistent/a", "h:b"]),
    ("rsync", ["--rsh=sh", "/nonexistent/a", "h:b"]),
    ("rsync", ["--rsync-path=x", "/nonexistent/a", "h:b"]),
    ("rsync", ["/nonexistent/a", "rsync://h/mod"]),
    ("rsync", ["/nonexistent/a", "h::mod"]),
    ("rsync", ["/nonexistent/a", "h://x"]),
    ("git", ["-c", "core.sshCommand=x", "ls-remote", "h:r"]),
    ("git", ["ls-remote", "--upload-pack=x", "h:r"]),
    ("git", ["ls-remote", "--upload-pack", "x", "h:r"]),
    ("git", ["--config-env=core.sshCommand=X", "ls-remote", "h:r"]),
    ("git", ["ls-remote", "-c", "a=b", "h:r"]),
    ("git", ["fetch", "h:r"]),
    ("git", ["pull", "h:r"]),
    ("git", ["push", "h:r"]),
    ("git", ["ls-remote", "h:r", "extra"]),
    ("git", ["ls-remote", "ext::sh -c x"]),
    ("git", ["ls-remote", "--h", "h:r"]),
]


@pytest.mark.parametrize(("kind", "args"), VALID)
def test_each_fixed_form_is_accepted(tmp_path, kind, args):
    secretrun.check_arguments(tmp_path, args, kind, {"KEY": "k"})


@pytest.mark.parametrize(("kind", "args"), BYPASS)
def test_every_known_way_around_a_form_is_refused(tmp_path, kind, args):
    with pytest.raises(Refused, match="fixed forms"):
        secretrun.check_arguments(tmp_path, args, kind, {"KEY": "k"})


def test_glued_or_abbreviated_options_are_refused_fuzz(tmp_path):
    for kind, (_, options, _) in secretrun.TEMPLATES.items():
        first = ["ls-remote"] if kind == "git" else []
        for opt in options:
            for glued in (opt + "22", opt + "o", opt + "=x", opt + "v", "-v" + opt[1:], opt[:-1] or "-"):
                operands = {"git": ["h:r"], "ssh": ["h"]}.get(kind, ["/nonexistent/a", "h:b"])
                with pytest.raises(Refused, match="fixed forms"):
                    secretrun.check_arguments(tmp_path, [*first, glued, *operands], kind)


def test_the_kind_comes_from_the_real_file_not_the_name(tmp_path):
    ssh = shutil.which("ssh", path="/usr/bin")
    if not ssh:
        pytest.skip("no /usr/bin/ssh")
    (tmp_path / "ssh").symlink_to("/bin/sh")  # named ssh, is another program
    (tmp_path / "mytool").symlink_to(ssh)  # named something else, is ssh
    assert secretrun.program_kind(os.path.realpath(tmp_path / "ssh")) == "other"
    assert secretrun.program_kind(os.path.realpath(tmp_path / "mytool")) == "ssh"
    for wrapper in ("autossh", "sshpass", "git-upload-pack"):
        assert secretrun.program_kind(str(tmp_path / wrapper)) == "other"


def test_a_profile_needs_its_kind_a_form_and_the_private_home():
    run = ["/usr/bin/ssh", "h"]
    with pytest.raises(Refused, match="Set the profile again"):
        secretrun.command_template({"run": run})  # saved by an older orch: no migration
    with pytest.raises(Refused, match="Set the profile again"):
        secretrun.command_template({"run": run, "kind": "bogus", "any_command": True})
    assert secretrun.command_template({"run": run, "kind": "ssh"}) == "ssh"
    for profile in ({"kind": "other"}, {"kind": "ssh", "real_home": True}):
        with pytest.raises(Refused, match="--any-command"):
            secretrun.command_template({"run": run, **profile})
        assert secretrun.command_template({"run": run, **profile, "any_command": True}) is None
    assert secretrun.command_template({"env": {}}) is None


def test_sftp_has_no_fixed_form_and_needs_any_command(tmp_path):
    # sftp reads commands from stdin (!cmd runs a local shell with the key, put/get reach any local file):
    # a caller controls stdin, so no argument form makes it safe.
    assert "sftp" not in secretrun.TEMPLATES
    sftp = shutil.which("sftp", path="/usr/bin")
    if not sftp:
        pytest.skip("no /usr/bin/sftp")
    kind = secretrun.program_kind(os.path.realpath(sftp))
    assert kind == "other"
    profile = {"run": [sftp, "-i", "{file:KEY}", "me@h"], "kind": kind}
    with pytest.raises(Refused, match="--any-command") as e:
        secretrun.command_template(profile)
    assert str(e.value) == secretrun.NOT_A_FORM and "sftp" not in str(e.value)
    assert secretrun.command_template({**profile, "any_command": True}) is None
    with pytest.raises(Refused, match="Set the profile again"):  # saved while sftp had a form
        secretrun.command_template({**profile, "kind": "sftp"})
    with pytest.raises(Refused, match="fixed forms"):
        secretrun.check_arguments(tmp_path, ["-i", "{file:KEY}", "me@h"], "sftp", {"KEY": "k"})
    assert secretrun.neutral_ssh([sftp, "h"], {}, ["/usr/bin"], None) == [sftp, "-F", "none", "h"]


def test_ssh_with_a_terminal_runs_no_local_command_through_an_escape():
    # With an inherited terminal (no own session) a templated ssh has escapes (~C). With -F none no config
    # turns PermitLocalCommand on, so ~C cannot run a local command (and newer ssh has no ~C line at all).
    ssh = shutil.which("ssh", path="/usr/bin")
    if not ssh:
        pytest.skip("no /usr/bin/ssh")
    command = secretrun.neutral_ssh([ssh, "h"], {}, ["/usr/bin"], None)
    done = subprocess.run(
        [command[0], "-G", *command[1:]], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL
    )
    settings = dict(line.split(" ", 1) for line in done.stdout.splitlines() if " " in line)
    assert settings["permitlocalcommand"] == "no"
    assert settings.get("enableescapecommandline", "no") == "no"


def test_every_ssh_orch_starts_reads_no_ssh_or_git_config(tmp_path):
    ssh = shutil.which("ssh", path="/usr/bin")
    if not ssh:
        pytest.skip("no /usr/bin/ssh")
    hostile = tmp_path / ".ssh" / "config"  # what an agent could write: never named on any command line
    hostile.parent.mkdir()
    hostile.write_text("Host *\n  ProxyCommand touch /nonexistent/pwned\n")
    dirs = ["/usr/bin"]
    for name in ("ssh", "scp", "sftp"):
        prog = shutil.which(name, path="/usr/bin")
        if prog:
            assert secretrun.neutral_ssh([prog, "h"], {}, dirs, None) == [prog, "-F", "none", "h"]
    rsync = shutil.which("rsync", path="/usr/bin")
    if rsync:
        cmd = secretrun.neutral_ssh([rsync, "-a", "/x", "h:y"], {}, dirs, None)
        assert cmd[:3] == [rsync, "-e", f"{ssh} -F none"]
    git = shutil.which("git", path="/usr/bin")
    if git:
        env = {"GIT_SSH_COMMAND": "sh -c pwned", "HOME": str(tmp_path)}
        cmd = secretrun.neutral_ssh([git, "ls-remote", "h:r"], env, dirs, None, tmp_path / "p")
        assert cmd == [git, "ls-remote", "h:r"]
        assert env["GIT_SSH_COMMAND"] == f"{ssh} -F none"
        assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert secretrun.neutral_ssh(["/bin/sh", "-c", "x"], {}, dirs, None) == ["/bin/sh", "-c", "x"]
    assert str(hostile) not in " ".join(secretrun.neutral_ssh([ssh, "h"], {}, dirs, None))


def test_git_reads_no_repository_an_agent_planted_above_the_private_folder(tmp_path, monkeypatch):
    git = shutil.which("git", path="/usr/bin")
    ssh = shutil.which("ssh", path="/usr/bin")
    if not git or not ssh:
        pytest.skip("no /usr/bin/git or /usr/bin/ssh")
    with pytest.raises(Refused):
        secretrun.neutral_ssh([git, "ls-remote", "h:r"], {}, ["/usr/bin"], None)  # no private folder: nothing
    marker = tmp_path / "marker"
    script = tmp_path / "pwn.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    planted = tmp_path / "keys" / "tmp"  # a parent of the private folder an agent could write
    (planted / ".git").mkdir(parents=True)
    subprocess.run([git, "init", "-q", str(planted)], check=True, capture_output=True)
    (planted / ".git" / "config").write_text(
        f"[core]\n\tsshCommand = {script}\n\thooksPath = {tmp_path}\n\tfsmonitor = {script}\n"
        f"[credential]\n\thelper = !{script}\n"
        f'[url "ssh://127.0.0.1:1/"]\n\tinsteadOf = https://example.invalid/\n'
    )
    private = planted / "1-ab" / "~home"
    private.mkdir(parents=True)
    for k, v in {
        "GIT_CONFIG_PARAMETERS": "'core.sshCommand'='x'",
        "GIT_CONFIG_COUNT": "1",
        "GIT_DIR": "/x",
    }.items():
        monkeypatch.setenv(k, v)
    env = secretrun._environment(["/usr/bin", "/bin"], private)
    hostile = {"GIT_CONFIG_PARAMETERS": "'core.sshcommand'='x'", "GIT_EXEC_PATH": "/x", "GIT_SSH": "x"}
    hostile.update(
        GIT_PROXY_COMMAND="x", GIT_ASKPASS="x", SSH_ASKPASS="x", GIT_CONFIG_KEY_9="x", GIT_WORK_TREE="/x"
    )
    env.update(hostile)
    command = secretrun.neutral_ssh(
        [git, "ls-remote", "ssh://127.0.0.1:1/r"], env, ["/usr/bin"], None, private
    )
    for k in hostile:
        assert k not in env
    assert env["GIT_DIR"] == str(private / "no-git-dir") and not os.path.exists(env["GIT_DIR"])
    assert env["GIT_CEILING_DIRECTORIES"] == str(private.parent)
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_SSH_COMMAND"] == f"{ssh} -F none"
    config = {
        env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))
    }
    assert config == {
        "credential.helper": "",
        "core.sshCommand": f"{ssh} -F none",
        "core.fsmonitor": "false",
        "core.hooksPath": os.devnull,
        "core.askPass": "",
        "protocol.allow": "never",
        "protocol.https.allow": "always",
        "protocol.http.allow": "always",
        "protocol.ssh.allow": "always",
    }
    for url in ("ssh://127.0.0.1:1/r", "https://example.invalid/r"):
        command[-1] = url
        subprocess.run(
            command, env=env, cwd=private, capture_output=True, timeout=60, stdin=subprocess.DEVNULL
        )
        assert not marker.exists()
    for url in (f"file://{tmp_path}", f"ext::{script}"):  # other transports are off
        command[-1] = url
        done = subprocess.run(command, env=env, cwd=private, capture_output=True, timeout=60)
        assert done.returncode != 0 and not marker.exists()


def test_rsync_settings_and_the_copy_programs_are_guarded():
    assert keystore.env_denied("RSYNC_RSH") and keystore.env_denied("RSYNC_CONNECT_PROG")
    assert all(secretrun.RISKY_PROGRAMS.search(p) for p in ("scp", "sftp", "rsync"))

"""`orch secret` (slice 1.2): keys go to the command, never to the output; person-only ops need an hp1 proof
(invariant H1); every use is handed to the recorder seam without the value; no fail-open."""

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest
from conftest import seed_profiles

from orch import cli, keystore, secretrun
from orch import humanproof as hp
from orch.errors import Refused

TOKEN = "tok-Q7xP2mK9vL4zR8"  # made-up values, long enough to be stored
TOKEN2 = "tok-W3nB6cF1yH5qD0"
PY = sys.executable


@pytest.fixture
def ws(proj, monkeypatch):
    from orch import addons

    base = addons.real_home() / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def run(capsys):
    """Like the shared `run`, but a command's own exit code (SystemExit) is returned as the code."""

    def _run(*argv):
        try:
            code = cli.main(list(argv))
        except SystemExit as e:
            code = e.code
        cap = capsys.readouterr()
        return code, cap.out, cap.err

    return _run


RUN, TICKET = "r_8k2m01", "t_inv7c2"


def _claim(ws, run=RUN, pid=None):
    from orch import runs

    runs._write(ws, {"run": run, "ticket": TICKET, "pid": os.getpid() if pid is None else pid})


@pytest.fixture
def in_run(ws, monkeypatch):
    """Inside a live orch run: the env names it and the claim exists."""
    _claim(ws)
    monkeypatch.setenv("ORCH_RUN", RUN)
    monkeypatch.setenv("ORCH_TICKET", TICKET)


@pytest.fixture
def events(monkeypatch):
    got = []
    monkeypatch.setattr(secretrun, "_recorder", lambda root, ev: got.append(ev))
    return got


@pytest.fixture
def store(ws):
    keystore.add(ws, "api-token", "token", TOKEN)
    keystore.add(ws, "other-token", "token", TOKEN2)
    keystore.add(
        ws, "sa.pem", "key-file", b"-----BEGIN KEY-----\nabcdefghijklmnopqrstuvwxyz0123\n-----END-----\n"
    )
    seed_profiles(
        ws,
        {
            "svc": {
                "env": {"SVC_TOKEN": "api-token"},
                "files": {"SVC_KEY": "sa.pem"},
                "set": {"SVC_HOST": "https://example.test"},
                "extra": ["SVC_KEY", "SVC_HOST"],
                "run": [PY, "-c"],
            },
            "plain": {"env": {"PLAIN_TOKEN": "other-token"}},
            "filesonly": {"files": {"ONLY_KEY": "sa.pem"}, "extra": ["ONLY_KEY"]},
        },
    )
    return ws


def _proof(ws, op, target, by="human:pat", **kw):
    return hp.mint(hp.human_key(ws), hp.new_payload(op, target, by, **kw))


def _cli(run, monkeypatch, proof, *argv, stdin_rest=""):
    monkeypatch.setattr("sys.stdin", io.StringIO((proof + "\n" if proof is not None else "") + stdin_rest))
    return run(*argv, "--proof-stdin")


def _tree_text(root: Path) -> str:
    out = []
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            out.append(p.read_bytes().decode("utf-8", "replace"))
    return "\n".join(out)


# --------------------------------------------------------------------------- env / file / exec


def test_env_hands_the_key_to_the_command_and_hides_it_in_output(store, run, events):
    code, out, err = run(
        "secret",
        "env",
        "plain",
        "--",
        PY,
        "-c",
        "import os,sys;print(os.environ['PLAIN_TOKEN']);print(os.environ['PLAIN_TOKEN'], file=sys.stderr)",
    )
    assert code == 0
    assert TOKEN2 not in out + err
    assert "[hidden: other-token]" in out and "[hidden: other-token]" in err


def test_the_exit_code_of_the_command_is_passed_through(store, run):
    code, *_ = run("secret", "env", "plain", "--", PY, "-c", "raise SystemExit(7)")
    assert code == 7


def test_flags_after_the_double_dash_reach_the_command(store, run):
    code, out, _ = run(
        "secret", "env", "plain", "--", PY, "-c", "import sys;print(sys.argv[1:])", "--json", "-x"
    )
    assert code == 0 and "['--json', '-x']" in out


def test_child_env_is_clean(store, run, monkeypatch):
    monkeypatch.setenv("SOME_AGENT_VAR", "visible-in-parent")
    monkeypatch.setenv("PYTHONPATH", "/evil")
    code, out, _ = run("secret", "env", "plain", "--", PY, "-c", "import os;print(sorted(os.environ))")
    assert code == 0
    assert "SOME_AGENT_VAR" not in out and "PYTHONPATH" not in out and "ORCH_HOME" not in out
    assert "PLAIN_TOKEN" in out and "PATH" in out


def test_value_split_over_two_chunks_is_still_hidden(store, run):
    half = len(TOKEN2) // 2
    prog = (
        f"import sys,time;v=sys.argv[1];sys.stdout.write(v[:{half}]);sys.stdout.flush();time.sleep(0.3);"
        f"sys.stdout.write(v[{half}:]+'\\n')"
    )
    code, out, _ = run("secret", "env", "plain", "--", PY, "-c", prog, TOKEN2)
    assert code == 0 and TOKEN2 not in out and "[hidden: other-token]" in out


def test_file_mode_writes_a_private_temp_file_and_deletes_it(store, run, ws):
    prog = "import os,stat;p=os.environ['SVC_KEY'];print(oct(stat.S_IMODE(os.stat(p).st_mode)));print(p)"
    code, out, _ = run("secret", "file", "filesonly", "--", PY, "-c", prog.replace("SVC_KEY", "ONLY_KEY"))
    assert code == 0
    mode, path = out.split()[:2]
    assert mode == "0o600"
    assert not Path(path).exists() and not Path(path).parent.exists()
    assert str(ws) not in path  # in the guarded home, not the workspace


def test_file_mode_cleans_up_after_a_failing_command(store, run):
    code, out, _ = run(
        "secret",
        "file",
        "filesonly",
        "--",
        PY,
        "-c",
        "import os;print(os.environ['ONLY_KEY']);raise SystemExit(3)",
    )
    assert code == 3 and not Path(out.split()[0]).exists()


def test_file_placeholder_in_arguments(store, run):
    code, out, _ = run(
        "secret",
        "file",
        "filesonly",
        "--",
        PY,
        "-c",
        "import sys,os;print(sys.argv[1]==os.environ['ONLY_KEY'])",
        "{file:ONLY_KEY}",
    )
    assert code == 0 and "True" in out


def test_file_content_is_hidden_in_output(store, run):
    prog = "print(open(__import__('os').environ['ONLY_KEY']).read())"
    code, out, _ = run("secret", "file", "filesonly", "--", PY, "-c", prog)
    assert code == 0 and "abcdefghijklmnopqrstuvwxyz0123" not in out and "[hidden: sa.pem]" in out


def test_env_with_a_files_only_profile_points_to_file_mode(store, run):
    code, _, err = run("secret", "env", "filesonly", "--", PY, "-c", "pass")
    assert code == 2 and "secret file" in err


def test_exec_runs_the_profile_command_with_everything(store, run):
    prog = (
        "import os;print(os.environ['SVC_HOST'], 'SVC_TOKEN' in os.environ, "
        "os.path.exists(os.environ['SVC_KEY']))"
    )
    code, out, _ = run("secret", "exec", "svc", "--", prog)
    assert code == 0 and "https://example.test True True" in out


def test_exec_without_a_run_command_is_refused(store, run):
    code, _, err = run("secret", "exec", "plain", "--", "x")
    assert code == 2 and "no command" in err.lower()


def test_unknown_profile_and_empty_command(store, run):
    assert run("secret", "env", "nope", "--", PY)[0] == 2
    assert run("secret", "env", "plain")[0] == 2


def test_program_is_never_found_through_the_callers_path_or_cwd(store, run, ws, monkeypatch):
    planted = ws / "bin"
    planted.mkdir()
    exe = planted / "mytool"
    exe.write_text("#!/bin/sh\necho planted\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{planted}:/usr/bin:/bin")
    code, out, err = run("secret", "env", "plain", "--", "mytool")
    assert code == 2 and "planted" not in out and "not found" in err
    monkeypatch.chdir(planted)
    code, out, err = run("secret", "env", "plain", "--", "mytool")
    assert code == 2 and "planted" not in out


def test_temp_folder_swept_when_its_process_is_gone(store, run, ws):
    tmp = hp.guarded_home(ws) / "keys" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    stale = tmp / "999999999-0123456789abcdef"
    stale.mkdir()
    (stale / "k").write_text("x")
    keep = tmp / "notmine"
    keep.mkdir()
    run("secret", "file", "filesonly", "--", PY, "-c", "pass")
    assert not stale.exists() and keep.exists()


# --------------------------------------------------------------------------- recorder seam


def test_one_use_event_per_key_without_the_value(store, run, events, monkeypatch):
    monkeypatch.setenv("ORCH_SKILL", "databricks-jobs")
    code, *_ = run("secret", "exec", "svc", "--", "pass")
    assert code == 0
    assert sorted(e["key"] for e in events) == ["api-token", "sa.pem"]
    assert all(e["kind"] == "key.use" and e["action"] == "exec" and e["profile"] == "svc" for e in events)
    assert all(e["skill"] == "databricks-jobs" and e["outcome"]["ok"] for e in events)
    assert {e["command"] for e in events} == {os.path.basename(PY)}
    assert TOKEN not in json.dumps(events)


def test_event_comes_before_the_child_starts(store, run, ws, monkeypatch):
    seen = []
    monkeypatch.setattr(secretrun, "_recorder", lambda root, ev: seen.append(Path(ws / "started").exists()))
    run("secret", "env", "plain", "--", PY, "-c", f"open({str(ws / 'started')!r}, 'w').close()")
    assert seen == [False]


def test_a_failing_recorder_stops_the_command(store, run, ws, monkeypatch):
    def boom(root, ev):
        raise RuntimeError(TOKEN2)

    monkeypatch.setattr(secretrun, "_recorder", boom)
    code, out, err = run(
        "secret", "env", "plain", "--", PY, "-c", f"open({str(ws / 'started')!r}, 'w').close()"
    )
    assert code == 2 and not (ws / "started").exists()
    assert TOKEN2 not in out + err and "could not be recorded" in err


def test_refusal_is_recorded_too(store, run, events):
    code, *_ = run("secret", "get", "plain", "other-token")
    assert code == 2
    assert events and events[-1]["refused"] == "get_off" and events[-1]["outcome"]["ok"] is False
    code, *_ = run("secret", "get", "plain", "api-token")
    assert events[-1]["refused"] == "not_in_profile"


# --------------------------------------------------------------------------- list


def test_list_has_no_values_and_matches_the_schema(store, run):
    import jsonschema

    code, out, _ = run("secret", "list", "--json")
    assert code == 0
    data = json.loads(out)
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts" / "secrets.schema.json").read_text()
    )
    jsonschema.validate(data, {"$ref": "#/$defs/list_answer", "$defs": schema["$defs"]})
    assert {i["name"] for i in data["items"]} == {"api-token", "other-token", "sa.pem"}
    assert TOKEN not in out and TOKEN2 not in out and all("value" not in i for i in data["items"])
    assert next(i for i in data["items"] if i["name"] == "api-token")["profiles"] == ["svc"]
    code, out, _ = run("secret", "list")
    assert code == 0 and TOKEN not in out and "api-token" in out


# --------------------------------------------------------------------------- get


def _enable_get(run, monkeypatch, ws, profile="plain"):
    code, out, err = _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.profile", f"{profile}:allow_get"),
        "secret",
        "profile",
        "get-enable",
        profile,
    )
    assert code == 0, out + err


def test_get_is_off_by_default_and_needs_the_record_not_only_the_file(store, run, ws, monkeypatch):
    code, out, err = run("secret", "get", "plain", "other-token")
    assert code == 2 and "does not allow printing" in err and TOKEN2 not in out + err
    prof = keystore.read_profiles(ws)
    prof["plain"]["allow_get"] = True
    seed_profiles(ws, prof)  # the file alone: no matching settings record
    code, out, err = run("secret", "get", "plain", "other-token")
    assert code == 2 and TOKEN2 not in out


def test_get_works_for_a_script_after_a_person_enabled_it(store, run, ws, monkeypatch):
    _enable_get(run, monkeypatch, ws)
    code, out, _ = run("secret", "get", "plain", "other-token")
    assert code == 0 and out == TOKEN2
    code, _, err = run("secret", "get", "plain", "api-token")
    assert code == 2 and "does not hold" in err


def test_get_to_a_terminal_is_refused(store, run, ws, monkeypatch):
    _enable_get(run, monkeypatch, ws)

    class Tty(io.TextIOWrapper):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdout", Tty(io.BytesIO(), encoding="utf-8"))
    with pytest.raises(Refused, match="screen"):
        cli_secret_get = secretrun.get
        cli_secret_get(ws, "plain", "other-token", stdout_is_tty=True, out=io.BytesIO(), agent=False)


def test_get_is_off_again_after_get_disable(store, run, ws, monkeypatch):
    _enable_get(run, monkeypatch, ws)
    code, *_ = _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.profile", "plain:allow_get"),
        "secret",
        "profile",
        "get-disable",
        "plain",
    )
    assert code == 0
    assert run("secret", "get", "plain", "other-token")[0] == 2


def test_profile_set_resets_get(store, run, ws, monkeypatch):
    _enable_get(run, monkeypatch, ws)
    code, out, err = _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.profile", "plain"),
        "secret",
        "profile",
        "set",
        "plain",
        "--env",
        "PLAIN_TOKEN=other-token",
    )
    assert code == 0, out + err
    assert run("secret", "get", "plain", "other-token")[0] == 2


# --------------------------------------------------------------------------- person-only ops (H1)

OPS = {
    "add": ("secret.add", "new-key", ["secret", "add", "new-key", "--type", "token"], TOKEN + "\n"),
    "remove": ("secret.remove", "other-token", ["secret", "remove", "other-token"], ""),
    "profile-set": (
        "secret.profile",
        "fresh",
        ["secret", "profile", "set", "fresh", "--env", "FRESH_TOKEN=other-token"],
        "",
    ),
    "profile-remove": ("secret.profile", "plain:remove", ["secret", "profile", "remove", "plain"], ""),
    "get-enable": ("secret.profile", "plain:allow_get", ["secret", "profile", "get-enable", "plain"], ""),
    "get-disable": ("secret.profile", "plain:allow_get", ["secret", "profile", "get-disable", "plain"], ""),
    "agents-enable": (
        "secret.profile",
        "plain:agents_may_env",
        ["secret", "profile", "agents-enable", "plain"],
        "",
    ),
    "agents-disable": (
        "secret.profile",
        "plain:agents_may_env",
        ["secret", "profile", "agents-disable", "plain"],
        "",
    ),
}


PROVEN = [n for n in OPS if n not in ("get-disable", "agents-disable")]  # switching off needs no proof


def _state(ws):
    return (
        [(k["name"], k["state"]) for k in keystore.list_keys(ws)],
        keystore.read_profiles(ws),
        hp.effective(ws, "secret.allow_get.plain", True),
    )


@pytest.mark.parametrize("name", OPS)
def test_each_person_op_succeeds_with_a_valid_proof(store, run, ws, monkeypatch, name):
    op, target, argv, rest = OPS[name]
    before = _state(store)
    code, out, err = _cli(run, monkeypatch, _proof(ws, op, target), *argv, stdin_rest=rest)
    assert code == 0, out + err
    assert TOKEN not in out + err and TOKEN2 not in out + err
    assert name in ("get-disable", "agents-disable") or _state(ws) != before


@pytest.mark.parametrize("name", PROVEN)
@pytest.mark.parametrize(
    "case", ["forged", "missing", "expired", "wrong_target", "wrong_op", "replay", "by_mismatch"]
)
def test_each_person_op_refuses_a_bad_proof_and_changes_nothing(store, run, ws, monkeypatch, name, case):
    op, target, argv, rest = OPS[name]
    before = _state(ws)
    now = int(time.time())
    if case == "forged":
        good = _proof(ws, op, target)
        proof = good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB")
    elif case == "missing":
        proof = ""
    elif case == "expired":
        proof = _proof(ws, op, target, now=now - 120)
    elif case == "wrong_target":
        proof = _proof(ws, op, "someone-else")
    elif case == "wrong_op":
        proof = _proof(ws, "secret.remove" if op != "secret.remove" else "secret.add", target)
    elif case == "by_mismatch":
        proof = _proof(ws, op, target)
        argv = [*argv, "--by", "human:someone-else"]
    else:
        proof = _proof(ws, op, target)
        first = _cli(run, monkeypatch, proof, *argv, stdin_rest=rest)
        assert first[0] == 0
        before = _state(ws)
    code, out, err = _cli(run, monkeypatch, proof, *argv, stdin_rest=rest)
    assert code == 2, out + err
    assert _state(ws) == before
    assert TOKEN not in out + err


@pytest.mark.parametrize("name", PROVEN)
def test_each_person_op_without_a_proof_flag_is_refused_whatever_by_says(store, run, ws, name):
    op, target, argv, _ = OPS[name]
    before = _state(ws)
    for by in ("human:pat", "human:owner"):
        code, out, err = run(*argv, "--by", by)
        assert code == 2 and "dashboard" in (out + err)
    assert run(*argv, "--by", "agent:claude")[0] == 2
    assert _state(ws) == before


@pytest.mark.parametrize("name", PROVEN)
def test_an_agent_with_a_valid_proof_is_still_refused(store, run, ws, monkeypatch, name):
    op, target, argv, rest = OPS[name]
    monkeypatch.setenv("CLAUDECODE", "1")
    before = _state(ws)
    code, *_ = _cli(run, monkeypatch, _proof(ws, op, target), *argv, stdin_rest=rest)
    assert code == 2 and _state(ws) == before


def test_add_takes_the_value_from_stdin_and_never_prints_it(store, run, ws, monkeypatch):
    code, out, err = _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.add", "new-key"),
        "secret",
        "add",
        "new-key",
        "--type",
        "token",
        "--json",
        stdin_rest=TOKEN + "\n",
    )
    assert code == 0 and TOKEN not in out + err
    assert keystore.get_value(ws, "new-key") == TOKEN
    assert TOKEN not in _tree_text(ws)  # nothing in the workspace


def test_add_too_short_value_is_refused_without_echo(store, run, ws, monkeypatch):
    code, out, err = _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.add", "tiny"),
        "secret",
        "add",
        "tiny",
        "--type",
        "token",
        stdin_rest="abc\n",
    )
    assert code == 2 and "abc" not in out + err.replace("at least 8", "")


def test_add_key_file_from_a_path(store, run, ws, monkeypatch):
    f = ws / "k.pem"
    f.write_bytes(b"-----BEGIN-----\nabcdefghijklmnopqrstuvwxyz0123456789\n-----END-----\n")
    code, out, err = _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.add", "kk"),
        "secret",
        "add",
        "kk",
        "--type",
        "key-file",
        "--file",
        str(f),
    )
    assert code == 0, out + err
    assert keystore.get_value(ws, "kk") == f.read_bytes()


def test_stub_commands_are_gone_from_the_cli(store, run):
    code, _, err = run("secret", "list")
    assert code == 0 and "not built yet" not in err


def test_no_subcommand_lists_them(store, run):
    code, _, err = run("secret")
    assert code == 2 and "Subcommands" not in err and "env, file, exec, list, get" in err


# --------------------------------------------------------------------------- agents_may_env (agent callers)

LOCK_RUN = [PY, "-c", "import os;print(len(os.environ['LOCK_TOKEN']))"]


@pytest.fixture
def lock(store, ws, in_run, monkeypatch):
    prof = keystore.read_profiles(ws)
    prof["lock"] = {"env": {"LOCK_TOKEN": "other-token"}, "files": {}, "run": LOCK_RUN}
    seed_profiles(ws, prof)
    monkeypatch.setenv("CLAUDECODE", "1")  # an agent tool in the environment
    return ws


def _as_person(run, monkeypatch, ws, op_args, target, *rest):
    """A person's proven op, with the agent marker out of the environment for the call."""
    monkeypatch.delenv("CLAUDECODE", raising=False)
    try:
        return _cli(
            run, monkeypatch, _proof(ws, "secret.profile", target), "secret", "profile", *op_args, *rest
        )
    finally:
        monkeypatch.setenv("CLAUDECODE", "1")


def _enable_agents(run, monkeypatch, ws, profile="lock"):
    monkeypatch.delenv("CLAUDECODE", raising=False)
    code, out, err = _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.profile", f"{profile}:agents_may_env"),
        "secret",
        "profile",
        "agents-enable",
        profile,
    )
    monkeypatch.setenv("CLAUDECODE", "1")
    assert code == 0, out + err


def _listener():
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(1.5)
    got = []

    def accept():
        try:
            c, _ = srv.accept()
            got.append(c.recv(4096))
        except OSError:
            pass

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    return srv, srv.getsockname()[1], got, t


def _refused(run, *cmd, profile="lock", mode="env"):
    code, out, err = run("secret", mode, profile, "--", *cmd)
    assert code == 2 and "agents may only run this profile's own command" in err, (code, out, err)
    assert TOKEN2 not in out + err
    return out, err


def test_agent_can_run_exactly_the_profiles_own_command(lock, run):
    code, out, _ = run("secret", "env", "lock", "--", *LOCK_RUN)
    assert code == 0 and out.strip() == str(len(TOKEN2))


@pytest.mark.parametrize(
    "cmd",
    [
        [PY, "-c", "import os;print(os.environ['LOCK_TOKEN'])"],
        ["/bin/sh", "-c", "echo $LOCK_TOKEN"],
        ["/usr/bin/env"],
        ["python3", "-c", "print(1)"],
        [PY],
        [*LOCK_RUN, "--eval", "x"],
        [*LOCK_RUN[:2]],
        ["/usr/bin/curl", "http://127.0.0.1:1/"],
    ],
    ids=["python-c", "sh-c", "env", "bare-name", "interpreter-alone", "loose-args", "shorter", "curl"],
)
def test_agent_cannot_run_other_commands_while_the_switch_is_off(lock, run, cmd, events):
    _refused(run, *cmd)
    assert events and {e["refused"] for e in events} == {"agent_command"}
    assert all(e["outcome"]["ok"] is False for e in events)


def test_exfil_to_a_local_port_never_starts(lock, run):
    srv, port, got, t = _listener()
    prog = (
        f"import os,socket;s=socket.create_connection(('127.0.0.1',{port}));"
        "s.sendall(os.environ['LOCK_TOKEN'].encode())"
    )
    _refused(run, PY, "-c", prog)
    t.join(2)
    srv.close()
    assert got == []


def test_a_symlinked_interpreter_alias_is_refused(lock, run, ws, monkeypatch):
    alias = ws.parent / "alias-python"
    alias.symlink_to(PY)
    _refused(run, str(alias), "-c", "print(1)")
    _refused(run, str(alias), *LOCK_RUN[1:])  # same arguments, other program path: not the approved one


def test_argv0_spoof_is_refused(lock, run, ws, monkeypatch):
    spoof = ws.parent / "python-spoof"
    spoof.write_text("#!/bin/sh\necho spoofed\n")
    spoof.chmod(0o755)
    _refused(run, str(spoof), *LOCK_RUN[1:])


def test_by_agent_flag_counts_as_an_agent_even_without_the_environment(lock, run, monkeypatch):
    monkeypatch.delenv("CLAUDECODE")
    _refused_code = run("secret", "env", "--by", "agent:codex", "lock", "--", "/bin/sh", "-c", "echo hi")
    assert _refused_code[0] == 2 and "own command" in _refused_code[2]


def test_a_person_or_script_is_not_restricted(lock, run, monkeypatch):
    monkeypatch.delenv("CLAUDECODE")
    code, out, _ = run("secret", "env", "lock", "--", "/bin/sh", "-c", "echo hi")
    assert code == 0 and "hi" in out


def test_exec_without_extra_arguments_is_allowed_for_an_agent(lock, run):
    code, out, _ = run("secret", "exec", "lock")
    assert code == 0 and out.strip() == str(len(TOKEN2))


EXTRA = [["-c", "print(1)"], ["/tmp/out.txt"], ["--eval", "x"]]


@pytest.mark.parametrize("extra", EXTRA, ids=["-c", "path", "flag"])
def test_agent_exec_with_extra_arguments_is_refused(lock, run, events, extra):
    _refused(run, *extra, mode="exec")
    assert events and {e["refused"] for e in events} == {"agent_command"}


def test_agent_exec_extra_arguments_cannot_reach_the_keys(lock, run, ws):
    marker = ws.parent / "exec-leak.txt"
    # run is `python -c <prog>`: an appended argument would become sys.argv, here an output path
    prof = keystore.read_profiles(ws)
    prof["lock"]["run"] = [PY, "-c", "import os,sys;open(sys.argv[1],'w').write(os.environ['LOCK_TOKEN'])"]
    seed_profiles(ws, prof)
    _refused(run, str(marker), mode="exec")
    assert not marker.exists()


def test_agent_exec_by_flag_with_extra_arguments_is_refused(lock, run, monkeypatch):
    monkeypatch.delenv("CLAUDECODE")
    code, _, err = run("secret", "exec", "--by", "agent:codex", "lock", "--", "-c", "print(1)")
    assert code == 2 and "own command" in err


def test_agent_exec_with_the_switch_on_may_add_arguments(lock, run, ws, monkeypatch):
    _enable_agents(run, monkeypatch, ws)
    code, out, err = run("secret", "exec", "lock", "--", "--extra")
    assert code == 0, (code, out, err)
    assert "agents may only" not in err and out.strip().isdigit(), (code, out, err)


def test_a_person_exec_with_extra_arguments_is_allowed(store, run, ws, monkeypatch):
    prof = keystore.read_profiles(ws)
    run_cmd = [PY, "-c", "import sys;print(sys.argv[1])"]
    prof["pl"] = {"env": {"T": "other-token"}, "files": {}, "run": run_cmd}
    seed_profiles(ws, prof)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    code, out, _ = run("secret", "exec", "pl", "--", "hello")
    assert code == 0 and out.strip() == "hello"


@pytest.mark.parametrize("mode", ["env", "file", "exec"])
def test_all_three_modes_share_one_agent_gate(lock, run, ws, events, mode):
    prof = keystore.read_profiles(ws)
    prof["lock"]["files"] = {"F": "other-token"} if mode == "file" else {}
    prof["lock"]["extra"] = ["F"] if mode == "file" else []
    seed_profiles(ws, prof)
    cmd = ["--eval", "x"] if mode == "exec" else ["/bin/sh", "-c", "echo $LOCK_TOKEN"]
    _refused(run, *cmd, mode=mode)
    assert {e["refused"] for e in events} == {"agent_command"}
    assert {e["action"] for e in events} == {mode}
    ok = [] if mode == "exec" else list(LOCK_RUN)
    assert run("secret", mode, "lock", "--", *ok)[0] == 0


def test_file_mode_has_the_same_limit(lock, run, ws):
    prof = keystore.read_profiles(ws)
    prof["flock"] = {"env": {}, "files": {"F": "sa.pem"}, "extra": ["F"], "run": [PY, "-c", "pass"]}
    seed_profiles(ws, prof)
    _refused(run, "/bin/sh", "-c", "cat $F", profile="flock", mode="file")
    assert run("secret", "file", "flock", "--", PY, "-c", "pass")[0] == 0


def test_switch_on_allows_any_command_and_needs_the_person_record(lock, run, ws, monkeypatch):
    prof = keystore.read_profiles(ws)
    prof["lock"]["agents_may_env"] = True
    seed_profiles(ws, prof)  # the file alone: no matching record
    _refused(run, "/bin/sh", "-c", "echo hi")
    _enable_agents(run, monkeypatch, ws)
    code, out, _ = run("secret", "env", "lock", "--", "/bin/sh", "-c", "echo $LOCK_TOKEN")
    assert code == 0 and TOKEN2 not in out and "[hidden: other-token]" in out
    _as_person(run, monkeypatch, ws, ("agents-disable", "lock"), "lock:agents_may_env")
    _refused(run, "/bin/sh", "-c", "echo hi")


def test_profile_set_turns_the_switch_off_again(lock, run, ws, monkeypatch):
    _enable_agents(run, monkeypatch, ws)
    code, out, err = _as_person(
        run, monkeypatch, ws, ("set", "lock"), "lock",
        "--env", "LOCK_TOKEN=other-token", "--run", PY, "--run=-c", "--run", "pass",
    )  # fmt: skip
    assert code == 0, out + err
    _refused(run, "/bin/sh", "-c", "echo hi")


# --------------------------------------------------------------------------- review fixes (Opus, #459)


def test_turning_a_switch_off_needs_no_proof_even_for_an_agent(lock, run, ws, monkeypatch):
    _enable_agents(run, monkeypatch, ws)
    _as_person(run, monkeypatch, ws, ("get-enable", "plain"), "plain:allow_get")
    for sub, name in (("agents-disable", "lock"), ("get-disable", "plain")):
        code, out, err = run("secret", "profile", sub, name, "--by", "agent:claude")
        assert code == 0, out + err
    _refused(run, "/bin/sh", "-c", "echo hi")
    assert run("secret", "get", "plain", "other-token")[0] == 2
    assert hp.effective(ws, "secret.agents_may_env.lock", True) is False  # the record says off, by "reset"


def test_removing_a_profile_is_not_authorised_by_a_set_proof(store, run, ws, monkeypatch):
    code, *_ = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "plain"), "secret", "profile", "remove", "plain"
    )
    assert code == 2 and "plain" in keystore.read_profiles(ws)
    code, *_ = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "plain:remove"), "secret", "profile", "remove", "plain"
    )
    assert code == 0 and "plain" not in keystore.read_profiles(ws)


def test_a_hand_edit_to_off_writes_the_off_record(store, run, ws, monkeypatch):
    _enable_get(run, monkeypatch, ws)
    prof = keystore.read_profiles(ws)
    prof["plain"]["allow_get"] = False
    seed_profiles(ws, prof)
    assert run("secret", "get", "plain", "other-token")[0] == 2  # writes the tombstone
    prof["plain"]["allow_get"] = True
    seed_profiles(ws, prof)  # back on in the file only: the old record must not come back
    assert run("secret", "get", "plain", "other-token")[0] == 2


def test_profile_set_stores_the_program_as_a_full_path(store, run, ws, monkeypatch):
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "bare"), "secret", "profile", "set", "bare",
        "--env", "T=other-token", "--run", "sh",
    )  # fmt: skip
    assert code == 0, out + err
    assert os.path.isabs(keystore.read_profiles(ws)["bare"]["run"][0])


def test_profile_set_never_finds_a_program_in_the_workspace(store, run, ws, monkeypatch):
    planted = ws / "bin"
    planted.mkdir()
    (planted / "mytool").write_text("#!/bin/sh\n")
    (planted / "mytool").chmod(0o755)
    monkeypatch.setenv("PATH", f"{planted}:/usr/bin:/bin")
    code, _, err = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "bare"), "secret", "profile", "set", "bare",
        "--env", "T=other-token", "--run", "mytool",
    )  # fmt: skip
    assert code == 2 and "not found" in err and "bare" not in keystore.read_profiles(ws)


def test_exec_refuses_a_profile_command_that_is_not_a_full_path(store, run, ws, tmp_path, monkeypatch):
    prof = keystore.read_profiles(ws)
    prof["rel"] = {"env": {"T": "other-token"}, "run": ["mytool"]}
    seed_profiles(ws, prof)
    planted = ws / "bin"
    planted.mkdir()
    (planted / "mytool").write_text("#!/bin/sh\necho planted\n")
    (planted / "mytool").chmod(0o755)
    monkeypatch.setenv("PATH", f"{planted}:/usr/bin:/bin")
    code, out, err = run("secret", "exec", "rel")
    assert code == 2 and "planted" not in out and "full path" in err


def test_output_is_released_at_once_not_when_the_command_ends(store, ws):
    """An MCP-style server answers a short line and keeps running: the line must arrive before it exits."""
    times = []

    class Out:
        def write(self, b):
            if b:
                times.append((time.monotonic(), bytes(b)))

        def flush(self):
            pass

    start = time.monotonic()
    prog = "import sys,time;print('{\"ok\":1}');sys.stdout.flush();time.sleep(1.5)"
    code = secretrun.run(ws, "env", "plain", [PY, "-c", prog], stdout=Out(), stderr=Out(), agent=False)
    assert code == 0 and times and times[0][1].startswith(b'{"ok":1}')
    assert times[0][0] - start < 1.2


def test_stream_releases_everything_but_a_possible_needle_start(store, ws):
    from orch import hider

    h = hider.Hider(keystore.all_needles(ws))
    s = hider.HidingStream(h, binary=True)
    assert s.feed(b"reply\n", now=True) == b"reply\n"
    half = TOKEN2[:5].encode()
    assert s.feed(b"x " + half, now=True) == b"x "  # only the start of a possible key is held
    assert s.feed(TOKEN2[5:].encode(), now=True) == b"[hidden: other-token]"


def test_binary_key_file_is_hidden_in_its_hex_form(ws, run):
    blob = bytes(range(256)) * 2
    keystore.add(ws, "blob.p12", "key-file", blob)
    seed_profiles(ws, {"bin": {"files": {"B": "blob.p12"}, "extra": ["B"]}})
    prog = "import os;print(open(os.environ['B'],'rb').read().hex())"
    code, out, _ = run("secret", "file", "bin", "--", PY, "-c", prog)
    assert code == 0 and blob.hex() not in out and "[hidden: blob.p12]" in out


@pytest.mark.skipif(os.name != "posix", reason="POSIX sessions")
def test_the_child_runs_in_its_own_session_without_a_terminal(store, run):
    code, out, _ = run("secret", "env", "plain", "--", PY, "-c", "import os;print(os.getsid(0)==os.getpid())")
    assert code == 0 and "True" in out


def test_pid_liveness():
    assert secretrun._pid_alive(os.getpid()) is True
    assert secretrun._pid_alive(999999999) is False


# --------------------------------------------------------------------------- Opus delta (F1-F7)


class _Sink:
    def __init__(self):
        self.data = b""

    def write(self, b):
        self.data += bytes(b)

    def flush(self):
        pass


def _gone(pid, wait=5.0):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _env():
    return {"PATH": "/usr/bin:/bin"}


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups")
def test_a_background_process_of_the_command_does_not_outlive_it_or_hang_the_call(store, ws):
    from orch import hider

    h = hider.Hider(keystore.all_needles(ws))
    out = _Sink()
    start = time.monotonic()
    code = secretrun._child(["/bin/sh", "-c", "sleep 60 & echo $!"], _env(), h, out, _Sink())
    assert code == 0 and time.monotonic() - start < 8
    assert _gone(int(out.data.split()[0]))


@pytest.mark.skipif(os.name != "posix", reason="POSIX signals")
def test_sigterm_ends_the_command_and_everything_it_started(store, ws):
    import signal
    import threading

    from orch import hider

    h = hider.Hider(keystore.all_needles(ws))
    out = _Sink()
    timer = threading.Timer(0.8, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.start()
    before = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit) as e:
        secretrun._child(["/bin/sh", "-c", "sleep 60 & echo $!; wait"], _env(), h, out, _Sink())
    timer.cancel()
    assert e.value.code == 128 + signal.SIGTERM
    assert _gone(int(out.data.split()[0]))
    assert signal.getsignal(signal.SIGTERM) is before  # handlers restored


@pytest.mark.skipif(os.name != "posix", reason="POSIX signals")
def test_a_second_signal_during_cleanup_is_ignored(store, ws):
    import signal
    import threading

    from orch import hider

    h = hider.Hider(keystore.all_needles(ws))
    timer = threading.Timer(
        0.5, lambda: (os.kill(os.getpid(), signal.SIGTERM), os.kill(os.getpid(), signal.SIGHUP))
    )
    timer.start()
    with pytest.raises(SystemExit) as e:
        secretrun._child(["/bin/sh", "-c", "sleep 60 & wait"], _env(), h, _Sink(), _Sink())
    timer.cancel()
    assert e.value.code in (128 + signal.SIGTERM, 128 + signal.SIGHUP)  # the first one wins


def test_enable_holds_the_key_lock_across_record_and_file(store, run, ws, monkeypatch):
    held = []
    real_lock = hp._key_lock
    depth = []

    import contextlib

    @contextlib.contextmanager
    def tracking(d):
        with real_lock(d):
            depth.append(1)
            try:
                yield
            finally:
                depth.pop()

    monkeypatch.setattr(hp, "_key_lock", tracking)
    real_set = hp.record_set
    monkeypatch.setattr(hp, "record_set", lambda *a, **k: (held.append(bool(depth)), real_set(*a, **k))[1])
    _enable_get(run, monkeypatch, ws)
    assert held and all(held)


def test_reading_the_switch_takes_the_key_lock(store, run, ws, monkeypatch):
    _enable_get(run, monkeypatch, ws)
    import contextlib

    seen = []
    real_lock = hp._key_lock

    @contextlib.contextmanager
    def tracking(d):
        seen.append(1)
        with real_lock(d):
            yield

    monkeypatch.setattr(hp, "_key_lock", tracking)
    assert run("secret", "get", "plain", "other-token")[0] == 0
    assert seen


def test_a_proof_given_with_a_lowering_is_checked_and_spent(store, run, ws, monkeypatch):
    _enable_get(run, monkeypatch, ws)
    argv = ["secret", "profile", "get-disable", "plain"]
    bad = _proof(ws, "secret.profile", "other:allow_get")
    code, *_ = _cli(run, monkeypatch, bad, *argv)
    assert code == 2 and run("secret", "get", "plain", "other-token")[0] == 0  # refused: still on
    good = _proof(ws, "secret.profile", "plain:allow_get")
    assert _cli(run, monkeypatch, good, *argv)[0] == 0
    _enable_get(run, monkeypatch, ws)
    assert _cli(run, monkeypatch, good, *argv)[0] == 2  # spent: a replay is refused


def test_lowering_goes_to_the_recorder_seam_and_a_failing_recorder_does_not_block_it(
    store, run, ws, monkeypatch
):
    got = []
    monkeypatch.setattr(secretrun, "_recorder", lambda root, ev: got.append(ev))
    _enable_get(run, monkeypatch, ws)
    run("secret", "profile", "get-disable", "plain")
    assert got[-1]["action"] == "profile.get_disable" and got[-1]["profile"] == "plain"
    assert got[-1]["by"] == "reset" and TOKEN2 not in json.dumps(got)

    def boom(root, ev):
        raise RuntimeError("x")

    monkeypatch.setattr(secretrun, "_recorder", boom)
    _enable_get(run, monkeypatch, ws)
    assert run("secret", "profile", "get-disable", "plain")[0] == 0


def test_agent_is_a_required_argument(store, ws):
    with pytest.raises(TypeError):
        secretrun.run(ws, "env", "plain", [PY], stdout=_Sink(), stderr=_Sink())


def _set(run, monkeypatch, ws, name, *extra):
    return _cli(
        run, monkeypatch, _proof(ws, "secret.profile", name), "secret", "profile", "set", name,
        "--env", "T=other-token", *extra,
    )  # fmt: skip


def test_set_refuses_a_program_inside_the_workspace(store, run, ws, monkeypatch):
    exe = ws / "mytool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    code, _, err = _set(run, monkeypatch, ws, "inws", "--run", str(exe))
    assert code == 2 and "inside this workspace" in err and "inws" not in keystore.read_profiles(ws)


def test_set_refuses_a_program_others_can_change(store, run, ws, monkeypatch, tmp_path):
    d = tmp_path / "shared"
    d.mkdir()
    exe = d / "tool"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    d.chmod(0o777)
    try:
        code, _, err = _set(run, monkeypatch, ws, "loose", "--run", str(exe))
        assert code == 2 and "other users" in err
        d.chmod(0o700)
        exe.chmod(0o775)
        code, _, err = _set(run, monkeypatch, ws, "loose", "--run", str(exe))
        assert code == 2 and "other users" in err
    finally:
        d.chmod(0o700)


def test_set_refuses_a_relative_path_and_resolves_symlinks(store, run, ws, monkeypatch):
    code, _, err = _set(run, monkeypatch, ws, "rel", "--run", "./tool")
    assert code == 2 and "relative" in err
    code, _, err = _set(run, monkeypatch, ws, "rel", "--run", "bin/tool")
    assert code == 2 and "relative" in err
    code, out, _ = _set(run, monkeypatch, ws, "sym", "--run", "/bin/sh", "--json")
    stored = keystore.read_profiles(ws)["sym"]["run"][0]
    assert stored == os.path.realpath("/bin/sh") and json.loads(out)["command"] == stored


def test_set_warns_about_an_interpreter_and_shows_the_resolved_path(store, run, ws, monkeypatch):
    code, out, err = _set(run, monkeypatch, ws, "interp", "--run", "/bin/sh")
    assert code == 0 and os.path.realpath("/bin/sh") in out
    assert "can run any code" in err
    code, out, err = _set(run, monkeypatch, ws, "interp2", "--run", "/bin/sh", "--json")
    assert json.loads(out)["warnings"]


@pytest.mark.parametrize(
    "prog,warns",
    [
        ("psql", True),
        ("mysql", True),
        ("sqlite3", True),
        ("redis-cli", True),
        ("mongosh", True),
        ("mytool", False),
    ],
)
def test_set_warns_about_database_clients_only(store, run, ws, monkeypatch, tmp_path, prog, warns):
    # a link named like the client to a harmless safe-folder program: matched by the name that was approved
    exe = tmp_path / prog
    exe.symlink_to(os.path.realpath("/usr/bin/true"))
    code, out, err = _set(run, monkeypatch, ws, "db", "--run", str(exe))
    assert code == 0, (code, out, err)
    assert ("can run any code" in err) is warns
    code, out, err = _set(run, monkeypatch, ws, "db2", "--run", str(exe), "--json")
    assert code == 0, (code, out, err)
    assert bool(json.loads(out).get("warnings")) is warns


def test_a_large_key_with_a_diverging_byte_is_not_slow(ws):
    from orch import hider

    big = "".join(chr(97 + (i * 7 + i // 13) % 26) for i in range(60000))
    h = hider.Hider({"big": big})
    s = hider.HidingStream(h)
    start = time.monotonic()
    out = [s.feed(big[:59000], now=True), s.feed("X", now=True)]
    for _ in range(40):
        out.append(s.feed("abc" * 160, now=True))
    out.append(s.close())
    assert time.monotonic() - start < 3
    assert "".join(out).startswith(big[:100])


# --------------------------------------------------------------------------- the real record writer (M1)


def _record_text(ws):
    from orch.record import record_dir

    out = []
    for p in record_dir(ws).rglob("*"):
        if p.is_file():
            out.append(p.read_bytes().decode("utf-8", "replace"))
    return "\n".join(out)


def _forms(value):
    import base64
    from urllib.parse import quote

    raw = value.encode()
    forms = {value, raw.hex(), raw.hex().upper(), quote(value, safe=""), json.dumps(value)[1:-1]}
    for off in range(3):
        b = base64.b64encode(b"x" * off + raw).decode().rstrip("=")
        forms.add(b[4:-4])
        forms.add(base64.urlsafe_b64encode(b"x" * off + raw).decode().rstrip("=")[4:-4])
    return forms


def test_a_use_is_written_to_the_run_record_without_the_value(store, run, ws, in_run):
    from orch.record import read_run

    code, out, err = run(
        "secret", "env", "plain", "--", PY, "-c", "import os;print(os.environ['PLAIN_TOKEN'])"
    )
    assert code == 0
    lines = read_run(ws, RUN).unwrap()
    uses = [x for x in lines if x["kind"] == "key.use"]
    assert (
        len(uses) == 1 and uses[0]["used"]["name"] == "other-token" and uses[0]["data"]["profile"] == "plain"
    )
    assert uses[0]["via"] == "broker" and uses[0]["data"]["command"] == os.path.basename(PY)
    text = _record_text(ws)
    for secret in (TOKEN2, TOKEN):
        for f in _forms(secret):
            assert len(f) < 8 or f not in text, f


def test_a_refusal_and_a_lowering_are_in_the_record(store, run, ws, in_run, monkeypatch):
    from orch.record import read_run

    assert run("secret", "get", "plain", "other-token")[0] == 2
    assert run("secret", "profile", "get-disable", "plain")[0] == 0
    kinds = [
        (x["kind"], x["data"].get("refused") or x["data"].get("action")) for x in read_run(ws, RUN).unwrap()
    ]
    assert ("key.use", "get_off") in kinds and ("secret.change", "profile.get_disable") in kinds


def test_no_hider_for_the_record_stops_the_command(store, run, ws, in_run, monkeypatch):
    from orch import record

    class Off:
        def __init__(self, *a, **k):
            raise record.RecordOff("Recording is off until key hiding is ready.")

    monkeypatch.setattr(record, "RecordWriter", Off)
    code, out, err = run(
        "secret", "env", "plain", "--", PY, "-c", f"open({str(ws / 'started')!r}, 'w').close()"
    )
    assert code == 2 and "could not be recorded" in err and not (ws / "started").exists()
    assert TOKEN2 not in out + err


def test_a_damaged_record_stops_the_command_but_not_a_lowering(store, run, ws, in_run, monkeypatch):
    from orch import record

    def boom(*a, **k):
        raise record.RecordUnavailable("io")

    monkeypatch.setattr(record.RecordWriter, "append", boom)
    code, _, err = run("secret", "env", "plain", "--", PY, "-c", "pass")
    assert code == 2 and "could not be recorded" in err
    assert run("secret", "profile", "get-disable", "plain")[0] == 0


def test_outside_a_run_a_person_or_script_is_written_to_the_unattributed_run(store, run, ws):
    from orch.record import read_run

    assert run("secret", "env", "plain", "--", PY, "-c", "pass")[0] == 0
    assert run("secret", "profile", "get-disable", "plain")[0] == 0
    day = time.strftime("%Y%m%d", time.gmtime())
    lines = read_run(ws, f"r_outside_{day}").unwrap()
    assert [x["kind"] for x in lines] == ["key.use", "secret.change"]
    assert {x["ticket"] for x in lines} == {"t_outside"} and lines[0]["harness"] == "generic"
    assert TOKEN2 not in _record_text(ws)


def test_an_unrecordable_call_outside_a_run_is_refused_too(store, run, ws, monkeypatch):
    from orch import record

    def boom(*a, **k):
        raise record.RecordUnavailable("io")

    monkeypatch.setattr(record.RecordWriter, "append", boom)
    code, _, err = run(
        "secret", "env", "plain", "--", PY, "-c", f"open({str(ws / 'started')!r}, 'w').close()"
    )
    assert code == 2 and "could not be recorded" in err and not (ws / "started").exists()


def test_a_failing_record_leaves_no_key_file_behind(store, run, ws, monkeypatch):
    def boom(root, ev):
        raise RuntimeError("no")

    monkeypatch.setattr(secretrun, "_recorder", boom)
    code, _, err = run("secret", "file", "filesonly", "--", PY, "-c", "pass")
    assert code == 2 and "could not be recorded" in err
    assert not (hp.guarded_home(ws) / "keys" / "tmp").exists()


def test_the_record_text_is_built_from_the_checked_command_name(store, run, ws, in_run):
    from orch.record import read_run

    odd = ws / "we ird;name"
    odd.write_text("#!/bin/sh\nexit 0\n")
    odd.chmod(0o755)
    assert run("secret", "env", "plain", "--", str(odd))[0] == 0
    use = next(x for x in read_run(ws, RUN).unwrap() if x["kind"] == "key.use")
    assert use["text"] == "Key other-token handed to a command" and use["data"]["command"] is None


def test_secret_change_by_must_be_a_person_or_reset():
    import jsonschema

    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts" / "activity.schema.json").read_text()
    )
    v = jsonschema.Draft202012Validator(schema)
    ev = json.loads(
        (
            Path(__file__).resolve().parents[2] / "contracts/examples/activity/valid-secret-change.json"
        ).read_text()
    )
    assert v.is_valid(ev)
    for by in ("human:pat", "reset"):
        assert v.is_valid({**ev, "data": {**ev["data"], "by": by}})
    for by in ("agent:x", "someone", "human:", ""):
        assert not v.is_valid({**ev, "data": {**ev["data"], "by": by}}), by


# --------------------------------------------------------------------------- agents need a live run


def _nothing_touched(ws):
    assert not (ws / "started").exists()
    assert not (hp.guarded_home(ws) / "keys" / "tmp").exists()


def _agent_call(run, monkeypatch, *cmd, profile="filesonly", mode="file"):
    monkeypatch.setenv("CLAUDECODE", "1")
    return run("secret", mode, profile, "--", *cmd)


@pytest.mark.parametrize("how", ["no-run", "only-run", "only-ticket"])
def test_an_agent_without_a_run_is_refused_before_anything_is_touched(store, run, ws, monkeypatch, how):
    if how != "no-run":
        monkeypatch.setenv(
            "ORCH_RUN" if how == "only-run" else "ORCH_TICKET", RUN if how == "only-run" else TICKET
        )
    code, out, err = _agent_call(run, monkeypatch, PY, "-c", f"open({str(ws / 'started')!r}, 'w').close()")
    assert code == 2 and "inside an active orch run" in err
    _nothing_touched(ws)


def test_an_agent_by_flag_without_a_run_is_refused_too(store, run, ws):
    code, _, err = run("secret", "env", "--by", "agent:codex", "plain", "--", PY, "-c", "pass")
    assert code == 2 and "inside an active orch run" in err


def test_an_agent_without_a_run_cannot_get_a_key(store, run, ws, monkeypatch):
    _enable_get(run, monkeypatch, ws)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = run("secret", "get", "plain", "other-token")
    assert code == 2 and TOKEN2 not in out + err


def test_an_agent_with_a_run_that_does_not_match_the_ticket_is_refused(store, run, ws, monkeypatch):
    _claim(ws, run="r_other0001")
    monkeypatch.setenv("ORCH_RUN", RUN)
    monkeypatch.setenv("ORCH_TICKET", TICKET)
    code, _, err = _agent_call(run, monkeypatch, PY, "-c", f"open({str(ws / 'started')!r}, 'w').close()")
    assert code == 2 and "not active" in err
    _nothing_touched(ws)


def test_an_agent_with_a_dead_or_finished_run_is_refused(store, run, ws, monkeypatch):
    monkeypatch.setenv("ORCH_RUN", RUN)
    monkeypatch.setenv("ORCH_TICKET", TICKET)
    code, _, err = _agent_call(run, monkeypatch, PY, "-c", "pass")  # no claim at all: finished
    assert code == 2 and "not active" in err
    _claim(ws, pid=999999999)  # a claim whose process is gone
    code, _, err = _agent_call(run, monkeypatch, PY, "-c", "pass")
    assert code == 2 and "not active" in err
    _nothing_touched(ws)


def test_an_agent_with_a_live_matching_run_works_and_is_recorded(lock, run, ws):
    from orch.record import read_run

    code, out, err = run("secret", "env", "lock", "--", *LOCK_RUN)
    assert code == 0, err
    assert [x["kind"] for x in read_run(ws, RUN).unwrap()] == ["key.use"]


def test_a_person_or_script_without_a_run_still_works(store, run, ws):
    assert run("secret", "env", "plain", "--", PY, "-c", "pass")[0] == 0
    assert run("secret", "file", "filesonly", "--", PY, "-c", "pass")[0] == 0


def test_a_script_naming_a_run_that_is_not_live_is_refused_and_writes_nothing(store, run, ws, monkeypatch):
    from orch.record import record_dir

    monkeypatch.setenv("ORCH_RUN", RUN)
    monkeypatch.setenv("ORCH_TICKET", TICKET)
    code, _, err = run("secret", "env", "plain", "--", PY, "-c", "pass")
    assert code == 2 and "not active" in err and not record_dir(ws).exists()


# ----------------------------------------------------------------------- retention of the unattributed run


def _write_line(ws, run, kind="key.use", **over):
    from orch import record

    ev = {"kind": "key.use", "key": "other-token", "action": "env", "profile": "plain", "command": "x",
          "skill": None, "outcome": {"ok": True}, "refused": None}  # fmt: skip
    old = os.environ.get("ORCH_RUN"), os.environ.get("ORCH_TICKET")
    os.environ["ORCH_RUN"], os.environ["ORCH_TICKET"] = run, "t_outside"
    try:
        line = secretrun._record_event(ws, ev)
    finally:
        for k, v in zip(("ORCH_RUN", "ORCH_TICKET"), old, strict=True):
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    line.update(over, kind=kind)
    record.RecordWriter(ws, hider=__import__("orch.hider", fromlist=["x"]).Hider({"k": TOKEN2})).append(line)


def test_the_unattributed_run_is_deleted_by_retention_by_the_day_in_its_id(store, ws):
    from orch import record

    _write_line(ws, "r_outside_20250101")
    day = time.strftime("%Y%m%d", time.gmtime())
    _write_line(ws, f"r_outside_{day}")
    # a planted run.state with an old `at` must not make today's run look old or ended
    _write_line(ws, f"r_outside_{day}", kind="run.state", text="done", via="core", outcome=None, used=None,
                data={"state": "done"}, at="2000-01-01T00:00:00Z")  # fmt: skip
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result = record.apply_retention(ws, now, 90, 2048, lambda run, events: None)
    assert result["delete_run"] == ["r_outside_20250101"], result
    assert record.read_run(ws, f"r_outside_{day}").status == "ok"


def test_the_unattributed_run_of_the_day_is_not_ended_until_midnight(store, ws):
    from orch import record

    _write_line(ws, "r_outside_20260101")
    assert record.apply_retention(ws, "2026-01-01T12:00:00Z", 0, 0, lambda r, e: None)["delete_run"] == []
    assert record.apply_retention(ws, "2026-01-02T00:00:01Z", 0, 0, lambda r, e: None)["delete_run"] == [
        "r_outside_20260101"
    ]


def test_the_unattributed_run_has_a_daily_cap(store, run, ws, monkeypatch):
    monkeypatch.setattr(secretrun, "OUTSIDE_DAY_CAP", 3)
    codes = [run("secret", "env", "plain", "--", PY, "-c", "pass")[0] for _ in range(4)]
    assert codes == [0, 0, 0, 2]


# --------------------------------------------------------------------------- profile body MAC (W2b, HIGH)


def _pfile(ws):
    return hp.key_dir(ws) / "profiles.toml"


def _edit_file(ws, old, new):
    """What anything running as the user can do: edit the profile file directly (no proof, no ledger)."""
    f = _pfile(ws)
    text = f.read_text()
    head, sep, tail = text.partition("[profile.good]")
    block, sep2, rest = tail.partition("\n[")
    assert old in block
    f.write_text(head + sep + block.replace(old, new) + sep2 + rest)


def _set_ok(run, monkeypatch, ws, name, *extra, proof_name=None):
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", proof_name or name), "secret", "profile", "set", name,
        "--env", "T=other-token", *extra,
    )  # fmt: skip
    assert code == 0, out + err


EDITED = "changed outside orch"


def test_profile_set_with_proof_then_exec_still_works(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY, "--set", "A=b", "--extra", "A")
    assert hp.profile_verified(ws, "good", keystore.read_profiles(ws)["good"])
    code, out, err = run("secret", "exec", "good", "--", "-c", "import os;print(os.environ['T'])")
    assert code == 0 and "[hidden: other-token]" in out, err


def test_an_edited_run_in_the_profile_file_is_refused(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    _edit_file(ws, os.path.realpath(PY), "/bin/echo")
    for argv in (("exec", "good"), ("env", "good", "--", PY, "-c", "pass")):
        code, out, err = run("secret", *argv)
        assert code == 2 and EDITED in err, argv


@pytest.mark.parametrize(
    "old,new",
    [
        ('T = "other-token"', 'T = "api-token"'),  # another key into the same variable
        ('T = "other-token"', 'T = "other-token", U = "api-token"'),  # an extra env variable
        ("run = [", 'extra = ["F"]\nfiles = { F = "sa.pem" }\nrun = ['),  # an added file
        ("run = [", 'extra = ["X"]\nset = { X = "1" }\nrun = ['),  # an added plain setting
    ],
)
def test_an_edited_env_files_or_set_is_refused(store, run, ws, monkeypatch, old, new):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    _edit_file(ws, old, new)
    code, _, err = run("secret", "env", "good", "--", PY, "-c", "pass")
    assert code == 2 and EDITED in err


def test_an_edited_profile_cannot_be_revived_by_a_switch_change(store, run, ws, monkeypatch):
    """Turning a switch rewrites the file; it must not re-sign a body that was edited outside orch."""
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    _edit_file(ws, os.path.realpath(PY), "/bin/echo")
    code, out, err = _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.profile", "good:allow_get"),
        "secret",
        "profile",
        "get-enable",
        "good",
    )
    assert code == 0, out + err
    assert run("secret", "env", "good", "--", PY, "-c", "pass")[0] == 2
    assert run("secret", "get", "good", "other-token")[0] == 2


def test_a_profile_without_a_mac_is_refused_even_for_get(store, run, ws, monkeypatch):
    f = _pfile(ws)
    f.write_text(f.read_text() + '\n[profile.forged]\nenv = { T = "other-token" }\nallow_get = true\n')
    for argv in (("env", "forged", "--", PY, "-c", "pass"), ("get", "forged", "other-token")):
        code, _, err = run("secret", *argv)
        assert code == 2 and EDITED in err


def test_a_copied_mac_from_another_profile_or_workspace_is_refused(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "one", "--run", PY)
    # same body under another name: the ledger has no entry for it
    text = _pfile(ws).read_text()
    block = text[text.index("[profile.one]") :].split("\n[")[0]
    _pfile(ws).write_text(text + "\n" + block.replace("profile.one", "profile.two"))
    assert run("secret", "env", "two", "--", PY, "-c", "pass")[0] == 2
    # the ledger entry of one name copied to another
    ledger = hp.key_dir(ws) / hp.PROFILE_LEDGER
    data = json.loads(ledger.read_text())
    data["entries"]["two"] = data["entries"]["one"]
    ledger.write_text(json.dumps(data))
    code, _, err = run("secret", "env", "two", "--", PY, "-c", "pass")
    assert code == 2 and EDITED in err
    # a MAC made for another workspace id does not verify here
    body = keystore.read_profiles(ws)["one"]
    other = hp.profile_mac(hp.human_key(ws), "f" * 32, "one", body)
    data["entries"]["one"] = other
    ledger.write_text(json.dumps(data))
    assert run("secret", "env", "one", "--", PY, "-c", "pass")[0] == 2


def test_a_profile_with_a_missing_ledger_is_refused(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    (hp.key_dir(ws) / hp.PROFILE_LEDGER).unlink()
    code, _, err = run("secret", "env", "good", "--", PY, "-c", "pass")
    assert code == 2 and EDITED in err


def test_remove_tombstones_the_mac(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    saved = _pfile(ws).read_text()
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "good:remove"), "secret", "profile", "remove", "good"
    )
    assert code == 0, out + err
    _pfile(ws).write_text(saved)  # the old file put back
    assert run("secret", "env", "good", "--", PY, "-c", "pass")[0] == 2


@pytest.mark.parametrize(
    "var",
    [
        "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "PATH", "Path", "NODE_OPTIONS", "BASH_ENV", "GIT_SSH_COMMAND",
        "PYTHONPATH", "PYTHONSTARTUP", "PERL5OPT", "RUBYOPT", "NODE_PATH", "IFS", "SHELLOPTS", "PS4", "ENV",
        "JAVA_TOOL_OPTIONS", "MY_OPTIONS", "PATHEXT", "COMSPEC", "ld_preload",
    ],
)  # fmt: skip
def test_loader_and_interpreter_variables_are_refused_at_set_and_at_run(store, run, ws, monkeypatch, var):
    for sect in ("--set", "--env"):
        value = "x" if sect == "--set" else "other-token"
        code, _, err = _cli(
            run, monkeypatch, _proof(ws, "secret.profile", "bad"), "secret", "profile", "set", "bad",
            "--env", "T=other-token", sect, f"{var}={value}",
        )  # fmt: skip
        assert code == 2 and "bad" not in keystore.read_profiles(ws), (var, sect)
    # forged into the file of a signed profile: refused at run time as well
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    _edit_file(ws, "run = [", f'set = {{ {var} = "x" }}\nrun = [')
    assert run("secret", "env", "good", "--", PY, "-c", "pass")[0] == 2


def test_a_denied_variable_with_a_valid_mac_still_fails_at_run(store, run, ws, monkeypatch):
    """Defence in depth: even a body someone managed to sign is refused when it is read and when it runs."""
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    _edit_file(ws, "run = [", 'set = { NODE_OPTIONS = "--require x" }\nrun = [')
    body = {"env": {"T": "other-token"}, "set": {"NODE_OPTIONS": "--require x"}, "run": [PY]}
    hp.profile_sign(ws, "good", body)  # a forged-but-signed body (the signer being compromised)
    code, _, err = run("secret", "env", "good", "--", PY, "-c", "pass")
    assert code == 2 and "NODE_OPTIONS" in err
    # and the run-time check alone, with the reader's check out of the way
    monkeypatch.setattr(keystore, "read_profiles", lambda root: {"good": body})
    monkeypatch.setattr(hp, "profile_verified", lambda *a: True)
    with pytest.raises(Refused, match="may not set"):
        secretrun._profile(ws, "good")


def test_exec_checks_the_program_again_when_it_runs(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    monkeypatch.setattr(
        secretrun, "approve_program", lambda root, name: (_ for _ in ()).throw(Refused("Refused: gone."))
    )
    code, _, err = run("secret", "exec", "good", "--", "-c", "pass")
    assert code == 2 and "gone" in err


def test_profile_set_without_a_proof_or_with_a_wrong_target_stores_no_mac(store, run, ws, monkeypatch):
    before = (hp.key_dir(ws) / hp.PROFILE_LEDGER).exists()
    args = ("secret", "profile", "set", "nope", "--env", "T=other-token")
    assert run(*args)[0] == 2  # no proof
    assert _cli(run, monkeypatch, _proof(ws, "secret.profile", "other"), *args)[0] == 2  # wrong target
    assert _cli(run, monkeypatch, _proof(ws, "secret.add", "nope"), *args)[0] == 2  # wrong op
    assert "nope" not in keystore.read_profiles(ws)
    ent = hp._ledger_load(ws, hp.PROFILE_LEDGER) or {}
    assert "nope" not in ent and (hp.key_dir(ws) / hp.PROFILE_LEDGER).exists() == before or "nope" not in ent


def test_saving_one_profile_never_signs_an_edited_other_profile(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "a", "--run", PY)
    _set_ok(run, monkeypatch, ws, "b", "--run", PY)
    f = _pfile(ws)
    text = f.read_text()
    head, sep, tail = text.partition("[profile.b]")
    f.write_text(head + sep + tail.replace('T = "other-token"', 'T = "api-token"', 1))
    assert run("secret", "env", "b", "--", PY, "-c", "pass")[0] == 2
    _set_ok(run, monkeypatch, ws, "a", "--run", PY, "--set", "X=1", "--extra", "X")  # the person sets A
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "a:allow_get"), "secret", "profile", "get-enable", "a"
    )
    assert code == 0, out + err
    code, _, err = run("secret", "env", "b", "--", PY, "-c", "pass")
    assert code == 2 and EDITED in err
    assert run("secret", "env", "a", "--", PY, "-c", "pass")[0] == 0


def test_a_damaged_profiles_file_refuses_the_save_and_signs_nothing(store, run, ws, monkeypatch):
    _pfile(ws).write_text("this is = not [ toml")
    before = hp._ledger_load(ws, hp.PROFILE_LEDGER)
    code, _, _ = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "n"), "secret", "profile", "set", "n",
        "--env", "T=other-token",
    )  # fmt: skip
    assert code == 2 and hp._ledger_load(ws, hp.PROFILE_LEDGER) == before


def test_deleting_the_file_between_the_reads_does_not_get_a_body_signed(store, run, ws, monkeypatch):
    """The reported race: the file vanishes (or is corrupted) while a switch is changed; nothing is signed."""
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    _edit_file(ws, os.path.realpath(PY), "/bin/echo")
    real = hp.record_set

    def sabotage(*a, **k):
        _pfile(ws).unlink(missing_ok=True)
        return real(*a, **k)

    monkeypatch.setattr(hp, "record_set", sabotage)
    _cli(
        run,
        monkeypatch,
        _proof(ws, "secret.profile", "good:allow_get"),
        "secret",
        "profile",
        "get-enable",
        "good",
    )
    monkeypatch.setattr(hp, "record_set", real)
    assert run("secret", "exec", "good", "--", "PWNED")[0] == 2


def test_remove_writes_the_tombstone_even_when_the_file_has_no_such_profile(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    saved = _pfile(ws).read_text()
    f = _pfile(ws)
    f.write_text(
        saved.split("[profile.good]")[0] + '[profile.plain]\nenv = { PLAIN_TOKEN = "other-token" }\n'
    )
    code, _, _ = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "good:remove"), "secret", "profile", "remove", "good"
    )
    assert code == 2  # "no such profile", but the tombstone is there
    f.write_text(saved)
    assert run("secret", "env", "good", "--", PY, "-c", "pass")[0] == 2


def test_variable_names_clash_in_any_case(store, run, ws, monkeypatch):
    code, _, _ = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "dup"), "secret", "profile", "set", "dup",
        "--env", "Tok=other-token", "--set", "TOK=x",
    )  # fmt: skip
    assert code == 2 and "dup" not in keystore.read_profiles(ws)


def test_remove_on_a_damaged_file_still_tombstones(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    saved = _pfile(ws).read_text()
    _pfile(ws).write_text("not [ toml")
    code, _, _ = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "good:remove"), "secret", "profile", "remove", "good"
    )
    assert code == 2  # the file is damaged
    _pfile(ws).write_text(saved)
    code, _, err = run("secret", "env", "good", "--", PY, "-c", "pass")
    assert code == 2 and EDITED in err


def test_list_on_a_damaged_file_shows_the_keys_without_profiles(store, run, ws):
    _pfile(ws).write_text("not [ toml")
    code, out, _ = run("secret", "list", "--json")
    assert code == 0 and "api-token" in out


# --- `extra`: person-approved variable names (W2b) ---------------------------------------------


def test_an_undeclared_set_name_is_refused_at_set_and_when_forged(store, run, ws, monkeypatch):
    code, _, err = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "u"), "secret", "profile", "set", "u",
        "--env", "T=other-token", "--set", "SOME_HOST=x",
    )  # fmt: skip
    assert code == 2 and "not an approved variable" in err and "--extra" in err
    _set_ok(run, monkeypatch, ws, "good", "--run", PY)
    _edit_file(ws, "run = [", 'set = { SOME_HOST = "x" }\nrun = [')
    code, _, err = run("secret", "env", "good", "--", PY, "-c", "pass")
    assert code == 2


def test_extra_with_proof_is_accepted_and_reaches_the_command(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY, "--set", "SOME_HOST=h1", "--extra", "SOME_HOST")
    code, out, err = run("secret", "exec", "good", "--", "-c", "import os;print(os.environ['SOME_HOST'])")
    assert code == 0 and "h1" in out, err


@pytest.mark.parametrize(
    "name",
    ["XDG_CONFIG_HOME", "VISUAL", "MANPAGER", "SSH_ASKPASS", "SUDO_ASKPASS", "LESSCLOSE", "lower", "PATH"],
)
def test_extra_with_a_denied_name_is_refused(store, run, ws, monkeypatch, name):
    code, _, _ = _cli(
        run, monkeypatch, _proof(ws, "secret.profile", "x"), "secret", "profile", "set", "x",
        "--env", "T=other-token", "--set", f"{name}=v", "--extra", name,
    )  # fmt: skip
    assert code == 2 and "x" not in keystore.read_profiles(ws)


def test_extra_edited_in_the_file_is_a_mac_mismatch(store, run, ws, monkeypatch):
    _set_ok(run, monkeypatch, ws, "good", "--run", PY, "--set", "SOME_HOST=h1", "--extra", "SOME_HOST")
    _edit_file(ws, 'extra = ["SOME_HOST"]', 'extra = ["SOME_HOST", "OTHER_HOST"]')
    code, _, err = run("secret", "env", "good", "--", PY, "-c", "pass")
    assert code == 2 and EDITED in err


def test_forged_extra_without_a_proof_is_refused(store, run, ws, monkeypatch):
    args = (
        "secret",
        "profile",
        "set",
        "f",
        "--env",
        "T=other-token",
        "--set",
        "SOME_HOST=x",
        "--extra",
        "SOME_HOST",
    )
    assert run(*args)[0] == 2
    assert "f" not in keystore.read_profiles(ws)

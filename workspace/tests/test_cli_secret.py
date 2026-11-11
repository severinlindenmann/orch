"""`orch secret` (slice 1.2): keys go to the command, never to the output; person-only ops need an hp1 proof
(invariant H1); every use is handed to the recorder seam without the value; no fail-open."""

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

from orch import cli, keystore, secretrun
from orch import humanproof as hp
from orch.errors import Refused

TOKEN = "tok-Q7xP2mK9vL4zR8"  # made-up values, long enough to be stored
TOKEN2 = "tok-W3nB6cF1yH5qD0"
PY = sys.executable
_REAL_PERSON_BY, _REAL_PENDING_MAC = hp.person_by, hp.ENFORCE_PENDING_MAC  # before conftest's legacy shim


@pytest.fixture(autouse=True)
def _real_proof(monkeypatch):
    """conftest trusts --by for modules not named test_human_proof*; this module tests the real proof."""
    monkeypatch.setattr(hp, "person_by", _REAL_PERSON_BY)
    monkeypatch.setattr(hp, "ENFORCE_PENDING_MAC", _REAL_PENDING_MAC)


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
    keystore.write_profiles(
        ws,
        {
            "svc": {
                "env": {"SVC_TOKEN": "api-token"},
                "files": {"SVC_KEY": "sa.pem"},
                "set": {"SVC_HOST": "https://example.test"},
                "run": [PY, "-c"],
            },
            "plain": {"env": {"PLAIN_TOKEN": "other-token"}},
            "filesonly": {"files": {"ONLY_KEY": "sa.pem"}},
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
    keystore.write_profiles(ws, prof)  # the file alone: no matching settings record
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
        cli_secret_get(ws, "plain", "other-token", stdout_is_tty=True, out=io.BytesIO())


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
    "profile-remove": ("secret.profile", "plain", ["secret", "profile", "remove", "plain"], ""),
    "get-enable": ("secret.profile", "plain:allow_get", ["secret", "profile", "get-enable", "plain"], ""),
    "get-disable": ("secret.profile", "plain:allow_get", ["secret", "profile", "get-disable", "plain"], ""),
}


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
    assert name == "get-disable" or _state(ws) != before


@pytest.mark.parametrize("name", OPS)
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


@pytest.mark.parametrize("name", OPS)
def test_each_person_op_without_a_proof_flag_is_refused_whatever_by_says(store, run, ws, name):
    op, target, argv, _ = OPS[name]
    before = _state(ws)
    for by in ("human:pat", "human:owner"):
        code, out, err = run(*argv, "--by", by)
        assert code == 2 and "dashboard" in (out + err)
    assert run(*argv, "--by", "agent:claude")[0] == 2
    assert _state(ws) == before


@pytest.mark.parametrize("name", OPS)
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

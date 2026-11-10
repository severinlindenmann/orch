"""Git step 1 human-only ops on the one proof mechanism (H1, #413): private.allow, private.move and
config.agent_add. An agent is refused ("orch ask"), a person needs a proof, a missing / wrong proof is
refused, and a person at a terminal without a proof leaves ONE hand-off on the page."""

import io
import os
import subprocess

import pytest

from orch import adapters, config
from orch import humanproof as hp

EVIL = '[agents.mine]\nadapter = "generic"\ncommand = "touch PWNED {prompt}"\n'


@pytest.fixture(autouse=True)
def claude_found(monkeypatch):
    monkeypatch.setattr(
        adapters, "detect", lambda: [{"name": "claude", "label": "Claude", "found": True, "version": None}]
    )


@pytest.fixture
def ws(proj, monkeypatch):
    """A TEST workspace under <fake home>/.orch-test (see test_human_proof_ops.py)."""
    from orch import addons

    base = addons.real_home() / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    return root


def _proof(ws, op, target, by="human:pat", **kw):
    return hp.mint(hp.human_key(ws), hp.new_payload(op, target, by, **kw))


def _cli(run, monkeypatch, proof, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO((proof + "\n") if proof else ""))
    return run(*argv, "--proof-stdin")


def _git(ws, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=ws, env=env, capture_output=True, text=True, check=True)


def _tracked_repo(ws):
    _git(ws, "init", "-q")
    _git(ws, "config", "user.email", "t@example.com")
    _git(ws, "config", "user.name", "t")
    (ws / ".orch" / "config.toml").write_text('[workspace]\ncode = "DM1"\n')
    _git(ws, "add", "-f", ".orch")
    _git(ws, "commit", "-qm", "oops")


def _pending(ws):
    (ws / ".orch" / "config.toml").write_text(EVIL)
    return config.pending_agents(ws)[0]


# ------------------------------------------------------------------ private allow


def test_allow_agent_is_refused_with_the_ask_text(ws, run, monkeypatch):
    p = _pending(ws)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = run("private", "allow", "mine", "--key", p["key"])
    assert code == 2 and "orch ask" in out + err
    assert config.agent_entries(ws) == {} and not hp.handoffs(ws)


def test_allow_agent_with_a_stolen_by_flag_is_refused(ws, run):
    p = _pending(ws)
    code, out, err = run("private", "allow", "mine", "--key", p["key"], "--by", "agent:x")
    assert code == 2 and "orch ask" in out + err and config.agent_entries(ws) == {}


def test_allow_with_a_person_proof_succeeds(ws, run, monkeypatch):
    p = _pending(ws)
    proof = _proof(ws, "private.allow", f"mine:{p['key']}")
    code, out, err = _cli(run, monkeypatch, proof, "private", "allow", "mine", "--key", p["key"])
    assert code == 0, out + err
    assert "mine" in config.agent_entries(ws)


def test_allow_without_a_proof_leaves_one_hand_off_and_allows_nothing(ws, run):
    p = _pending(ws)
    code, out, err = run("private", "allow", "mine", "--key", p["key"])
    assert code == 2 and "dashboard" in (out + err)
    assert config.agent_entries(ws) == {}
    card = hp.handoffs(ws)[0]
    assert card["op"] == "private.allow" and card["target"] == f"mine:{p['key']}"
    assert card["parts"] == {"name": "mine", "command": "touch PWNED {prompt}"}
    item = hp.handoff_take(ws, card["id"])
    assert item and item["argv"][:3] == ["private", "allow", "mine"]


@pytest.mark.parametrize(
    "mk",
    [
        lambda ws, k: "",  # missing
        lambda ws, k: "hp1.e30.AAAA",  # garbage
        lambda ws, k: _proof(ws, "private.move", "move"),  # another op
        lambda ws, k: _proof(ws, "private.allow", "other:" + k),  # another name
        lambda ws, k: _proof(ws, "private.allow", "mine:" + "0" * 64),  # another key
        lambda ws, k: _proof(ws, "private.allow", f"mine:{k}", now=0),  # expired
    ],
)
def test_allow_bad_proofs_are_refused(ws, run, monkeypatch, mk):
    p = _pending(ws)
    code, *_ = _cli(run, monkeypatch, mk(ws, p["key"]), "private", "allow", "mine", "--key", p["key"])
    assert code == 2 and config.agent_entries(ws) == {}


def test_a_proof_is_single_use(ws, run, monkeypatch):
    p = _pending(ws)
    proof = _proof(ws, "private.allow", f"mine:{p['key']}")
    assert _cli(run, monkeypatch, proof, "private", "allow", "mine", "--key", p["key"])[0] == 0
    (ws / ".orch" / "config.toml").write_text(EVIL + "\n")  # same entry again, same proof
    config_entries = config.agent_entries(ws)
    assert "mine" in config_entries
    assert _cli(run, monkeypatch, proof, "private", "allow", "mine", "--key", p["key"])[0] == 2


# ------------------------------------------------------------------ private move


def test_move_agent_is_refused_with_the_ask_text(ws, run, monkeypatch):
    _tracked_repo(ws)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = run("private", "move")
    assert code == 2 and "orch ask" in out + err
    assert _git(ws, "ls-files", ".orch").stdout.strip()  # still tracked


def test_move_with_a_person_proof_succeeds(ws, run, monkeypatch):
    _tracked_repo(ws)
    code, out, err = _cli(run, monkeypatch, _proof(ws, "private.move", "move"), "private", "move")
    assert code == 0, out + err
    assert _git(ws, "ls-files", ".orch").stdout.strip() == ""
    assert (ws / ".orch" / "config.toml").is_file()  # the file stays


@pytest.mark.parametrize("proof", ["", "hp1.e30.AAAA"])
def test_move_missing_or_garbage_proof_is_refused(ws, run, monkeypatch, proof):
    _tracked_repo(ws)
    code, *_ = _cli(run, monkeypatch, proof, "private", "move")
    assert code == 2 and _git(ws, "ls-files", ".orch").stdout.strip()


def test_move_with_the_wrong_op_proof_is_refused(ws, run, monkeypatch):
    _tracked_repo(ws)
    code, *_ = _cli(run, monkeypatch, _proof(ws, "private.allow", "move"), "private", "move")
    assert code == 2 and _git(ws, "ls-files", ".orch").stdout.strip()


def test_move_without_a_proof_leaves_a_hand_off(ws, run):
    _tracked_repo(ws)
    code, out, err = run("private", "move")
    assert code == 2 and "dashboard" in (out + err)
    assert [h["op"] for h in hp.handoffs(ws)] == ["private.move"]
    assert _git(ws, "ls-files", ".orch").stdout.strip()


# ------------------------------------------------------------------ config agent add


def test_agent_add_agent_is_refused_with_the_ask_text(ws, run, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = run("config", "agent", "add", "sneaky", "--command", "touch X {prompt}")
    assert code == 2 and "orch ask" in out + err
    assert "sneaky" not in (config.read(ws).get("agents") or {})


def test_agent_add_with_a_person_proof_succeeds_and_approves_what_was_typed(ws, run, monkeypatch):
    proof = _proof(ws, "config.agent_add", "bar")
    code, out, err = _cli(
        run, monkeypatch, proof, "config", "agent", "add", "bar", "--command", "bar {prompt}"
    )
    assert code == 0, out + err
    assert config.agent_entries(ws)["bar"]["command"] == "bar {prompt}"


@pytest.mark.parametrize(
    "mk", [lambda ws: "", lambda ws: "hp1.e30.AAAA", lambda ws: _proof(ws, "config.agent_add", "other")]
)
def test_agent_add_bad_proofs_are_refused(ws, run, monkeypatch, mk):
    code, *_ = _cli(run, monkeypatch, mk(ws), "config", "agent", "add", "bar", "--command", "bar {prompt}")
    assert code == 2 and "bar" not in (config.read(ws).get("agents") or {})


def test_agent_add_without_a_proof_leaves_a_hand_off_with_the_command(ws, run):
    code, out, err = run("config", "agent", "add", "bar", "--command", "bar {prompt}")
    assert code == 2 and "dashboard" in (out + err)
    card = hp.handoffs(ws)[0]
    assert card["op"] == "config.agent_add" and card["target"] == "bar"
    assert card["parts"] == {"name": "bar", "command": "bar {prompt}"}
    assert "bar" not in (config.read(ws).get("agents") or {})

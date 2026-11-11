"""Slice 2.11: Insights settings (`orch config get|set insights.*`, `orch record settings`) and the human-only
`orch record delete-detail` (human-proof.md `insights.settings`, `record.delete_detail`, invariant H1)."""

import io
import json
import os
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from orch import cli_record, config, hider, pageproof
from orch import humanproof as hp
from orch.errors import Refused
from orch.record import RecordTampered, RecordWriter, record_dir

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
RUN_A, RUN_B, RUN_C = "r_8k2m01", "r_9z8y77", "r_7c7c7c"


@pytest.fixture
def ws(proj, monkeypatch):
    """A TEST workspace under <fake home>/.orch-test with its test home (as in test_human_proof_ops)."""
    from orch import addons

    base = addons.real_home() / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.chdir(root)
    _connect(root)  # share_counts on needs a relay connection (not_connected refuses it, see below)
    return root


def _connect(root, policy=None):
    """A relay connection (`.orch/secrets/relay.json`) and, if given, the last relay policy."""
    sec = root / ".orch" / "secrets"
    sec.mkdir(parents=True, exist_ok=True)
    conn = {"url": "https://r.example", "workspace": "w_1", "token": "orn_x"}
    (sec / "relay.json").write_text(json.dumps(conn))
    if policy is not None:
        (sec / "policy.json").write_text(json.dumps({"usage_counts": policy}))


def _disconnect(root):
    (root / ".orch" / "secrets" / "relay.json").unlink()


def _proof(ws, op, target, by="human:pat", **kw):
    return hp.mint(hp.human_key(ws), hp.new_payload(op, target, by, **kw))


def _sp(ws, key, value, **kw):
    """An `insights.settings` proof: VALUE-BOUND, target `key=value` (2.11 addendum)."""
    return _proof(ws, "insights.settings", f"{key}={value}", **kw)


def _used(ws) -> int:
    """How many proofs were spent (the nonce store)."""
    store = hp.key_dir(ws) / "proofs-used.json"
    return len(json.loads(store.read_text())) if store.is_file() else 0


def _cli(run, monkeypatch, proof, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO((proof + "\n") if proof else ""))
    return run(*argv, "--proof-stdin")


def _answer(out):
    return json.loads(out.strip().splitlines()[-1])


def _record(ws, key):
    path, wkey = hp._settings_path(ws)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    return (data["workspaces"].get(wkey) or {}).get(key)


def _granted(ws, key) -> bool:
    """A person's grant is in the record (a tombstone or the default is no grant)."""
    rec = _record(ws, key)
    return bool(rec) and str(rec.get("by")).startswith("human:")


def _get(run, key):
    code, out, err = run("config", "get", key, "--json")
    assert code == 0, out + err
    return json.loads(out)[key]


# ------------------------------------------------------------------ read


def test_get_defaults_and_aliases(ws, run):
    assert _get(run, "insights.share_counts") is True  # owner default (I5) while no record ever existed
    assert _get(run, "insights.share_names") is False
    assert _get(run, "insights.keep_days") == 90
    assert _get(run, "insights.max_mb") == 2048
    assert _get(run, "record.keep_days") == 90
    assert _get(run, "record.max_mb") == 2048
    code, out, _ = run("config", "get", "--json")
    listing = json.loads(out)
    assert {k: listing[k] for k in config.INSIGHTS_KEYS} == {
        "insights.share_counts": True,
        "insights.share_names": False,
        "insights.keep_days": 90,
        "insights.max_mb": 2048,
    }


def test_file_value_true_without_record_reads_false(ws, run):
    config.set_key(ws, "insights", "share_names", True)  # what an agent can do: edit the file
    assert _get(run, "insights.share_names") is False
    assert config.insights_share_names(ws) is False


def test_file_retention_alone_never_widens(ws, run):
    config.set_key(ws, "record", "keep_days", 365)
    config.set_key(ws, "record", "max_mb", 4096)
    assert _get(run, "insights.keep_days") == 90 and config.record_keep_days(ws) == 90
    assert _get(run, "insights.max_mb") == 2048 and config.record_max_mb(ws) == 2048


def test_share_counts_off_is_a_tombstone_the_file_cannot_undo(ws, run):
    code, out, err = run("config", "set", "insights.share_counts", "off", "--by", "agent:x", "--json")
    assert code == 0, out + err
    assert json.loads(out) == {"insights.share_counts": False, "changed": True, "widened": False}
    assert _record(ws, "insights.share_counts")["value"] is False
    assert _record(ws, "insights.share_counts")["by"] == "reset"  # no person is named for a lowering
    config.set_key(ws, "insights", "share_counts", True)  # the file edited back to on
    assert _get(run, "insights.share_counts") is False


@pytest.mark.parametrize("key,start", [("insights.share_names", None), ("insights.share_counts", "off")])
def test_share_switch_turned_off_from_the_file_stays_off(ws, run, monkeypatch, key, start):
    """MED-2: a person's grant, then the person turns it off FROM THE FILE (usage-counts.md: allowed): the
    read writes the False tombstone (`by: file`), so an agent editing the file back to on gets nothing."""
    table, name = config.INSIGHTS_KEYS[key]
    _start(run, key, start)
    assert _cli(run, monkeypatch, _sp(ws, key, "on"), "config", "set", key, "on", "--json")[0] == 0
    assert _record(ws, key)["value"] is True and _get(run, key) is True
    config.set_key(ws, table, name, False)  # the person, in config.toml
    assert config.insights_value(ws, key) is False
    assert _record(ws, key)["value"] is False and _record(ws, key)["by"] == "file"
    config.set_key(ws, table, name, True)  # an agent, in config.toml
    assert config.insights_value(ws, key) is False and _get(run, key) is False
    assert _record(ws, key)["value"] is False


def test_file_tombstone_is_decided_with_the_file_read_again_under_the_lock(ws, run, monkeypatch):
    """A reader that saw the old off file never writes its tombstone over a person's grant made in between
    (the grant writes record and file under keys.lock; the reader reads both again there)."""
    key = "insights.share_names"
    proof = _sp(ws, key, "on")
    assert _cli(run, monkeypatch, proof, "config", "set", key, "on", "--json")[0] == 0
    stale = False  # what the reader saw before the person's grant
    assert hp.effective(ws, key, stale, lambda: config.file_value(ws, "insights", "share_names")) is True
    assert _record(ws, key)["value"] is True and _record(ws, key)["by"] == "human:pat"
    assert config.insights_share_names(ws) is True


@pytest.mark.parametrize("key,start", [("insights.share_names", None), ("insights.share_counts", "off")])
@pytest.mark.parametrize(
    "bad",
    ["invalid toml [", '[insights]\nshare_names = "no"\nshare_counts = 0\n', "insights = 4\n"],
    ids=["not_toml", "not_a_bool", "not_a_table"],
)
def test_unreadable_or_invalid_config_is_off_but_never_a_tombstone(ws, run, monkeypatch, key, start, bad):
    """N6: a config.toml that cannot be read (mid-write, not valid TOML) or a value that is not true / false
    reads off and writes nothing: only a PARSED false is the person's off, so the grant counts again once the
    file is fixed."""
    _start(run, key, start)
    assert _cli(run, monkeypatch, _sp(ws, key, "on"), "config", "set", key, "on", "--json")[0] == 0
    good = config.path(ws).read_text()
    config.path(ws).write_text(bad)
    assert config.insights_value(ws, key) is False
    assert _record(ws, key)["value"] is True and _record(ws, key)["by"] == "human:pat"
    config.path(ws).write_text(good)
    assert config.insights_value(ws, key) is True


def test_file_unreadable_when_read_again_under_the_lock_writes_no_tombstone(ws, run, monkeypatch):
    """N6: the reader saw a parsed false, but under keys.lock the file cannot be read (mid-write): off, and no
    tombstone over the person's grant."""
    key = "insights.share_names"
    assert _cli(run, monkeypatch, _sp(ws, key, "on"), "config", "set", key, "on", "--json")[0] == 0
    assert hp.effective(ws, key, False, lambda: None) is False
    assert _record(ws, key)["value"] is True and _record(ws, key)["by"] == "human:pat"
    assert hp.effective(ws, key, None) is False  # never a tombstone, also without file_now
    assert _record(ws, key)["by"] == "human:pat" and config.insights_share_names(ws) is True


def test_agents_may_finish_unreadable_config_is_off_without_a_tombstone(ws):
    """N6, the same rule for workflow.agents_may_finish: an unreadable config.toml is off (no error, no
    tombstone); a parsed false is the tombstone."""
    config.set_agents_may_finish(ws, True, "human:pat")
    assert config.agents_may_finish(ws) is True
    good = config.path(ws).read_text()
    config.path(ws).write_text("invalid toml [")
    assert config.agents_may_finish(ws) is False
    assert _record(ws, "workflow.agents_may_finish")["by"] == "human:pat"
    config.path(ws).write_text(good)
    assert config.agents_may_finish(ws) is True
    config.set_key(ws, "workflow", "agents_may_finish", False)  # a parsed false: the person's off
    assert config.agents_may_finish(ws) is False
    assert _record(ws, "workflow.agents_may_finish")["by"] == "file"


# ------------------------------------------------------------------ write: widening needs the person

WIDENING = [  # (key, from: a narrowing done first, or None, value, effective value after)
    ("insights.share_names", None, "on", True),
    ("insights.share_counts", "off", "on", True),  # on by the owner default: it widens only from off
    ("insights.keep_days", None, "365", 365),
    ("insights.max_mb", None, "4096", 4096),
]


def _start(run, key, start):
    if start is not None:
        assert run("config", "set", key, start, "--by", "agent:x", "--json")[0] == 0  # narrowing: open


@pytest.mark.parametrize("key,start,value,want", WIDENING)
def test_widening_with_a_proof(ws, run, monkeypatch, key, start, value, want):
    _start(run, key, start)
    code, out, err = _cli(run, monkeypatch, _sp(ws, key, value), "config", "set", key, value)
    assert code == 0, out + err
    assert "Saved:" in out
    assert _get(run, key) == want
    rec = _record(ws, key)
    assert rec["value"] == want and rec["by"] == "human:pat"


@pytest.mark.parametrize("key,start,value,want", WIDENING)
def test_widening_answer_and_same_value_noop(ws, run, monkeypatch, key, start, value, want):
    _start(run, key, start)
    code, out, err = _cli(run, monkeypatch, _sp(ws, key, value), "config", "set", key, value, "--json")
    assert code == 0 and json.loads(out) == {key: want, "changed": True, "widened": True}, out + err
    spent, rec = _used(ws), _record(ws, key)
    # the same value again: success, nothing written, no proof needed (none given) and none read (one given)
    code, out, err = run("config", "set", key, value, "--by", "agent:x", "--json")
    assert code == 0 and json.loads(out) == {key: want, "changed": False, "widened": False}, out + err
    unused = _sp(ws, key, value)
    code, out, _ = _cli(run, monkeypatch, unused, "config", "set", key, value, "--json")
    assert code == 0 and json.loads(out) == {key: want, "changed": False, "widened": False}
    code, out, _ = run("config", "set", key, value)
    assert code == 0 and "Already" in out
    assert _used(ws) == spent and _record(ws, key) == rec


def test_proof_stdin_is_read_once_before_the_lock(ws, run, monkeypatch):
    """L5: with --proof-stdin the line read before keys.lock is ALWAYS passed on, so stdin is never read again
    inside the lock (also when the read gave nothing)."""
    calls = []

    def read_once():
        calls.append(1)
        return None  # whatever the read gave, it is the only read

    monkeypatch.setattr(hp, "read_proof_line", read_once)
    code, out, _ = run("config", "set", "insights.share_names", "on", "--proof-stdin", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert len(calls) == 1
    assert not _granted(ws, "insights.share_names")


@pytest.mark.parametrize("key,start,value,want", WIDENING)
def test_agent_is_refused_before_anything_else(ws, run, monkeypatch, key, start, value, want):
    _start(run, key, start)
    before = config.path(ws).read_text() if config.path(ws).is_file() else None
    code, out, _ = run("config", "set", key, value, "--by", "agent:x", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    monkeypatch.setenv("CLAUDECODE", "1")  # an agent in the environment, even holding a valid proof
    proof = _sp(ws, key, value)
    code, out, _ = _cli(run, monkeypatch, proof, "config", "set", key, value, "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    # refused first: even a stale --if-current does not get past the agent check
    code, out, _ = _cli(run, monkeypatch, proof, "config", "set", key, value, "--if-current", "x", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    monkeypatch.delenv("CLAUDECODE")
    assert not _granted(ws, key)
    assert (config.path(ws).read_text() if config.path(ws).is_file() else None) == before
    # the proof was never read: the person can still use it
    assert _cli(run, monkeypatch, proof, "config", "set", key, value, "--json")[0] == 0


BAD_PROOFS = {
    "missing": lambda ws, key: "",
    "garbage": lambda ws, key: "hp1.e30.AAAA",
    "expired": lambda ws, key: _sp(ws, key, "on", now=int(time.time()) - 500),
    "key only (old target)": lambda ws, key: _proof(ws, "insights.settings", key),
    "another value": lambda ws, key: _sp(ws, key, "off"),
    "another key": lambda ws, key: _sp(ws, "insights.share_counts", "on"),
    "true not on": lambda ws, key: _sp(ws, key, "true"),
    "wrong op": lambda ws, key: _proof(ws, "focus.settings", f"{key}=on"),
}


@pytest.mark.parametrize("bad", sorted(BAD_PROOFS))
def test_widening_bad_proofs_refused(ws, run, monkeypatch, bad):
    key = "insights.share_names"
    code, out, _ = _cli(run, monkeypatch, BAD_PROOFS[bad](ws, key), "config", "set", key, "on", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert not _granted(ws, key) and _get(run, key) is False
    assert not (config.read(ws).get("insights") or {}).get("share_names")  # the file is untouched too


def test_proof_for_another_value_refused(ws, run, monkeypatch):
    """A proof minted for 365 can not set 4096 (or another key), and nothing changes."""
    key = "insights.max_mb"
    for proof in (_sp(ws, key, "1024"), _sp(ws, "insights.keep_days", "4096"), _sp(ws, key, "04096")):
        code, out, _ = _cli(run, monkeypatch, proof, "config", "set", key, "4096", "--json")
        assert code == 2 and _answer(out)["code"] == "needs_person"
    assert _get(run, key) == 2048 and _record(ws, key) is None and _used(ws) == 0
    proof = _sp(ws, "insights.keep_days", "365")  # a keep_days proof: refused for 4096, still good for 365
    assert _cli(run, monkeypatch, proof, "config", "set", key, "4096", "--json")[0] == 2
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.keep_days", "365", "--json")[0] == 0


def test_proof_reused_refused(ws, run, monkeypatch):
    key = "insights.keep_days"
    proof = _sp(ws, key, "365")
    assert _cli(run, monkeypatch, proof, "config", "set", key, "365", "--json")[0] == 0
    assert run("config", "set", key, "30", "--json")[0] == 0  # narrowed by anyone
    code, out, _ = _cli(run, monkeypatch, proof, "config", "set", key, "365", "--json")  # used before
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert _get(run, key) == 30


def test_if_current_mismatch_is_changed(ws, run, monkeypatch):
    """A UI that showed 90 while someone else already set 365: refused `changed`, nothing written, the proof
    not spent."""
    key = "insights.keep_days"
    assert _cli(run, monkeypatch, _sp(ws, key, "365"), "config", "set", key, "365", "--json")[0] == 0
    rec, spent, before = _record(ws, key), _used(ws), config.path(ws).read_text()
    for value in ("30", "365", "90"):  # narrowing, same and (from the stale view) widening alike
        proof = _sp(ws, key, value)
        argv = ("config", "set", key, value, "--if-current", "90", "--json")
        code, out, _ = _cli(run, monkeypatch, proof, *argv)
        assert code == 2 and _answer(out) == {
            "error": "This changed in the meantime: now 365",
            "code": "changed",
        }
    assert _record(ws, key) == rec and _used(ws) == spent and config.path(ws).read_text() == before
    code, out, _ = run("config", "set", key, "30", "--if-current", "365", "--json")  # the right view
    assert code == 0 and json.loads(out) == {key: 30, "changed": True, "widened": False}
    code, out, _ = run("config", "set", "insights.share_names", "off", "--if-current", "on", "--json")
    assert code == 2 and _answer(out)["code"] == "changed" and "now off" in _answer(out)["error"]
    code, out, _ = run("config", "set", "insights.share_names", "off", "--if-current", "off", "--json")
    assert code == 0 and json.loads(out)["changed"] is False


def test_if_current_only_for_insights(ws, run):
    code, out, err = run("config", "set", "workflow.copies", "off", "--if-current", "on")
    assert code == 2 and "--if-current" in out + err


def test_narrowing_needs_no_proof(ws, run, monkeypatch):
    proof = _sp(ws, "insights.share_names", "on")
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.share_names", "on", "--json")[0] == 0
    spent = _used(ws)
    for key, value, want in (
        ("insights.share_names", "off", False),
        ("insights.share_counts", "off", False),
        ("insights.keep_days", "30", 30),
        ("insights.max_mb", "512", 512),
    ):
        code, out, err = run("config", "set", key, value, "--by", "agent:x", "--json")
        assert code == 0 and json.loads(out) == {key: want, "changed": True, "widened": False}, out + err
        assert _record(ws, key)["value"] == want
    assert _used(ws) == spent


def test_race_two_widenings_at_once(ws, monkeypatch):
    """Two callers widen at the same moment, each with its own valid proof: the read-compare-write is one
    critical section, so exactly one proof is spent, the other finds the value already set (no-op) and no
    update is lost (a widening of another key at the same time survives in the file and the record)."""
    import threading

    hp.key_dir(ws)
    key = "insights.keep_days"
    proofs = [_sp(ws, key, "365"), _sp(ws, key, "365")]
    other = _sp(ws, "insights.max_mb", "4096")
    real = config.set_insights
    gate = threading.Barrier(3)

    def slow_set(*a, **kw):  # widen the window between the decision and the write
        time.sleep(0.05)
        return real(*a, **kw)

    monkeypatch.setattr(config, "set_insights", slow_set)
    results, errors = {}, []

    def go(name, setting, value, proof):
        try:
            gate.wait()
            results[name] = config.change_insights(
                ws,
                setting,
                value,
                person=lambda target: hp.verify_and_consume(ws, proof, "insights.settings", target),
                if_current=None,
            )
        except Exception as e:  # reported below
            errors.append(e)

    threads = [
        threading.Thread(target=go, args=("a", key, 365, proofs[0])),
        threading.Thread(target=go, args=("b", key, 365, proofs[1])),
        threading.Thread(target=go, args=("m", "insights.max_mb", 4096, other)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    first, second = sorted((results["a"], results["b"]), key=lambda r: not r["changed"])
    assert first == {key: 365, "changed": True, "widened": True}
    assert second == {key: 365, "changed": False, "widened": False}
    assert results["m"] == {"insights.max_mb": 4096, "changed": True, "widened": True}
    assert _used(ws) == 2  # one keep_days proof and the max_mb proof; the loser's proof stays unspent
    assert config.record_keep_days(ws) == 365 and config.record_max_mb(ws) == 4096
    assert config.read(ws)["record"] == {"keep_days": 365, "max_mb": 4096}  # no lost update in the file
    unspent = proofs[1] if results["a"]["changed"] else proofs[0]
    hp.record_set(ws, key, 30, "agent:x")
    config.set_key(ws, "record", "keep_days", 30)
    assert config.change_insights(
        ws, key, 365, person=lambda t: hp.verify_and_consume(ws, unspent, "insights.settings", t)
    )["changed"]


def test_race_concurrent_change_with_if_current(ws, monkeypatch):
    """Two UIs both showed 90: one narrows to 30, the other widens to 365 with a proof, both --if-current 90.
    Whoever comes second is refused `changed`; the final value is the first one's, never a mix."""
    import threading

    hp.key_dir(ws)
    key = "insights.keep_days"
    proof = _sp(ws, key, "365")
    gate = threading.Barrier(2)
    results, errors = {}, []

    def go(name, value):
        try:
            gate.wait()
            results[name] = config.change_insights(
                ws,
                key,
                value,
                person=lambda t: hp.verify_and_consume(ws, proof, "insights.settings", t),
                if_current="90",
            )
        except config.InsightsRefused as e:
            errors.append((name, e.code, str(e)))

    threads = [threading.Thread(target=go, args=(n, v)) for n, v in (("down", 30), ("up", 365))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 1 and len(errors) == 1
    (winner, res), (_, code, msg) = next(iter(results.items())), errors[0]
    assert code == "changed" and msg == f"This changed in the meantime: now {res[key]}"
    assert config.record_keep_days(ws) == res[key] == (30 if winner == "down" else 365)
    assert _used(ws) == (1 if winner == "up" else 0)


def test_a_change_waits_for_the_lock_held_elsewhere_and_sees_the_new_value(ws):
    """Another thread holds keys.lock and widens keep_days to 365 inside it: a concurrent narrowing with
    --if-current 90 and a concurrent widening with a proof both BLOCK until the lock is released, then decide
    on the NEW value (the stale one is refused `changed`, the widening is a no-op, its proof not spent)."""
    import threading

    d = hp.key_dir(ws)
    key = "insights.keep_days"
    proof = _sp(ws, key, "365")
    holding, release = threading.Event(), threading.Event()
    results, called = {}, []

    def holder():
        with hp._key_lock(d):
            holding.set()
            config.set_insights(ws, key, 365, "human:other")  # the change made under the held lock
            release.wait(10)

    def narrow():
        try:
            results["narrow"] = config.change_insights(ws, key, 30, if_current="90")
        except config.InsightsRefused as e:
            results["narrow"] = (e.code, str(e))

    def widen():
        def person(t):
            called.append(t)
            return hp.verify_and_consume(ws, proof, "insights.settings", t)

        results["widen"] = config.change_insights(ws, key, 365, person=person)

    h = threading.Thread(target=holder)
    h.start()
    assert holding.wait(10)
    waiters = [threading.Thread(target=narrow), threading.Thread(target=widen)]
    for t in waiters:
        t.start()
    time.sleep(0.4)
    assert all(t.is_alive() for t in waiters) and results == {} and called == []  # blocked on the lock
    release.set()
    h.join(10)
    for t in waiters:
        t.join(15)
    assert results["narrow"] == ("changed", "This changed in the meantime: now 365")
    assert results["widen"] == {key: 365, "changed": False, "widened": False}
    assert called == [] and _used(ws) == 0  # the proof was never read
    assert config.record_keep_days(ws) == 365 and _record(ws, key)["by"] == "human:other"


def test_widening_if_current_share_state_and_proof_run_in_one_critical_section(ws, monkeypatch):
    """The current-value read (the widening decision and the --if-current compare), the share state check and
    the proof check all run while change_insights holds keys.lock, and the lock is taken once."""
    d = hp.key_dir(ws)
    key = "insights.share_counts"
    assert config.change_insights(ws, key, False)["changed"]  # narrowing first (open)
    proof = _sp(ws, key, "on")
    seen = []
    real_value, real_blocked = config.insights_value, config.share_counts_blocked

    def value(root, setting):
        seen.append(("value", hp._lock_held(d)))
        return real_value(root, setting)

    def blocked(root):
        seen.append(("share_state", hp._lock_held(d)))
        return real_blocked(root)

    def person(t):
        seen.append(("proof", hp._lock_held(d)))
        return hp.verify_and_consume(ws, proof, "insights.settings", t)

    monkeypatch.setattr(config, "insights_value", value)
    monkeypatch.setattr(config, "share_counts_blocked", blocked)
    res = config.change_insights(ws, key, True, person=person, if_current="off")
    assert res == {key: True, "changed": True, "widened": True}
    assert [s for s, _ in seen][:3] == ["value", "share_state", "proof"]
    assert all(held for _, held in seen), seen
    assert not hp._lock_held(d) and _used(ws) == 1


# ------------------------------------------------------------------ share_counts: only where it is available


@pytest.mark.parametrize("state", ["not_connected", "off_by_admin"])
def test_share_counts_on_refused_when_sharing_is_not_available(ws, run, monkeypatch, state):
    assert run("config", "set", "insights.share_counts", "off", "--json")[0] == 0
    if state == "not_connected":
        _disconnect(ws)
    else:
        _connect(ws, policy="off")
    assert config.share_counts_state(ws) == state
    rec, before = _record(ws, "insights.share_counts"), config.path(ws).read_text()
    proof = _sp(ws, "insights.share_counts", "on")
    for extra in ((), ("--if-current", "off")):
        argv = ("config", "set", "insights.share_counts", "on", *extra, "--json")
        code, out, _ = _cli(run, monkeypatch, proof, *argv)
        ans = _answer(out)
        assert code == 2 and ans["code"] == "not_available", out
        assert ans["error"] == config.SHARE_BLOCKED_MSG[state] and "not available" in ans["error"]
    asked = []
    with pytest.raises(config.InsightsRefused) as e:
        config.change_insights(
            ws, "insights.share_counts", True, person=lambda t: asked.append(t) or "human:pat"
        )
    assert e.value.code == "not_available" and asked == []
    # nothing written, the proof not consumed
    assert _record(ws, "insights.share_counts") == rec and config.path(ws).read_text() == before
    assert _used(ws) == 0 and _get(run, "insights.share_counts") is False
    # off (narrowing / same value) is always allowed
    code, out, _ = run("config", "set", "insights.share_counts", "off", "--json")
    assert code == 0 and json.loads(out)["changed"] is False
    # once sharing is available the same, unspent proof works
    _connect(ws, policy="on")
    code, out, err = _cli(run, monkeypatch, proof, "config", "set", "insights.share_counts", "on", "--json")
    want = {"insights.share_counts": True, "changed": True, "widened": True}
    assert code == 0 and json.loads(out) == want, out + err
    assert _used(ws) == 1 and config.share_counts_state(ws) == "on"


def test_share_counts_off_is_allowed_whatever_the_share_state(ws, run):
    _connect(ws, policy="off")
    code, out, err = run("config", "set", "insights.share_counts", "off", "--by", "agent:x", "--json")
    assert code == 0 and json.loads(out)["changed"] is True, out + err
    _disconnect(ws)
    assert config.share_counts_state(ws) == "not_connected"
    assert _get(run, "insights.share_counts") is False


def test_share_counts_on_allowed_when_connected(ws, run, monkeypatch):
    assert config.share_counts_state(ws) == "on"  # connected, no admin policy kept: the owner default
    assert run("config", "set", "insights.share_counts", "off", "--json")[0] == 0
    assert config.share_counts_state(ws) == "off"
    _connect(ws, policy="on")
    proof = _sp(ws, "insights.share_counts", "on")
    code, out, err = _cli(run, monkeypatch, proof, "config", "set", "insights.share_counts", "on", "--json")
    assert code == 0 and json.loads(out)["changed"] is True, out + err
    assert _record(ws, "insights.share_counts")["by"] == "human:pat" and config.share_counts_state(ws) == "on"


def test_share_state_needs_a_full_relay_connection(ws):
    (ws / ".orch" / "secrets" / "relay.json").write_text(json.dumps({"url": "https://r.example"}))
    assert config.share_counts_state(ws) == "not_connected"
    (ws / ".orch" / "secrets" / "relay.json").write_text("not json")
    assert config.share_counts_state(ws) == "not_connected"
    _connect(ws, policy="off")
    assert config.share_counts_state(ws) == "off_by_admin"


def test_relay_refresh_keeps_the_admin_policy(ws):
    from orch import relay

    sec = ws / ".orch" / "secrets"
    relay._keep_policy(ws, {"usage_counts": "off", "live_session": "allowed"})
    assert json.loads((sec / "policy.json").read_text()) == {"usage_counts": "off"}
    assert config.share_counts_state(ws) == "off_by_admin"
    relay._keep_policy(ws, None)  # a snapshot without one keeps the last
    relay._keep_policy(ws, {"usage_counts": "maybe"})
    assert config.share_counts_state(ws) == "off_by_admin"
    relay._keep_policy(ws, {"usage_counts": "on"})
    assert config.share_counts_state(ws) == "on"


def test_widening_without_proof_by_a_person_flag_is_refused(ws, run):
    code, out, err = run("config", "set", "insights.keep_days", "365", "--by", "human:pat", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert "dashboard" in out + err
    assert _get(run, "insights.keep_days") == 90


def test_widening_forged_by_and_replay_refused(ws, run, monkeypatch):
    key = "insights.share_names"
    proof = _sp(ws, key, "on")
    code, out, _ = _cli(
        run, monkeypatch, proof, "config", "set", key, "on", "--by", "human:someone", "--json"
    )
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert not _granted(ws, key)
    proof = _sp(ws, key, "on")
    assert _cli(run, monkeypatch, proof, "config", "set", key, "on", "--json")[0] == 0
    assert _cli(run, monkeypatch, proof, "config", "set", key, "off", "--json")[0] == 0  # off: no proof read
    code, out, _ = _cli(run, monkeypatch, proof, "config", "set", key, "on", "--json")  # replayed
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert _get(run, key) is False


@pytest.mark.parametrize(
    "key,value", [("insights.keep_days", "60"), ("insights.max_mb", "3000"), ("insights.share_names", "yes")]
)
def test_invalid_value_lists_the_allowed_ones(ws, run, key, value):
    code, out, _ = run("config", "set", key, value, "--json")
    assert code == 2 and _answer(out)["code"] == "invalid"
    assert not _granted(ws, key)


# ------------------------------------------------------------------ narrowing and retention


def test_narrowing_is_open_and_the_lower_record_sticks(ws, run, monkeypatch):
    code, out, err = run("config", "set", "insights.keep_days", "30", "--by", "agent:x", "--json")
    assert code == 0 and json.loads(out) == {"insights.keep_days": 30, "changed": True, "widened": False}, (
        out + err
    )
    rec = _record(ws, "insights.keep_days")
    assert rec["value"] == 30 and rec["by"] == "reset"
    config.set_key(ws, "record", "keep_days", 365)  # the file edited back up
    assert _get(run, "insights.keep_days") == 30
    code, out, _ = run("config", "set", "insights.keep_days", "90", "--by", "agent:x", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"  # up again (from 30) is a widening
    proof = _sp(ws, "insights.keep_days", "90")
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.keep_days", "90", "--json")[0] == 0
    assert _get(run, "insights.keep_days") == 90


def test_retention_uses_the_lower_of_file_and_record(ws, run, monkeypatch):
    proof = _sp(ws, "insights.max_mb", "4096")
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.max_mb", "4096", "--json")[0] == 0
    assert config.record_max_mb(ws) == 4096
    config.set_key(ws, "record", "max_mb", 1024)  # a person lowers it in the file
    assert config.record_max_mb(ws) == 1024
    assert _record(ws, "insights.max_mb")["value"] == 1024  # the lowering is recorded at once
    config.set_key(ws, "record", "max_mb", 4096)  # and the file alone cannot raise it again
    assert config.record_max_mb(ws) == 1024


def test_record_set_refuses_an_agent_raise_and_bad_values(ws):
    hp.key_dir(ws)
    with pytest.raises(hp.Refused):
        hp.record_set(ws, "insights.keep_days", 365, "agent:x")
    with pytest.raises(hp.Refused):
        hp.record_set(ws, "insights.keep_days", 7, "human:pat")  # not an allowed value
    with pytest.raises(hp.Refused):
        hp.record_set(ws, "insights.max_mb", True, "human:pat")
    hp.record_set(ws, "insights.keep_days", 30, "agent:x")  # lowering: anyone
    rec = _record(ws, "insights.keep_days")
    assert (rec["value"], rec["by"]) == (30, "reset")
    with pytest.raises(hp.Refused):
        hp.record_set(ws, "insights.keep_days", 90, "agent:x")  # back up from 30: a person only
    hp.record_set(ws, "insights.keep_days", 90, "human:pat")
    assert _record(ws, "insights.keep_days")["value"] == 90


@pytest.mark.parametrize("planted", [99999, True, "*", [1], -5, 0])
def test_forged_settings_record_value_counts_as_none(ws, run, planted):
    hp.key_dir(ws)
    path, wkey = hp._settings_path(ws)
    rec = {"value": planted, "by": "human:pat", "at": "2026-11-16T09:00:00Z"}
    body = {"schema": "orch.human-settings/1", "workspaces": {wkey: {"insights.keep_days": rec}}}
    hp._write_private(path, json.dumps(body))
    config.set_key(ws, "record", "keep_days", 365)
    assert config.record_keep_days(ws) == 90  # the default record, never the planted value


def test_loose_settings_record_is_reset_and_reads_safe(ws, run, monkeypatch):
    proof = _sp(ws, "insights.share_names", "on")
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.share_names", "on", "--json")[0] == 0
    hp.record_set(ws, "insights.keep_days", 30, "agent:x")
    path, _ = hp._settings_path(ws)
    os.chmod(path, 0o644)  # a loose (possibly forged) record is never trusted
    assert config.insights_share_names(ws) is False
    assert config.record_keep_days(ws) == 30  # a reset only lowers: the lower retention record is kept


def test_settings_record_stays_schema_valid(ws, run, monkeypatch):
    proof = _sp(ws, "insights.keep_days", "365")
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.keep_days", "365", "--json")[0] == 0
    run("config", "set", "insights.max_mb", "512", "--json")
    schema = json.loads((CONTRACTS / "human-proof.schema.json").read_text())
    path, _ = hp._settings_path(ws)
    Draft202012Validator({"$ref": "#/$defs/settings_record", "$defs": schema["$defs"]}).validate(
        json.loads(path.read_text())
    )


def test_insights_is_a_page_server(ws, monkeypatch):
    from orch import addons

    assert "insights" in hp.LAUNCH_SERVERS and "insights" in pageproof.SERVERS
    pageproof.PageSession(ws, "insights")  # accepted as a page server
    monkeypatch.setattr(addons, "SHIPPED_ADDONS", (*addons.SHIPPED_ADDONS, "insights"))
    token = hp.write_launch_token(ws, "insights")  # once orch ships the add-on (its manifest)
    assert token and hp.consume_launch_token(ws, "insights", token)


def test_insights_launch_token_refused_without_a_shipped_manifest(ws):
    """Insights in LAUNCH_SERVERS is not enough: this orch does not ship workspace-addons/insights yet, so no
    launch token is written for it and none is accepted (focus and dashboard keep theirs)."""
    from orch import addons

    assert "insights" not in addons.SHIPPED_ADDONS
    assert not hp.launch_server_ok("insights")
    with pytest.raises(hp.Refused):
        hp.write_launch_token(ws, "insights")
    assert not (hp.key_dir(ws) / "launch-insights.token").exists()
    hp._write_private(hp.key_dir(ws) / "launch-insights.token", f"{'a' * 32}\n{int(time.time()) + 30}\n")
    assert hp.consume_launch_token(ws, "insights", "a" * 32) is False  # a planted token file does not count
    assert hp.launch_url(ws, "insights", "http://127.0.0.1:1/") == "http://127.0.0.1:1/"
    for server in ("focus", "dashboard"):
        token = hp.write_launch_token(ws, server)
        assert token and hp.consume_launch_token(ws, server, token)


def _ops():
    schema = json.loads((CONTRACTS / "human-proof.schema.json").read_text())
    return schema["$defs"]["op"]["enum"]


def test_insights_server_mints_only_its_two_ops(ws):
    page = pageproof.PageSession(ws, "insights")
    assert page.key is not None
    assert pageproof.SERVER_OPS["insights"] == {"insights.settings", "record.delete_detail"}
    for op in _ops():
        if op in ("insights.settings", "record.delete_detail"):
            assert page.mint(op, "t_abcdef").startswith("hp1.")
            continue
        with pytest.raises(hp.Refused):
            page.mint(op, "t_abcdef")
    for op in ("run.type", "secret.add", "update", "addon.add_local"):
        with pytest.raises(hp.Refused):
            page.mint(op, "x")
    for server in ("focus", "dashboard"):  # every other server keeps its behaviour
        other = pageproof.PageSession(ws, server)
        assert other.mint("run.type", "t_abcdef").startswith("hp1.")
        assert other.mint("secret.add", "deploy-key").startswith("hp1.")


def _payload(proof):
    import base64

    part = proof.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


@pytest.mark.parametrize(
    "key,value,text",
    [
        ("insights.keep_days", 365, "365"),
        ("insights.max_mb", 4096, "4096"),
        ("insights.share_names", True, "on"),
    ],
)
def test_insights_mint_target_is_the_check_target(ws, run, monkeypatch, key, value, text):
    """The page mints with config.insights_target, the ONE canonical form the core checks: the proof is
    accepted by `orch config set` for that value (also typed as 0365) and refused for another one."""
    page = pageproof.PageSession(ws, "insights")
    proof = page.mint_insights_setting(key, value)
    assert _payload(proof)["target"] == config.insights_target(key, value) == f"{key}={text}"
    seen = []
    real = hp.verify_and_consume

    def spy(root, p, op, target, by_flag=None):
        seen.append((op, target))
        return real(root, p, op, target, by_flag)

    monkeypatch.setattr(hp, "verify_and_consume", spy)
    typed = "0" + text if type(value) is int else text
    code, out, err = _cli(run, monkeypatch, proof, "config", "set", key, typed, "--json")
    assert code == 0, out + err
    assert seen == [("insights.settings", _payload(proof)["target"])]
    with pytest.raises(hp.Refused):
        page.mint_insights_setting("record.keep_days", 365)


# ------------------------------------------------------------------ record settings / delete-detail


@pytest.fixture
def rec(ws, run):
    """Two tickets: A with two runs that have detail, B with one run that has detail."""
    tids = []
    for title in ("A", "B"):
        code, out, _ = run("ticket", "new", title, "--json", "--by", "agent:x")
        tids.append(json.loads(out)["id"])
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    for run_id, tid in ((RUN_A, tids[0]), (RUN_B, tids[0]), (RUN_C, tids[1])):
        for n in (1, 2):
            w.append(
                dict(
                    example, run=run_id, ticket=tid, id=f"toolu_{run_id[2:]}{n}", at=f"2026-11-16T09:1{n}:00Z"
                ),
                detail={"input": {"n": n}, "output": "x" * 2000},
            )
    return tids


def _detail(ws, run_id):
    return record_dir(ws) / "detail" / run_id


def _lines(ws):
    return {p.name: p.read_bytes() for p in (record_dir(ws) / "runs").iterdir()}


def _changes(ws):
    folder = record_dir(ws) / "alerts"
    if not folder.is_dir():
        return []
    out = [json.loads(x) for p in folder.iterdir() for x in p.read_text().splitlines()]
    return [x for x in out if x.get("schema") == "orch.record-change/1"]


def test_record_settings(ws, rec, run, monkeypatch):
    code, out, err = run("record", "settings", "--json")
    assert code == 0, out + err
    got = json.loads(out)
    assert got == {
        "keep_days": 90,
        "max_mb": 2048,
        "share_counts": True,
        "share_names": False,
        "record_mb": 1,
        "detail_mb": 1,
        "runs": 3,
    }
    proof = _sp(ws, "insights.share_names", "on")
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.share_names", "on", "--json")[0] == 0
    run("config", "set", "insights.keep_days", "30", "--json")
    got = json.loads(run("record", "settings", "--json")[1])
    assert (got["share_names"], got["keep_days"]) == (True, 30)


def test_record_settings_empty_record(ws, run):
    got = json.loads(run("record", "settings", "--json")[1])
    assert (got["record_mb"], got["detail_mb"], got["runs"]) == (0, 0, 0)


def test_record_settings_unreadable_record_gives_the_marker(ws, rec, run, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    runs = record_dir(ws) / "runs"
    runs.rename(tmp_path / "moved")
    runs.symlink_to(outside, target_is_directory=True)
    code, out, _ = run("record", "settings", "--json")
    got = json.loads(out)
    assert code == 0 and got["status"] == "tampered" and got["reason"] == "link"
    assert got["record_mb"] is None and got["keep_days"] == 90
    assert got["message"] == str(RecordTampered("link"))


def test_lowering_retention_deletes_nothing_now(ws, rec, run):
    before = sorted(p for p in record_dir(ws).rglob("*") if p.is_file() and "alerts" not in p.parts)
    assert run("config", "set", "insights.keep_days", "30", "--json")[0] == 0
    assert run("config", "set", "insights.max_mb", "512", "--json")[0] == 0
    after = sorted(p for p in record_dir(ws).rglob("*") if p.is_file() and "alerts" not in p.parts)
    assert after == before


def test_delete_detail_with_a_proof(ws, rec, run, monkeypatch):
    a, b = rec
    lines = _lines(ws)
    counts_before = json.loads(run("record", "counts", "--json")[1])
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert json.loads(out) == {"deleted": 2, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert not _detail(ws, RUN_A).exists() and not _detail(ws, RUN_B).exists()
    assert _detail(ws, RUN_C).is_dir()  # the other ticket keeps its detail
    assert _lines(ws) == lines  # every line stays as it was
    counts_after = json.loads(run("record", "counts", "--json")[1])
    for k in ("generated_at", "inventory"):
        counts_before.pop(k), counts_after.pop(k)
    assert counts_after == counts_before
    (change,) = _changes(ws)
    assert (change["change"], change["by"], change["ticket"], change["deleted"]) == (
        "record.delete_detail",
        "human:pat",
        a,
        2,
    )
    schema = json.loads((CONTRACTS / "activity.schema.json").read_text())
    Draft202012Validator(
        {"$ref": "#/$defs/record_change", "$defs": schema["$defs"]}, format_checker=FormatChecker()
    ).validate(change)
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", f"toolu_{RUN_A[2:]}1", "--json")
    assert code == 2 and _answer(out)["code"] == "not_found"  # details not available
    again = _proof(ws, "record.delete_detail", a)  # nothing left: 0, and a new audit line
    code, out, _ = _cli(run, monkeypatch, again, "record", "delete-detail", a, "--json")
    assert code == 0
    assert json.loads(out) == {"deleted": 0, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert len(_changes(ws)) == 2


BAD_DELETE = {
    "missing": lambda ws, a, b: "",
    "garbage": lambda ws, a, b: "hp1.e30.AAAA",
    "expired": lambda ws, a, b: _proof(ws, "record.delete_detail", a, now=int(time.time()) - 500),
    "wrong target": lambda ws, a, b: _proof(ws, "record.delete_detail", b),
    "wrong op": lambda ws, a, b: _proof(ws, "insights.settings", a),
}


def _untouched(ws):
    assert _detail(ws, RUN_A).is_dir() and _detail(ws, RUN_B).is_dir() and _detail(ws, RUN_C).is_dir()
    assert _changes(ws) == []


@pytest.mark.parametrize("bad", sorted(BAD_DELETE))
def test_delete_detail_bad_proofs(ws, rec, run, monkeypatch, bad):
    a, b = rec
    code, out, _ = _cli(run, monkeypatch, BAD_DELETE[bad](ws, a, b), "record", "delete-detail", a, "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    _untouched(ws)


def test_delete_detail_without_proof_and_forged_by(ws, rec, run, monkeypatch):
    a, _ = rec
    code, out, err = run("record", "delete-detail", a, "--by", "human:pat", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person" and "dashboard" in out + err
    proof = _proof(ws, "record.delete_detail", a)
    code, out, _ = _cli(
        run, monkeypatch, proof, "record", "delete-detail", a, "--by", "human:other", "--json"
    )
    assert code == 2 and _answer(out)["code"] == "needs_person"
    _untouched(ws)


def test_delete_detail_agent_refused_first(ws, rec, run, monkeypatch):
    a, _ = rec
    code, out, _ = run("record", "delete-detail", "t_nothere1", "--by", "agent:x", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"  # before the ticket is even looked at
    proof = _proof(ws, "record.delete_detail", a)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, _ = _cli(run, monkeypatch, proof, "record", "delete-detail", a, "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    monkeypatch.delenv("CLAUDECODE")
    _untouched(ws)
    assert _cli(run, monkeypatch, proof, "record", "delete-detail", a, "--json")[0] == 0  # proof not spent


def test_delete_detail_replay_refused(ws, rec, run, monkeypatch):
    a, _ = rec
    proof = _proof(ws, "record.delete_detail", a)
    assert _cli(run, monkeypatch, proof, "record", "delete-detail", a, "--json")[0] == 0
    code, out, _ = _cli(run, monkeypatch, proof, "record", "delete-detail", a, "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert len(_changes(ws)) == 1


@pytest.mark.parametrize("ticket", ["t_nothere1", "../x", "T_ABCDEF"])
def test_delete_detail_unknown_ticket(ws, rec, run, monkeypatch, ticket):
    code, out, _ = _cli(
        run,
        monkeypatch,
        _proof(ws, "record.delete_detail", "t_nothere1"),
        "record",
        "delete-detail",
        ticket,
        "--json",
    )
    assert code == 2 and _answer(out)["code"] == "not_found"
    _untouched(ws)


@pytest.mark.parametrize("which", [RUN_B, RUN_C])
def test_delete_detail_skips_an_unreadable_run_and_says_so(ws, rec, run, monkeypatch, tmp_path, which):
    """M4: a run that cannot be read is no veto: it is skipped (its detail stays, also this ticket's own
    files in it), counted in `unreadable`, and the CLI says so plainly; the readable runs lose this ticket's
    detail."""
    a, _ = rec
    run_file = record_dir(ws) / "runs" / f"{which}.jsonl"
    outside = tmp_path / "outside.jsonl"
    run_file.rename(outside)
    run_file.symlink_to(outside)  # one run of the record was changed outside orch (planted by an agent)
    before = sorted(p.name for p in _detail(ws, which).iterdir())
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    gone = 1 if which == RUN_B else 2  # RUN_B is A's: only RUN_A goes; RUN_C is B's: RUN_A and RUN_B go
    assert json.loads(out) == {"deleted": gone, "ticket": a, "kept": 0, "unreadable": 1, "skipped": 0}
    assert "1 run could not be read; its detail was not deleted." in err
    assert cli_record.delete_unreadable_text(3) == "3 runs could not be read; their detail was not deleted."
    assert not _detail(ws, RUN_A).exists()
    assert sorted(p.name for p in _detail(ws, which).iterdir()) == before  # the unreadable run keeps it all
    assert [c["deleted"] for c in _changes(ws)] == [gone]


def test_delete_detail_never_removes_a_folder_a_file_was_written_to_in_between(ws, rec, run, monkeypatch):
    """M3: after this ticket's files went, another ticket's detail written into the same run folder (before
    the folder is removed) stays: the folder goes only by rmdir, which fails when it is not empty. The files
    of a run are deleted under that run's lock (the writer stores detail under it)."""
    from orch import record

    a, _ = rec
    real, seen = record._rmdir_empty, []

    def write_in_between(ws_, rel):
        run_id = rel[-1]
        seen.append((run_id, (record_dir(ws) / "runs" / f"{run_id}.lock").exists()))
        late = record_dir(ws) / "detail" / run_id / ("f" * 32 + ".json")
        late.write_text("{}")  # another ticket's writer was quicker than the folder removal
        return real(ws_, rel)

    monkeypatch.setattr(record, "_rmdir_empty", write_in_between)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert sorted(seen) == [(RUN_A, True), (RUN_B, True)]  # under each run's lock
    for run_id in (RUN_A, RUN_B):
        assert [p.name for p in _detail(ws, run_id).iterdir()] == ["f" * 32 + ".json"]


def test_rmdir_empty_removes_only_an_empty_folder(ws, rec):
    from orch import record

    assert record._rmdir_empty(ws, ("detail", RUN_A)) is False  # not empty: stays
    assert _detail(ws, RUN_A).is_dir()
    (record_dir(ws) / "detail" / "r_emptyy1").mkdir()
    assert record._rmdir_empty(ws, ("detail", "r_emptyy1")) is True
    assert not (record_dir(ws) / "detail" / "r_emptyy1").exists()
    assert record._rmdir_empty(ws, ("detail", "r_emptyy1")) is False  # already gone


def test_delete_detail_deletes_this_tickets_orphan_files(ws, rec, run, monkeypatch):
    """M4: a detail file of this ticket that no line points at (the detail is written before its line: a crash
    in between) goes too and counts in `deleted`; another ticket's orphan and a file whose stored fields do
    not give its own name stay."""
    from orch import record

    a, b = rec
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())

    def orphan(run_id, tid, eid, *, name=None):
        payload = {
            "v": 1,
            "id": eid,
            "run": run_id,
            "kind": example["kind"],
            "ticket": tid,
            "input": {},
            "output": "orphan",
            "truncated": False,
            "hidden": 0,
        }
        name = name or record.detail_name(run_id, example["kind"], eid, tid)
        folder = _detail(ws, run_id)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / f"{name}.json"
        path.write_text(json.dumps(payload))
        os.chmod(path, 0o600)
        return path

    RUN_D = "r_4d4d4d"
    mine_in_c = orphan(RUN_C, a, "toolu_lost1")  # A's orphan in B's run
    mine_alone = orphan(RUN_D, a, "toolu_lost2")  # A's orphan in a run with no run file at all
    theirs = orphan(RUN_C, b, "toolu_lost3")  # B's orphan: stays
    renamed = orphan(RUN_C, a, "toolu_lost4", name="0" * 32)  # stored fields do not give this name: stays
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    # A, B, C, D
    assert json.loads(out) == {"deleted": 4, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert not mine_in_c.exists() and not mine_alone.exists() and not _detail(ws, RUN_D).exists()
    assert theirs.exists() and renamed.exists()
    assert len(list(_detail(ws, RUN_C).iterdir())) == 4  # B's two own files, B's orphan, the renamed one
    assert [c["deleted"] for c in _changes(ws)] == [4]


def test_delete_detail_needs_json(ws, rec, run):
    code, out, err = run("record", "delete-detail", rec[0])
    assert code == 2 and "Use --json" in err
    assert cli_record.SUBCOMMANDS == ("tail", "query", "counts", "settings", "delete-detail", "hook")


def test_proof_request_parts_for_the_hand_off_cards(monkeypatch):
    """Hand-off card parts: {setting, value} for insights.settings, {title} for record.delete_detail."""
    import inspect

    from orch import cli_config, cli_record

    cfg = inspect.getsource(cli_config)
    rec = inspect.getsource(cli_record)
    assert 'parts={"setting": key, "value": config.insights_text(value)}' in cfg
    assert 'parts={"title": _ticket_title(root, tid)}' in rec


def test_insights_person_is_page_only_and_the_card_shows_the_bound_value(ws, run, monkeypatch):
    """The person is asked with no_handoff (a terminal hand-off would wait for a click holding keys.lock) and
    the card's value is the canonical one the target binds (`0365` shows as 365)."""
    from orch import cli_config

    asked = []

    def fake_person(args, root, op, target, **kw):
        asked.append((op, target, kw))
        raise hp.Refused(hp.HANDOFF)

    monkeypatch.setattr(cli_config, "_person", fake_person)
    code, out, _ = run("config", "set", "insights.keep_days", "0365", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert asked == [
        (
            "insights.settings",
            "insights.keep_days=365",
            {"no_handoff": hp.HANDOFF, "parts": {"setting": "insights.keep_days", "value": "365"}},
        )
    ]


def test_widening_without_a_proof_queues_no_hand_off(ws, run, monkeypatch):
    def no_handoff(*a, **k):
        raise AssertionError("a hand-off was queued while keys.lock is held")

    monkeypatch.setattr(hp, "request_handoff", no_handoff)
    for key, value in (("insights.share_names", "on"), ("insights.keep_days", "365")):
        code, out, err = run("config", "set", key, value, "--json")
        assert code == 2 and _answer(out) == {"error": hp.HANDOFF, "code": "needs_person"}, out + err
        assert not _granted(ws, key)


# ------------------------------------------------------------------ settle vectors (2.11 review)


def test_settle_proof_for_share_names_does_not_set_share_counts(ws, run, monkeypatch):
    assert run("config", "set", "insights.share_counts", "off", "--json")[0] == 0
    proof = _sp(ws, "insights.share_names", "on")
    code, out, _ = _cli(run, monkeypatch, proof, "config", "set", "insights.share_counts", "on", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert _get(run, "insights.share_counts") is False and _used(ws) == 0
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.share_names", "on", "--json")[0] == 0


def test_settle_proof_for_365_does_not_set_90(ws, run, monkeypatch):
    key = "insights.keep_days"
    assert run("config", "set", key, "30", "--json")[0] == 0  # 90 is now a widening
    proof = _sp(ws, key, "365")
    code, out, _ = _cli(run, monkeypatch, proof, "config", "set", key, "90", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert _get(run, key) == 30 and _used(ws) == 0


def test_settle_leading_zeros(ws, run, monkeypatch):
    """`0365` is the number 365: the target is built from the parsed value, so a proof minted for the text
    `0365` never matches and the one for `365` does."""
    key = "insights.keep_days"
    code, out, _ = _cli(run, monkeypatch, _sp(ws, key, "0365"), "config", "set", key, "0365", "--json")
    assert code == 2 and _answer(out)["code"] == "needs_person"
    assert _get(run, key) == 90
    code, out, err = _cli(run, monkeypatch, _sp(ws, key, "365"), "config", "set", key, "0365", "--json")
    assert code == 0 and json.loads(out) == {key: 365, "changed": True, "widened": True}, out + err
    for bad in ("٣٦٥", "+365", "-30", "365.0", "9" * 40):  # unicode digits, signs, huge: invalid
        code, out, _ = run("config", "set", key, bad, "--json")
        assert code == 2 and _answer(out)["code"] == "invalid"


def test_settle_bool_in_a_numeric_file_setting_is_the_default(ws, run):
    """`keep_days = true` in the file is not 1: the default, no `True` record, and the answer is a number."""
    config.set_key(ws, "record", "keep_days", True)
    config.set_key(ws, "record", "max_mb", False)
    assert config.file_value(ws, "record", "keep_days") == 90
    got = _get(run, "insights.keep_days")
    assert got == 90 and type(got) is int
    assert type(config.record_max_mb(ws)) is int and config.record_max_mb(ws) == 2048
    assert _record(ws, "insights.keep_days") is None and _record(ws, "insights.max_mb") is None
    settings = json.loads(run("record", "settings", "--json")[1])
    assert type(settings["keep_days"]) is int and type(settings["max_mb"]) is int


# (file key, file value, effective value: snapped down, floor 30 / 512, never above the record)
FILE_RETENTION = [
    ("keep_days", True, 90),  # a bool is not a number: the default
    ("keep_days", 1, 30),  # the floor: a file edit cannot make pruning delete nearly everything
    ("keep_days", 29, 30),
    ("keep_days", 45, 30),  # snapped DOWN to an allowed value
    ("keep_days", 100, 90),
    ("keep_days", 0, 30),  # <= 0: "as little as possible", the floor (L2), never the default
    ("keep_days", -5, 30),
    ("max_mb", 0, 512),
    ("keep_days", 99999, 90),  # snapped to 365, then the default record (90) caps it
    ("max_mb", 1, 512),
    ("max_mb", 600, 512),
    ("max_mb", False, 2048),
    ("max_mb", 10**9, 2048),
]


@pytest.mark.parametrize("key,value,want", FILE_RETENTION)
def test_file_retention_is_snapped_down_with_a_floor(ws, run, monkeypatch, key, value, want):
    """H2: an agent's edit of config.toml can lower retention only to an allowed value, never below 30 / 512,
    and never writes a record below that floor."""
    from orch import record

    setting = f"insights.{key}"
    config.set_key(ws, "record", key, value)
    assert config.file_value(ws, "record", key) in hp.RETENTION_ALLOWED[setting]
    got = _get(run, setting)
    assert got == want and type(got) is int
    assert getattr(config, f"record_{key}")(ws) == want
    rec = _record(ws, setting)
    assert rec is None or (rec["value"] == want and rec["value"] >= hp.RETENTION_FLOOR[setting])
    seen = []
    monkeypatch.setattr(record, "apply_retention", lambda root, now, keep, mb, fold: seen.append((keep, mb)))
    cli_record.prune(ws, lambda r, e: None, now="2026-11-16T00:00:00Z")
    assert seen[-1][0] >= 30 and seen[-1][1] >= 512 and want in seen[-1]


@pytest.mark.parametrize("planted", [1, 29, 511])
def test_a_record_below_the_floor_counts_as_none(ws, planted):
    hp.key_dir(ws)
    path, wkey = hp._settings_path(ws)
    recs = {
        s: {"value": planted, "by": "file", "at": "2026-11-16T09:00:00Z"}
        for s in ("insights.keep_days", "insights.max_mb")
    }
    hp._write_private(path, json.dumps({"schema": "orch.human-settings/1", "workspaces": {wkey: recs}}))
    assert config.record_keep_days(ws) == 90 and config.record_max_mb(ws) == 2048


def test_unreadable_settings_record_retention_is_the_lower_of_file_and_default(ws):
    hp.key_dir(ws)
    path, _ = hp._settings_path(ws)
    hp._write_private(path, "not json")
    assert config.record_keep_days(ws) == 90 and config.record_max_mb(ws) == 2048
    config.set_key(ws, "record", "keep_days", 30)
    config.set_key(ws, "record", "max_mb", 4096)
    assert config.record_keep_days(ws) == 30 and config.record_max_mb(ws) == 2048


def test_key_lock_nested_in_one_thread_and_another_thread_waits(ws):
    """H1: keys.lock is re-entrant per thread by design (a depth count over one O_EXCL file): nested takes in
    one thread go through; a second thread blocks until the first thread's OUTERMOST exit."""
    import threading

    d = hp.key_dir(ws)
    order, entered = [], threading.Event()

    def other():
        with hp._key_lock(d):
            order.append("other")
        entered.set()

    with hp._key_lock(d):
        with hp._key_lock(d):  # nested in the same thread: no wait, no deadlock
            t = threading.Thread(target=other)
            t.start()
            assert not entered.wait(0.3)  # the other thread is held off ...
        assert not entered.wait(0.2)  # ... also after the INNER exit
        order.append("first")
    assert entered.wait(5)  # ... and gets in after the outermost exit
    t.join(5)
    assert order == ["first", "other"]


def test_proof_stdin_is_read_before_keys_lock_is_taken(ws, run, monkeypatch):
    """M1: the proof line is read (a stdin that never closes) BEFORE change_insights takes keys.lock: while
    the reader waits, another thread can take the lock; only verify-and-consume runs inside it."""
    import threading

    d = hp.key_dir(ws)
    key = "insights.keep_days"
    proof = _sp(ws, key, "365")
    checks = []

    def slow_reader():
        checks.append(hp._lock_held(d))  # not held by this thread while stdin is read
        done = threading.Event()

        def take():
            with hp._key_lock(d):
                done.set()

        t = threading.Thread(target=take)
        t.start()
        checks.append(done.wait(5))  # another thread gets keys.lock while this one waits on stdin
        t.join(5)
        return proof

    monkeypatch.setattr(hp, "read_proof_line", slow_reader)
    code, out, err = run("config", "set", key, "365", "--proof-stdin", "--json")
    assert code == 0, out + err
    assert checks == [False, True] and _get(run, key) == 365 and _used(ws) == 1


def test_a_proof_stdin_that_never_closes_does_not_hold_keys_lock(ws, run, monkeypatch):
    """M1 with a real pipe nobody writes to: the command waits on stdin with keys.lock free."""
    import threading

    d = hp.key_dir(ws)
    r, w = os.pipe()
    reader = os.fdopen(r, "r")
    monkeypatch.setattr("sys.stdin", reader)
    result = []
    t = threading.Thread(
        target=lambda: result.append(
            run("config", "set", "insights.keep_days", "365", "--proof-stdin", "--json")
        ),
        daemon=True,
    )
    t.start()
    time.sleep(0.3)  # the command now waits on the pipe
    got = threading.Event()

    def take():
        with hp._key_lock(d):
            got.set()

    taker = threading.Thread(target=take, daemon=True)
    taker.start()
    try:
        assert got.wait(5), "keys.lock was held while the proof was read from stdin"
    finally:
        os.close(w)  # stdin ends: the command finishes (no proof: refused)
        t.join(10)
    assert result and result[0][0] == 2 and _answer(result[0][1])["code"] == "needs_person"


def test_retention_read_never_overwrites_a_newer_widening(ws, monkeypatch):
    """A reader that saw file 30 < record 365 while a person's widening was between its record write and its
    file write must not write 30 over the person's record once it gets the lock: it reads both again there."""
    key = "insights.keep_days"
    hp.key_dir(ws)
    hp.record_set(ws, key, 365, "human:pat")  # the widening's record write ...
    config.set_key(ws, "record", "keep_days", 30)  # ... the file still says the old value
    real_lock, done = hp._key_lock, []

    @__import__("contextlib").contextmanager
    def lock_after_the_widening(d):
        if not done:
            done.append(1)
            config.set_key(ws, "record", "keep_days", 365)  # the widening finishes before the reader's lock
        with real_lock(d):
            yield

    monkeypatch.setattr(hp, "_key_lock", lock_after_the_widening)
    assert hp.retention(ws, key, 30) == 365
    assert done and _record(ws, key)["value"] == 365 and _record(ws, key)["by"] == "human:pat"
    monkeypatch.setattr(hp, "_key_lock", real_lock)
    config.set_key(ws, "record", "keep_days", 30)  # a real lowering of the file is still recorded at once
    assert config.record_keep_days(ws) == 30
    assert (_record(ws, key)["value"], _record(ws, key)["by"]) == (30, "file")


# ------------------------------------------------------------------ the lock


def test_key_lock_is_reentrant_and_only_the_outermost_exit_unlocks(ws):
    d = hp.key_dir(ws)
    lock = d / "keys.lock"
    with hp._key_lock(d):
        with hp._key_lock(d):
            with hp._key_lock(d):
                assert lock.exists()
            assert lock.exists() and hp._lock_held(d)  # an inner exit keeps the outer lock
        assert lock.exists() and hp._lock_held(d)
    assert not lock.exists() and not hp._lock_held(d)


def test_change_insights_takes_the_lock_once_for_the_whole_section(ws, monkeypatch):
    """Retention read, proof consume and record write all run inside change_insights' lock: the file lock is
    created exactly once (the nested takes are re-entrant)."""
    key = "insights.keep_days"
    hp.key_dir(ws)
    proof = _sp(ws, key, "365")
    created = []
    real_open = os.open

    def counting_open(path, flags, *a, **k):
        if str(path).endswith("keys.lock") and flags & os.O_EXCL:
            created.append(path)
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(hp.os, "open", counting_open)
    res = config.change_insights(
        ws, key, 365, person=lambda t: hp.verify_and_consume(ws, proof, "insights.settings", t)
    )
    monkeypatch.setattr(hp.os, "open", real_open)
    assert res == {key: 365, "changed": True, "widened": True}
    assert len(created) == 1 and _used(ws) == 1


def _settle_child(fake_home, ws, name, value, proof, log, barrier, q):
    """One process of the concurrency test (spawned: it repeats the fixture's fake home)."""
    from orch import addons

    addons.real_home = lambda: Path(fake_home)
    os.chdir(ws)
    real = config.set_insights

    def logged(root, setting, v, by=None):  # runs inside change_insights' lock: the serialized order
        out = real(root, setting, v, by)
        with open(log, "a") as f:
            f.write(f"{name}\n")
        return out

    config.set_insights = logged
    barrier.wait()
    try:
        res = config.change_insights(
            Path(ws),
            "insights.keep_days",
            value,
            person=lambda t: hp.verify_and_consume(Path(ws), proof, "insights.settings", t),
        )
        q.put((name, res))
    except Exception as e:  # noqa: BLE001 - reported to the parent
        q.put((name, repr(e)))


def test_two_processes_widen_and_narrow_concurrently(ws, tmp_path):
    """Two real processes, one widening 90 -> 365 with a proof and one narrowing to 30: the final record, the
    file and the effective value are the LAST serialized writer's, the proof is spent once, nothing is
    lost."""
    import multiprocessing as mp

    from orch import addons

    key = "insights.keep_days"
    ctx = mp.get_context("spawn")
    hp.key_dir(ws)
    for round_ in range(3):
        hp._settings_write(ws, key, 90, "reset")  # back to the start: record and file 90
        config.set_key(ws, "record", "keep_days", 90)
        spent = _used(ws)
        log = tmp_path / f"order-{round_}.log"
        proof = _sp(ws, key, "365")
        barrier, q = ctx.Barrier(2), ctx.Queue()
        procs = [
            ctx.Process(
                target=_settle_child,
                args=(str(addons.real_home()), str(ws), name, value, proof, str(log), barrier, q),
            )
            for name, value in (("widen", 365), ("narrow", 30))
        ]
        for p in procs:
            p.start()
        res = dict(q.get(timeout=60) for _ in procs)
        for p in procs:
            p.join(30)
        assert all(isinstance(r, dict) for r in res.values()), res
        order = log.read_text().split()
        assert sorted(order) == ["narrow", "widen"], order  # both wrote, one after the other
        want = {"widen": 365, "narrow": 30}[order[-1]]
        assert res["widen"]["changed"] and res["narrow"]["changed"]
        assert _record(ws, key)["value"] == want
        assert _record(ws, key)["by"] == ("human:pat" if want == 365 else "reset")
        assert config.read(ws)["record"]["keep_days"] == want and config.record_keep_days(ws) == want
        assert _used(ws) == spent + 1  # the widening's proof, spent exactly once


# ------------------------------------------------------------------ delete-detail (2.11 review)


def test_delete_detail_not_found_comes_before_the_proof(ws, rec, run, monkeypatch):
    proof = _proof(ws, "record.delete_detail", "t_nothere1")
    code, out, _ = _cli(run, monkeypatch, proof, "record", "delete-detail", "t_nothere1", "--json")
    assert code == 2 and _answer(out)["code"] == "not_found"
    assert _used(ws) == 0  # the proof was never read
    _untouched(ws)


@pytest.mark.parametrize("ticket", ["t_abcdef/../x", "../../t_abcdef", "r_8k2m01", "t_ABC123", "t_a"])
def test_delete_detail_odd_ids_are_not_found(ws, rec, run, monkeypatch, ticket):
    proof = _proof(ws, "record.delete_detail", "t_nothere1")
    code, out, _ = _cli(run, monkeypatch, proof, "record", "delete-detail", ticket, "--json")
    assert code == 2 and _answer(out)["code"] == "not_found"
    assert _used(ws) == 0
    _untouched(ws)


@pytest.mark.parametrize("error", [OSError("disk"), "invalid"])
def test_delete_detail_audit_line_failure_deletes_nothing(ws, rec, run, monkeypatch, error):
    from orch import record

    def fail(*a, **k):
        raise record.RecordInvalid() if error == "invalid" else error

    monkeypatch.setattr(record, "note_change", fail)
    a, _ = rec
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 2 and _answer(out) == {"error": cli_record.DELETE_NOT_SAVED, "code": "not_available"}
    assert "Traceback" not in err and str(ws) not in out + err
    _untouched(ws)


def test_delete_detail_symlinked_detail_folder_is_tampered(ws, rec, run, monkeypatch, tmp_path):
    a, _ = rec
    detail = record_dir(ws) / "detail"
    moved = tmp_path / "moved-detail"
    detail.rename(moved)
    detail.symlink_to(moved, target_is_directory=True)
    code, out, _ = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 2 and _answer(out)["code"] == "tampered"
    assert (moved / RUN_A).is_dir() and (moved / RUN_B).is_dir() and (moved / RUN_C).is_dir()
    assert _changes(ws) == []


def test_delete_detail_partial_deletion(ws, rec, run, monkeypatch):
    """A crash in the middle: the audit line (written first) stays, the error is plain (not_available), what
    is left goes with a new proof."""
    from orch import record

    a, _ = rec
    real, calls = record._unlink, []

    def flaky(*args, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk")
        return real(*args, **kw)

    monkeypatch.setattr(record, "_unlink", flaky)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 2 and _answer(out) == {"error": cli_record.DELETE_PARTLY, "code": "not_available"}
    assert "Traceback" not in err
    left = [p for r in (RUN_A, RUN_B) if _detail(ws, r).is_dir() for p in _detail(ws, r).iterdir()]
    assert 1 <= len(left) < 4
    assert len(_changes(ws)) == 1
    monkeypatch.setattr(record, "_unlink", real)
    code, out, _ = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0 and json.loads(out)["ticket"] == a
    assert not _detail(ws, RUN_A).exists() and not _detail(ws, RUN_B).exists() and _detail(ws, RUN_C).is_dir()


def test_delete_detail_keeps_other_tickets_detail_in_a_shared_run(ws, rec, run, monkeypatch):
    """A line of ticket A added to B's run (e.g. by a hook caller) makes the run shared: A's proof deletes
    only the detail A's own lines point at; B's detail in that run stays readable."""
    a, b = rec
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    w.append(
        dict(example, run=RUN_C, ticket=a, id="toolu_planted1", at="2026-11-16T09:15:00Z"),
        detail={"input": {"n": 9}, "output": "planted"},
    )
    before = sorted(p.name for p in _detail(ws, RUN_C).iterdir())
    assert len(before) == 3
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    # RUN_A, RUN_B and A's one file in RUN_C
    assert json.loads(out) == {"deleted": 3, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    after = sorted(p.name for p in _detail(ws, RUN_C).iterdir())
    assert len(after) == 2 and set(after) < set(before)
    for n in (1, 2):  # B's detail is still there
        code, out, _ = run("record", "query", "--run", RUN_C, "--detail", f"toolu_{RUN_C[2:]}{n}", "--json")
        assert code == 0, out
    code, out, _ = run("record", "query", "--run", RUN_C, "--detail", "toolu_planted1", "--json")
    assert code == 2 and _answer(out)["code"] == "not_found"


def _plant(ws, run_id, line):
    """An agent with file access appends a raw line to a run file (no writer, no hider)."""
    path = record_dir(ws) / "runs" / f"{run_id}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(line) + "\n")


def _own_line(ws, run_id, n):
    path = record_dir(ws) / "runs" / f"{run_id}.jsonl"
    return next(
        e for e in map(json.loads, path.read_text().splitlines()) if e["id"] == f"toolu_{run_id[2:]}{n}"
    )


def _planted_b_line(ws, b):
    """A line of ticket B in A's run naming A's detail file (same id, finished, so dedupe keeps it)."""
    victim = _own_line(ws, RUN_A, 1)
    return dict(victim, ticket=b, seq=99, outcome={"ok": True, "error": None, "ms": 1})


def test_detail_names_differ_per_ticket_in_one_run(ws, rec):
    """I4: ticket A's line in B's run with the same run, kind and id gets its own detail file."""
    from orch import record

    a, b = rec
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    same = f"toolu_{RUN_C[2:]}1"
    mine = w.append(
        dict(
            example,
            run=RUN_C,
            ticket=a,
            id=same,
            at="2026-11-16T09:15:00Z",
            outcome={"ok": True, "error": None, "ms": 1},
        ),
        detail={"input": {"n": 9}, "output": "a's own"},
    )
    theirs = _own_line(ws, RUN_C, 1)
    assert (mine["id"], mine["kind"]) == (theirs["id"], theirs["kind"]) and theirs["ticket"] == b
    assert mine["detail"] and theirs["detail"] and mine["detail"] != theirs["detail"]
    for line, ticket, output in ((mine, a, "a's own"), (theirs, b, "x" * 2000)):
        got = record.read_detail(ws, RUN_C, Path(line["detail"]).stem, ticket=ticket).unwrap()
        assert (got["ticket"], got["output"]) == (ticket, output)


def test_planted_line_of_another_ticket_does_not_block_delete(ws, rec, run, monkeypatch):
    """A line of ticket B pointing at A's detail file does not stop A's delete (no veto by other tickets), and
    A's delete leaves B's own detail alone, also B's file in a run A shares."""
    a, b = rec
    example = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    w.append(
        dict(
            example,
            run=RUN_C,
            ticket=a,
            id=f"toolu_{RUN_C[2:]}1",
            at="2026-11-16T09:15:00Z",
            outcome={"ok": True, "error": None, "ms": 1},
        ),
        detail={"input": {"n": 9}, "output": "a's own"},
    )
    _plant(ws, RUN_A, _planted_b_line(ws, b))
    b_files = sorted(p.name for p in _detail(ws, RUN_C).iterdir())
    assert len(b_files) == 3
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert json.loads(out) == {"deleted": 3, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert not _detail(ws, RUN_A).exists() and not _detail(ws, RUN_B).exists()
    left = sorted(p.name for p in _detail(ws, RUN_C).iterdir())
    assert len(left) == 2 and set(left) < set(b_files)
    from orch import record

    for n in (1, 2):  # B's own detail is untouched and still readable through B's own lines
        line = _own_line(ws, RUN_C, n)
        got = record.read_detail(ws, RUN_C, Path(line["detail"]).stem, ticket=b).unwrap()
        assert (got["ticket"], got["output"]) == (b, "x" * 2000)
    code, out, _ = run("record", "query", "--run", RUN_C, "--detail", f"toolu_{RUN_C[2:]}2", "--json")
    assert code == 0 and json.loads(out)["output"] == "x" * 2000


def test_planted_line_path_is_refused_on_read_and_counted_as_kept(ws, rec, run, monkeypatch):
    """The planted line of B names A's file: reading it through that line is refused (the file's own ticket is
    not the line's), and B's delete does not follow it: A's file stays, reported as kept (never silent)."""
    a, b = rec
    _plant(ws, RUN_A, _planted_b_line(ws, b))
    target = _own_line(ws, RUN_A, 1)["id"]
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", target, "--json")
    assert code == 2 and _answer(out)["code"] == "tampered"
    a_files = sorted(p.name for p in _detail(ws, RUN_A).iterdir())
    assert len(a_files) == 2
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", b), "record", "delete-detail", b, "--json"
    )
    assert code == 0, out + err
    # B's RUN_C goes; A's file named by B's planted line stays and is reported
    assert json.loads(out) == {"deleted": 1, "ticket": b, "kept": 1, "unreadable": 0, "skipped": 0}
    assert not _detail(ws, RUN_C).exists()
    assert sorted(p.name for p in _detail(ws, RUN_A).iterdir()) == a_files
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", f"toolu_{RUN_A[2:]}2", "--json")
    assert code == 0 and json.loads(out)["ticket"] == a


@pytest.mark.parametrize("how", ["fifo", "file_link", "folder_link"])
def test_planted_unsafe_detail_of_one_run_is_no_veto(ws, rec, run, monkeypatch, tmp_path, how):
    """MED-1 / R1: a planted line of ticket A (a made-up id) plus a FIFO or a link at the detail name it
    computes: only that FILE is skipped (`skipped`), A's real detail in the same run and in the other run
    goes. A linked run detail FOLDER: that run is skipped and counted unreadable (its detail stays), the
    other run loses A's detail. Never a veto of the whole delete."""
    from orch import record

    if how == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("requires FIFO")
    a, _ = rec
    victim, kept_run = (RUN_B, RUN_A) if how == "folder_link" else (RUN_A, RUN_B)
    line = _own_line(ws, victim, 1)
    name = record.detail_name(victim, line["kind"], "toolu_fake01", a)
    _plant(ws, victim, dict(line, id="toolu_fake01", seq=99, detail=f"detail/{victim}/{name}.json"))
    target = _detail(ws, victim) / f"{name}.json"
    outside = tmp_path / "outside"
    outside.mkdir()
    if how == "fifo":
        os.mkfifo(target, 0o600)
    elif how == "file_link":
        (outside / "x.json").write_text("{}")
        target.symlink_to(outside / "x.json")
    else:
        _detail(ws, victim).rename(outside / victim)
        _detail(ws, victim).symlink_to(outside / victim, target_is_directory=True)
    before = sorted(p.name for p in _detail(ws, victim).iterdir())
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert not _detail(ws, kept_run).exists()  # the other run of A lost its detail
    assert _detail(ws, RUN_C).is_dir()
    if how == "folder_link":
        assert json.loads(out) == {"deleted": 1, "ticket": a, "kept": 0, "unreadable": 1, "skipped": 0}
        assert "1 run could not be read; its detail was not deleted." in err
        assert sorted(p.name for p in _detail(ws, victim).iterdir()) == before  # the skipped run keeps it all
        assert [c["deleted"] for c in _changes(ws)] == [1]
    else:
        assert json.loads(out) == {"deleted": 2, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 1}
        assert "1 detail file was changed outside orch; it was not deleted." in err
        assert "could not be read" not in err
        # A's two real files in the victim run went; only the planted one stays (and what it points at)
        assert [p.name for p in _detail(ws, victim).iterdir()] == [f"{name}.json"] and len(before) == 3
        assert how == "fifo" or (outside / "x.json").read_text() == "{}"
        assert [c["deleted"] for c in _changes(ws)] == [2]


def test_find_detail_files_skips_an_unsafe_file_or_run_and_refuses_only_an_unsafe_detail_folder(
    ws, rec, tmp_path
):
    """R1: a file that is not safe skips only that pair (`kept`); a run's folder that is a link skips that run
    (`unreadable`); only the detail folder itself refuses. N3: the answer is not a tuple (an old caller that
    unpacks it fails loudly)."""
    from orch import record

    files = {r: sorted(p.stem for p in _detail(ws, r).iterdir()) for r in (RUN_A, RUN_B)}
    items = [(r, f) for r in (RUN_A, RUN_B) for f in files[r]]
    bad = (RUN_A, files[RUN_A][0])
    (_detail(ws, RUN_A) / f"{bad[1]}.json").unlink()
    (_detail(ws, RUN_A) / f"{bad[1]}.json").symlink_to(tmp_path)
    got = record.find_detail_files(ws, items)
    assert got.status == "ok" and got.alert is None
    assert got.value == record.DetailFiles(tuple(ref for ref in items if ref != bad), (), (bad,))
    with pytest.raises(TypeError):
        pairs, runs = got.value
    _detail(ws, RUN_B).rename(tmp_path / "moved_b")
    _detail(ws, RUN_B).symlink_to(tmp_path / "moved_b", target_is_directory=True)
    got = record.find_detail_files(ws, items)
    assert got.value == record.DetailFiles(((RUN_A, files[RUN_A][1]),), (RUN_B,), (bad,))
    detail = record_dir(ws) / "detail"
    detail.rename(tmp_path / "moved")
    detail.symlink_to(tmp_path / "moved", target_is_directory=True)
    got = record.find_detail_files(ws, items)
    assert got.status == "tampered" and got.reason == "link"


def test_delete_detail_files_a_run_pruned_in_between_is_already_gone(ws, rec, run, monkeypatch):
    """L4: retention pruned a run between finding the files and deleting them: already gone, not a partial
    delete; the other run's files go."""
    import shutil

    from orch import record

    a, _ = rec
    real = record.delete_detail_files

    def pruned_first(root, items, **kw):
        shutil.rmtree(_detail(ws, RUN_B))  # retention, at the same moment
        return real(root, items, **kw)

    monkeypatch.setattr(record, "delete_detail_files", pruned_first)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    # the answer says what this call deleted (RUN_A); the audit line, written before, what was going to go
    assert json.loads(out) == {"deleted": 1, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 0}
    assert [c["deleted"] for c in _changes(ws)] == [2]
    assert not _detail(ws, RUN_A).exists() and not _detail(ws, RUN_B).exists()
    nothing = real(ws, [(RUN_B, "a" * 32), ("r_gone0001", "b" * 32)])  # nothing there: nothing fails
    assert nothing == record.DetailFiles()


@pytest.mark.parametrize("how", ["file", "folder", "lock"])
def test_delete_detail_files_a_swap_after_finding_skips_only_that(ws, rec, run, monkeypatch, tmp_path, how):
    """N4: after the files were found (and the audit line written), one file, the run's detail folder or the
    run's lock is swapped for a link: only that file (or run) stays, reported; the rest goes and the answer
    says what went. No whole refusal after the audit line."""
    from orch import record

    a, _ = rec
    real = record.delete_detail_files
    first = sorted(_detail(ws, RUN_A).iterdir())[0]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("x")

    def swapped_first(root, items, **kw):
        if how == "file":
            first.unlink()
            first.symlink_to(elsewhere)
        elif how == "folder":
            _detail(ws, RUN_A).rename(tmp_path / "moved")
            _detail(ws, RUN_A).symlink_to(tmp_path / "moved", target_is_directory=True)
        else:
            (record_dir(ws) / "runs" / f"{RUN_A}.lock").symlink_to(elsewhere)
        return real(root, items, **kw)

    monkeypatch.setattr(record, "delete_detail_files", swapped_first)
    code, out, err = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 0, out + err
    assert [c["deleted"] for c in _changes(ws)] == [2]  # the audit line: what was going to go
    assert not _detail(ws, RUN_B).exists() and _detail(ws, RUN_C).is_dir()
    assert elsewhere.read_text() == "x"
    if how == "file":
        assert json.loads(out) == {"deleted": 2, "ticket": a, "kept": 0, "unreadable": 0, "skipped": 1}
        assert "1 detail file was changed outside orch; it was not deleted." in err
        assert [p.name for p in _detail(ws, RUN_A).iterdir()] == [first.name]  # only the swapped one stays
    else:
        assert json.loads(out) == {"deleted": 1, "ticket": a, "kept": 0, "unreadable": 1, "skipped": 0}
        assert "1 run could not be read; its detail was not deleted." in err
        assert len(list(_detail(ws, RUN_A).iterdir())) == 2  # the skipped run keeps all its detail


# ------------------------------------------------------------------ prune reads the effective values


def test_prune_uses_the_effective_values(ws, run, monkeypatch):
    from orch import record

    seen = []
    monkeypatch.setattr(record, "apply_retention", lambda root, now, keep, mb, fold: seen.append((keep, mb)))
    config.set_key(ws, "record", "keep_days", 365)  # the file alone: never longer than approved
    config.set_key(ws, "record", "max_mb", 4096)
    cli_record.prune(ws, lambda r, e: None, now="2026-11-16T00:00:00Z")
    assert seen[-1] == (90, 2048)
    proof = _sp(ws, "insights.keep_days", "365")
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.keep_days", "365", "--json")[0] == 0
    cli_record.prune(ws, lambda r, e: None)
    assert seen[-1] == (365, 2048)
    config.set_key(ws, "record", "keep_days", 30)  # a lower file value counts at once
    cli_record.prune(ws, lambda r, e: None)
    assert seen[-1] == (30, 2048)


# ------------------------------------------------------------------ --detail compares ticket and id (M5)


def test_detail_of_a_line_with_no_ticket_is_tampered(ws, rec, monkeypatch, run):
    """The line's ticket is ALWAYS compared: a line with no ticket (None) never reads a stored t_... file."""
    from orch import record

    real = record.read_run

    def ticketless(*a, **k):
        result = real(*a, **k)
        for e in result.value or []:
            e.pop("ticket", None)
        return result

    monkeypatch.setattr(record, "read_run", ticketless)
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", f"toolu_{RUN_A[2:]}1", "--json")
    assert code == 2 and _answer(out)["code"] == "tampered"


def test_detail_whose_stored_id_is_not_the_lines_is_tampered(ws, rec, run):
    """A planted line of the SAME ticket with another id pointing at an existing file: the stored id
    differs."""
    victim = _own_line(ws, RUN_A, 1)
    _plant(ws, RUN_A, dict(victim, id="toolu_fake01", seq=99))
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", "toolu_fake01", "--json")
    assert code == 2 and _answer(out)["code"] == "tampered"
    code, out, _ = run("record", "query", "--run", RUN_A, "--detail", victim["id"], "--json")
    assert code == 0 and json.loads(out)["id"] == victim["id"]


def test_counts_report_the_effective_share_names(ws, run, monkeypatch):
    def names():
        code, out, err = run("record", "counts", "--json")
        assert code == 0, out + err
        return json.loads(out)["sharing"]["names"]

    assert names() is False
    config.set_key(ws, "insights", "share_names", True)  # the file alone: still off
    assert names() is False
    proof = _sp(ws, "insights.share_names", "on")
    assert _cli(run, monkeypatch, proof, "config", "set", "insights.share_names", "on", "--json")[0] == 0
    assert names() is True


def test_relay_connect_clears_the_last_admin_policy(ws, monkeypatch):
    """A (re)connection never inherits a stale admin policy; the refresh of THIS connection writes it."""
    from orch import net, relay

    _connect(ws, "off")
    assert config.share_counts_state(ws) == "off_by_admin"
    monkeypatch.setattr(net, "connect_service", lambda *a, **k: {"workspace": "w_2"})
    monkeypatch.setattr(relay, "refresh", lambda root: "refreshed")
    relay.connect(ws, "https://r2.example", "w_2", "orn_y")
    assert not (net.secrets_dir(ws) / "policy.json").exists()
    assert config.share_counts_state(ws) == "on"


def test_relay_connect_that_fails_keeps_the_current_policy(ws, monkeypatch):
    """N7: a failed reconnect (a wrong token: nothing written) keeps the current connection's admin policy, so
    its off_by_admin guard stays; a connection that stops half-way AFTER writing the new relay.json never
    pairs with the old policy; a successful one clears it also when the old connection's refresh wrote one
    in between."""
    from orch import net, relay

    _connect(ws, "off")
    policy = net.secrets_dir(ws) / "policy.json"
    conn = net.secrets_dir(ws) / "relay.json"

    def wrong_token(*a, **k):
        raise Refused("That token does not look right.")

    monkeypatch.setattr(net, "connect_service", wrong_token)
    with pytest.raises(Refused):
        relay.connect(ws, "https://r2.example", "w_2", "orn_y")
    assert policy.is_file() and config.share_counts_state(ws) == "off_by_admin"

    def half_way(*a, **k):
        conn.write_text(json.dumps({"url": "https://r2.example", "workspace": "w_2", "token": "orn_y"}))
        raise OSError("the skills could not be refreshed")

    monkeypatch.setattr(net, "connect_service", half_way)
    with pytest.raises(OSError):
        relay.connect(ws, "https://r2.example", "w_2", "orn_y")
    assert not policy.exists() and config.share_counts_state(ws) == "on"

    _connect(ws, "off")
    monkeypatch.setattr(
        net, "connect_service", lambda *a, **k: policy.write_text("{}") or {"workspace": "w_2"}
    )
    monkeypatch.setattr(relay, "refresh", lambda root: "refreshed")
    relay.connect(ws, "https://r2.example", "w_2", "orn_y")
    assert not policy.exists()


def test_an_event_with_no_ticket_gets_no_detail_file(ws):
    """M5: one rule for a missing ticket: no detail file (not detail_lost); the writer's guard."""
    w = RecordWriter(ws, hider=hider.Hider({"deploy-key": "KEYVALUE-abc123XYZ-secret"}))
    event = {"run": RUN_A, "kind": "step", "id": "toolu_x", "ticket": None}
    assert w._prepare_detail(event, {"input": {}, "output": "x"}) is None
    assert "detail_lost" not in event

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
    return root


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


def test_insights_is_a_page_server(ws):
    assert "insights" in hp.LAUNCH_SERVERS and "insights" in pageproof.SERVERS
    assert hp.write_launch_token(ws, "insights")
    pageproof.PageSession(ws, "insights")  # accepted as a page server


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
    assert json.loads(out) == {"deleted": 2, "ticket": a}
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
    assert code == 0 and json.loads(out) == {"deleted": 0, "ticket": a}
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


def test_delete_detail_unreadable_record_deletes_nothing(ws, rec, run, monkeypatch, tmp_path):
    a, _ = rec
    run_file = record_dir(ws) / "runs" / f"{RUN_C}.jsonl"
    outside = tmp_path / "outside.jsonl"
    run_file.rename(outside)
    run_file.symlink_to(outside)  # one run of the record was changed outside orch
    code, out, _ = _cli(
        run, monkeypatch, _proof(ws, "record.delete_detail", a), "record", "delete-detail", a, "--json"
    )
    assert code == 2 and _answer(out)["code"] == "tampered"
    assert _detail(ws, RUN_A).is_dir() and _detail(ws, RUN_B).is_dir()
    assert _changes(ws) == []


def test_delete_detail_needs_json(ws, rec, run):
    code, out, err = run("record", "delete-detail", rec[0])
    assert code == 2 and "Use --json" in err
    assert cli_record.SUBCOMMANDS == ("tail", "query", "counts", "settings", "delete-detail")


def test_proof_request_parts_for_the_hand_off_cards(monkeypatch):
    """Hand-off card parts: {setting, value} for insights.settings, {title} for record.delete_detail."""
    import inspect

    from orch import cli_config, cli_record

    cfg = inspect.getsource(cli_config)
    rec = inspect.getsource(cli_record)
    assert 'parts={"setting": key, "value": args.value}' in cfg
    assert 'parts={"title": _ticket_title(root, tid)}' in rec

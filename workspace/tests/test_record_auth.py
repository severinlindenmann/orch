"""Record MAC, slice S1: the pure core (orch.record_auth), the key and head helpers in humanproof, and the
contract vectors (contracts/vectors/activity-v1.json "record_auth"; independent reference in
contracts/validate.py).

The writer and readers do not use any of this yet (S2), so these tests also pin that nothing else changed."""

import hmac
import json
import os
import re
from pathlib import Path

import jsonschema
import pytest

from orch import addons
from orch import humanproof as hp
from orch import record_auth as ra
from orch.errors import Refused

pytestmark = pytest.mark.no_record_key  # this module builds its own guarded test homes (fixture tws)

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
VEC = json.loads((CONTRACTS / "vectors/activity-v1.json").read_text())["record_auth"]
HK = bytes.fromhex(VEC["human_key"])
WS, RUN = VEC["ws"], VEC["run"]
RK, KID = ra.derive(HK, WS)


def _raw(lines):
    return b"".join(bytes.fromhex(x) for x in lines)


def _summary(v):
    return dict(shown=[e["seq"] for e in v.events], changed=v.changed, removed=v.removed, reason=v.reason)


def _ids(cases):
    return [c["name"] for c in cases]


def _body(n, **over):
    ev = {"v": 1, "id": f"{RUN}:{n}", "seq": n, "run": RUN, "via": "core", "kind": "run.state", "text": "t"}
    ev.update(over)
    return json.dumps(ev, separators=(",", ":"), ensure_ascii=False).encode()


def _chain(n, rk=RK, kid=KID, run=RUN, ws=WS, **over):
    lines, p = [], ra.genesis(rk, ws, run)
    for s in range(1, n + 1):
        line = ra.seal(rk, kid, ws, run, s, p, _body(s, run=run, **over))
        lines.append(line)
        p = ra.split(line)[3]
    return lines


# ------------------------------ vectors


def test_derive_matches_vector():
    assert (RK.hex(), KID) == (VEC["rk"], VEC["kid"])
    assert ra.genesis(RK, WS, RUN) == VEC["genesis"]
    assert ra.job_genesis(RK, WS, RUN, VEC["job"]) == VEC["job_genesis"]
    assert RK != HK  # a subkey, never human.key itself
    assert ra.derive(HK, VEC["ws_other"])[0] != RK  # bound to the workspace


@pytest.mark.parametrize("c", VEC["seal"], ids=lambda c: f"seq{c['seq']}")
def test_seal_matches_vector(c):
    body = bytes.fromhex(c["body_hex"])
    line = ra.seal(RK, KID, WS, RUN, c["seq"], c["prev"], body)
    assert line.hex() == c["line_hex"]
    assert ra.split(line) == (body, KID, c["prev"], ra.split(line)[3])
    assert len(line) - len(body) == ra.SUFFIX_LEN  # the "}" of the body is replaced by the "," of the suffix


@pytest.mark.parametrize("c", VEC["verify"], ids=_ids(VEC["verify"]))
def test_verify_vectors(c):
    assert _summary(ra.verify_run(_raw(c["lines"]), RUN, WS, RK, KID, c["head"])) == c["expect"]


@pytest.mark.parametrize("c", VEC["legacy"], ids=_ids(VEC["legacy"]))
def test_legacy_vectors(c):
    raw = b"".join(bytes.fromhex(x) if x.endswith("0a") else bytes.fromhex(x) + b"\n" for x in c["lines"])
    if c["head"] == "unknown":
        # the head state is the guarded home's, decided in humanproof (never "legacy"): see the damage tests
        assert c["expect"]["mode"] == "unverified"
        return
    mode, _rest, unchecked = ra.legacy_split(raw, c["head"] == "present")
    assert {"mode": mode, "unchecked": unchecked} == c["expect"]


@pytest.mark.parametrize("c", VEC["legacy_prefix"], ids=_ids(VEC["legacy_prefix"]))
def test_legacy_prefix_vectors(c):
    pre, base = ra.legacy_prefix(bytes.fromhex(c["raw_hex"]), c["head"])
    assert {"prefix_lines": len([x for x in pre.split(b"\n") if x]), "base": base} == c["expect"]


@pytest.mark.parametrize("c", VEC["job_streams"], ids=_ids(VEC["job_streams"]))
def test_job_vectors(c):
    got = ra.verify_run(_raw(c["lines"]), RUN, WS, RK, KID, c["head"], job=c["job"])
    assert _summary(got) == c["expect"]


@pytest.mark.parametrize("c", VEC["spool"], ids=_ids(VEC["spool"]))
def test_spool_vectors(c):
    assert ra.drain_ok(RK, WS, RUN, c["file"], c["entry"], c["sm"], c["drained"], c["floor"]) is c["drain"]


@pytest.mark.parametrize("c", VEC["detail"], ids=_ids(VEC["detail"]))
def test_detail_vectors(c):
    got = "ok" if ra.detail_hash(bytes.fromhex(c["file_hex"])) == c["detail_hash"] else "swapped"
    assert got == c["detail"]


@pytest.mark.parametrize("c", VEC["heads"], ids=_ids(VEC["heads"]))
def test_head_vectors(c):
    assert ra.head_ok(RK, WS, c["head"]) is c["ok"]


# ------------------------------ adversarial


def test_forged_line_with_real_shape_is_changed_never_shown():
    real = _chain(2)
    # the agent plants a line that says via core / run.state done, guessing the shape, with a made-up MAC
    forged = _body(2, via="core", kind="run.state", text="done")[:-1] + (
        b',"auth":{"k":"%s","p":"%s","m":"%s"}}\n' % (KID.encode(), b"A" * 43, b"B" * 43)
    )
    v = ra.verify_run(real[0] + forged + real[1], RUN, WS, RK, KID)
    assert [e["seq"] for e in v.events] == [1, 2] and v.events[1]["text"] == "t"
    assert (v.changed, v.removed, v.reason) == (1, 0, "content")


def test_forged_line_sealed_with_a_guessed_key_is_changed():
    wrong_rk, _ = ra.derive(b"\x01" * 32, WS)
    forged = ra.seal(
        wrong_rk, KID, WS, RUN, 1, ra.genesis(wrong_rk, WS, RUN), _body(1, via="broker", kind="key.use")
    )
    v = ra.verify_run(forged, RUN, WS, RK, KID)
    assert v.events == [] and v.changed == 1 and v.reason == "content"


def test_an_edited_byte_anywhere_in_the_body_breaks_the_line():
    line = _chain(1)[0]
    for i in range(0, len(line) - ra.SUFFIX_LEN, 7):
        edited = line[:i] + bytes([line[i] ^ 1]) + line[i + 1 :]
        v = ra.verify_run(edited, RUN, WS, RK, KID)
        assert v.events == [], i


def test_edited_via_or_kind_breaks_the_line():
    line = _chain(1)[0]
    for a, b in ((b'"via":"core"', b'"via":"log"'), (b'"kind":"run.state"', b'"kind":"step"')):
        assert a in line
        assert ra.verify_run(line.replace(a, b), RUN, WS, RK, KID).events == []


def test_edited_link_or_kid_breaks_the_line():
    line = _chain(1)[0]
    body, kid, p, m = ra.split(line)
    other_p = "C" * 43
    assert ra.verify_run(line.replace(p.encode(), other_p.encode()), RUN, WS, RK, KID).events == []
    swapped = body[:-1] + b',"auth":{"k":"%s","p":"%s","m":"%s"}}\n' % (KID.encode(), p.encode(), b"D" * 43)
    assert ra.verify_run(swapped, RUN, WS, RK, KID).events == []


def test_reordered_lines_never_show_a_line_twice_or_out_of_order():
    a, b, c, d = _chain(4)
    v = ra.verify_run(a + c + b + d, RUN, WS, RK, KID)
    seqs = [e["seq"] for e in v.events]
    assert seqs == sorted(set(seqs)) and 2 not in seqs and v.changed == 1


def test_truncated_tail_is_seen_through_the_head():
    lines = _chain(4)
    head = {"kid": KID, "seq": 4}
    v = ra.verify_run(b"".join(lines[:2]), RUN, WS, RK, KID, head)
    assert (v.removed, v.changed, v.reason) == (2, 0, "removed")
    assert (
        ra.verify_run(b"".join(lines[:2]), RUN, WS, RK, KID).removed == 0
    )  # without a head nothing is known


def test_head_seq_must_be_a_real_integer():
    lines = b"".join(_chain(2))
    for seq in (True, 9.0, "9"):
        assert ra.verify_run(lines, RUN, WS, RK, KID, {"kid": KID, "seq": seq}).removed == 0


def test_deleted_file_with_head_is_removed_not_empty_ok():
    v = ra.verify_run(b"", RUN, WS, RK, KID, {"kid": KID, "seq": 3})
    assert (v.events, v.removed, v.reason) == ([], 3, "removed")


def test_line_replayed_from_another_run_or_workspace_is_changed():
    other_run = _chain(2, run="r_other01")
    other_ws = _chain(2, rk=ra.derive(HK, "f" * 32)[0], ws="f" * 32)
    mine = _chain(2)
    v = ra.verify_run(mine[0] + other_run[1] + other_ws[1] + mine[1], RUN, WS, RK, KID)
    assert [e["seq"] for e in v.events] == [1, 2] and v.changed == 2


def test_older_copy_of_the_same_run_cannot_be_spliced_in():
    a = _chain(3)
    b = _chain(3, text="from a rewritten history")  # same seqs, other bodies, valid MACs of the same key
    v = ra.verify_run(a[0] + a[1] + b[2], RUN, WS, RK, KID)
    assert [e["seq"] for e in v.events] == [1, 2]
    assert v.changed == 1  # right seq, wrong link


def test_duplicate_key_and_auth_inside_body_are_not_verified():
    p = ra.genesis(RK, WS, RUN)
    for body in (_body(1)[:-1] + b',"seq":1}', _body(1)[:-1] + b',"auth":{}}'):
        line = ra.seal(RK, KID, WS, RUN, 1, p, body)
        assert ra.verify_run(line, RUN, WS, RK, KID).events == []


def test_seq_must_be_an_integer():
    p = ra.genesis(RK, WS, RUN)
    for seq in ("1", 1.0, True, None):
        body = _body(1, seq=seq)
        line = ra.seal(RK, KID, WS, RUN, 1, p, body)
        assert ra.verify_run(line, RUN, WS, RK, KID).events == []


def test_torn_tail_and_blank_lines_are_not_events():
    lines = _chain(2)
    raw = lines[0] + b"\n\n" + lines[1][:-30]  # a blank line, then a torn write
    v = ra.verify_run(raw, RUN, WS, RK, KID)
    assert [e["seq"] for e in v.events] == [1] and v.changed == 1


def test_junk_line_does_not_shift_later_seq():
    a, b, c = _chain(3)
    v = ra.verify_run(a + b"junk\n" + b + c, RUN, WS, RK, KID)
    assert [e["seq"] for e in v.events] == [1, 2, 3] and v.changed == 1 and v.removed == 0


def test_planted_unknown_kid_is_changed_once_the_current_key_verified():
    a, b = _chain(2)
    planted = _body(1, via="core")[:-1] + b',"auth":{"k":"00000000","p":"%s","m":"%s"}}\n' % (
        b"A" * 43,
        b"B" * 43,
    )
    v = ra.verify_run(a + planted + b, RUN, WS, RK, KID)
    assert [e["seq"] for e in v.events] == [1, 2] and (v.changed, v.reason) == (1, "content")
    # before any verified line it can only be the old segment of a rotation
    v = ra.verify_run(planted + a, RUN, WS, RK, KID)
    assert (v.changed, v.reason) == (1, "old_key") and [e["seq"] for e in v.events] == [1]


def test_key_missing_or_wrong_verifies_nothing():
    lines = b"".join(_chain(3))
    other_rk, other_kid = ra.derive(b"\x07" * 32, WS)
    v = ra.verify_run(lines, RUN, WS, other_rk, other_kid)
    assert v.events == [] and v.changed == 3 and v.reason == "old_key"
    with pytest.raises(ra.SealError):
        ra.derive(b"", WS)  # no key: nothing is derived, nothing sealed


def test_seal_refuses_bad_input_without_leaking_the_key():
    p = ra.genesis(RK, WS, RUN)
    for args in (
        (RK, KID, WS, RUN, 0, p, _body(1)),
        (RK, KID, WS, RUN, 1, "short", _body(1)),
        (RK, "xx", WS, RUN, 1, p, _body(1)),
        (RK, KID, WS, RUN, 1, p, b'{"a":1'),
        (RK, KID, WS, RUN, 1, p, b"{}"),
        (RK, KID, WS, RUN, 1, p, b'["a"]'),
        (RK, KID, WS, RUN, 1, p, b'{"a":"x\n"}'),
    ):
        with pytest.raises(ra.SealError) as e:
            ra.seal(*args)
        assert RK.hex() not in str(e.value) and HK.hex() not in str(e.value)


def test_macs_are_compared_in_constant_time(monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(ra.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    ra.verify_run(b"".join(_chain(2)), RUN, WS, RK, KID)
    assert len(calls) >= 4  # kid and MAC of each line, plus the links
    src = Path(ra.__file__).read_text()
    assert not re.search(r"\b(mac|want|prev)\s*[!=]=\s", src)


def test_split_is_exact_and_rejects_lookalikes():
    line = _chain(1)[0]
    assert ra.split(line)[0] == _body(1)
    assert ra.split(line.rstrip(b"\n")) == ra.split(line)
    assert ra.split(_body(1)) is None
    assert ra.split(line[:-5] + b"}}\n") is None
    assert ra.split(b"x" * 300) is None
    # the suffix must be the LAST 125 bytes: an auth object earlier in the body does not count
    mid = (
        _body(1)[:-1]
        + b',"auth":{"k":"%s","p":"%s","m":"%s"}' % (KID.encode(), b"A" * 43, b"B" * 43)
        + b',"z":1}'
    )
    assert ra.split(mid) is None


def test_spool_entry_is_bound_to_run_name_and_content():
    entry = {"event": {"kind": "step"}, "payload": None, "default_id": "x:1"}
    name = "00000000000000000100_" + "a" * 32 + ".json"
    sm = ra.spool_mac(RK, WS, RUN, name, entry)
    assert ra.spool_ok(RK, WS, RUN, name, entry, sm)
    assert not ra.spool_ok(RK, WS, "r_other01", name, entry, sm)
    assert not ra.spool_ok(RK, WS, RUN, name.replace("a", "b", 1), entry, sm)
    assert not ra.spool_ok(RK, WS, RUN, name, dict(entry, default_id="x:2"), sm)
    assert not ra.spool_ok(RK, WS, RUN, name, entry, None)
    assert not ra.spool_ok(
        RK, WS, RUN, name, dict(entry, sm=sm), sm
    )  # no key outside {event, payload, default_id}
    assert not ra.spool_ok(
        RK, WS, RUN, name, dict(entry, extra=1), ra.spool_mac(RK, WS, RUN, name, dict(entry, extra=1))
    )
    assert not ra.drain_ok(RK, WS, RUN, "../../evil.json", entry, sm, [], "0" * 20)


def test_line_mac_is_not_a_head_or_spool_mac():
    # domains are separate: the same bytes MACed in another domain never verify as a line
    line = _chain(1)[0]
    body, _, p, m = ra.split(line)
    assert m != ra.head_mac(RK, WS, {"seq": 1})
    assert m != ra.spool_mac(RK, WS, RUN, "n", {"a": 1})


# ------------------------------ humanproof helpers


@pytest.fixture
def tws(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    base = acct / ".orch-test"
    ws = base / "ws"
    (ws / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.setattr(hp, "install_kind", lambda: "test")
    for k in list(os.environ):
        if k.startswith("CODEX_") or k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            monkeypatch.delenv(k)
    hp._RECORD_KEYS.clear()
    return ws


def test_record_key_fails_closed_without_key(tws):
    addons.workspace_id(tws, create=True)
    assert hp.record_key(tws) is None  # create=False never makes a key
    assert not (hp.guarded_home(tws) / "keys").exists()  # nothing was created


def test_record_key_is_a_subkey_of_human_key(tws):
    addons.workspace_id(tws, create=True)
    human = hp.human_key(tws)
    ws, kid, rk = hp.record_key(tws)
    assert (rk, kid) == ra.derive(human, ws) and rk != human
    assert hp.record_key(tws) == (ws, kid, rk)


def test_record_key_follows_a_rotation(tws, monkeypatch):
    addons.workspace_id(tws, create=True)
    hp.human_key(tws)
    first = hp.record_key(tws)
    f = hp.key_dir(tws, create=False) / "human.key"
    f.write_text("11" * 32 + "\n")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    second = hp.record_key(tws)
    assert second[1] != first[1] and second[2] == ra.derive(bytes.fromhex("11" * 32), first[0])[0]


def test_record_key_create_makes_the_key(tws):
    addons.workspace_id(tws, create=True)
    assert hp.record_key(tws, create=True) is not None
    assert (hp.key_dir(tws, create=False) / "human.key").exists()


def test_record_head_roundtrip_and_tamper(tws):
    addons.workspace_id(tws, create=True)
    hp.human_key(tws)
    assert hp.record_head_read(tws, "r_abcdef") == (None, True)
    hp.record_head_write(tws, "r_abcdef", {"run": "r_abcdef", "seq": 3, "mac": "M" * 43})
    head, ok = hp.record_head_read(tws, "r_abcdef")
    assert ok and head["seq"] == 3 and head["kid"] == hp.record_key(tws)[1] and head["hm"]
    path = hp.key_dir(tws, create=False) / "record-heads" / "r_abcdef.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    path.write_text(
        path.read_text().replace('"seq":3', '"seq":1')
    )  # an agent lowers the head to hide a truncation
    assert hp.record_head_read(tws, "r_abcdef") == (None, False)
    path.write_text("not json")
    assert hp.record_head_read(tws, "r_abcdef") == (None, False)


def test_record_head_of_one_run_does_not_verify_for_another(tws):
    addons.workspace_id(tws, create=True)
    hp.human_key(tws)
    hp.record_head_write(tws, "r_aaaaaa", {"seq": 9, "mac": "M" * 43})
    hp.record_head_write(tws, "r_bbbbbb", {"seq": 1, "mac": "M" * 43})
    heads = hp.key_dir(tws, create=False) / "record-heads"
    head, ok = hp.record_head_read(tws, "r_aaaaaa")
    assert ok is True and head["run"] == "r_aaaaaa"
    (heads / "r_bbbbbb.json").write_text((heads / "r_aaaaaa.json").read_text())  # copy A over B
    assert hp.record_head_read(tws, "r_bbbbbb") == (None, False)
    hp.record_head_write(tws, "r_cccccc", {"run": "r_aaaaaa", "seq": 2})  # a caller cannot name another run
    assert hp.record_head_read(tws, "r_cccccc")[0]["run"] == "r_cccccc"


def test_record_head_after_a_key_rotation_is_old_key_not_damaged(tws):
    addons.workspace_id(tws, create=True)
    hp.human_key(tws)
    hp.record_head_write(tws, "r_abcdef", {"seq": 4, "mac": "M" * 43})
    f = hp.key_dir(tws, create=False) / "human.key"
    f.write_text("22" * 32 + "\n")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000))
    assert hp.record_head_read(tws, "r_abcdef") == (None, "old_key")


def test_record_key_cache_does_not_survive_a_loose_key(tws):
    addons.workspace_id(tws, create=True)
    hp.human_key(tws)
    first = hp.record_key(tws)
    f = hp.key_dir(tws, create=False) / "human.key"
    f.chmod(0o644)  # same inode, same mtime: only mode and ctime change
    second = hp.record_key(tws)
    assert second != first  # derived again: the loose key was rotated (human_key), never kept in use


def test_record_head_run_name_cannot_leave_the_folder(tws):
    addons.workspace_id(tws, create=True)
    hp.human_key(tws)
    for bad in ("../x", "r_a/b", "", "R_ABCDEF", None):
        with pytest.raises(Refused):
            hp.record_head_write(tws, bad, {"seq": 1})
        assert hp.record_head_read(tws, bad) == (None, False)


def test_record_head_write_needs_a_key(tws):
    addons.workspace_id(tws, create=True)
    with pytest.raises(Refused):
        hp.record_head_write(tws, "r_abcdef", {"seq": 1})


# ------------------------------ nothing else changed


def test_unsigned_current_shape_records_still_validate():
    """Existing (unsigned) examples validate against the root schema (auth and detail_hash are optional)."""
    schema = json.loads((CONTRACTS / "activity.schema.json").read_text())
    root = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    files = sorted((CONTRACTS / "examples/activity").glob("*.json"))
    assert files
    for f in files:
        assert root.is_valid(json.loads(f.read_text())) == f.name.startswith("valid-"), f.name
    sealed = jsonschema.Draft202012Validator({"$ref": "#/$defs/sealed_event", "$defs": schema["$defs"]})
    body = jsonschema.Draft202012Validator({"$ref": "#/$defs/event_body", "$defs": schema["$defs"]})
    ok = json.loads((CONTRACTS / "examples/activity-sealed/valid-step.json").read_text())
    assert sealed.is_valid(ok) and root.is_valid(ok) and not body.is_valid(ok)
    unsigned = {k: v for k, v in ok.items() if k != "auth"}
    assert body.is_valid(unsigned) and not sealed.is_valid(unsigned)


def test_only_the_record_store_and_the_key_helpers_use_the_record_mac():
    src = Path(__file__).resolve().parents[1] / "src/orch"
    users = [
        p.name for p in src.glob("*.py") if p.name != "record_auth.py" and "record_auth" in p.read_text()
    ]
    assert sorted(users) == ["humanproof.py", "record.py"]  # the one writer (_commit) and the one reader


# ------------------------------ S2: the writer and the readers fail closed (real guarded test home)


def _sealed_ws(tws):
    """A test workspace with a key and a sealed run of two lines (written by the writer)."""
    from orch import hider as hiding
    from orch.record import RecordWriter

    addons.workspace_id(tws, create=True)
    hp.human_key(tws)
    w = RecordWriter(tws, hider=hiding.Hider({"k": "KEYVALUE-abc123XYZ-secret"}))
    ev = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    for n in (1, 2):
        w.append(dict(ev, run="r_8k2m01", id=f"toolu_{n}"))
    return w


def _tail(capsys, tws, monkeypatch, run="r_8k2m01"):
    from orch import cli

    monkeypatch.chdir(tws)
    code = cli.main(["record", "tail", "--run", run, "--json"])
    return code, [json.loads(x) for x in capsys.readouterr().out.splitlines()]


def test_writer_is_off_without_a_key_and_nothing_is_written(tws):
    from orch import hider as hiding
    from orch import record

    addons.workspace_id(tws, create=True)
    w = record.RecordWriter(tws, hider=hiding.Hider({"k": "KEYVALUE-abc123XYZ-secret"}))
    ev = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    with pytest.raises(record.RecordOff, match="protection is ready"):
        w.append(dict(ev, run="r_8k2m01"))
    assert not (tws / ".orch/record").exists()


@pytest.mark.parametrize(
    "damage", ["id_removed", "id_forged", "key_folder_unreadable", "key_removed", "second_folder"]
)
def test_a_damaged_guarded_home_never_downgrades_a_sealed_run_to_legacy(tws, capsys, monkeypatch, damage):
    from orch import record

    _sealed_ws(tws)
    assert [e["id"] for e in record.read_run(tws, "r_8k2m01").unwrap()] == ["toolu_1", "toolu_2"]
    # strip the auth too: if any state fell back to the legacy parse, these plain lines would show
    run = tws / ".orch/record/runs/r_8k2m01.jsonl"
    run.write_text(
        "".join(json.dumps(json.loads(ra.split(x)[0])) + "\n" for x in run.read_bytes().splitlines())
    )
    kd = hp.key_dir(tws, create=False)
    if damage == "id_removed":
        (tws / ".orch/.local-id").unlink()
    elif damage == "id_forged":
        (tws / ".orch/.local-id").write_text("ab" * 16 + "\n")
    elif damage == "second_folder":  # an attacker-made second folder bound to this path (SECOND_FOLDER)
        other = kd.parent / ("ab" * 16)
        other.mkdir(mode=0o700)
        (other / "binding.json").write_text(
            json.dumps({"schema": "orch.binding/1", "realpath": os.path.realpath(tws)}) + "\n"
        )
        (tws / ".orch/.local-id").write_text("cd" * 16 + "\n")
    elif damage == "key_folder_unreadable":
        kd.chmod(0)
    else:
        (kd / "human.key").unlink()
    try:
        read = record.read_run(tws, "r_8k2m01")
        # a lost or forged local id is healed from the one bound key folder (#587): the stripped lines are
        # then judged against the head that is there. Never shown as a legacy run either way.
        assert (read.status, read.reason) == ("tampered", "unverified") and read.value is None
        code, lines = _tail(capsys, tws, monkeypatch)
        assert code == 2 and lines[0]["code"] == "tampered"
        assert "orch cannot check these records" in lines[0]["error"]
    finally:
        kd.chmod(0o700)


def test_a_run_with_only_a_head_and_no_sealed_line_is_unverified_without_a_key(tws):
    from orch import record

    _sealed_ws(tws)
    run = tws / ".orch/record/runs/r_8k2m01.jsonl"
    run.write_text('{"v":1}\n')
    (hp.key_dir(tws, create=False) / "human.key").unlink()
    assert record.read_run(tws, "r_8k2m01").reason == "unverified"  # the head is there: never legacy


def test_a_genuine_legacy_run_in_a_clean_home_is_shown_not_checked(tws, capsys, monkeypatch):
    from orch import record

    ev = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    runs = tws / ".orch/record/runs"
    runs.mkdir(parents=True)
    (runs / "r_old00001.jsonl").write_text(json.dumps(dict(ev, run="r_old00001", seq=1)) + "\n")
    _sealed_ws(tws)  # the first sealed write lists the run that existed (cutover)
    read = record.read_run(tws, "r_old00001")
    assert (read.status, read.legacy, read.reason) == ("ok", True, "unchecked")
    code, lines = _tail(capsys, tws, monkeypatch, "r_old00001")
    assert code == 0 and [ln["event"]["checked"] for ln in lines if ln["type"] == "event"] == [False]


def test_a_key_rotation_hides_the_old_lines_and_the_new_segment_is_verified(tws):
    from orch import hider as hiding
    from orch import record

    w = _sealed_ws(tws)
    f = hp.key_dir(tws, create=False) / "human.key"
    f.write_text("11" * 32 + "\n")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    ev = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    stored = w.append(dict(ev, run="r_8k2m01", id="toolu_new"))
    assert stored["seq"] == 1  # a new segment: seq 1 with the new genesis
    read = record.read_run(tws, "r_8k2m01")
    assert (read.reason, read.changed) == ("old_key", 2) and [e["id"] for e in read.unwrap()] == ["toolu_new"]
    assert hiding  # noqa: B015


def test_an_unknown_home_state_with_no_run_file_is_unverified_not_missing(tws):
    from orch import record

    _sealed_ws(tws)
    assert record.read_run(tws, "r_nofile01").reason == "missing"  # clean home, no such run
    kd = hp.key_dir(tws, create=False)
    other = kd.parent / ("ab" * 16)  # a second key folder bound to the same path: the home cannot be trusted
    other.mkdir(mode=0o700)
    (other / "binding.json").write_text(
        json.dumps({"schema": "orch.binding/1", "realpath": os.path.realpath(tws)}) + "\n"
    )
    read = record.read_run(tws, "r_nofile01")
    assert (read.status, read.reason) == ("tampered", "unverified")


@pytest.mark.parametrize("damage", ["removed", "forged"])
def test_a_lost_or_forged_local_id_never_switches_recording_off_or_changes_the_mac(tws, damage):
    from orch import record

    w = _sealed_ws(tws)
    before = hp.record_key(tws)
    idf = tws / ".orch/.local-id"
    if damage == "removed":
        idf.unlink()
    else:
        idf.write_text("ef" * 16 + "\n")
    assert hp.record_key(tws) == before  # the id is the key folder's name, healed from the trusted home
    ev = json.loads((CONTRACTS / "examples/activity/valid-step-started.json").read_text())
    assert w.append(dict(ev, run="r_8k2m01", id="toolu_3"))["seq"] == 3  # still seals
    assert [e["id"] for e in record.read_run(tws, "r_8k2m01").unwrap()] == ["toolu_1", "toolu_2", "toolu_3"]
    # a spool entry made now carries the right workspace id: it still drains
    lock = tws / ".orch/record/runs/r_8k2m01.lock"
    lock.touch()
    import orch.record as rec

    old, rec._LOCK_WAIT = rec._LOCK_WAIT, 0.01
    try:
        w.append(dict(ev, run="r_8k2m01", id="toolu_s"))
    finally:
        rec._LOCK_WAIT = old
    lock.unlink()
    w.append(dict(ev, run="r_8k2m01", id="toolu_4"))
    assert "toolu_s" in [e["id"] for e in record.read_run(tws, "r_8k2m01").unwrap()]

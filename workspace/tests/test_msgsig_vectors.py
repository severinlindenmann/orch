"""Signed messages v1: the shared vectors (contracts/vectors/msgsig-v1.json) against orch.msgsig."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from orch import msgsig

REPO = Path(__file__).resolve().parents[2]
VEC = json.loads((REPO / "contracts" / "vectors" / "msgsig-v1.json").read_text(encoding="utf-8"))


def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def test_msgsig_constants_match_the_contract():
    c = VEC["constants"]
    assert c["tag"] == msgsig.SIG_TAG.decode()
    assert tuple(c["purposes"]) == msgsig.PURPOSES
    assert c["max_signed_bytes"] == msgsig.MAX_SIGNED_BYTES
    assert c["max_depth"] == msgsig.MAX_DEPTH
    assert c["future_skew_ms"] == msgsig.FUTURE_SKEW_MS
    assert c["max_expiry_ms"] == msgsig.MAX_EXPIRY_MS
    assert c["max_age_ms"] == msgsig.MAX_AGE_MS


@pytest.mark.parametrize("name", list(VEC["parties"]))
def test_msgsig_key_id_and_fingerprint(name):
    p = VEC["parties"][name]
    pub = bytes.fromhex(p["pub"])
    assert msgsig.key_id(pub) == p["key_id"]
    assert msgsig.fingerprint(pub) == p["fingerprint"]
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(p["seed"]))
    assert sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw) == pub


@pytest.mark.parametrize("case", VEC["keys"], ids=lambda c: c["name"])
def test_msgsig_public_key_rules(case):
    assert msgsig.public_key_ok(bytes.fromhex(case["pub"])) is case["ok"]


@pytest.mark.parametrize("case", VEC["sign"], ids=lambda c: c["name"])
def test_msgsig_signatures_are_exact(case):
    env = msgsig.sign(bytes.fromhex(case["seed"]), case["purpose"], _b64u(case["signed"]))
    assert env["sig"] == case["sig"]
    assert env["signed"] == case["signed"]


@pytest.mark.parametrize("case", VEC["strict_json"], ids=lambda c: c["name"])
def test_msgsig_strict_json(case):
    data = bytes.fromhex(case["hex"])
    if case["ok"]:
        assert isinstance(msgsig.read_strict_json(data), dict)
    else:
        with pytest.raises((ValueError, UnicodeDecodeError)):
            msgsig.read_strict_json(data)


def _outcome(fn) -> str:
    try:
        r = fn()
    except msgsig.SigError as e:
        return e.code
    return r if isinstance(r, str) else "ok"


@pytest.mark.parametrize("case", VEC["messages"], ids=lambda c: c["name"])
def test_msgsig_receiver(case):
    rx = case["receiver"]
    if rx is None:
        pytest.skip("relay only")
    got = _outcome(
        lambda: msgsig.receiver_check(
            case["envelope"],
            me=rx["me"],
            accepted={o: [bytes.fromhex(k) for k in ks] for o, ks in rx["accepted"].items()},
            now_ms=rx["now_ms"],
            seen={tuple(s) for s in rx["seen"]},
            groups=[tuple(g) for g in rx["groups"]],
        )
    )
    assert got == case["expect_receiver"], case["note"]


@pytest.mark.parametrize("case", VEC["messages"], ids=lambda c: c["name"])
def test_msgsig_relay_gate(case):
    r = case["relay"]
    if r is None:
        pytest.skip("receiver only")
    got = _outcome(
        lambda: msgsig.relay_check(
            case["envelope"],
            caller=r["caller"],
            registered=[bytes.fromhex(k) for k in r["registered"]],
            seen=r["seen"],
        )[0]
    )
    assert got == case["expect_relay"], case["note"]


def test_msgsig_wycheproof():
    wrong = []
    for t in VEC["wycheproof"]["cases"]:
        got = msgsig.verify_raw(bytes.fromhex(t["pk"]), bytes.fromhex(t["msg"]), bytes.fromhex(t["sig"]))
        if t["expect"] != "either" and got is not t["expect"]:
            wrong.append((t["tcId"], t["flags"], t["expect"], got))
    assert not wrong, wrong
    assert VEC["wycheproof"]["count"] >= 200


def test_msgsig_the_phone_copy_is_the_same_file():
    phone = REPO / "mobile" / "OrchMobileTests" / "Fixtures" / "msgsig-v1.json"
    assert phone.read_bytes() == (REPO / "contracts" / "vectors" / "msgsig-v1.json").read_bytes()


def test_msgsig_every_case_family_is_there():
    names = [c["name"] for c in VEC["messages"]]
    for family in (
        "good_",
        "wrong_",
        "missing_",
        "changed_",
        "replayed",
        "redirected",
        "strict_",
        "field_",
        "envelope_",
    ):
        assert any(n.startswith(family) for n in names), family

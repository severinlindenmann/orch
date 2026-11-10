"""Every case of contracts/vectors/human-proof-v1.json against orch.humanproof (reference:
contracts/validate.py)."""

import base64
import json
from pathlib import Path

import pytest

from orch import humanproof as hp

VEC = json.loads((Path(__file__).resolve().parents[2] / "contracts/vectors/human-proof-v1.json").read_text())


def _ids(cases):
    return [c["name"] for c in cases]


def _verify(c, used=None):
    return hp.check_proof(
        c.get("proof"),
        key_hex=c.get("key"),
        op=c["op"],
        target=c["target"],
        now=c["now"],
        by_flag=c.get("by_flag"),
        agent_env=bool(c.get("agent_env")),
        used_nonces=c.get("used_nonces", []) if used is None else used,
        home_trusted=c.get("home_trusted") is not False,
        dev_record=bool(c.get("dev_record")),
        dev_key=c.get("dev_key"),
    )


@pytest.mark.parametrize("c", VEC["verify"], ids=_ids(VEC["verify"]))
def test_verify(c):
    assert _verify(c) == c["result"]


@pytest.mark.parametrize("c", VEC["concurrent"], ids=_ids(VEC["concurrent"]))
def test_concurrent(c):
    used, got = [], []
    for call in c["calls"]:
        r = _verify(call, list(used))
        if r == "ok":
            part = call["proof"].split(".")[1]
            used.append(json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["nonce"])
        got.append(r)
    assert got == c["results"]


@pytest.mark.parametrize("c", VEC["settle"], ids=_ids(VEC["settle"]))
def test_settle(c):
    assert hp.settle(c["setting"], c["events"]) == c["effective"]


def test_setting_defaults_match_vectors():
    assert set(hp.SETTING_DEFAULTS) == set(VEC["settings"])


@pytest.mark.parametrize("c", VEC["pending"], ids=_ids(VEC["pending"]))
def test_pending(c):
    assert hp.pending_is_human(bytes.fromhex(c["key"]), c["workspace"], c["ticket"], c["line"]) is c["human"]


@pytest.mark.parametrize("c", VEC["deliver"], ids=_ids(VEC["deliver"]))
def test_deliver(c):
    assert hp.pending_deliver(c["line"], c["delivered_ids"]) is c["deliver"]


@pytest.mark.parametrize("c", VEC["wont_do"], ids=_ids(VEC["wont_do"]))
def test_wont_do(c):
    got = hp.wontdo_is_human(
        bytes.fromhex(c["key"]),
        c["workspace"],
        c["ticket"],
        c["decision"],
        c["mac"],
        c["relay_authenticated_sender"],
    )
    assert got is c["human"]


@pytest.mark.parametrize("c", VEC["home"], ids=_ids(VEC["home"]))
def test_home(c):
    got = hp.home_ok(
        c["account_home"], c["install"], c["prefix_real_dir"], c["workspace_realpath"], c["home_realpath"]
    )
    assert got is c["ok"]


@pytest.mark.parametrize("c", VEC["dev_mark"], ids=_ids(VEC["dev_mark"]))
def test_dev_mark(c):
    assert hp.dev_can_mark(c["install_dev"], c["creating"], c["has_human_key"]) is c["ok"]

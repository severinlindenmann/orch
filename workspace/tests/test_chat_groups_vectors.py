"""The contract vectors (contracts/vectors/chat-groups/) through the receiver code of the workspace
(orch.chat_groups): valid ones are accepted, invalid ones are refused. Pure rules: no disk, no network."""

import json

import pytest
from conftest import CONTRACTS

from orch import chat_groups as cg

VECTORS = sorted((CONTRACTS / "vectors" / "chat-groups").glob("*.json"))


def errors(case):
    m, ctx = case["message"], case.get("context") or {}
    return cg.message_errors(m, ctx) + cg.receive_errors(m, ctx)


@pytest.mark.parametrize("f", VECTORS, ids=lambda f: f.stem)
def test_vector(f):
    case = json.loads(f.read_text())
    errs = errors(case)
    if f.name.startswith("valid-"):
        assert errs == []
    else:
        assert errs, f"{f.name} should be refused"
    exp = (case.get("expect") or {}) if f.name.startswith("valid-") else {}
    m, ctx = case["message"], case.get("context") or {}
    if "group_text" in exp:
        assert cg.phone_joins_group(m, ctx) is exp["group_text"]
    if "shown_as" in exp:
        assert cg.shown_as(m, ctx) == exp["shown_as"]
    if "order" in exp:
        assert cg.order_step(m, ctx) == exp["order"]
    if "applied_after" in exp:
        assert cg.applied_after(m, ctx) == exp["applied_after"]
    if "stored_as" in exp:
        assert cg.store_key(m, ctx) == (exp["stored_as"], exp.get("store", "new"))
    if "card" in exp:
        assert cg.card_kind(m["body"]) == exp["card"]
    for ans, want in (exp.get("parse") or {}).items():
        assert cg.parse_allow_answer(ans) == want
    if "map" in exp:
        mp = exp["map"]
        assert cg.ALLOW_MAP[cg.parse_allow_answer(mp["answer"])] == {
            k: v for k, v in mp.items() if k != "answer"
        }
        ge = m["body"].get("group_event") or {}
        if ge.get("kind") == "approved":
            assert ge.get("mode") == mp["approved_mode"]


def test_there_are_vectors():
    assert len(VECTORS) >= 20
    assert any(f.name.startswith("invalid-") for f in VECTORS)


def test_fanout_id_shape_and_stability():
    a = cg.fanout_id("ws_fin0000001", "m_homeanswer000000", "ws_ban0000001")
    assert a == cg.fanout_id("ws_fin0000001", "m_homeanswer000000", "ws_ban0000001")
    assert a != cg.fanout_id("ws_fin0000001", "m_homeanswer000000", "phones")
    assert a != cg.fanout_id("ws_other00001", "m_homeanswer000000", "ws_ban0000001")
    assert len(a) == 18 and a.startswith("m_")

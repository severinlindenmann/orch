"""The contract vectors (contracts/vectors/chat-groups/) through the receiver code of the workspace
(orch.chat_groups): valid ones are accepted, invalid ones are refused. Pure rules: no disk, no network."""

import json

import pytest
from conftest import CONTRACTS

from orch import chat_groups as cg

VECTORS = sorted((CONTRACTS / "vectors" / "chat-groups").glob("*.json"))


def errors(case):
    m, ctx = case["message"], case.get("context") or {}
    return cg.message_errors(m) + cg.receive_errors(m, ctx)


@pytest.mark.parametrize("f", VECTORS, ids=lambda f: f.stem)
def test_vector(f):
    case = json.loads(f.read_text())
    errs = errors(case)
    if f.name.startswith("valid-"):
        assert errs == []
    else:
        assert errs, f"{f.name} should be refused"
    exp = case.get("expect") or {}
    if "group_text" in exp:
        assert cg.phone_joins_group(case["message"], case.get("context") or {}) is exp["group_text"]


def test_there_are_vectors():
    assert len(VECTORS) >= 20
    assert any(f.name.startswith("invalid-") for f in VECTORS)


def test_fanout_id_shape_and_stability():
    a = cg.fanout_id("ws_fin0000001", "m_homeanswer000000", "ws_ban0000001")
    assert a == cg.fanout_id("ws_fin0000001", "m_homeanswer000000", "ws_ban0000001")
    assert a != cg.fanout_id("ws_fin0000001", "m_homeanswer000000", "phones")
    assert a != cg.fanout_id("ws_other00001", "m_homeanswer000000", "ws_ban0000001")
    assert len(a) == 18 and a.startswith("m_")

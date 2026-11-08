from orch_focus.server import agent_label
from orch_focus.view import _item


def test_agent_label():
    agents = [{"name": "claude", "label": "Claude", "chosen": True}]
    for claim in (None, {}, {"agent": "claude"}, {"label": "claude"}):
        assert agent_label(claim, agents) == "Claude"
    assert agent_label({"label": "Studio", "agent": "claude"}, agents) == "Studio"
    assert agent_label({"agent": "codex"}, agents) == "Codex"
    assert agent_label({}, [{"name": "custom", "label": "Studio"}]) == "Studio"
    assert agent_label({}, []) == "Agent"
    assert _item({"ticket": "t_test"}, None, False, agents)["subtitle"].startswith("Claude")

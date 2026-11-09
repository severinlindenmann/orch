"""The adapter split preserves the original data and defines fragment precedence."""

import json
from pathlib import Path

import pytest

from orch import agentsdata


def test_golden_and_package():
    golden = Path(__file__).with_name("fixtures") / "agents.golden.json"
    assert agentsdata.load() == json.loads(golden.read_bytes())
    assert {p.name for p in agentsdata.agents_dir().iterdir()} == {
        "base.json",
        "deny.json",
        "capabilities.json",
        "connections.json",
        "readonly.json",
    }


@pytest.fixture
def data(tmp_path):
    (tmp_path / "base.json").write_text(
        json.dumps({"adapters": {"example": {"nested": {"a": 1}, "list": [1]}}})
    )
    for name in agentsdata.FRAGMENTS:
        (tmp_path / f"{name}.json").write_text("{}")
    return tmp_path


def test_merge(data):
    for i, name in enumerate(agentsdata.FRAGMENTS):
        fragment = {"adapters": {"example": {"nested": {name: i}, "list": [i], "scalar": i}}}
        (data / f"{name}.json").write_text(json.dumps(fragment))
    adapter = agentsdata.load(data)["adapters"]["example"]
    assert adapter["nested"] == {"a": 1, "deny": 0, "capabilities": 1, "connections": 2, "readonly": 3}
    assert adapter["list"] == [3]
    assert adapter["scalar"] == 3


@pytest.mark.parametrize("fragment", [[], None, 1, {"adapters": {"new": {}}}, {"adapters": []}])
def test_invalid_fragment(data, fragment):
    (data / "deny.json").write_text(json.dumps(fragment))
    with pytest.raises(RuntimeError):
        agentsdata.load(data)

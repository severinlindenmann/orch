"""The adapter split preserves the original data and defines fragment precedence."""

import json

import pytest

from orch import agentsdata


def test_empty_fragments_give_exactly_base_and_package_has_all_parts():
    base = json.loads((agentsdata.agents_dir() / "base.json").read_bytes())
    filled = {"capabilities"}  # filled by W2b 1.9 (capability flags); the others stay empty until their slice
    for name in agentsdata.FRAGMENTS:
        part = json.loads((agentsdata.agents_dir() / f"{name}.json").read_bytes())
        assert (part != {}) if name in filled else (part == {})
    merged = agentsdata.load()
    assert {k: v for k, v in merged.items() if k != "adapters"} == {
        k: v for k, v in base.items() if k != "adapters"
    }
    assert merged["adapters"].keys() == base["adapters"].keys()
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

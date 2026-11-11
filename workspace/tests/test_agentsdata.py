"""The adapter split preserves the original data and defines fragment precedence."""

import json

import pytest

from orch import agentsdata


def test_empty_fragments_give_exactly_base_and_package_has_all_parts():
    base = json.loads((agentsdata.agents_dir() / "base.json").read_bytes())
    for name in agentsdata.FRAGMENTS:
        if name == "reminder":  # B9: the work-check hooks (not empty)
            continue
        got = json.loads((agentsdata.agents_dir() / f"{name}.json").read_bytes())
        if name == "connections":  # W2b 1.10: only the settings locations (inventory.md)
            assert {a: set(v) for a, v in got["adapters"].items()} == {
                "claude": {"mcp_settings"},
                "codex": {"mcp_settings"},
            }
        elif name == "capabilities":  # W2b 1.8: what the record can learn from the tool's stream
            assert got == {
                "adapters": {
                    "claude": {
                        "capabilities": {"activity": "live"},
                        "oneshot": {"events": "claude-stream-json/1"},
                    }
                }
            }
        elif name == "deny":  # W2b 1.4: how each adapter is told the deny rules (secrets.md, Deny rules)
            assert {a: v["deny"]["format"] for a, v in got["adapters"].items()} == {
                "claude": "patterns/1",
                "codex": "none",
                "generic": "none",
            }
        else:
            assert got == {}
    merged = agentsdata.load()
    rem = json.loads((agentsdata.agents_dir() / "reminder.json").read_bytes())["adapters"]["claude"]
    assert merged["adapters"]["claude"]["reminder_hooks"] == rem["reminder_hooks"]
    assert merged["adapters"]["claude"]["oneshot"]["settings_args"] == rem["oneshot"]["settings_args"]
    for adapter in merged["adapters"].values():
        adapter.pop("mcp_settings", None)
        adapter.pop("deny", None)
    for key in ("reminder_hooks", "reminder"):
        merged["adapters"]["claude"].pop(key)
    merged["adapters"]["claude"]["oneshot"].pop("settings_args")
    merged["adapters"]["claude"]["oneshot"].pop("events")
    merged["adapters"]["claude"]["capabilities"].pop("activity")
    assert merged == base
    assert {p.name for p in agentsdata.agents_dir().iterdir()} == {
        "base.json",
        "deny.json",
        "capabilities.json",
        "connections.json",
        "readonly.json",
        "reminder.json",
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
    last = len(agentsdata.FRAGMENTS) - 1
    assert adapter["nested"] == {"a": 1, **{n: i for i, n in enumerate(agentsdata.FRAGMENTS)}}
    assert adapter["list"] == [last]
    assert adapter["scalar"] == last


@pytest.mark.parametrize("fragment", [[], None, 1, {"adapters": {"new": {}}}, {"adapters": []}])
def test_invalid_fragment(data, fragment):
    (data / "deny.json").write_text(json.dumps(fragment))
    with pytest.raises(RuntimeError):
        agentsdata.load(data)

import copy
import json
import re
from pathlib import Path

import pytest
from conftest import CONTRACTS

from orch import addons, conn_config, inventory

VEC = json.loads((CONTRACTS / "vectors" / "inventory-v1.json").read_text(encoding="utf-8"))
WID = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def env(tmp_path, monkeypatch):
    account = tmp_path / "account"
    orch_home = account / "orch-home"
    root = account / "ws"
    (root / ".orch").mkdir(parents=True)
    orch_home.mkdir()
    (root / ".orch" / ".local-id").write_text(WID + "\n")
    monkeypatch.setattr(addons, "real_home", lambda: account)
    monkeypatch.setenv("ORCH_HOME", str(orch_home))
    return root, account, orch_home


def _w(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def _mcp(root, servers, allow=None):
    doc = {"schema": "orch.mcp/1", "servers": servers}
    if allow is not None:
        doc["allow"] = allow
    _w(root / ".orch" / "mcp.json", doc)


@pytest.mark.parametrize(
    "c", [c for c in VEC["precedence"] if c["kind"] == "connection"], ids=lambda c: c["name"]
)
def test_vector_precedence(c):
    winners, shadowed = conn_config.resolve(c["entries"])
    assert {i["name"]: i["source"] for i in winners} == c["winners"]
    assert len(winners) + len(shadowed) == len(c["entries"])
    assert all(i["shadowed_by"] == c["winners"][i["name"]] for i in shadowed)
    assert inventory.winners(c["entries"]) == c["winners"]


@pytest.mark.parametrize("c", VEC["allowed"], ids=lambda c: c["name"])
def test_vector_allowed(env, c):
    root, account, orch_home = env
    _mcp(root, {"s": {"command": ["srv"], "actions": c["actions"]}}, {"s": c["file"]})
    calls = []

    def grants(r, h):
        calls.append((r, h))
        return {"s": c["grant"]} if c["grant"] is not None else {}

    result = conn_config.effective(root, orch_home=orch_home, account_home=account, grants=grants)
    item = result["connections"][0]
    assert calls == [(root, orch_home)]
    assert item["allowed_actions"] == c["allowed"]
    assert item["allow_all"] == (c["file"] == c["grant"] == "*")
    assert inventory.allowed(c["file"], c["grant"], c["actions"]) == c["allowed"]


def test_precedence_and_fields(env):
    root, account, orch_home = env
    _mcp(root, {"shared": {"command": ["/bin/mine", "arg"], "label": "Shared"}})
    _w(
        orch_home / "keys" / WID / "connections.json",
        {
            "mcpServers": {
                "shared": {"command": ["admin"]},
                "admin-only": {"url": "https://a.example/path"},
            }
        },
    )
    _w(
        account / ".claude.json",
        {
            "mcpServers": {
                "shared": {"command": "harness"},
                "admin-only": {"command": "other"},
                "solo": {"command": "solo"},
            }
        },
    )
    result = conn_config.effective(root)
    assert result["schema"] == "orch.conn-config/1"
    assert [(i["name"], i["source"]) for i in result["connections"]] == [
        ("admin-only", "admin"),
        ("shared", "workspace"),
        ("solo", "harness"),
    ]
    assert [i["also_from"] for i in result["connections"]] == [["harness"], ["admin", "harness"], []]
    assert [(i["name"], i["source"], i["shadowed_by"]) for i in result["shadowed"]] == [
        ("admin-only", "harness", "admin"),
        ("shared", "admin", "workspace"),
        ("shared", "harness", "workspace"),
    ]
    fields = {
        "name",
        "source",
        "transport",
        "command",
        "host",
        "profile",
        "version",
        "allowed_actions",
        "allow_all",
        "state",
        "recipe_ref",
    }
    for group, extra in (("connections", "also_from"), ("shadowed", "shadowed_by")):
        for item in result[group]:
            assert set(item) == fields | {extra} | ({"label"} if item["source"] == "workspace" else set())
            assert item["recipe_ref"] == f"{item['source']}/{item['name']}@{item['version'][7:23]}"
            assert re.fullmatch(r"[a-z]+/[a-z-]+@[0-9a-f]{16}", item["recipe_ref"])
    assert result["connections"][1]["command"] == "mine"
    assert result["connections"][1]["label"] == "Shared"
    assert result["connections"][0]["host"] == "a.example"


def test_no_grants_and_intersection(env):
    root, _, orch_home = env
    _mcp(root, {"s": {"command": ["srv"]}}, {"s": ["write", "read"]})
    assert conn_config.effective(root)["connections"][0]["allowed_actions"] == []
    _w(orch_home / "human-settings.json", {"workspaces": {WID: {"conn.allow.s": {"value": "*"}}}})
    assert conn_config.effective(root)["connections"][0]["allowed_actions"] == []
    assert not conn_config.effective(root)["connections"][0]["allow_all"]
    result = conn_config.effective(root, grants=lambda r, h: {"s": ["read", "delete"]})
    assert result["connections"][0]["allowed_actions"] == ["read"]
    assert not result["connections"][0]["allow_all"]
    assert conn_config.no_grants(root, orch_home) == {}


def test_unknown_source_and_pure_resolve():
    items = [{"name": "s", "source": s} for s in ("harness", "admin", "unproven")]
    before = copy.deepcopy(items)
    winners, shadowed = conn_config.resolve(items)
    assert winners == [{"name": "s", "source": "workspace"}]
    assert shadowed == [{"name": "s", "source": s, "shadowed_by": "workspace"} for s in ("admin", "harness")]
    assert inventory.winners(items) == {"s": "workspace"}
    assert items == before


def test_inventory_unknown_source_sort(env, monkeypatch):
    root, _, _ = env
    _mcp(root, {"s": {"command": ["srv"]}})
    original = inventory._entry

    def unknown(*args):
        return {**original(*args), "source": "unproven"}

    monkeypatch.setattr(inventory, "_entry", unknown)
    assert inventory.connections(root)[0][0]["source"] == "workspace"


def test_no_leaks_all_sources(env):
    root, account, orch_home = env
    secrets = []
    sources = {}
    for source in ("workspace", "admin", "harness"):
        env_value, header, arg, path, query, password = [
            f"SECRET-{source}-{k}" for k in ("env", "header", "arg", "path", "query", "password")
        ]
        secrets.extend((env_value, header, arg, path, query, password))
        common = {"env": {"TOKEN": env_value}, "headers": {"Authorization": header}}
        sources[source] = {
            "stdio": {**common, "command": [f"/opt/{password}/srv", arg], "args": [arg]},
            "http": {**common, "url": f"https://user:{password}@api.example/{path}?token={query}"},
        }
    _mcp(root, sources["workspace"])
    _w(orch_home / "keys" / WID / "connections.json", {"mcpServers": sources["admin"]})
    _w(account / ".claude.json", {"mcpServers": sources["harness"]})
    result = conn_config.effective(root)
    assert len(result["connections"]) == 2
    assert len(result["shadowed"]) == 4
    for render in (json.dumps, repr, str):
        out = render(result)
        assert all(secret not in out for secret in secrets)
        assert "user:" not in out
    for item in result["connections"] + result["shadowed"]:
        assert (item["command"], item["host"]) == (
            ("srv", None) if item["name"] == "stdio" else (None, "api.example")
        )

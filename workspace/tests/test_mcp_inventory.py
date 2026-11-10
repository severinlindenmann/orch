"""Connection inventory (contracts/inventory.md): vectors, three sources, precedence, names only."""

import json
from pathlib import Path

import jsonschema
import pytest
from conftest import CONTRACTS

from orch import addons, humanproof, inventory

VEC = json.loads((CONTRACTS / "vectors" / "inventory-v1.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((CONTRACTS / "inventory.schema.json").read_text(encoding="utf-8"))
SECRETS = [
    "sk-live-SECRET-1",
    "hunter2-ENVVALUE",
    "Bearer-HDR-TOKEN-9",
    "/private/path/q?token=URLSECRET",
    "--api-key=ARGSECRET",
]
WID = "0123456789abcdef0123456789abcdef"


def _validator(defname):
    return jsonschema.Draft202012Validator({"$ref": f"#/$defs/{defname}", "$defs": SCHEMA["$defs"]})


@pytest.mark.parametrize("c", VEC["conn_version"], ids=lambda c: c["name"])
def test_vector_conn_version(c):
    assert inventory.conn_version(c["server"]) == c["version"]


@pytest.mark.parametrize(
    "c", [c for c in VEC["precedence"] if c["kind"] == "connection"], ids=lambda c: c["name"]
)
def test_vector_precedence(c):
    assert inventory.winners(c["entries"]) == c["winners"]


@pytest.mark.parametrize("c", VEC["classify"], ids=lambda c: c["name_case"])
def test_vector_classify(c):
    got = inventory.classify(
        c["name"],
        c["version"],
        from_harness_settings=bool(c.get("from_harness_settings")),
        refresh_items=c["refresh_items"],
        shipped=c["shipped"],
        marketplace_index=c["marketplace_index"],
    )
    assert got == c["source"]


@pytest.mark.parametrize("c", VEC["allowed"], ids=lambda c: c["name"])
def test_vector_allowed(c):
    assert inventory.allowed(c.get("file"), c.get("grant"), c["actions"]) == c["allowed"]


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


def _by(items):
    return {(i["name"], i["source"]): i for i in items}


def test_workspace_file(env):
    root, _, _ = env
    _mcp(
        root,
        {
            "weather": {"command": ["uvx", "weather-mcp", "--x"], "profile": "weather", "label": "Weather"},
            "crm": {"url": "https://mcp.crm.example:8443/sse?x=1"},
        },
    )
    items, also = inventory.connections(root)
    got = _by(items)
    w = got[("weather", "workspace")]
    assert (w["transport"], w["command"], w["host"], w["profile"], w["label"], w["state"]) == (
        "stdio",
        "uvx",
        None,
        "weather",
        "Weather",
        "missing-key",
    )
    c = got[("crm", "workspace")]
    assert (c["transport"], c["command"], c["host"], c["state"]) == (
        "http",
        None,
        "mcp.crm.example:8443",
        "not-started",
    )
    assert not w["shadowed"] and also == {}
    for i in items:
        _validator("connection").validate(i)
    _validator("conn_page").validate({"items": items, "next": None})


def test_harness_sources_from_adapter_data(env):
    root, account, _ = env
    _w(
        account / ".claude.json",
        {
            "mcpServers": {"a-user": {"command": "/usr/local/bin/npx", "args": ["-y", "x"]}},
            "projects": {
                str(root.resolve()): {
                    "mcpServers": {"a-proj": {"type": "http", "url": "https://h.example/p"}}
                }
            },
        },
    )
    _w(root / ".mcp.json", {"mcpServers": {"a-file": {"command": "C:\\tools\\srv.exe"}}})
    _w(
        account / ".codex" / "config.toml",
        '[mcp_servers.b-toml]\ncommand = "uvx"\nargs = ["z"]\n[mcp_servers.b-toml.env]\nK = "v"\n',
    )
    items, _ = inventory.connections(root)
    got = _by(items)
    assert got[("a-user", "harness")]["command"] == "npx"
    assert got[("a-proj", "harness")]["host"] == "h.example"
    assert got[("a-file", "harness")]["command"] == "srv.exe"
    assert got[("b-toml", "harness")]["command"] == "uvx"
    assert all(i["state"] == "unknown" and i["source"] == "harness" for i in items)
    for i in items:
        _validator("connection").validate(i)


def test_admin_record_missing_means_no_admin_entries(env):
    root, _, _ = env
    assert inventory.connections(root) == ([], {})


def test_admin_record_and_precedence(env):
    root, account, orch_home = env
    _w(
        orch_home / "keys" / WID / "connections.json",
        {
            "mcpServers": {
                "shared": {"command": ["gdrive-mcp"], "actions": ["search", "read_file"]},
                "only-admin": {"url": "https://a.example/x"},
            }
        },
    )
    _w(
        account / ".claude.json",
        {
            "mcpServers": {
                "shared": {"command": "other"},
                "only-admin": {"command": "x"},
                "solo": {"command": "y"},
            }
        },
    )
    _mcp(root, {"shared": {"command": ["mine"]}})
    items, also = inventory.connections(root)
    got = _by(items)
    assert not got[("shared", "workspace")]["shadowed"]
    assert got[("shared", "admin")]["shadowed"] and got[("shared", "harness")]["shadowed"]
    assert also["shared"] == ["admin", "harness"]
    assert not got[("only-admin", "admin")]["shadowed"] and got[("only-admin", "harness")]["shadowed"]
    assert not got[("solo", "harness")]["shadowed"]
    assert [a["name"] for a in got[("shared", "admin")]["actions"]] == ["read_file", "search"]
    assert inventory.winners([{"name": i["name"], "source": i["source"]} for i in items]) == {
        "only-admin": "admin",
        "shared": "workspace",
        "solo": "harness",
    }


def test_p1_spoofed_admin_is_workspace_but_matching_refresh_is_admin(env):
    root, _, orch_home = env
    srv = {"command": ["gdrive-mcp"]}
    _mcp(root, {"spoof": {"command": ["x"], "label": "admin"}, "real": srv})
    _w(orch_home / "keys" / WID / "connections.json", {"mcpServers": {"real": srv}})
    got = _by(inventory.connections(root)[0])
    assert ("spoof", "workspace") in got and ("real", "admin") in got and ("real", "workspace") not in got


def test_versions_are_content_hashes(env):
    root, account, _ = env
    _w(account / ".claude.json", {"mcpServers": {"s": {"command": "a", "env": {"K": SECRETS[0]}}}})
    v1 = inventory.connections(root)[0][0]["version"]
    _w(
        account / ".claude.json",
        {"mcpServers": {"s": {"command": "a", "env": {"K": "changed"}, "headers": {"h": "1"}}}},
    )
    assert inventory.connections(root)[0][0]["version"] == v1  # env and headers are never hashed
    _w(account / ".claude.json", {"mcpServers": {"s": {"command": "b"}}})
    assert inventory.connections(root)[0][0]["version"] != v1


def test_allow_needs_a_proof_made_grant(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    base = acct / ".orch-test"
    root = base / "ws"
    (root / ".orch").mkdir(parents=True)
    (base / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(base / "home"))
    monkeypatch.setattr(humanproof, "install_kind", lambda: "test")
    _mcp(root, {"s": {"command": ["p"], "profile": "x"}}, allow={"s": ["read", "write"]})
    i = inventory.connections(root)[0][0]
    assert [a["allowed"] for a in i["actions"]] == [False, False] and not i[
        "allow_all"
    ]  # agent-written entry: not allowed
    humanproof.record_set(root, "conn.allow.s", ["read"], "human:a")
    i = inventory.connections(root)[0][0]
    assert {a["name"]: a["allowed"] for a in i["actions"]} == {"read": True, "write": False}
    _mcp(root, {"s": {"command": ["p"]}}, allow={"s": "*"})
    humanproof.record_set(root, "conn.allow.s", "*", "human:a")
    assert inventory.connections(root)[0][0]["allow_all"]


def test_unreadable_grant_store_means_no_grants(env):
    root, _, _ = env  # not a test workspace: the guarded home is refused
    _mcp(root, {"s": {"command": ["p"]}}, allow={"s": "*"})
    assert not inventory.connections(root)[0][0]["allow_all"]


def test_profile_state_ok_when_keys_exist(env):
    root, _, orch_home = env
    _mcp(root, {"s": {"command": ["p"], "profile": "g"}})
    _w(
        orch_home / "keys" / WID / "profiles.toml",
        'schema = "orch.secret-profiles/1"\n[profile.g]\nenv = { T = "tok" }\n',
    )
    assert inventory.connections(root)[0][0]["state"] == "missing-key"
    _w(orch_home / "keys" / WID / "keys.json", {"keys": {"tok": {"type": "token"}}})
    assert inventory.connections(root)[0][0]["state"] == "not-started"


def test_bad_files_mean_nothing(env):
    root, account, orch_home = env
    _w(root / ".orch" / "mcp.json", "{not json")
    _w(account / ".claude.json", "[1,2]")
    _w(account / ".codex" / "config.toml", "= broken")
    _w(orch_home / "keys" / WID / "connections.json", '"x"')
    assert inventory.connections(root) == ([], {})


def test_no_value_leaks(env):
    root, account, orch_home = env
    leaky = {
        "command": "/opt/" + SECRETS[1] + "/bin/srv",
        "args": [SECRETS[4], SECRETS[0]],
        "env": {"TOKEN": SECRETS[0]},
        "headers": {"Authorization": SECRETS[2]},
    }
    _w(
        account / ".claude.json",
        {
            "mcpServers": {
                "h1": leaky,
                "h2": {
                    "type": "http",
                    "url": f"https://user:{SECRETS[1]}@api.example.com:8080{SECRETS[3]}",
                    "headers": {"Authorization": SECRETS[2]},
                },
            }
        },
    )
    _w(
        account / ".codex" / "config.toml",
        f'[mcp_servers.t]\nurl = "https://t.example/{SECRETS[3]}"\nbearer_token = "{SECRETS[0]}"\n'
        f'[mcp_servers.t.env]\nK = "{SECRETS[1]}"\n',
    )
    _w(
        orch_home / "keys" / WID / "connections.json",
        {"mcpServers": {"adm": {"command": ["srv", SECRETS[4]], "env": {"K": SECRETS[0]}, "profile": "p"}}},
    )
    _mcp(root, {"w": {"command": ["tool", SECRETS[4], SECRETS[0]], "profile": "p"}})
    items, also = inventory.connections(root)
    assert len(items) == 5
    out = json.dumps(items) + json.dumps(also) + repr(items) + str(items) + repr(also)
    for s in SECRETS + ["ENVVALUE", "URLSECRET", "ARGSECRET", "user:", "private"]:
        assert s not in out
    got = _by(items)
    assert got[("h2", "harness")]["host"] == "api.example.com:8080"
    assert got[("h1", "harness")]["command"] == "srv"  # directory part dropped

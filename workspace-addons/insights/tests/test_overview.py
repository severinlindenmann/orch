"""T0 overview contract, projection, privacy, and fenced HTTP checks."""

import copy
import hashlib
import hmac
import http.client
import json
import os
import re
import subprocess
import sys
import tomllib
from importlib import resources
from pathlib import Path

import jsonschema
import pytest

from orch_insights.lists import build_list
from orch_insights.overview import ERROR, PARTIAL, build_overview
from orch_insights.server import read_counts

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
PACKAGE = resources.files("orch_insights")


def request(server, path="/api/overview", method="GET", headers=None):
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    base = {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}"}
    conn.request(method, path, headers={**base, **(headers or {})})
    response = conn.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    conn.close()
    return result


def set_answer(fake, answer):
    (fake.parent / "answer.json").write_text(json.dumps(answer))


def item(answer, **changes):
    result = copy.deepcopy(answer["items"][0])
    result.update(changes)
    return result


def all_rows(answer):
    # 2.10: the rows moved from the overview to the lists (/api/list/<tab>); the overview keeps counts.
    return [row for tab in ("skills", "connections", "keys") for row in build_list(answer, tab)["rows"]]


def test_manifest_and_packaged_assets():
    manifest = tomllib.loads(PACKAGE.joinpath("orch-addon.toml").read_text())
    assert manifest["name"] == "insights"
    assert manifest["version"] == "0.1.0"
    assert manifest["run"] == "orch_insights"
    assert manifest["background"] is True
    assert manifest["dashboard"] == {"label": "Insights", "icon": "chart", "order": 30}
    assert not {"runs_agents", "ticket_ext"} & manifest.keys()
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert project["project"]["entry-points"]["orch.addons"] == {"insights": "orch_insights"}
    for name in ("index.html", "insights.css", "insights.js"):
        assert PACKAGE.joinpath("web", name).is_file()


def test_manifest_contract():
    manifest = tomllib.loads(PACKAGE.joinpath("orch-addon.toml").read_text())
    schema = json.loads((CONTRACTS / "addon-manifest.schema.json").read_text())
    jsonschema.validate(manifest, schema)


def test_example_denominators_inventory_and_privacy(answer):
    view = build_overview(answer)
    assert {tab: value["count"] for tab, value in view["tabs"].items()} == {
        "skills": 3,
        "connections": 3,
        "keys": 2,
    }
    row = build_list(answer, "skills")["rows"][0]
    assert row["name"] == "Invoice export"
    assert row["numbers"] == "5 of 23 runs"
    assert row["unseen"] == "4 runs can't tell"
    assert row["label"] == "Working well"
    connections = build_list(answer, "connections")["rows"]
    assert any(row["name"] == "Google Drive" for row in connections)
    assert any(row["name"] == "google-sa.json" for row in build_list(answer, "keys")["rows"])
    for word in ("MCP", "NetBird", "VPN", "sha256"):
        assert word not in json.dumps(view)


@pytest.mark.parametrize(
    "case", json.loads((CONTRACTS / "vectors/counts-v1.json").read_text())["denominators"]
)
def test_contract_vectors(case, nothing):
    answer = copy.deepcopy(nothing)
    answer["runs"] = len(case["runs"])
    answer["tickets"] = len({run["ticket"] for run in case["runs"]})
    answer["items"] = [
        {"action": None, "first_seen": None, "last_seen": None, "versions": [], **entry}
        for entry in case["items"]
    ]
    # Vector inventory entries have no package metadata: existing matching items already carry their counts.
    answer["inventory"] = {**answer["inventory"], "skills": [], "connections": [], "keys": []}
    for entry in case["inventory"]:
        tab = {"skill": "skills", "mcp": "connections", "key": "keys"}[entry["kind"]]
        template = next(x for x in nothing["inventory"][tab] if x["source"] == entry["source"])
        answer["inventory"][tab].append({**template, "name": entry["name"]})
    view = build_overview(answer)
    assert "error" not in view
    for entry in case["items"]:
        if entry["kind"] == "tool":
            continue
        tab = {"skill": "skills", "mcp": "connections", "key": "keys"}[entry["kind"]]
        rows = build_list(answer, tab)["rows"]
        expected_name = (
            entry["name"] if entry["kind"] == "key" else entry["name"].replace("-", " ").capitalize()
        )
        row = next(x for x in rows if x["name"] == expected_name)
        if entry["seen"] == "unknown":
            assert row["uses"] is None and row["numbers"] == "Can't tell yet"
            assert row["label"] == "Can't tell yet"
        else:
            assert row["numbers"] == f"{entry['runs']['used']} of {entry['runs']['of']} runs"
        if entry["runs"]["unseen"] == 1:
            assert row["unseen"] == "1 run can't tell"


def test_all_health_labels_and_sorting(answer):
    answer["items"] = [
        item(answer, name="working"),
        item(answer, name="failing", uses=5, ok=3, failed=2),
        item(answer, name="idle", uses=0, ok=0, failed=0, seen="not_seen"),
        item(answer, name="recent", first_seen="2026-11-15T00:00:00Z"),
        item(answer, name="uncertain", uses=0, ok=0, failed=0, seen="unknown"),
    ]
    view = build_list(answer, "skills")
    rows = {row["name"]: row for row in view["rows"]}
    assert rows["Working"]["label"] == "Working well"
    assert rows["Failing"]["label"] == "Needs a look"
    assert rows["Idle"]["label"] == "Not used"
    assert rows["Idle"]["detail"] == "Not used in 30 days"
    assert rows["Recent"]["label"] == "New"
    assert rows["Uncertain"]["label"] == "Can't tell yet"
    assert rows["Uncertain"]["uses"] is None
    assert "0" not in rows["Uncertain"]["numbers"]
    assert view["rows"][0]["name"] == "Failing"


@pytest.mark.parametrize(
    "uses,failed,refused,kind,expected",
    [
        (2, 1, 0, "skill", "working"),
        (5, 1, 0, "skill", "look"),
        (6, 1, 0, "skill", "working"),
        (1, 0, 1, "key", "look"),
        (1, 0, 1, "mcp", "look"),
    ],
)
def test_health_thresholds(answer, uses, failed, refused, kind, expected):
    answer["items"] = [
        item(answer, kind=kind, uses=uses, failed=failed, refused=refused, ok=uses - failed - refused)
    ]
    row = next(row for row in all_rows(answer) if row["uses"] == uses)
    assert row["health"] == expected


def test_inventory_dedup_and_hidden_kinds(answer):
    original, original_rows = build_overview(answer), all_rows(answer)
    answer["items"] += [item(answer, kind=kind, name=f"hidden-{kind}") for kind in ("tool", "helper", "job")]
    answer["items"].append(copy.deepcopy(answer["items"][0]))
    result = build_overview(answer)
    assert result["tabs"] == original["tabs"]
    assert all_rows(answer) == original_rows
    assert "hidden-" not in json.dumps(result) + json.dumps(all_rows(answer))
    inventory_only = next(row for row in all_rows(answer) if row["name"] == "Google Drive")
    assert inventory_only["health"] == "unknown" and inventory_only["uses"] is None


def test_cards_order_limit_and_honest_units(answer):
    answer["items"] = [
        item(answer, kind="key", name="unused", seen="not_seen", uses=0, ok=0, failed=0),
        item(answer, kind="mcp", name="stripe", refused=3, failed=0, uses=3, ok=0),
        item(answer, name="bad", uses=5, ok=3, failed=2),
    ]
    cards = build_overview(answer)["needs"]
    assert [card["kind"] for card in cards] == ["skill", "connection", "key"]
    assert cards[0]["text"] == "2 of 5 uses failed; 0 refused."
    assert cards[1]["title"] == 'Stripe said "not allowed" 3 times'
    assert cards[2]["title"] == "1 key not used in 30 days"
    assert all(card["button"] == "Look" for card in cards)
    answer["items"].append({**answer["items"][2], "name": "also-bad", "uses": 5, "ok": 0, "failed": 5})
    cards = build_overview(answer)["needs"]
    assert len(cards) == 3
    assert [card["kind"] for card in cards] == ["skill", "skill", "connection"]


def test_first_day_and_all_good(nothing, answer):
    assert build_overview(nothing)["first_day"] is True
    assert build_overview(nothing)["empty_needs"] == "All good this month."
    answer["items"] = [answer["items"][0]]
    view = build_overview(answer)
    assert view["needs"] == [] and view["empty_needs"] == "All good this month."
    assert view["first_day"] is False
    answer["runs"] = 0
    assert build_overview(answer)["first_day"] is False


@pytest.mark.parametrize("state", ["on", "off", "off_by_admin", "not_connected"])
def test_sharing(answer, state):
    answer["sharing"]["counts"] = state
    sharing = build_overview(answer)["sharing"]
    assert sharing["on"] is (state == "on")
    assert sharing["chip"] == ("Sharing counts with your admin" if state == "on" else None)


def test_incomplete_fails_closed(answer, server, fake_orch):
    answer["complete"] = False
    set_answer(fake_orch, answer)
    code, _, body = request(server)
    assert code == 200
    assert json.loads(body) == {"error": PARTIAL, "complete": False}
    assert "runs" not in json.loads(body)


@pytest.mark.parametrize("bad", [None, [], {}, {"schema": "orch.counts/1", "items": []}])
def test_bad_shapes(bad):
    assert build_overview(bad) == {"error": ERROR, "complete": False}


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "orch.counts/2"),
        ("runs", False),
        ("runs", -1),
        ("tickets", "0"),
        ("items", [None]),
        ("items", {}),
        ("inventory", []),
        ("sharing", None),
        ("generated_at", "yesterday"),
        ("generated_at", "yesterdayZ"),
        ("generated_at", "2026-99-99T00:00:00Z"),
        ("since", "yesterdayZ"),
        ("complete", "true"),
    ],
)
def test_schema_shaped_garbage(answer, field, value):
    answer[field] = value
    assert build_overview(answer)["error"] == ERROR


@pytest.mark.parametrize("mutation", ["exit", "json", "schema", "missing"])
def test_cli_failure(ws, fake_orch, answer, mutation, server):
    if mutation == "exit":
        (fake_orch.parent / "exit").touch()
    elif mutation == "json":
        (fake_orch.parent / "answer.json").write_text("not json")
    elif mutation == "schema":
        answer["schema"] = "wrong"
        set_answer(fake_orch, answer)
    else:
        fake_orch.unlink()
    assert build_overview(read_counts(ws, fake_orch)) == {"error": ERROR, "complete": False}
    code, _, body = request(server)
    assert code == 200 and json.loads(body) == {"error": ERROR, "complete": False}


def test_cli_arguments_and_environment(ws, fake_orch, monkeypatch):
    monkeypatch.setenv("ORCH_BIN", "/never/use/this")
    assert read_counts(ws, fake_orch)["schema"] == "orch.counts/1"
    call = json.loads((fake_orch.parent / "call.json").read_text())
    assert call == {
        "args": ["record", "counts", "--days", "30", "--json"],
        "cwd": str(ws),
        "root": str(ws),
        "stdin": "",
    }


def test_own_interpreter_and_timeout(ws, monkeypatch):
    def run(args, **kwargs):
        assert args == [
            sys.executable,
            "-I",
            "-P",
            "-m",
            "orch",
            "record",
            "counts",
            "--days",
            "30",
            "--json",
        ]
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 10
        assert kwargs["cwd"] == ws
        assert kwargs["env"]["ORCH_ROOT"] == str(ws)
        raise subprocess.TimeoutExpired(args, 10)

    monkeypatch.setenv("ORCH_BIN", "/never/use/this")
    monkeypatch.setattr(subprocess, "run", run)
    assert read_counts(ws) is None


def test_api_whitelists_fields(server, fake_orch, answer):
    answer["items"][2]["value"] = "s3cret"
    set_answer(fake_orch, answer)
    code, headers, body = request(server)
    assert code == 200 and headers["Content-Type"] == "application/json"
    view = json.loads(body)
    assert "error" not in view
    assert "stripe-key" in body.decode()
    for forbidden in ("s3cret", "sha256", "MCP", "NetBird", "VPN"):
        assert forbidden not in body.decode()
    assert not re.search(r"\b(?:ws_|t_|r_)[a-z0-9]{6,}", body.decode())
    assert not any(name.lower().startswith("access-control-") for name in headers)


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "UNKNOWN"])
def test_read_only(server, method):
    assert request(server, method=method)[0] == 405
    assert request(server, method=method, headers={"Host": "evil.example:8431"})[0] == 403


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:{port}",
        "evil.example:80",
        "127.0.0.1.evil.example:{port}",
        "localhost.evil.example:{port}",
        "[::1]:{port}",
        "0.0.0.0:{port}",
        "127.0.0.2:{port}",
        "localhost.:{port}",
        "127.0.0.1",
        "127.0.0.1:{port}@evil.example",
        "evil.example:{port}, 127.0.0.1:{port}",
        "",
    ],
)
def test_rebinding_host_refused_on_read_routes(server, fake_orch, host):
    """The read routes have no session (the page loads them before any exists): the Host check is the fence."""
    port = server.server_address[1]
    for path in ("/api/overview", "/api/list/skills", "/api/settings"):
        code, _, body = request(server, path, headers={"Host": host.format(port=port)})
        assert code == 403 and b"not allowed" in body
    assert not (fake_orch.parent / "calls.jsonl").exists()  # nothing was read


def test_fence_and_unknown_paths(server):
    assert request(server, headers={"Host": "evil.example:8431"})[0] == 403
    assert request(server, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert request(server, "/not-here")[0] == 404
    assert request(server, "/web/../orch-addon.toml")[0] == 404
    assert request(server, "/kit/../origin.py")[0] == 404


def test_assets_prefix_and_nonce(server, monkeypatch):
    code, _, body = request(server, "/", headers={"X-Forwarded-Prefix": "/addon/insights"})
    assert code == 200 and b'data-prefix="/addon/insights"' in body
    assert b"__P__" not in body
    assert b"/addon/insights/web/insights.js" in body
    assert b'data-prefix=""' in request(server, "/", headers={"X-Forwarded-Prefix": '"><script>'})[2]
    for path in (
        "/web/insights.css",
        "/web/insights.js",
        "/kit/tokens.css",
        "/kit/components.css",
        "/kit/icons.js",
    ):
        assert request(server, path)[0] == 200
    nonce, challenge = "a" * 32, "b" * 32
    monkeypatch.setenv("ORCH_INSIGHTS_NONCE", nonce)
    code, _, body = request(server, f"/ready?c={challenge}")
    assert code == 200
    assert json.loads(body) == {
        "pid": os.getpid(),
        "mac": hmac.new(nonce.encode(), challenge.encode(), hashlib.sha256).hexdigest(),
    }
    assert nonce not in body.decode()
    assert request(server, f"/ready?c={challenge}", headers={"Host": "evil.example:8431"})[0] == 403
    assert request(server, "/ready?c=bad")[0] == 404


def test_frontend_text_only_and_refresh():
    js = PACKAGE.joinpath("web", "insights.js").read_text()
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js
    assert "textContent" in js and "createElement" in js
    assert "setInterval(refresh, 30000)" in js and "document.hidden" in js
    assert "row.uses === null" in js
    assert "Nothing recorded yet. Counts appear after the first helper run." in js
    assert "dataset.prefix" in js
    for word in ("MCP", "NetBird", "VPN"):
        assert word not in js


def test_cli_status_open_and_delegation(ws, monkeypatch, capsys):
    from orch_insights import cli

    monkeypatch.setattr(cli.service, "start", lambda root: {"pid": 42, "port": 8431})
    monkeypatch.setattr(cli.service, "running", lambda root: None)
    monkeypatch.setattr(cli.service, "stop", lambda root: "not running")
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: pytest.fail("must not open"))
    assert cli.main(["--dir", str(ws), "open", "--no-open", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["url"] == "http://127.0.0.1:8431"
    assert cli.main(["--dir", str(ws), "status", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {"running": False}
    assert cli.main(["--dir", str(ws), "stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stopped"] is False


def test_bundled_counts_contract_matches_repository():
    def expand(node, filename):
        if isinstance(node, list):
            return [expand(value, filename) for value in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            file, pointer = node["$ref"].split("#")
            target = file or filename
            value = json.loads((CONTRACTS / target).read_text())
            for part in pointer.strip("/").split("/"):
                value = value[part]
            return expand(value, target)
        return {key: expand(value, filename) for key, value in node.items()}

    schema = json.loads((CONTRACTS / "counts.schema.json").read_text())["$defs"]["answer"]
    assert json.loads(PACKAGE.joinpath("answer.schema.json").read_text()) == expand(
        schema, "counts.schema.json"
    )

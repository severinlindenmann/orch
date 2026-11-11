"""T0 lists: columns, state words, detail panels, privacy, and the fenced /api/list routes."""

import copy
import json
import re
from importlib import resources

import pytest
from test_overview import item, request, set_answer

from orch_insights.lists import build_detail, build_list, connection_state
from orch_insights.overview import ERROR, PARTIAL

PACKAGE = resources.files("orch_insights")
TABS = ("skills", "connections", "keys")
HASH = "sha256:" + "d" * 64


def rows(answer, tab):
    view = build_list(answer, tab)
    assert "error" not in view, view
    return {row["name"]: row for row in view["rows"]}


def strings(node, skip_details=False):
    """Every string in a JSON tree, optionally outside the folded `details` blocks."""
    if isinstance(node, dict):
        for key, value in node.items():
            if skip_details and key == "details":
                continue
            yield key
            yield from strings(value, skip_details)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value, skip_details)
    elif isinstance(node, str):
        yield node


def key_item(answer, name, **changes):
    return item(answer, kind="key", name=name, versions=[], **changes)


def connection(answer, name, **changes):
    template = copy.deepcopy(answer["inventory"]["connections"][0])
    template.update(name=name, label=name.capitalize(), **changes)
    return template


def test_columns_and_shape(answer):
    expected = {
        "skills": ["Skill", "From", "Uses", "State"],
        "connections": ["Connection", "From", "Allowed actions", "State"],
        "keys": ["Key", "From", "Uses", "State"],
    }
    for tab in TABS:
        view = build_list(answer, tab)
        assert view["columns"] == expected[tab]
        assert view["count"] == len(view["rows"])
        assert [f["id"] for f in view["filters"]] == ["all", "look", "idle"]
        assert [f["label"] for f in view["filters"]] == ["All", "Needs a look", "Not used"]
        for row in view["rows"]:
            assert {
                "name",
                "source",
                "health",
                "label",
                "uses",
                "numbers",
                "unseen",
                "last_used",
            } <= row.keys()
            assert {"text", "tone"} == row["state"].keys()
    assert build_list(answer, "tools") is None
    assert build_detail(answer, "tools", "x") is None


def test_key_state_chips_and_types(answer):
    answer["items"] = [
        key_item(answer, "in-use", source="workspace"),
        key_item(answer, "admin-ok", source="admin"),
        key_item(answer, "idle", seen="not_seen", uses=0, ok=0, failed=0, last_seen=None),
        key_item(answer, "refused", uses=2, ok=0, failed=0, refused=2),
        key_item(answer, "refused-once", uses=1, ok=0, failed=0, refused=1),
        key_item(answer, "unsure", seen="unknown", uses=0, ok=0, failed=0),
    ]
    answer["inventory"]["keys"] = [
        {"name": name, "type": kind, "source": "workspace"}
        for name, kind in (
            ("in-use", "token"),
            ("idle", "password"),
            ("unsure", "key-file"),
            ("refused", "json"),
        )
    ]
    keys = rows(answer, "keys")
    states = {name: row["state"]["text"] for name, row in keys.items()}
    assert states == {
        "in-use": "In use",
        "admin-ok": "Managed by your admin",
        "idle": "Not used 30+ days",
        "refused": "Refused 2 times",
        "refused-once": "Refused 1 time",
        "unsure": "Can't tell yet",
    }
    assert {name: keys[name]["type"] for name in ("in-use", "idle", "unsure", "refused")} == {
        "in-use": "token",
        "idle": "password",
        "unsure": "key file",
        "refused": "JSON file",
    }
    assert keys["admin-ok"]["type"] == "Can't tell yet"
    assert keys["admin-ok"]["source"] == "Shared by your admin"
    assert {"term": "Value", "value": "Never shown or recorded"} in keys["in-use"]["panel"]["details"]


@pytest.mark.parametrize(
    "seen,last_seen,expected",
    [
        ("yes", "2026-11-13T09:00:00Z", "Last used 3 days ago"),
        ("yes", "2026-11-15T09:00:00Z", "Last used yesterday"),
        ("yes", "2026-11-16T09:00:00Z", "Last used today"),
        ("not_seen", None, "Never used in 30 days"),
        ("unknown", None, "Can't tell yet"),
    ],
)
def test_last_used_relative_to_answer(answer, seen, last_seen, expected):
    zero = {"uses": 0, "ok": 0, "failed": 0} if seen != "yes" else {}
    answer["items"] = [item(answer, seen=seen, last_seen=last_seen, **zero)]
    assert rows(answer, "skills")["Invoice export"]["last_used"] == expected
    # Only generated_at moves the wording, never the clock.
    answer["generated_at"] = "2026-11-26T09:30:00Z"
    if seen == "yes":
        assert rows(answer, "skills")["Invoice export"]["last_used"].endswith("days ago")


def test_sorting_and_filters(answer):
    answer["items"] = [
        item(answer, name="busy", uses=9, ok=9, failed=0),
        item(answer, name="quiet", uses=2, ok=2, failed=0),
        item(answer, name="failing", uses=5, ok=3, failed=2),
        item(answer, name="idle", uses=0, ok=0, failed=0, seen="not_seen", last_seen=None),
    ]
    view = build_list(answer, "skills")
    names = [row["name"] for row in view["rows"]]
    assert names[:3] == ["Failing", "Busy", "Quiet"]
    by_name = {row["name"]: row for row in view["rows"]}
    assert by_name["Failing"]["filter"] == "look"
    assert by_name["Idle"]["filter"] == "idle"
    assert by_name["Busy"]["filter"] == ""
    assert {f["id"]: f["count"] for f in view["filters"]} == {"all": len(names), "look": 1, "idle": 1}


def test_keys_never_carry_a_value(answer, server, fake_orch):
    answer["items"][2].update(value="s3cret-item", secret="hunter2-item")
    answer["inventory"]["keys"][0].update(value="s3cret-inventory", secret="hunter2-inventory")
    for tab in TABS:
        text = json.dumps(build_list(answer, tab))
        assert "error" not in json.loads(text)
        for word in ("s3cret", "hunter2", '"secret"'):
            assert word not in text
    keys = rows(answer, "keys")
    assert keys["google-sa.json"]["type"] == "JSON file"
    set_answer(fake_orch, answer)
    code, _, body = request(server, "/api/list/keys")
    assert code == 200 and "google-sa.json" in body.decode()
    assert "s3cret" not in body.decode() and "hunter2" not in body.decode()


@pytest.mark.parametrize(
    "actions,allow_all,expected",
    [
        ([True, True, False], False, "2 of 3 allowed"),
        ([True, False], True, "All allowed"),
        ([False, False], False, "Not allowed by this workspace"),
        ([], False, "Not allowed by this workspace"),
    ],
)
def test_connection_allowed_actions(answer, actions, allow_all, expected):
    entry = connection(
        answer,
        "github",
        actions=[{"name": f"a{i}", "allowed": on} for i, on in enumerate(actions)],
        allow_all=allow_all,
    )
    answer["inventory"]["connections"] = [entry]
    assert rows(answer, "connections")["Github"]["allowed"] == expected


@pytest.mark.parametrize(
    "state,expected",
    [
        ("ok", "Working"),
        ("not-started", "Not started"),
        ("missing-key", "Needs attention"),
        ("unknown", None),
    ],
)
def test_connection_states(answer, state, expected):
    answer["inventory"]["connections"] = [connection(answer, "github", state=state)]
    assert rows(answer, "connections")["Github"]["state"]["text"] == (expected or "Can't tell yet")


def test_unknown_connection_state_words(answer):
    assert connection_state("rebooting")["text"] == "Can't tell yet"
    assert connection_state(None)["text"] == "Can't tell yet"
    # The answer itself is schema checked: an unknown state string fails closed, no rows.
    answer["inventory"]["connections"][0]["state"] = "rebooting"
    assert build_list(answer, "connections") == {"error": ERROR, "complete": False}


def test_connection_words_and_transport_only_in_details(answer):
    slack = answer["inventory"]["connections"][1]
    slack["host"] = "mcp.slack.example/secret/path?token=x"
    gdrive = answer["inventory"]["connections"][0]
    gdrive["command"] = "npx --token abc"
    view = build_list(answer, "connections")
    assert "error" not in view
    text = json.dumps(view)
    for leak in ("secret", "path", "token", "abc", "?"):
        assert leak not in text
    assert not any("MCP" in value for value in strings(view, skip_details=True))
    for row in view["rows"]:
        for value in strings(row, skip_details=True):
            assert "mcp.slack.example" not in value and value != "npx"
    connections = {row["name"]: row for row in view["rows"]}
    slack_details = {d["term"]: d["value"] for d in connections["Slack"]["panel"]["details"]}
    assert slack_details["Runs as"] == "web address"
    assert slack_details["Address"] == "mcp.slack.example"
    assert "MCP" in slack_details["Kind"]
    drive_details = {d["term"]: d["value"] for d in connections["Google Drive"]["panel"]["details"]}
    assert drive_details["Runs as"] == "program on this computer"
    assert drive_details["Program"] == "npx"
    assert connections["Slack"]["allowed"] == "1 of 2 allowed"
    assert connections["Google Drive"]["allowed"] == "2 of 2 allowed"
    assert connections["Weather"]["state"]["text"] == "Not started"


def test_skill_versions_line(answer):
    assert rows(answer, "skills")["Invoice export"]["versions"] is None
    first = answer["items"][0]["versions"][0]
    answer["items"][0]["versions"] = [
        {**first, "version": HASH, "uses": 4, "ok": 4, "failed": 0, "first_seen": "2026-11-12T08:00:00Z"},
        {**first, "uses": 2, "ok": 1, "failed": 1, "first_seen": "2026-11-02T08:00:00Z"},
        {
            **first,
            "version": "sha256:" + "e" * 64,
            "uses": 1,
            "ok": 1,
            "failed": 0,
            "first_seen": "2026-11-05T08:00:00Z",
        },
    ]
    row = rows(answer, "skills")["Invoice export"]
    assert row["versions"] == "Changed 2 times; since the latest change: 4 of 4 ok"
    assert "sha256" not in json.dumps(row)


@pytest.mark.parametrize("shadow_first", [True, False])
def test_shadowed_skill_wording(answer, shadow_first):
    loser = {"name": "newsletter-writing", "source": "admin", "version": HASH, "shadowed": True}
    skills = answer["inventory"]["skills"]
    answer["inventory"]["skills"] = [loser, *skills] if shadow_first else [*skills, loser]
    view = build_list(answer, "skills")
    row = next(row for row in view["rows"] if row["name"] == "Newsletter writing")
    assert row["source"] == "This workspace"
    assert row["also"] == "Also in your admin's shared items; this one is used"
    assert rows(answer, "skills")["Orch"]["also"] is None


@pytest.mark.parametrize(
    "state,expected", [("on", True), ("off", True), ("off_by_admin", True), ("not_connected", False)]
)
def test_can_ask_admin(answer, state, expected):
    answer["sharing"]["counts"] = state
    for tab in TABS:
        assert build_list(answer, tab)["can_ask_admin"] is expected


def test_inventory_only_rows_and_panel(answer):
    drive = rows(answer, "connections")["Google Drive"]
    assert drive["uses"] is None and drive["health"] == "unknown"
    assert drive["last_used"] == "Can't tell yet"
    assert drive["panel"]["numbers"] == ["Can't tell yet"]
    assert drive["panel"]["tickets"] is None
    assert drive["panel"]["first_seen"] == "Can't tell yet"
    assert "0" not in drive["numbers"]
    skill = rows(answer, "skills")["Invoice export"]
    panel = skill["panel"]
    assert panel["tickets"] == "3 done, 1 sent back, 1 open"
    assert panel["note"] == "Errors are not proof that this is bad."
    assert panel["first_seen"] == "2 Nov 2026" and panel["last_seen"] == "16 Nov 2026"
    assert panel["numbers"] == [
        "7 uses: 6 ok, 1 failed, 0 refused",
        "Used in 5 of 23 runs",
        "4 runs can't tell",
    ]
    assert build_detail(answer, "skills", skill["key"]) == panel
    assert build_detail(answer, "skills", "not-there") is None
    weather = rows(answer, "connections")["Weather"]
    assert weather["last_used"] == "Never used in 30 days" and weather["panel"]["last_seen"] == "Not seen"


def test_no_hashes_or_record_ids(answer):
    answer["items"][0]["versions"].append({**answer["items"][0]["versions"][0], "version": HASH})
    for tab in TABS:
        text = json.dumps(build_list(answer, tab))
        assert "sha256" not in text and "dddd" not in text and "cccc" not in text
        assert not re.search(r"\b(?:ws_|t_|r_)[a-z0-9]{6,}", text)


@pytest.mark.parametrize("bad", [None, [], {}])
def test_bad_shapes_fail_closed(bad):
    for tab in TABS:
        assert build_list(bad, tab) == {"error": ERROR, "complete": False}


def test_api_lists(server):
    for tab in TABS:
        code, headers, body = request(server, f"/api/list/{tab}")
        assert code == 200 and headers["Content-Type"] == "application/json"
        view = json.loads(body)
        assert view["tab"] == tab and view["rows"]
        assert "sha256" not in body.decode()
    for path in ("/api/list/tools", "/api/list/", "/api/list", "/api/list/skills/x", "/api/list/../overview"):
        assert request(server, path)[0] == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_api_lists_read_only_and_fenced(server, method):
    assert request(server, "/api/list/keys", method=method)[0] == 405
    assert request(server, "/api/list/keys", method=method, headers={"Host": "evil.example:8431"})[0] == 403
    assert request(server, "/api/list/keys", headers={"Host": "evil.example:8431"})[0] == 403
    assert request(server, "/api/list/keys", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403


@pytest.mark.parametrize("mutation", ["exit", "json", "incomplete", "unavailable"])
def test_api_lists_fail_closed(server, fake_orch, answer, mutation):
    expected = {"error": PARTIAL, "complete": False}
    if mutation == "exit":
        (fake_orch.parent / "exit").touch()
        expected = {"error": ERROR, "complete": False}
    elif mutation == "json":
        (fake_orch.parent / "answer.json").write_text("not json")
        expected = {"error": ERROR, "complete": False}
    elif mutation == "incomplete":
        answer["complete"] = False
        set_answer(fake_orch, answer)
    else:
        answer["unavailable"] = [{"run": None, "status": "unavailable", "reason": "io", "message": "x"}]
        set_answer(fake_orch, answer)
    for tab in TABS:
        code, _, body = request(server, f"/api/list/{tab}")
        assert code == 200 and json.loads(body) == expected


def test_frontend_lists_text_only_and_read_only():
    js = PACKAGE.joinpath("web", "insights.js").read_text()
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "outerHTML" not in js
    assert "/api/list/${tab}" in js
    assert "row.uses === null" in js
    for word in ("MCP", "Ask admin", "method:"):
        assert word not in js
    # Read-only slice: no Remove / Allow actions (signed human actions come later).
    assert not re.search(r"\b(?:Remove|Allow)\b", js)
    css = PACKAGE.joinpath("web", "insights.css").read_text()
    assert "position: fixed" in css and "bottom: 0" in css

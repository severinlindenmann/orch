"""orch services view: the Services page as one list-and-panel block (mockup layout C), with a fake driver."""

import json

from conftest import CONTRACTS, jrun, validator

VIEW_SCHEMA = CONTRACTS / "addon-view.schema.json"


def _view(cli):
    code, out, _ = cli("view", "--json")
    assert code == 0, out
    view = json.loads(out)
    assert not [e.message for e in validator(VIEW_SCHEMA).iter_errors(view)]
    return view


def _add(cli, sid, name, *extra):
    code, out = jrun(cli, "add", name, "--id", sid, *extra, "--", "python3", "-m", "http.server", "8000")
    assert code == 0, out


def _facts(item):
    return {f["label"]: f for f in item["panel"]["facts"]}


def test_empty_page_is_one_sentence_one_button_and_the_automation_footnote(cli):
    view = _view(cli)
    split, foot = view["blocks"]
    assert split["type"] == "split" and split["groups"] == [] and split["param"] == "svc"
    assert split["empty"]["title"] == "No services yet"
    assert split["empty"]["button"] == {"label": "Ask the helper", "to": "app:chat"}
    assert foot == {
        "type": "footnote",
        "text": "Timed jobs that run and end are in Automation.",
        "link": {"label": "Open Automation", "to": "app:addon/automation"},
    }


def test_every_managed_service_is_in_the_list_with_its_panel(cli, ws):
    _add(cli, "web", "Web preview", "--ticket", "DM1-12", "--auto", "--start")
    _add(cli, "front", "Dashboard front", "--addon", "dashboard")
    view = _view(cli)
    (group,) = view["blocks"][0]["groups"]
    assert group["title"] == "Managed with orch" and group["meta"] == "1 running · 1 stopped"
    front, web = group["items"]  # sorted by name, failing ones first
    assert web["state"] == {"label": "Running", "tone": "good"}
    assert web["action"]["label"] == "Stop" and front["action"]["label"] == "Start"
    assert [b["label"] for b in web["panel"]["buttons"]] == ["Stop", "Restart"]
    assert [b["label"] for b in front["panel"]["buttons"]] == ["Start"]
    f = _facts(web)
    assert f["State"]["value"].startswith("Running since today ") and f["State"]["tone"] == "good"
    assert f["Starts by itself"]["value"] == "Yes, after this computer restarts"
    assert f["Starts by itself"]["switch"]["on"] is True
    assert f["Starts by itself"]["switch"]["action"]["args"] == {"verb": "auto-off", "target": "web"}
    assert f["Made by"] == {"label": "Made by", "value": "DM1-12", "link": "t_abc123"}
    g = _facts(front)
    assert g["Starts by itself"]["value"] == "No, you start it by hand"
    assert g["Starts by itself"]["switch"]["action"]["args"]["verb"] == "auto-on"
    assert g["Made by"]["value"] == "Dashboard add-on" and "link" not in g["Made by"]
    for item in (web, front):  # every action names this service only
        acts = [b["action"] for b in item["panel"]["buttons"]] + [item["panel"]["danger"]["action"]]
        assert all(a["op"] == "addon.act" and a["args"]["target"] == item["id"] for a in acts)


def test_remove_says_what_happens(cli):
    _add(cli, "web", "Web preview", "--ticket", "DM1-12", "--start")
    item = _view(cli)["blocks"][0]["groups"][0]["items"][0]
    d = item["panel"]["danger"]
    assert d["label"] == "Remove" and d["action"]["args"] == {"verb": "remove", "target": "web"}
    assert d["confirm"]["title"] == "Remove Web preview?" and d["confirm"]["keep"] == "Keep it"
    assert d["confirm"]["lines"] == [
        "It stops now and leaves this list.",
        "It will not start by itself again.",
        "Ticket DM1-12 and its files stay as they are.",
    ]


def test_log_shows_the_last_20_lines_masked_and_plain(cli, ws, stored_keys):
    _add(cli, "web", "Web preview", "--start")
    secret = "zq-stored-value-81723"
    stored_keys["k"] = secret
    log = ws / ".orch/addons/services/logs/web.log"
    lines = [f"line {i}" for i in range(30)] + [f"key loaded: {secret}", "<b>tag</b> done", ""]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    item = _view(cli)["blocks"][0]["groups"][0]["items"][0]
    got = item["panel"]["log"]["lines"]
    assert len(got) == 20 and got[0] == "line 12"
    assert secret not in json.dumps(item) and "••••••" in got[-2]
    assert got[-1] == "‹b›tag‹/b› done"


def test_found_group_shows_only_manage_with_orch_and_nothing_when_empty(ws):
    from orch_services.view import build

    rows = []
    assert len(build(ws, (rows, 0, None), found=[])["blocks"][0]["groups"]) == 0
    found = [
        {
            "id": "old-test-page",
            "name": "Old test page on port 8794",
            "what": "A page somebody started by hand",
        },
        {"id": "launchd:ch.Example.Forwarder", "name": "Forwarder"},
        {"id": "", "name": "skipped"},
    ]
    view = build(ws, (rows, 0, None), found=found)
    assert not [e.message for e in validator(VIEW_SCHEMA).iter_errors(view)]
    (group,) = view["blocks"][0]["groups"]
    assert group["title"] == "Found on this computer" and len(group["items"]) == 2
    item, real = group["items"]
    # a real label with capitals gets a plain page id; Manage with orch still sends the real found id
    assert real["id"].startswith("found-")
    assert real["panel"]["buttons"][0]["action"]["args"]["target"] == "launchd:ch.Example.Forwarder"
    assert item["state"] == {"label": "Running, not managed", "tone": "neutral"}
    assert item["panel"]["buttons"] == [
        {
            "label": "Manage with orch",
            "action": {"op": "addon.act", "args": {"verb": "adopt", "target": "old-test-page"}},
        }
    ]
    assert "danger" not in item["panel"] and "action" not in item


def test_a_failing_service_comes_first_with_health_and_depends(ws):
    from orch_services.view import build

    rows = [
        {"id": "a", "name": "Alpha", "state": "running", "since": None, "auto": False},
        {
            "id": "b",
            "name": "Budget guard",
            "state": "failing",
            "since": None,
            "auto": False,
            "health": {"ok": False, "text": "Not alive"},
            "depends": ["Every helper run that has a budget"],
        },
    ]
    view = build(ws, (rows, 0, None))
    assert not [e.message for e in validator(VIEW_SCHEMA).iter_errors(view)]
    items = view["blocks"][0]["groups"][0]["items"]
    assert [i["id"] for i in items] == ["b", "a"]
    f = _facts(items[0])
    assert f["Health check"] == {"label": "Health check", "value": "Not alive", "tone": "bad"}
    assert f["Depends on it"]["value"] == "Every helper run that has a budget"
    assert (
        "These stop working: Every helper run that has a budget."
        in items[0]["panel"]["danger"]["confirm"]["lines"]
    )
    assert view["blocks"][0]["groups"][0]["meta"] == "1 running · 1 failing"


def test_a_platform_note_shows_as_the_notice(cli, fake):
    fake.unavailable = "no session"
    view = _view(cli)
    assert view["notice_tone"] == "warn" and "no session" in view["notice"]

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
    assert f["State"]["value"] == "Running since today 10:00" and f["State"]["tone"] == "good"
    assert f["Starts by itself"]["value"] == "Yes, after this computer restarts"
    assert f["Starts by itself"]["switch"]["on"] is True
    assert f["Starts by itself"]["switch"]["action"]["args"] == {"verb": "auto-off", "target": "web"}
    assert f["Made by"] == {"label": "Made by", "value": "DM1-12", "link": "t_abc123"}
    g = _facts(front)
    assert g["Starts by itself"]["value"] == "Only after a crash, not after this computer restarts"
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
        "Its log stays on this computer.",
        "Ticket DM1-12 and its files stay as they are.",
    ]


def test_log_shows_the_last_100_lines_masked_and_plain(cli, ws, stored_keys):
    _add(cli, "web", "Web preview", "--start")
    secret = "zq-stored-value-81723"
    stored_keys["k"] = secret
    log = ws / ".orch/addons/services/logs/web.log"
    lines = [f"line {i}" for i in range(130)] + [f"key loaded: {secret}", "<b>tag</b> done", ""]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    item = _view(cli)["blocks"][0]["groups"][0]["items"][0]
    got = item["panel"]["log"]["lines"]
    assert len(got) == 100 and got[0] == "line 32"
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
    # a real label with capitals gets a plain page id; Manage with orch sends it (the page draws a button only
    # when its target is the item's own id) and adopt finds the real job from it
    assert real["id"].startswith("found-")
    assert real["panel"]["buttons"][0]["action"]["args"]["target"] == real["id"]
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


def test_an_adopted_service_shows_its_own_log_and_remove_says_it_is_only_forgotten(cli, ws, monkeypatch):
    # review ORCH-378: the page read logs/<id>.log (empty or an older service's) and promised "it stops now"
    import orch_services.cli as cli_mod
    from orch_services import store
    from orch_services.view import build

    store.save(
        ws,
        {
            "schema": store.SCHEMA,
            "id": "notes",
            "name": "Notes sync",
            "command": ["/usr/bin/python3", "sync.py"],
            "cwd": ".",
            "auto": True,
            "created_at": store.now(),
            "made_by": {"found": True},
            "adopted": {"kind": "systemd", "entry": "notes-sync.service", "path": None},
        },
    )
    old = store.log_path(ws, "notes")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("left over from an older service\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(cli_mod, "_log_lines", lambda root, rec, n: seen.append(rec["id"]) or ["job started"])
    row = {"id": "notes", "name": "Notes sync", "state": "running", "since": None, "auto": True}
    row["made_by"] = {"found": True}
    item = build(ws, ([row], 0, None))["blocks"][0]["groups"][0]["items"][0]
    assert item["panel"]["log"]["lines"] == ["job started"] and seen == ["notes"]
    assert item["panel"]["danger"]["confirm"]["lines"] == [
        "orch stops managing it and it leaves this list.",
        "The job itself is left as it is on this computer.",
    ]


def test_the_open_question_is_pinned_with_restart_stop_and_a_link_to_its_ticket(ws):
    # ORCH-371 bug 1: list had the question, the page never showed it
    from orch_services.view import build

    rows = [
        {
            "id": "b",
            "name": "Budget guard",
            "state": "failing",
            "since": None,
            "auto": False,
            "health": {"ok": False, "text": "Not alive"},
            "question": {
                "ticket": "t_abc1234",
                "id": "q1",
                "title": "Budget guard keeps stopping",
                "text": "It failed 3 times in the last 10 minutes. Restart, Stop or Look into it?",
            },
        },
        {"id": "a", "name": "Alpha", "state": "running", "since": None, "auto": False, "question": None},
    ]
    view = build(ws, (rows, 0, None))
    assert not [e.message for e in validator(VIEW_SCHEMA).iter_errors(view)]
    failing, fine = view["blocks"][0]["groups"][0]["items"]
    assert failing["question"] == {
        "title": "Budget guard keeps stopping",
        "text": "It failed 3 times in the last 10 minutes. Restart, Stop or Look into it?",
        "buttons": [
            {"label": "Restart", "action": {"op": "addon.act", "args": {"verb": "restart", "target": "b"}}},
            {"label": "Stop", "action": {"op": "addon.act", "args": {"verb": "stop", "target": "b"}}},
            {"label": "Look into it", "link": "t_abc1234"},
        ],
    }
    assert "question" not in fine


def test_a_stopped_found_job_says_stopped_and_the_found_group_says_none_are_managed(ws):
    # ORCH-371 bugs 4 and 7
    from orch_services.view import build

    found = [{"id": "launchd:com.example.walkfound", "name": "walkfound", "running": False, "since": None}]
    view = build(ws, ([], 0, None), found=found)
    assert not [e.message for e in validator(VIEW_SCHEMA).iter_errors(view)]
    (group,) = view["blocks"][0]["groups"]
    assert group["meta"] == "orch manages none of these yet"
    (item,) = group["items"]
    assert item["state"] == {"label": "Stopped, not managed", "tone": "neutral"}
    assert _facts(item)["Found"]["value"] == "Stopped, not made by orch"


def test_a_stopped_service_has_a_quiet_health_line(ws):
    # ORCH-371 bug 6: a red dot next to "Stopped, so not checked" read like an alarm
    from orch_services.view import build

    rows = [
        {
            "id": "w",
            "name": "Web",
            "state": "stopped",
            "since": None,
            "auto": False,
            "health": {"ok": False, "text": "Stopped, so not checked"},
        }
    ]
    (item,) = build(ws, (rows, 0, None))["blocks"][0]["groups"][0]["items"]
    assert _facts(item)["Health check"]["tone"] == "neutral"


def test_a_running_job_that_does_not_answer_is_amber_in_the_list(ws):
    # ORCH-641: alive but silent on its address must not show a green Running dot in the list
    from orch_services.view import build

    def row(sid, ok):
        return {
            "id": sid,
            "name": sid,
            "state": "running",
            "since": None,
            "auto": False,
            "health": {"ok": ok, "text": "x"},
        }

    items = build(ws, ([row("hung", False), row("fine", True)], 0, None))["blocks"][0]["groups"][0]["items"]
    by = {i["id"]: i for i in items}
    assert by["hung"]["state"] == {"label": "Not answering", "tone": "warn"}
    assert by["fine"]["state"] == {"label": "Running", "tone": "good"}
    assert _facts(by["hung"])["State"]["value"] == "Running"  # the panel keeps the plain state


def test_a_service_with_a_port_shows_its_address_as_a_link_next_to_the_health_check(cli):
    # ORCH-846: a web app's address was shown nowhere; the person had to know the port
    _add(cli, "web", "Web preview", "--port", "8765", "--start")
    _add(cli, "watch", "Watcher")
    view = _view(cli)  # checked against the view contract, so the local link is allowed there
    by = {i["id"]: i for i in view["blocks"][0]["groups"][0]["items"]}
    labels = [f["label"] for f in by["web"]["panel"]["facts"]]
    assert labels.index("Address") == labels.index("Health check") - 1
    assert _facts(by["web"])["Address"] == {
        "label": "Address",
        "value": "http://127.0.0.1:8765",
        "link": "http://127.0.0.1:8765",
    }
    assert "Address" not in _facts(by["watch"])  # no port, no address


def test_a_stopped_service_shows_its_address_without_a_link_and_a_bad_port_shows_none(ws):
    from orch_services.view import build

    def row(sid, state, port):
        return {"id": sid, "name": sid, "state": state, "since": None, "auto": False, "port": port}

    rows = [row("off", "stopped", 5173), row("odd", "running", "8000"), row("big", "running", 70000)]
    by = {i["id"]: i for i in build(ws, (rows, 0, None))["blocks"][0]["groups"][0]["items"]}
    assert _facts(by["off"])["Address"] == {"label": "Address", "value": "http://127.0.0.1:5173"}
    assert "Address" not in _facts(by["odd"]) and "Address" not in _facts(by["big"])


def test_a_plain_program_in_found_has_no_manage_button(ws):
    # ORCH-934: adopt refuses a bare process, so the page must not draw a button that can only fail
    from orch_services.view import build

    found = [
        {
            "id": "process:4242",
            "name": "Python http.server",
            "running": True,
            "what": "A program started by hand",
        },
        {"id": "old-test-page", "name": "Old test page", "running": True},
    ]
    view = build(ws, ([], 0, None), found=found)
    assert not [e.message for e in validator(VIEW_SCHEMA).iter_errors(view)]
    (group,) = view["blocks"][0]["groups"]
    plain, entry = group["items"]
    assert "buttons" not in plain["panel"] and plain["panel"]["facts"]
    assert entry["panel"]["buttons"][0]["label"] == "Manage with orch"


def test_stop_on_a_job_marked_important_asks_once_everywhere(ws):
    # ORCH-641: the list row, the panel and the pinned question all carry the one question; other jobs stop at once
    from orch_services.view import build

    def row(sid, important, state="running"):
        return {
            "id": sid,
            "name": sid.title(),
            "state": state,
            "since": None,
            "auto": False,
            "important": important,
        }

    fwd = row("fwd", True, "failing")
    fwd["question"] = {"title": "Fwd keeps stopping", "ticket": "t_abc123"}
    items = build(ws, ([fwd, row("plain", False)], 0, None))["blocks"][0]["groups"][0]["items"]
    by = {i["id"]: i for i in items}
    stops = [by["fwd"]["action"], by["fwd"]["panel"]["buttons"][0], by["fwd"]["question"]["buttons"][1]]
    for b in stops:
        assert b["label"] == "Stop" and b["confirm"]["title"] == "Stop Fwd?"
        assert b["confirm"]["keep"] == "Keep it running" and "marked important" in b["confirm"]["lines"][0]
    assert "confirm" not in by["plain"]["action"] and "confirm" not in by["plain"]["panel"]["buttons"][0]
    f, g = _facts(by["fwd"])["Important"], _facts(by["plain"])["Important"]
    assert f["value"] == "Yes, Stop asks first" and f["switch"]["action"]["args"]["verb"] == "important-off"
    assert g["value"] == "No" and g["switch"]["action"]["args"]["verb"] == "important-on"

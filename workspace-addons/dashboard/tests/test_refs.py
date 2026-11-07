from pathlib import Path

"""Ticket links and add-on fields in the dashboard: the three new ops (ref.add, ref.rm, ticket.field), the
refresh answer, and the link view the page gets from the core's one link module (orch.refs)."""

import json
import threading

import pytest

from orch_dashboard import actions, data

from .test_act import acts, calls, post

ADDONS = [
    {
        "name": "alpha",
        "active": True,
        "acts": ["refresh"],
        "ticket_links": [
            {
                "kind": "github-pr",
                "label": "Pull request",
                "icon": "git-pull-request",
                "match": ["https://github.com/*/*/pull/*"],
                "statuses": ["open", "merged"],
            }
        ],
        "ticket_fields": {
            "section": "Campaign",
            "show_on_card": ["channel"],
            "fields": [
                {
                    "key": "channel",
                    "title": "Channel",
                    "type": "choice",
                    "read_only": False,
                    "hidden": False,
                    "options": [{"value": "youtube", "label": "YouTube"}],
                },
                {"key": "pr", "title": "PR status", "type": "text", "read_only": True, "hidden": False},
                {"key": "x", "title": "<b>", "type": "evil", "read_only": False, "hidden": False},
            ],
        },
    },
    {
        "name": "beta",
        "active": False,
        "ticket_links": [
            {"kind": "campaign", "label": "Campaign", "icon": "megaphone", "match": ["https://ads.example/*"]}
        ],
    },
]


@pytest.fixture
def base(act_orch, ws):
    from orch_dashboard.server import make_server

    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        f'if a[:2] == ["addon", "list"]:\n    print(json.dumps({ADDONS!r}).replace("True", "true").replace("False", "false"))\n    sys.exit(0)\n'
        'if a[1:3] == ["act", "refresh"]:\n    print(json.dumps({"ticket": "t_abcdef", "changes": [{"field": "status"}], "say": "PR #4 was merged."}))\n'
        '    sys.exit(0)\nif a[:2] in (["addon", "list"]',
    )
    act_orch.write_text(src)
    srv = make_server(ws, 0, orch_bin=str(act_orch))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_link_and_field_ops_build_one_argv(base, act_orch):
    me = actions.actor()
    common = ["--by", me, "--json"]
    cases = [
        (
            {"op": "ref.add", "args": {"ticket": "t_abcdef", "target": "https://github.com/a/b/pull/4"}},
            ["ref", "add", "t_abcdef", *common, "--", "https://github.com/a/b/pull/4"],
        ),
        (
            {"op": "ref.add", "args": {"ticket": "t_abcdef", "target": "docs/readme.md"}},
            ["ref", "add", "t_abcdef", *common, "--", "docs/readme.md"],
        ),
        ({"op": "ref.rm", "args": {"ticket": "t_abcdef", "n": 1}}, ["ref", "rm", "t_abcdef", "1", *common]),
        (
            {
                "op": "ticket.field",
                "args": {
                    "ticket": "t_abcdef",
                    "addon": "alpha",
                    "field": "channel",
                    "value": "youtube",
                    "if_revision": 3,
                },
            },
            ["ticket", "set", "t_abcdef", "alpha.channel", "--if-revision=3", *common, "--", "youtube"],
        ),
        (
            {
                "op": "ticket.field",
                "args": {"ticket": "t_abcdef", "addon": "alpha", "field": "budget", "value": ""},
            },
            ["ticket", "set", "t_abcdef", "alpha.budget", *common, "--", ""],
        ),
    ]
    for body, want in cases:
        code, text, _ = post(base, body)
        assert code == 200, (body, text)
        assert acts(act_orch)[-1] == want, body


@pytest.mark.parametrize(
    "body",
    [
        {"op": "ref.add", "args": {"ticket": "t_abcdef", "target": ""}},
        {"op": "ref.add", "args": {"ticket": "t_abcdef", "target": "x" * 2001}},
        {"op": "ref.add", "args": {"ticket": "t_abcdef", "target": "a\0b"}},
        {"op": "ref.add", "args": {"ticket": "t_abcdef", "target": 4}},
        {"op": "ref.add", "args": {"ticket": "--evil", "target": "notes.md"}},
        {"op": "ref.add", "args": {"ticket": "t_abcdef", "target": "notes.md", "kind": "x"}},
        {"op": "ref.rm", "args": {"ticket": "t_abcdef", "n": 0}},
        {"op": "ref.rm", "args": {"ticket": "t_abcdef", "n": True}},
        {
            "op": "ticket.field",
            "args": {"ticket": "t_abcdef", "addon": "beta", "field": "x", "value": "1"},
        },  # off
        {
            "op": "ticket.field",
            "args": {"ticket": "t_abcdef", "addon": "gamma", "field": "x", "value": "1"},
        },  # unknown
        {
            "op": "ticket.field",
            "args": {"ticket": "t_abcdef", "addon": "ticket", "field": "x", "value": "1"},
        },  # core
        {
            "op": "ticket.field",
            "args": {"ticket": "t_abcdef", "addon": "alpha", "field": "a.b", "value": "1"},
        },
        {"op": "ticket.field", "args": {"ticket": "t_abcdef", "addon": "alpha", "field": "x", "value": 5}},
    ],
)
def test_bad_link_and_field_requests_are_refused(base, act_orch, body):
    assert post(base, body)[0] == 400, body
    assert not any(c[:1] in (["ref"],) or c[:2] == ["ticket", "set"] for c in calls(act_orch))


def test_refresh_answer_comes_back_with_the_state(base, act_orch):
    code, text, _ = post(
        base, {"op": "addon.act", "args": {"addon": "alpha", "verb": "refresh", "target": "t_abcdef"}}
    )
    assert code == 200, text
    assert json.loads(text)["act_result"] == {"changes": 1, "say": "PR #4 was merged."}
    assert acts(act_orch)[-1][:3] == ["alpha", "act", "refresh"]


def test_addons_carry_typed_fields_acts_and_link_kinds():
    rows = data.load_addons(None, None, ADDONS)
    assert [a["name"] for a in rows] == ["alpha"]
    a = rows[0]
    assert a["acts"] == ["refresh"] and a["link_kinds"] == ["github-pr"]
    assert [f["key"] for f in a["ticket_fields"]["fields"]] == ["channel", "pr"]  # unknown type dropped
    assert [k["kind"] for k in data.link_kinds(ADDONS)] == ["github-pr"]  # only active add-ons


def test_links_get_one_view_from_the_core_module():
    t = {
        "refs": [
            {"kind": "github-pr", "url": "https://github.com/a/b/pull/4", "status": "merged"},
            {"kind": "campaign", "url": "https://ads.example/c/1", "status": "live"},
            {"type": "ticket", "url": "t_abcdef"},
        ]
    }
    data.add_link_views([t], data.link_kinds(ADDONS))
    pr, camp, internal = t["refs"]
    assert (pr["view"]["label"], pr["view"]["status"], pr["view"]["group"]) == (
        "GitHub · Pull request",
        "merged",
        "Pull request",
    )
    assert (camp["view"]["label"], camp["view"]["status"]) == ("Reference", None)  # its add-on is off
    assert internal["view"]["label"] == "Reference"
    snap = {"refs": [{"kind": "github-pr", "url": "https://github.com/a/b/pull/4", "status": "merged"}]}
    data.add_link_views([snap], [])  # a shared copy names no add-on
    assert (snap["refs"][0]["view"]["label"], snap["refs"][0]["view"]["status"]) == ("GitHub", None)


def test_page_renders_links_with_text_only_and_safe_hrefs():
    src = (data.Path(data.__file__).parent / "web" / "app.js").read_text()
    for fn in (
        "function linkRow",
        "function linksCard",
        "function fieldSections",
        "function cardLinks",
        "function linkGroups",
    ):
        assert fn in src
    body = src[src.index("// ---- Ticket links and add-on fields") : src.index("function liveLinkFor")]
    assert "innerHTML" not in body and "safeHref" in body and "rel:'noopener noreferrer'" in body


def test_a_link_always_shows_its_real_host_and_no_borrowed_site_icon():
    kinds = data.link_kinds(
        [
            {
                "name": "gamma",
                "active": True,
                "ticket_links": [
                    {
                        "kind": "gh-like",
                        "label": "GitHub PR",
                        "icon": "github",
                        "match": ["https://github.com/*"],
                    }
                ],
            }
        ]
    )
    t = {"refs": [{"kind": "gh-like", "url": "https://evil.example/acme/pull/1"}]}
    data.add_link_views([t], kinds)
    v = t["refs"][0]["view"]
    assert (v["label"], v["icon"], v["host"]) == ("GitHub PR", "link", "evil.example")
    assert (v["shown_type"], v["host_head"], v["domain"]) == ("Link", "", "evil.example")


def test_link_type_is_an_allowlist_and_the_domain_is_the_registrable_part():
    from orch import refs

    evil = "https://github.com.evil.example/x"
    for label in (
        "github\u0323com",
        "github\uff0ecom",
        "GitHub",
        "Pull\u202erequest",
        "a" * 25,
        "x.y",
        "My GitHub PR",
        "GitHub-PR",
        "Git-Hub",
        "G i t h u b",
        "G\u00edthub",
        "\u01c0github",
        "Kampagne Zürich",
    ):
        assert data.shown_type(label, evil, refs) == "Link", label
    assert data.shown_type("GitHub · Pull request", evil, refs) == "Pull request"
    assert (
        data.shown_type("GitHub · Pull request", "https://github.com/a/b/pull/1", refs)
        == "GitHub · Pull request"
    )
    assert data.shown_type("Campaign 2026", evil, refs) == "Campaign 2026"
    assert data.host_parts(evil) == ("github.com.", "evil.example")
    assert data.host_parts("https://www.github.com/a") == ("", "github.com")
    assert data.host_parts("https://shop.example.co.uk/") == ("shop.", "example.co.uk")
    assert data.host_parts("http://10.0.0.5:8080/") == ("", "10.0.0.5")
    src = (data.Path(data.__file__).parent / "web" / "app.js").read_text()
    css = (data.Path(data.__file__).parent / "web" / "style.css").read_text()
    assert (
        "if (bh !== linkHost(v)) return" in src
        and "h('span', {className:'lk-dom'}" in src
        and ".lk .t .lk-dom{flex:none" in css
        and "direction:rtl" in css
    )


def test_a_host_the_browser_reads_differently_is_shown_as_a_plain_link():
    """Parser differential: Python reads evil.example, the browser github.com; the page then shows the browser's."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node is not installed")
    url = "https://github.com\\@evil.example/"
    head, dom = data.host_parts(url)
    src = (data.Path(data.__file__).parent / "web" / "app.js").read_text()
    lines = [
        ln for ln in src.splitlines() if ln.strip().startswith(("const browserHost =", "const linkHost ="))
    ]
    assert len(lines) == 2
    js = (
        "\n".join(lines)
        + f"\nconsole.log(JSON.stringify([browserHost({json.dumps(url)}), linkHost({json.dumps({'host_head': head, 'domain': dom})})]))"
    )
    browser, ours = json.loads(
        subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    )
    assert browser == "github.com" and ours == "evil.example"  # differ -> linkSub shows "Link · github.com"


def test_reference_ops_reach_core_for_all_four_kinds(ws, tmp_path):
    import sys

    pytest.importorskip("cryptography")  # the real CLI runs in a subprocess; this venv may lack the core deps
    command = tmp_path / "orch-core"
    src = Path(__file__).resolve().parents[3] / "workspace" / "src"
    command.write_text(
        f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(src)!r})\n"
        "from orch.cli import main\nraise SystemExit(main())\n"
    )
    command.chmod(0o700)
    (ws / "notes.md").write_text("# Notes")
    artifacts = ws / ".orch/tickets/t_weekly01/artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "result.txt").write_text("Result")
    targets = [
        ("t_other000x", "ticket"),
        ("https://example.com/spec", "url"),
        ("notes.md", "file"),
        ("artifact:result.txt", "artifact"),
    ]
    for target, kind in targets:
        code, text, _ = actions.run_op(
            ws, str(command), "ref.add", {"ticket": "t_weekly01", "target": target}
        )
        assert code == 200, text
        t = json.loads((ws / ".orch/tickets/t_weekly01.json").read_text())
        assert t["refs"][-1]["kind"] == kind
    before = len(t["refs"])
    code, text, _ = actions.run_op(ws, str(command), "ref.rm", {"ticket": "t_weekly01", "n": before})
    assert code == 200, text
    assert len(json.loads((ws / ".orch/tickets/t_weekly01.json").read_text())["refs"]) == before - 1


def test_references_carry_their_stored_number(ws):
    """A stored reference flagged local is dropped from the page, but the others keep their stored numbers
    (the ones `orch ref list` and `orch ref rm` use)."""
    f = ws / ".orch/tickets/t_weekly01.json"
    t = json.loads(f.read_text())
    t["refs"] = [
        {"kind": "url", "url": "https://example.com/a"},
        {"kind": "file", "path": "x.md", "local": True},
        {"kind": "url", "url": "https://example.com/c"},
    ]
    f.write_text(json.dumps(t))
    shown = next(x for x in data.load_state(ws)["tickets"] if x["id"] == "t_weekly01")["refs"]
    assert [(r["url"], r["n"]) for r in shown] == [("https://example.com/a", 1), ("https://example.com/c", 3)]

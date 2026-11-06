"""Ticket links and add-on fields in the dashboard: the three new ops (link.add, link.remove, ticket.field), the
refresh answer, and the link view the page gets from the core's one link module (orch.links)."""
import json
import threading

import pytest

from orch_dashboard import actions, data

from .test_act import acts, calls, post

ADDONS = [{"name": "alpha", "active": True, "acts": ["refresh"],
           "ticket_links": [{"kind": "github-pr", "label": "Pull request", "icon": "git-pull-request",
                             "match": ["https://github.com/*/*/pull/*"], "statuses": ["open", "merged"]}],
           "ticket_fields": {"section": "Campaign", "show_on_card": ["channel"],
                             "fields": [{"key": "channel", "title": "Channel", "type": "choice", "read_only": False,
                                         "hidden": False, "options": [{"value": "youtube", "label": "YouTube"}]},
                                        {"key": "pr", "title": "PR status", "type": "text", "read_only": True, "hidden": False},
                                        {"key": "x", "title": "<b>", "type": "evil", "read_only": False, "hidden": False}]}},
          {"name": "beta", "active": False, "ticket_links": [{"kind": "campaign", "label": "Campaign", "icon": "megaphone",
                                                             "match": ["https://ads.example/*"]}]}]


@pytest.fixture
def base(act_orch, ws):
    from orch_dashboard.server import make_server
    src = act_orch.read_text().replace(
        'if a[:2] in (["addon", "list"]',
        f'if a[:2] == ["addon", "list"]:\n    print(json.dumps({ADDONS!r}).replace("True", "true").replace("False", "false"))\n    sys.exit(0)\n'
        'if a[1:3] == ["act", "refresh"]:\n    print(json.dumps({"ticket": "t_abcdef", "changes": [{"field": "status"}], "say": "PR #4 was merged."}))\n'
        '    sys.exit(0)\nif a[:2] in (["addon", "list"]')
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
        ({"op": "link.add", "args": {"ticket": "t_abcdef", "url": "https://github.com/a/b/pull/4"}},
         ["link", "add", "t_abcdef", *common, "--", "https://github.com/a/b/pull/4"]),
        ({"op": "link.add", "args": {"ticket": "t_abcdef", "url": "http://intranet.local/x", "title": "--Runbook"}},
         ["link", "add", "t_abcdef", "--title=--Runbook", *common, "--", "http://intranet.local/x"]),
        ({"op": "link.remove", "args": {"ticket": "t_abcdef", "url": "https://github.com/a/b/pull/4"}},
         ["link", "remove", "t_abcdef", *common, "--", "https://github.com/a/b/pull/4"]),
        ({"op": "ticket.field", "args": {"ticket": "t_abcdef", "addon": "alpha", "field": "channel", "value": "youtube",
                                         "if_revision": 3}},
         ["ticket", "set", "t_abcdef", "alpha.channel", "--if-revision=3", *common, "--", "youtube"]),
        ({"op": "ticket.field", "args": {"ticket": "t_abcdef", "addon": "alpha", "field": "budget", "value": ""}},
         ["ticket", "set", "t_abcdef", "alpha.budget", *common, "--", ""]),
    ]
    for body, want in cases:
        code, text, _ = post(base, body)
        assert code == 200, (body, text)
        assert acts(act_orch)[-1] == want, body


@pytest.mark.parametrize("body", [
    {"op": "link.add", "args": {"ticket": "t_abcdef", "url": "javascript:alert(1)"}},
    {"op": "link.add", "args": {"ticket": "t_abcdef", "url": "file:///etc/passwd"}},
    {"op": "link.add", "args": {"ticket": "t_abcdef", "url": "https://a.example/x y"}},
    {"op": "link.add", "args": {"ticket": "t_abcdef", "url": "https://a.example/\x1b[2J"}},
    {"op": "link.add", "args": {"ticket": "t_abcdef", "url": "https://a.example/", "title": "two\nlines"}},
    {"op": "link.add", "args": {"ticket": "--evil", "url": "https://a.example/"}},
    {"op": "link.add", "args": {"ticket": "t_abcdef", "url": "https://a.example/", "kind": "x"}},
    {"op": "link.remove", "args": {"ticket": "t_abcdef", "url": "1"}},
    {"op": "ticket.field", "args": {"ticket": "t_abcdef", "addon": "beta", "field": "x", "value": "1"}},  # off
    {"op": "ticket.field", "args": {"ticket": "t_abcdef", "addon": "gamma", "field": "x", "value": "1"}},  # unknown
    {"op": "ticket.field", "args": {"ticket": "t_abcdef", "addon": "ticket", "field": "x", "value": "1"}},  # core
    {"op": "ticket.field", "args": {"ticket": "t_abcdef", "addon": "alpha", "field": "a.b", "value": "1"}},
    {"op": "ticket.field", "args": {"ticket": "t_abcdef", "addon": "alpha", "field": "x", "value": 5}},
])
def test_bad_link_and_field_requests_are_refused(base, act_orch, body):
    assert post(base, body)[0] == 400, body
    assert not any(c[:1] in (["link"],) or c[:2] == ["ticket", "set"] for c in calls(act_orch))


def test_refresh_answer_comes_back_with_the_state(base, act_orch):
    code, text, _ = post(base, {"op": "addon.act", "args": {"addon": "alpha", "verb": "refresh", "target": "t_abcdef"}})
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
    t = {"links": [{"kind": "github-pr", "url": "https://github.com/a/b/pull/4", "status": "merged"},
                   {"kind": "campaign", "url": "https://ads.example/c/1", "status": "live"},
                   {"type": "ticket", "url": "t_abcdef"}]}
    data.add_link_views([t], data.link_kinds(ADDONS))
    pr, camp, internal = t["links"]
    assert (pr["view"]["label"], pr["view"]["status"], pr["view"]["group"]) == ("GitHub · Pull request", "merged", "Pull request")
    assert (camp["view"]["label"], camp["view"]["status"]) == ("Link", None)  # its add-on is off
    assert internal["view"]["label"] == "Link"
    snap = {"links": [{"kind": "github-pr", "url": "https://github.com/a/b/pull/4", "status": "merged"}]}
    data.add_link_views([snap], [])  # a shared copy names no add-on
    assert (snap["links"][0]["view"]["label"], snap["links"][0]["view"]["status"]) == ("GitHub", None)


def test_page_renders_links_with_text_only_and_safe_hrefs():
    src = (data.Path(data.__file__).parent / "web" / "app.js").read_text()
    for fn in ("function linkRow", "function linksCard", "function fieldSections", "function cardLinks", "function linkGroups"):
        assert fn in src
    body = src[src.index("// ---- Ticket links and add-on fields"):src.index("function liveLinkFor")]
    assert "innerHTML" not in body and "safeHref" in body and "rel:'noopener noreferrer'" in body


def test_a_link_always_shows_its_real_host_and_no_borrowed_site_icon():
    kinds = data.link_kinds([{"name": "gamma", "active": True, "ticket_links": [
        {"kind": "gh-like", "label": "GitHub PR", "icon": "github", "match": ["https://github.com/*"]}]}])
    t = {"links": [{"kind": "gh-like", "url": "https://evil.example/acme/pull/1"}]}
    data.add_link_views([t], kinds)
    v = t["links"][0]["view"]
    assert (v["label"], v["icon"], v["host"]) == ("GitHub PR", "link", "evil.example")
    assert (v["shown_type"], v["host_head"], v["domain"]) == ("Link", "", "evil.example")


def test_link_type_is_an_allowlist_and_the_domain_is_the_registrable_part():
    from orch import links

    evil = "https://github.com.evil.example/x"
    for label in ("github\u0323com", "github\uff0ecom", "GitHub", "Pull\u202erequest", "a" * 25, "x.y", "a  b", "My GitHub PR", "GitHub-PR"):
        assert data.shown_type(label, evil, links) == "Link", label
    assert data.shown_type("GitHub · Pull request", evil, links) == "Pull request"
    assert data.shown_type("GitHub · Pull request", "https://github.com/a/b/pull/1", links) == "GitHub · Pull request"
    assert data.shown_type("Kampagne Zürich", evil, links) == "Kampagne Zürich"
    assert data.host_parts(evil) == ("github.com.", "evil.example")
    assert data.host_parts("https://www.github.com/a") == ("", "github.com")
    assert data.host_parts("https://shop.example.co.uk/") == ("shop.", "example.co.uk")
    assert data.host_parts("http://10.0.0.5:8080/") == ("", "10.0.0.5")
    src = (data.Path(data.__file__).parent / "web" / "app.js").read_text()
    css = (data.Path(data.__file__).parent / "web" / "style.css").read_text()
    assert "if (bh !== linkHost(v)) return" in src and "h('span', {className:'lk-dom'}" in src and ".lk .t .lk-dom{flex:none" in css and "direction:rtl" in css


def test_a_host_the_browser_reads_differently_is_shown_as_a_plain_link():
    """Parser differential: Python reads evil.example, the browser github.com; the page then shows the browser's."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node is not installed")
    url = "https://github.com\\@evil.example/"
    head, dom = data.host_parts(url)
    src = (data.Path(data.__file__).parent / "web" / "app.js").read_text()
    lines = [ln for ln in src.splitlines() if ln.strip().startswith(("const browserHost =", "const linkHost ="))]
    assert len(lines) == 2
    js = "\n".join(lines) + f"\nconsole.log(JSON.stringify([browserHost({json.dumps(url)}), linkHost({json.dumps({'host_head': head, 'domain': dom})})]))"
    browser, ours = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert browser == "github.com" and ours == "evil.example"  # differ -> linkSub shows "Link · github.com"

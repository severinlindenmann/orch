"""Ticket links (kind, known sites, add-on link types), add-on fields (`orch ticket set`), refresh act."""

import json
import os
import stat
import sys
import textwrap

import pytest
from test_addons import install, make_addon, run, uv_calls  # noqa: F401

from orch import addons, links, phone_view, tickets
from orch.errors import Refused

LINKS = """
[[ticket_links]]
kind = "github-pr"
label = "Pull request"
icon = "git-pull-request"
match = "https://github.com/*/*/pull/*"
statuses = ["open", "review", "merged", "closed"]

[[ticket_links]]
kind = "campaign"
label = "Campaign"
icon = "megaphone"
match = ["https://ads.acme.example/campaigns/*"]

[ticket_fields]
section = "Campaign"
show_on_card = ["channel"]

[acts.refresh]
summary = "Update link titles and status"
writes = ["links", "ext.hello"]
"""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "channel": {
            "title": "Channel",
            "type": "string",
            "enum": ["youtube", "newsletter"],
            "x-labels": {"youtube": "YouTube", "newsletter": "Newsletter"},
        },
        "budget": {"title": "Budget", "type": "number", "minimum": 0},
        "launch_date": {"title": "Launch date", "type": "string", "format": "date"},
        "brief": {"title": "Brief", "type": "string", "format": "uri"},
        "audience": {"title": "Audience", "type": "string", "maxLength": 10},
        "pr_status": {"title": "PR status", "type": "string", "readOnly": True},
        "currency": {"type": "string", "x-hidden": True},
    },
}

# The example refresh act: GitHub pull request state through `gh pr view <url> --json state,title`.
REFRESH = textwrap.dedent(
    """\
    import json, os, shutil, subprocess, sys
    from pathlib import Path
    argv = sys.argv[1:]
    if argv[:2] != ["act", "refresh"]:
        sys.exit(2)
    tid = argv[-1]
    t = json.loads(Path(os.environ["ORCH_ROOT"], ".orch", "tickets", tid + ".json").read_text())
    prs = [ln for ln in t["links"] if ln.get("kind") == "github-pr"]
    if not prs:
        print(json.dumps({"ticket": tid, "links": [], "say": "Nothing to update (no GitHub links)"}))
        sys.exit(0)
    if not shutil.which("gh"):
        print(json.dumps({"ticket": tid, "links": [], "say": "gh is not installed here, nothing updated."}))
        sys.exit(0)
    out, last = [], None
    for ln in prs:
        cmd = ["gh", "pr", "view", ln["url"], "--json", "state,title"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            continue
        pr = json.loads(r.stdout)
        last = {"OPEN": "open", "MERGED": "merged", "CLOSED": "closed"}.get(pr["state"], "open")
        out.append({"url": ln["url"], "title": pr["title"], "status": last})
    res = {"ticket": tid, "links": out}
    if last:
        res["ext"] = {"hello": {"pr_status": last}}
    print(json.dumps(res))
    """
)


@pytest.fixture
def hello(tmp_path, monkeypatch, uv_calls):  # noqa: F811
    folder = make_addon(tmp_path / "src-addons", extra=LINKS)
    pkg = folder / "src" / "orch_hello"
    (pkg / "ext.schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    (pkg / "__main__.py").write_text(REFRESH, encoding="utf-8")
    eps = {}
    monkeypatch.setattr(addons, "_entry_points", lambda: dict(eps))
    orig = addons.run_uv

    def fake_uv(args):
        orig(args)
        sys.path.insert(0, str(folder / "src"))
        monkeypatch.setenv("PYTHONPATH", str(folder / "src"))
        eps["hello"] = "orch_hello"

    monkeypatch.setattr(addons, "run_uv", fake_uv)
    yield folder
    if str(folder / "src") in sys.path:
        sys.path.remove(str(folder / "src"))


@pytest.fixture
def tid(proj, run):  # noqa: F811
    code, out, err = run("ticket", "new", "Invoice CSV export", "--json", "--by", "human:anna")
    assert code == 0, err
    return json.loads(out)["id"]


def jrun(run, *argv):  # noqa: F811
    code, out, err = run(*argv, "--json")
    assert code == 0, err
    return json.loads(out)


# ---- the shared module ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,name",
    [
        ("https://github.com/acme/billing/pull/418", "GitHub"),
        ("https://acme.atlassian.net/wiki/spaces/FIN/pages/88213", "Confluence"),
        ("https://acme.atlassian.net/browse/BIL-7", "Jira"),
        ("https://www.notion.so/acme/Winter-6f1c2a", "Notion"),
        ("https://www.figma.com/design/k2Lq9/Billing?node-id=12-40", "Figma"),
        ("https://youtu.be/Qx7mW2pLk9A", "YouTube"),
        ("https://www.youtube.com/watch?v=Qx7mW2pLk9A", "YouTube"),
        ("https://docs.google.com/document/d/9xY/edit", "Google Docs"),
        ("https://docs.google.com/spreadsheets/d/1aB9/edit", "Google Sheets"),
        ("https://linear.app/acme/issue/BIL-77", "Linear"),
        ("https://acme.slack.com/archives/C1", "Slack"),
    ],
)
def test_known_sites(url, name):
    assert links.site(url)["name"] == name


def test_unknown_and_lookalike_hosts_are_plain_links():
    for url in (
        "https://intranet.acme.local/runbooks/42",
        "https://github.com.evil.example/x",
        "https://notgithub.com/",
    ):
        d = links.describe({"kind": "link", "url": url}, [])
        assert (d["label"], d["icon"]) == ("Link", "link"), url
    d = links.describe({"kind": "link", "url": "https://intranet.acme.local/runbooks/42"}, [])
    assert d["title"] == "intranet.acme.local/runbooks/42"


@pytest.mark.parametrize(
    "url",
    ["", "ftp://x.example/a", "javascript:alert(1)", "file:///etc/passwd", "https://", "https://a b.example"],
)
def test_only_http_links(url):
    with pytest.raises(Refused, match="https://"):
        links.check_url(url)


def test_add_on_kind_wins_and_off_falls_back_to_the_site():
    kinds = [
        {
            "kind": "github-pr",
            "label": "Pull request",
            "icon": "git-pull-request",
            "match": ["https://github.com/*/*/pull/*"],
            "addon": "github",
        }
    ]
    url = "https://github.com/acme/billing/pull/418"
    assert links.kind_for(url, kinds) == "github-pr"
    assert links.kind_for("https://github.com/acme/billing/issues/3", kinds) == "link"
    assert (
        links.kind_for("https://github.com/acme/billing/pull/418/files", kinds) == "github-pr"
    )  # * at the end
    ln = {"kind": "github-pr", "url": url, "status": "open"}
    on = links.describe(ln, kinds)
    assert (on["label"], on["icon"], on["status"], on["group"]) == (
        "GitHub · Pull request",
        "github",
        "open",
        "Pull request",
    )
    off = links.describe(ln, [])
    assert (off["label"], off["status"], off["group"]) == ("GitHub", None, "Links")


def test_old_type_links_still_read():
    d = links.describe({"type": "github", "url": "https://github.com/a/b/pull/1", "title": "PR 1"}, [])
    assert (d["kind"], d["label"], d["title"]) == ("github", "GitHub", "PR 1")


# ---- orch link add / list / remove ------------------------------------------------------------------------


def test_link_add_list_remove(proj, run, tid, validate):  # noqa: F811
    ln = jrun(run, "link", "add", tid, "https://intranet.acme.local/runbooks/42", "--by", "agent:dev-1")
    assert ln["kind"] == "link" and ln["by"] == "agent:dev-1" and ln["at"].endswith("Z") and "title" not in ln
    code, out, _ = run(
        "link", "add", tid, "https://www.figma.com/design/k2Lq9/Billing", "--title", "Export states"
    )
    assert code == 0 and out.strip().endswith('→ Figma "Export states"')
    code, out, _ = run("link", "list", tid)
    lines = out.splitlines()
    assert lines[0].split() == ["1", "Link", "intranet.acme.local/runbooks/42"]
    assert lines[1].split()[:3] == ["2", "Figma", "Export"]
    validate(tickets.load(proj, tid))
    code, out, _ = run("link", "remove", tid, "1")
    assert code == 0 and "Removed link 1" in out
    t = tickets.load(proj, tid)
    assert [ln["url"] for ln in t["links"]] == ["https://www.figma.com/design/k2Lq9/Billing"]
    assert "Removed link intranet.acme.local/runbooks/42" in t["history"][-1]["text"]
    assert run("link", "remove", tid, "9")[0] == 2


def test_link_add_refuses_non_web_and_is_one_entry_per_address(proj, run, tid):  # noqa: F811
    code, _, err = run("link", "add", tid, "file:///tmp/a.txt")
    assert code == 2 and "https://" in err
    url = "https://example.com/a"
    run("link", "add", tid, url)
    code, out, _ = run("link", "add", tid, url)
    assert code == 0 and "already has this link" in out
    run("link", "add", tid, url, "--title", "Now with a title")
    t = tickets.load(proj, tid)
    assert len(t["links"]) == 1 and t["links"][0]["title"] == "Now with a title"


def test_old_flags_still_work(proj, run, tid):  # noqa: F811
    code, _, err = run("link", "add", tid, "--type", "jira", "--url", "https://acme.atlassian.net/browse/X-1")
    assert code == 0, err
    assert tickets.load(proj, tid)["links"][0]["kind"] == "jira"


def test_active_add_on_sets_the_kind(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    code, out, _ = run("link", "add", tid, "https://github.com/acme/billing/pull/418")
    assert code == 0 and "→ Pull request github.com/acme/billing/pull/418" in out
    assert tickets.load(proj, tid)["links"][0]["kind"] == "github-pr"
    rows = jrun(run, "link", "list", tid)
    assert rows[0]["view"]["label"] == "GitHub · Pull request"
    lst = {a["name"]: a for a in jrun(run, "addon", "list")}["hello"]
    assert [k["kind"] for k in lst["ticket_links"]] == ["github-pr", "campaign"]
    assert lst["ticket_fields"]["section"] == "Campaign" and lst["acts"] == ["refresh"]
    assert {f["key"]: f["type"] for f in lst["ticket_fields"]["fields"]} == {
        "channel": "choice",
        "budget": "number",
        "launch_date": "date",
        "brief": "url",
        "audience": "text",
        "pr_status": "text",
        "currency": "text",
    }


def test_inactive_add_on_link_shows_as_plain_link(proj, run, tid):  # noqa: F811
    t = tickets.load(proj, tid)
    t["links"].append(
        {"kind": "campaign", "url": "https://ads.acme.example/campaigns/4471", "status": "planned"}
    )
    tickets.save(proj, t)
    d = links.describe(t["links"][0], links.active_kinds(proj))
    assert (d["label"], d["status"]) == ("Link", None)


# ---- add-on fields ----------------------------------------------------------------------------------------


def test_ticket_set_fields(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    code, out, _ = run("ticket", "set", tid, "hello.budget", "2400")
    assert code == 0 and out.strip().endswith("Campaign · Budget: 2400")
    run("ticket", "set", tid, "hello.channel", "YouTube")
    run("ticket", "set", tid, "hello.launch_date", "2026-12-01")
    assert tickets.load(proj, tid)["ext"]["hello"] == {
        "budget": 2400,
        "channel": "youtube",
        "launch_date": "2026-12-01",
    }
    code, _, err = run("ticket", "set", tid, "hello.channel", "radio")
    assert code == 2 and 'Can\'t set Channel to "radio". Pick one of: YouTube, Newsletter.' in err
    code, _, err = run("ticket", "set", tid, "hello.pr_status", "merged")
    assert code == 2 and "filled in by the Hello add-on. Run: orch hello act refresh -- " in err
    for field, value, words in (
        ("budget", "lots", "Budget must be a number"),
        ("budget", "-1", "at least 0"),
        ("launch_date", "1 Dec", "a day like"),
        ("brief", "notion.so/x", "web address"),
        ("audience", "far too long text", "at most 10"),
        ("nope", "x", "Campaign has no field nope"),
    ):
        code, _, err = run("ticket", "set", tid, f"hello.{field}", value)
        assert code == 2 and words in err, (field, err)
    run("ticket", "set", tid, "hello.budget", "")
    assert "budget" not in tickets.load(proj, tid)["ext"]["hello"]


def test_ticket_set_needs_an_active_add_on(proj, run, tid):  # noqa: F811
    code, _, err = run("ticket", "set", tid, "marketing.budget", "1")
    assert code == 2 and "no add-on field" in err


# ---- refresh act ------------------------------------------------------------------------------------------


def _fake_gh(tmp_path, monkeypatch, state="MERGED"):
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    gh = b / "gh"
    gh.write_text(f'#!/bin/sh\necho \'{{"state": "{state}", "title": "Add CSV export for invoices"}}\'\n')
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")


@pytest.mark.skipif(os.name == "nt", reason="fake gh is a shell script")
def test_refresh_merges_status_title_and_own_ext(proj, run, hello, tid, tmp_path, monkeypatch, validate):  # noqa: F811
    install(run, hello)
    run("link", "add", tid, "https://github.com/acme/billing/pull/418")
    run("link", "add", tid, "https://example.com/other", "--title", "Other")
    _fake_gh(tmp_path, monkeypatch)
    code, out, err = run("hello", "act", "refresh", "--by", "human:anna", "--json", "--", tid)
    assert code == 0, err
    res = json.loads(out)
    assert [(c["field"], c["new"]) for c in res["changes"]] == [
        ("title", "Add CSV export for invoices"),
        ("status", "merged"),
        ("pr_status", "merged"),
    ]
    t = tickets.load(proj, tid)
    pr = t["links"][0]
    assert (pr["title"], pr["status"]) == ("Add CSV export for invoices", "merged")
    assert t["links"][1] == {**t["links"][1], "title": "Other"} and "status" not in t["links"][1]
    assert t["ext"]["hello"]["pr_status"] == "merged"
    assert [h["by"] for h in t["history"][-3:]] == ["human:anna"] * 3
    validate(t)
    rev = t["revision"]
    code, out, _ = run("hello", "act", "refresh", "--", tid)  # nothing new: no write
    assert code == 0 and "Nothing to update" in out and tickets.load(proj, tid)["revision"] == rev


def test_refresh_merge_keeps_to_its_own_fields(proj, tid):
    tickets.link_add(proj, tid, "https://github.com/a/b/pull/1", "human:x", "github-pr")
    with pytest.raises(Refused, match="only update links and ext.hello"):
        tickets.merge_refresh(proj, tid, "hello", {"ext": {"other": {"x": 1}}}, "human:x", None)
    out = {
        "links": [{"url": "https://github.com/a/b/pull/1", "status": "<b>x</b>", "kind": "evil", "url2": 1}]
    }
    _, changes = tickets.merge_refresh(proj, tid, "hello", out, "human:x", None)
    assert changes == [] and tickets.load(proj, tid)["links"][0]["kind"] == "github-pr"


def test_refresh_with_no_add_on_links(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    code, out, _ = run("hello", "act", "refresh", "--", tid)
    assert code == 0 and "Nothing to update (no GitHub links)" in out


# ---- phone ------------------------------------------------------------------------------------------------


def test_phone_view_link_carries_label_icon_status(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    run("link", "add", tid, "https://github.com/acme/billing/pull/418")
    run("link", "add", tid, "https://intranet.acme.local/x")
    t = tickets.load(proj, tid)
    t["links"][0]["status"] = "review"
    tickets.save(proj, t)
    atts = phone_view.attachments(proj, tickets.load(proj, tid), None, upload=False)
    by_url = {a["url"]: a for a in atts}
    pr = by_url["https://github.com/acme/billing/pull/418"]
    assert (pr["label"], pr["icon"], pr["mono"], pr["status"]) == (
        "GitHub · Pull request",
        "github",
        "GH",
        "review",
    )
    plain = by_url["https://intranet.acme.local/x"]
    assert (plain["label"], plain["icon"]) == ("Link", "link") and "status" not in plain


# ---- no terminal escapes from titles, add-on answers or fields -------------------------------------------

ESC = "\x1b]8;;https://evil.example\x07click\x1b[2J"
C1 = "\x9b31m"


def _clean(text: str) -> bool:
    return not any((ord(c) < 32 and c != "\n") or 0x7F <= ord(c) <= 0x9F or c in "\u202e\u200b" for c in text)


def test_link_title_escapes_are_cut_on_write_and_show(proj, run, tid):  # noqa: F811
    code, out, _ = run("link", "add", tid, "https://example.com/a", "--title", f"Spec{ESC}{C1}\u202e end")
    assert code == 0 and _clean(out)
    title = tickets.load(proj, tid)["links"][0]["title"]
    assert _clean(title) and title.startswith("Spec") and title.endswith("end")
    t = tickets.load(proj, tid)
    t["links"].append(
        {"kind": "link", "url": "https://example.com/b", "title": f"old{ESC}{C1}"}
    )  # an old file
    tickets.save(proj, t)
    for argv in (("link", "list", tid), ("ticket", "show", tid)):
        assert _clean(run(*argv)[1].replace("\n", " "))
    assert run("link", "add", tid, f"https://example.com/{C1}x")[0] == 2


def test_refresh_title_and_say_escapes_are_cut(proj, tid):
    tickets.link_add(proj, tid, "https://github.com/a/b/pull/1", "human:x", "github-pr")
    out = {"links": [{"url": "https://github.com/a/b/pull/1", "title": f"PR{ESC}{C1}"}], "say": ESC}
    t, changes = tickets.merge_refresh(proj, tid, "hello", out, "human:x", None)
    assert _clean(t["links"][0]["title"]) and _clean(changes[0]["new"]) and _clean(t["history"][-1]["text"])
    assert _clean(links.one_line(ESC + C1))


def test_text_field_escapes_are_cut(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    code, out, _ = run("ticket", "set", tid, "hello.audience", f"a\x1b[2J{C1}b")
    assert code == 0 and _clean(out) and _clean(tickets.load(proj, tid)["ext"]["hello"]["audience"])
    code, _, err = run("ticket", "set", tid, "hello.channel", f"x{C1}{ESC}")
    assert code == 2 and _clean(err.replace("\n", " "))


def test_numbers_refuse_commas_and_not_finite(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    for bad in ("2,5", "nan", "inf", "1e400"):
        code, _, err = run("ticket", "set", tid, "hello.budget", bad)
        assert code == 2 and "must be a number" in err, bad
    assert run("ticket", "set", tid, "hello.budget", "2’400.5")[0] == 0
    assert tickets.load(proj, tid)["ext"]["hello"]["budget"] == 2400.5


def test_trailing_star_needs_something_and_subdomains_count():
    kinds = [
        {"kind": "pr", "label": "PR", "icon": "x", "match": ["https://github.com/*/*/pull/*"], "addon": "a"}
    ]
    assert links.kind_for("https://github.com/a/b/pull/", kinds) == "link"
    assert links.site("https://gist.github.com/x")["name"] == "GitHub"


def test_old_type_flag_sets_the_kind_and_link_is_plain(proj, run, tid):  # noqa: F811
    run("link", "add", tid, "--type", "github", "--url", "https://example.com/a")
    run("link", "add", tid, "--type", "link", "--url", "https://example.com/b")
    assert [ln["kind"] for ln in tickets.load(proj, tid)["links"]] == ["github", "link"]


def test_refresh_who_people_refuses_agents(proj, run, hello, tid):  # noqa: F811
    m = hello / "src" / "orch_hello" / "orch-addon.toml"
    m.write_text(
        m.read_text().replace(
            'summary = "Update link titles and status"', 'summary = "Update"\nwho = "people"'
        )
    )
    install(run, hello)
    code, _, err = run("hello", "act", "refresh", "--by", "agent:claude", "--", tid)
    assert code == 2 and "Only a person" in err
    assert run("hello", "act", "refresh", "--by", "human:anna", "--", tid)[0] == 0

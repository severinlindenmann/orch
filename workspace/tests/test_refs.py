"""Ticket links (kind, known sites, add-on link types), add-on fields (`orch ticket set`), refresh act."""

import json
import os
import stat
import sys
import textwrap

import pytest
from test_addons import install, make_addon, run, uv_calls  # noqa: F401

from orch import addons, phone_view, refs, tickets
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
writes = ["refs", "ext.hello"]
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
    prs = [ln for ln in t["refs"] if ln.get("kind") == "github-pr"]
    if not prs:
        print(json.dumps({"ticket": tid, "refs": [], "say": "Nothing to update (no GitHub links)"}))
        sys.exit(0)
    if not shutil.which("gh"):
        print(json.dumps({"ticket": tid, "refs": [], "say": "gh is not installed here, nothing updated."}))
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
    res = {"ticket": tid, "refs": out}
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
    assert refs.site(url)["name"] == name


def test_unknown_and_lookalike_hosts_are_plain_links():
    for url in (
        "https://intranet.acme.local/runbooks/42",
        "https://github.com.evil.example/x",
        "https://notgithub.com/",
    ):
        d = refs.describe({"kind": "url", "url": url}, [])
        assert (d["label"], d["icon"]) == ("Reference", "link"), url
    d = refs.describe({"kind": "url", "url": "https://intranet.acme.local/runbooks/42"}, [])
    assert d["title"] == "intranet.acme.local/runbooks/42"


@pytest.mark.parametrize(
    "url",
    ["", "ftp://x.example/a", "javascript:alert(1)", "file:///etc/passwd", "https://", "https://a b.example"],
)
def test_only_http_links(url):
    with pytest.raises(Refused, match="https://"):
        refs.check_url(url)


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
    assert refs.kind_for(url, kinds) == "github-pr"
    assert refs.kind_for("https://github.com/acme/billing/issues/3", kinds) == "url"
    assert (
        refs.kind_for("https://github.com/acme/billing/pull/418/files", kinds) == "github-pr"
    )  # * at the end
    ln = {"kind": "github-pr", "url": url, "status": "open"}
    on = refs.describe(ln, kinds)
    assert (on["label"], on["icon"], on["status"], on["group"]) == (
        "GitHub · Pull request",
        "github",
        "open",
        "Pull request",
    )
    off = refs.describe(ln, [])
    assert (off["label"], off["status"], off["group"]) == ("GitHub", None, "References")


def test_addon_type_on_another_host_shows_the_real_host_and_no_site_icon():
    kinds = [
        {
            "kind": "github-pr",
            "label": "GitHub PR",
            "icon": "github",
            "match": ["https://github.com/*"],
            "addon": "gh",
        }
    ]
    d = refs.describe({"kind": "github-pr", "url": "https://evil.example/acme/pull/1"}, kinds)
    assert (d["label"], d["icon"], d["host"]) == ("GitHub PR", "link", "evil.example")
    real = refs.describe({"kind": "github-pr", "url": "https://www.github.com/a/b/pull/1"}, kinds)
    assert (real["icon"], real["host"]) == ("github", "github.com")


def test_ref_add_list_remove(proj, run, tid, validate):  # noqa: F811
    ln = jrun(run, "ref", "add", tid, "https://intranet.acme.local/runbooks/42", "--by", "agent:dev-1")
    assert ln["kind"] == "url" and ln["by"] == "agent:dev-1" and ln["at"].endswith("Z") and "title" not in ln
    code, out, _ = run(
        "ref", "add", tid, "https://www.figma.com/design/k2Lq9/Billing", "--title", "Export states"
    )
    assert code == 0 and "Added reference to" in out
    code, out, _ = run("ref", "list", tid)
    lines = out.splitlines()
    assert lines[0].split() == ["1", "Reference", "intranet.acme.local/runbooks/42"]
    assert lines[1].split()[:3] == ["2", "Figma", "Export"]
    validate(tickets.load(proj, tid))
    code, out, _ = run("ref", "rm", tid, "1")
    assert code == 0 and "Removed reference 1" in out
    t = tickets.load(proj, tid)
    assert [ln["url"] for ln in t["refs"]] == ["https://www.figma.com/design/k2Lq9/Billing"]
    assert "Removed reference https://intranet.acme.local/runbooks/42" in t["history"][-1]["text"]
    assert run("ref", "rm", tid, "9")[0] == 2


def test_ref_add_refuses_non_web_and_is_one_entry_per_address(proj, run, tid):  # noqa: F811
    code, _, err = run("ref", "add", tid, "file:///tmp/a.txt")
    assert code == 2 and "https://" in err
    url = "https://example.com/a"
    run("ref", "add", tid, url)
    code, out, _ = run("ref", "add", tid, url)
    assert code == 0 and "already has this reference" in out
    run("ref", "add", tid, url, "--title", "Now with a title")
    t = tickets.load(proj, tid)
    assert len(t["refs"]) == 1 and t["refs"][0]["title"] == "Now with a title"


def test_active_add_on_sets_the_kind(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    code, out, _ = run("ref", "add", tid, "https://github.com/acme/billing/pull/418")
    assert code == 0 and "https://github.com/acme/billing/pull/418" in out
    assert tickets.load(proj, tid)["refs"][0]["kind"] == "github-pr"
    rows = jrun(run, "ref", "list", tid)
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
    t["refs"].append(
        {"kind": "campaign", "url": "https://ads.acme.example/campaigns/4471", "status": "planned"}
    )
    tickets.save(proj, t)
    d = refs.describe(t["refs"][0], refs.active_kinds(proj))
    assert (d["label"], d["status"]) == ("Reference", None)


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
    run("ref", "add", tid, "https://github.com/acme/billing/pull/418")
    run("ref", "add", tid, "https://example.com/other", "--title", "Other")
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
    pr = t["refs"][0]
    assert (pr["title"], pr["status"]) == ("Add CSV export for invoices", "merged")
    assert t["refs"][1] == {**t["refs"][1], "title": "Other"} and "status" not in t["refs"][1]
    assert t["ext"]["hello"]["pr_status"] == "merged"
    assert [h["by"] for h in t["history"][-3:]] == ["human:anna"] * 3
    validate(t)
    rev = t["revision"]
    code, out, _ = run("hello", "act", "refresh", "--", tid)  # nothing new: no write
    assert code == 0 and "Nothing to update" in out and tickets.load(proj, tid)["revision"] == rev


def test_refresh_merge_keeps_to_its_own_fields(proj, tid):
    tickets.ref_add(proj, tid, "https://github.com/a/b/pull/1", "human:x", "github-pr")
    with pytest.raises(Refused, match="only update refs and ext.hello"):
        tickets.merge_refresh(proj, tid, "hello", {"ext": {"other": {"x": 1}}}, "human:x", None)
    out = {
        "refs": [{"url": "https://github.com/a/b/pull/1", "status": "<b>x</b>", "kind": "evil", "url2": 1}]
    }
    _, changes = tickets.merge_refresh(proj, tid, "hello", out, "human:x", None)
    assert changes == [] and tickets.load(proj, tid)["refs"][0]["kind"] == "github-pr"


def test_refresh_with_no_add_on_links(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    code, out, _ = run("hello", "act", "refresh", "--", tid)
    assert code == 0 and "Nothing to update (no GitHub links)" in out


# ---- phone ------------------------------------------------------------------------------------------------


def test_phone_view_link_carries_label_icon_status(proj, run, hello, tid):  # noqa: F811
    install(run, hello)
    run("ref", "add", tid, "https://github.com/acme/billing/pull/418")
    run("ref", "add", tid, "https://intranet.acme.local/x")
    t = tickets.load(proj, tid)
    t["refs"][0]["status"] = "review"
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
    assert (plain["label"], plain["icon"]) == ("Reference", "link") and "status" not in plain


# ---- no terminal escapes from titles, add-on answers or fields -------------------------------------------

ESC = "\x1b]8;;https://evil.example\x07click\x1b[2J"
C1 = "\x9b31m"


def _clean(text: str) -> bool:
    return not any((ord(c) < 32 and c != "\n") or 0x7F <= ord(c) <= 0x9F or c in "\u202e\u200b" for c in text)


def test_link_title_escapes_are_cut_on_write_and_show(proj, run, tid):  # noqa: F811
    code, out, _ = run("ref", "add", tid, "https://example.com/a", "--title", f"Spec{ESC}{C1}\u202e end")
    assert code == 0 and _clean(out)
    title = tickets.load(proj, tid)["refs"][0]["title"]
    assert _clean(title) and title.startswith("Spec") and title.endswith("end")
    t = tickets.load(proj, tid)
    t["refs"].append({"kind": "url", "url": "https://example.com/b", "title": f"old{ESC}{C1}"})  # an old file
    tickets.save(proj, t)
    for argv in (("ref", "list", tid), ("ticket", "show", tid)):
        assert _clean(run(*argv)[1].replace("\n", " "))
    assert run("ref", "add", tid, f"https://example.com/{C1}x")[0] == 2


def test_refresh_title_and_say_escapes_are_cut(proj, tid):
    tickets.ref_add(proj, tid, "https://github.com/a/b/pull/1", "human:x", "github-pr")
    out = {"refs": [{"url": "https://github.com/a/b/pull/1", "title": f"PR{ESC}{C1}"}], "say": ESC}
    t, changes = tickets.merge_refresh(proj, tid, "hello", out, "human:x", None)
    assert _clean(t["refs"][0]["title"]) and _clean(changes[0]["new"]) and _clean(t["history"][-1]["text"])
    assert _clean(refs.one_line(ESC + C1))


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
    assert refs.kind_for("https://github.com/a/b/pull/", kinds) == "url"
    assert refs.site("https://gist.github.com/x")["name"] == "GitHub"


def test_refresh_who_people_refuses_agents(proj, run, hello, tid, monkeypatch):  # noqa: F811
    m = hello / "src" / "orch_hello" / "orch-addon.toml"
    m.write_text(
        m.read_text().replace(
            'summary = "Update link titles and status"', 'summary = "Update"\nwho = "people"'
        )
    )
    install(run, hello)
    code, _, err = run("hello", "act", "refresh", "--by", "agent:claude", "--", tid)
    assert code == 2 and "Only a person" in err
    monkeypatch.setenv("ORCH_AGENT", "claude")  # an agent saying it is a person
    code, _, err = run("hello", "act", "refresh", "--by", "human:anna", "--", tid)
    assert code == 2 and "Only a person" in err
    monkeypatch.delenv("ORCH_AGENT")
    assert run("hello", "act", "refresh", "--by", "human:anna", "--", tid)[0] == 0


@pytest.mark.parametrize(
    "bad",
    [
        "https://github.com\\@evil.example/",
        "https://evil.example\\github.com/",
        "https://github.com@evil.example/",
        "https://user:pw@evil.example/",
        "https://evil.example/\tx",
        "https://evil.example/ x",
    ],
)
def test_url_with_backslash_userinfo_or_whitespace_is_refused(bad):
    with pytest.raises(Refused):
        refs.check_url(bad)


def test_url_is_stored_canonical_with_an_ascii_host():
    assert refs.check_url("HTTPS://GitHub.COM:443/a/b?q=1#f") == "https://github.com:443/a/b?q=1#f"
    homograph = refs.check_url("https://gіthub.com/acme")  # Cyrillic i
    assert homograph.startswith("https://xn--") and homograph.isascii()
    d = refs.describe({"kind": "url", "url": homograph}, [])
    assert d["host"].startswith("xn--") and d["label"] == "Reference" and d["icon"] == "link"


@pytest.mark.parametrize("value", ["docs/spec.md", r"docs\spec.md:40", "docs/./spec.md"])
def test_project_files(proj, run, tid, value, validate):  # noqa: F811
    ref = jrun(run, "ref", "add", tid, value)
    assert ref["kind"] == "file" and ref["path"] == "docs/spec.md"
    assert jrun(run, "ref", "list", tid)[0]["path"] == "docs/spec.md"
    validate(tickets.load(proj, tid))
    assert run("ref", "rm", tid, value)[0] == 0
    assert not tickets.load(proj, tid)["refs"]


def test_ticket_and_artifact_references(proj, run, tid, new_ticket, validate):  # noqa: F811
    other = new_ticket("The other ticket")
    key = tickets.load(proj, other)["key"]
    for target in (key.lower(), other.upper()):
        assert jrun(run, "ref", "add", tid, target)["ticket"] == other
    assert len(tickets.load(proj, tid)["refs"]) == 1
    assert run("ref", "list", tid)[0] == 0
    assert run("ref", "rm", tid, key)[0] == 0
    assert run("ref", "add", tid, tid)[0] == 2
    assert run("ref", "add", tid, "DM-999999")[0] == 2
    assert run("ref", "add", tid, "t_zzzzzz")[0] == 2
    for owner, target in [(tid, "artifact:report.pdf"), (other, f"artifact:{key}/report.pdf")]:
        assert run("ref", "add", tid, target)[0] == 2
        artifact = proj / ".orch" / "tickets" / owner / "artifacts" / "report.pdf"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"report")
        ref = jrun(run, "ref", "add", tid, target)
        assert ref["ticket"] == owner and ref["name"] == "report.pdf"
        assert "title" not in ref and "status" not in ref
        jrun(run, "ref", "add", tid, target)
        assert len(tickets.load(proj, tid)["refs"]) == 1
        assert run("ref", "list", tid)[0] == 0
        validate(tickets.load(proj, tid))
        assert run("ref", "rm", tid, target)[0] == 0
        artifact.unlink()
        artifact.symlink_to(proj / ".orch" / "config.toml")
        assert run("ref", "add", tid, target)[0] == 2


def test_local_reference_is_private(proj, run, tid):  # noqa: F811
    target = str(proj.parent / "private.txt")
    ref = jrun(run, "ref", "add", tid, target)
    assert ref["local"] is True
    assert not tickets.load(proj, tid)["refs"]
    assert target not in (proj / ".orch" / "tickets" / f"{tid}.json").read_text()
    jrun(run, "ref", "add", tid, target)
    assert len(refs.local_refs(proj, tid)) == 1
    assert "local/" in (proj / ".orch" / ".gitignore").read_text().splitlines()
    assert not (proj / ".gitignore").exists()
    assert "On this computer only" in run("ref", "list", tid)[1]
    assert run("ref", "rm", tid, "1")[0] == 0
    assert not refs.local_refs(proj, tid)
    assert jrun(run, "ref", "add", tid, "../private.txt")["local"] is True


def test_project_symlink_outside_refused(proj, run, tid):  # noqa: F811
    (proj / "outside").symlink_to(proj.parent, target_is_directory=True)
    assert run("ref", "add", tid, "outside/private.txt")[0] == 2


def test_namespaced_kind(proj, run, tid):  # noqa: F811
    ref = jrun(run, "ref", "add", tid, "https://example.com/pr", "--kind", "github:pr")
    assert ref["kind"] == "github:pr"
    assert refs.describe(ref, [])["type"] == "Reference"


def test_phone_shows_shared_references_with_current_ticket_title(proj, run, tid, new_ticket):  # noqa: F811
    other = new_ticket("Current title")
    tickets.ref_add(proj, tid, other, "human:test")
    tickets.ref_add(proj, tid, "docs/spec.md:40", "human:test")
    tickets.ref_add(proj, tid, str(proj.parent / "private.txt"), "human:test")
    rows = phone_view.build(proj, tickets.load(proj, tid), [])["refs"]
    assert rows == [
        {"kind": "ticket", "ticket": other, "title": "Current title", "status": "open"},
        {"kind": "file", "path": "docs/spec.md", "line": 40},
    ]


def test_ticket_and_artifact_on_same_ticket_are_distinct(proj, run, tid, new_ticket):  # noqa: F811
    other = new_ticket()
    artifact = proj / ".orch" / "tickets" / other / "artifacts" / "report.pdf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"report")
    tickets.ref_add(proj, tid, f"artifact:{other}/report.pdf", "human:test")
    tickets.ref_add(proj, tid, other, "human:test")
    assert len(tickets.load(proj, tid)["refs"]) == 2
    artifact.unlink()
    tickets.ref_remove(proj, tid, f"artifact:{other}/report.pdf", "human:test")
    assert [r["kind"] for r in tickets.load(proj, tid)["refs"]] == ["ticket"]


def test_no_old_commands_or_flags(proj, run, tid):  # noqa: F811
    for args in [
        ("link", "add", tid, "https://example.com"),
        ("ref", "remove", tid, "1"),
        ("ref", "add", tid, "--url", "https://example.com"),
    ]:
        with pytest.raises(SystemExit) as error:
            run(*args)
        assert error.value.code == 2


def test_addon_kind_survives_repeat_while_inactive(proj, run, tid):  # noqa: F811
    tickets.ref_add(proj, tid, "https://example.com", "human:test", "hello:pr")
    tickets.ref_add(proj, tid, "https://example.com", "human:test")
    ref = tickets.load(proj, tid)["refs"][0]
    assert ref["kind"] == "hello:pr"
    kinds = refs.kinds_of(
        {
            "hello": {
                "ticket_links": [{"kind": "hello:pr", "label": "Pull request", "icon": "git-pull-request"}]
            }
        }
    )
    assert refs.describe(ref, kinds)["type"] == "Pull request"


@pytest.mark.parametrize("kind", ["file", "artifact"])
def test_stored_path_escapes_are_cleaned(proj, run, tid, kind):  # noqa: F811
    value = "report\x1b]0;x\x07\x1b[31m.txt"
    ref = {"kind": kind, "path": value} if kind == "file" else {"kind": kind, "ticket": tid, "name": value}
    t = tickets.load(proj, tid)
    t["refs"] = [ref]
    tickets.save(proj, t)
    for argv in (("ref", "list", tid), ("ticket", "show", tid)):
        code, out, err = run(*argv)
        assert code == 0, err
        assert "report" in out and _clean(out)


@pytest.mark.parametrize("path", ["sub/.git/config", ".orch./secrets/x", ".git /config", "sub/.GiT/config"])
def test_private_project_paths_refused(proj, run, tid, path):  # noqa: F811
    assert run("ref", "add", tid, path)[0] == 2
    assert run("ref", "add", tid, str(proj / path))[0] == 2
    assert not refs.all_refs(proj, {"id": tid, "refs": [{"kind": "file", "path": path}]})


def test_invalid_stored_ticket_ids_and_local_symlink(proj, tid, monkeypatch):
    with pytest.raises(Refused):
        refs.local_path(proj, "../../../x")
    with pytest.raises(Refused):
        tickets.ticket_path(proj, tid + "\n")
    path = refs.local_path(proj, tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    outside = proj / "outside.json"
    outside.write_text(json.dumps([{"kind": "file", "path": "private.txt"}]))
    path.symlink_to(outside)
    assert refs.local_refs(proj, tid) == []
    assert refs.all_refs(proj, {"id": "../../../x", "refs": []}) == []

    def forbidden(*args):
        pytest.fail("invalid ticket id must not be loaded")

    monkeypatch.setattr(tickets, "load", forbidden)
    for kind in ("ticket", "artifact"):
        ref = {"kind": kind, "ticket": "../../../x", "name": "report.txt"}
        assert refs.describe(ref, [], proj)["title"] == "invalid reference"
        assert refs.all_refs(proj, {"id": tid, "refs": [ref]}) == []


def test_ticket_json_id_cannot_read_outside_local_refs(proj, run, tid):  # noqa: F811
    path = tickets.ticket_path(proj, tid)
    t = tickets.load(proj, tid)
    t["id"] = "../../../x"
    path.write_text(json.dumps(t))
    (proj / "x.json").write_text(json.dumps([{"kind": "file", "path": "PRIVATE_MARKER"}]))
    for argv in (("ref", "list", tid), ("ticket", "show", tid)):
        code, out, err = run(*argv)
        assert code == 0, err
        assert "PRIVATE_MARKER" not in out

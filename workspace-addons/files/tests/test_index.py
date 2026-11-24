import os
import time

from conftest import write

from orch_files import extract, index, walk


def paths(root):
    return sorted(e.path for e in walk.walk(str(root)))


def test_walk_lists_work_and_ticket_files_and_leaves_out_noise(ws):
    got = paths(ws)
    assert "notes.md" in got and "Finance/summary.md" in got
    assert ".orch/tickets/t_abc123/artifacts/summary.md" in got
    assert ".orch/tickets/t_ghi789/evidence/card.png" in got
    for gone in ("node_modules/pkg/index.js", "build/out.txt", "debug.log", ".orch/run/x.json"):
        assert gone not in got
    assert "keep.log" in got  # a ! rule keeps it
    assert not any(p.startswith(".orch/tickets/t_abc123.json") for p in got)


def test_walk_never_follows_links(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("outside the workspace")
    os.symlink(outside, ws / "linked")
    os.symlink(outside / "secret.md", ws / "linked.md")
    got = paths(ws)
    assert not any(p.startswith("linked") for p in got)


def test_private_names_are_listed_but_marked(ws):
    rows = {e.path: e for e in walk.walk(str(ws))}
    assert rows["prod.env"].private
    assert walk.private_name(("keys", "server.pem"))
    assert walk.private_name((".ssh", "config"))
    assert not walk.private_name((".github", "workflows", "ci.yml"))
    assert not rows["notes.md"].private


def test_leave_out_folders(ws):
    got = [e.path for e in walk.walk(str(ws), ("Finance",))]
    assert not any(p.startswith("Finance/") for p in got)


def test_inner_repositories_show_even_when_the_outer_gitignore_names_them(tmp_path):
    # A workspace of several repositories ignores them in its own .gitignore (ORCH-1730, Pilatus).
    write(tmp_path, ".gitignore", "dlh_*/\n*.log\nsub_wt\n")
    write(tmp_path, "docs/r.md", "doc")
    write(tmp_path, "dlh_hub/src/app.py", "print(1)")
    write(tmp_path, "dlh_hub/run.log", "outer rules stop at the repository")
    write(tmp_path, "dlh_hub/.gitignore", "out/\n")
    write(tmp_path, "dlh_hub/out/build.txt", "its own rules still hold")
    (tmp_path / "dlh_hub" / ".git").mkdir()
    write(tmp_path, "dlh_hub/.git/HEAD", "ref: refs/heads/main")
    write(tmp_path, "sub_wt/.git", "gitdir: ../.git/worktrees/sub_wt")  # a worktree or submodule
    write(tmp_path, "sub_wt/a.md", "a")
    write(tmp_path, "dlh_plain/b.md", "ignored, not a repository")
    os.symlink(tmp_path / "dlh_hub" / ".git", tmp_path / "dlh_link_git")
    got = paths(tmp_path)
    assert "docs/r.md" in got and "dlh_hub/src/app.py" in got and "sub_wt/a.md" in got
    assert "dlh_hub/run.log" in got
    assert "dlh_hub/out/build.txt" not in got
    assert not any(p.startswith("dlh_hub/.git/") for p in got)
    assert "dlh_plain/b.md" not in got
    assert not any(p.startswith("dlh_link") for p in got)
    # the person's own leave-out list still wins
    assert not any(p.startswith("dlh_hub/") for p in (e.path for e in walk.walk(str(tmp_path), ("dlh_hub",))))


def test_system_files_are_hidden_until_the_switch_is_on(ws):
    # Files opens on the person's own files: dot names and agent instruction files wait behind the switch (ORCH-1691)
    write(ws, "Sales/.hidden/x.md", "x")
    write(ws, "Sales/AGENTS.md", "agent words")
    system = (
        ".env",
        ".gitignore",
        ".claude/settings.json",
        "CLAUDE.local.md",
        "Sales/.hidden/x.md",
        "Sales/AGENTS.md",
    )
    got = paths(ws)
    assert not set(system) & set(got)
    assert "notes.md" in got and "prod.env" in got
    shown = sorted(e.path for e in walk.walk(str(ws), show_ignored=True))
    assert set(system) <= set(shown)
    assert not any(p.startswith(".orch/run") for p in shown)


def test_show_ignored_lists_what_gitignore_names_but_not_program_folders(ws):
    got = sorted(e.path for e in walk.walk(str(ws), show_ignored=True))
    assert "debug.log" in got and "build/out.txt" not in got and "node_modules/pkg/index.js" not in got
    assert not any(p.startswith(".orch/run") for p in got)
    assert not any(p.startswith("Finance/") for p in (e.path for e in walk.walk(str(ws), ("Finance",), True)))


def test_gitignore_patterns():
    ig = walk.Ignore("sub", ["*.tmp", "/top.txt", "docs/**/draft.md", "cache/", "!keep.tmp"])
    assert ig.match("sub/a.tmp", False) is True
    assert ig.match("sub/keep.tmp", False) is False
    assert ig.match("sub/top.txt", False) is True
    assert ig.match("sub/x/top.txt", False) is None
    assert ig.match("sub/docs/a/b/draft.md", False) is True
    assert ig.match("sub/cache", True) is True and ig.match("sub/cache", False) is None
    assert ig.match("other/a.tmp", False) is None


def test_read_head_refuses_links_and_traversal(ws, tmp_path):
    (tmp_path / "out.txt").write_text("outside")
    os.symlink(tmp_path / "out.txt", ws / "l.txt")
    assert walk.read_head(str(ws), "l.txt", 100) is None
    assert walk.read_head(str(ws), "../out.txt", 100) is None
    assert walk.read_head(str(ws), "notes.md", 6) == b"# Team"


def test_kinds_and_text():
    assert extract.kind_of("a/b.MD") == "md" and extract.kind_of("x.xlsx") == "table"
    assert extract.kind_of("Makefile") == "text" and extract.kind_of("x.bin") == "file"
    kind, text, title = extract.text_of("p.html", "page", b"<title>T</title><script>no</script><p>Hello</p>")
    assert "Hello" in text and "no" not in text and title == "T"
    kind, text, _ = extract.text_of("x.bin", "file", b"plain words\n")
    assert kind == "text" and "plain" in text
    assert extract.text_of("x.bin", "file", b"\x00\x01binary")[1] == ""


def test_office_parts_with_entities_are_not_read():
    import io
    import zipfile

    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(
            "word/document.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><w:document xmlns:w="w">&a;</w:document>'
        )
    assert extract.office_text(b.getvalue(), "docx") == ""


def test_search_names_first_then_text_with_the_line(built):
    res = index.search(built, "price")
    found = [(i["path"], i["found"]) for i in res["items"]]
    assert found[0][1] == "name"
    assert ("Finance/summary.md", "name") in found  # title "Price check"
    res = index.search(built, "invoic")
    hit = next(i for i in res["items"] if i["path"] == "Finance/summary.md")
    assert hit["found"] == "text" and hit["line"] == "Müller invoiced in March"
    assert res["ready"] and res["total"] >= 10


def test_search_folds_accents_and_reads_office_files(built):
    assert [i["path"] for i in index.search(built, "muller")["items"]] == ["Finance/summary.md"]
    assert any(i["path"] == "Finance/budget-2027.xlsx" for i in index.search(built, "pumpkin")["items"])
    assert any(i["path"] == "Sales/offer.docx" for i in index.search(built, "seeblick")["items"])
    assert any(i["path"] == "Sales/page.html" for i in index.search(built, "opening hours")["items"])
    assert not index.search(built, "hidden")["items"]  # script text of a web page is not text


def test_every_word_must_match_and_short_words(built):
    assert not index.search(built, "muller pumpkin")["items"]
    assert index.search(built, "pr")["items"]  # under three letters: names only
    assert index.search(built, "zz")["items"] == []


def test_private_and_secret_text_never_enter_the_index(built):
    assert not index.search(built, "STRIPE")["items"]
    assert not index.search(built, "AKIAIOSFODNN7")["items"]
    assert any(i["path"] == "prod.env" for i in index.search(built, "env")["items"])  # the name still shows


def test_ticket_files_use_the_title_from_evidence(built):
    hit = next(i for i in index.search(built, "summary")["items"] if i["ticket"] == "t_abc123")
    assert hit["title"] == "Price check: summary"
    assert any(i["ticket"] == "t_abc123" for i in index.search(built, "DM-21")["items"])


def test_refresh_reads_only_changed_files(built):
    again = index.refresh(built)
    assert again.changed == 0 and again.read == 0 and again.removed == 0
    write(built, "notes.md", "# Team meeting\nNow about rhubarb.\n", time.time())
    (built / "Marketing" / "aws.txt").unlink()
    pr = index.refresh(built)
    assert pr.changed == 1 and pr.read == 1 and pr.removed == 1
    assert index.search(built, "rhubarb")["items"][0]["path"] == "notes.md"
    assert "notes.md" not in [i["path"] for i in index.search(built, "december")["items"]]


def test_text_is_read_in_steps_and_search_works_meanwhile(ws):
    for i in range(300):
        write(ws, f"many/n{i}.md", f"note {i} about apricot\n")
    pr = index.refresh(ws, text_seconds=0)
    assert pr.unread > 0
    assert index.search(ws, "n12")["items"]  # names are searchable at once
    st = index.status(ws)
    assert st["ready"] and st["unread"] == pr.unread
    index.refresh(ws)
    assert index.status(ws)["unread"] == 0
    assert len(index.search(ws, "apricot", limit=200)["items"]) == 200


def test_ticket_ext_title_changes_follow(built):
    import json

    p = built / ".orch" / "tickets" / "t_abc123.json"
    t = json.loads(p.read_text())
    t["title"] = "Wholesale price check"
    p.write_text(json.dumps(t))
    index.refresh(built)
    assert any(i["ticket"] == "t_abc123" for i in index.search(built, "wholesale price check")["items"])


def test_ticket_groups(built):
    groups = {g["id"]: g for g in index.ticket_groups(built)}
    assert [t["key"] for t in groups["working"]["tickets"]] == ["DM-21"]
    assert [t["key"] for t in groups["review"]["tickets"]] == ["DM-23"]
    assert [t["key"] for t in groups["earlier"]["tickets"]] == ["DM-6"]  # done long ago
    assert "done" not in groups
    assert groups["working"]["label"] == "Working" and groups["earlier"]["label"] == "Earlier"


def test_versions_and_titles():
    assert index.version_of("catalogue-draft-v2.pdf") == ("catalogue-draft.pdf", 2)
    assert index.version_of("Price list version 3.md") == ("price list.md", 3)
    assert index.version_of("summary.md") is None
    assert index.nice_title("price-check_summary-v2.md") == "Price check summary"


def test_folder_and_tree(built):
    top = index.folder(built, "")
    assert {f["name"] for f in top["folders"]} >= {"Finance", "Sales", "Marketing"}
    assert all(not f["path"].startswith(".orch") for f in top["files"])
    fin = index.folder(built, "Finance")
    assert {f["name"] for f in fin["files"]} == {"summary.md", "budget-2027.xlsx"}
    counts = {f["path"]: f["count"] for f in index.tree(built)["folders"]}
    assert counts["Finance"] == 2 and counts[""] >= 9


def test_index_rebuilds_after_delete(built):
    for p in index.cache_dir(built).glob("index.db*"):
        p.unlink()
    assert index.search(built, "muller")["ready"] is False
    index.refresh(built)
    assert index.search(built, "muller")["items"]


def test_a_secret_in_a_heading_leaves_no_title_behind(ws):
    write(ws, "keys.md", "# AKIAIOSFODNN7EXAMPLE\nnothing else\n")
    index.refresh(ws)
    row = index.one(ws, "keys.md")
    assert row["private"] and "AKIA" not in row["title"]
    assert not index.search(ws, "AKIAIOSFODNN7")["items"]


def test_a_secret_far_into_the_text_is_seen(ws):
    write(ws, "long.txt", "x " * 700_000 + "AKIAIOSFODNN7EXAMPLE\n")
    index.refresh(ws)
    assert index.one(ws, "long.txt")["private"]


def test_a_file_that_cannot_be_read_now_is_tried_again(ws, monkeypatch):
    real = walk.read_head
    monkeypatch.setattr(
        walk, "read_head", lambda root, rel, n: None if rel == "notes.md" else real(root, rel, n)
    )
    index.refresh(ws)
    assert not index.search(ws, "december")["items"]
    monkeypatch.setattr(walk, "read_head", real)
    index.refresh(ws)
    assert index.search(ws, "december")["items"][0]["path"] == "notes.md"

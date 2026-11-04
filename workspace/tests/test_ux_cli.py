"""UX round 1: profile, idempotent blocks, working links, plain errors."""

import json
import re

from fakes import WS

from orch import skills


def connect(run, srv, svc):
    return run(svc, "connect", srv.url, "--workspace", WS, "--token", srv.token)


def test_relay_profile_show_and_change(proj, run, rel):
    connect(run, rel, "relay")
    code, out, _ = run("relay", "profile")
    assert code == 0 and "Description: d" in out
    code, out, err = run("relay", "profile", "--description", "Builds sites", "--tags", "web, design")
    assert code == 0, err
    assert "Saved." in out and "web, design" in out
    patch = [c for c in rel.calls if c[0] == "PATCH"][0]
    assert json.loads(patch[3]) == {"description": "Builds sites", "tags": ["web", "design"]}
    assert run("relay", "profile")[1].count("Builds sites") == 1


def test_publish_profile_and_limits(proj, run, pub):
    connect(run, pub, "publish")
    assert run("publish", "profile", "--tags", "a,b")[0] == 0
    assert pub.me["tags"] == ["a", "b"]
    code, _, err = run("publish", "profile", "--description", "x" * 281)
    assert code == 2 and "280" in err
    code, _, err = run("publish", "profile", "--tags", ",".join(f"t{i}" for i in range(9)))
    assert code == 2 and "8 tags" in err


def test_second_init_and_addon_blocks_do_not_nest(proj):
    body = "<!-- orch:begin orch-x -->\n## orch-x\nHello\n<!-- orch:end orch-x -->\n"
    for _ in range(3):
        skills.set_block(proj, "orch-x", body)
    text = (proj / "AGENTS.md").read_text()
    assert text.count("orch:begin orch-x") == 1 and text.count("orch:end orch-x") == 1


def test_set_block_repairs_nested_blocks(proj):
    (proj / "AGENTS.md").write_text(
        "mine\n<!-- orch:begin a -->\n<!-- orch:begin a -->\nold\n<!-- orch:end a -->\n<!-- orch:end a -->\n"
    )
    skills.set_block(proj, "a", "new")
    text = (proj / "AGENTS.md").read_text()
    assert text == "mine\n<!-- orch:begin a -->\nnew\n<!-- orch:end a -->\n"


def test_block_file_either_case(tmp_path):
    (tmp_path / "agents-block.md").write_text("## s\nhi")
    assert skills.read_block(tmp_path, "s") == "## s\nhi"


def test_share_link_has_the_real_key(proj, run, pub, tmp_path):
    connect(run, pub, "publish")
    f = tmp_path / "r.txt"
    f.write_text("hello")
    out = run("publish", "file", str(f))[1]
    link = [ln for ln in out.splitlines() if "#k=" in ln][0]
    assert re.fullmatch(r"\S+/f/f_[a-z0-9]+#k=[A-Za-z0-9_-]{43}", link)


def test_check_done_unknown_ticket_says_so_first(proj, run):
    code, _, err = run("check", "done", "t_nope", "c1")
    assert code == 2 and "doesn't exist" in err and "proof" not in err


def test_repeat_private_deploy_still_prints_the_link(proj, run, pub, tmp_path):
    connect(run, pub, "publish")
    app = tmp_path / "myapp"
    assert run("publish", "new", "static", str(app))[0] == 0
    first = run("publish", "app", str(app))[1]
    assert "?token=" in first
    orig = pub.routes
    # the server only shows the token the first time
    pub.routes = [
        (m, r, (lambda mm, q, b, fn=fn: _no_token(fn(mm, q, b)))) if m == "PUT" else (m, r, fn)
        for m, r, fn in orig
    ]
    again = run("publish", "app", str(app))[1]
    assert "?token=" in again
    assert "?token=" in run("publish", "list")[1]


def _no_token(res):
    status, obj = res[0], dict(res[1])
    obj.pop("view_token", None)
    return status, obj


def test_ticket_list_hides_finished(proj, run, new_ticket):
    t = new_ticket("Open one")
    run("ticket", "status", t, "done")
    out = run("ticket", "list")[1]
    assert "Open one" not in out and "1 finished" in out
    assert "Open one" in run("ticket", "list", "--all")[1]


def test_check_done_shorthand_and_duplicate_question(proj, run, new_ticket):
    t = new_ticket()
    run("check", "add", t, "Ship")
    assert run("check", "done", t, "c1", "--command", "pytest -q")[0] == 0
    run("ask", t, "Which?", "--option", "A")
    run("ask", t, "Which?", "--option", "A")
    shown = json.loads(run("ticket", "show", t, "--json")[1])
    assert len(shown["questions"]) == 1


def test_help_hides_advanced_until_help_all(run, capsys):
    import pytest

    with pytest.raises(SystemExit):
        run("--help")
    assert not re.search(r"^\s+answer\s", capsys.readouterr().out, re.M)
    with pytest.raises(SystemExit):
        run("--help-all")
    assert re.search(r"^\s+answer\s", capsys.readouterr().out, re.M)

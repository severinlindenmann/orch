"""Edit on the Skills page (ORCH-840): what can be edited, the save path (opaque ids, revisions, copy before write,
links, sizes), the header form (only changed lines move, unknown metadata and the body stay byte for byte) and
hostile text. Threat model: ORCH-840 edit-design.md."""

import io
import json
import os
import sys

import pytest

from orch_skills import cli, edit, model
from orch_skills.switches import Refused

ME = "human:severin"
HOSTILE = '</textarea><script>alert(1)</script><img src=x onerror="alert(2)">\n`rm -rf ~` $(id) ${HOME}\n'


def _names(root):
    return model.orch_names(model.build(root))


def _item(root, kind, name):
    data = model.build(root)
    return next(it for it in data[kind] if it["name"] == name)


def _save(root, target, rev, doc):
    return edit.save(root, target, rev, doc, ME, _names(root))


def _bin(root):
    b = root / edit.BIN
    return sorted(b.iterdir()) if b.is_dir() else []


# ---- what can be edited ----------------------------------------------------------------------------------


def test_only_this_workspaces_own_files_get_an_edit_id(ws):
    data = model.build(ws)
    by = {(it["kind"], it["name"]): it for k in ("skills", "instructions") for it in data[k]}
    assert edit.EDIT_ID.fullmatch(by[("skill", "release-walk")]["edit"]["id"])
    assert edit.EDIT_ID.fullmatch(by[("instructions", "AGENTS.md")]["edit"]["id"])
    for key in (("skill", "orch"), ("skill", "orch-hello"), ("skill", "github"), ("skill", "status-page")):
        assert "edit" not in by[key], key
        assert by[key]["edit_why"]
    assert "edit" not in by[("instructions", "Your rules for every project")]
    assert all("edit" not in it for (kind, name), it in by.items() if kind == "instructions" and name == "orch blocks")


def test_the_edit_id_names_no_path(ws):
    it = _item(ws, "skills", "release-walk")
    assert "release" not in it["edit"]["id"] and "/" not in it["edit"]["id"]


# ---- the save path ---------------------------------------------------------------------------------------


def test_save_an_instruction_file_keeps_a_copy_first(ws):
    it = _item(ws, "instructions", "AGENTS.md")
    loaded = edit.load(ws, it["edit"]["id"], _names(ws))
    old = (ws / "AGENTS.md").read_bytes()
    assert loaded["mode"] == "text" and loaded["text"] == old.decode()
    assert loaded["revision"] == edit.revision(old)
    res = _save(ws, it["edit"]["id"], loaded["revision"], {"text": "# Workspace rules\nNew rule.\n"})
    assert res["changed"] is True
    assert (ws / "AGENTS.md").read_text() == "# Workspace rules\nNew rule.\n"
    assert res["revision"] == edit.revision((ws / "AGENTS.md").read_bytes())
    [copy] = _bin(ws)
    assert (copy / "AGENTS.md").read_bytes() == old
    rec = json.loads((copy / "record.json").read_text())
    assert rec["from"] == "AGENTS.md" and rec["why"] == "edit" and rec["by"] == ME


def test_a_stale_save_is_refused_and_changes_nothing(ws):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.load(ws, it["edit"]["id"], _names(ws))["revision"]
    (ws / "AGENTS.md").write_text("# Someone else saved first\n")
    with pytest.raises(edit.Stale) as e:
        _save(ws, it["edit"]["id"], rev, {"text": "mine"})
    assert e.value.now == edit.revision((ws / "AGENTS.md").read_bytes())
    assert (ws / "AGENTS.md").read_text() == "# Someone else saved first\n"
    assert _bin(ws) == []


def test_the_same_revision_saves_only_once(ws):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.load(ws, it["edit"]["id"], _names(ws))["revision"]
    _save(ws, it["edit"]["id"], rev, {"text": "first\n"})
    with pytest.raises(edit.Stale):
        _save(ws, it["edit"]["id"], rev, {"text": "second\n"})
    assert (ws / "AGENTS.md").read_text() == "first\n"


def test_an_editor_saving_during_the_write_wins(ws, monkeypatch):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.load(ws, it["edit"]["id"], _names(ws))["revision"]
    real = edit._copy_to_bin

    def meanwhile(*a, **k):
        out = real(*a, **k)
        (ws / "AGENTS.md").write_text("editor\n")
        return out

    monkeypatch.setattr(edit, "_copy_to_bin", meanwhile)
    with pytest.raises(edit.Stale):
        _save(ws, it["edit"]["id"], rev, {"text": "mine\n"})
    assert (ws / "AGENTS.md").read_text() == "editor\n"


def test_no_copy_no_write(ws, monkeypatch):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.load(ws, it["edit"]["id"], _names(ws))["revision"]
    old = (ws / "AGENTS.md").read_bytes()

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(edit, "_copy_to_bin", broken)
    with pytest.raises(Refused, match="copy"):
        _save(ws, it["edit"]["id"], rev, {"text": "x"})
    assert (ws / "AGENTS.md").read_bytes() == old


@pytest.mark.parametrize(
    "target",
    [
        "e_" + "0" * 24,  # well formed, not listed
        "skill:workspace:release-walk",  # the switch id is not an edit id
        "../AGENTS.md",
        "/etc/passwd",
        "e_" + "0" * 23 + "g",
        "E_" + "0" * 24,
        "",
    ],
)
def test_forged_ids_are_refused(ws, target):
    rev = edit.revision((ws / "AGENTS.md").read_bytes())
    with pytest.raises(Refused):
        _save(ws, target, rev, {"text": "x"})
    with pytest.raises(Refused):
        edit.load(ws, target, _names(ws))


def test_the_id_of_an_orch_or_shared_skill_cannot_be_used(ws):
    for where, name in (("workspace", "orch-hello"), ("workspace", "github")):
        for base in (".agents/skills", ".claude/skills"):
            forged = edit.edit_id("skill", where, name, f"{base}/{name}/SKILL.md")
            with pytest.raises(Refused):
                edit.load(ws, forged, _names(ws))


def test_a_link_swapped_in_is_refused_and_the_target_is_untouched(ws, tmp_path):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.load(ws, it["edit"]["id"], _names(ws))["revision"]
    outside = tmp_path / "outside.md"
    outside.write_bytes((ws / "AGENTS.md").read_bytes())
    (ws / "AGENTS.md").unlink()
    try:
        os.symlink(outside, ws / "AGENTS.md")
    except (OSError, NotImplementedError):
        pytest.skip("no links here")
    with pytest.raises(Refused):
        _save(ws, it["edit"]["id"], rev, {"text": "x"})
    assert outside.read_bytes().startswith(b"# Workspace rules")
    assert _item(ws, "instructions", "AGENTS.md").get("edit") is None


def test_a_linked_skill_folder_is_not_offered(ws, tmp_path):
    real = tmp_path / "elsewhere" / "linked"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("---\nname: linked\ndescription: A skill reached through a link.\n---\nx\n")
    try:
        os.symlink(real, ws / ".agents/skills/linked", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no links here")
    assert all(c["name"] != "linked" for c in edit.candidates(ws))


def test_a_big_or_binary_file_is_not_offered(ws):
    (ws / "CLAUDE.md").write_bytes(b"x" * (edit.MAX_FILE + 1))
    (ws / "AGENTS.local.md").write_bytes(b"a\x00b")
    data = model.build(ws)
    by = {it["name"]: it for it in data["instructions"]}
    assert "edit" not in by["CLAUDE.md"] and "edit" not in by["AGENTS.local.md"]
    assert "edit" in by["AGENTS.md"]


@pytest.mark.parametrize(
    "raw",
    [
        b"x" * (edit.MAX_INPUT + 1),
        b'{"text": "a\\u0000b"}'.replace(b"\\u0000", b"\x00"),
        b"\xff\xfe",
        b"[]",
        b"{}",
        b'{"text": "a", "text": "b"}',
        b'{"text": "a", "path": "/etc/passwd"}',
        b"not json",
    ],
)
def test_bad_input_is_refused(raw):
    with pytest.raises(Refused):
        edit.read_input(io.BytesIO(raw))


def test_a_lone_surrogate_and_a_nul_in_the_text_are_refused(ws):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.load(ws, it["edit"]["id"], _names(ws))["revision"]
    for bad in ("a\ud800b", "a\x00b", "x" * (edit.MAX_FILE + 1)):
        with pytest.raises(Refused):
            _save(ws, it["edit"]["id"], rev, {"text": bad})
    assert _bin(ws) == []


def test_hostile_text_is_kept_as_plain_text(ws):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.load(ws, it["edit"]["id"], _names(ws))["revision"]
    _save(ws, it["edit"]["id"], rev, {"text": HOSTILE})
    assert (ws / "AGENTS.md").read_text() == HOSTILE
    assert edit.load(ws, it["edit"]["id"], _names(ws))["text"] == HOSTILE


def test_crlf_files_keep_crlf_from_a_browser_text_box(ws):
    (ws / "AGENTS.md").write_bytes(b"# Rules\r\nOne.\r\n")
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.load(ws, it["edit"]["id"], _names(ws))["revision"]
    _save(ws, it["edit"]["id"], rev, {"text": "# Rules\nOne.\nTwo.\n"})
    assert (ws / "AGENTS.md").read_bytes() == b"# Rules\r\nOne.\r\nTwo.\r\n"


def test_keep_newlines():
    assert edit.keep_newlines("a\r\nb\n", "a\nb\n") == "a\r\nb\n"  # unchanged mixed text stays as it was
    assert edit.keep_newlines("a\r\nb\r\n", "a\nc\n") == "a\r\nc\r\n"
    assert edit.keep_newlines("a\nb\n", "a\nc\n") == "a\nc\n"
    assert edit.keep_newlines("a\r\nb\n", "x\n") == "x\n"  # mixed and changed: as sent


def test_nothing_changed_writes_nothing(ws):
    it = _item(ws, "instructions", "AGENTS.md")
    loaded = edit.load(ws, it["edit"]["id"], _names(ws))
    res = _save(ws, it["edit"]["id"], loaded["revision"], {"text": loaded["text"]})
    assert res["changed"] is False and _bin(ws) == []


# ---- the command (only a person, text on stdin) ---------------------------------------------------------


def _cli(ws, monkeypatch, capsys, target, rev, payload, by=ME):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload.encode("utf-8")), encoding="utf-8"))
    code = cli.main(["--dir", str(ws), "act", "save", f"--value={rev}", "--by", by, "--json", target])
    return code, json.loads(capsys.readouterr().out)


def test_cli_save_and_history(ws, monkeypatch, capsys):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.revision((ws / "AGENTS.md").read_bytes())
    code, out = _cli(ws, monkeypatch, capsys, it["edit"]["id"], rev, json.dumps({"text": "new\n"}))
    assert code == 0, out
    assert out["changed"] is True and out["revision"] == edit.revision(b"new\n")
    assert cli._history(ws)[0]["what"] == "edited"


def test_cli_stale_answers_with_the_current_revision(ws, monkeypatch, capsys):
    it = _item(ws, "instructions", "AGENTS.md")
    code, out = _cli(ws, monkeypatch, capsys, it["edit"]["id"], "0" * 64, json.dumps({"text": "x"}))
    assert code == 2
    assert out["revision"] == edit.revision((ws / "AGENTS.md").read_bytes()) and out["changed_by"]


def test_a_helper_cannot_save(ws, monkeypatch, capsys):
    it = _item(ws, "instructions", "AGENTS.md")
    rev = edit.revision((ws / "AGENTS.md").read_bytes())
    monkeypatch.setenv("ORCH_RUN", "r1")
    code, out = _cli(ws, monkeypatch, capsys, it["edit"]["id"], rev, json.dumps({"text": "x"}))
    assert code == 2 and "person" in out["error"]
    monkeypatch.delenv("ORCH_RUN")
    code, out = _cli(ws, monkeypatch, capsys, it["edit"]["id"], rev, json.dumps({"text": "x"}), by="agent:claude")
    assert code == 2
    assert (ws / "AGENTS.md").read_text().startswith("# Workspace rules")


def test_other_verbs_take_no_value(ws, capsys):
    code = cli.main(["--dir", str(ws), "act", "on", "--value=x", "--by", ME, "--json", "skill:orch:orch-hello"])
    assert code == 2


# ---- the page server -------------------------------------------------------------------------------------


def test_the_page_server_gives_the_item_as_json(ws):
    import http.client
    import threading

    from orch_skills import server

    it = _item(ws, "instructions", "AGENTS.md")
    (ws / "AGENTS.md").write_text(HOSTILE)
    srv = server.make_server(ws, 0, nonce="")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("GET", "/api/item?id=" + it["edit"]["id"], headers={"Host": f"127.0.0.1:{port}"})
        r = c.getresponse()
        body = r.read()
        assert r.status == 200, body
        assert r.getheader("Content-Type") == "application/json"
        assert json.loads(body)["text"] == HOSTILE
        c.request("GET", "/api/item?id=../AGENTS.md", headers={"Host": f"127.0.0.1:{port}"})
        r = c.getresponse()
        r.read()
        assert r.status == 404
        c.request("POST", "/api/item?id=" + it["edit"]["id"], body=b"x", headers={"Host": f"127.0.0.1:{port}"})
        r = c.getresponse()
        r.read()
        assert r.status == 405
    finally:
        srv.shutdown()
        srv.server_close()


# ---- the header form (needs the one header reader, orch.skillmeta) ---------------------------------------

SKILL = (
    "---\n"
    "name: release-walk\n"
    "description: Run a release pass in a test home like a person.\n"
    "# a comment the person wrote\n"
    "license: MIT\n"
    "metadata:\n"
    '  status: "draft"\n'
    "  version: 1.0\n"
    "  api-credits: api-credits.toml\n"
    '  platforms: "macos,linux"\n'
    "x-team-note: keep me\n"
    "---\n"
    "# release-walk\n"
    "\n"
    "Steps, with trailing spaces   \n"
    "and no newline at the end"
)


@pytest.fixture
def skill(ws):
    pytest.importorskip("orch.skillmeta")
    if not hasattr(__import__("orch.skillmeta").skillmeta, "parse_header"):
        pytest.skip("this orch has no header reader")
    p = ws / ".agents/skills/release-walk/SKILL.md"
    p.write_text(SKILL, newline="")
    it = _item(ws, "skills", "release-walk")
    assert it["edit"]["mode"] == "skill"
    return ws, it["edit"]["id"], p


def _form(ws, target):
    return edit.load(ws, target, _names(ws))


def test_the_form_shows_the_header_and_the_body(skill):
    ws, target, _ = skill
    got = _form(ws, target)
    assert got["fields"]["description"] == "Run a release pass in a test home like a person."
    assert got["fields"]["status"] == "draft" and got["fields"]["version"] == "1.0"
    assert got["body"] == SKILL.split("---\n", 2)[2]


def test_only_the_changed_lines_move(skill):
    ws, target, p = skill
    got = _form(ws, target)
    fields = {**got["fields"], "status": "active", "owner": "Severin", "platforms": "macos, linux"}
    _save(ws, target, got["revision"], {"fields": fields, "body": got["body"]})
    new = p.read_text()
    old_lines, new_lines = SKILL.split("\n"), new.split("\n")
    assert '  status: "active"' in new_lines and '  owner: "Severin"' in new_lines
    # every other line is byte for byte the same, in the same order
    assert [x for x in new_lines if x not in ('  status: "active"', '  owner: "Severin"')] == [
        x for x in old_lines if x != '  status: "draft"'
    ]
    assert '  platforms: "macos,linux"' in new_lines  # same list, other spacing: left alone
    assert new.endswith("and no newline at the end")


def test_a_cleared_field_drops_its_line_and_unknown_metadata_stays(skill):
    ws, target, p = skill
    got = _form(ws, target)
    _save(ws, target, got["revision"], {"fields": {**got["fields"], "version": ""}, "body": got["body"]})
    new = p.read_text()
    assert "version:" not in new
    assert "  api-credits: api-credits.toml\n" in new and "x-team-note: keep me\n" in new
    assert "# a comment the person wrote\n" in new and "license: MIT\n" in new


def test_a_header_without_metadata_gets_one(skill):
    ws, target, p = skill
    p.write_text("---\nname: release-walk\ndescription: Run a release pass in a test home like a person.\n---\nBody\n")
    got = _form(ws, target)
    _save(ws, target, got["revision"], {"fields": {**got["fields"], "tags": "release, qa"}, "body": got["body"]})
    assert p.read_text() == (
        "---\nname: release-walk\ndescription: Run a release pass in a test home like a person.\n"
        'metadata:\n  tags: "release, qa"\n---\nBody\n'
    )


def test_the_body_is_written_as_sent(skill):
    ws, target, p = skill
    got = _form(ws, target)
    body = got["body"] + "\n\n---\nname: not-a-header\n---\n" + HOSTILE
    _save(ws, target, got["revision"], {"fields": got["fields"], "body": body})
    assert p.read_text() == SKILL + "\n\n---\nname: not-a-header\n---\n" + HOSTILE
    assert _form(ws, target)["fields"]["description"] == got["fields"]["description"]


def test_crlf_skill_keeps_crlf(skill):
    ws, target, p = skill
    p.write_bytes(SKILL.replace("\n", "\r\n").encode())
    got = _form(ws, target)
    browser_body = got["body"].replace("\r\n", "\n")
    _save(ws, target, got["revision"], {"fields": {**got["fields"], "status": "active"}, "body": browser_body})
    raw = p.read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert b'  status: "active"\r\n' in raw


@pytest.mark.parametrize(
    "key, value",
    [
        ("description", "two\nlines"),
        ("description", ""),
        ("description", "x" * 1025),
        ("status", "beta"),
        ("platforms", "macos, amiga"),
        ("review-by", "31.03.2027"),
        ("review-by", "2027-02-30"),
        ("owner", "bidi\u202eevil"),
        ("owner", "x" * 301),
    ],
)
def test_bad_field_values_are_refused(skill, key, value):
    ws, target, p = skill
    got = _form(ws, target)
    with pytest.raises(Refused):
        _save(ws, target, got["revision"], {"fields": {**got["fields"], key: value}, "body": got["body"]})
    assert p.read_text() == SKILL


def test_unknown_form_fields_are_refused(skill):
    ws, target, p = skill
    got = _form(ws, target)
    for extra in ({"name": "other"}, {"metadata": "x"}, {"api-credits": "x"}):
        with pytest.raises(Refused):
            _save(ws, target, got["revision"], {"fields": {**got["fields"], **extra}, "body": got["body"]})
    assert p.read_text() == SKILL


def test_tricky_values_are_quoted_and_read_back(skill):
    ws, target, _p = skill
    got = _form(ws, target)
    desc = 'Use when: a "release" is due --- or # not; back\\slash, yes, 2027-01-01, true'
    _save(
        ws,
        target,
        got["revision"],
        {"fields": {**got["fields"], "description": desc, "version": "2.0"}, "body": got["body"]},
    )
    again = _form(ws, target)["fields"]
    assert again["description"] == desc and again["version"] == "2.0"


def test_a_form_save_for_a_text_mode_skill_is_refused(skill):
    ws, target, p = skill
    p.write_text("---\nname: release-walk\ndescription: |\n  a block value\n---\nBody\n")
    got = _form(ws, target)
    assert got["mode"] == "text"
    with pytest.raises(Refused):
        _save(ws, target, got["revision"], {"fields": {"description": "x" * 30}, "body": "Body\n"})
    _save(ws, target, got["revision"], {"text": got["text"] + "More.\n"})
    assert p.read_text().endswith("More.\n")


def test_a_text_save_of_a_skill_needs_its_header(skill):
    ws, target, p = skill
    p.write_text("---\nname: release-walk\ndescription: |\n  a block value\n---\nBody\n")
    got = _form(ws, target)
    with pytest.raises(Refused, match="header"):
        _save(ws, target, got["revision"], {"text": "no header any more"})


def test_the_page_never_draws_text_as_html():
    from importlib import resources

    js = resources.files("orch_skills").joinpath("web", "skills.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in js, sink
    assert "orch.save" in js and ".value = value" in js

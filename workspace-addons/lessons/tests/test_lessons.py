import json
import os
from pathlib import Path

from conftest import CONTRACTS, jrun, validator

from orch_lessons import store

LIST = CONTRACTS / "addons" / "lessons" / "list.schema.json"
VIEW = CONTRACTS / "addon-view.schema.json"


def extra(ws) -> Path:
    return ws / ".orch" / "addons" / "lessons" / "AGENTS-extra.md"


def agents(ws) -> str:
    return (ws / ".orch" / "harness" / "AGENTS.orch.md").read_text(encoding="utf-8")


def test_add_list_schema_and_agents_text(cli, ws):
    code, out = jrun(
        cli, "add", "Run the web tests with npm run test:web.", "--ticket", "DM1-12", "--by", "agent:claude"
    )
    assert code == 0 and out["added"] is True
    assert out["lesson"]["ticket"] == "t_abc123" and out["lesson"]["by"] == "agent:claude"
    assert "Helpers read it" in out["next"]
    code, out2 = jrun(cli, "add", "  run the WEB tests   with npm run test:web. ")
    assert out2["added"] is False and out2["lesson"]["id"] == out["lesson"]["id"]
    jrun(cli, "add", "The customer list lives in Sales/2026/customers.xlsx.", "--by", "agent:codex")
    code, data = jrun(cli, "list")
    validator(LIST).validate(data)
    assert data["shown"] == 2 and data["unreadable"] == 0 and len(data["lessons"]) == 2
    text = extra(ws).read_text(encoding="utf-8")
    assert text.startswith(store.HEADER) and text.count("\n- ") == 2
    assert "customers.xlsx" in agents(ws) and "npm run test:web" in agents(ws)
    assert "Write lessons." in agents(ws)


def test_edit_rm_and_act(cli, ws):
    _, a = jrun(cli, "add", "First lesson here.", "--by", "agent:claude")
    lid = a["lesson"]["id"]
    code, raw, _ = cli(
        "act", "edit", "--by", "human:severin", "--value", "Second wording.", "--json", "--", lid
    )
    e = json.loads(raw)
    assert (
        code == 0
        and e["lesson"]["text"] == "Second wording."
        and e["lesson"]["changed_by"] == "human:severin"
    )
    assert "Second wording." in agents(ws) and "First lesson" not in agents(ws)
    code, r = jrun(cli, "rm", lid)
    assert r["removed"] == lid
    assert not extra(ws).exists() and "Second wording" not in agents(ws)
    code, err = jrun(cli, "rm", lid)
    assert code == 2 and "No lesson" in err["error"]
    code, raw, _ = cli("act", "rm", "--by", "human:x", "--json", "--", "l_zzzzzz")
    err = json.loads(raw)
    assert code == 2 and "orch lessons list" in err["error"]


def test_text_rules(cli):
    for bad, word in (("", "Say what"), ("a\nb", "one plain line"), ("x" * 201, "200")):
        code, out = jrun(cli, "add", bad)
        assert code == 2 and word in out["error"]
    code, out = jrun(cli, "add", "ok", "--ticket", "t_nonexist1")
    assert code == 2 and "doesn't exist" in out["error"]
    code, out = jrun(cli, "add", "ok", "--by", "someone else")
    assert code == 2


def test_secret_is_refused_and_named(cli, ws):
    code, out = jrun(cli, "add", "The key is sk-ant-api03-" + "A1b2C3d4" * 6)
    assert code == 2 and "Remove it" in out["error"]
    assert not (ws / ".orch" / "addons" / "lessons").exists()
    _, a = jrun(cli, "add", "fine")
    code, out = jrun(cli, "edit", a["lesson"]["id"], "token ghp_" + "a1B2c3D4" * 5)
    assert code == 2


def test_a_stored_key_value_is_refused(cli, stored_keys):
    stored_keys["shop"] = "zq81-plain-looking-value-4471"
    code, out = jrun(cli, "add", "Use zq81-plain-looking-value-4471 for the shop.")
    assert code == 2 and "stored keys" in out["error"]


def test_scanner_that_cannot_run_refuses(cli, monkeypatch):
    from orch import phone_results

    monkeypatch.setattr(phone_results, "value_hider", lambda root: None)
    code, _out = jrun(cli, "add", "Anything.")
    assert code == 2


def test_cap_truncates_and_hints(cli, ws):
    ids = []
    for i in range(30):
        _, o = jrun(cli, "add", f"Lesson {i:02d} " + "ü" * 150)
        ids.append(o["lesson"]["id"])
    assert "3 KB" in o["next"]
    _, data = jrun(cli, "list")
    validator(LIST).validate(data)
    assert data["shown"] < 30 and data["bytes"] > 3072
    assert sum(1 for x in data["lessons"] if x["shown"]) == data["shown"]
    assert len(extra(ws).read_bytes()) <= 3072
    assert len(agents(ws).encode()) <= 3072 + 200
    # newest first: the last added is shown
    assert data["lessons"][0]["text"].startswith("Lesson 29")
    _code, view = jrun(cli, "view")
    assert view["notice_tone"] == "warn"


def test_crlf_file_and_unreadable_skipped(cli, ws):
    d = ws / ".orch" / "addons" / "lessons"
    d.mkdir(parents=True)
    (d / "l_aaaaaa.md").write_bytes(
        b"---\r\nby: agent:claude\r\nat: 2026-11-15T18:02:11Z\r\nflavour: kept\r\n---\r\nCRLF lesson.\r\n"
    )
    (d / "l_bbbbbb.md").write_text("no front matter", encoding="utf-8")
    (d / "l_cccccc.md").write_bytes(b"\xff\xfe broken")
    (d / "notes.txt").write_text("x", encoding="utf-8")
    _, data = jrun(cli, "list")
    validator(LIST).validate(data)
    assert [x["text"] for x in data["lessons"]] == ["CRLF lesson."] and data["unreadable"] == 3
    jrun(cli, "edit", "l_aaaaaa", "Edited.")
    body = (d / "l_aaaaaa.md").read_text(encoding="utf-8")
    assert "flavour: kept" in body and "changed_at:" in body and "\r" not in body
    assert (d / "l_bbbbbb.md").read_text(encoding="utf-8") == "no front matter"  # never rewritten


def test_view_validates(cli, ws):
    _, a = jrun(
        cli, "add", "Run tests with npm run test:web.", "--ticket", "t_abc123", "--by", "agent:claude"
    )
    _, view = jrun(cli, "view")
    validator(VIEW).validate(view)
    item = view["blocks"][0]["items"][0]
    assert (
        item["link"] == "t_abc123" and "from DM1-12" in item["subtitle"] and "by Claude" in item["subtitle"]
    )
    assert item["actions"][0]["action"]["op"] == "addon.prompt"
    jrun(cli, "rm", a["lesson"]["id"])
    _, empty = jrun(cli, "view")
    validator(VIEW).validate(empty)
    assert empty["blocks"][0]["items"] == [] and empty["blocks"][0]["count"] == 0


def test_actor_defaults(cli, ws, monkeypatch):
    monkeypatch.setenv("ORCH_AGENT", "claude")
    _, a = jrun(cli, "add", "From a helper.")
    assert a["lesson"]["by"] == "agent:claude"
    monkeypatch.delenv("ORCH_AGENT")
    _, b = jrun(cli, "add", "From a person.")
    assert b["lesson"]["by"].startswith(("human:", "agent:"))


def test_text_output_ends_with_next_step(cli):
    code, out, _ = cli("add", "Plain output.")
    assert code == 0 and out.strip().endswith("next start.")
    code, out, _ = cli("list")
    assert out.strip().splitlines()[-1].startswith("Next:")


def test_add_from_a_copy_writes_to_the_home(cli, ws, tmp_path, monkeypatch):
    copy = tmp_path / "copy"
    (copy / "sub").mkdir(parents=True)
    monkeypatch.chdir(copy / "sub")
    monkeypatch.setenv("ORCH_ROOT", str(ws))
    from orch_lessons.cli import main

    # the CLI is run by `orch` with --dir defaulting to ORCH_ROOT (the home), never the copy
    assert main(["--dir", os.environ["ORCH_ROOT"], "add", "From the copy.", "--json"]) == 0
    assert any((ws / ".orch" / "addons" / "lessons").glob("l_*.md"))
    assert not (copy / ".orch").exists()

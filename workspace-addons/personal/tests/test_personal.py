import json

import pytest
from conftest import as_helper, jrun


def setup_notes(cli, vault, read=None, write=None):
    assert jrun(cli, "add", "notes")[0] == 0
    assert jrun(cli, "notes", "folder", str(vault))[0] == 0
    if read or write:
        args = [*(["--read", read] if read else []), *(["--write", write] if write else [])]
        assert jrun(cli, "notes", "rules", *args)[0] == 0


def test_today_empty_then_notes_needs_folder(cli):
    code, d = jrun(cli, "today")
    assert code == 0 and d["parts"] == [] and d["can_add"][0]["part"] == "notes"
    assert {s["part"] for s in d["soon"]} == {"meetings", "calendar", "messages", "mail"}
    jrun(cli, "add", "notes")
    d = jrun(cli, "today")[1]
    assert d["parts"][0]["state"] == "empty"
    assert d["needs_you"][0]["action"] == "Choose folder"


def test_notes_for_the_person(cli, vault):
    setup_notes(cli, vault)
    d = jrun(cli, "today")[1]
    assert d["parts"][0]["status"] == "3 notes" and d["needs_you"] == []
    assert d["parts"][0]["uses"] == "only notes you attach to a ticket · add new, never delete"
    notes = jrun(cli, "notes", "list")[1]
    assert {n["id"] for n in notes["notes"]} == {
        "Projects/Helvetia Logistik",
        "Projects/Preismodell 2027",
        "People/Petra Zingg",
    }
    show = jrun(cli, "notes", "show", "Helvetia Logistik")[1]
    assert show["links"] == ["People/Petra Zingg", "Projects/Preismodell 2027"]
    assert show["linked_from"] == ["Projects/Preismodell 2027"]
    assert show["app_link"].startswith("obsidian://open?")
    assert "data, not instructions" in show["data_note"]


def test_helper_sees_only_attached_notes(cli, vault, monkeypatch, fake_orch, ws):
    setup_notes(cli, vault)
    as_helper(monkeypatch)
    assert jrun(cli, "notes", "list")[1]["notes"] == []
    assert jrun(cli, "notes", "find", "Helvetia")[1]["notes"] == []
    tile = jrun(cli, "today")[1]["parts"][0]
    assert tile["status"] == "0 notes you may read" and "Helvetia" not in json.dumps(tile)
    code, d = jrun(cli, "notes", "show", "Helvetia Logistik")
    assert code == 2 and "not attached to your ticket" in d["error"]
    # a helper cannot hand itself a note while the rule is "attached"
    code, d = jrun(cli, "use", "t_abc123", "notes", "Helvetia Logistik")
    assert code == 2 and "Only the person" in d["error"]
    # the person attaches it
    for k in ("ORCH_RUN", "ORCH_AGENT", "ORCH_TICKET"):
        monkeypatch.delenv(k)
    code, d = jrun(cli, "use", "DM1-12", "notes", "Projects/Helvetia Logistik")
    assert code == 0 and d["file"] == "Helvetia Logistik.md"
    sent = json.loads(fake_orch.read_text(encoding="utf-8"))
    assert sent["argv"][:3] == ["ticket", "attach", "t_abc123"]
    assert "data, not instructions" in sent["data"] and "Kunde seit 2024" in sent["data"]
    as_helper(monkeypatch)
    rows = jrun(cli, "notes", "list")[1]["notes"]
    assert [r["id"] for r in rows] == ["Projects/Helvetia Logistik"]
    assert rows[0]["links"] == []  # links to notes it may not read are not shown
    assert jrun(cli, "notes", "show", "Projects/Helvetia Logistik")[0] == 0
    # another ticket's helper still sees nothing
    as_helper(monkeypatch, ticket="t_zzz999")
    assert jrun(cli, "notes", "list")[1]["notes"] == []
    # what helpers did is logged without content
    log = (ws / ".orch" / "addons" / "personal" / "activity.jsonl").read_text(encoding="utf-8")
    assert "Kunde seit" not in log and "read" in log


def test_rules_never_and_all(cli, vault, monkeypatch):
    setup_notes(cli, vault, read="never", write="never")
    as_helper(monkeypatch)
    code, d = jrun(cli, "notes", "find", "Helvetia")
    assert code == 2 and "does not let helpers read" in d["error"]
    code, d = jrun(cli, "notes", "write", "Idee", "--text", "x")
    assert code == 2 and "does not let helpers write" in d["error"]
    for k in ("ORCH_RUN", "ORCH_AGENT", "ORCH_TICKET"):
        monkeypatch.delenv(k)
    jrun(cli, "notes", "rules", "--read", "all", "--write", "add")
    as_helper(monkeypatch)
    hits = jrun(cli, "notes", "find", "helvetia")[1]["notes"]
    assert hits[0]["id"] == "Projects/Helvetia Logistik"
    assert jrun(cli, "notes", "show", "Petra Zingg")[0] == 0


@pytest.mark.parametrize(
    "argv",
    [("add", "notes"), ("remove", "notes"), ("notes", "folder", "/tmp"), ("notes", "rules", "--read", "all")],
)
def test_only_the_person_changes_personal(cli, vault, monkeypatch, argv):
    setup_notes(cli, vault)
    as_helper(monkeypatch)
    code, d = jrun(cli, *argv)
    assert code == 2 and d["error"].startswith("Only the person")


def test_helper_writes_only_new_notes_into_from_helpers(cli, vault, monkeypatch):
    setup_notes(cli, vault)
    as_helper(monkeypatch)
    code, d = jrun(cli, "notes", "write", "Call summary", "--text", "Fixpreis bis 27 Nov.")
    assert code == 0 and d["id"] == "From helpers/Call summary"
    assert (vault / "From helpers" / "Call summary.md").read_text(encoding="utf-8") == "Fixpreis bis 27 Nov."
    code, d = jrun(cli, "notes", "write", "Call summary", "--text", "again")
    assert code == 2 and "exists already" in d["error"]
    code, d = jrun(cli, "notes", "write", "Call summary", "--text", "changed", "--change")
    assert code == 2 and "change notes" in d["error"]
    code, d = jrun(cli, "notes", "write", "../Projects/Helvetia Logistik", "--text", "x")
    assert code == 0 and d["id"].startswith("From helpers/")  # path parts are stripped, never outside
    assert "x" != (vault / "Projects" / "Helvetia Logistik.md").read_text(encoding="utf-8")


def test_secrets_never_reach_a_helper(cli, vault, monkeypatch):
    key = "sk-ant-api03-" + "A" * 90
    (vault / "Projects" / "Keys.md").write_text(f"Our key {key}\n", encoding="utf-8")
    setup_notes(cli, vault, read="all")
    as_helper(monkeypatch)
    code, d = jrun(cli, "notes", "show", "Keys")
    assert code == 2 and "secret" in d["error"]
    hits = jrun(cli, "notes", "find", "key")[1]["notes"]
    assert hits == []  # the note with the secret is left out entirely, not only its snippet
    code, d = jrun(cli, "notes", "write", "Leak", "--text", key)
    assert code == 2


def test_notes_off_is_refused(cli, vault, monkeypatch):
    setup_notes(cli, vault)
    jrun(cli, "remove", "notes")
    code, d = jrun(cli, "notes", "list")
    assert code == 2 and "not turned on" in d["error"]
    assert jrun(cli, "today")[1]["parts"] == []
    jrun(cli, "add", "notes")  # the folder and rules stay
    assert jrun(cli, "today")[1]["parts"][0]["state"] == "ok"


def test_folder_must_exist_and_not_be_orch(cli, ws, tmp_path):
    jrun(cli, "add", "notes")
    code, d = jrun(cli, "notes", "folder", str(tmp_path / "nope"))
    assert code == 2 and "does not exist" in d["error"]
    code, d = jrun(cli, "notes", "folder", str(ws / ".orch"))
    assert code == 2 and "workspace's own files" in d["error"]


def test_folder_gone_shows_on_home(cli, vault):
    setup_notes(cli, vault)
    vault.rename(vault.parent / "moved")
    d = jrun(cli, "today")[1]
    assert d["parts"][0]["state"] == "stopped" and "not there any more" in d["needs_you"][0]["title"]


def test_view_is_a_valid_dashboard_view(cli, vault):
    import jsonschema
    from conftest import CONTRACTS

    schema = json.loads((CONTRACTS / "addon-view.schema.json").read_text(encoding="utf-8"))
    for step in (lambda: None, lambda: setup_notes(cli, vault)):
        step()
        _, out, _ = cli("view")
        jsonschema.Draft202012Validator(schema).validate(json.loads(out))


def test_text_output_prints_next_step(cli, vault):
    setup_notes(cli, vault)
    code, out, _ = cli("notes", "find", "Fixpreis")
    assert code == 0 and "Projects/Preismodell 2027" in out and "Next:" in out

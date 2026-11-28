import json
from datetime import UTC, datetime

import pytest
from conftest import jrun

from orch_lessons import store, view


def _write(ws, name, body):
    d = ws / ".orch" / "addons" / "lessons"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8", newline="")
    return d / name


def _lesson(extra="", at="2026-11-15T18:02:11Z", by="agent:claude", text="A lesson."):
    return f"---\nby: {by}\nat: {at}\n{extra}---\n{text}\n"


def test_day_shows_the_local_day_and_falls_back_on_a_bad_date():
    iso = "2026-11-15T18:02:11Z"
    local = datetime(2026, 11, 15, 18, 2, 11, tzinfo=UTC).astimezone()
    assert view._day(iso) == f"{local.day} {local.strftime('%b')}"
    assert view._day("2026-11-15 nonsense") == "2026-11-15"


def test_ticket_label_never_crashes_on_odd_ticket_files(ws):
    tickets = ws / ".orch" / "tickets"
    (tickets / "t_listed1.json").write_text("[1, 2]", encoding="utf-8")
    (tickets / "t_broken1.json").write_text("{nope", encoding="utf-8")
    (tickets / "t_nokey01.json").write_text(json.dumps({"id": "t_nokey01"}), encoding="utf-8")
    assert view._ticket(ws, "t_abc123")["key"] == "DM1-12"
    for tid in ("t_listed1", "t_broken1", "t_nokey01", "t_missing1"):
        assert view._ticket(ws, tid) == {"id": tid, "title": tid}


def test_view_shows_at_most_50_and_counts_all(cli, ws):
    for i in range(55):
        _write(ws, f"l_{i:06d}.md", _lesson(at=f"2026-11-15T10:00:{i:02d}Z", text=f"Short {i}."))
    _, v = jrun(cli, "view")
    block = v["blocks"][0]
    assert block["count"] == 55 and len(block["items"]) == 50
    assert block["items"][0]["title"] == "Short 54."
    assert "This page shows 50 at a time; 5 older are on the next page." in v["notice"]
    # W-052 (owner 28 Nov): the warning's button leads to the older lessons, never away from the page
    assert v["header"]["link"] == {"label": "Show older lessons", "to": "app:addon/lessons"}
    older = v["blocks"][1]
    assert older["title"] == block["title"] and [i["title"] for i in older["items"]][-1] == "Short 0."
    assert all([a["action"]["args"]["verb"] for a in i["actions"]] == ["edit", "rm"] for i in older["items"])
    assert "empty" not in older and "empty" in block


def test_view_reaches_a_thousand_lessons_in_pages_and_says_what_is_left(cli, ws):
    """W-052: 796 older lessons were hidden behind a button that left the page. Every page holds 50, a view holds 20
    pages; beyond that the notice says how many show once newer ones are deleted. No delete-many."""
    for i in range(1003):
        _write(ws, f"l_{i:06d}.md", _lesson(at=f"2026-11-{1 + i // 3600:02d}T{i // 60 % 24:02d}:{i % 60:02d}:00Z", text=f"L {i}."))
    _, v = jrun(cli, "view")
    assert len(v["blocks"]) == 20 and all(len(b["items"]) == 50 and b["title"] == "Saved lessons" for b in v["blocks"])
    assert v["blocks"][0]["count"] == 1003
    assert "953 older are on the next pages." in v["notice"] and "The oldest 3 show once newer ones are deleted." in v["notice"]
    verbs = {a["action"]["args"]["verb"] for b in v["blocks"] for i in b["items"] for a in i["actions"]}
    assert verbs == {"edit", "rm"}


def test_view_with_few_lessons_keeps_one_list_and_the_way_back(cli, ws):
    _write(ws, "l_aaaaaa.md", _lesson(by="human:severin"))
    _, v = jrun(cli, "view")
    assert len(v["blocks"]) == 1 and v["header"]["link"] == {"label": "← Add-ons", "to": "app:settings/addons"}
    assert "notice" not in v


def test_view_item_without_a_ticket_has_no_link(cli, ws):
    _write(ws, "l_aaaaaa.md", _lesson(by="human:severin"))
    _, v = jrun(cli, "view")
    item = v["blocks"][0]["items"][0]
    assert (
        "link" not in item
        and item["subtitle"].startswith("Added ")
        and item["subtitle"].endswith("by Severin")
    )


@pytest.mark.parametrize(
    "body",
    [
        "---\nby: agent:claude\nat: 2026-11-15T18:02:11Z\n",  # never closed
        _lesson(at="2026-11-15 18:02"),  # bad time
        _lesson(by="someone else"),  # bad actor
        _lesson(extra="ticket: nope\n"),
        _lesson(extra="changed_by: nobody\n"),
        _lesson(extra="changed_at: yesterday\n"),
        _lesson(extra="not a key value line\n"),
        _lesson(text=""),
        _lesson(text="x" * 201),
    ],
)
def test_unreadable_lessons_are_counted_and_untouched(cli, ws, body):
    p = _write(ws, "l_bad000.md", body)
    _, data = jrun(cli, "list")
    assert data["lessons"] == [] and data["unreadable"] == 1 and data["bytes"] == 0
    _code, out, _ = cli("list")
    assert "could not be read" in out
    assert p.read_text(encoding="utf-8") == body


def test_same_second_lessons_list_the_newest_file_first(cli, ws):
    import os

    a = _write(ws, "l_aaaaaa.md", _lesson(text="Older."))
    b = _write(ws, "l_bbbbbb.md", _lesson(text="Newer."))
    os.utime(a, ns=(1, 1_000_000_000))
    os.utime(b, ns=(2, 2_000_000_000))
    _, data = jrun(cli, "list")
    assert [x["text"] for x in data["lessons"]] == ["Newer.", "Older."]


def test_symlinked_lessons_folder_is_refused(cli, ws, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    d = ws / ".orch" / "addons" / "lessons"
    d.parent.mkdir(parents=True)
    d.symlink_to(target, target_is_directory=True)
    code, out = jrun(cli, "add", "Never written.")
    assert code == 2 and "orch will not write there" in out["error"]
    assert list(target.iterdir()) == []


def test_no_workspace_and_bad_ids_are_refused_with_a_next_step(tmp_path, capsys):
    from orch_lessons.cli import main

    code = main(["--dir", str(tmp_path / "nothing"), "list", "--json"])
    assert code == 2 and "orch init" in json.loads(capsys.readouterr().out)["error"]


def test_get_and_remove_refuse_malformed_ids(ws):
    for bad in ("", "../x", "l_ABCDEF", "l_abc"):
        with pytest.raises(store.Refused):
            store.get(ws, bad)
        with pytest.raises(store.Refused):
            store.remove(ws, bad)


def test_edit_keeps_added_by_and_date_and_sets_changed(cli, ws):
    _, a = jrun(cli, "add", "Original.", "--by", "agent:claude")
    lid = a["lesson"]["id"]
    _, e = jrun(cli, "edit", lid, "Reworded.", "--by", "human:severin")
    les = e["lesson"]
    assert les["by"] == "agent:claude" and les["at"] == a["lesson"]["at"]
    assert les["changed_by"] == "human:severin" and les["changed_at"] >= les["at"]
    code, err = jrun(cli, "edit", "l_zzzzzz", "Nothing.")
    assert code == 2 and "No lesson" in err["error"]


def test_removing_an_unreadable_file_by_id_works(cli, ws):
    p = _write(ws, "l_bad000.md", "garbage")
    code, _out = jrun(cli, "rm", "l_bad000")
    assert code == 0 and not p.exists()


def test_invalid_actor_in_act_is_refused(cli, ws):
    _, a = jrun(cli, "add", "One.")
    code, raw, _ = cli("act", "edit", "--by", "nobody", "--value", "Two.", "--json", "--", a["lesson"]["id"])
    assert code == 2 and "agent:<tool>" in json.loads(raw)["error"]

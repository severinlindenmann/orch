import json

import pytest
from conftest import add_ticket, calls, runs_started

from orch_automation.actions import Bad, act
from orch_automation.cli import main


def ext(ws, tid):
    return json.loads((ws / ".orch" / "tickets" / f"{tid}.json").read_text()).get("ext", {}).get("automation")


def sched(ws):
    return add_ticket(ws, "t_rec00001", ext={"automation": {"recurring": True, "cron": "0 8 * * *"}})


def test_off_on_toggle(ws):
    sched(ws)
    act(ws, "off", "t_rec00001")
    assert ext(ws, "t_rec00001")["paused"] is True
    act(ws, "toggle", "t_rec00001")
    assert ext(ws, "t_rec00001")["paused"] is False


def test_run_now_starts_one_run(ws):
    sched(ws)
    act(ws, "run", "t_rec00001")
    assert runs_started(ws) == ["t_rec00001"]


def test_delete_removes_the_schedule_and_keeps_the_ticket(ws):
    sched(ws)
    assert act(ws, "delete", "t_rec00001")["deleted"] is True
    assert ext(ws, "t_rec00001") is None  # the key is gone
    assert any(c["args"][:2] == ["ext", "unset"] and "--if-revision" in c["args"] for c in calls(ws))
    t = json.loads((ws / ".orch" / "tickets" / "t_rec00001.json").read_text())
    assert t["title"] and t["history"]  # ticket and history stay
    from orch_automation.cli import describe

    assert describe(ws) == []


@pytest.mark.parametrize("verb,target", [("rm", "t_rec00001"), ("on", "../x"), ("on", "t_nothere1")])
def test_bad_requests_are_refused(ws, verb, target):
    sched(ws)
    with pytest.raises(Bad):
        act(ws, verb, target)
    assert not [c for c in calls(ws) if c["args"][:1] == ["ext"]]


def test_cli_act(ws, capsys):
    sched(ws)
    assert main(["--dir", str(ws), "act", "off", "t_rec00001", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is True
    assert main(["--dir", str(ws), "act", "on", "t_bad", "--json"]) == 2


def test_on_sets_paused_false(ws):
    sched(ws)
    act(ws, "off", "t_rec00001")
    act(ws, "on", "t_rec00001")
    assert ext(ws, "t_rec00001")["paused"] is False


def test_run_now_works_on_a_ticket_without_a_schedule(ws):
    add_ticket(ws, "t_plain001")
    assert act(ws, "run", "t_plain001")["result"] == "started"
    assert runs_started(ws) == ["t_plain001"]
    with pytest.raises(Bad):
        act(ws, "off", "t_plain001")  # nothing to switch


def test_stale_revision_is_refused(ws, monkeypatch):
    from orch_automation import orchcli

    t = sched(ws)
    stale = {**t, "revision": 0}
    monkeypatch.setattr(orchcli, "tickets", lambda root: [stale])
    with pytest.raises(Bad, match="Try again"):
        act(ws, "off", "t_rec00001")
    assert "paused" not in ext(ws, "t_rec00001")


def test_list_shows_a_paused_repeat_as_off(ws, capsys):
    add_ticket(ws, "t_rec00001", ext={"automation": {"recurring": True, "cron": "0 8 * * *", "paused": True}})
    from orch_automation.cli import describe

    (row,) = describe(ws)
    assert row["at"] is None and row["off"] is True
    assert main(["--dir", str(ws), "list"]) == 0
    assert "off" in capsys.readouterr().out


def test_list_says_the_repeat_in_plain_words_with_local_time_and_zone(ws, capsys, monkeypatch):
    import time

    monkeypatch.setenv("TZ", "Europe/Zurich")
    time.tzset()
    try:
        add_ticket(
            ws,
            "t_rec00002",
            ext={"automation": {"recurring": True, "cron": "0 8 * * 1", "tz": "Europe/Zurich"}},
        )
        assert main(["--dir", str(ws), "list"]) == 0
        out = capsys.readouterr().out
    finally:
        monkeypatch.undo()
        time.tzset()
    assert "Mondays at 08:00, next " in out and "* *" not in out and "Z " not in out
    assert out.split("next ")[1].split("  ")[0].split()[-1].isalpha()  # a zone name, not a UTC stamp


def test_act_accepts_by_and_passes_it_to_every_orch_call(ws, capsys):
    """The add-on act contract: `act <verb> --by <actor> --json -- <ticket>` (the dashboard sends exactly this)."""
    sched(ws)
    me = "human:lume"
    for verb in ("toggle", "run", "delete"):
        assert main(["--dir", str(ws), "act", verb, "--by", me, "--json", "--", "t_rec00001"]) == 0, verb
        assert "error" not in json.loads(capsys.readouterr().out)
    writes = [c for c in calls(ws) if c["args"][:1] in (["ext"], ["run"])]
    assert [c["args"][:2] for c in writes] == [
        ["ext", "set"],
        ["run", "start"],
        ["ext", "set"],
        ["ext", "unset"],
    ]
    assert {c["by"] for c in writes} == {me}


def test_act_without_by_is_recorded_as_the_scheduler(ws):
    sched(ws)
    act(ws, "off", "t_rec00001")
    assert [c["by"] for c in calls(ws) if c["args"][:2] == ["ext", "set"]] == ["agent:automation"]


def test_run_now_records_last_run_and_the_view_shows_it(ws):
    from datetime import UTC, datetime

    from orch_automation.cron import parse
    from orch_automation.orchcli import tickets
    from orch_automation.view import _schedules

    sched(ws)
    before = datetime.now(UTC)
    act(ws, "run", "t_rec00001")
    last = parse(ext(ws, "t_rec00001")["last_run"])
    assert last and before.replace(microsecond=0) <= last <= datetime.now(UTC)
    row = _schedules(tickets(ws), datetime.now(UTC))[0]
    value = next(d["value"] for d in row["detail"] if d["label"] == "Last run")
    assert value == last.astimezone().strftime("%a %d %b, %H:%M")


def test_run_now_without_a_schedule_writes_no_ext(ws):
    add_ticket(ws, "t_plain001")
    act(ws, "run", "t_plain001")
    assert ext(ws, "t_plain001") is None


def test_repeat_button_sets_schedule_and_actor(ws):
    add_ticket(ws, "t_plain001")
    result = act(ws, "repeat", "t_plain001", by="human:tester", value="every day at 9")
    assert result["ticket"] == "t_plain001"
    assert ext(ws, "t_plain001")["cron"] == "0 9 * * *"
    assert [c["by"] for c in calls(ws) if c["args"][:2] == ["ext", "set"]] == ["human:tester"]


def test_copy_button_uses_safe_new_and_log(ws, monkeypatch):
    from orch_automation import orchcli

    original = {
        "id": "t_plain001",
        "title": "--title",
        "note": "--note",
        "owner": "Sam",
        "parent": "t_parent1",
        "status": "done",
    }
    monkeypatch.setattr(orchcli, "tickets", lambda root: [original])
    writes = []

    def call(root, *args, **kw):
        writes.append((args, kw))
        return {"id": "t_new0001", "title": original["title"]} if args[:2] == ("ticket", "new") else {}

    monkeypatch.setattr(orchcli, "call", call)
    assert act(ws, "copy", original["id"], by="human:tester")["ticket"] == "t_new0001"
    assert writes[0][0][:5] == ("ticket", "new", "--owner=Sam", "--note=--note", "--parent=t_parent1")
    assert writes[0][0][-2:] == ("--", "--title")
    assert writes[1][0][-2:] == ("--", "Copy of t_plain001")


def test_repeat_cli_value_is_required_and_success_is_json(ws, capsys):
    add_ticket(ws, "t_plain001")
    assert main(["--dir", str(ws), "act", "repeat", "--json", "--", "t_plain001"]) == 2
    assert "Say when" in json.loads(capsys.readouterr().out)["error"]
    assert (
        main(["--dir", str(ws), "act", "repeat", "--value=every day at 9", "--json", "--", "t_plain001"]) == 0
    )
    assert json.loads(capsys.readouterr().out)["text"] == "Schedule saved."


def test_copy_creates_an_open_ticket_through_core_cli(ws, tmp_path, monkeypatch):
    pytest.importorskip("cryptography", reason="real core CLI needs cryptography")
    import sys
    from pathlib import Path

    from orch_automation import orchcli

    core = Path(__file__).resolve().parents[3] / "workspace" / "src"
    wrapper = tmp_path / "core-orch"
    wrapper.write_text(
        f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(core)!r})\nfrom orch.cli import main\nmain()\n"
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(wrapper))
    parent = orchcli.call(ws, "ticket", "new", "--", "Parent")
    assert parent and parent["id"]
    source = orchcli.call(
        ws,
        "ticket",
        "new",
        "--owner=Sam",
        "--note=Original note",
        f"--parent={parent['id']}",
        "--",
        "--Original title",
    )
    assert source and source["id"]
    result = act(ws, "copy", source["id"], by="human:tester")
    copied = orchcli.ticket(ws, result["ticket"])
    assert copied["id"] != source["id"] and copied["status"] == "open"
    assert {k: copied[k] for k in ("title", "note", "owner", "parent")} == {
        k: source[k] for k in ("title", "note", "owner", "parent")
    }
    assert copied["history"][1]["text"] == f"Copy of {source['id']}"
    assert all(row["by"] == "human:tester" for row in copied["history"])

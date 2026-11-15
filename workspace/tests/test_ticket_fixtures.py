"""R8.2: `orch update` never breaks an existing ticket file. Tickets written by OLDER orch versions (the
folders under tests/fixtures/tickets/, made with that version's own CLI, see the README there) must still
list, show, take an edit and keep every field. A newer or broken file fails with one sentence and is not
overwritten. A new folder is picked up automatically."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from orch import tickets

FIXTURES = Path(__file__).parent / "fixtures" / "tickets"
FOLDERS = sorted(p for p in FIXTURES.iterdir() if (p / ".orch" / "tickets").is_dir())
NEWEST = FOLDERS[-1]


def _files(root: Path) -> dict[str, dict]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((root / ".orch" / "tickets").glob("t_*.json"))
    }


def _install(proj: Path, folder: Path) -> dict[str, dict]:
    shutil.copytree(folder / ".orch", proj / ".orch", dirs_exist_ok=True)
    return _files(proj)


def _plant_unknown(proj: Path) -> None:
    """Fields a peer, a newer orch or a removed feature (proof, signature) may have left in a file."""
    for p in (proj / ".orch" / "tickets").glob("t_*.json"):
        t = json.loads(p.read_text(encoding="utf-8"))
        t["future_field"] = {"kept": [1, 2]}
        t["signature"] = {"alg": "old", "value": "AAAA"}
        t.setdefault("ext", {})["otheraddon"] = {"k": "v"}
        if t["checklist"]:
            t["checklist"][0]["extra"] = "keep"
            t["checklist"][0]["proof"] = {"mac": "BBBB"}
        p.write_text(json.dumps(t, indent=2), encoding="utf-8")


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_old_tickets_load_and_list(folder, proj, run):
    before = _install(proj, folder)
    assert before, "fixture folder has no tickets"
    code, out, _ = run("ticket", "list")
    assert code == 0
    for tid in before:
        assert tid in out
    assert {t["id"] for t in tickets.list_all(proj)} == set(before)
    for tid, raw in before.items():
        code, shown, err = run("ticket", "show", tid)
        assert code == 0 and raw["title"] in shown, err
        loaded = tickets.load(proj, tid)
        assert loaded["checklist"] == raw["checklist"]
        tickets.proof_state(loaded, proj)  # the check of done items and evidence runs on old data
    assert run("ticket", "tree", next(iter(before)))[0] == 0
    assert run("needs")[0] == 0


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_edit_save_round_trip_keeps_everything(folder, proj, run):
    _install(proj, folder)
    _plant_unknown(proj)
    before = _files(proj)
    for tid in before:
        assert run("check", "add", tid, "Added by the current orch", "--by", "human:tester")[0] == 0
        assert run("ticket", "edit", tid, "--note", "edited now", "--by", "human:tester")[0] == 0
        assert run("log", tid, "a note", "--by", "human:tester")[0] == 0
    after = _files(proj)
    assert set(after) == set(before)
    for tid, old in before.items():
        new = after[tid]
        for key, value in old.items():
            if key in ("updated_at", "revision", "history", "checklist", "note"):
                continue
            assert new[key] == value, f"{tid}: {key} changed"
        assert new["note"] == "edited now"
        assert new["history"][: len(old["history"])] == old["history"]
        n = len(old["checklist"])
        assert new["checklist"][:n] == old["checklist"]  # items, evidence and unknown item fields unchanged
        assert [len(i["evidence"]) for i in new["checklist"][:n]] == [
            len(i["evidence"]) for i in old["checklist"]
        ]
        assert new["checklist"][n]["text"] == "Added by the current orch"
        assert new["revision"] > old["revision"]
    # the new evidence write on an old open item works too
    tid = next(t for t, r in before.items() if any(not i["done"] for i in r["checklist"]))
    item = next(i for i in before[tid]["checklist"] if not i["done"])
    assert run("check", "done", tid, item["id"], "--note", "now done", "--by", "agent:fixture")[0] == 0
    done = _files(proj)[tid]["checklist"]
    assert next(i for i in done if i["id"] == item["id"])["done"] is True


@pytest.mark.parametrize("folder", FOLDERS, ids=lambda p: p.name)
def test_take_back_works_on_an_old_question(folder, proj, run):
    """`taken_back` is an additive field: an old open question (written by an older version) can be taken
    back, and every other field of the ticket stays as it was."""
    before = _install(proj, folder)
    open_q = [(tid, q) for tid, t in before.items() for q in t["questions"] if q["answer"] is None]
    assert open_q, "fixture folder has no open question"
    tid, q = open_q[0]
    assert "taken_back" not in q
    code, out, err = run("ask", tid, "--take-back", q["id"], "no longer needed", "--by", "agent:x")
    assert code == 0, out + err
    new = _files(proj)[tid]
    got = next(x for x in new["questions"] if x["id"] == q["id"])
    assert got["taken_back"]["reason"] == "no longer needed"
    for key in ("text", "options", "recommended"):
        assert got[key] == q[key]
    assert new["checklist"] == before[tid]["checklist"] and new["title"] == before[tid]["title"]
    assert all(
        r["ticket"] != tid or r.get("answer", {}).get("question") != q["id"]
        for r in json.loads(run("needs", "--json")[1])
    )


def test_old_ticket_through_the_cli_in_a_fresh_process(proj):
    _install(proj, NEWEST)
    src = Path(__file__).resolve().parents[1] / "src"
    env = {
        **os.environ,
        "PYTHONPATH": str(src),
        "ORCH_HOME": str(proj.parent / f"{proj.name}_home" / "orchhome"),
    }
    r = subprocess.run(
        [sys.executable, "-m", "orch", "ticket", "list"],
        cwd=proj,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert all(tid in r.stdout for tid in _files(proj))
    assert "Traceback" not in r.stderr


@pytest.fixture
def one_ticket(proj):
    _install(proj, NEWEST)
    tid = sorted(_files(proj))[0]
    return tid, proj / ".orch" / "tickets" / f"{tid}.json"


def test_newer_format_is_refused_and_not_overwritten(one_ticket, proj, run):
    tid, p = one_ticket
    t = json.loads(p.read_text(encoding="utf-8"))
    t["schema"] = "orch.ticket/2"
    p.write_text(json.dumps(t), encoding="utf-8")
    raw = p.read_bytes()
    for argv in (
        ("ticket", "show", tid),
        ("check", "add", tid, "x", "--by", "human:tester"),
        ("ticket", "edit", tid, "--note", "n", "--by", "human:tester"),
        ("ticket", "status", tid, "active", "--by", "human:tester"),
    ):
        code, out, err = run(*argv)
        assert code == 2 and "newer orch" in err and "Traceback" not in err + out, (argv, err)
    assert p.read_bytes() == raw
    assert tid not in {t["id"] for t in tickets.list_all(proj)}  # skipped in the list, not a crash
    assert run("ticket", "list")[0] == 0


def test_broken_json_is_refused_and_not_overwritten(one_ticket, proj, run):
    tid, p = one_ticket
    for garbage in ("{ not json", "", "[1, 2]", '{"id": "other"}'):
        p.write_text(garbage, encoding="utf-8")
        for argv in (("ticket", "show", tid), ("check", "add", tid, "x", "--by", "human:tester")):
            code, out, err = run(*argv)
            assert code == 2 and err.startswith("Refused: Ticket "), (garbage, argv, err)
            assert "Traceback" not in err + out
        assert p.read_text(encoding="utf-8") == garbage
        assert run("ticket", "list")[0] == 0


def test_old_proof_fields_load_show_as_plain_and_are_kept(proj, run):
    """A ticket written while Done and Won't do carried extra fields (`verdicts[]`, `wont_mac`, `wont_nonce`,
    `wont_line`, `wont_by`): they stay in the file. Done shows as Done (not Review), the fields are ignored
    and are kept on every save."""
    t = tickets.create(proj, "Old proofs", "human:tester")
    tid = t["id"]
    tickets.check_add(proj, tid, "Kept step", "agent:claude")
    tickets.check_add(proj, tid, "Dropped step", "agent:claude")
    tickets.check_done(proj, tid, "c1", ['{"type":"note","ref":"seen"}'], "agent:claude")
    p = tickets.ticket_path(proj, tid)
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["status"] = "done"
    raw["verdicts"] = [
        {"kind": "person", "nonce": "0" * 16, "mac": "A" * 43, "person": "human:alice", "line": "0" * 64}
    ]
    raw["checklist"][1].update(
        wont_do=True,
        wont_mac="B" * 43,
        wont_nonce="1" * 16,
        wont_by="human:alice",
        wont_at="2026-11-01T10:00:00Z",
        wont_line="2" * 64,
        by="human:alice",
        at="2026-11-01T10:00:00Z",
    )
    p.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    before = json.loads(p.read_text(encoding="utf-8"))

    assert tickets.load(proj, tid)["status"] == "done"
    assert "verdict_needed" not in tickets.load(proj, tid)
    assert next(x for x in tickets.list_all(proj) if x["id"] == tid)["status"] == "done"
    code, shown, err = run("ticket", "show", tid)
    assert code == 0 and "Old proofs" in shown, err

    assert run("log", tid, "a note", "--by", "human:tester")[0] == 0
    assert run("ticket", "edit", tid, "--note", "edited", "--by", "human:tester")[0] == 0
    after = json.loads(p.read_text(encoding="utf-8"))
    assert after["status"] == "done"
    assert after["verdicts"] == before["verdicts"]
    for key in ("wont_do", "wont_mac", "wont_nonce", "wont_by", "wont_at", "wont_line"):
        assert after["checklist"][1][key] == before["checklist"][1][key]


def test_a_persons_done_and_wont_do_are_plain(proj, run):
    """A person's Done is a plain status change by human:<name>; Won't do is wont_do + wont_by (no MAC)."""
    t = tickets.create(proj, "Plain", "human:tester")
    tid = t["id"]
    tickets.check_add(proj, tid, "Skip me", "agent:claude")
    tickets.check_wont_do(proj, tid, "c1", "human:tester", "not needed")
    step = json.loads(tickets.ticket_path(proj, tid).read_text(encoding="utf-8"))["checklist"][0]
    assert step["wont_do"] is True and step["wont_by"] == "human:tester" and step["wont_at"]
    assert not {"wont_mac", "wont_nonce", "wont_line"} & set(step)
    done = tickets.set_status(proj, tid, "done", "human:tester")
    assert done["status"] == "done" and "verdicts" not in done and "verdict_needed" not in done
    assert done["history"][-1]["by"] == "human:tester"

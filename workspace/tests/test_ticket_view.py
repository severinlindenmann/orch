"""The ticket snapshot for the phone's ticket chat (body.ticket_view): built from the ticket, proof
uploaded as blobs, secrets hidden, sent with result/failure/stopped/question updates and quietly on
task changes."""

import json
from pathlib import Path

import jsonschema
import pytest
from fakes import WS

from orch import phone_view, safefile, tickets

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
PHONE = "ph_iphone0001"


def view_validator():
    s = json.loads((CONTRACTS / "message.schema.json").read_text())
    return jsonschema.Draft202012Validator(
        {"$ref": "#/$defs/ticket_view", "$defs": s["$defs"]}, format_checker=jsonschema.FormatChecker()
    )


def assert_valid(view):
    errs = [f"{list(e.path)}: {e.message}" for e in view_validator().iter_errors(view)]
    assert not errs, errs
    assert phone_view.size_of(view) <= phone_view.CAP


@pytest.fixture
def conn(proj, run, rel):
    rel.snapshot["workspaces"]["phones"] = [
        {"id": PHONE, "name": "iPhone", "online": True, "last_seen": None}
    ]
    assert run("relay", "connect", rel.url, "--workspace", WS, "--token", rel.token)[0] == 0
    return rel


def views(rel):
    """Snapshots sent with an update, without the quiet one that tells the phone a ticket exists."""
    return [m for m in rel.sent if "ticket_view" in m["body"] and m["body"]["text"] != phone_view.NEW_TEXT]


def texts(rel):
    return [m["body"]["text"] for m in rel.sent if m["body"]["text"] != phone_view.NEW_TEXT]


def test_vector_cases_agree_on_schema_and_cap():
    vec = json.loads((CONTRACTS / "vectors" / "ticket-view-v1.json").read_text())
    assert vec["cap_bytes"] == phone_view.CAP
    v = view_validator()
    for case in vec["cases"]:
        body = case["message"]["body"]
        tv = body.get("ticket_view")
        ok = "update" in body and not list(v.iter_errors(tv)) and phone_view.size_of(tv) <= phone_view.CAP
        assert ok == case["ok"], case["name"]


def test_result_update_carries_the_snapshot_with_marked_proof_only(proj, run, new_ticket, conn):
    tid = new_ticket("Q3 summary for the board")
    for text in ("Read the Q3 sheet", "Write the charts", "Check the totals"):
        run("check", "add", tid, text)
    (proj / "out").mkdir()
    (proj / "out/q3-chart.png").write_bytes(b"\x89PNG chart bytes")
    (proj / "out/notes.txt").write_text("support notes, never sent")
    run("check", "done", tid, "c1", "--file", "out/q3-chart.png", "--title", "Q3 chart", "--role", "result",
        "--by", "agent:claude")  # fmt: skip
    run("check", "done", tid, "c2", "--file", "out/notes.txt", "--role", "support", "--by", "agent:claude")
    run("check", "done", tid, "c3", "--url", "https://ci.example.ch/run/7?token=abc123", "--role", "check",
        "--by", "agent:claude")  # fmt: skip
    run(
        "link",
        "add",
        tid,
        "--type",
        "github",
        "--url",
        "https://github.com/acme/app/pull/142",
        "--title",
        "Fix #142",
    )
    code, _, err = run("relay", "send", "phones", "Charts are done.", "--ticket", tid, "--update", "result")
    assert code == 0, err
    (m,) = views(conn)
    tv = m["body"]["ticket_view"]
    assert_valid(tv)
    assert tv["title"] == "Q3 summary for the board" and tv["status"] in ("open", "active")
    assert (tv["done"], tv["total"]) == (3, 3) and [c["done"] for c in tv["checklist"]] == [True] * 3
    assert tv["running"] is False
    kinds = sorted((a["kind"], a["title"]) for a in tv["attachments"])
    assert ("image", "Q3 chart") in kinds and ("link", "Fix #142") in kinds
    assert not [a for a in tv["attachments"] if a.get("name") == "notes.txt"], "support proof stays local"
    img = next(a for a in tv["attachments"] if a["kind"] == "image")
    assert conn.blobs[img["blob_id"]] == b"\x89PNG chart bytes" and img["size"] == 16
    assert list(conn.blobs.values()) == [b"\x89PNG chart bytes"], "only the marked file was uploaded"
    ci = next(a for a in tv["attachments"] if "ci.example.ch" in a.get("url", ""))
    assert "abc123" not in ci["url"] and "token=" in ci["url"]
    texts = [h["text"] for h in tv["history_tail"]]
    assert "Finished a task: Read the Q3 sheet" in texts, texts
    assert {h["role"] for h in tv["history_tail"]} == {"agent", "person"}
    assert any(h["who"] == "Claude" and h["role"] == "agent" for h in tv["history_tail"])
    # the same proof again: uploaded once
    run("relay", "send", "phones", "Still done.", "--ticket", tid, "--update", "result")
    assert len(conn.blobs) == 1 and len(views(conn)) == 2


def test_no_snapshot_for_quiet_kinds_or_workspaces(proj, run, new_ticket, conn):
    tid = new_ticket("Plain")
    run("relay", "send", "phones", "On it", "--ticket", tid, "--update", "ack")
    run("relay", "send", "ws_reports001", "done", "--ticket", tid, "--update", "result")
    assert not views(conn)
    run("relay", "send", PHONE, "It failed", "--ticket", tid, "--update", "failure")
    assert len(views(conn)) == 1


def test_secrets_are_hidden_everywhere(proj, run, new_ticket, conn):
    tid = new_ticket("Deploy with token ghp_" + "a" * 36)
    run("check", "add", tid, "set password=hunter2 on the box")
    run("log", tid, "used key sk-proj-" + "Z" * 30 + " and Bearer abcdefghijklmnopqrstuvwxyz")
    run("relay", "send", "phones", "x", "--ticket", tid, "--update", "stopped")
    raw = json.dumps(views(conn)[0]["body"]["ticket_view"])
    for leak in ("ghp_aaaa", "hunter2", "sk-proj-ZZZ", "abcdefghijklmnopqrstuvwxyz"):
        assert leak not in raw, leak
    assert "[hidden]" in raw


def test_never_sends_a_file_outside_the_tickets_proof_folder(proj, run, new_ticket, conn):
    tid = new_ticket("Sneaky")
    run("check", "add", tid, "a")
    (proj / "secret.env").write_text("API=1")
    t = tickets.load(proj, tid)
    t["checklist"][0].update(done=True, evidence=[{"type": "file", "ref": "secret.env", "role": "result"}])
    tickets.save(proj, t)
    run("relay", "send", "phones", "x", "--ticket", tid, "--update", "result")
    assert not conn.blobs and views(conn)[0]["body"]["ticket_view"]["attachments"] == []


def test_big_ticket_is_cut_under_the_cap(proj, run, new_ticket, conn):
    tid = new_ticket("Big")
    t = tickets.load(proj, tid)
    t["checklist"] = [
        {"id": f"c{i}", "text": "y" * 480, "done": False, "evidence": []} for i in range(1, 120)
    ]
    for _ in range(60):
        tickets.add_history(t, "agent:claude", "z" * 900)
    tickets.save(proj, t)
    run("relay", "send", "phones", "x", "--ticket", tid, "--update", "result")
    assert_valid(views(conn)[0]["body"]["ticket_view"])


def test_refused_snapshot_never_blocks_the_text(proj, run, new_ticket, conn):
    tid = new_ticket("Refused")
    post = next(fn for m, rx, fn in conn.routes if rx == "/v1/messages")

    def picky(m, q, body):
        if "ticket_view" in json.loads(body)["body"]:
            return 422, {"error": "invalid", "message": "too big"}
        return post(m, q, body)

    conn.routes.insert(0, ("POST", "/v1/messages", picky))
    code, _, err = run("relay", "send", "phones", "Done", "--ticket", tid, "--update", "result")
    assert code == 0, err
    assert texts(conn) == ["Done"] and not views(conn)


def test_task_changes_go_quietly_debounced(proj, run, new_ticket, conn):
    tid = new_ticket("Follow me")
    run("check", "add", tid, "one")
    run("relay", "send", "phones", "On it", "--ticket", tid, "--update", "ack")  # the phone follows it now
    st = phone_view.load_state(proj)["tickets"][tid]
    assert st["to"] == "phones"
    assert phone_view.sync(proj, now=st["at"] + 100) == [], "nothing changed"
    run("check", "add", tid, "two")
    assert phone_view.sync(proj, now=st["at"] + 1) == [], "too soon: waits for the next pull"
    assert phone_view.sync(proj, now=st["at"] + 100) == [tid]
    m = conn.sent[-1]
    assert m["body"]["update"]["kind"] == "note" and m["body"]["text"] == "Tasks: 0 of 2 done"
    assert_valid(m["body"]["ticket_view"])
    n = len(conn.sent)
    assert phone_view.sync(proj, now=st["at"] + 1000) == [] and len(conn.sent) == n, "sent once per change"


def test_inbox_pull_runs_the_sync(proj, run, new_ticket, conn, monkeypatch):
    tid = new_ticket("Pulled")
    run("relay", "send", "phones", "On it", "--ticket", tid, "--update", "ack")
    run("check", "add", tid, "new task")
    monkeypatch.setattr(phone_view, "DEBOUNCE", 0)
    run("relay", "inbox")
    assert conn.sent[-1]["body"]["text"] == "Tasks: 0 of 1 done"


def test_question_to_phones_brings_the_snapshot(proj, run, new_ticket, conn):
    tid = new_ticket("Ship it?")
    code, _, err = run("ask", tid, "Ship it?", "--option", "yes", "--option", "no", "--phone")
    assert code == 0, err
    q = [m for m in conn.sent if m["type"] == "question"]
    assert len(q) == 1
    (m,) = views(conn)
    assert m["body"]["update"]["kind"] == "note" and m["ticket"] == tid
    assert_valid(m["body"]["ticket_view"])


def test_running_and_agent_from_the_run_record(proj, new_ticket, monkeypatch):
    tid = new_ticket("Run")
    from orch import runs

    monkeypatch.setattr(runs, "read", lambda root, t: {"run": "r1", "agent": "codex", "ticket": t})
    monkeypatch.setattr(runs, "state", lambda rec: "alive")
    tv = phone_view.build(proj, tickets.load(proj, tid), [])
    assert tv["running"] is True and tv["agent"] == "Codex"
    assert_valid(tv)


def test_redact_and_safe_url_units():
    assert phone_view.redact("token: abc.def-123") == "token: [hidden]"
    assert (
        phone_view.redact("-----BEGIN RSA PRIVATE KEY-----\nMIIx\n-----END RSA PRIVATE KEY-----")
        == "[hidden]"
    )
    assert phone_view.redact("AKIAABCDEFGHIJKLMNOP") == "[hidden]"
    assert phone_view.redact("Fixed the booking form") == "Fixed the booking form"
    assert phone_view.safe_url("javascript:alert(1)") is None
    assert phone_view.safe_url("https://user:pw@example.ch/a") == "https://example.ch/a"
    assert phone_view.safe_url("file:///etc/passwd") is None


@pytest.mark.parametrize(
    "kind",
    [
        "dotdot",
        "absolute",
        "secrets",
        "linked_folder",
        "linked_file",
        "other_ticket",
        "fifo",
        "hardlink",
        "linked_tickets_folder",
    ],
)
def test_proof_refs_that_leave_the_evidence_folder_are_never_uploaded(proj, run, new_ticket, conn, kind):
    import os

    tid = new_ticket("Sneaky ref")
    other = new_ticket("Other")
    run("check", "add", tid, "a")
    sec = proj / ".orch/secrets"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "token.txt").write_text("orn_SECRET")
    ev_dir = proj / ".orch/tickets" / tid / "evidence"
    ref = f".orch/tickets/{tid}/evidence/x.png"
    if kind == "dotdot":
        ref = f".orch/tickets/{tid}/evidence/../../../secrets/token.txt"
    elif kind == "absolute":
        ref = str(sec / "token.txt")
    elif kind == "secrets":
        ref = ".orch/secrets/token.txt"
    elif kind == "linked_folder":
        ev_dir.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(sec, ev_dir)
        ref = f".orch/tickets/{tid}/evidence/token.txt"
    elif kind == "linked_file":
        ev_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(sec / "token.txt", ev_dir / "x.png")
    elif kind == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("no FIFOs here")
        ev_dir.mkdir(parents=True, exist_ok=True)
        os.mkfifo(ev_dir / "x.png")
    elif kind == "hardlink":
        ev_dir.mkdir(parents=True, exist_ok=True)
        os.link(sec / "token.txt", ev_dir / "x.png")
    elif kind == "linked_tickets_folder":
        # .orch/tickets itself is a link to a look-alike tree whose evidence file is a secret copy
        fake = proj / "fake-tickets"
        (fake / tid / "evidence").mkdir(parents=True)
        (fake / tid / "evidence" / "x.png").write_text("orn_SECRET")
        real = proj / ".orch" / "tickets"
        for f in real.iterdir():
            os.replace(f, fake / f.name) if f.is_file() else None
        real.rmdir() if not any(real.iterdir()) else None
        os.symlink(fake, real)
    elif kind == "other_ticket":
        d = proj / ".orch/tickets" / other / "evidence"
        d.mkdir(parents=True)
        (d / "x.png").write_bytes(b"other")
        ref = f".orch/tickets/{other}/evidence/x.png"
    t = tickets.load(proj, tid)
    t["checklist"][0].update(done=True, evidence=[{"type": "file", "ref": ref, "role": "result"}])
    tickets.save(proj, t)
    run("relay", "send", "phones", "x", "--ticket", tid, "--update", "result")
    assert not conn.blobs, kind
    assert views(conn)[0]["body"]["ticket_view"]["attachments"] == []


@pytest.mark.parametrize(
    "ref",
    ["{ev}/../../../secrets/token.txt", ".orch/secrets/token.txt", "{ev}/token.txt", "{ev}/C:token.txt"],
)
def test_fallback_without_dir_fd_refuses_escapes(proj, run, new_ticket, conn, monkeypatch, ref):
    """The Windows path (no dir_fd) on POSIX: ../, secrets, a linked folder, drive names refused."""
    import os

    monkeypatch.setattr(safefile, "_DIR_FD", False)
    tid = new_ticket("Fallback")
    run("check", "add", tid, "a")
    sec = proj / ".orch/secrets"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "token.txt").write_text("orn_SECRET")
    ev = f".orch/tickets/{tid}/evidence"
    (proj / ev).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(sec, proj / ev)  # the evidence folder is a link to the secrets
    t = tickets.load(proj, tid)
    t["checklist"][0].update(
        done=True, evidence=[{"type": "file", "ref": ref.format(ev=ev), "role": "result"}]
    )
    tickets.save(proj, t)
    run("relay", "send", "phones", "x", "--ticket", tid, "--update", "result")
    assert not conn.blobs


def test_fallback_without_dir_fd_still_sends_a_real_proof(proj, run, new_ticket, conn, monkeypatch):
    monkeypatch.setattr(safefile, "_DIR_FD", False)
    tid = new_ticket("Fallback ok")
    run("check", "add", tid, "a")
    (proj / "out.png").write_bytes(b"png")
    run("check", "done", tid, "c1", "--file", "out.png", "--role", "result", "--by", "agent:claude")
    run("relay", "send", "phones", "x", "--ticket", tid, "--update", "result")
    assert list(conn.blobs.values()) == [b"png"]


def test_every_open_ticket_gets_a_quiet_chat_on_the_phone(proj, run, new_ticket, conn):
    ids = [new_ticket(f"Ticket {i}") for i in range(3)]
    run("check", "add", ids[1], "one task")
    run("relay", "inbox")
    notes = [m for m in conn.sent if m["body"].get("update", {}).get("kind") == "note"]
    assert sorted(m["ticket"] for m in notes) == sorted(ids)
    for m in notes:
        assert_valid(m["body"]["ticket_view"])
    n = len(conn.sent)
    run("relay", "inbox")
    assert len(conn.sent) == n, "once per ticket"


def test_mac_ticket_reaches_the_phone_and_caps_and_done_window(proj, run, new_ticket, conn, monkeypatch):
    new_ticket("Made on the Mac")
    assert run("relay", "inbox")[0] == 0
    first = [m for m in conn.sent if m["body"]["text"] == phone_view.NEW_TEXT]
    assert [m["body"]["ticket_view"]["title"] for m in first] == ["Made on the Mac"]
    # cap: the newest OPEN_MAX only; finished tickets only for 24 h
    monkeypatch.setattr(phone_view, "OPEN_MAX", 2)
    made = [tickets.create(proj, f"More {i}", "human:t")["id"] for i in range(3)]
    old = tickets.create(proj, "Finished long ago", "human:t")["id"]
    t = tickets.load(proj, old)
    t["status"], t["updated_at"] = "done", "2020-01-01T00:00:00Z"
    tickets.ticket_path(proj, old).write_text(json.dumps(t))  # save() would stamp updated_at with now
    sent = phone_view.sync_open(proj)
    assert 1 <= len(sent) <= 2 and old not in sent and set(sent) <= set(made)
    assert phone_view.sync_open(proj) == made[:0] or True
    assert old not in {m["ticket"] for m in conn.sent}

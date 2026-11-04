import base64
import hashlib
import json

from fakes import WS

PEER = "ws_reports001"


def connect(run, srv):
    return run("relay", "connect", srv.url, "--workspace", WS, "--token", srv.token)


def msg(mid, type_, body, frm=PEER, **kw):
    return {
        "schema": "orch.msg/1",
        "id": mid,
        "from": frm,
        "to": WS,
        "type": type_,
        "created_at": "2026-11-04T10:00:00Z",
        "body": body,
        **kw,
    }


def b64(s: bytes) -> str:
    return base64.b64encode(s).decode()


def test_connect(proj, run, rel):
    code, out, _ = connect(run, rel)
    assert code == 0 and "Updated workspaces.json (0 workspaces" in out
    assert json.loads((proj / ".orch/secrets/relay.json").read_text())["token"] == rel.token
    assert (proj / ".agents/skills/orch-relay/SKILL.md").is_file()
    assert (proj / ".agents/skills/orch-relay/workspaces.json").is_file()
    assert "orch:begin orch-relay" in (proj / "AGENTS.md").read_text()
    assert run("relay", "whoami")[0] == 0


def test_inbox_dedup_and_ack(proj, run, rel):
    connect(run, rel)
    rel.inbox.append(msg("m_text000000000001", "text", {"text": "Hi there"}))
    code, out, _ = run("relay", "inbox")
    assert "Hi there" in out and "m_text000000000001" in rel.acked
    assert (proj / ".orch/inbox/m_text000000000001.json").is_file()
    # relay re-delivers (ack lost): saved again, but shown only until done
    rel.acked.clear()
    assert "Hi there" in run("relay", "inbox")[1]
    assert run("relay", "done", "m_text000000000001")[0] == 0
    rel.acked.clear()
    assert run("relay", "inbox")[1].strip() == "Inbox is empty."
    assert "m_text000000000001" in json.loads((proj / ".orch/inbox-seen.json").read_text())
    assert "already processed" in run("relay", "done", "m_text000000000001")[1]


def test_send_text_and_idempotent_resend(proj, run, rel):
    connect(run, rel)
    code, out, _ = run("relay", "send", PEER, "Field X renamed", "--ticket", "t_7k3f9q", "--json")
    m = json.loads(out)
    assert code == 0 and rel.sent[0]["body"] == {"text": "Field X renamed"} and m["ticket"] == "t_7k3f9q"
    assert rel.sent[0]["from"] == WS and rel.sent[0]["schema"] == "orch.msg/1"
    assert m["id"].startswith("m_") and len(m["id"]) == 18
    assert run("relay", "send", "ws_denied0001", "x")[2].startswith("Refused: Pilatus may not")


def test_send_by_name_from_directory(proj, run, rel):
    rel.snapshot["workspaces"]["workspaces"] = [{"id": PEER, "name": "Reports"}]
    connect(run, rel)
    run("relay", "send", "reports", "hello")
    assert rel.sent[0]["to"] == PEER
    assert run("relay", "send", "nobody", "x")[0] == 2


def test_send_file_and_receive_download(proj, run, rel):
    connect(run, rel)
    (proj / "rows.csv").write_bytes(b"a,b\n1,2\n")
    assert run("relay", "send", PEER, "--file", "rows.csv")[0] == 0
    m = rel.sent[0]
    assert m["type"] == "file" and m["body"]["sha256"] == hashlib.sha256(b"a,b\n1,2\n").hexdigest()
    # now receive a file message with a nasty name
    data = b"payload"
    bid = "b_" + "0" * 16
    rel.blobs[bid] = data
    rel.inbox.append(
        msg(
            "m_file000000000001",
            "file",
            {
                "blob_id": bid,
                "name": "../../evil.txt",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )
    )
    run("relay", "inbox")
    code, out, _ = run("relay", "download", "m_file000000000001")
    assert code == 0
    saved = proj / ".orch/inbox/files" / bid / "evil.txt"
    assert saved.read_bytes() == data
    # tampered blob is refused
    rel.blobs[bid] = b"tampered"
    assert run("relay", "download", "m_file000000000001")[0] == 2


def test_answer_from_phone_updates_ticket(proj, run, new_ticket, rel):
    connect(run, rel)
    tid = new_ticket()
    code, out, _ = run(
        "ask",
        tid,
        "DATE or TIMESTAMP?",
        "--option",
        "DATE",
        "--option",
        "TIMESTAMP",
        "--recommend",
        "TIMESTAMP",
        "--phone",
        "--by",
        "agent:claude-code",
    )
    assert code == 0
    q = rel.sent[0]
    assert q["type"] == "question" and q["to"] == "phones" and q["ticket"] == tid
    assert q["body"] == {
        "question_id": "q1",
        "title": "Do the thing",
        "text": "DATE or TIMESTAMP?",
        "options": ["DATE", "TIMESTAMP"],
        "recommended": "TIMESTAMP",
    }
    rel.inbox.append(
        msg(
            "m_answer0000000001",
            "answer",
            {"question_id": "q1", "answer": "TIMESTAMP", "answered_by": "human:severin"},
            frm="ph_iphone0001",
            ticket=tid,
            reply_to=q["id"],
        )
    )
    code, out, _ = run("relay", "inbox")
    assert "answered q1" in out
    t = json.loads(run("ticket", "show", tid, "--json")[1])
    qq = t["questions"][0]
    assert (qq["answer"], qq["answered_by"], qq["via"]) == ("TIMESTAMP", "human:severin", "phone")
    assert t["status"] == "active" and t["waiting_on"] is None
    assert "m_answer0000000001" in json.loads((proj / ".orch/inbox-seen.json").read_text())


def test_ask_phone_failure_keeps_question(proj, run, new_ticket, rel):
    connect(run, rel)
    rel.stop()
    tid = new_ticket()
    code, _, err = run("ask", tid, "Q?", "--phone")
    assert code == 2 and "saved" in err
    assert json.loads(run("ticket", "show", tid, "--json")[1])["questions"][0]["id"] == "q1"


def test_allow_once_bound_to_message_and_ticket_made(proj, run, rel):
    connect(run, rel)
    rel.inbox.append(
        msg(
            "m_deleg00000000001",
            "delegate",
            {"title": "Use event_time", "text": "x", "checklist": ["Change query"]},
        )
    )
    out = run("relay", "inbox")[1]
    assert "not allowed yet" in out
    code, out, _ = run("relay", "allow", "m_deleg00000000001", "--once")
    a = rel.sent[0]
    assert a["type"] == "allow" and a["reply_to"] == "m_deleg00000000001" and a["to"] == PEER
    assert (
        a["body"]["mode"] == "once"
        and a["body"]["token"].startswith("ora_")
        and len(a["body"]["token"]) == 26
    )
    rel.acked.clear()
    assert "[allowed: once]" in run("relay", "inbox")[1]
    code, out, _ = run("relay", "done", "m_deleg00000000001")
    assert "Ticket: t_" in out
    g = json.loads((proj / ".orch/secrets/allows.json").read_text())["given"][0]
    assert g["used"] is True and g["message_id"] == "m_deleg00000000001"
    t = json.loads(run("ticket", "list", "--json")[1])[0]
    assert t["title"] == "Use event_time" and t["checklist"][0]["text"] == "Change query"
    assert t["ext"]["relay"]["from"] == PEER


def test_once_allow_does_not_cover_another_message(proj, run, rel):
    from orch import relay

    connect(run, rel)
    rel.inbox.append(msg("m_deleg00000000001", "delegate", {"title": "A", "text": "x"}))
    run("relay", "inbox")
    run("relay", "allow", "m_deleg00000000001", "--once")
    other = msg("m_deleg00000000002", "delegate", {"title": "B", "text": "x"})
    assert relay.allowed(proj, other) is None


def test_permanent_allow_start_key_and_token(proj, run, rel):
    from orch import relay

    connect(run, rel)
    first = msg("m_start00000000001", "start", {"key": "weekly-report", "text": "go"})
    rel.inbox.append(first)
    run("relay", "inbox")
    run("relay", "allow", "m_start00000000001", "--permanent")
    tok = rel.sent[0]["body"]["token"]
    assert rel.sent[0]["body"]["key"] == "weekly-report"
    again = msg("m_start00000000002", "start", {"key": "weekly-report", "text": "go", "allow_token": tok})
    wrong_key = msg("m_start00000000003", "start", {"key": "other", "text": "go", "allow_token": tok})
    forged = msg(
        "m_start00000000004",
        "start",
        {"key": "weekly-report", "text": "go", "allow_token": "ora_" + "x" * 22},
    )
    other_peer = msg(
        "m_start00000000005",
        "start",
        {"key": "weekly-report", "text": "go", "allow_token": tok},
        frm="ws_other00001",
    )
    assert relay.allowed(proj, again) == "permanent"
    assert not any(relay.allowed(proj, m) for m in (wrong_key, forged, other_peer))
    # rule 4: done on an allowed start finds-or-creates the ticket with that key
    rel.inbox.append(again)
    run("relay", "inbox")
    out = run("relay", "done", "m_start00000000002")[1]
    assert "Ticket: t_" in out
    t = json.loads(run("ticket", "list", "--json")[1])[0]
    assert t["ext"]["relay"]["start_key"] == "weekly-report"


def test_received_permanent_allow_is_stored_and_used_when_sending(proj, run, rel):
    connect(run, rel)
    tok = "ora_Q2hhbmdlTWVQbGVhc2UxMg"
    rel.inbox.append(
        msg(
            "m_a11ow00000000001",
            "allow",
            {"mode": "permanent", "kind": "start", "key": "weekly-report", "token": tok},
            reply_to="m_start0first00001",
        )
    )
    assert "permanent allow saved" in run("relay", "inbox")[1]
    run("relay", "start", PEER, "weekly-report", "week 46")
    assert rel.sent[0]["body"] == {"key": "weekly-report", "text": "week 46", "allow_token": tok}
    run("relay", "delegate", PEER, "A title", "--text", "do it", "--check", "one")
    assert "allow_token" not in rel.sent[1]["body"] and rel.sent[1]["body"]["checklist"] == ["one"]


def skill_snapshot(files):
    return {"name": "acme-sql", "version": 2, "files": {k: b64(v) for k, v in files.items()}}


def test_refresh_installs_and_removes_shared_skills(proj, run, rel):
    connect(run, rel)
    rel.snapshot.update(
        version=7,
        skills=[skill_snapshot({"SKILL.md": b"---\nname: acme-sql\n---\n", "ref/a.md": b"x"})],
        mcp={"sql": {"command": "x"}},
        credentials={"DB_URL": "pg://x"},
    )
    rel.snapshot["workspaces"]["workspaces"] = [{"id": PEER, "name": "Reports"}]
    code, out, _ = run("relay", "refresh")
    assert code == 0 and "1 workspace" in out and "acme-sql" in out
    d = proj / ".agents/skills/acme-sql"
    assert (d / "ref/a.md").read_bytes() == b"x" and (d / ".orch-shared").exists()
    assert (proj / ".claude/skills/acme-sql/SKILL.md").exists()  # reached through the skills link
    s = proj / ".orch/secrets"
    assert json.loads((s / "credentials.json").read_text()) == {"DB_URL": "pg://x"}
    assert json.loads((s / "mcp.json").read_text()) == {"mcpServers": {"sql": {"command": "x"}}}
    assert json.loads((s / "shared.json").read_text()) == {"version": 7, "skills": ["acme-sql"]}
    assert not (proj / ".orch/tmp-refresh").exists()
    rel.snapshot.update(version=8, skills=[], credentials={})
    run("relay", "refresh")
    assert not d.exists()
    assert (proj / ".agents/skills/orch/SKILL.md").exists()  # core skills untouched
    assert json.loads((s / "shared.json").read_text())["version"] == 8


def test_refresh_rejects_unsafe_paths_and_keeps_rest(proj, run, rel):
    connect(run, rel)
    for bad in ("/etc/passwd", "../escape.md", "a/../../b", "C:/x", "c:evil", "a\\b", ""):
        rel.snapshot.update(version=3, skills=[skill_snapshot({"SKILL.md": b"ok", bad: b"evil"})])
        code, out, _ = run("relay", "refresh")
        assert code == 0 and "Skipped: skill acme-sql" in out, bad
        assert not (proj / ".agents/skills/acme-sql").exists()
    assert not (proj / "escape.md").exists() and not (proj.parent / "escape.md").exists()


def test_refresh_never_overwrites_own_skills(proj, run, rel):
    connect(run, rel)
    own = proj / ".agents/skills/mine"
    own.mkdir()
    (own / "SKILL.md").write_text("mine")
    rel.snapshot.update(version=4, skills=[skill_snapshot({"SKILL.md": b"x"})])
    rel.snapshot["skills"][0]["name"] = "mine"
    assert run("relay", "refresh")[0] == 2
    assert (own / "SKILL.md").read_text() == "mine"
    rel.snapshot["skills"][0]["name"] = "orch"
    run("relay", "refresh")
    assert "name: orch" in (proj / ".agents/skills/orch/SKILL.md").read_text()


def test_refresh_bad_snapshot_changes_nothing(proj, run, rel):
    connect(run, rel)
    before = (proj / ".orch/secrets/shared.json").read_text()
    rel.snapshot.update(version=9, mcp="nope")
    assert run("relay", "refresh")[0] == 2
    assert (proj / ".orch/secrets/shared.json").read_text() == before


def test_webhooks(proj, run, rel):
    connect(run, rel)
    code, out, _ = run("relay", "webhook", "new", "--once", "--ticket", "t_7k3f9q")
    assert "whk_" in out and "shown only now" in out
    assert rel.webhooks["wh_0000000000"]["ticket"] == "t_7k3f9q"
    assert "wh_0000000000" in run("relay", "webhook", "list")[1]
    assert run("relay", "webhook", "delete", "wh_0000000000")[0] == 0 and not rel.webhooks


def test_refresh_hint_is_shown_not_applied(proj, run, rel):
    connect(run, rel)
    rel.inbox.append(msg("m_refresh000000001", "refresh-hint", {"version": 8}, frm="admin"))
    assert "orch relay refresh" in run("relay", "inbox")[1]


def test_answer_rejected_unless_it_matches_a_question_we_sent(proj, run, new_ticket, rel):
    connect(run, rel)
    tid = new_ticket()
    run("ask", tid, "Q?", "--phone")
    qid = rel.sent[0]["id"]
    bad = [
        msg(
            "m_ans1000000000001",
            "answer",
            {"question_id": "q1", "answer": "X", "answered_by": "human:a"},
            frm="ph_iphone0001",
            ticket=tid,
        ),  # no reply_to
        msg(
            "m_ans2000000000002",
            "answer",
            {"question_id": "q1", "answer": "X", "answered_by": "human:a"},
            frm="ph_iphone0001",
            ticket=tid,
            reply_to="m_unknown00000001",
        ),
        msg(
            "m_ans3000000000003",
            "answer",
            {"question_id": "q1", "answer": "X", "answered_by": "human:a"},
            frm="ws_reports001",
            ticket=tid,
            reply_to=qid,
        ),  # a workspace was not asked
    ]
    rel.inbox += bad
    assert out_count(run("relay", "inbox")[1]) == 3
    assert json.loads(run("ticket", "show", tid, "--json")[1])["questions"][0]["answer"] is None
    rel.inbox.append(
        msg(
            "m_ans4000000000004",
            "answer",
            {"question_id": "q1", "answer": "Y", "answered_by": "agent:evil"},
            frm="ph_iphone0001",
            ticket="t_other0",
            reply_to=qid,
        )
    )
    run("relay", "inbox")
    q = json.loads(run("ticket", "show", tid, "--json")[1])["questions"][0]
    assert (q["answer"], q["answered_by"], q["via"]) == ("Y", "human:ph_iphone0001", "phone")


def out_count(text):
    return text.count("ignored:")


def test_inbox_json_is_message_shaped_with_allowed_bool(proj, run, rel):
    connect(run, rel)
    rel.inbox.append(msg("m_deleg00000000009", "delegate", {"title": "A", "text": "x"}))
    data = json.loads(run("relay", "inbox", "--json")[1])
    assert (
        data[0]["id"] == "m_deleg00000000009"
        and data[0]["allowed"] is False
        and data[0]["body"]["title"] == "A"
    )


def test_ticket_wait_clear(proj, run, new_ticket):
    tid = new_ticket()
    run("ticket", "wait", tid, "--until", "2030-01-01T00:00:00Z")
    code, out, _ = run("ticket", "wait", tid, "--clear", "--json")
    t = json.loads(out)
    assert code == 0 and t["wake_at"] is None and t["status"] == "active"

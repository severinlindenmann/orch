"""Mail and Messages (ORCH-652): what needs the person, read rules for helpers, drafts only (never send), the Mail
app way in, and a fix ticket when a way in stops."""

import json
import os
import re
import stat
import sys
import time
from pathlib import Path

import pytest
from conftest import as_helper, jrun

PY = sys.executable
SRC = Path(__file__).resolve().parents[1] / "src" / "orch_personal"


def iso(hours_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours_ago * 3600))


MAILS = [
    {
        "ref": "m1",
        "from": "Petra Zingg",
        "subject": "Rückfrage zur Offerte",
        "when": iso(1),
        "preview": "Ist die Schnittstelle im Fixpreis enthalten?",
        "unread": True,
        "to_me": True,
    },
    {
        "ref": "m2",
        "from": "Newsletter",
        "subject": "Angebote",
        "when": iso(2),
        "preview": "Jetzt kaufen",
        "unread": True,
        "to_me": False,
    },
    {
        "ref": "m3",
        "from": "Steueramt",
        "subject": "Frist 30 Nov",
        "when": iso(30),
        "preview": "Bitte einreichen.",
        "unread": False,
        "flagged": True,
    },
    {
        "ref": "m4",
        "from": "Marco Keller",
        "subject": "Erledigt",
        "when": iso(3),
        "preview": "Danke.",
        "unread": False,
        "to_me": True,
    },
    {
        "ref": "m5",
        "from": "Alte Mail",
        "subject": "Vor einer Woche",
        "when": iso(24 * 7),
        "preview": "?",
        "unread": True,
        "to_me": True,
    },
]
CHATS = [
    {
        "ref": "c1",
        "chat": "Lea Brunner",
        "from": "Lea Brunner",
        "when": iso(1),
        "preview": "Kannst du die Offerte v2 heute noch anschauen?",
        "unread": True,
        "direct": True,
        "link": "msteams:/l/chat/0/0?users=lea",
    },
    {
        "ref": "c2",
        "chat": "Projekt Helvetia",
        "from": "Anna Meier",
        "when": iso(2),
        "preview": "Preismodell im Wiki",
        "unread": True,
        "direct": False,
    },
]

WAY = r"""
import json, os, sys, pathlib
req = json.load(sys.stdin)
a, v = req["action"], req["values"]
data = pathlib.Path(os.environ["ORCH_PERSONAL_WAY_DATA"])
calls = data / "calls.jsonl"
with calls.open("a") as f:
    f.write(json.dumps(req) + "\n")
items = json.loads(pathlib.Path("items.json").read_text())
if a == "list":
    print(json.dumps({"items": items, "more": False}))
elif a == "find":
    w = v["words"].lower()
    print(json.dumps({"items": [i for i in items if w in json.dumps(i).lower()]}))
elif a == "show":
    i = next(i for i in items if i["ref"] == v["ref"])
    if "chat" in i:
        print(json.dumps({"chat": i["chat"], "messages": [{"who": i["from"], "when": i["when"], "text": i["preview"]}],
                          "link": i.get("link")}))
    else:
        print(json.dumps({"from": i["from"], "to": ["me@example.ch"], "subject": i["subject"], "when": i["when"],
                          "text": "Guten Tag\n\n" + i["preview"]}))
elif a == "draft":
    mode = pathlib.Path("draft-mode.txt").read_text().strip() if pathlib.Path("draft-mode.txt").exists() else "ok"
    if mode == "unclear":
        print(json.dumps({"saved": "maybe"}))
    else:
        print(json.dumps({"saved": True, "draft": "dr-" + v["ref"]}))
"""


def make_source(ws, slug, part, items, name, draft=True, extra_actions=None, files=None):
    d = ws / ".orch" / "addons" / "personal" / "ways" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "way.py").write_text(WAY, encoding="utf-8")
    (d / "items.json").write_text(json.dumps(items), encoding="utf-8")
    for fname, body in (files or {}).items():
        (d / fname).write_text(body, encoding="utf-8")
    acts = ["list", "find", "show"] + (["draft"] if draft else []) + list(extra_actions or [])
    lines = [f'name = "{name}"', f'part = "{part}"', "[actions]"]
    lines += [f"{a} = {json.dumps([PY, 'way.py'])}" for a in acts]
    (d / "way.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d


def calls(ws, slug):
    f = ws / ".orch" / "addons" / "personal" / "ways-data" / slug / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


@pytest.fixture(autouse=True)
def fresh_cache():
    from orch_personal import inbox

    inbox.forget_cache()
    yield
    inbox.forget_cache()


@pytest.fixture
def outlook(cli, ws):
    make_source(ws, "outlook", "mail", MAILS, "Outlook")
    assert jrun(cli, "add", "mail")[0] == 0
    assert jrun(cli, "ways", "on", "outlook")[1]["status"] == "works"
    return ws


@pytest.fixture
def teams(cli, ws):
    make_source(ws, "teams", "messages", CHATS, "Teams", draft=False)
    assert jrun(cli, "add", "messages")[0] == 0
    assert jrun(cli, "ways", "on", "teams")[1]["status"] == "works"
    return ws


# --- no send anywhere ----------------------------------------------------------------------------------------
def test_a_mail_way_in_that_lists_send_cannot_be_turned_on(cli, ws):
    make_source(ws, "outlook", "mail", MAILS, "Outlook", extra_actions=["send"])
    jrun(cli, "add", "mail")
    code, d = jrun(cli, "ways", "on", "outlook")
    assert code == 2 and "only read and make drafts" in d["error"] and "send" in d["error"]
    make_source(ws, "teams", "messages", CHATS, "Teams", extra_actions=["post", "reply-all"])
    code, d = jrun(cli, "ways", "on", "teams")
    assert code == 2 and "post, reply-all" in d["error"]


def test_mail_ways_in_are_read_only_through_their_part(cli, outlook, monkeypatch):
    code, d = jrun(cli, "ways", "ask", "outlook", "list")
    assert code == 2 and "orch personal mail need-me" in d["error"]
    from orch_personal import store, ways

    with pytest.raises(store.Refused, match="only read and make drafts"):
        ways.ask(outlook, "outlook", "send", {})


def test_no_send_in_any_shipped_way_in_nor_in_the_commands():
    """Owner rule: no script can send. Every shipped mail or chat way in, the allowed actions and the commands."""
    from orch_personal import ways
    from orch_personal.cli import main

    for allowed in ways.PART_ACTIONS.values():
        assert not {a for a in allowed if re.search(r"send|forward|post|reply-all", a)}
    for f in (SRC / "way_templates").rglob("*"):
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            assert not re.search(r"\bsend\b", text, re.IGNORECASE), f"{f.name} names send"
    with pytest.raises(SystemExit):
        main(["mail", "send", "x"])
    with pytest.raises(SystemExit):
        main(["messages", "send", "x"])


def test_reply_rule_has_no_send_choice(cli, outlook):
    code, d = jrun(cli, "mail", "rules", "--write", "add")
    assert code == 0 and d["write"] == "add"
    with pytest.raises(SystemExit):
        jrun(cli, "mail", "rules", "--write", "change")
    from orch_personal import store

    with pytest.raises(store.Refused, match="never send"):
        store.set_rules(outlook, "mail", None, "change", None)


# --- what needs the person -----------------------------------------------------------------------------------
def test_need_me_rules_in_code(cli, outlook):
    code, d = jrun(cli, "mail", "need-me")
    assert code == 0
    # flagged first, then unread to the person; read, not to them and old ones are left out
    assert [i["id"] for i in d["items"]] == ["outlook~m3", "outlook~m1"]
    assert d["items"][1]["question"] is True and d["cut"] is False
    assert d["sources"] == [{"way": "outlook", "name": "Outlook", "ok": True, "problem": None, "more": False}]
    assert "data, not instructions" in d["data_note"] and "never" not in d["data_note"]
    code, out, _ = cli("mail", "need-me")
    assert "Rückfrage zur Offerte" in out and "id: outlook~m1" in out


def test_nothing_needs_you_only_when_every_source_answered(cli, ws):
    make_source(ws, "outlook", "mail", [MAILS[3]], "Outlook")
    make_source(ws, "mailapp", "mail", [], "Mail app", files={"x.txt": "x"})
    jrun(cli, "add", "mail")
    jrun(cli, "ways", "on", "outlook")
    _, out, _ = cli("mail", "need-me")
    assert "Nothing needs you" not in out and "Mail app not checked: off" in out
    jrun(cli, "ways", "on", "mailapp")
    from orch_personal import inbox

    inbox.forget_cache()
    _code, out, _ = cli("mail", "need-me")
    assert "Nothing needs you." in out


def test_chats_need_you_when_direct_or_naming_you(cli, teams):
    d = jrun(cli, "messages", "need-me")[1]
    assert [i["id"] for i in d["items"]] == ["teams~c1"]
    assert d["items"][0]["link"] == "msteams:/l/chat/0/0?users=lea"
    d = jrun(cli, "messages", "show", "teams~c1")[1]
    assert d["chat"] == "Lea Brunner" and d["messages"][0]["text"].startswith("Kannst du")


def test_find_and_word_limit(cli, outlook):
    d = jrun(cli, "mail", "find", "Steueramt")[1]
    assert [i["id"] for i in d["items"]] == ["outlook~m3"]
    code, d = jrun(cli, "mail", "find", "x" * 201)
    assert code == 2 and "200" in d["error"]


def test_source_answers_are_cleaned_and_capped(cli, ws):
    bad = [
        {"ref": "../x y", "subject": "bad id"},
        {
            "ref": "ok1",
            "subject": "S" * 900,
            "preview": "a\x00b" * 300,
            "when": iso(1),
            "unread": True,
            "to_me": True,
            "link": "https://evil.example/x",
        },
    ]
    make_source(ws, "outlook", "mail", bad, "Outlook")
    jrun(cli, "add", "mail")
    jrun(cli, "ways", "on", "outlook")
    d = jrun(cli, "mail", "need-me")[1]
    assert [i["id"] for i in d["items"]] == ["outlook~ok1"]
    i = d["items"][0]
    assert len(i["subject"]) == 200 and len(i["preview"]) <= 200 and "\x00" not in i["preview"]
    assert i["link"] is None  # only Outlook and Teams links


# --- helpers follow the person's rules -----------------------------------------------------------------------
def test_helper_reads_only_what_the_rules_allow(cli, outlook, monkeypatch, fake_orch):
    as_helper(monkeypatch)
    code, d = jrun(cli, "mail", "need-me")
    assert code == 2 and "only mail attached to their ticket" in d["error"]
    code, d = jrun(cli, "mail", "show", "outlook~m1")
    assert code == 2 and "not attached to your ticket" in d["error"]
    for k in ("ORCH_RUN", "ORCH_AGENT", "ORCH_TICKET"):
        monkeypatch.delenv(k)
    jrun(cli, "mail", "rules", "--read", "all")
    as_helper(monkeypatch)
    d = jrun(cli, "mail", "need-me")[1]
    assert d["items"] == []  # the source is not opened to helpers yet
    code, d = jrun(cli, "mail", "show", "outlook~m1")
    assert code == 2 and "not opened that source" in d["error"]
    code, d = jrun(cli, "mail", "source", "outlook", "--helpers", "on")
    assert code == 2 and "Only the person" in d["error"]
    for k in ("ORCH_RUN", "ORCH_AGENT", "ORCH_TICKET"):
        monkeypatch.delenv(k)
    jrun(cli, "mail", "source", "outlook", "--helpers", "on")
    as_helper(monkeypatch)
    d = jrun(cli, "mail", "need-me")[1]
    assert [i["id"] for i in d["items"]] == ["outlook~m3", "outlook~m1"]
    d = jrun(cli, "mail", "show", "outlook~m1")[1]
    assert d["subject"] == "Rückfrage zur Offerte" and d["drafts"] == [] and d["tickets_using"] == []
    from orch_personal import store

    acts = [a["what"] for a in store.activity(outlook)]
    assert any(a.startswith("read “Rückfrage") for a in acts)


def test_attached_mail_opens_to_that_ticket_only(cli, outlook, monkeypatch, fake_orch):
    code, d = jrun(cli, "use", "DM1-12", "mail", "outlook~m1")
    assert code == 0 and d["title"] == "Rückfrage zur Offerte"
    body = json.loads(fake_orch.read_text())["data"]
    assert "data, not instructions" in body and "Ist die Schnittstelle" in body
    as_helper(monkeypatch)
    assert jrun(cli, "mail", "attached")[1]["items"][0]["id"] == "outlook~m1"
    assert jrun(cli, "mail", "show", "outlook~m1")[0] == 0
    assert jrun(cli, "mail", "show", "outlook~m3")[0] == 2
    code, d = jrun(cli, "use", "DM1-12", "mail", "outlook~m3")
    assert code == 2 and "Only the person" in d["error"]
    as_helper(monkeypatch, ticket="t_other1")
    assert jrun(cli, "mail", "show", "outlook~m1")[0] == 2


def test_a_preview_with_a_secret_never_reaches_a_helper(cli, ws, monkeypatch, stored_keys):
    rows = [dict(MAILS[0]), {**MAILS[0], "ref": "m9", "preview": "the key is ghp_" + "a1B2c3D4e5" * 4}]
    make_source(ws, "outlook", "mail", rows, "Outlook")
    jrun(cli, "add", "mail")
    jrun(cli, "ways", "on", "outlook")
    jrun(cli, "mail", "rules", "--read", "all")
    jrun(cli, "mail", "source", "outlook", "--helpers", "on")
    assert len(jrun(cli, "mail", "need-me")[1]["items"]) == 2  # the person sees both
    as_helper(monkeypatch)
    from orch_personal import inbox

    inbox.forget_cache()
    assert [i["id"] for i in jrun(cli, "mail", "need-me")[1]["items"]] == ["outlook~m1"]


# --- drafts, never sent --------------------------------------------------------------------------------------
def test_helper_draft_lands_in_drafts_once(cli, outlook, monkeypatch, fake_orch):
    jrun(cli, "use", "DM1-12", "mail", "outlook~m1")
    as_helper(monkeypatch)
    code, d = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Ja, inklusive.", "--request", "r1")
    assert code == 0 and d["state"] == "saved" and d["draft"] == "dr-m1" and "not sent" in d["words"]
    again = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Ja, inklusive.", "--request", "r1")[1]
    assert again["again"] is True and again["id"] == d["id"]
    assert [c["action"] for c in calls(outlook, "outlook")].count("draft") == 1
    assert "title" not in d and "problem" not in d  # the subject stays with the person
    as_helper(monkeypatch, ticket="t_other1")  # another ticket with the same request id gets its own draft
    other = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Anders", "--request", "r1")
    assert other[0] == 2  # and here it may not even read that mail
    from orch_personal import store

    assert any("(not sent)" in a["what"] for a in store.activity(outlook))


def test_unclear_draft_answer_is_never_tried_again(cli, ws, monkeypatch):
    make_source(ws, "outlook", "mail", MAILS, "Outlook", files={"draft-mode.txt": "unclear"})
    jrun(cli, "add", "mail")
    jrun(cli, "ways", "on", "outlook")
    d = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Hallo", "--request", "r2")[1]
    assert d["state"] == "unsure" and "look in Drafts" in d["words"]
    d = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Hallo", "--request", "r2")[1]
    assert d["state"] == "unsure" and d["again"] is True
    assert [c["action"] for c in calls(ws, "outlook")].count("draft") == 1


def test_helper_cannot_draft_when_the_rule_says_never(cli, outlook, monkeypatch, fake_orch):
    jrun(cli, "mail", "rules", "--write", "never")
    jrun(cli, "use", "DM1-12", "mail", "outlook~m1")
    as_helper(monkeypatch)
    code, d = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Hallo")
    assert code == 2 and "does not let helpers draft" in d["error"]


def test_draft_with_a_secret_is_refused(cli, outlook, stored_keys):
    code, _d = jrun(cli, "mail", "draft", "outlook~m1", "--text", "token ghp_" + "a1B2c3D4e5" * 4)
    assert code == 2


def test_teams_reply_is_kept_on_personal_for_the_person(cli, teams, monkeypatch, fake_orch):
    jrun(cli, "use", "DM1-12", "messages", "teams~c1")
    as_helper(monkeypatch)
    d = jrun(cli, "messages", "draft", "teams~c1", "--text", "Ja, heute nach 14:30.")[1]
    assert d["state"] == "local" and "copy and send yourself" in d["words"]
    assert [c["action"] for c in calls(teams, "teams")].count("draft") == 0
    for k in ("ORCH_RUN", "ORCH_AGENT", "ORCH_TICKET"):
        monkeypatch.delenv(k)
    today = jrun(cli, "today")[1]
    tile = next(t for t in today["parts"] if t["part"] == "messages")
    assert tile["status"] == "1 need you" and tile["rows"][0]["ready"] is True
    need = next(n for n in today["needs_you"] if n["part"] == "messages")
    assert need["title"] == "Lea Brunner waits for your answer" and "not sent" in need["text"]
    from orch_personal import api

    page = api.inbox_page(teams, api.Who(helper=False, by="human:me"), "messages")
    assert page["drafts"][0]["text"] == "Ja, heute nach 14:30."
    gone = api.inbox_throw_away(teams, api.Who(helper=False, by="human:me"), "messages", d["id"])
    assert gone["gone"] is True
    with pytest.raises(api.Refused, match="Only the person"):
        api.inbox_throw_away(teams, api.Who(helper=True, by="agent:x"), "messages", d["id"])


# --- tiles ---------------------------------------------------------------------------------------------------
def test_mail_tile_and_stopped_source(cli, ws):
    make_source(ws, "outlook", "mail", MAILS, "Outlook")
    jrun(cli, "add", "mail")
    tile = next(t for t in jrun(cli, "today")[1]["parts"] if t["part"] == "mail")
    assert tile["state"] == "stopped" and tile["status"] == "Not checked" and "off" in tile["line"]
    jrun(cli, "ways", "on", "outlook")
    from orch_personal import inbox

    inbox.forget_cache()
    tile = next(t for t in jrun(cli, "today")[1]["parts"] if t["part"] == "mail")
    assert tile["status"] == "2 need you" and tile["line"] == "2 mails need you"
    assert [r["title"] for r in tile["rows"]] == ["Frist 30 Nov", "Rückfrage zur Offerte"]
    assert tile["uses"] == "nothing yet (no source is open to helpers)"


def test_mail_part_without_source(cli, ws):
    jrun(cli, "add", "mail")
    tile = next(t for t in jrun(cli, "today")[1]["parts"] if t["part"] == "mail")
    assert tile["state"] == "empty" and tile["status"] == "No source yet"


# --- way in stopped: a fix ticket, once ----------------------------------------------------------------------
@pytest.fixture
def orch_tickets(tmp_path, monkeypatch, ws):
    """A fake orch that makes tickets as files (so 'is it open' reads them) and logs every call."""
    log = tmp_path / "orch.log"
    script = tmp_path / "fake-orch-tickets"
    script.write_text(
        "#!" + PY + "\n"
        "import json, sys, pathlib\n"
        "a = sys.argv[1:]\n"
        f"pathlib.Path({str(log)!r}).open('a').write(json.dumps(a) + '\\n')\n"
        f"root = pathlib.Path({str(ws)!r})\n"
        "if a[:2] == ['ticket', 'new']:\n"
        "    n = len(list((root / '.orch' / 'tickets').glob('t_fix*.json')))\n"
        "    tid = 't_fix%03d' % n\n"
        "    (root / '.orch' / 'tickets' / (tid + '.json')).write_text(json.dumps({'id': tid, 'status': 'todo', 'title': a[2]}))\n"
        "    print(json.dumps({'id': tid}))\n"
        "else:\n"
        "    print('{}')\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("ORCH_BIN", str(script))
    return log


def test_a_fix_ticket_after_two_failed_checks_and_only_one(cli, ws, orch_tickets):
    d = make_source(ws, "outlook", "mail", MAILS, "Outlook", files={"check.py": "print('ok')\n"})
    toml = (
        (d / "way.toml")
        .read_text()
        .replace("[actions]", f"selfcheck = {json.dumps([PY, 'check.py'])}\n[actions]")
    )
    (d / "way.toml").write_text(toml)
    jrun(cli, "add", "mail")
    assert jrun(cli, "ways", "on", "outlook")[1]["status"] == "works"
    (d / "check.py").write_text("import sys\nprint('Outlook signed you out.')\nsys.exit(1)\n")
    jrun(cli, "ways", "on", "outlook")  # the person turns the changed way in on again
    assert not orch_tickets.exists() or "ticket" not in orch_tickets.read_text()  # one failure: no ticket yet
    w = jrun(cli, "ways", "check", "outlook")[1]["ways"][0]
    assert w["status"] == "stopped" and w["fix_ticket"] == "t_fix000"
    made = [json.loads(x) for x in orch_tickets.read_text().splitlines()]
    assert made[0][:3] == ["ticket", "new", "Fix the Outlook way in"]
    note = made[0][made[0].index("--note") + 1]
    assert "Outlook signed you out." in note and "orch personal ways check outlook" in note
    jrun(cli, "ways", "check", "outlook")
    jrun(cli, "ways", "check", "outlook")
    news = [x for x in orch_tickets.read_text().splitlines() if '"new"' in x]
    assert len(news) == 1  # never a second ticket while one is open
    jrun(cli, "remove", "mail")  # the Mail tile would ask the source itself
    today = jrun(cli, "today")[1]
    need = next(n for n in today["needs_you"] if n["part"] == "ways")
    assert need["fix_ticket"] == "t_fix000" and need["action"] == "Try again"
    (d / "check.py").write_text("print('ok')\n")
    jrun(cli, "ways", "on", "outlook")
    lines = [json.loads(x) for x in orch_tickets.read_text().splitlines()]
    assert lines[-1][:3] == ["ticket", "summary", "t_fix000"] and "works again" in lines[-1][3]


def test_permission_never_makes_a_fix_ticket(cli, ws, orch_tickets):
    d = make_source(
        ws,
        "outlook",
        "mail",
        MAILS,
        "Outlook",
        files={"check.py": "import sys\nprint('Allow it.')\nsys.exit(3)\n"},
    )
    toml = (
        (d / "way.toml")
        .read_text()
        .replace("[actions]", f"selfcheck = {json.dumps([PY, 'check.py'])}\n[actions]")
    )
    (d / "way.toml").write_text(toml)
    jrun(cli, "add", "mail")
    for _ in range(3):
        jrun(cli, "ways", "on", "outlook")
    assert not orch_tickets.exists()


# --- the Mail app way in -------------------------------------------------------------------------------------
FAKE_OSA = r"""#!{py}
import json, os, sys, pathlib
script = sys.stdin.read()
log = pathlib.Path(os.environ["HOME"]) / "osa.jsonl"
with log.open("a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "script": script}}) + "\n")
mode = (pathlib.Path(os.environ["HOME"]) / "osa-mode").read_text().strip()
import time
NOW = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3600))
US, RS = "\x1f", "\x1e"
if mode == "closed":
    print("NOTRUNNING"); sys.exit(0)
if mode == "denied":
    sys.stderr.write("execution error: Not authorized to send Apple events to Mail. (-1743)\n"); sys.exit(1)
if "on rows(" in script and "whose date received" in script and "set accs to my picked(argv, 3)" in script and "item 2 of argv) as integer) * days" in script:
    print("ACC-1:41" + US + "Petra Zingg <petra@example.ch>" + US + "Rückfrage" + US + NOW + US + "false" + US + "false" + US + "true" + US + "Ist das im Fixpreis?" + RS)
elif "first message of" in script and "reply m" in script:
    print("SAVED")
elif "first message of" in script:
    print("Petra Zingg <petra@example.ch>" + RS + "me@example.ch" + US + RS + RS + "Rückfrage" + RS + NOW + RS + "Guten Tag\nIst das im Fixpreis?")
elif "enabled of a" in script:
    print("iCloud" + RS + "Work" + RS)
else:
    print("2")
"""


@pytest.fixture
def mac_mail(cli, ws, tmp_path, monkeypatch):
    home = Path(os.environ["HOME"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    osa = bin_dir / "osascript"
    osa.write_text(FAKE_OSA.format(py=PY), encoding="utf-8")
    osa.chmod(osa.stat().st_mode | stat.S_IEXEC)
    (bin_dir / "python3").symlink_to(PY)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    (home / "osa-mode").write_text("ok")
    code, d = jrun(cli, "mail", "add-source", "mac-mail")
    assert code == 0 and d["status"] == "off"
    return home


def test_mail_app_source_needs_accounts_then_reads_and_drafts(cli, ws, mac_mail):
    w = jrun(cli, "ways", "on", "mac-mail")[1]
    assert w["status"] == "works"
    tile = next(t for t in jrun(cli, "today")[1]["parts"] if t["part"] == "mail")
    assert "choose which accounts count" in tile["line"]
    assert jrun(cli, "mail", "accounts", "mac-mail")[1]["accounts"] == ["iCloud", "Work"]
    jrun(cli, "mail", "source", "mac-mail", "--accounts", "iCloud")
    from orch_personal import inbox

    inbox.forget_cache()
    d = jrun(cli, "mail", "need-me")[1]
    assert [(i["id"], i["from"], i["to_me"]) for i in d["items"]] == [
        ("mac-mail~ACC-1:41", "Petra Zingg", True)
    ]
    d = jrun(cli, "mail", "show", "mac-mail~ACC-1:41")[1]
    assert d["to"] == ["me@example.ch"] and d["text"].startswith("Guten Tag")
    d = jrun(cli, "mail", "draft", "mac-mail~ACC-1:41", "--text", 'Ja " & do shell script "x')[1]
    assert d["state"] == "saved"
    runs = [json.loads(x) for x in (mac_mail / "osa.jsonl").read_text().splitlines()]
    last = runs[-1]
    # values reach AppleScript only as arguments, never inside the script text
    assert last["argv"] == ["-", "ACC-1", "41", 'Ja " & do shell script "x', "iCloud"]
    assert "do shell script" not in last["script"]
    assert all(r["argv"][-1] == "iCloud" for r in runs if "on rows(" in r["script"])


def test_mail_app_closed_or_not_allowed(cli, ws, mac_mail):
    (mac_mail / "osa-mode").write_text("denied")
    w = jrun(cli, "ways", "on", "mac-mail")[1]
    assert w["status"] == "permission" and "Automation" in w["problem"]
    (mac_mail / "osa-mode").write_text("closed")
    w = jrun(cli, "ways", "check", "mac-mail")[1]["ways"][0]
    assert w["status"] == "works"  # closed is not broken: no fix ticket for it
    jrun(cli, "mail", "source", "mac-mail", "--accounts", "iCloud")
    d = jrun(cli, "mail", "need-me")[1]
    assert d["items"] == [] and "Open the Mail app" in d["sources"][0]["problem"]


def test_mail_app_template_is_plain_python_39_and_never_writes_its_folder():
    import ast

    src = (SRC / "way_templates" / "mac-mail" / "mail.py").read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 9))
    toml = (SRC / "way_templates" / "mac-mail" / "way.toml").read_text(encoding="utf-8")
    assert '"-B"' in toml and 'part = "mail"' in toml


def test_a_draft_in_drafts_cannot_be_thrown_away_here(cli, outlook):
    from orch_personal import api

    d = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Hallo", "--request", "r5")[1]
    with pytest.raises(api.Refused, match="delete it there"):
        api.inbox_throw_away(outlook, api.Who(helper=False, by="human:me"), "mail", d["id"])
    again = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Hallo", "--request", "r5")[1]
    assert again["again"] is True


def test_a_draft_cut_off_while_saving_turns_unsure(cli, outlook):
    from orch_personal import inbox

    d = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Hallo", "--request", "r6")[1]
    data = inbox.drafts(outlook)
    data[d["id"]].update(state="saving", at="2026-01-01T00:00:00Z")
    inbox._save_drafts(outlook, data)
    again = jrun(cli, "mail", "draft", "outlook~m1", "--text", "Hallo", "--request", "r6")[1]
    assert again["state"] == "unsure" and "look in Drafts" in again["words"]
    assert [c["action"] for c in calls(outlook, "outlook")].count("draft") == 1


def test_find_says_which_sources_were_not_searched(cli, outlook, ws):
    make_source(ws, "other", "mail", [], "Other mail")
    d = jrun(cli, "mail", "find", "Steueramt")[1]
    assert {"way": "other", "name": "Other mail", "ok": False, "problem": "off", "more": False} in d[
        "sources"
    ]
    _, out, _ = cli("mail", "find", "nothing-like-this")
    assert "Other mail not checked: off" in out


def test_mail_app_reads_each_account_and_flagged_older_mail():
    src = (SRC / "way_templates" / "mac-mail" / "mail.py").read_text(encoding="utf-8")
    assert "or flagged status is true" in src  # flagged mail older than the window still comes
    assert "set n to 0\n\t\t\tif (name of acc as text) is in accs" in src  # the limit counts per account
    assert "text item delimiters to {character id 30, character id 31}" in src  # mail text cannot fake fields

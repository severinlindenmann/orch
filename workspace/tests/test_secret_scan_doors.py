"""R5.2 / R8.2 (#797): every door a secret could leave through, or be written down through, runs the one
scanner (secretscan). One planted token per kind the scanner knows (built at run time, so the repo holds no
token-shaped literal) plus a stored key value goes through each door. Each door must refuse, send / write /
upload nothing, name the kind, and never echo the value.

A door that does not scan today is an xfail(strict=True) with its issue, so the gap stays visible and the
test turns red the day it is fixed (then the marker is removed). A structural test lists the outbound helpers
and checks with the AST that each reaches the scanner, so a new door that skips it fails here."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from test_publish_client import connect as pub_connect
from test_publish_client import make_app
from test_relay_client import PEER
from test_relay_client import connect as rel_connect

from orch import keystore, secretscan
from orch.errors import Refused

# one runtime-built sample per kind; the stored key is added to the keystore by the `stored` fixture
SAMPLES = {
    "private-key": "-----BEGIN PRIVATE KEY-----\n"
    + "MIIBVgIBADANBgkqhkiG9w0B"
    + "\n-----END PRIVATE KEY-----",
    "orch-token": "orn_" + "A1b2C3d4" * 3,
    "api-key": "sk_live_" + "A1b2C3d4" * 3,
    "github-token": "ghp_" + "A1b2C3d4E5" * 3,
    "gitlab-or-slack-token": "glpat-" + "A1b2C3d4" * 3,
    "aws-key": "AKIA" + "ABCDEFGH12345678",
    "jwt": "eyJ" + "a1B2c3D4e5F6" + "." + "g7H8i9J0k1L2" + "." + "m3N4o5P6",
    "bearer-token": "Bearer " + "q1W2e3R4t5Y6u7I8",
    "api-token": "AIza" + "B1c2D3e4F5" * 3 + "G6h7I",
    "password-in-url": "https://bob:" + "pw" + "Zx81Qk@host.example/x",
    "webhook-token": "https://hooks.slack.com/services/T" + "0ABCDEF" + "/B0ABCDEF/" + "xK3" * 8,
    "secret-value": "password=" + "R3alSecretValue99",
}
STORED = "stored-" + "Zq7Lm2Xp9Wk4Vb8N"  # a value of the workspace's own keystore
KIND_IDS = [*SAMPLES, "stored-key"]
# how each kind reads in a refusal (secretscan.WORDS)
WORD = {**{k: secretscan.WORDS[k] for k in SAMPLES}, "stored-key": secretscan.WORDS["stored-key"]}


@pytest.fixture(params=KIND_IDS)
def planted(request, proj):
    """(kind, value that must never appear anywhere). A stored key gets its value into the keystore first."""
    kind = request.param
    if kind == "stored-key":
        keystore.add(proj, "planted-token", "token", STORED)
        return kind, STORED
    return kind, SAMPLES[kind]


def _secret_part(kind: str, value: str) -> str:
    """The part of a sample that must not be echoed: the whole value, or its body after the prefix."""
    return value.split("=", 1)[1] if kind == "secret-value" else value


def _clean(kind, value, *texts, named=True):
    """named=False: the text was re-encoded (UTF-16), the scanner reads it in several ways and may name
    another kind first; it is still refused and the value is still never echoed."""
    blob = "\n".join(str(t) for t in texts)
    assert not named or WORD[kind] in blob, f"the refusal names the kind ({WORD[kind]!r}): {blob!r}"
    body = _secret_part(kind, value)
    assert body not in blob and body[6:] not in blob, "the value is never echoed"


def test_the_samples_are_real_kinds_of_the_scanner(proj):
    """The planted samples cover every kind in secretscan.KINDS (new pattern => new sample here)."""
    assert set(SAMPLES) == set(secretscan.KINDS) | {"secret-value"}
    for kind, text in SAMPLES.items():
        assert any(f["kind"] == kind for f in secretscan.find(text)), kind
    keystore.add(proj, "planted-token", "token", STORED)
    assert [f["kind"] for f in secretscan.find(f"x {STORED}", proj)] == ["stored-key"]


PROFILE_ISSUE = "#944"
NOTE_ISSUE = "#943"


# ---- relay doors -----------------------------------------------------------------------------------------


@pytest.fixture
def on(proj, run, rel):
    rel_connect(run, rel)
    return rel


def _nothing_left(proj, rel):
    assert not rel.sent and not rel.blobs
    ob = proj / ".orch" / "outbox"
    assert not ob.exists() or not list(ob.iterdir())


def test_relay_cli_send_text(proj, run, on, planted):
    kind, value = planted
    code, out, err = run("relay", "send", PEER, f"deploy with {value} please")
    assert code != 0
    _clean(kind, value, out, err)
    _nothing_left(proj, on)


def test_relay_cli_send_file_text_and_binary(proj, run, on, planted):
    kind, value = planted
    (proj / "notes.txt").write_text(f"line one\nnote: {value}\n", encoding="utf-8")
    (proj / "x.bin").write_bytes(b"\x00\x01\x02" + value.encode() + b"\x00")
    for name in ("notes.txt", "x.bin"):
        code, out, err = run("relay", "send", PEER, "--file", name)
        assert code != 0, name
        _clean(kind, value, out, err)
    _nothing_left(proj, on)


def test_relay_cli_delegate_and_start(proj, run, on, planted):
    kind, value = planted
    for args in (
        ("delegate", PEER, f"use {value}", "--text", "x"),
        ("delegate", PEER, "T", "--text", f"use {value}"),
        ("delegate", PEER, "T", "--text", "x", "--check", f"item {value}"),
        ("start", PEER, "review", f"use {value}"),
    ):
        code, out, err = run("relay", *args)
        assert code != 0, args
        _clean(kind, value, out, err)
    _nothing_left(proj, on)


# every wire type that carries user text: text, question, answer, group message, file name, delegate and
# start summaries, the review card
WIRE_BODIES = {
    "text": lambda v: ("text", {"text": f"hello {v}"}),
    "question": lambda v: ("question", {"question_id": "q1", "text": f"which? {v}", "options": ["a"]}),
    "answer": lambda v: ("answer", {"question_id": "q1", "answer": f"it is {v}", "answered_by": "agent:x"}),
    "group-text": lambda v: (
        "text",
        {"text": "hi", "group": {"id": "g1"}, "by": "ws", "update": {"kind": v}},
    ),
    "file-name": lambda v: ("file", {"blob_id": "b_1", "name": f"{v}.txt", "size": 3, "sha256": "0" * 64}),
    "delegate-summary": lambda v: (
        "delegate",
        {"title": "T", "text": "x", "checklist": ["a"], "summary": f"done with {v}"},
    ),
    "start": lambda v: ("start", {"key": "review", "text": f"go {v}"}),
    "review-card": lambda v: (
        "question",
        {"question_id": "q2", "text": "ok?", "options": ["a"], "card": {"t": v}},
    ),
}


@pytest.mark.parametrize("door", WIRE_BODIES)
def test_relay_message_every_wire_type(proj, on, planted, door):
    from orch import relay

    kind, value = planted
    type_, body = WIRE_BODIES[door](value)
    with pytest.raises(Refused) as e:
        relay._message(proj, PEER, type_, body)
    _clean(kind, value, e.value)
    _nothing_left(proj, on)


def test_relay_send_functions(proj, on, planted):
    from orch import relay

    kind, value = planted
    (proj / "f.txt").write_text(f"a {value}\n", encoding="utf-8")
    calls = (
        lambda: relay.send_text(proj, PEER, f"hi {value}"),
        lambda: relay.send_file(proj, PEER, proj / "f.txt", None),
        lambda: relay.send_file(proj, PEER, proj / "f.txt", f"see {value}"),
        lambda: relay.send_start(proj, PEER, "review", f"go {value}", None),
        lambda: relay.send_delegate(proj, PEER, "T", f"use {value}", ["a"], None),
    )
    for call in calls:
        with pytest.raises(Refused) as e:
            call()
        _clean(kind, value, e.value)
    _nothing_left(proj, on)


def test_relay_api_is_the_choke_point_for_dicts_and_bytes(proj, on, planted):
    from orch import relay

    kind, value = planted
    for body in ({"text": value}, [{"a": value}], {value: "key"}, value.encode(), value.encode("utf-16")):
        with pytest.raises(Refused) as e:
            relay._api(proj, "POST", "/v1/anything", body)
        _clean(kind, value, e.value, named=not (isinstance(body, bytes) and body[:2] == b"\xff\xfe"))
    _nothing_left(proj, on)


@pytest.mark.xfail(strict=True, reason=PROFILE_ISSUE)
def test_relay_profile_description_is_scanned(proj, run, on, planted):
    kind, value = planted
    n = len(on.calls)
    code, out, err = run("relay", "profile", "--description", f"we use {value}")
    assert code != 0
    _clean(kind, value, out, err)
    assert len(on.calls) == n


# ---- publish doors ---------------------------------------------------------------------------------------


def _publish_clean(pub, n, kind, value, code, out, err, named=True):
    assert code != 0
    _clean(kind, value, out, err, named=named)
    assert not pub.files and not pub.apps and len(pub.calls) == n


def test_publish_file_text_utf16_and_replace(proj, run, pub, planted):
    kind, value = planted
    pub_connect(run, pub)
    (proj / "ok.txt").write_text("fine")
    res = json.loads(run("publish", "file", "ok.txt", "--json")[1])
    pub.files.clear()
    n = len(pub.calls)
    (proj / "s.env").write_text(f"A=1\n{value}\nB=2\n")
    (proj / "u16.txt").write_bytes(b"\xff\xfe" + f"A=1\n{value}\nB=2\n".encode("utf-16-le"))
    for args in (
        ("file", "s.env"),
        ("file", "u16.txt"),
        ("file", "s.env", "--replace", res["id"]),
    ):
        code, out, err = run("publish", *args)
        _publish_clean(pub, n, kind, value, code, out, err, named=args[1] != "u16.txt")


def test_publish_folder_bundle(proj, run, pub, planted):
    kind, value = planted
    pub_connect(run, pub)
    site = proj / "site"
    (site / "js").mkdir(parents=True)
    (site / "index.html").write_text("<h1>hi</h1>")
    (site / "js" / "app.js").write_text(f"x = 1;\n{value}\n")
    n = len(pub.calls)
    code, out, err = run("publish", "file", "site")
    _publish_clean(pub, n, kind, value, code, out, err)
    assert "js/app.js" in err


def test_publish_app_bundle(proj, run, pub, planted):
    kind, value = planted
    pub_connect(run, pub)
    app = make_app(proj)
    (app / "config.py").write_text(f"X = 1\n{value}\n")
    n = len(pub.calls)
    code, out, err = run("publish", "app", str(app))
    _publish_clean(pub, n, kind, value, code, out, err)
    assert "config.py" in err


@pytest.mark.xfail(strict=True, reason=NOTE_ISSUE)
def test_publish_note_is_scanned(proj, run, pub, planted):
    """The note travels inside the encrypted file header, but it is still text the person did not review."""
    kind, value = planted
    pub_connect(run, pub)
    (proj / "ok.txt").write_text("fine")
    n = len(pub.calls)
    code, out, err = run("publish", "file", "ok.txt", "--note", f"the key is {value}"[:270])
    _publish_clean(pub, n, kind, value, code, out, err)


@pytest.mark.xfail(strict=True, reason=PROFILE_ISSUE)
def test_publish_profile_description_is_scanned(proj, run, pub, planted):
    kind, value = planted
    pub_connect(run, pub)
    n = len(pub.calls)
    code, out, err = run("publish", "profile", "--description", f"we use {value}"[:270])
    _publish_clean(pub, n, kind, value, code, out, err)


# ---- evidence doors (what a ticket keeps and what a phone or the relay may later show) --------------------


@pytest.fixture
def step(proj, run, new_ticket):
    tid = new_ticket("Q3 invoice export")
    run("check", "add", tid, "Export CSV")
    return tid


def _ticket_bytes(proj, tid):
    base = proj / ".orch" / "tickets"
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def _evidence_refused(proj, run, tid, planted, args):
    kind, value = planted
    before = _ticket_bytes(proj, tid)
    code, out, err = run(*args)
    assert code != 0, "the evidence write must be refused"
    _clean(kind, value, out, err)
    assert _ticket_bytes(proj, tid) == before, "nothing is written"


EVIDENCE_DOORS = {
    "note": lambda v, f: ("--note", f"saw {v} in the log"),
    "command": lambda v, f: ("--command", f"curl -H 'X: {v}' https://x.test"),
    "url": lambda v, f: ("--url", f"https://x.test/?a={v}"),
    "pr": lambda v, f: ("--pr", f"PR {v}"),
    "commit": lambda v, f: ("--commit", f"fix {v}"),
    "file": lambda v, f: ("--file", f),
    "summary": lambda v, f: ("--note", "ok", "--summary", f"it was {v}"),
}


@pytest.mark.parametrize("door", EVIDENCE_DOORS)
def test_evidence_check_done(proj, run, step, planted, door):
    kind, value = planted
    (proj / "out.txt").write_text(f"result\napi={value}\n", encoding="utf-8")
    extra = EVIDENCE_DOORS[door](value, "out.txt")
    _evidence_refused(proj, run, step, planted, ("check", "done", step, "c1", *extra))


def test_evidence_check_record_command_and_output(proj, run, step, planted):
    kind, value = planted
    (proj / "out.txt").write_text(f"ran\n{value}\n", encoding="utf-8")
    _evidence_refused(
        proj, run, step, planted, ("check", "record", step, "c1", "--cmd", f"x {value}", "--exit", "0")
    )
    _evidence_refused(
        proj, run, step, planted, ("check", "record", step, "c1", "--cmd", "pytest", "--output", "out.txt")
    )


def test_evidence_clean_file_with_secret_note_copies_nothing(proj, run, step):
    """The proof is scanned before a --file is copied: a secret in the note leaves no stray copy behind."""
    value = SAMPLES["github-token"]
    (proj / "clean.txt").write_text("all good\n", encoding="utf-8")
    _evidence_refused(
        proj,
        run,
        step,
        ("github-token", value),
        ("check", "done", step, "c1", "--file", "clean.txt", "--note", value),
    )
    code, out, err = run(
        "check", "done", step, "c1", "--file", "clean.txt", "--note", "ok", "--summary", "fine"
    )
    assert code == 0, err  # a clean proof still goes through


# ---- structural guard: a new door that skips the scanner fails here --------------------------------------

SRC = Path(__file__).resolve().parents[1] / "src" / "orch"
SCANS = {"find", "refuse_if_secret", "refuse_if_secret_in", "scan_outgoing", "scan_blob", "scan_files"}
# helper -> the scanner call it must make (directly)
OUTBOUND = {
    ("relay.py", "_api"): {"scan_blob", "scan_outgoing"},  # every relay HTTP body, bytes and JSON
    ("relay.py", "scan_blob"): {"refuse_if_secret"},
    ("relay.py", "resend_outbox"): {"scan_outgoing"},  # an old outbox entry is scanned again before it posts
    ("publish.py", "scan_files"): {"find"},  # every publish upload runs this on the plain bytes
    ("publish.py", "bundle"): {"scan_files"},
    ("publish.py", "pack"): {"scan_files"},
    ("publish.py", "share_file"): {"scan_files", "bundle"},
    ("secretscan.py", "refuse_if_secret"): {"find"},
    ("secretscan.py", "refuse_if_secret_in"): {"find"},
}
# functions that put bytes on the wire without scanning themselves, because their caller did (the scanned
# bytes are what they send). A new HTTP call site must be added here on purpose, with its scanner named.
WIRE_CALLERS = {
    ("relay.py", "_api"): "scans itself",
    ("publish.py", "_api"): "its bodies are scanned by share_file (scan_files) and deploy (pack)",
    ("publish.py", "profile"): "net.profile",  # see PROFILE_ISSUE: not scanned yet
    ("relay.py", "_post_message"): "posts the outbox bytes after _message / resend_outbox scanned them",
}


def _funcs(path: str) -> dict[str, ast.AST]:
    tree = ast.parse((SRC / path).read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _called(fn: ast.AST) -> set[str]:
    names = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return names


@pytest.mark.parametrize(("module", "name"), OUTBOUND)
def test_every_outbound_helper_reaches_the_scanner(module, name):
    fns = _funcs(module)
    assert name in fns, f"{module}:{name} was renamed or removed: update OUTBOUND"
    calls = _called(fns[name])
    assert calls & OUTBOUND[(module, name)], (
        f"{module}:{name} no longer calls {sorted(OUTBOUND[(module, name)])}: "
        "an outbound path must run secretscan (R5.2)"
    )


def test_publish_upload_callers_scan_before_sending():
    """deploy sends pack(...) and share_file sends the bundle/bytes it scanned: both call a scanning helper
    before _api, and every other _api call in publish.py carries no user content."""
    fns = _funcs("publish.py")
    assert _called(fns["deploy"]) & {"pack"}
    assert _called(fns["share_file"]) & {"scan_files"}


def test_no_new_http_door_in_relay_or_publish():
    """Every function in relay.py / publish.py that calls net.call_json (or urlopen) directly is on the
    list above. A new one fails here until someone decides how it scans."""
    for module in ("relay.py", "publish.py"):
        for name, fn in _funcs(module).items():
            if _called(fn) & {"call_json", "urlopen"} and (module, name) not in WIRE_CALLERS:
                pytest.fail(f"{module}:{name} sends over the network: scan it with secretscan and list it")


def test_ticket_fixture_test_is_collected():
    """#834: the old-ticket fixture test lives where CI's workspace job collects it."""
    p = Path(__file__).with_name("test_ticket_fixtures.py")
    assert p.is_file()
    assert "def test_" in p.read_text(encoding="utf-8")

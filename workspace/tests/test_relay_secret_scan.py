"""R5.2: every path that sends content over the relay scans it first with the one scanner (secretscan).
A hit refuses the send with one plain sentence (kind + field, never the value), and nothing is posted or
kept in the outbox."""

import json

import pytest
from test_relay_client import PEER, connect

from orch.errors import Refused

TOKEN = "ghp_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0"  # built at run time: no token literal in the repo
PEM = "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----"


def _clean(proj, rel, code, out, err):
    blob = out + err
    assert code != 0, "the send must be refused"
    assert TOKEN not in blob and "MIIBVg" not in blob, "the value is never echoed"
    assert "nothing was sent" in blob and "Remove it" in blob  # R8.4: the next step
    assert not rel.sent and not rel.blobs
    ob = proj / ".orch" / "outbox"
    assert not ob.exists() or not list(ob.iterdir())


@pytest.fixture
def on(proj, run, rel):
    connect(run, rel)
    return rel


def test_send_text_refused(proj, run, on):
    code, out, err = run("relay", "send", PEER, f"deploy with {TOKEN} please")
    _clean(proj, on, code, out, err)
    assert "GitHub token" in err and "text" in err


def test_send_text_to_ticket_and_phone_refused(proj, run, on):
    from orch import relay

    with pytest.raises(Exception) as e:
        relay.send_text(proj, "phones", f"my key {TOKEN}", None, "note")
    assert TOKEN not in str(e.value) and "nothing was sent" in str(e.value)
    assert not on.sent


def test_send_file_refused(proj, run, on):
    (proj / "notes.txt").write_text(f"line one\napi note: {TOKEN}\n", encoding="utf-8")
    code, out, err = run("relay", "send", PEER, "--file", "notes.txt")
    _clean(proj, on, code, out, err)
    assert "The file has" in err


def test_send_file_binary_with_token_refused(proj, run, on):
    (proj / "x.bin").write_bytes(b"\x00\x01\x02" + TOKEN.encode() + b"\x00")
    code, out, err = run("relay", "send", PEER, "--file", "x.bin")
    _clean(proj, on, code, out, err)


def test_send_file_clean_still_goes(proj, run, on):
    (proj / "rows.csv").write_bytes(b"a,b\n1,2\n")
    assert run("relay", "send", PEER, "--file", "rows.csv")[0] == 0 and on.sent


def test_send_file_text_note_refused(proj, run, on):
    (proj / "rows.csv").write_bytes(b"a,b\n1,2\n")
    code, out, err = run("relay", "send", PEER, f"token {TOKEN}", "--file", "rows.csv")
    assert code != 0 and TOKEN not in out + err and not on.sent


def test_delegate_refused_in_title_text_and_checklist(proj, run, on):
    for args in (
        (f"use {TOKEN}", "--text", "x"),
        ("T", "--text", f"use {TOKEN}"),
        ("T", "--text", "x", "--check", f"item {TOKEN}"),
    ):
        code, out, err = run("relay", "delegate", PEER, *args)
        _clean(proj, on, code, out, err)


def test_start_refused(proj, run, on):
    code, out, err = run("relay", "start", PEER, "weekly-report", f"go {TOKEN}")
    _clean(proj, on, code, out, err)


def test_private_key_block_refused(proj, run, on):
    code, out, err = run("relay", "send", PEER, PEM)
    _clean(proj, on, code, out, err)
    assert "private key" in err


def test_nested_fields_and_view_refused(proj, on):
    from orch import relay

    body = {"text": "hi", "ticket_view": {"blocks": [{"items": [{"value": f"x {TOKEN}"}]}]}}
    with pytest.raises(Exception) as e:
        relay._message(proj, PEER, "text", body)
    assert "value" in str(e.value) and TOKEN not in str(e.value)
    assert not on.sent


def test_question_and_group_post_use_the_same_check(proj, on):
    from orch import relay

    for type_, body in (
        ("question", {"question_id": "q1", "text": f"which? {TOKEN}", "options": ["a"]}),
        ("text", {"text": "hello", "group": {"id": "g1"}, "by": "ws", "update": {"kind": f"{TOKEN}"}}),
        ("file", {"blob_id": "b_1", "name": f"{TOKEN}.txt", "size": 3, "sha256": "0" * 64}),
    ):
        with pytest.raises(Exception) as e:
            relay._message(proj, PEER, type_, body)
        assert TOKEN not in str(e.value)
    assert not on.sent


def test_blob_upload_check_covers_every_blob_caller(proj, on):
    from orch import relay

    with pytest.raises(Exception) as e:
        relay._api(proj, "POST", "/v1/blobs", f"hello\ntoken={TOKEN}\n".encode(), 5)
    assert "The file has" in str(e.value) and TOKEN not in str(e.value)
    assert not on.blobs
    assert relay._api(proj, "POST", "/v1/blobs", b"plain bytes", 5)[1]["size"] == 11


def test_protocol_fields_are_not_content(proj, on):
    from orch import relay

    relay.scan_outgoing(
        proj,
        {"allow_token": "orn_" + "A" * 24, "blob_id": "b_" + "0" * 16, "sha256": "f" * 64, "text": "hello"},
    )
    json.dumps({})  # (no secret: no refusal)


def test_blob_check_big_file_utf16_and_odd_paths(proj, on):
    from orch import relay

    big = b"x\n" * 700_000 + f"token={TOKEN}\n".encode()  # secret past the first MB
    with pytest.raises(Refused) as e:
        relay._api(proj, "POST", "/v1/blobs", big, 5)
    assert TOKEN not in str(e.value)
    with pytest.raises(Refused):
        relay._api(proj, "post", "/v1/blobs/?x=1", f"token {TOKEN}".encode("utf-16"), 5)
    with pytest.raises(Refused):
        relay._api(proj, "POST", "/v1/blobs", memoryview(b"x"), 5)
    assert not on.blobs


def test_nested_token_field_is_scanned_top_level_one_is_not(proj, on):
    from orch import relay

    relay.scan_outgoing(proj, {"text": "hi", "token": TOKEN})  # the protocol's own field
    with pytest.raises(Refused):
        relay.scan_outgoing(proj, {"text": "hi", "meta": {"token": TOKEN}})


def test_hidden_value_is_exempt_but_a_real_one_on_the_same_line_is_not(proj, on):
    from orch import relay

    relay.scan_outgoing(proj, {"text": "password=[hidden] on the box"})  # a scrubbed pair: fine
    relay.scan_outgoing(proj, {"text": "https://ci.example.ch/run/7?token=%5Bhidden%5D"})
    for text in (
        "note=[hidden] api_key=" + "R3alSecretValue99",
        "password=[hidden], password=hunter2hunter2",
        "api_key=[hidden]R3alSecretValue99",
        "api_key=R3alSecretValue99=[hidden]",
        "api_key: R3alSecretValue99 : [hidden]",
    ):
        with pytest.raises(Refused) as e:
            relay.scan_outgoing(proj, {"text": text})
        assert "R3alSecretValue99" not in str(e.value) and "hunter2" not in str(e.value)

"""ORCH-696: voice into the message box. POST /api/voice/words takes the recording of the page's microphone and
answers its words through the connected relay (orch.relay.transcribe); the person's session only, the relay on only,
and every refusal one plain sentence. Nothing is sent to a helper from here."""

import functools
import json
import threading
import urllib.error
import urllib.request

import pytest

from orch_dashboard import voice
from orch_dashboard.server import make_server

WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 64


class Person:
    """The person's dashboard session (cookie + page secret), as in test_term.py."""

    revoked = False

    def __init__(self, ok):
        self.ok = ok

    def can_act(self, headers, port):
        return self.ok and headers.get("X-Orch-Page") == "secret"

    def authed(self, headers, port):
        return self.can_act(headers, port)

    def cookie_ok(self, headers, port):
        return self.ok


class Refused(Exception):
    def __init__(self, status):
        super().__init__("no")
        self.status = status


@pytest.fixture
def heard(monkeypatch):
    """The relay stand-in: on, and what it 'hears' (a string, or a status it refuses with)."""
    from orch import errors, relay

    said = {"answer": "Please keep the old file name.", "calls": []}

    def transcribe(root, audio, mime, timeout=60):
        said["calls"].append((audio, mime))
        a = said["answer"]
        if a is None or isinstance(a, int):  # None: the relay did not answer
            e = errors.Refused("relay said no")
            e.status = a
            raise e
        return {"text": a, "language": "en", "duration": 2.0}

    monkeypatch.setattr(relay, "transcribe", transcribe)
    monkeypatch.setattr(voice, "relay_on", lambda root, orch_bin: said.get("on", True))
    return said


def serve(tmp_path, session):
    srv = make_server(tmp_path, 0, orch_bin=None)
    srv.RequestHandlerClass = functools.partial(srv.RequestHandlerClass, session=session)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def post(base, body=WEBM, kind="audio/webm;codecs=opus", secret="secret", origin=True):
    h = {"Content-Type": kind, "X-Orch-Page": secret, **({"Origin": base} if origin else {})}
    req = urllib.request.Request(base + "/api/voice/words", data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_words_come_back_for_the_person_only(tmp_path, heard):
    srv, base = serve(tmp_path, Person(True))
    try:
        code, body = post(base)
        assert code == 200 and json.loads(body) == {"text": "Please keep the old file name."}
        assert heard["calls"] == [(WEBM, "audio/webm")]
        assert post(base, secret="wrong")[0] == 403  # a script without the page secret
        assert post(base, origin=False)[0] == 403  # not a page
        assert len(heard["calls"]) == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_watch_only_server_never_listens(tmp_path, heard):
    srv, base = serve(tmp_path, Person(False))
    try:
        code, _ = post(base)
        assert code == 403 and heard["calls"] == []
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize(
    ("answer", "code", "words"),
    [
        ("", 422, voice.EMPTY),
        ("   ", 422, voice.EMPTY),
        (503, 503, voice.NO_KEY),
        (429, 429, voice.BUSY),
        (413, 413, voice.LONG),
        (422, 422, voice.EMPTY),
        (502, 502, voice.FAILED),
        (None, 502, voice.FAILED),
    ],
)
def test_every_refusal_is_one_plain_sentence(tmp_path, heard, answer, code, words):
    heard["answer"] = answer
    got = voice.words(tmp_path, None, WEBM, "audio/webm")
    assert got[0] == code and got[1].decode() == words and got[2].startswith("text/plain")
    assert words.count(".") == 1 and words.endswith(".")


def test_relay_off_listens_to_nothing(tmp_path, heard):
    heard["on"] = False
    code, body, _ = voice.words(tmp_path, None, WEBM, "audio/webm")
    assert code == 409 and body.decode() == voice.OFF and heard["calls"] == []


def test_only_recordings_are_taken(tmp_path, heard):
    code, _, _ = voice.words(tmp_path, None, b"{}", "application/json")
    assert code == 415 and heard["calls"] == []


def test_relay_on_needs_the_connection_and_the_addon(tmp_path, monkeypatch):
    assert voice.relay_on(tmp_path, "orch") is False  # no saved connection
    (tmp_path / ".orch" / "secrets").mkdir(parents=True)
    (tmp_path / ".orch" / "secrets" / "relay.json").write_text(
        json.dumps({"url": "https://relay.example", "workspace": "ws_x", "token": "t"})
    )
    rows = [{"name": "relay", "active": False}]
    monkeypatch.setattr(voice, "run_orch", lambda orch_bin, argv, root: rows)
    assert voice.relay_on(tmp_path, "orch") is False  # connected but the add-on is off
    rows[0]["active"] = True
    assert voice.relay_on(tmp_path, "orch") is True


def test_the_real_path_through_the_relay_stand_in(tmp_path, monkeypatch):
    """The page's request, the real server, orch.relay.transcribe and the local relay stand-in (workspace/tests/fakes.py,
    the one the click-throughs use): the stand-in gets the sound with its type, the page gets the words."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "workspace" / "tests"))
    import fakes

    rel = fakes.make_relay()
    try:
        sec = tmp_path / ".orch" / "secrets"
        sec.mkdir(parents=True)
        (sec / "relay.json").write_text(
            json.dumps({"url": rel.url, "workspace": fakes.WS, "token": rel.token})
        )
        monkeypatch.setattr(
            voice, "run_orch", lambda orch_bin, argv, root: [{"name": "relay", "active": True}]
        )
        srv = make_server(tmp_path, 0, orch_bin="orch")
        srv.RequestHandlerClass = functools.partial(srv.RequestHandlerClass, session=Person(True))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            code, body = post(base)
            assert code == 200 and json.loads(body) == {"text": "Please keep the old file name."}
            method, path, hdrs, sent = rel.calls[-1]
            assert (method, path, sent, hdrs["Content-Type"]) == (
                "POST",
                "/v1/transcribe",
                WEBM,
                "audio/webm",
            )
            rel.transcribe_off = True
            assert post(base) == (503, voice.NO_KEY)
            rel.transcribe_off, rel.transcript = False, ""
            assert post(base) == (422, voice.EMPTY)
        finally:
            srv.shutdown()
            srv.server_close()
    finally:
        rel.stop()

"""relay.transcribe (ORCH-696): a short recording from the dashboard's message box becomes words through
the relay's POST /v1/transcribe (workspace auth). The relay holds the speech key; orch only sends audio and
reads text."""

import pytest
from fakes import WS

from orch import relay
from orch.errors import Refused

WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 64  # the start of a WebM file; the stand-in does not decode it


def connect(run, srv):
    assert run("relay", "connect", srv.url, "--workspace", WS, "--token", srv.token)[0] == 0


def test_words_come_back_with_the_recording_type(proj, run, rel):
    connect(run, rel)
    out = relay.transcribe(proj, WEBM, "audio/webm;codecs=opus")
    assert out == {"text": "Please keep the old file name.", "language": "en", "duration": 2.0}
    method, path, hdrs, body = rel.calls[-1]
    assert (method, path, body) == ("POST", "/v1/transcribe", WEBM)
    assert hdrs["Content-Type"] == "audio/webm" and hdrs["X-Orch-Workspace"] == WS


def test_safari_mp4_is_sent_as_m4a(proj, run, rel):
    connect(run, rel)
    relay.transcribe(proj, WEBM, "audio/mp4")
    assert rel.calls[-1][2]["Content-Type"] == "audio/m4a"


def test_nothing_heard_is_empty_text(proj, run, rel):
    connect(run, rel)
    rel.transcript = "   "
    assert relay.transcribe(proj, WEBM, "audio/webm")["text"] == ""


def test_words_are_cleaned(proj, run, rel):
    connect(run, rel)
    rel.transcript = "Hello​ there <!-- hidden --> friend"
    assert relay.transcribe(proj, WEBM, "audio/webm")["text"] == "Hello there  friend"


def test_relay_without_speech_key_says_so(proj, run, rel):
    connect(run, rel)
    rel.transcribe_off = True
    with pytest.raises(Refused) as e:
        relay.transcribe(proj, WEBM, "audio/webm")
    assert e.value.status == 503


@pytest.mark.parametrize(
    ("audio", "mime", "status"),
    [
        (WEBM, "video/mp4", 422),
        (b"", "audio/webm", 422),
        (b"x" * (relay.TRANSCRIBE_MAX + 1), "audio/webm", 413),
    ],
)
def test_refused_before_anything_is_sent(proj, run, rel, audio, mime, status):
    connect(run, rel)
    before = len(rel.calls)
    with pytest.raises(Refused) as e:
        relay.transcribe(proj, audio, mime)
    assert e.value.status == status and len(rel.calls) == before


def test_not_connected_is_refused(proj):
    with pytest.raises(Refused, match="not connected to a relay"):
        relay.transcribe(proj, WEBM, "audio/webm")


def test_a_recording_holding_a_secret_is_refused_and_not_sent(proj, run, rel):
    """R5.2: the recording is scanned before it leaves; a secret in it stops the upload and is not echoed."""
    connect(run, rel)
    token = "ghp_" + "A1b2C3d4E5" * 3  # built at run time, so the repo holds no token-shaped literal
    before = len(rel.calls)
    with pytest.raises(Refused) as e:
        relay.transcribe(proj, WEBM + token.encode(), "audio/webm")
    assert len(rel.calls) == before and token not in str(e.value)

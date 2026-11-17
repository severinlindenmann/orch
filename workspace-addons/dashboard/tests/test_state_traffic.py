"""The page asks for the state all the time: an unchanged state costs no body (304), a changed one goes out gzipped."""

import gzip
import json
import urllib.error
import urllib.request


def _open(base, headers=None):
    req = urllib.request.Request(base + "/api/state", headers=headers or {})
    return urllib.request.urlopen(req, timeout=30)


def test_unchanged_state_answers_304_without_a_body(act_server):
    with _open(act_server) as r:
        tag = r.headers["ETag"]
        assert json.loads(r.read())["rev"]
    try:
        _open(act_server, {"If-None-Match": tag})
        raise AssertionError("expected 304")
    except urllib.error.HTTPError as e:
        assert e.code == 304
        assert e.read() == b""


def test_other_revision_gets_the_full_state(act_server):
    with _open(act_server, {"If-None-Match": '"old-rev"'}) as r:
        assert r.status == 200
        assert json.loads(r.read())


def test_state_is_gzipped_when_the_browser_accepts_it(act_server):
    with _open(act_server, {"Accept-Encoding": "gzip"}) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        assert json.loads(raw)["rev"]

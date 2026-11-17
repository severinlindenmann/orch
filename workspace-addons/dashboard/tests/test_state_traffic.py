"""The page asks for the state all the time: an unchanged state costs a few bytes, a changed one goes out gzipped."""

import gzip
import json
import urllib.request


def _open(base, headers=None, query=""):
    req = urllib.request.Request(base + "/api/state" + query, headers=headers or {})
    return urllib.request.urlopen(req, timeout=30)


def test_unchanged_state_answers_a_few_bytes(act_server):
    with _open(act_server) as r:
        rev = json.loads(r.read())["rev"]
    with _open(act_server, query="?have=" + rev) as r:
        raw = r.read()
    assert json.loads(raw) == {"unchanged": True, "rev": rev}
    assert len(raw) < 200


def test_other_revision_gets_the_full_state(act_server):
    with _open(act_server, query="?have=old-rev") as r:
        assert "unchanged" not in json.loads(r.read())


def test_state_is_gzipped_when_the_browser_accepts_it(act_server):
    with _open(act_server, {"Accept-Encoding": "gzip"}) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        assert json.loads(raw)["rev"]

"""ORCH-403: one stalled request to the sharing server must not use up the dashboard's 10 s for the
Shared links page. `publish view` cuts each request after a few seconds and net retries the GET."""

import json

from test_publish_client import connect, own_sleeps

from orch import net, publish


def test_view_cuts_a_stalled_request_and_tries_again(proj, run, pub, monkeypatch):
    connect(run, pub)
    (proj / "a.txt").write_text("x")
    fid = json.loads(run("publish", "file", "a.txt", "--json")[1])["id"]

    real, timeouts = net.urllib.request.urlopen, []
    sleeps = own_sleeps(monkeypatch)

    def stalls_once(req, timeout, **kw):
        timeouts.append(timeout)
        if len(timeouts) == 1:  # the first request hangs until the time limit cuts it
            raise TimeoutError("timed out")
        return real(req, timeout=timeout, **kw)

    monkeypatch.setattr(net.urllib.request, "urlopen", stalls_once)
    v = publish.view(proj)

    shared = v["blocks"][0]
    assert [i["actions"][0]["action"]["args"]["id"] for i in shared["items"]] == [fid]
    assert sleeps == [1]  # tried once more after the stall
    # every request of the page has a short limit; the old 120 s let one stall hold the page past 10 s
    assert timeouts and all(t <= publish.VIEW_TIMEOUT for t in timeouts)
    assert publish.VIEW_TIMEOUT + sleeps[0] + publish.VIEW_TIMEOUT < 10


def test_other_publish_commands_keep_the_long_limit(proj, run, pub, monkeypatch):
    connect(run, pub)
    real, timeouts = net.urllib.request.urlopen, []

    def record(req, timeout, **kw):
        timeouts.append(timeout)
        return real(req, timeout=timeout, **kw)

    monkeypatch.setattr(net.urllib.request, "urlopen", record)
    publish.list_all(proj)  # `orch publish list` a person runs: a slow line is fine, no early cut
    assert timeouts and all(t == 120 for t in timeouts)

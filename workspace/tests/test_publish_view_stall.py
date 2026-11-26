"""ORCH-403, changed by ORCH-2170 (RP7): one stalled or refused request to publish must not hold the Publish
page. `publish view` makes one short try (no waits between tries) and, when there is no answer, lists the
local record and says publish can't be reached."""

import json
import time

from test_publish_client import connect

from orch import net, publish


def _share(proj, run, pub, name="a.txt", *extra):
    (proj / name).write_text("x")
    return json.loads(run("publish", "file", name, "--json", *extra)[1])["id"]


def test_view_gives_up_on_a_stalled_request_and_lists_the_local_record(proj, run, pub, monkeypatch):
    connect(run, pub)
    fid = _share(proj, run, pub, "a.txt", "--note", "Draft plan")
    publish._remember(proj, fid, expires_at="2099-01-01T00:00:00Z")  # the fake server's date is long past
    timeouts = []
    slept = []
    monkeypatch.setattr(net.time, "sleep", lambda s: slept.append(s))

    def stalls(req, timeout, **kw):
        timeouts.append(timeout)
        raise TimeoutError("timed out")

    monkeypatch.setattr(net.urllib.request, "urlopen", stalls)
    t0 = time.monotonic()
    v = publish.view(proj)
    assert time.monotonic() - t0 < 2  # nothing waited
    assert slept == [] and len(timeouts) == 1 and timeouts[0] <= publish.VIEW_TIMEOUT  # one short try
    assert (
        v["notice"] == "Publish can't be reached. People may not be able to open your links until it is back."
    )
    assert v["button"]["action"] == {"op": "addon.refresh"}
    shared = v["blocks"][0]
    assert [i["actions"][0]["action"]["args"]["id"] for i in shared["items"]] == [fid]
    assert shared["items"][0]["subtitle"] == "“Draft plan”"
    assert shared["meta"].startswith("As of ") and "No shared links" not in json.dumps(v)


def test_other_publish_commands_keep_the_long_limit(proj, run, pub, monkeypatch):
    connect(run, pub)
    real, timeouts = net.urllib.request.urlopen, []

    def record(req, timeout, **kw):
        timeouts.append(timeout)
        return real(req, timeout=timeout, **kw)

    monkeypatch.setattr(net.urllib.request, "urlopen", record)
    publish.list_all(proj)  # `orch publish list` a person runs: a slow line is fine, no early cut
    assert timeouts and all(t == 120 for t in timeouts)

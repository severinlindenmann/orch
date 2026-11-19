"""GET /api/docs (docspage.py): every Documentation page plus this workspace's live facts, read locally. A relay or
publish address shows only its host name; a token never leaves."""

import json
import urllib.request

from orch_dashboard import docspage


def _rows(**on):
    return [{"name": n, "active": a, "running": a, "background": True, "docs_pages": []} for n, a in on.items()]


def test_relay_shows_its_host_never_the_token(ws, monkeypatch):
    from orch import net

    monkeypatch.setattr(net, "load_service", lambda root, name: {"url": f"https://{name}.example.org/x", "workspace": "ws_1", "token": "orn_SECRET"})
    out = docspage.live(ws, {"settings": {"live_max": 3, "reviewer_on": False}, "tickets": [{"status": "active"}, {"status": "done"}]},
                        _rows(relay=True, publish=True, focus=False))
    assert out["relay"]["value"] == "Connected to relay.example.org" and out["relay"]["tone"] == "done"
    assert out["publish"]["value"] == "Connected"
    assert out["helper-limit"] == {"label": "Helper limit", "value": "3 at once", "tone": "", "note": "1 working now"}
    assert out["reviewer"]["value"] == "Off"
    assert "orn_SECRET" not in json.dumps(out) and "ws_1" not in json.dumps(out)


def test_off_or_not_connected_says_so(ws):
    out = docspage.live(ws, {"settings": {"live_max": None, "reviewer_on": True}}, _rows(relay=False, publish=True))
    assert out["relay"]["value"] == "Off"
    assert out["publish"]["value"] == "Not connected"  # no publish.json in the workspace
    assert out["helper-limit"]["value"] == "No limit"
    assert out["reviewer"]["value"] == "On"


def test_api_docs_serves_pages_and_live_facts(server):
    req = urllib.request.Request(server + "/api/docs", headers={"Origin": server, "Sec-Fetch-Site": "same-origin"})
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    ids = [p["id"] for p in data["pages"]]
    assert ids[0] == "ticket-life" and "new-ticket" in ids
    assert [g["id"] for g in data["groups"]] == ["orch", "builtin", "addon"]
    assert set(data["live"]["rows"]) >= {"relay", "publish", "helper-limit", "reviewer", "addons"}
    assert "orn_SECRET" not in json.dumps(data)

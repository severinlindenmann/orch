"""The Usage page: its model (GET /api/page), the clicks (`orch usage act`) and the page server's fence."""

import json
import threading
import urllib.error
import urllib.request

import pytest
from conftest import jrun, switcher_data

from orch_usage import cli as usage_cli
from orch_usage import page, server, store, switching


def _seed(cli):
    assert jrun(cli, "list")[0] == 0
    for args in (
        ("limit", "first", "95%", "--period", "5h"),
        ("limit", "first", "100%", "--period", "week"),
        ("limit", "TEAMCO", "70", "--period", "week"),
        ("order", "TEAMCO", "2"),
    ):
        assert jrun(cli, *args, "--by", "human:owner")[0] == 0


def _ids(ws):
    return {a["label"]: a["id"] for a in store.load(ws)["accounts"]}


def _act(cli, verb, target, by="human:Some Person"):
    return jrun(cli, "act", verb, target, "--by", by)


def test_page_model_shows_use_limits_resets_and_who_is_in_use(cli, fake_switcher, ws):
    _seed(cli)
    m = page.build(usage_cli.gather(ws), ws)
    assert m["switcher"] is True and m["switching"] is False and m["one_account"] is False
    first = m["accounts"][0]
    assert (first["label"], first["state"], first["unit"], first["periods"]) == (
        "first",
        "in-use",
        "%",
        ["5h", "week"],
    )
    assert [(b["period"], b["used"], b.get("limit")) for b in first["bars"]] == [
        ("5h", 97.0, 95),
        ("week", 80.0, 100),
    ]
    assert first["bars"][0]["resets_at"].startswith("2026-11-16T19:29")
    assert [a["label"] for a in m["accounts"]] == ["first", "TEAMCO", "second"]
    assert m["accounts"][1]["state"] == "ready"
    assert "@" not in json.dumps(m) and "example.test" not in json.dumps(m)  # never an address
    assert (
        "source" not in m["accounts"][0] and "key" not in m["accounts"][0]
    )  # never the reader's key or path


def test_every_click_is_a_cli_command_with_a_history_line(cli, fake_switcher, ws):
    _seed(cli)
    ids = _ids(ws)
    second = ids["second"]
    code, d = _act(cli, "limit", f"{second}:week:85%")
    assert (
        code == 0
        and d["changed"] is True
        and d["account"]["rule"]["limits"] == [{"value": 85, "unit": "%", "period": "week"}]
    )
    assert _act(cli, "limit", f"{second}:5h:92")[0] == 0
    assert _act(cli, "limit", f"{second}:5h:none")[0] == 0
    assert _act(cli, "order", f"{second}:up")[1]["account"]["order"] == 2
    assert _act(cli, "order", f"{second}:3")[1]["account"]["order"] == 3
    assert _act(cli, "off", second)[1]["account"]["on"] is False
    assert _act(cli, "on", second)[1]["account"]["on"] is True
    assert _act(cli, "end", f"{second}:2099-01-31")[1]["account"]["rule"]["ends"].startswith("2099-0")
    assert _act(cli, "end", f"{second}:none")[1]["account"]["rule"]["ends"] is None
    assert _act(cli, "switching", "on")[1]["switching"] is True
    rows = page.history_rows(ws)
    assert rows[0] == {"at": rows[0]["at"], "who": "You", "text": "Switching turned on"}
    assert any(r["text"] == "second: limit 85% (week)" for r in rows)
    whos = {r["who"] for r in store.history(ws)}
    assert "human:Some_Person" in whos  # a name with spaces is one word in the history


def test_period_change_and_a_credit_limit_until_a_date(cli, fake_switcher, ws):
    _seed(cli)
    ids = _ids(ws)
    p = ws / ".orch/addons/usage/accounts.json"
    data = json.loads(p.read_text())
    data["accounts"].append(
        {
            "id": "a_api001",
            "label": "API key 1",
            "type": "api-key",
            "provider": "anthropic-api",
            "source": {"reader": "none"},
            "on": True,
            "order": 4,
            "rule": {"limits": [], "for": [], "ends": None},
            "prev": None,
        }
    )
    p.write_text(json.dumps(data))
    code, d = _act(cli, "limit", "a_api001:month:100$")
    assert code == 0 and d["account"]["rule"]["limits"] == [{"value": 100, "unit": "$", "period": "month"}]
    code, d = _act(cli, "period", "a_api001:month:until:2099-02-01")
    assert code == 0 and d["account"]["rule"]["limits"][0]["period"] == "until"
    code, d = _act(cli, "period", f"{ids['TEAMCO']}:week:5h")
    assert code == 0 and d["account"]["rule"]["limits"][0]["period"] == "5h"
    m = page.build(usage_cli.gather(ws), ws)
    api = next(a for a in m["accounts"] if a["id"] == "a_api001")
    assert api["unit"] == "$" and api["periods"] == ["week", "month", "until"]
    assert api["bars"][0]["unit"] == "$" and api["bars"][0]["until"].startswith("2099-02-0")


@pytest.mark.parametrize(
    "verb,target",
    [
        ("limit", "a_zzzzzz:week:90"),  # no such account
        ("limit", "first:week:90"),  # a label, not an id
        ("limit", "ID:week:--by=agent:x"),
        ("limit", "ID:year:90"),
        ("limit", "ID:week:-5"),
        ("limit", "ID:week:101%"),
        ("order", "ID:sideways"),
        ("end", "ID:tomorrow"),
        ("end", "ID:2000-01-01"),
        ("switching", "maybe"),
        ("rm", "ID"),
        ("on", "ID extra"),
    ],
)
def test_bad_clicks_are_refused_and_change_nothing(cli, fake_switcher, ws, verb, target):
    _seed(cli)
    before = (ws / ".orch/addons/usage/accounts.json").read_text()
    target = target.replace("ID", _ids(ws)["first"])
    code, d = _act(cli, verb, target)
    assert code == 2 and d["error"]
    assert (ws / ".orch/addons/usage/accounts.json").read_text() == before


def test_all_at_limit_and_one_account(cli, fake_switcher, ws):
    _seed(cli)
    switching._write(switching.memory_path(ws), {"all_at_limit": True})
    assert page.build(usage_cli.gather(ws), ws)["all_at_limit"] is True
    data = switcher_data()
    data["accounts"] = data["accounts"][:1]
    fake_switcher.answer(data)
    m = page.build(usage_cli.gather(ws), ws)
    # the two others stay known (missing), so a second account is still there
    assert m["one_account"] is False and {a["state"] for a in m["accounts"][1:]} == {"missing"}


def test_one_account_only(cli, fake_switcher, ws):
    data = switcher_data()
    data["accounts"] = data["accounts"][:1]
    fake_switcher.answer(data)
    m = page.build(usage_cli.gather(ws), ws)
    assert m["one_account"] is True and len(m["accounts"]) == 1


def test_history_is_thirty_days_and_plain(ws):
    store.usage_dir(ws).mkdir(parents=True, exist_ok=True)
    rows = [
        {"at": "2000-01-01T00:00:00Z", "who": "human:x", "what": "old", "label": "A"},
        {"at": store.now(), "who": "usage", "what": "switched to B", "label": "A", "why": "week 97% of 98%"},
        {"at": store.now(), "who": "agent:helper", "what": "turned off", "label": "B"},
        {"at": "not a time", "who": "usage", "what": "bad", "label": "A"},
    ]
    (store.usage_dir(ws) / "history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = page.history_rows(ws)
    assert [(r["who"], r["text"]) for r in out] == [
        ("A helper", "B: turned off"),
        ("Usage", "A: switched to B (week 97% of 98%)"),
    ]


# ---------------------------------------------------------------- the page server


@pytest.fixture
def served(ws):
    model = {"accounts": [], "switcher": False, "warnings": ["The account switcher is not installed."]}
    srv = server.make_server(ws, 0, gather=lambda root: model, nonce="ab" * 16)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _get(port, path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_server_serves_page_model_and_kit_only(served):
    code, body, hdr = _get(served, "/api/page")
    assert code == 200 and json.loads(body)["schema"] == "orch.usage-page/1"
    assert "default-src 'self'" in hdr["Content-Security-Policy"]
    code, body, _ = _get(served, "/", {"X-Forwarded-Prefix": "/addon/usage"})
    assert code == 200 and b'href="/addon/usage/kit/tokens.css"' in body and b"__P__" not in body
    code, body, _ = _get(served, "/", {"X-Forwarded-Prefix": "https://elsewhere"})
    assert code == 200 and b'href="/kit/tokens.css"' in body
    assert _get(served, "/web/usage.js")[0] == 200
    assert _get(served, "/web/../server.py")[0] == 404
    assert _get(served, "/kit/gallery.html")[0] == 404


def test_server_only_reads_and_proves_its_start(served):
    req = urllib.request.Request(f"http://127.0.0.1:{served}/api/page", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 405
    code, body, _ = _get(served, "/ready?c=" + "0" * 32)
    assert code == 200 and set(json.loads(body)) == {"pid", "mac"}
    assert _get(served, "/ready?c=xyz")[0] == 404
    code, _, _ = _get(served, "/api/page", {"Host": "evil.test"})
    assert code == 403
    code, _, _ = _get(served, "/api/page", {"Sec-Fetch-Site": "cross-site"})
    assert code == 403


def test_the_dashboards_exact_command_shape(cli, fake_switcher, ws):
    """The dashboard sends `act <verb> --by <person> --json -- <target>` (addon-manifest.md, Act)."""
    _seed(cli)
    acc = _ids(ws)["second"]
    code, out, _ = cli("act", "limit", "--by", "human:owner", "--json", "--", f"{acc}:week:88%")
    assert code == 0 and json.loads(out)["account"]["rule"]["limits"] == [
        {"value": 88, "unit": "%", "period": "week"}
    ]

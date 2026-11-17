"""The phone warns when a tool login, connection or key runs out soon or stopped working (ORCH-47,
contracts/tool-alert.md, vectors/tool-alert-v1.json): what the workspace sends, and that nothing is sent or
kept while the relay is off or no phone is paired."""

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from orch import addons, health, phone_alerts, phone_view, relay

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
VECTORS = json.loads((CONTRACTS / "vectors/tool-alert-v1.json").read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(json.loads((CONTRACTS / "message.schema.json").read_text()))
NOW = datetime.strptime(VECTORS["now"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A workspace whose relay, phones and last check the case sets; every message to the relay is kept."""
    box = {"relay_on": True, "phones": ["ph_iphone0001"], "doc": None, "sent": [], "logged": []}
    monkeypatch.setattr(addons, "active", lambda root: {"relay": {}} if box["relay_on"] else {})
    monkeypatch.setattr(phone_view, "_paired", lambda root: list(box["phones"]))
    monkeypatch.setattr(health, "last", lambda root: box["doc"])
    (tmp_path / ".orch" / "secrets").mkdir(parents=True)
    state = tmp_path / ".orch" / "secrets" / "tool-alerts.json"
    monkeypatch.setattr(phone_alerts, "_state_path", lambda root: state)

    def fake_message(root, to, type_, body, ticket=None, reply_to=None, mid=None, created_at=None):
        m = {"schema": "orch.msg/1", "id": mid, "from": VECTORS["workspace_id"], "to": to, "type": type_,
             "created_at": created_at, "body": body}  # fmt: skip
        assert ticket is None and reply_to is None
        box["sent"].append(m)
        return {**m, "sent": True}

    monkeypatch.setattr(relay, "_message", fake_message)
    monkeypatch.setattr(
        relay, "log_send_failure", lambda root, what, why: box["logged"].append((what, str(why)))
    )
    box["state"] = state
    return box


def _seed(box, case):
    box["relay_on"], box["phones"] = case["relay_on"], case["phones"]
    box["doc"] = {
        "schema": "orch.health/1",
        "checked_at": case.get("checked_at", VECTORS["now"]),
        "items": case["items"],
    }
    if case["sent"]:
        box["state"].write_text(json.dumps(case["sent"]))


@pytest.mark.parametrize("case", VECTORS["workspace"], ids=lambda c: c["name"])
def test_vector_workspace(tmp_path, wired, case):
    _seed(wired, case)
    ids = phone_alerts.sync(tmp_path, now=NOW, tz=UTC)
    assert [m["body"] for m in wired["sent"]] == case["send"]
    assert ids == [m["id"] for m in wired["sent"]]
    for m in wired["sent"]:
        assert m["to"] == "phones"
        assert list(VALIDATOR.iter_errors(m)) == []
        raw = json.dumps(m)
        assert "A ticket title that never travels" not in raw  # only keys, never titles
        assert "t_orch" not in raw  # no ticket ids
    if not case["relay_on"] or not case["phones"]:
        assert not wired["state"].exists()  # with no phone connected nothing changes, nothing is kept


def test_sent_once_then_quiet(tmp_path, wired):
    case = VECTORS["workspace"][0]
    _seed(wired, case)
    first = phone_alerts.sync(tmp_path, now=NOW, tz=UTC)
    again = phone_alerts.sync(tmp_path, now=NOW, tz=UTC)
    assert len(first) == 1 and again == []
    kept = json.loads(wired["state"].read_text())
    assert kept["claude"]["id"] == first[0] and kept["claude"]["state"] == "soon"


def test_phone_paired_later_gets_open_warning(tmp_path, wired):
    case = {**VECTORS["workspace"][0], "phones": []}
    _seed(wired, case)
    assert phone_alerts.sync(tmp_path, now=NOW, tz=UTC) == []
    wired["phones"] = ["ph_iphone0001"]
    assert len(phone_alerts.sync(tmp_path, now=NOW, tz=UTC)) == 1


def test_secret_in_label_is_never_sent(tmp_path, wired):
    case = VECTORS["workspace"][0]
    _seed(wired, case)
    wired["doc"]["items"] = [{**case["items"][0], "label": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"}]
    assert phone_alerts.sync(tmp_path, now=NOW, tz=UTC) == []
    assert wired["sent"] == [] and wired["logged"]


def test_relay_refusal_is_logged_not_raised(tmp_path, wired, monkeypatch):
    _seed(wired, VECTORS["workspace"][0])

    def refuse(*a, **k):
        raise relay.Refused("no")

    monkeypatch.setattr(relay, "_message", refuse)
    assert phone_alerts.sync(tmp_path, now=NOW, tz=UTC) == []
    assert wired["logged"]


def test_words_match_dashboard_name_rule():
    assert phone_alerts.label({"label": "GitHub", "kind": "login"}) == "GitHub login"
    assert phone_alerts.label({"label": "Payments key", "kind": "key"}) == "Payments key"
    assert phone_alerts.label({"label": "Wiki‮\nx", "kind": "connection"}) == "Wiki x connection"
    a = phone_alerts.alert(
        {"name": "gh", "label": "GitHub", "kind": "login", "state": "soon", "ends_at": None, "stops": []}
    )
    assert phone_alerts.text(a) == "The GitHub login runs out soon. Renew it on your computer."


def test_inbox_pull_runs_it(tmp_path, monkeypatch):
    calls = []
    for name in ("sync_open", "sync", "sync_light", "sync_reviews", "sync_cards"):
        monkeypatch.setattr(phone_view, name, lambda root: [])
    monkeypatch.setattr(relay, "send_working", lambda root: None)
    monkeypatch.setattr(phone_alerts, "sync", lambda root: calls.append(root) or [])
    relay.sync_phone_views(tmp_path)
    assert calls == [tmp_path]

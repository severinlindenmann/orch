"""cli.visible at 10,000 tickets (ORCH-518): the add-ons that are on are worked out once per listing, not
once per ticket (65 s of `orch ticket list --all --json` at 10,000), and a change of the workspace's add-on
switch file shows at once."""

import json

from orch import addons, cli


def test_one_registry_read_per_listing_and_a_switch_shows_at_once(tmp_path, monkeypatch):
    root = tmp_path
    (root / ".orch").mkdir()
    on = {"focus": {}}
    calls = []

    def active(r):
        calls.append(r)
        return dict(on)

    monkeypatch.setattr(addons, "active", active)
    cli._SHOWN_EXT.clear()
    t = {"id": "t_aaaaaa", "ext": {"focus": {"x": 1}, "factory": {"y": 2}, "relay": {"z": 3}}}
    for _ in range(500):
        assert cli.visible(root, t)["ext"] == {"focus": {"x": 1}, "relay": {"z": 3}}
    assert len(calls) == 1

    on["factory"] = {}
    addons.activation_path(root).write_text(json.dumps({"active": on}), encoding="utf-8")  # turned on here
    assert set(cli.visible(root, t)["ext"]) == {"focus", "factory", "relay"}
    assert len(calls) == 2


def test_kept_only_for_a_moment(tmp_path, monkeypatch):
    root = tmp_path
    calls = []
    monkeypatch.setattr(addons, "active", lambda r: calls.append(r) or {})
    cli._SHOWN_EXT.clear()
    t = {"id": "t_aaaaaa", "ext": {"focus": {}}}
    cli.visible(root, t)
    now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    cli._SHOWN_EXT.clear()
    cli.visible(root, t)
    now[0] += cli.SHOWN_EXT_SECONDS + 0.1  # another process may have turned one on: ask again
    cli.visible(root, t)
    assert len(calls) == 3

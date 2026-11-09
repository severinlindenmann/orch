"""Workspace look (contracts/look.md, vectors/look-v1.json): defaults, local_set, connect, agent guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orch import addons, config, look, net
from orch.errors import Refused

C = Path(__file__).resolve().parents[2] / "contracts"
VEC = json.loads((C / "vectors/look-v1.json").read_text(encoding="utf-8"))


def test_packaged_copy_is_the_contract():
    assert (Path(look.__file__).with_name("look.json")).read_bytes() == (C / "look.json").read_bytes()
    assert len(look.ICON_IDS) == 100 and len(look.COLOR_IDS) == 12


@pytest.mark.parametrize("v", VEC["default"], ids=lambda v: v["name"][:12] or "empty")
def test_default(v):
    assert look.djb2_32(v["name"]) == v["djb2_32"]
    assert look.default_color(v["name"]) == v["color"]
    assert look.default_letter(v["name"]) == v["letter"]


@pytest.fixture
def ws(proj):
    (proj / ".orch").mkdir()
    return proj


def _seed(root, st):
    if st["icon"] or st["color"] or st["set_by"]:
        look._write(root, st["icon"], st["color"], st["set_by"])


@pytest.mark.parametrize("v", VEC["local_set"], ids=lambda v: v["name"])
def test_local_set(ws, v):
    _seed(ws, v["local"])
    by = "agent:claude" if v["caller"] == "agent" else "human:owner"
    kw = {k: v["request"][k] for k in ("icon", "color") if k in v["request"]}
    if v["ok"]:
        look.set_look(ws, by=by, push=False, **kw)
    else:
        with pytest.raises(Refused):
            look.set_look(ws, by=by, push=False, **kw)
    assert look.read(ws) == v["after"]


def test_set_by_is_not_in_the_workspace(ws):
    look.set_look(ws, icon="bank", by="human:owner", push=False)
    assert "look_set_by" not in (ws / ".orch/config.toml").read_text()
    # an agent writing the lock into config.toml changes nothing
    config.set_key(ws, "workspace", "look_set_by", "agent")
    with pytest.raises(Refused):
        look.set_look(ws, icon="house", by="agent:claude", push=False)
    assert look.read(ws)["set_by"] == "human"


def test_unwritable_home_is_a_skippable_refusal_not_a_traceback(ws, monkeypatch):
    # a sandboxed agent (codex workspace-write) cannot write ORCH_HOME: "optional, skip it", not a crash
    def deny(*a, **k):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(net, "write_json", deny)
    with pytest.raises(Refused, match="optional: skip it"):
        look.set_look(ws, icon="bank", by="agent:codex", push=False)


def test_agent_in_environment_counts_as_agent(ws, run, monkeypatch):
    run("look", "set", "--icon", "bank", "--by", "human:owner")
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run("look", "set", "--icon", "house", "--by", "human:owner")
    assert code == 2 and "person chose" in err


def test_cli_list_and_show(ws, run):
    code, out, _ = run("look", "list", "--json")
    d = json.loads(out)
    assert code == 0 and len(d["icons"]) == 100 and len(d["colors"]) == 12
    code, out, _ = run("look", "show")
    assert "Nobody has picked" in out
    code, _, err = run("look", "set", "--icon", "walet")
    assert code == 2 and "wallet" in err


def test_bad_hand_edit_is_ignored(ws):
    config.set_key(ws, "workspace", "icon", "unicorn")
    assert look.read(ws)["icon"] is None


class Fake:
    def __init__(self, who=None):
        self.calls, self.who = [], who or {}

    def __call__(self, method, url, headers=None, body=None, timeout=0):
        self.calls.append((method, url, body))
        return 200, self.who


def _connect(ws, monkeypatch, fake):
    net.write_json(net.secrets_dir(ws) / "relay.json", {"url": "http://r", "workspace": "w", "token": "t"})
    monkeypatch.setattr(net, "call_json", fake)


@pytest.mark.parametrize("v", VEC["connect"], ids=lambda v: v["name"])
def test_connect(ws, monkeypatch, v):
    if v["local"]["icon"] or v["local"]["color"]:
        look._write(ws, v["local"]["icon"], v["local"]["color"], "human")
    fake = Fake()
    _connect(ws, monkeypatch, fake)
    look.on_connect(ws, "relay", v["remote"])
    got = look.read(ws)
    expect = v["write_local"] or v["local"]
    assert (got["icon"], got["color"]) == (expect["icon"], expect["color"])
    if v["write_local"]:
        assert got["set_by"] == v["write_local"]["set_by"] == "human"
    assert fake.calls == [("PATCH", "http://r/v1/me", v["send"])]


def test_failed_push_is_remembered(ws, monkeypatch):
    def boom(*a, **k):
        raise Refused("down")

    _connect(ws, monkeypatch, boom)
    out = look.set_look(ws, icon="bank", by="human:o")
    assert out["sent"] == {"relay": False}
    assert look.show.__name__ and net.read_json(look._state_path(ws), {}) == {"relay": "not yet sent"}


@pytest.mark.parametrize("v", VEC["shared_pages_set"], ids=lambda v: v["name"])
def test_shared_pages(ws, monkeypatch, v):
    fake = Fake()
    net.write_json(net.secrets_dir(ws) / "publish.json", {"url": "http://p", "workspace": "w", "token": "t"})
    monkeypatch.setattr(net, "call_json", fake)
    if v["local"] is False:
        look.set_shared_pages(ws, False, by="human:o")
        fake.calls.clear()
    by = "agent:claude" if v["caller"] == "agent" else "human:o"
    if v["ok"]:
        assert look.set_shared_pages(ws, v["request"], by=by) == v["after"]
        assert fake.calls == [("PATCH", "http://p/v1/me", {"show_on_shared_pages": v["request"]})]
    else:
        with pytest.raises(Refused):
            look.set_shared_pages(ws, v["request"], by=by)
        assert fake.calls == []
    assert look.shared_pages(ws) is v["after"]


def test_status_json_has_look(ws, run):
    code, out, _ = run("status", "--json")
    assert code == 0


def test_cli_shared_pages(ws, run, monkeypatch, tmp_path):
    monkeypatch.setenv("ORCH_HOME", str(addons.real_home() / "home"))
    code, out, _ = run("look", "shared-pages", "--json")
    assert code == 0 and json.loads(out) == {"on": True}  # on by default
    code, out, _ = run("look", "shared-pages", "off", "--by", "human:owner", "--json")
    assert code == 0 and json.loads(out) == {"on": False}
    assert look.shared_pages(ws) is False
    code, _, err = run("look", "shared-pages", "on", "--by", "agent:claude")
    assert code == 2 and "person" in err and look.shared_pages(ws) is False

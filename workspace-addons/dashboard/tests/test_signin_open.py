"""The dashboard sign-in (report r-1119-1255-ws): a second workspace keeps its port over a restart (so the
browser keeps its sign-in), `orch dashboard open` opens the page with a sign-in, and the bookmark link names a real address."""

import errno
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("orch")
from orch import addons, pagelaunch, pagesession, tickets
from orch_dashboard import cli, service


@pytest.fixture
def ws(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    (acct / ".orch-test" / "home").mkdir(parents=True)
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    for k in list(os.environ):
        if k.startswith("CODEX_") or k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ORCH_AGENT"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    root = acct / ".orch-test" / "ws"
    (root / ".orch" / "tickets").mkdir(parents=True)
    return root


# ---- the fallback port ------------------------------------------------------------------------------------


def test_fallback_ports_are_the_same_on_every_start_and_below_short_lived_ports(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    ports = service.fallback_ports(a)
    assert ports == service.fallback_ports(a)  # same folder, same ports
    assert ports != service.fallback_ports(b)  # another workspace starts elsewhere
    assert len(set(ports)) == service.FALLBACK_TRIES
    assert all(20000 <= p < 30000 for p in ports)  # never in a system's short-lived range (32768+)
    assert 8420 not in ports


def test_a_taken_8420_binds_this_workspaces_own_port_not_a_random_one(ws, monkeypatch):
    tried = []
    first, second = service.fallback_ports(ws)[:2]

    def fake_make_server(root, port, orch_bin=None, remote=None):
        tried.append(port)
        if port in (8420, first):  # another workspace has 8420, something else the first fallback
            raise OSError(errno.EADDRINUSE, "in use")
        return port

    monkeypatch.setattr(cli, "make_server", fake_make_server)
    assert cli._bind_fallback(ws) == second
    assert 0 not in tried


def test_all_fallback_ports_taken_falls_back_to_any_free_port(ws, monkeypatch):
    def fake_make_server(root, port, orch_bin=None, remote=None):
        if port:
            raise OSError(errno.EADDRINUSE, "in use")
        return "any"

    monkeypatch.setattr(cli, "make_server", fake_make_server)
    assert cli._bind_fallback(ws) == "any"


def test_the_kept_session_is_found_again_on_the_same_fallback_port(ws):
    """The point of a stable port: the second start adopts the first start's session (cookie and page secret)."""
    port = service.fallback_ports(ws)[0]
    one = pagesession.PageSession(ws, "dashboard", port)
    two = pagesession.PageSession(ws, "dashboard", port)
    assert two.resumed and (two.cookie, two.secret) == (one.cookie, one.secret)


# ---- orch dashboard open ----------------------------------------------------------------------------------


def _running(monkeypatch, port=20123):
    monkeypatch.setattr(service, "running", lambda root: {"pid": 1, "port": port})


def test_open_opens_the_running_dashboard_with_a_one_time_sign_in(ws, monkeypatch, capsys):
    _running(monkeypatch)
    opened = []
    monkeypatch.setattr(pagelaunch, "open_browser", lambda url: opened.append(url) or True)
    assert cli.main(["--dir", str(ws), "open"]) == 0
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:20123") and "#launch=" in opened[0]
    out = capsys.readouterr().out
    assert "signed in" in out and "#launch=" not in out  # the token is never printed without --print


def test_open_print_prints_a_link_with_the_local_address(ws, monkeypatch, capsys):
    _running(monkeypatch)
    monkeypatch.setattr(pagelaunch, "open_browser", lambda url: pytest.fail("no browser with --print"))
    assert cli.main(["--dir", str(ws), "open", "--print", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["url"].startswith("http://127.0.0.1:20123/#launch=")


def test_open_is_refused_for_an_agent(ws, monkeypatch, capsys):
    _running(monkeypatch)
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: False)
    monkeypatch.setattr(pagelaunch, "open_browser", lambda url: pytest.fail("an agent never opens a sign-in"))
    assert cli.main(["--dir", str(ws), "open"]) == 2
    assert "Only a person can sign in" in capsys.readouterr().err
    assert not (Path(pagelaunch.key_dir(ws)) / "launch-dashboard.token").exists()


@pytest.mark.parametrize("env", [{"tool": "claude"}, {"run": "r_1"}])
@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_open_print_never_prints_a_sign_in_link_for_a_helper(ws, monkeypatch, capsys, env, extra):
    """ORCH-2167: the printed link carries the sign-in. Under an agent tool, and inside an orch run whose tool
    orch does not know, `--print` prints no link (so none lands in a helper's log) and makes no token."""
    _running(monkeypatch)
    monkeypatch.setattr(tickets, "agent_tool", lambda: env.get("tool"))
    if env.get("run"):
        monkeypatch.setenv("ORCH_RUN", env["run"])
    else:
        monkeypatch.delenv("ORCH_RUN", raising=False)
    monkeypatch.setattr(pagelaunch, "is_test_workspace", lambda root: False)
    assert cli.main(["--dir", str(ws), "open", "--print", *extra]) == 2
    cap = capsys.readouterr()
    assert "#launch=" not in cap.out + cap.err and "http" not in cap.out
    assert not (Path(pagelaunch.key_dir(ws)) / "launch-dashboard.token").exists()


def test_open_says_how_to_start_a_stopped_dashboard(ws, monkeypatch, capsys):
    monkeypatch.setattr(service, "running", lambda root: None)
    assert cli.main(["--dir", str(ws), "open"]) == 2
    assert "orch start" in capsys.readouterr().err


def test_the_sign_in_notice_names_the_open_command():
    assert cli.OPEN_COMMAND in pagesession.SIGNIN_MSG
    assert cli.OPEN_COMMAND in pagesession.REVOKED_MSG
    assert pagesession.SIGNIN_MSG.startswith("Sign in to do this")  # the page keys its notice on these words


# ---- the bookmark link ------------------------------------------------------------------------------------


def test_bookmark_link_uses_the_local_address_without_remote_listening(ws, monkeypatch, capsys):
    _running(monkeypatch, 20321)
    assert cli.main(["--dir", str(ws), "remote", "link", "--json"]) == 0
    url = json.loads(capsys.readouterr().out)["url"]
    assert url.startswith("http://127.0.0.1:20321/go/") and "<" not in url


def test_bookmark_link_of_a_stopped_dashboard_says_how_to_start_it(ws, monkeypatch, capsys):
    monkeypatch.setattr(service, "running", lambda root: None)
    assert cli.main(["--dir", str(ws), "remote", "link"]) == 2
    err = capsys.readouterr().err
    assert "orch start" in err and "address of the dashboard" not in err


def test_a_refused_new_bookmark_keeps_the_old_one(ws, monkeypatch, capsys):
    old = pagelaunch.standing_link_secret(ws)
    monkeypatch.setattr(service, "running", lambda root: None)
    assert cli.main(["--dir", str(ws), "remote", "link", "--new"]) == 2
    assert pagelaunch.standing_link_ok(ws, old)


def test_open_without_a_sign_in_link_says_so_and_opens_nothing(ws, monkeypatch, capsys):
    _running(monkeypatch)
    monkeypatch.setattr(pagelaunch, "write_launch_token", lambda root, server, life=30, why=None: None)
    monkeypatch.setattr(pagelaunch, "open_browser", lambda url: pytest.fail("no page without the sign-in"))
    assert cli.main(["--dir", str(ws), "open"]) == 2
    assert "could not be made" in capsys.readouterr().err

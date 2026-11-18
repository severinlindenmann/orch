"""Owner rule (16 Nov): after the sign-in, everything works from any computer. The only check of a page
server is the sign-in (cookie + page secret, or the dashboard's word for an add-on page behind it); nothing
checks where the browser is, and no code tells a person to come to "this computer"."""

import re
from pathlib import Path

import pytest

from orch import addons, pagesession
from orch import home as home_mod

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def tws(tmp_path, monkeypatch):
    acct = tmp_path / "acct"
    ws = acct / ".orch-test" / "ws"
    (ws / ".orch").mkdir(parents=True)
    (acct / ".orch-test" / "home").mkdir()
    monkeypatch.setattr(addons, "real_home", lambda: acct)
    monkeypatch.setenv("ORCH_HOME", str(acct / ".orch-test" / "home"))
    monkeypatch.setattr(home_mod, "install_kind", lambda: "test")
    for k in ("ORCH_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.delenv(k, raising=False)
    return ws


def _person(s, port, **extra):
    return {"Cookie": f"{s.cookie_name(port)}={s.cookie}", pagesession.PAGE_HEADER: s.secret, **extra}


def test_the_session_acts_from_any_host_and_through_any_proxy(tws):
    s = pagesession.PageSession(tws, "dashboard", 8420)
    s.active = True
    for extra in (
        {"Host": "127.0.0.1:8420"},
        {"Host": "orch.team.example"},
        {"Host": "10.0.0.5:8791", "X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"},
        {"Host": "127.0.0.1:8420", "Forwarded": "for=203.0.113.7", "X-Forwarded-Prefix": "/x"},
    ):
        assert s.can_act(_person(s, 8420, **extra), 8420), extra
    # still the login: the cookie alone, the secret alone or another port's name is no session
    assert not s.can_act({"Cookie": f"{s.cookie_name(8420)}={s.cookie}"}, 8420)
    assert not s.can_act({pagesession.PAGE_HEADER: s.secret}, 8420)
    assert not s.can_act(_person(s, 8420), 8421)
    assert s.cookie_ok({"Cookie": f"{s.cookie_name(8420)}={s.cookie}"}, 8420)
    assert not s.cookie_ok({"Cookie": f"{s.cookie_name(8420)}=x{s.cookie}"}, 8420)


def test_the_session_is_kept_across_a_restart_and_a_used_link_ends_it(tws):
    a = pagesession.PageSession(tws, "dashboard", 8420)
    b = pagesession.PageSession(tws, "dashboard", 8420)  # the restarted server, same port
    assert (a.cookie, a.secret) == (b.cookie, b.secret)
    c = pagesession.PageSession(tws, "dashboard", 8421)  # another port: its own session (like its cookie)
    assert c.cookie != a.cookie
    f = home_mod.key_dir(tws) / "session-dashboard-8420.key"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    from orch import pagelaunch

    tok = pagelaunch.write_launch_token(tws, "dashboard")
    assert b.launch(tok) == b.cookie
    assert b.launch(tok) is None and b.revoked  # the link used twice: the session ends, and stays ended
    d = pagesession.PageSession(tws, "dashboard", 8420)
    assert (d.cookie, d.secret) == (b.cookie, b.secret) != (a.cookie, a.secret)


def test_a_session_older_than_its_life_is_not_kept(tws):
    a = pagesession.PageSession(tws, "dashboard", 8420)
    f = home_mod.key_dir(tws) / "session-dashboard-8420.key"
    f.write_text(f"{a.cookie}\n{a.secret}\n1\n")  # expired long ago
    b = pagesession.PageSession(tws, "dashboard", 8420)
    assert b.cookie != a.cookie


def test_the_dashboard_vouches_only_with_the_private_key(tws):
    key = pagesession.vouch_key(tws, create=True)
    assert key and pagesession.vouch_key(tws) == key  # made once, then the same
    f = pagesession.PageSession(tws, "focus", 8430)
    f.active = True
    assert f.can_act({pagesession.VOUCH_HEADER: key, "X-Forwarded-Prefix": "/addon/focus"}, 8430)
    assert not f.can_act({pagesession.VOUCH_HEADER: key + "x"}, 8430)
    assert not f.can_act({pagesession.VOUCH_HEADER: ""}, 8430)
    d = pagesession.PageSession(tws, "dashboard", 8420)
    d.active = True
    assert not d.can_act({pagesession.VOUCH_HEADER: key}, 8420)  # the dashboard never takes its own word
    f.active = False  # a server started by an agent never acts as the person
    assert not f.can_act({pagesession.VOUCH_HEADER: key}, 8430)


# The texts and checks the owner ruled out. A product file that brings one back fails here.
FORBIDDEN = (
    re.compile(r"from this computer", re.I),
    re.compile(r"dashboard on this computer", re.I),
    re.compile(r"orch restarted\. Reload this page", re.I),
    re.compile(r"pagesession\.(host_ok|forwarded)\b"),
    re.compile(r"from orch\.pagesession import[^\n]*\b(host_ok|forwarded)\b"),
)
SCAN = ("workspace/src", "workspace-addons")
SKIP_PARTS = {"tests", "mockup", "node_modules", ".venv", "__pycache__"}


def test_no_same_computer_limit_is_left_in_the_product():
    bad = []
    for top in SCAN:
        for f in (REPO / top).rglob("*"):
            if not f.is_file() or SKIP_PARTS & set(f.relative_to(REPO).parts):
                continue
            if f.suffix not in (".py", ".js", ".html", ".md", ".toml", ".json"):
                continue
            text = f.read_text(errors="replace")
            bad += [f"{f.relative_to(REPO)}: {p.pattern}" for p in FORBIDDEN if p.search(text)]
    assert bad == [], bad

"""Every data read of Insights needs the sign-in, this computer's own address too (ORCH-481, owner 18 Nov).

Its own session cookie, or the dashboard's word for a signed-in person in front of it. Only the page shell and its
program files open without it."""

import inspect
import re

import pytest
from conftest import FakeSession
from test_overview import request

from orch_insights import server

pytestmark = pytest.mark.real_signin


def _api_reads():
    """Every /api/ address Insights reads, taken from its own GET code (a new one is covered by itself)."""
    src = inspect.getsource(server.Handler.do_GET)
    found = set(re.findall(r'"(/api/[a-z/-]+)"', src))
    found |= {"/api/list/skills", "/api/checkup/p_abcdef"}
    return sorted(found)


READS = _api_reads()


@pytest.mark.parametrize("with_session", [False, True])
@pytest.mark.parametrize("name", ["127.0.0.1", "localhost"])
def test_no_read_on_this_computer_without_the_sign_in(start_server, fake_session, name, with_session):
    srv = start_server(session=fake_session if with_session else None)
    port = srv.server_address[1]
    assert "/api/overview" in READS and "/api/settings" in READS
    for path in READS:
        for extra in ({}, {"Sec-Fetch-Site": "same-origin"}):
            code, _, body = request(srv, path, headers={"Host": f"{name}:{port}", **extra})
            assert code == 401, (path, extra, code)
            assert body.decode().startswith("Sign in to ")


def test_reads_work_with_the_own_cookie_or_the_dashboards_word(start_server, fake_session):
    srv = start_server(session=fake_session)
    cookie = {"Cookie": f"orch_page_insights_{srv.server_address[1]}={FakeSession.cookie}"}
    assert request(srv, "/api/overview", headers=cookie)[0] == 200
    assert request(srv, "/api/overview", headers={"X-Orch-Reader": FakeSession.read_vouch})[0] == 200
    assert request(srv, "/api/overview", headers={"X-Orch-Person": FakeSession.vouch})[0] == 200
    assert request(srv, "/api/overview", headers={"X-Orch-Reader": "x" * 44})[0] == 401
    bad = {"Cookie": f"orch_page_insights_{srv.server_address[1]}=old-cookie"}
    assert request(srv, "/api/overview", headers=bad)[0] == 401


def test_the_page_shell_opens_without_the_sign_in(start_server, fake_session):
    srv = start_server(session=fake_session)
    assert request(srv, "/")[0] == 200
    assert request(srv, "/web/insights.js")[0] == 200

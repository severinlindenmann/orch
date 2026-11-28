"""cardtext (card fragments, server address) and cli_screen (reserved run command)."""

import argparse

import pytest

from orch import cardtext, cli, cli_screen
from orch.errors import Refused


def test_part_one_line_quotes_and_cap():
    assert cardtext.part('a\n  "b"\t\u201cc\u201d') == "a 'b' 'c'"
    assert cardtext.part(None) == ""
    out = cardtext.part("x" * 200)
    assert out == "x" * 120 + "\u2026"
    assert cardtext.part("{value}") == "{value}"


def test_tail_keeps_the_end():
    assert cardtext.tail("/a/b") == "/a/b"
    out = cardtext.tail("/head/" + "d" * 100 + "/real/folder", 20)
    assert out.startswith("\u2026") and out.endswith("/real/folder") and len(out) == 21


@pytest.mark.parametrize(
    "url,want",
    [("https://relay.example.com", "relay.example.com"), (" https://h.example:8443/x ", "h.example:8443")],
)
def test_server_address(url, want):
    assert cardtext.server_address(url) == want


@pytest.mark.parametrize(
    "url,msg",
    [
        ("https://user:pw@h.example", cardtext.NO_USERINFO),
        ("https://user@h.example", cardtext.NO_USERINFO),
        ("", "That is not a server address."),
        ("https://h.example:notaport", "That is not a server address."),
    ],
)
def test_server_address_refused(url, msg):
    with pytest.raises(Refused) as exc:
        cardtext.server_address(url)
    assert str(exc.value) == msg


def test_screen_dispatch_ignores_other_commands(tmp_path):
    assert cli_screen.dispatch(argparse.Namespace(cmd="ticket", sub="type"), tmp_path) is False
    assert cli_screen.dispatch(argparse.Namespace(cmd="run", sub="other"), tmp_path) is False


def test_run_type_refused_with_next_step(proj, capsys):
    before = sorted(proj.rglob("*"))
    assert cli.main(["run", "type", "hello"]) == 2
    err = capsys.readouterr().err
    assert "not built yet" in err and "orch run --help" in err
    assert sorted(proj.rglob("*")) == before

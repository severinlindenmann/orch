"""Reserved commands refuse, with no side effects."""

import pytest

from orch import cli

PAIRS = [  # `record delete-detail` is built (test_insights_settings.py)
    ("job", "run"),
    ("conn", "list"),
    ("conn", "show"),
    ("conn", "allow"),
    ("run", "screen"),
    ("run", "type"),
]


@pytest.mark.parametrize("group,sub", PAIRS)
def test_stubs(proj, capsys, group, sub):
    before = sorted(proj.rglob("*"))
    assert cli.main([group, sub, "value"]) == 2
    assert "not built yet" in capsys.readouterr().err
    assert sorted(proj.rglob("*")) == before


@pytest.mark.parametrize("flag", ["--help", "--help-all"])
def test_hidden(proj, capsys, flag):
    with pytest.raises(SystemExit) as exc:
        cli.main([flag])
    assert exc.value.code == 0
    words = capsys.readouterr().out.split()
    assert not set(words) & {"secret", "record", "job", "conn"}


@pytest.mark.parametrize("group", ["record", "job", "conn"])
def test_no_subcommand_lists_them(proj, capsys, group):
    assert cli.main([group]) == 2
    err = capsys.readouterr().err
    assert (
        ("not built yet" in err or group in ("record", "job")) and "Subcommands:" in err and "None" not in err
    )

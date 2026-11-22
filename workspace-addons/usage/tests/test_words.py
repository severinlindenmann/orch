"""Small words found in the clean e2e of Usage (ORCH-931): ordinals, help lines, plain refusals, the On/Off label."""

import re
from pathlib import Path

import pytest
from conftest import jrun

from orch_usage import share
from orch_usage.cli import main


@pytest.mark.parametrize(
    "n,word",
    [
        (1, "1st"),
        (2, "2nd"),
        (3, "3rd"),
        (4, "4th"),
        (11, "11th"),
        (12, "12th"),
        (13, "13th"),
        (21, "21st"),
        (22, "22nd"),
        (111, "111th"),
    ],
)
def test_ordinal(n, word):
    assert share.ordinal(n) == word


def test_save_preset_says_every_2nd(cli, no_switcher):
    code, d = jrun(cli, "share", "--preset", "save")
    text = " ".join(d["counts"])
    assert code == 0 and "every 2nd Code start" in text and "2th" not in text


def test_help_has_one_line_per_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for cmd in (
        "list",
        "needs",
        "seen",
        "history",
        "limit",
        "period",
        "order",
        "on",
        "off",
        "end",
        "share",
        "switching",
        "run",
        "start",
        "stop",
        "status",
    ):
        assert re.search(rf"^\s+{cmd}\s+\S", out, re.MULTILINE), cmd
    assert "SUPPRESS" not in out and "{list," not in out


@pytest.mark.parametrize(
    "argv,words",
    [
        (["seen", "nonsense"], '"nonsense" is not a warning here. Use one of: all-at-limit, switch-failed.'),
        (["frob"], '"frob" is not an orch usage command. Run orch usage --help.'),
        (["limit"], "missing account, value"),
    ],
)
def test_wrong_words_are_refused_plainly(ws, capsys, argv, words):
    with pytest.raises(SystemExit) as e:
        main(argv)
    err = capsys.readouterr().err
    assert e.value.code == 2 and words in err and err.startswith("Refused:")
    assert "invalid choice" not in err and "error:" not in err


def test_the_on_label_follows_the_switch():
    js = (Path(__file__).resolve().parents[1] / "src/orch_usage/web/usage.js").read_text(encoding="utf-8")
    assert "text: 'On'}), on)" not in js  # never a fixed On next to the switch
    assert "a.on ? 'On' : 'Off'" in js and "on.checked ? 'On' : 'Off'" in js


def test_today_says_the_same_word_as_the_account():
    """ORCH-1468: TEAMCO said 'Over its limit' under Subscriptions and 'Skipped' under Today: one word per account."""
    js = (Path(__file__).resolve().parents[1] / "src/orch_usage/web/usage.js").read_text(encoding="utf-8")
    assert "STATE[model.accounts.find(a => a.id === s.id)?.state]" in js
    assert "h('span', {className: 'pill', text: 'Skipped'})" not in js

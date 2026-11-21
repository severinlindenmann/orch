"""ORCH-793: subcommands added with help=SUPPRESS must not print "==SUPPRESS==" in any --help screen."""

import argparse

import pytest

from orch import cli


def _all_parsers(parser, path=("orch",)):
    yield path, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                yield from _all_parsers(child, (*path, name))


@pytest.mark.parametrize("show_all", [False, True])
def test_no_help_screen_prints_the_hidden_marker(show_all):
    bad = [
        " ".join(path)
        for path, p in _all_parsers(cli.build_parser(show_all))
        if "==SUPPRESS==" in p.format_help()
    ]
    assert bad == []


def test_secret_help_leaves_hidden_subcommands_out():
    p = cli.build_parser()
    secret = p._subparsers._group_actions[0].choices["secret"]
    text = secret.format_help()
    assert "==SUPPRESS==" not in text
    assert "    scan " not in text  # hidden, not listed with a blank description
    ns = p.parse_args(["secret", "scan"])  # still runs
    assert ns.sub == "scan"

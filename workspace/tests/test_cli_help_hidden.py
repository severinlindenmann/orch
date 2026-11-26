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


@pytest.mark.parametrize(
    "argv", ["ticket list --all", "ticket show WS-1", "needs --json", "doctor pass --dry-run", "counts"]
)
def test_everyday_branch_parses_like_the_full_cli(argv):
    words = argv.split()
    quick, full = cli.build_parser(command=words[0]), cli.build_parser()
    assert quick.parse_args(words) == full.parse_args(words)
    assert cli.nextstep.leaf_path(quick, quick.parse_args(words)) == cli.nextstep.leaf_path(
        full, full.parse_args(words)
    )


@pytest.mark.parametrize("show_all", [False, True])
def test_help_starts_with_the_two_everyday_examples(show_all):
    """ORCH-1936: a person sees how to list tickets and what needs them before the command list."""
    text = cli.build_parser(show_all).format_help()
    head, catalogue = text.split("positional arguments:", 1)
    assert "Examples, inside a workspace:" in head
    assert "See your tickets: orch ticket list" in head
    assert "See what needs your answer: orch needs" in head
    assert all(len(line) <= 40 for line in head.splitlines()[2:])  # readable on a narrow terminal
    assert ("    update " in catalogue) is show_all  # normal and --help-all lists stay as they were
    p = cli.build_parser(show_all)
    assert p.parse_args(["ticket", "list"]).sub == "list"
    assert p.parse_args(["needs"]).cmd == "needs"

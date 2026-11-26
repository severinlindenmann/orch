"""AGENTS.md R1.1 / R1.2 / R7.5: in a fresh workspace no help screen names relay, publish, phone, an add-on
package, or a "never use" word of docs/wording.md."""

import argparse
import importlib.util
import re

import pytest
from test_core_names_no_addon import ADDONS, ROOT

from orch import cli

_spec = importlib.util.spec_from_file_location("wording_lint", ROOT / "brand/tests/test_wording.py")
wording = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wording)

# `orch_<addon>` package names and hyphenated add-on names (plain words like "usage" are ordinary English)
ADDON_NAMES = {f"orch_{n}" for n in ADDONS} | {n for n in ADDONS if "-" in n}
SEAMS = re.compile(r"relay|publish|phone", re.I)


def _screens(parser, path=("orch",)):
    yield " ".join(path), parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            # top level: only what `orch --help-all` lists; hidden commands, relay, publish and the
            # not-yet-built ones are not shown in a fresh workspace (R1.1)
            listed = {a.dest for a in action._choices_actions} if len(path) == 1 else None
            for name, child in action.choices.items():
                if listed is None or name in listed:
                    yield from _screens(child, (*path, name))


@pytest.fixture(scope="module", params=[False, True], ids=["help", "help-all"])
def screens(request, tmp_path_factory):
    # nothing is turned on: the parser is built from the code alone, no workspace state is read
    return [(n, q.format_help()) for n, q in _screens(cli.build_parser(request.param))]


def test_every_screen_is_found(screens):
    names = {n for n, _ in screens}
    assert {"orch", "orch ticket", "orch ticket list"} <= names


def test_no_help_screen_names_an_addon_or_a_seam(screens):
    bad = []
    for name, text in screens:
        bad += [f"{name}: {m.group()}" for m in SEAMS.finditer(text)]
        bad += [f"{name}: {n}" for n in ADDON_NAMES if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text)]
    assert not bad, "R1.1/R1.2: help names an add-on or an optional part:\n" + "\n".join(sorted(set(bad)))


def test_no_help_screen_uses_a_never_word(screens):
    bad = []
    for name, text in screens:
        # `agent:<tool>` is the actor key the CLI keeps (docs/wording.md), not the screen word
        # the command and flag names `agents`, `config agent` and `--agent` are CLI words too
        text = re.sub(r"agent:<tool>|--agent\b|orch agents|orch config agent|^\s+agents?\s{2,}", "", text, flags=re.M)
        words = wording.never_words(text)
        bad += [f"{name}: {w}" for w in words]
    assert not bad, "R7.5: words from docs/wording.md 'never use' in help:\n" + "\n".join(sorted(set(bad)))

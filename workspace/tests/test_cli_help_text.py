"""Every help screen: 1-2 examples that parse, the next step, one word per thing (R2.7, R7.5), and no relay or
publish anywhere until it is on (R1.1)."""

import argparse
import importlib.util
import re
import shlex
from pathlib import Path

import pytest
from conftest import turn_on

from orch import addons, cli, helptext

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("orch_wording", ROOT / "brand/tests/test_wording.py")
wording = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wording)

ALL_ON = frozenset(addons.CORE_ADDONS)
NAMES = re.compile(r"(?<![A-Za-z_-])(relay|publish)(?![A-Za-z_])", re.I)


def _screens(show_all=True, on=ALL_ON):
    """(path, parser, shown): every help screen; shown = a person can find it in a help list."""
    out = []

    def walk(p, path, shown):
        out.append((path, p, shown))
        sp = next((a for a in p._actions if isinstance(a, argparse._SubParsersAction)), None)
        if sp is None:
            return
        listed = {a.dest for a in sp._choices_actions}
        seen = set()
        for name, child in sp.choices.items():
            if id(child) in seen:
                continue
            seen.add(id(child))
            # relay and publish are never listed among the commands; they are add-ons, shown once on
            in_list = name in listed or (not path and name in on)
            walk(child, f"{path} {name}".strip(), shown and in_list)

    walk(cli.build_parser(show_all, on=on), "", True)
    return out


def test_every_listed_screen_has_examples_and_a_next_step():
    screens = [(path, p) for path, p, shown in _screens() if shown and path]
    assert len(screens) > 150 and any(path == "relay send" for path, _ in screens)
    bad = []
    for path, p in screens:
        text = p.format_help()
        ex = re.search(r"\nExamples:\n((?:  orch .*\n)+)", text)
        n = len(ex.group(1).splitlines()) if ex else 0
        if not 1 <= n <= 2 or "\nNext step: " not in text:
            bad.append(path)
    assert not bad, f"add them to orch/helptext.py EXAMPLES (1-2 each): {bad}"


def test_top_help_shows_examples_and_the_next_step():
    text = cli.build_parser().format_help()
    assert "See your tickets: orch ticket list" in text
    assert 'Next step: orch init  (in a new folder), then orch ticket new "<title>"' in text


def test_every_example_is_a_real_command_of_its_screen():
    parser = cli.build_parser(True, on=ALL_ON)
    paths = {path for path, _, _ in _screens()}
    assert set(helptext.EXAMPLES) <= paths, set(helptext.EXAMPLES) - paths
    for path, examples in helptext.EXAMPLES.items():
        assert 1 <= len(examples) <= 2, path
        for line in examples:
            argv = shlex.split(line.partition(" < ")[0])
            assert argv[0] == "orch" and " ".join(argv[1:]).startswith(path), line
            try:
                parser.parse_args(argv[1:])
            except SystemExit:
                pytest.fail(f"{path}: the example does not parse: {line}")
            assert len(f"  {line}") <= 100, line


@pytest.mark.parametrize("show_all", [False, True])
def test_no_help_names_relay_or_publish_while_they_are_off(show_all):
    bad = []
    for path, p, _ in _screens(show_all, on=frozenset()):
        if path.split(" ")[0] in addons.CORE_ADDONS:
            continue  # their own help is reachable only once they are on
        bad += [f"orch {path}: {m.group(0)}" for m in NAMES.finditer(p.format_help())]
    assert not bad, bad


def test_relay_options_come_back_once_the_relay_is_on():
    off = _screens(on=frozenset())
    on = _screens(on=frozenset({"relay"}))
    ask_off = next(p for path, p, _ in off if path == "ask").format_help()
    ask_on = next(p for path, p, _ in on if path == "ask").format_help()
    assert "--phone" not in ask_off and "--phone" in ask_on
    top_on = next(p for path, p, _ in on if path == "").format_help()
    assert "relay" not in next(p for path, p, _ in off if path == "").format_help()
    assert "publish" not in top_on  # only the add-on that is on
    assert cli.build_parser(on=frozenset()).parse_args(["ask", "WEB-1", "q", "--phone"]).phone  # still runs


def test_help_uses_one_word_per_thing():
    """docs/wording.md: no never-use word in any help screen. Command names (`orch agents`,
    `orch config agent`) and values (`agent:<tool>`, `--agent`) stay as they are."""
    names = re.compile(r"(?m)orch (config )?agents?\b|^ {4}agents?(?= )")
    bad = []
    for path, p, _ in _screens():
        text = names.sub("", p.format_help())
        hits = [m.group(0) for rx in (wording.WORD, wording.LOWER) for m in rx.finditer(text)]
        bad += [f"orch {path}: {h}" for h in hits]
    assert not bad, bad


def _help(run, capsys, *argv):
    with pytest.raises(SystemExit) as e:
        run(*argv, "--help")
    assert e.value.code == 0
    return capsys.readouterr().out


def test_main_shows_relay_help_only_once_it_is_on(proj, run, capsys):
    out = _help(run, capsys, "ask")
    assert "--phone" not in out and "Examples:\n  orch ask " in out and "Next step: " in out
    turn_on(proj, "relay")
    assert "--phone" in _help(run, capsys, "ask")
    assert "Examples:\n  orch relay send " in _help(run, capsys, "relay", "send")

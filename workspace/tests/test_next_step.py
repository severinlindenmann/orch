"""AGENTS.md R2.7: every orch command ends with a `Next:` line (one table: orch/nextstep.py)."""

import argparse
import json
import re

from orch import addons, cli, nextstep


def _leaves():
    top = cli.build_parser(show_all=True)
    out = []

    def walk(p, path):
        subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            out.append(" ".join(path))
            return
        for s in subs:
            helps = {a.dest: a.help for a in s._choices_actions}
            for name, sp in s.choices.items():
                # top level: hidden commands were removed from the list, except the built-in add-ons
                # (listed only when on, but real commands); below it: hidden means help=SUPPRESS
                if helps.get(name) == argparse.SUPPRESS:
                    continue
                if not path and name not in helps and name not in addons.CORE_ADDONS:
                    continue
                walk(sp, [*path, name])

    walk(top, [])
    return out


def test_every_visible_command_has_a_next_step_or_a_reason():
    leaves = _leaves()
    assert "ticket new" in leaves and "relay send" in leaves
    missing = [p for p in leaves if p not in nextstep.EXEMPT and nextstep.entry(p) is None]
    assert not missing, f"add them to nextstep.HINTS (or EXEMPT with a reason): {missing}"
    assert all(nextstep.EXEMPT.values()) and len(nextstep.EXEMPT) <= 3


def _last(out):
    lines = [x for x in out.strip().splitlines() if x]
    return lines[-1] if lines else ""


def test_flow_every_output_ends_with_a_next_line(proj, run):
    run("init", "--yes")
    t1 = json.loads(run("ticket", "new", "Do it", "--json")[1])["key"]
    steps = [
        ("ticket", "new", "Another"),
        ("check", "add", t1, "step one"),
        ("check", "add", t1, "step two"),
        ("check", "done", t1, "c1", "--note", "ok"),
        ("check", "done", t1, "c2", "--note", "ok"),
        ("ticket", "summary", t1, "all done"),
        ("ticket", "status", t1, "active"),
        ("ticket", "list"),
        ("ticket", "show", t1),
        ("ask", t1, "Which one?", "--option", "a", "--option", "b", "--recommend", "a"),
        ("wait", t1, "--on", "external:x"),
        ("needs",),
    ]
    seen = []
    for argv in steps:
        code, out, err = run(*argv)
        assert code == 0, (argv, out, err)
        line = _last(out)
        assert line.startswith("Next: "), (argv, out)
        seen.append(line)
        m = re.search(r"orch ([a-z-]+)", line)
        if m:
            assert m.group(1) in ("ticket", "check", "needs", "addon", "review", "init", "stop"), line
    assert "orch check add" in seen[0]
    assert "orch check done" in seen[1] and "orch check done" in seen[2]  # after check add
    assert "orch check done" in seen[3]  # one task is still open
    assert "orch ticket summary" in seen[4]  # all tasks done, no summary yet
    assert re.search(r"orch ticket status \S+ done", seen[5])  # summary written


def test_json_shape_is_unchanged(proj, run):
    run("init", "--yes")
    run("ticket", "new", "Do it")
    code, out, _ = run("ticket", "list", "--json")
    assert code == 0 and "Next:" not in out


def test_fresh_init_core_next_lines_name_no_part(proj, run):
    bad = re.compile(r"relay|publish|phone|automation|dashboard|sync|focus|insights", re.I)
    t1 = None
    for argv in (
        ("init", "--yes"),
        ("ticket", "new", "x"),
        ("ticket", "list"),
        ("ticket", "show", "T1"),
        ("check", "add", "T1", "s"),
        ("addon", "list"),
        ("needs",),
        ("status",),
        ("diag", "query"),
    ):
        argv = tuple(t1 if a == "T1" else a for a in argv)
        code, out, err = run(*argv)
        if argv[:2] == ("ticket", "new"):
            t1 = re.search(r"Created (\S+)", out).group(1)
        nxt = [x for x in out.splitlines() if x.startswith("Next:")]
        assert not any(bad.search(x) for x in nxt), (argv, nxt)

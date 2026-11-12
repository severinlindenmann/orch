"""ONE rule decides how a ticket's person fields show (orch.history, contracts/history.md). Readers never read
a ticket's `history`, an evidence entry's `by`, or test a value for "human:" themselves: they take
history.lines / shown_ticket / shown_json / is_person_line. This lint keeps it that way. The allowlist names
the WRITERS (the append points, merge and sync code that must see the stored bytes) and readers that read no
author, each with its reason; a new entry needs the same."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OWNER = "workspace/src/orch/history.py"

# (file, innermost function) -> why it may read the raw field
ALLOW = {
    # writers: core's append points and the one write path
    ("workspace/src/orch/tickets.py", "add_history"): "THE history-append point",
    ("workspace/src/orch/tickets.py", "_sign_done"): "signs the line its own op just appended",
    ("workspace/src/orch/chat.py", "copy_history"): "writer: sets the time of the line add_history just made",
    # readers that read no author
    ("workspace/src/orch/tickets.py", "attach"): "writer: is the line already there (its text only)",
    ("workspace/src/orch/workcheck.py", "last_event"): "timestamps only",
    ("workspace/src/orch/phone_view.py", "phone_proof"): "evidence files for the phone, no author",
    ("workspace/src/orch/tickets.py", "trim_runs"): "writer: caps recorded runs",
    # add-ons that read tickets from orch's CLI JSON (already shown by cli._out -> history.shown_json)
    ("workspace-addons/focus/src/orch_focus/server.py", "_shape"): "CLI JSON (shown); passed to the page",
    (
        "workspace-addons/focus/src/orch_focus/server.py",
        "tickets_list",
    ): "CLI JSON (shown); closing time only",
    ("workspace-addons/automation/src/orch_automation/loop.py", "others"): "CLI JSON (shown); counts lines",
    ("workspace-addons/automation/src/orch_automation/needs.py", "rows"): "CLI JSON (shown); orchcli.person",
    # the dashboard: data.shown is the one entry (core rule, fail closed without the core)
    (
        "workspace-addons/dashboard/src/orch_dashboard/data.py",
        "_demote_all",
    ): "fail-closed demotion without core",
    ("workspace-addons/dashboard/src/orch_dashboard/data.py", "load_general"): "reads data.shown(...)",
    (
        "workspace-addons/dashboard/src/orch_dashboard/data.py",
        "_mark_missing_proofs",
    ): "file marks, no author",
    ("workspace-addons/dashboard/src/orch_dashboard/data.py", "add_artifact_marks"): "links, no author",
    (
        "workspace-addons/dashboard/src/orch_dashboard/mobile.py",
        "mark_chat_history",
    ): "shown ticket (data.shown)",
}
# (file, function) -> why it may read a step/ref/plan `by` or another person field (answered_by, wont_by,
# person, description_by) raw. History reads stay under ALLOW.
PERSON_OK = {
    (
        "workspace/src/orch/adapters.py",
        "render",
    ): "v['person'] is the adapter's template value, not a ticket's",
    (
        "workspace/src/orch/humanproof.py",
        "wont_decision",
    ): "proof code: the bytes a person's decision MAC covers",
    ("workspace/src/orch/relay.py", "_answer_by"): "a relay message's body (its own rule), not a ticket",
    (
        "workspace/src/orch/relay.py",
        "_applied_ticket",
    ): "writer check: did this message's own answer land (compares stored bytes, shows nothing)",
    (
        "workspace/src/orch/tickets.py",
        "_wont_view",
    ): "writer guard: the stored Won't do state before/after an op",
}
# (file, function) -> readers that take the shown ticket at their entry (history.shown_ticket / shown_json /
# shown_item, checked below) and read person fields of THAT: the reason says which.
SHOWN = {
    ("workspace/src/orch/runs.py", "fresh_prompt"): "ticket = history.shown_ticket(...) first",
    ("workspace/src/orch/cli.py", "_show"): "t = history.shown_ticket(...) first",
    (
        "workspace/src/orch/relay.py",
        "apply_allow_answers",
    ): "t = history.shown_ticket(...); `raw` only for the proof (history.answer_proven)",
}
SHOWN_CALLS = ("shown_ticket", "shown_json", "shown_item")
# The sync add-on is the merge authority: it reads and writes stored bytes by design (its readers of person
# fields are the merge rules in merge.py, vector-tested); every module of it is a writer here.
WRITER_TREES = ("workspace-addons/sync/src/",)


def _sources():
    yield from sorted((REPO / "workspace/src/orch").rglob("*.py"))
    yield from sorted(REPO.glob("workspace-addons/*/src/**/*.py"))


def _const(node, value) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


def _key_read(node, key) -> bool:
    """`x[key]` (load) or `x.get(key, ...)`."""
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        return _const(node.slice, key)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and bool(node.args)
        and _const(node.args[0], key)
    )


def _strip(node):
    """str(x) -> x"""
    while (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str" and node.args
    ):
        node = node.args[0]
    return node


def _by_names(func) -> set[str]:
    """Names assigned from an entry's `by` in this function (also `by, via = str(e.get("by")), ...`)."""
    names = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            pairs = (
                zip(target.elts, node.value.elts, strict=False)
                if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple)
                else [(target, node.value)]
            )
            for t, v in pairs:
                if isinstance(t, ast.Name) and any(_key_read(x, "by") for x in ast.walk(v)):
                    names.add(t.id)
    return names


def _human_test(node, by_names) -> bool:
    """`<an entry's by>.startswith("human:")` (or a tuple holding a "human..." literal): a stored value
    believed as the person. The command's own actor (args.by, a `by` parameter) is not an entry's."""
    if not (
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "startswith"
    ):
        return False
    if not node.args:
        return False
    arg = node.args[0]
    values = arg.elts if isinstance(arg, ast.Tuple) else [arg]
    if not any(
        isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value.startswith("human")
        for v in values
    ):
        return False
    recv = _strip(node.func.value)
    return _key_read(recv, "by") or (isinstance(recv, ast.Name) and recv.id in by_names)


def _evidence_names(func) -> set[str]:
    """Names bound by iterating something that reads `evidence` (for loops and comprehensions)."""
    names = set()
    for node in ast.walk(func):
        pairs = []
        if isinstance(node, ast.For):
            pairs = [(node.target, node.iter)]
        elif isinstance(node, ast.comprehension):
            pairs = [(node.target, node.iter)]
        for target, it in pairs:
            if any(_key_read(x, "evidence") for x in ast.walk(it)) and isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _names(target) -> set[str]:
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _item_names(func, keys) -> set[str]:
    """Names bound from something that reads one of `keys`: loop and comprehension targets over it, and
    plain assignments from it (`plan = t.get("plan")`, `step = next(c for c in t["checklist"] ...)`)."""
    names = set()
    for node in ast.walk(func):
        pairs = []
        if isinstance(node, (ast.For, ast.comprehension)):
            pairs = [(node.target, node.iter)]
        elif isinstance(node, ast.Assign):
            pairs = [(t, node.value) for t in node.targets]
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            pairs = [(node.target, node.value)]
        for target, it in pairs:
            if any(_key_read(x, k) for x in ast.walk(it) for k in keys):
                names |= _names(target)
    return names


# Person fields with their own key: any read of them is a person read.
PERSON_KEYS = ("answered_by", "wont_by", "person", "description_by")
# `by` is a person field on these items (history and evidence have their own rules above).
BY_ITEMS = ("refs", "plan", "checklist")


def violations(path: Path, repo: Path = REPO) -> list[str]:
    rel = path.relative_to(repo).as_posix()
    if rel == OWNER or rel.startswith(WRITER_TREES):
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    owner: dict[int, ast.AST] = {}
    for f in funcs:  # innermost function wins (walk order: outer first, inner later)
        for n in ast.walk(f):
            owner[id(n)] = f
    by_names = {id(f): _by_names(f) for f in funcs}
    for node in ast.walk(tree):
        scope = owner.get(id(node))
        name = scope.name if scope is not None else "<module>"
        if (rel, name) in ALLOW:
            continue
        if _key_read(node, "history"):
            out.append(f"{rel}:{node.lineno} {name}: reads `history` (use history.lines / shown_ticket)")
        elif _human_test(node, by_names.get(id(scope), set())):
            out.append(f"{rel}:{node.lineno} {name}: tests for 'human:' (use history.is_person_line)")
    for f in funcs:
        if (rel, f.name) in ALLOW:
            continue
        person_ok = (rel, f.name) in PERSON_OK or (rel, f.name) in SHOWN
        ev = _evidence_names(f)
        items = _item_names(f, BY_ITEMS)
        for node in ast.walk(f):
            if owner.get(id(node)) is not f:
                continue  # an inner function is checked (and allowlisted) on its own
            if any(_key_read(node, k) for k in PERSON_KEYS):
                if not person_ok:
                    out.append(f"{rel}:{node.lineno} {f.name}: reads a person field raw (use shown_ticket)")
            elif _key_read(node, "by"):
                target = node.value if isinstance(node, ast.Subscript) else node.func.value
                if isinstance(target, ast.Name) and target.id in ev:
                    out.append(f"{rel}:{node.lineno} {f.name}: reads an evidence `by` (use shown_ticket)")
                elif not person_ok and (
                    (isinstance(target, ast.Name) and target.id in items)
                    or any(_key_read(target, k) for k in BY_ITEMS)
                ):
                    out.append(f"{rel}:{node.lineno} {f.name}: reads a step/ref/plan `by` (use shown_ticket)")
    return out


def test_no_reader_reads_person_fields_raw():
    found = [v for p in _sources() for v in violations(p)]
    assert not found, "\n".join(found)


def test_allowlist_has_no_stale_entries():
    """Every allowlisted function exists (a renamed one must not keep a hole open)."""
    missing = []
    for rel, name in (*ALLOW, *PERSON_OK, *SHOWN):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        if not any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name for n in ast.walk(tree)
        ):
            missing.append(f"{rel}:{name}")
    assert not missing, missing


def test_shown_readers_take_the_shown_ticket():
    """A SHOWN entry reads person fields only because it calls history.shown_* itself."""
    wrong = []
    for rel, name in SHOWN:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        f = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        if not any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in SHOWN_CALLS
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "history"
            for n in ast.walk(f)
        ):
            wrong.append(f"{rel}:{name}")
    assert not wrong, wrong


def test_the_lint_catches_each_kind(tmp_path):
    src = tmp_path / "bad.py"
    src.write_text(
        "def a(t):\n    return t['history'][-1]\n"
        "def b(t):\n    return t.get('history')\n"
        "def c(h):\n    return str(h.get('by')).startswith('human:')\n"
        "def d(c):\n    return [ev.get('by') for ev in c.get('evidence', [])]\n"
        "def e(c):\n    for ev in c['evidence']:\n        print(ev['by'])\n",
        encoding="utf-8",
    )
    found = violations(src, tmp_path)
    assert len(found) == 5, found


def test_the_lint_catches_every_person_field(tmp_path):
    src = tmp_path / "bad.py"
    src.write_text(
        "def a(q):\n    return q['answered_by']\n"
        "def b(c):\n    return c.get('wont_by')\n"
        "def c(v):\n    return v.get('person')\n"
        "def d(t):\n    return t['description_by']\n"
        "def e(t):\n    return [r.get('by') for r in t.get('refs') or []]\n"
        "def f(t):\n    for i, c in enumerate(t['checklist']):\n        print(c['by'])\n"
        "def g(t):\n    return t['plan']['by']\n"
        "def h(t):\n    plan = t.get('plan') or {}\n    return plan.get('by')\n"
        "def i(t):\n    step = next(c for c in t['checklist'])\n    return step.get('by')\n"
        "def ok(t, args):\n    return args.by, t.get('by'), [h for h in t.get('items', [])]\n",
        encoding="utf-8",
    )
    found = violations(src, tmp_path)
    assert len(found) == 9, found
    assert not [v for v in found if " ok:" in v], found

"""#539: every route of the page servers (dashboard, Focus, Insights) that mints a proof or acts with the page
session goes through the ONE rule, PageSession.authed / can_mint (cookie + page secret). This test enumerates
the gate calls of each server by AST, so a new route that checks the cookie some other way, or a new gate in
an unexpected handler, fails here and must be added to the list on purpose."""

import ast
from pathlib import Path

import pytest

ADDONS = Path(__file__).resolve().parents[2] / "workspace-addons"
SERVERS = {
    "dashboard": ADDONS / "dashboard/src/orch_dashboard/server.py",
    "focus": ADDONS / "focus/src/orch_focus/server.py",
    "insights": ADDONS / "insights/src/orch_insights/server.py",
}
# (enclosing method, gate) pairs: the complete list of places a server asks the session.
EXPECTED = {
    "dashboard": {
        ("do_GET", "authed"),  # /api/notices, /api/update-status (twice)
        ("do_POST", "can_mint"),  # /api/act (every op, handoff.confirm/dismiss, notice.ack), proxied act
        ("do_POST", "mint"),  # the callable handed down ONLY when can_mint passed
        ("_session_post", "launch"),
    },
    "focus": {
        ("_area_op", "can_mint"),  # area.accept / area.remove
        ("do_POST", "can_mint"),  # /api/act
        ("do_POST", "mint"),  # the callable handed down ONLY when can_mint passed
        ("_session_post", "launch"),
    },
    "insights": {
        ("_can_act", "can_mint"),  # settings view flag and every /api/act click
        ("_act", "mint"),  # handed down ONLY when _can_act() passed
        ("_session_post", "launch"),
    },
}
GATES = {"authed", "can_mint", "launch", "mint"}


def _gates(path: Path) -> tuple[set, list[str]]:
    tree = ast.parse(path.read_text())
    found, bad = set(), []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            is_attr = isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
            if is_attr and node.attr in GATES and node.value.attr == "session":
                found.add((fn.name, node.attr))
            # nobody compares the cookie by hand or reads the session secret/cookie outside the core
            if isinstance(node, ast.Attribute) and node.attr in ("cookie", "secret") and (
                isinstance(node.value, ast.Attribute) and node.value.attr == "session"
            ):
                bad.append(f"{fn.name}:{node.lineno} reads session.{node.attr}")
            if isinstance(node, ast.Constant) and node.value in ("Cookie", "X-Orch-Page"):
                bad.append(f"{fn.name}:{node.lineno} reads the {node.value} header")
    return found, bad


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_every_session_gate_is_the_one_rule(name):
    found, bad = _gates(SERVERS[name])
    assert found == EXPECTED[name], f"{name}: gate calls changed: {sorted(found ^ EXPECTED[name])}"
    # the only session value a handler may read is the secret to hand to the page in the /session answer
    assert [b for b in bad if "secret" not in b or "_session_post" not in b] == [], bad


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_no_server_mints_without_asking_the_session_rule(name):
    """run_with_proof / .mint( may only be reached in a function that also asks authed/can_mint (directly or
    via the `mint` callable handed down from a can_mint check)."""
    tree = ast.parse(SERVERS[name].read_text())
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        if "run_with_proof" in names or ("mint" in names and "session" in names):
            guarded = names & {"can_mint", "authed", "_can_act"}
            assert guarded, f"{name}.{fn.name} mints unguarded"

"""#539: every route of the page servers (dashboard, Focus, Insights) that acts with the page
session goes through the ONE rule, PageSession.authed / can_act (cookie + page secret). This test enumerates
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
        ("_can_act", "can_act"),  # /api/act (every op, update.start), update status, typing, report, vouching
        ("_signed_in", "cookie_ok"),  # READS under a host name that is not this computer's (a proxy in front)
        ("_session_post", "launch"),
    },
    "focus": {
        ("_area_op", "can_act"),  # area.accept / area.remove
        ("do_POST", "can_act"),  # /api/act
        ("_fence", "cookie_ok"),  # any host name once signed in
        ("_session_post", "launch"),
    },
    "insights": {
        ("_can_act", "can_act"),  # settings view flag and every /api/act click
        ("_can_act", "vouched"),  # behind the dashboard: its word for the person
        ("_fence", "cookie_ok"),  # any host name once signed in
        ("_session_post", "launch"),
    },
}
GUARDS = {"authed", "can_act", "launch", "cookie_ok", "vouched"}


def _gates(path: Path) -> tuple[set, list[str]]:
    tree = ast.parse(path.read_text())
    found, bad = set(), []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            is_attr = isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
            if is_attr and node.attr in GUARDS and node.value.attr == "session":
                found.add((fn.name, node.attr))
            # nobody compares the cookie by hand or reads the session secret/cookie outside the core
            if (
                isinstance(node, ast.Attribute)
                and node.attr in ("cookie", "secret")
                and (isinstance(node.value, ast.Attribute) and node.value.attr == "session")
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
def test_no_server_still_mints_a_proof(name):
    """A page action is a plain person action: nothing in a server mints or runs a core with a proof."""
    tree = ast.parse(SERVERS[name].read_text())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"mint", "run_with_proof"}, f"{name} still mints"

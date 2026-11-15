"""Lessons add-on scenario L1: a helper writes a lesson, the next start carries it; edit and rm change it."""
from __future__ import annotations

import json

from lib import check, scenario
from scenarios_factory import F

TEXT = "Run the web tests with npm run test:web; plain npm test skips them."


@scenario("L1")
def l1(e):
    """Lessons: turn it on, an agent-side `orch lessons add`, the next start (AGENTS.orch.md, the start prompt of the
    fake agent) carries the text; edit replaces it, rm removes it; a secret is refused and nothing is stored."""
    w = F(e, "L1").w  # a workspace with the fake agent registered (the Factory kit sets it up; its add-ons stay unused)
    rc, out, err = w.sh(["orch", "addon", "add", "lessons", "--yes"], timeout=600)
    check(rc == 0, f"addon add lessons: {(err or out)[-300:]}")
    agents = w.root / ".orch/harness/AGENTS.orch.md"
    check("orch-lessons" in agents.read_text(), "lessons block missing")
    check("Lessons from earlier helpers" not in agents.read_text(), "text before any lesson")

    tid = w.ticket("Lessons demo", "Say hello")
    agent_env = {"ORCH_AGENT": "fake", "ORCH_RUN": "r_e2elessn"}  # what an agent run has in its environment
    rc, out, err = w.sh(["orch", "lessons", "add", TEXT, "--ticket", tid, "--json"], env=agent_env)
    check(rc == 0, f"lessons add: {(err or out)[-300:]}")
    row = json.loads(out)
    check(row["added"] is True and row["lesson"]["by"] == "agent:fake" and row["lesson"]["ticket"] == tid, f"add answer: {row}")
    check(TEXT in agents.read_text(), "lesson not in AGENTS.orch.md after add")
    rc, out, _ = w.sh(["orch", "lessons", "add", TEXT.upper(), "--json"], env=agent_env)
    check(json.loads(out)["added"] is False, "the same text was stored twice")

    rc, out, _ = w.sh(["orch", "lessons", "add", "The key is sk-ant-api03-" + "A1b2C3d4" * 6, "--json"], env=agent_env)
    check(rc == 2 and "error" in json.loads(out), f"secret not refused: {rc} {out[:120]}")

    w.j("run", "start", tid)
    w.wait_done(tid)
    prompts = " ".join(w.lines("prompt"))
    check(TEXT in prompts, f"the next start does not carry the lesson: {prompts[:300]!r}")

    lid = row["lesson"]["id"]
    rc, out, err = w.sh(["orch", "lessons", "edit", lid, "Use npm run test:web for web tests.", "--json"])
    check(rc == 0 and json.loads(out)["lesson"]["changed_by"].startswith("human:"), f"edit: {(err or out)[-200:]}")
    text = agents.read_text()
    check("Use npm run test:web" in text and TEXT not in text, "edit did not replace the text")
    copy_view = json.loads(w.sh(["orch", "lessons", "view", "--json"])[1])
    check(copy_view["blocks"][0]["count"] == 1, f"view: {copy_view}")

    rc, out, err = w.sh(["orch", "lessons", "rm", lid, "--json"])
    check(rc == 0 and json.loads(out)["removed"] == lid, f"rm: {(err or out)[-200:]}")
    check("Use npm run test:web" not in agents.read_text(), "removed lesson still in AGENTS.orch.md")
    check(not (w.root / ".orch/addons/lessons/AGENTS-extra.md").exists(), "AGENTS-extra.md left behind")

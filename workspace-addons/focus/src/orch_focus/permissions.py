"""FO-10 a: a one-shot agent that was refused a tool asks the person, and "Allow and retry" starts the run again
with that tool allowed for this run only (`orch run start <ticket> --allow <tool>`). Nothing is written to the
agent's own settings. The tool comes from the agent's denial, never from the browser."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import actions, adapterdata, runfiles
from .events import RUN_ID

KIND = "focus:permission"
ALLOW = "Allow and retry"
NOT_NOW = "Not now"
TOOL = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


class Permissions:
    def __init__(self, root: Path, orch_bin: str | None):
        self.root, self.orch_bin = root, orch_bin
        self.state = self._load()

    def _file(self) -> Path:
        return runfiles.run_dir(self.root, "focus") / "permissions.json"  # plain folders only

    def _load(self) -> dict:
        try:
            d = runfiles.read_json(self._file()) or {}
        except RuntimeError:
            d = {}
        return {"asked": list(d.get("asked", []))[-60:], "done": list(d.get("done", []))[-60:]}

    def _save(self) -> None:
        self.state = {k: v[-60:] for k, v in self.state.items()}
        runfiles.write_json(self._file(), self.state)

    def _orch(self, argv: list[str]) -> int:
        try:
            return actions.orch(self.root, self.orch_bin, argv, timeout=30)[0]
        except actions.Unavailable:
            return 1

    def sync(self, tid: str, claim: dict, denials: list[dict], ticket: dict, agent_label: str) -> bool:
        """Ask for new denials, act on answers. Returns True when a run was started again."""
        agent, run = claim.get("agent"), claim.get("run")
        restarted = False
        changed = False
        eligible = claim.get("mode") == "oneshot" and adapterdata.permission_retry(self.root, agent or "")
        if eligible and isinstance(run, str) and RUN_ID.fullmatch(run):
            for d in denials:
                tool = d.get("tool")
                key = f"{run}:{tool}"
                if not isinstance(tool, str) or not TOOL.fullmatch(tool) or key in self.state["asked"]:
                    continue
                self.state["asked"].append(key)
                changed = True
                self._orch([
                    "ask", tid, f"{agent_label} needs your OK to use {tool}. Allow it and try again?",
                    "--option", ALLOW, "--option", NOT_NOW, "--recommend", ALLOW, "--kind", KIND,
                    "--action", json.dumps({"tool": tool, "run": run}), "--by", "agent:focus", "--json",
                ])  # fmt: skip
        for q in ticket.get("questions") or []:
            if q.get("kind") != KIND or q.get("answer") is None:
                continue
            key = f"{tid}:{q['id']}"
            if key in self.state["done"]:
                continue
            self.state["done"].append(key)
            changed = True
            tool = (q.get("action") or {}).get("tool")
            if q["answer"] == ALLOW and isinstance(tool, str) and TOOL.fullmatch(tool):
                restarted = (
                    self._orch(["run", "start", tid, f"--allow={tool}", "--by", "focus", "--json"]) == 0
                )
        if changed:
            try:
                self._save()
            except (OSError, RuntimeError):
                pass
        return restarted

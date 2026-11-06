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


def _qid(out: str) -> str | None:
    try:
        q = json.loads(out).get("id")
    except (ValueError, AttributeError):
        return None
    return q if isinstance(q, str) and re.fullmatch(r"q[0-9]{1,4}", q) else None


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
        qs = d.get("qs") if isinstance(d.get("qs"), dict) else {}
        return {
            "asked": list(d.get("asked", []))[-60:],
            "done": list(d.get("done", []))[-60:],
            "qs": dict(list(qs.items())[-60:]),
        }

    def _save(self) -> None:
        self.state = {
            "asked": self.state["asked"][-60:],
            "done": self.state["done"][-60:],
            "qs": dict(list(self.state["qs"].items())[-60:]),
        }
        runfiles.write_json(self._file(), self.state)

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        try:
            return actions.orch(self.root, self.orch_bin, argv, timeout=30)
        except actions.Unavailable:
            return 1, "", ""

    def sync(
        self, tid: str, claim: dict, running: bool, last_run, denials: list[dict], ticket: dict, label: str
    ) -> bool:
        """Ask for new denials, act on answers. Returns True when a run was started again.

        An answer counts only for a question Focus itself asked (its id is in the stored record, with the run
        and the tool from the agent's denial), for the latest run, once that run is over. The tool never comes
        from the question's own fields: an agent that makes up a focus:permission question gets nothing."""
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
                code, out, _ = self._run([
                    "ask", tid, f"{label} needs your OK to use {tool}. Allow it and try again?",
                    "--option", ALLOW, "--option", NOT_NOW, "--recommend", ALLOW, "--kind", KIND,
                    "--action", json.dumps({"tool": tool, "run": run}), "--by", "agent:focus", "--json",
                ])  # fmt: skip
                qid = _qid(out) if code == 0 else None
                if qid:
                    self.state["qs"][f"{tid}:{qid}"] = {
                        "run": run,
                        "tool": tool,
                        "agent": agent,
                        "mode": "oneshot",
                    }
        for q in ticket.get("questions") or []:
            if q.get("kind") != KIND or q.get("answer") is None or not isinstance(q.get("id"), str):
                continue
            key = f"{tid}:{q['id']}"
            rec = self.state["qs"].get(key)
            if rec is None or key in self.state["done"]:
                continue  # not asked by Focus, or already handled
            if running or rec["run"] != last_run:
                continue  # the run is still going, or a newer run exists: this answer is old
            self.state["done"].append(key)
            changed = True
            if (
                q["answer"] == ALLOW
                and TOOL.fullmatch(rec["tool"])
                and rec.get("mode") == "oneshot"
                and adapterdata.permission_retry(self.root, rec.get("agent") or "")
            ):
                code, _, _ = self._run(
                    ["run", "start", tid, f"--allow={rec['tool']}", "--by", "focus", "--json"]
                )
                restarted = code == 0
        if changed:
            try:
                self._save()
            except (OSError, RuntimeError):
                pass
        return restarted

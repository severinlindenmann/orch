"""LLM review of screenshots with the owner's Claude API credit (skill claude-api-credit): Nielsen heuristics + wording."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

REAL_HOME = Path(os.environ.get('E2E_REAL_HOME') or Path.home())
RUNNER = REAL_HOME / ".claude/skills/claude-api-credit/scripts/claude-api-run.py"
PROMPT = """You review screenshots of orch, a ticket tool for non-technical people. Each image is named below with its step.
Rules: UI says Ticket and Task (never Request/Job/Issue/Subtask), plain words, no VPN product names, minimal info with detail behind a click,
one plain click for admin actions (no typed words), clear next action, empty states say what to do. Judge against Nielsen's ten heuristics.
Report only real problems you can SEE in the image (max 2 per image, skip nitpicks). Output JSON only, a list of objects:
{"image": "<name>", "title": "...", "now": "what the screen shows and why it confuses", "proposal": "the concrete change (wording, layout, control)", "heuristic": "e.g. Visibility of status", "severity": "ux"}
Images:
"""


def review(shots: list[tuple[str, Path]], model="claude-sonnet-5-5", batch=6, log=print) -> list[dict]:
    """shots: [(label, path)]. One call per batch of images. Returns findings (NOW/PROPOSAL)."""
    found: list[dict] = []
    if not RUNNER.exists():
        log("claude-api-run.py missing, review skipped")
        return found
    for i in range(0, len(shots), batch):
        part = shots[i:i + batch]
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, dir=REAL_HOME / ".orch-e2e-review" if (REAL_HOME / ".orch-e2e-review").exists() else None) as f:
            f.write(PROMPT + "\n".join(f"- {n}" for n, _ in part) + "\n")
            task = f.name
        try:
            r = subprocess.run([str(RUNNER), f"e2efull-q{i // batch}", task, "--model", model, *[str(p) for _, p in part]],
                               capture_output=True, text=True, timeout=300,
                               env={"HOME": str(REAL_HOME), "PATH": os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin:" + str(REAL_HOME / ".local/bin") + ":/Users/lume/.local/bin", "LANG": "en_US.UTF-8"})
            m = re.search(r"\[.*\]", r.stdout, re.S)
            if r.returncode or not m:
                log(f"review batch {i // batch} failed: {(r.stderr or r.stdout)[-200:]}")
                continue
            for o in json.loads(m.group(0)):
                lab = o.get("image", "")
                p = next((str(pp) for n, pp in part if n == lab), "")
                found.append({"lane": "Q", "kind": "llm", "severity": o.get("severity", "ux"), "step": lab, "shots": [p] if p else [],
                              "title": o.get("title", ""), "now": o.get("now", ""), "proposal": o.get("proposal", ""),
                              "heuristic": o.get("heuristic", "")})
        except Exception as x:  # noqa: BLE001
            log(f"review batch {i // batch} error: {x}")
        finally:
            Path(task).unlink(missing_ok=True)
    return found

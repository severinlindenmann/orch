"""Run real agents (claude -p, codex exec) inside a temp workspace: restricted tools, watchdog, redacted transcript."""
from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path

CLAUDE_TOOLS = ["Bash(orch:*)", "Bash(git:*)", "Bash(python3:*)", "Bash(date:*)", "Read", "Write", "Edit", "Glob", "Grep"]
SECRET_RE = re.compile(r"(sk-ant-[A-Za-z0-9_-]{10,}|orn_[A-Za-z0-9_-]{20,}|orp_[A-Za-z0-9_-]{20,}|whk_[A-Za-z0-9_-]{16,}|"
                       r"eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|#k=[A-Za-z0-9_-]{20,})")


def redact(text: str, extra: list[str] = ()) -> str:
    for s in extra:
        if s and len(s) > 8:
            text = text.replace(s, "[REDACTED]")
    return SECRET_RE.sub("[REDACTED]", text)


def agent_env(e) -> dict:
    """Environment of the agent process: the e2e env plus only the agent's own login."""
    env = dict(e.env)
    if os.environ.get("E2E_CLAUDE_TOKEN"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["E2E_CLAUDE_TOKEN"]
    return env


def codex_home(e) -> str:
    return str(e.tmp / "codex")


def claude_cmd(prompt: str, max_turns: int = 40) -> list[str]:
    return ["claude", "-p", prompt, "--permission-mode", "acceptEdits", "--output-format", "stream-json", "--verbose",
            "--max-turns", str(max_turns), "--allowedTools", *CLAUDE_TOOLS]


def codex_cmd(ws: Path, prompt: str) -> list[str]:
    return ["codex", "exec", "-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true",
            "--skip-git-repo-check", "-C", str(ws), prompt]


def automation_agent_line(e, tool: str) -> str:
    """The agent command line (`agent = <command>`; sched_config turns it into [workspace] agent + [agents.e2eagent]; same restrictions as the direct runs)."""
    if tool == "claude":
        tools = " ".join(shlex.quote(t) for t in CLAUDE_TOOLS)
        return f"""agent = '''claude -p "{{prompt}}" --permission-mode acceptEdits --max-turns 40 --allowedTools {tools}'''"""
    return (f"agent = '''env CODEX_HOME={codex_home(e)} codex exec -s workspace-write "
            f"-c sandbox_workspace_write.network_access=true --skip-git-repo-check \"{{prompt}}\"'''")


def render_stream(raw: str) -> str:
    """claude --output-format stream-json -> readable transcript (tool calls and answers)."""
    out = []
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        t = ev.get("type")
        if t == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "text":
                    out.append(f"[assistant] {c['text']}")
                elif c.get("type") == "tool_use":
                    out.append(f"[tool] {c.get('name')} {json.dumps(c.get('input'), ensure_ascii=False)[:600]}")
        elif t == "user":
            for c in ev.get("message", {}).get("content", []) if isinstance(ev.get("message", {}).get("content"), list) else []:
                if c.get("type") == "tool_result":
                    body = c.get("content")
                    if isinstance(body, list):
                        body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                    out.append(f"[result] {str(body)[:500]}")
        elif t == "result":
            out.append(f"[final] {ev.get('result', '')}  (turns {ev.get('num_turns')}, error={ev.get('is_error')})")
    return "\n".join(out)


class AgentRun:
    def __init__(self, tool: str, rc: int | None, text: str, timed_out: bool, secs: float):
        self.tool, self.rc, self.text, self.timed_out, self.secs = tool, rc, text, timed_out, secs

    def said(self, *words: str) -> bool:
        t = self.text.lower()
        return any(w.lower() in t for w in words)

    def ran(self, fragment: str) -> bool:
        """A tool call (claude) or command line (codex) containing the fragment."""
        return any(fragment in l for l in self.text.splitlines() if l.startswith("[tool]") or "exec" in l[:12] or l.lstrip().startswith("$"))


def run_agent(e, name: str, tool: str, ws: Path, prompt: str, timeout: int = 300, env_over: dict | None = None) -> AgentRun:
    """Start one agent run in `ws`, kill its process group after `timeout` s, save the redacted transcript."""
    if tool == "claude":
        if not os.environ.get("E2E_CLAUDE_TOKEN"):
            from lib import Skip
            raise Skip("no Claude setup-token (Proton Pass item) available")
        cmd, env = claude_cmd(prompt), {**agent_env(e), **(env_over or {})}
    else:
        cmd, env = codex_cmd(ws, prompt), {**e.env, **(env_over or {}), "CODEX_HOME": codex_home(e)}
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=ws, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)
    e.pids.append(proc.pid)
    timed_out = False
    try:
        raw, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)  # only the process group of this agent
        except OSError:
            pass
        try:
            raw, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            raw, _ = proc.communicate()
    text = raw.decode("utf-8", "replace")
    if tool == "claude":
        text = render_stream(text)
    save_transcript(e, name, f"# {tool} in {ws.name}  rc={proc.returncode} timed_out={timed_out} {time.time() - t0:.0f}s\n"
                             f"# prompt: {prompt}\n\n{text}")
    return AgentRun(tool, proc.returncode, text, timed_out, time.time() - t0)


def save_transcript(e, name: str, text: str, append: bool = False) -> None:
    d = Path(os.environ.get("E2E_AGENT_RUNS") or e.tmp / "agent-runs")
    d.mkdir(parents=True, exist_ok=True)
    secrets = [os.environ.get("E2E_CLAUDE_TOKEN", "")] + [v for pair in e.creds.values() for v in pair[1:]]
    p = d / f"{name}.txt"
    with open(p, "a" if append else "w") as f:
        f.write(redact(text, secrets) + "\n")


def automation_once(e, ws: Path, name: str, timeout: int = 400, env_over: dict | None = None) -> str:
    """`orch automation run --once` (starts due agents; then waits for their runs to end). Log files are added to the transcript."""
    env = {**agent_env(e), **(env_over or {})}
    p = subprocess.run(["orch", "automation", "run", "--once"], cwd=ws, env=env, capture_output=True, timeout=timeout)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    end = time.time() + timeout  # core starts the agents detached: wait until no run holds a ticket
    while list((ws / ".orch/run/tickets").glob("*.json")) and time.time() < end:
        time.sleep(1)
    logs = sorted((ws / ".orch/run/logs").glob("*.log"))
    body = f"\n## automation run --once in {ws.name}: rc={p.returncode}\n{out}\n"
    for lg in logs:
        body += f"\n### {lg.name}\n{lg.read_text(errors='replace')[-6000:]}\n"
    save_transcript(e, name, body, append=True)
    return out

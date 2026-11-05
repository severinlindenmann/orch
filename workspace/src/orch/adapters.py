"""Agent tool adapters: the only place that knows tool names and how to recognise them."""

from __future__ import annotations

from collections.abc import Mapping


def detect_env(environ: Mapping[str, str]) -> str | None:
    """The agent tool a process runs under, from its environment (ORCH_AGENT first), else None."""
    if environ.get("ORCH_AGENT"):
        return environ["ORCH_AGENT"]
    if environ.get("CLAUDECODE") or environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude-code"
    if any(k.startswith("CODEX_") for k in environ):
        return "codex"
    return None

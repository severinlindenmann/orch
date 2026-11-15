"""The command and the last lines of a shell step's output, for the Earlier steps block (#692.1).

One helper for every reader (the record feed and the transcript reader): line breaks kept, at most 40 lines and
4000 characters, every line the shared secret scanner (`orch.secretscan`, the one `orch secret scan`, relay and
publish use) flags replaced by `[hidden: <kind>]`, then the event log's own redaction. Never a second pattern list.
"""

from __future__ import annotations

from . import events as ev

OUT_LINES, OUT_CHARS, CMD_CHARS = 40, 4000, 2000
LIMITS = {"command": CMD_CHARS, "output": OUT_CHARS}  # per-field limits for events.make
_SCAN_CAP = 200_000  # the scanner looks at the last 200 KB of a result at most


def _raw_result(content) -> str:
    """The result text with its line breaks kept (a list of blocks is joined by line breaks)."""
    if isinstance(content, list):
        content = "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return str(content or "").replace("\r\n", "\n").replace("\r", "\n")


def _hidden_lines(text: str, root) -> dict[int, str]:
    """{line: kind} for every line the shared scanner flags. A private key hides through its END line."""
    from orch import secretscan  # the one scanner `orch secret scan`, relay and publish use

    lines = text.split("\n")
    out: dict[int, str] = {}
    for f in secretscan.find(text, root):
        n, kind = f["line"], f["kind"]
        out.setdefault(n, kind)
        if kind == "private-key":
            i = n
            while i <= len(lines):
                out.setdefault(i, kind)
                if "-----END" in lines[i - 1]:
                    break
                i += 1
    return out


def output_tail(content, root=None) -> str | None:
    """The last lines of a shell step's result for the page: line breaks kept, at most 40 lines and 4000
    characters, every line the shared secret scanner flags replaced by `[hidden: <kind>]`, then the event
    log's own redaction (events.make). None when there is nothing to show or the scan could not run (fail
    closed: no output instead of an unchecked one)."""
    text = _raw_result(content).strip("\n")
    if not text.strip():
        return None
    try:
        text = text[-_SCAN_CAP:]
        hide = _hidden_lines(text, root)
    except Exception:  # noqa: BLE001 - an unchecked output is never shown
        return None
    lines = [f"[hidden: {hide[n]}]" if n in hide else ln for n, ln in enumerate(text.split("\n"), 1)]
    tail = "\n".join(lines[-OUT_LINES:])
    if len(tail) > OUT_CHARS:  # keep the END of the output, from a whole line
        tail = tail[-OUT_CHARS:]
        tail = tail.split("\n", 1)[1] if "\n" in tail else tail
    tail = ev.redact(tail)
    return tail if tail.strip() else None


def command_text(value) -> str | None:
    """The exact command of a shell step, as text (events.make redacts and clips it to CMD_CHARS)."""
    return value if isinstance(value, str) and value.strip() else None


def from_detail(detail, root=None) -> tuple[str | None, str | None]:
    """(command, output) of a Bash step's detail file {input, output}. The output is a text, a list of text
    blocks, or an object with stdout and stderr (the hook's shape). Anything else gives None for that part."""
    d = detail if isinstance(detail, dict) else {}
    inp = d.get("input")
    cmd = command_text(inp.get("command")) if isinstance(inp, dict) else None
    out = d.get("output")
    if isinstance(out, dict):
        out = "\n".join(
            str(out[k]) for k in ("stdout", "stderr") if isinstance(out.get(k), str) and out[k].strip()
        )
    return cmd, output_tail(out, root)

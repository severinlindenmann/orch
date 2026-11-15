"""One secret scanner for text: the token patterns, key=value pairs, flag values and the values of this
workspace's own stored keys. `orch secret scan` and the phone view's redact/file scan all use it, so there
is one list. A finding names a kind and a line, never the matched text."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

MAX_BYTES = 1_000_000

_RX = [
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?(-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
        re.S,
    ),  # PEM and PGP (PRIVATE KEY BLOCK)
    re.compile(r"\b(?:orn|orp|ora|whk|opk|apv)_[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}|\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    # JWT: one start per run of its characters (`-` is one of them but no word character: a \b start after
    # every `-` made "eyJ-eyJ-..." quadratic), the parts possessive
    re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{5,}"),
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    # Google API key, Hugging Face, npm, PyPI, SendGrid, DigitalOcean
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}|\bhf_[A-Za-z0-9]{30,}|\bnpm_[A-Za-z0-9]{36}"),
    re.compile(r"\bpypi-AgE[A-Za-z0-9_-]{50,}|\bSG\.[\w-]{22}\.[\w-]{43}|\bdop_v1_[a-f0-9]{64}"),
    # user:password@ in any URL (postgres://u:p@db, https://bob:pw@git...): one start per scheme run, the user
    # part possessive and without `:`, the password part stops at the last `@` before the path (linear)
    re.compile(r"(?i)(?<![\w+.-])[a-z][a-z0-9+.-]*+://[^\s/?#@:]*+:[^\s/?#]*@"),
    # webhook path tokens: Slack /services/T../B../x, Discord /api/webhooks/<id>/<token>, Telegram /bot<id>:x
    re.compile(
        r"(?<=/services/)T\w++/B\w++/\w++|(?<=/api/webhooks/)\d++/[\w-]++|(?<![\w-])bot\d++:[\w-]{20,}"
    ),
]

KINDS = [
    "private-key", "orch-token", "api-key", "github-token", "gitlab-or-slack-token", "aws-key", "jwt",
    "bearer-token", "api-token", "api-token", "password-in-url", "webhook-token",
]  # fmt: skip
assert len(KINDS) == len(_RX)
PATTERNS = list(zip(KINDS, _RX, strict=True))  # (kind, compiled pattern)

WORDS = {  # how a kind reads in the refusal sentence
    "private-key": "a private key",
    "orch-token": "an orch token",
    "api-key": "an API key",
    "github-token": "a GitHub token",
    "gitlab-or-slack-token": "a GitLab or Slack token",
    "aws-key": "an AWS key",
    "jwt": "a login token",
    "bearer-token": "a login token",
    "api-token": "an API token",
    "password-in-url": "a password in a web address",
    "webhook-token": "a webhook address",
    "secret-value": "a password or secret value",
    "stored-key": "one of this workspace's stored keys",
}


def too_large(n: int) -> bool:
    return n > MAX_BYTES


def find(text: str, root: Path | None = None) -> list[dict]:
    """[{kind, line}] (line from 1, one entry per kind and line), in text order. Pattern kinds first, then any
    other line the phone view's scrub would change (key=value, spaced values, flag values), then lines that
    hold a stored key value of the workspace (`root`). A stored-key check that cannot run reports `stored-key`
    on line 1 (fail closed)."""
    from orch import phone_view

    found: dict[tuple[int, str], None] = {}

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            found[(line_of(m.start()), kind)] = None
    flagged = {ln for ln, _ in found}
    for n, raw in enumerate(text.split("\n"), 1):
        if n in flagged:
            continue
        forms = (raw, phone_view._clean_full(raw), unicodedata.normalize("NFKC", raw))
        if any(phone_view._scrub_text(f) != f for f in dict.fromkeys(forms)):
            found[(n, "secret-value")] = None
    if root is not None:
        from orch import phone_results

        h = phone_results.value_hider(root)
        if h is None:
            found[(1, "stored-key")] = None
        else:
            try:
                for n, raw in enumerate(text.split("\n"), 1):
                    if h.hide_text(raw) != raw or h.hide_text(raw.replace("\r", "")) != raw.replace("\r", ""):
                        found[(n, "stored-key")] = None
                if not any(k == "stored-key" for _, k in found) and h.hide_text(text) != text:
                    found[(1, "stored-key")] = None  # a value that spans lines
            except Exception:  # noqa: BLE001 - never a pass
                found[(1, "stored-key")] = None
    return [{"kind": k, "line": ln} for (ln, k) in sorted(found)]


def refusal(found: list[dict]) -> str:
    first = found[0]
    more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
    return (
        f"The text has {WORDS.get(first['kind'], 'a secret')} on line {first['line']}{more}. "
        "Remove it and try again."
    )

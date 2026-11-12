"""The complete step-2 sync surface; everything else stays local."""

import re

NEVER_SYNCED = [
    ".gitignore",
    ".local-id",
    "me/",
    "chat/",
    "secrets/",
    "run/",
    "inbox/",
    "inbox-seen.json",
    "inbox-notes.json",
    "outbox/",
    "addons/",
    "local/",
    "harness/",
    "evidence/",
    "tickets/*/evidence/",
    "tmp-refresh/",
    "tmp-sync/",
    "config.toml",
    "addons.json",
    "*.lock",
    ".lock-*",
    ".tmp-*",
]
TICKET = re.compile(r"tickets/t_[a-z0-9]{6,16}\.json")
ARTIFACT = re.compile(
    r"tickets/t_[a-z0-9]{6,16}/artifacts/[A-Za-z0-9 ._()-]{1,100}(?:/[A-Za-z0-9 ._()-]{1,100})*"
)
SECRET = re.compile(
    r"\.env.*|.*\.(pem|key|p8|p12|pfx|kdbx)|id_rsa.*|id_ed25519.*|credentials.*", re.IGNORECASE
)
RESERVED = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", re.IGNORECASE)


def allowed(path):
    if path == "ticket-counter.json" or TICKET.fullmatch(path):
        return True
    return bool(ARTIFACT.fullmatch(path)) and all(
        p not in (".", "..", ".git", ".gitattributes", ".gitmodules", ".gitignore")
        and not p.endswith((".", " "))
        and not SECRET.fullmatch(p)
        and not RESERVED.fullmatch(p)
        and not p.endswith(".lock")
        and not p.startswith((".lock-", ".tmp-"))
        for p in path.lower().split("/")[3:]
    )

"""Session ID syntax shared by adapters and local ownership records."""

import re

# UUIDs and recorded adapter thread IDs both fit this conservative syntax.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def valid_session_id(sid: object) -> bool:
    return isinstance(sid, str) and SESSION_ID_RE.fullmatch(sid) is not None

"""Credit reader interface: `read(source: dict, since: str | None) -> CreditUse`. Read only.

`source` is the account's `source` table in accounts.json (`{"reader": "<name>", ...}`). A reader that cannot tell
returns `CreditUse(spent=None, note=...)`; it never raises for a missing file or a provider that has no number yet.
"""

from __future__ import annotations

from . import CreditUse, spend_log


def unknown(source: dict, since: str | None) -> CreditUse:
    """The stub: an account Usage knows but cannot measure yet."""
    return CreditUse(spent=None, since=since, note="No reader for this account yet.")


READERS = {"none": unknown, "spend-log": spend_log.read}

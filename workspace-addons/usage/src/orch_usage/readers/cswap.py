"""Subscription use reader: the account switcher's `cswap list --json` (schemaVersion 1). Read only.

The address of each account is used once to make a stable key (a hash) and a label, then dropped: it is never
returned, stored or printed. Missing switcher: `read()` returns None and Usage shows and warns only.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess

from . import SubscriptionUse, Window

ENV = "ORCH_USAGE_SWITCHER"  # path of the switcher command (tests, unusual installs)
TIMEOUT = 30
_WINDOWS = {"fiveHour": "5h", "sevenDay": "week"}


class ReaderError(Exception):
    """The switcher is there but its answer could not be read; plain words."""


def command() -> str | None:
    explicit = os.environ.get(ENV)
    if explicit:
        return explicit if os.path.isfile(explicit) and os.access(explicit, os.X_OK) else None
    return shutil.which("cswap")


def key_of(address: str) -> str:
    return "c_" + hashlib.sha256(address.strip().lower().encode("utf-8")).hexdigest()[:16]


def label_of(row: dict) -> str:
    """A team name when the account belongs to one, else the part before the @."""
    org = str(row.get("organizationName") or "").strip()
    address = str(row.get("email") or "")
    if org and row.get("isOrganization") and not org.endswith(" Organization") and "@" not in org:
        return org[:40]
    local = address.split("@", 1)[0].strip()
    return (local or f"Account {row.get('number', '?')}")[:40]


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse(data) -> list[SubscriptionUse]:
    if (
        not isinstance(data, dict)
        or data.get("schemaVersion") != 1
        or not isinstance(data.get("accounts"), list)
    ):
        raise ReaderError(
            "The account switcher answered in a form Usage does not know. Update it and try again."
        )
    out = []
    for row in data["accounts"]:
        if not isinstance(row, dict) or not isinstance(row.get("number"), int):
            continue
        address = row.get("email")
        if not isinstance(address, str) or "@" not in address:
            continue
        windows = {}
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
        for src, name in _WINDOWS.items():
            w = usage.get(src)
            if isinstance(w, dict):
                last = w.get("willLastToReset")
                windows[name] = Window(
                    pct=_num(w.get("pct")),
                    resets_at=w.get("resetsAt") if isinstance(w.get("resetsAt"), str) else None,
                    lasts_to_reset=last if isinstance(last, bool) else None,
                )
        out.append(
            SubscriptionUse(
                key=key_of(address),
                label=label_of(row),
                slot=row["number"],
                active=bool(row.get("active")),
                windows=windows,
                fetched_at=row.get("usageFetchedAt") if isinstance(row.get("usageFetchedAt"), str) else None,
                status=str(row.get("usageStatus") or "ok")[:20],
            )
        )
    return out


def read() -> list[SubscriptionUse] | None:
    cmd = command()
    if not cmd:
        return None
    try:
        p = subprocess.run(
            [cmd, "list", "--json"], capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ReaderError("The account switcher did not answer. Try again in a minute.") from None
    if p.returncode != 0:
        raise ReaderError("The account switcher could not list its accounts. Try again in a minute.")
    try:
        data = json.loads(p.stdout)
    except ValueError:
        raise ReaderError(
            "The account switcher's answer could not be read. Update it and try again."
        ) from None
    return parse(data)

"""Readers: small adapters, one file per provider, that only read numbers.

A use reader (subscriptions) answers "which accounts are there and how far is each": `read() -> list[SubscriptionUse]`
or None when its tool is missing. A credit reader (API key or credit) answers "how much was spent since a time":
`read(source, since) -> CreditUse`. Readers never return or keep a login, token, key or address: only a stable
key (a hash), a label, numbers and times.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Window:
    """One limit window of a subscription: percent used and when it starts again (UTC ISO, or None)."""

    pct: float | None
    resets_at: str | None = None
    lasts_to_reset: bool | None = None


@dataclass
class SubscriptionUse:
    key: str  # stable, not an address: a hash the reader makes
    label: str
    slot: int  # the switcher's own number for the account (it can change; the key does not)
    active: bool = False
    windows: dict[str, Window] = field(default_factory=dict)  # "5h", "week"
    fetched_at: str | None = None
    status: str = "ok"


@dataclass
class CreditUse:
    spent: float | None  # in the account's unit ($)
    since: str | None
    as_of: str | None = None
    estimated: bool = False
    note: str | None = None  # plain words when the number is missing


def subscription_reader(name: str):
    from . import cswap

    return {"cswap": cswap}.get(name)


def credit_reader(name: str):
    from . import credit

    return credit.READERS.get(name)

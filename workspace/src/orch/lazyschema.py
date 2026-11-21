"""A JSON Schema check that loads its library on first use (ORCH-609).

jsonschema with attrs, referencing and rpds takes about 20 ms to load. Modules that every orch command
imports kept their checks at module level, so each command (also `orch --version`) paid for it.
`checker(make)` returns a stand-in that builds the real validator the first time one of its methods is
used; `make` imports jsonschema itself."""

from __future__ import annotations

import threading


class _Lazy:
    __slots__ = ("_make", "_real", "_lock")

    def __init__(self, make):
        self._make, self._real, self._lock = make, None, threading.Lock()

    def __getattr__(self, name):
        real = self._real
        if real is None:
            with self._lock:
                if self._real is None:
                    self._real = self._make()
                real = self._real
        return getattr(real, name)


def checker(make) -> _Lazy:
    return _Lazy(make)

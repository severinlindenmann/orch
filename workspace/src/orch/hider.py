"""Exact-value hiding without store, filesystem, or environment access."""

import base64
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock
from typing import Any, TypeVar
from urllib.parse import quote, quote_plus

from orch.errors import Refused

_Data = TypeVar("_Data", str, bytes)


class HidingRefused(Refused):
    """An identifier cannot be emitted safely."""

    def __init__(self) -> None:
        super().__init__("Identifier hiding refused")


class NoHiderError(Refused):
    """A writer has no registered hider."""

    def __init__(self) -> None:
        super().__init__("No hider registered")


def _forms(value: str) -> set[str]:
    if len(value) < 8:
        return set()
    raw = value.encode("utf-8")
    b64 = []
    for offset in range(3):
        encoded = base64.b64encode(b"\0" * offset + raw).decode("ascii").rstrip("=")
        part = encoded[(8 * offset + 5) // 6:8 * (offset + len(raw)) // 6]
        b64.extend((part, part.translate(str.maketrans("+/", "-_"))))
    forms = {value, raw.hex(), raw.hex().upper(), *b64}
    for ascii_only in (False, True):
        escaped = json.dumps(value, ensure_ascii=ascii_only)[1:-1]
        forms.update((escaped, escaped.replace("/", "\\/")))
    for source in (value, *b64):
        for encode in (quote, quote_plus):
            escaped = encode(source, safe="")
            forms.update((escaped, re.sub(r"%[0-9A-Fa-f]{2}", lambda m: m[0].lower(), escaped)))
    if "\n" in value:
        forms.update(line for line in value.splitlines() if len(line) >= 16)
    return {form for form in forms if len(form) >= 8}


def _leaves(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _leaves(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _leaves(value)


def _hide_upto(buf: _Data, needles: tuple[tuple[_Data, _Data], ...], stop: int) -> tuple[_Data, int]:
    """Select leftmost candidates, breaking ties by precomputed needle order."""
    candidates = []
    for order, (needle, _) in enumerate(needles):
        start = buf.find(needle)
        while 0 <= start < stop:
            candidates.append((start, order))
            start = buf.find(needle, start + 1)
    candidates.sort()
    parts = []
    pos = 0
    for start, order in candidates:
        if start >= pos:
            needle, replacement = needles[order]
            parts.extend((buf[pos:start], replacement))
            pos = start + len(needle)
    end = max(pos, stop)
    parts.append(buf[pos:end])
    return buf[:0].join(parts), end


def _drop_prefix(text: _Data, needles: tuple[tuple[_Data, _Data], ...]) -> _Data:
    longest = 0
    for needle, _ in needles:
        for length in range(min(len(text), len(needle) - 1), max(3, longest), -1):
            if text.endswith(needle[:length]):
                longest = length
                break
    return text[:-longest] if longest else text


class Hider:
    """Precomputed forms; names are public labels and values are confidential."""

    def __init__(self, needles: dict[str, str | dict | list], *, salt: bytes | None = None):
        try:
            if not isinstance(needles, dict) or (salt is not None and not isinstance(salt, bytes)):
                raise TypeError
            forms: dict[str, str] = {}
            for name, value in needles.items():
                if not isinstance(name, str) or not isinstance(value, (str, dict, list)):
                    raise TypeError
                if isinstance(value, str):
                    values = (value,)
                else:
                    compact = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
                    if len(compact) >= 8:
                        forms.setdefault(compact, name)
                    values = _leaves(value)
                for leaf in values:
                    for form in _forms(leaf):
                        forms.setdefault(form, name)
            self._names = tuple(sorted(needles))
            self._text = tuple(
                (form, f"[hidden: {name}]")
                for form, name in sorted(forms.items(), key=lambda item: (-len(item[0]), item[0]))
            )
            self._binary = tuple(sorted(
                ((form.encode("utf-8"), marker.encode("utf-8")) for form, marker in self._text),
                key=lambda item: (-len(item[0]), item[0]),
            ))
            self._salt = secrets.token_bytes(32) if salt is None else salt
        except (TypeError, ValueError, RecursionError):
            raise ValueError("Invalid hiding configuration") from None

    @property
    def names(self) -> tuple[str, ...]:
        return self._names

    def __repr__(self) -> str:
        return f"Hider(names={len(self._names)}, forms={len(self._text)})"

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError("Hider cannot be serialized")

    def __getstate__(self) -> Any:
        raise TypeError("Hider cannot be serialized")

    def hide_text(self, s: str) -> str:
        return _hide_upto(s, self._text, len(s))[0]

    def hide_bytes(self, b: bytes) -> bytes:
        return _hide_upto(b, self._binary, len(b))[0]

    def drop_trailing_prefix(self, s: str) -> str:
        return _drop_prefix(s, self._text)

    def hide_cut(self, s: str, limit: int) -> str:
        if limit < 0:
            raise ValueError("Invalid hiding limit")
        hidden = self.hide_text(s)
        return self.drop_trailing_prefix(hidden[:limit]) if len(hidden) > limit else hidden

    def hide_cut_bytes(self, b: bytes, limit: int) -> bytes:
        if limit < 0:
            raise ValueError("Invalid hiding limit")
        hidden = self.hide_bytes(b)
        return _drop_prefix(hidden[:limit], self._binary) if len(hidden) > limit else hidden

    def hide_json(
        self, obj: Any, *, identifier_fields: frozenset[str] = frozenset(), on_identifier: str = "hash"
    ) -> Any:
        if on_identifier not in ("hash", "refuse"):
            raise ValueError("Invalid identifier policy")

        def identifier(original: Any) -> str:
            if on_identifier == "refuse":
                raise HidingRefused()
            if isinstance(original, str):
                text = original
            else:
                text = json.dumps(original, separators=(",", ":"), ensure_ascii=False)
            return "h-" + hmac.new(self._salt, text.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

        scalars = (type(None), bool, int, float)

        def hidden_key(key: Any) -> Any:
            if type(key) not in (str, *scalars):
                raise TypeError
            text = key if type(key) is str else str(key)
            return identifier(text) if self.hide_text(text) != text else key

        def walk(value: Any) -> Any:
            kind = type(value)
            if kind is dict:
                result = {}
                for key, child in value.items():
                    hidden = walk(child)
                    new_key = hidden_key(key)
                    if key in identifier_fields and hidden != child:
                        hidden = identifier(child)
                    result[new_key] = hidden
                return result
            if kind in (list, tuple):
                return kind(walk(child) for child in value)
            if kind is str:
                return self.hide_text(value)
            if kind in (bytes, bytearray):
                return self.hide_bytes(bytes(value))
            if kind in (int, float):
                hidden = self.hide_text(str(value))
                return hidden if hidden != str(value) else value
            if kind in (type(None), bool):
                return value
            raise TypeError

        try:
            return walk(obj)
        except (TypeError, ValueError, RecursionError):
            raise ValueError("Invalid hiding input") from None


class HidingStream:
    """Hold undecidable suffixes until another chunk or close arrives."""

    def __init__(self, hider: Hider, *, binary: bool = False):
        self._needles = hider._binary if binary else hider._text
        self._buf = b"" if binary else ""
        self._holdback = max((len(n) for n, _ in self._needles), default=1) - 1
        self._closed = False
        self._parts: list[Any] = []
        self._new = 0
        self._quantum = max(64, self._holdback // 2) if self._needles else 0

    def __repr__(self) -> str:
        return f"HidingStream(closed={self._closed})"

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError("HidingStream cannot be serialized")

    def __getstate__(self) -> Any:
        raise TypeError("HidingStream cannot be serialized")

    def feed(self, chunk: Any) -> Any:
        if self._closed:
            raise ValueError("Hiding stream is closed")
        if type(chunk) is not type(self._buf):
            raise TypeError("Invalid hiding chunk")
        # Tiny chunks are coalesced: scanning runs once enough new data has arrived, never per byte.
        # The output is the same as scanning each chunk (the holdback already delays the tail).
        self._parts.append(chunk)
        self._new += len(chunk)
        if self._new < self._quantum:
            return self._buf[:0]
        return self._scan()

    def _scan(self) -> Any:
        self._buf = self._buf[:0].join([self._buf, *self._parts])
        self._parts.clear()
        self._new = 0
        out, end = _hide_upto(self._buf, self._needles, max(0, len(self._buf) - self._holdback))
        self._buf = self._buf[end:]
        return out

    def close(self) -> Any:
        self._closed = True
        buf = self._buf[:0].join([self._buf, *self._parts])
        self._parts.clear()
        out, _ = _hide_upto(buf, self._needles, len(buf))
        self._buf = self._buf[:0]
        return out


_lock = RLock()
_registered: Hider | None = None


def register_hider(h: Hider) -> None:
    if not isinstance(h, Hider):
        raise TypeError("Expected a Hider")
    global _registered
    with _lock:
        _registered = h


def unregister_hider() -> None:
    global _registered
    with _lock:
        _registered = None


def current_hider() -> Hider:
    with _lock:
        if _registered is None:
            raise NoHiderError()
        return _registered


@contextmanager
def use_hider(h: Hider) -> Iterator[Hider]:
    global _registered
    with _lock:
        previous = _registered
        register_hider(h)
    try:
        yield h
    finally:
        with _lock:
            _registered = previous

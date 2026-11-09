"""Contract and security checks for exact-value hiding."""

import ast
import base64
import copy
import hashlib
import hmac
import json
import pickle
import random
import re
import string
import time
import traceback
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest

from orch.errors import Refused
from orch.hider import (
    Hider,
    HidingRefused,
    HidingStream,
    NoHiderError,
    current_hider,
    register_hider,
    unregister_hider,
    use_hider,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
VECTORS = json.loads((CONTRACTS / "vectors/secrets-v1.json").read_text())
TOKEN = 'AbCé/ Q"rStUvWxYz0123456'
MARKER = "[hidden: token]"


def required_forms(value):
    """Independent form examples, including base64 inside larger byte strings."""
    forms = {value, value.encode().hex(), value.encode().hex().upper()}
    for ascii_only in (False, True):
        escaped = json.dumps(value, ensure_ascii=ascii_only)[1:-1]
        forms.update((escaped, escaped.replace("/", "\\/")))
    for encoder in (quote, quote_plus):
        escaped = encoder(value, safe="")
        forms.update((escaped, re.sub(r"%[0-9A-F]{2}", lambda m: m[0].lower(), escaped)))
    for offset in range(3):
        for encoder in (base64.b64encode, base64.urlsafe_b64encode):
            blob = encoder(b"x" * offset + value.encode() + b"suffix").decode()
            first_bit = offset * 8
            last_bit = first_bit + len(value.encode()) * 8
            part = "".join(
                char for index, char in enumerate(blob)
                if index * 6 >= first_bit and (index + 1) * 6 <= last_bit
            )
            for source in (blob, part):
                forms.add(source)
                for url_encoder in (quote, quote_plus):
                    escaped = url_encoder(source, safe="")
                    forms.update((escaped, re.sub(r"%[0-9A-F]{2}", lambda m: m[0].lower(), escaped)))
    return sorted(forms)


def _reference():
    """The reference functions of contracts/validate.py, extracted without running that script."""
    tree = ast.parse((CONTRACTS / "validate.py").read_text())
    wanted = {
        "SEC_MIN_LEN", "sec_b64_forms", "sec_forms", "sec_needles", "_hide_upto", "sec_hide",
        "sec_hide_stream",
    }
    body = []
    for node in tree.body:
        names = {t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)}
        if getattr(node, "name", None) in wanted or names & wanted:
            body.append(node)
    space = {"base64": base64, "json": json}
    exec(compile(ast.Module(body, []), "validate.py", "exec"), space)  # noqa: S102 - our own repo file
    return space


REF = _reference()


@pytest.mark.parametrize("case", VECTORS["hide"], ids=lambda case: case["name"])
def test_equals_reference(case):
    needles = REF["sec_needles"](case["keys"])
    whole = "".join(case["chunks"])
    assert REF["sec_hide"](whole, needles) == case["expect"]
    hider = Hider({key["name"]: key["value"] for key in case["keys"]})
    assert hider.hide_text(whole) == REF["sec_hide"](whole, needles)
    # every reference needle is covered by the library (it may know more forms, never fewer)
    for needle, _ in needles:
        assert hider.hide_text(needle) != needle


def test_reference_forms_covered():
    for value in (TOKEN, "fake-token-Q7xP2mK9vL4", "p@ss w/rd 2026!", 'pa"ss\\word-2026'):
        hider = Hider({"token": value})
        for form in REF["sec_forms"](value):
            assert hider.hide_text("<" + form + ">") == "<" + MARKER + ">"


FORMS = required_forms(TOKEN)


@pytest.fixture(autouse=True)
def clean_registration():
    unregister_hider()
    yield
    unregister_hider()


@pytest.mark.parametrize("case", VECTORS["hide"], ids=lambda case: case["name"])
def test_contract(case):
    hider = Hider({key["name"]: key["value"] for key in case["keys"]})
    whole = "".join(case["chunks"])
    assert hider.hide_text(whole) == case["expect"]
    stream = HidingStream(hider)
    assert "".join(stream.feed(chunk) for chunk in case["chunks"]) + stream.close() == case["expect"]
    binary = HidingStream(hider, binary=True)
    streamed = b"".join(binary.feed(c.encode()) for c in case["chunks"]) + binary.close()
    assert streamed == case["expect"].encode()
    assert hider.hide_bytes(whole.encode()) == case["expect"].encode()


@pytest.mark.parametrize("case", VECTORS["min_len"])
def test_minimum(case):
    hider = Hider({"token": case["value"]})
    assert hider.hide_text(case["value"]) == (MARKER if case["hidden"] else case["value"])
    if not case["hidden"]:
        for form in required_forms(case["value"]):
            assert hider.hide_text(form) == form


@pytest.mark.parametrize("form", FORMS)
def test_forms_and_all_splits(form):
    hider = Hider({"token": TOKEN})
    text = "before:" + form + ":after"
    expected = hider.hide_text(text)
    assert MARKER in expected
    assert form not in expected
    assert hider.hide_bytes(text.encode()) == expected.encode()
    for binary in (False, True):
        source = text.encode() if binary else text
        want = expected.encode() if binary else expected
        empty = source[:0]
        for offset in range(len(source) + 1):
            stream = HidingStream(hider, binary=binary)
            assert stream.feed(source[:offset]) + stream.feed(source[offset:]) + stream.close() == want
        stream = HidingStream(hider, binary=binary)
        assert empty.join(stream.feed(source[i:i + 1]) for i in range(len(source))) + stream.close() == want


def test_quote_base64_variants():
    value = "+++>>>???///xyz"
    hider = Hider({"token": value})
    for encoder in (quote, quote_plus):
        form = encoder(base64.b64encode(value.encode()).decode(), safe="")
        assert hider.hide_text(form) == MARKER
        assert hider.hide_text(re.sub(r"%[0-9A-F]{2}", lambda m: m[0].lower(), form)) == MARKER


def test_cut():
    hider = Hider({"token": TOKEN})
    text = "prefix " + TOKEN + " suffix"
    hidden = hider.hide_text(text)
    assert hider.hide_cut(text, 12) == hidden[:12]
    for form in FORMS[:1] + [TOKEN]:
        assert hider.drop_trailing_prefix("!" + form[:4]) == "!"
    assert hider.drop_trailing_prefix("!" + TOKEN[:3]) == "!" + TOKEN[:3]
    assert hider.hide_cut("!" + TOKEN[:6], 100) == "!" + TOKEN[:6]
    for source in (text, "!" + TOKEN[:12] + " rest"):
        for limit in range(len(source) + 1):
            result = hider.hide_cut(source, limit)
            if limit < len(hider.hide_text(source)):
                assert not any(result.endswith(TOKEN[:n]) for n in range(4, len(TOKEN)))
            assert len(result) <= limit
    assert hider.hide_cut("!" + TOKEN[:12] + " rest", 13) == "!"
    binary = ("!" + TOKEN[:12] + " rest").encode()
    assert hider.hide_cut_bytes(binary, len(("!" + TOKEN[:12]).encode())) == b"!"
    assert hider.hide_cut_bytes(TOKEN.encode(), 100) == MARKER.encode()
    for method, source in ((hider.hide_cut, text), (hider.hide_cut_bytes, text.encode())):
        with pytest.raises(ValueError, match="Invalid hiding limit"):
            method(source, -1)


def test_json():
    hider = Hider({"token": TOKEN, "digits": "12345678"}, salt=b"fixed")
    original = {"ordinary": [TOKEN, (TOKEN, 123456789, 12345678.25)], "safe": {"x": 7}, "bool": True}
    result = hider.hide_json(original)
    assert result == {
        "ordinary": [MARKER, (MARKER, "[hidden: digits]9", "[hidden: digits].25")],
        "safe": {"x": 7}, "bool": True,
    }
    assert result is not original and result["safe"] is not original["safe"]
    assert original["ordinary"][0] == TOKEN
    obj = {"command": TOKEN, TOKEN: "safe"}
    expected_hash = "h-" + hmac.new(b"fixed", TOKEN.encode(), hashlib.sha256).hexdigest()[:16]
    result = hider.hide_json(obj, identifier_fields=frozenset({"command"}))
    assert result == {"command": expected_hash, expected_hash: "safe"}
    assert hider.hide_json(obj, identifier_fields=frozenset({"command"})) == result
    assert TOKEN not in repr(result)
    assert Hider({"token": TOKEN}).hide_json({TOKEN: 1}) != Hider({"token": TOKEN}).hide_json({TOKEN: 1})
    for obj in ({"command": TOKEN}, {TOKEN: 1}):
        with pytest.raises(HidingRefused):
            hider.hide_json(obj, identifier_fields=frozenset({"command"}), on_identifier="refuse")
    assert hider.hide_json({"command": "safe"}, on_identifier="refuse") == {"command": "safe"}


def test_json_needle_and_multiline():
    obj = {"value": TOKEN, "lines": "abcdefghijklmnop\nqrstuvwxyz012345\nshort"}
    hider = Hider({"token": obj})
    compact = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    assert hider.hide_text(compact) == MARKER
    for text in (TOKEN, "abcdefghijklmnop", "qrstuvwxyz012345"):
        assert hider.hide_text(text) == MARKER
    assert hider.hide_text("short") == "short"
    assert Hider({"token": [TOKEN]}).hide_text(TOKEN) == MARKER
    assert Hider({"token": {}}).hide_text("{}") == "{}"


def test_registration():
    assert issubclass(NoHiderError, Refused)
    with pytest.raises(NoHiderError):
        current_hider()
    first, second = Hider({}), Hider({"token": TOKEN})
    register_hider(first)
    with use_hider(second):
        assert current_hider() is second
        with use_hider(first):
            assert current_hider() is first
        assert current_hider() is second
    assert current_hider() is first
    with pytest.raises(RuntimeError), use_hider(second):
        raise RuntimeError("test")
    assert current_hider() is first
    unregister_hider()
    with use_hider(first):
        assert current_hider() is first
    with pytest.raises(NoHiderError):
        current_hider()
    with pytest.raises(TypeError):
        register_hider(TOKEN)


def test_no_leaks():
    hider = Hider({"token": TOKEN})
    assert len(TOKEN) == 24
    assert hider.names == ("token",)
    assert str(hider) == repr(hider)
    stream = HidingStream(hider)
    stream.close()
    operations = [
        lambda: pickle.dumps(hider), lambda: copy.deepcopy(hider), lambda: copy.copy(hider),
        lambda: hider.__getstate__(), lambda: hider.hide_cut(TOKEN, -1),
        lambda: hider.hide_cut_bytes(TOKEN.encode(), -1),
        lambda: hider.hide_json(TOKEN, on_identifier=TOKEN),
        lambda: hider.hide_json({TOKEN: 1}, on_identifier="refuse"),
        lambda: hider.hide_json({"command": TOKEN}, identifier_fields={"command"}, on_identifier="refuse"),
        lambda: stream.feed(TOKEN), current_hider, lambda: register_hider(TOKEN),
        lambda: Hider({"token": object()}), lambda: HidingStream(hider).feed(TOKEN.encode()),
    ]
    for operation in operations:
        with pytest.raises((TypeError, ValueError, HidingRefused, NoHiderError)) as caught:
            operation()
        rendered = repr(hider) + str(caught.value) + repr(caught.value) + repr(caught.value.args)
        rendered += "".join(traceback.format_exception(caught.value))
        for form in FORMS:
            assert form not in rendered


@pytest.mark.parametrize("operation", [pickle.dumps, copy.copy, copy.deepcopy])
def test_copying_refused(operation):
    with pytest.raises(TypeError):
        operation(Hider({"token": TOKEN}))


def test_order_overlap_and_identity():
    hider = Hider({"z": "abcdefgh", "a": "abcdefgh", "long": "abcdefghijk", "overlap": "fghijklm"})
    assert hider.names == ("a", "long", "overlap", "z")
    assert hider.hide_text("abcdefghijklm abcdefgh") == "[hidden: long]lm [hidden: z]"
    # An overlapping occurrence of the same needle may be the next eligible match.
    hider = Hider({"x": "abababab"})
    assert hider.hide_text("abababababababab") == "[hidden: x][hidden: x]"
    hider = Hider({})
    assert hider.hide_text(TOKEN) == TOKEN
    assert hider.hide_bytes(TOKEN.encode()) == TOKEN.encode()
    for binary in (False, True):
        stream = HidingStream(hider, binary=binary)
        chunk = TOKEN.encode() if binary else TOKEN
        assert stream.feed(chunk) == chunk
        assert stream.close() == chunk[:0]
        assert stream.close() == chunk[:0]
        with pytest.raises(ValueError):
            stream.feed(chunk)


def test_performance():
    rng = random.Random(42)
    tokens = ["".join(rng.choices(string.ascii_letters + string.digits, k=32)) for _ in range(10)]
    hider = Hider({f"key{i}": token for i, token in enumerate(tokens)})
    text = "." * (1024 * 1024) + " ".join(tokens)
    start = time.perf_counter()
    result = hider.hide_text(text)
    elapsed = time.perf_counter() - start
    assert result.count("[hidden:") == 10
    assert elapsed < 1.5


def test_json_rejects_and_hides_non_json_values():
    hider = Hider({"token": TOKEN})

    class Sneaky:
        def __str__(self):
            return TOKEN

    assert hider.hide_json({"b": TOKEN.encode(), "ba": bytearray(b"x" + TOKEN.encode())}) == {
        "b": MARKER.encode(), "ba": b"x" + MARKER.encode(),
    }
    plain = {1: None, 2.5: True, None: 0, False: [1]}
    assert hider.hide_json(plain) == plain
    bads = ({TOKEN}, Sneaky(), {"k": Sneaky()}, {(1, 2): 1}, {"k": {TOKEN}}, {Sneaky(): 1}, {"k": object()})
    for bad in bads:
        with pytest.raises(ValueError, match="Invalid hiding input") as caught:
            hider.hide_json(bad)
        assert TOKEN not in str(caught.value) + repr(caught.value.args)
    digits = Hider({"d": "12345678"}, salt=b"s")
    result = digits.hide_json({12345678: 1})
    assert list(result) != [12345678] and "12345678" not in repr(result)
    with pytest.raises(HidingRefused):
        digits.hide_json({12345678: 1}, on_identifier="refuse")

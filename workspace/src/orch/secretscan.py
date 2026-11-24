"""One secret scanner for text: the token patterns, key=value pairs, flag values and the values of this
workspace's own stored keys. `orch secret scan` and the phone view's redact/file scan all use it, so there
is one list. A finding names a kind and a line, never the matched text."""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

from orch.errors import Refused

MAX_BYTES = 1_000_000

_RX = [
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?(-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
        re.S,
    ),  # PEM and PGP (PRIVATE KEY BLOCK)
    re.compile(
        r"\b(?:orn|orp|ora|ors|whk|opk|apv|odt)_[A-Za-z0-9_-]{16,}"
    ),  # ors_: a signing key (signkey.py); odt_: dashboard login token (ORCH-1035)
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
    "keys-unreadable": "text orch could not compare with your saved keys",
}


def too_large(n: int) -> bool:
    return n > MAX_BYTES


NOTE_SKIPPED = "Couldn't read your saved keys, so this check skipped them. Every other secret check ran."
_noted = False


def note_skipped(root: Path | None = None) -> None:
    """The visible note when a send skipped the stored-key comparison: once per process on stderr (a CLI user
    sees it next to the result), every time in the debug log. Never silent."""
    global _noted
    if not _noted:
        _noted = True
        print(NOTE_SKIPPED, file=sys.stderr)
    try:
        from orch import diag

        diag.log("secretscan.stored_keys_unreadable", "warn", root=root)
    except Exception:  # noqa: BLE001 - the note on stderr already reached the user
        pass


def stored_keys_readable(root: Path) -> bool:
    from orch import phone_results

    return phone_results.value_hider(root) is not None


def keys_unreadable_reason(root: Path | None) -> str:
    """Why the saved keys of `root` cannot be read, in the core's own words (e.g. "this folder's saved keys
    still belong to <old folder> ... run orch workspace move-here"), for a refusal that would otherwise only
    say "secret". Never a value: the reasons are orch's refusals, which name no key value."""
    try:
        from orch import keystore

        keystore.all_needles(root)
    except Exception as e:  # noqa: BLE001 - only to say why; the caller stays refused either way
        text = " ".join(str(e).split()).removeprefix("Refused: ")[:1000]
        if text:
            return text
    return "orch could not read them just now. Try again in a moment."


def unreadable_refusal(root: Path | None) -> str:
    why = keys_unreadable_reason(root)
    return f"orch could not compare the text with your saved keys, so it stays refused: {why}"


def find(text: str, root: Path | None = None, *, strict: bool = True, labels: bool = True) -> list[dict]:
    """[{kind, line}] (line from 1, one entry per kind and line), in text order. Pattern kinds first, then any
    other line the phone view's scrub would change (key=value, spaced values, flag values), then lines that
    hold a stored key value of the workspace (`root`). A stored-key check that cannot run reports `stored-key`
    on line 1 (fail closed) when `strict`. With strict=False (sends: relay, publish) only that comparison is
    skipped, with a visible note (note_skipped); every other detector still runs and blocks. With labels=False
    the line scrub (key=value, spaced values, flag values) is skipped: only for the raw bytes of a picture
    whose pixel runs were proven (pngpixels), which then get the full rules in their label_view (passes)."""
    from orch import phone_view

    found: dict[tuple[int, str], None] = {}

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            found[(line_of(m.start()), kind)] = None
    flagged = {ln for ln, _ in found}
    # A line's verdict depends only on its own text: each distinct line is checked once (a big file of
    # repeated lines took minutes; ORCH-260).
    scrubbed: dict[str, bool] = {}
    for n, raw in enumerate(text.split("\n") if labels else (), 1):
        if n in flagged:
            continue
        hit = scrubbed.get(raw)
        if hit is None:
            forms = (raw, phone_view._clean_full(raw), unicodedata.normalize("NFKC", raw))
            hit = scrubbed[raw] = any(phone_view._scrub_text(f) != f for f in dict.fromkeys(forms))
        if hit:
            found[(n, "secret-value")] = None
    if root is not None:
        from orch import phone_results

        h = phone_results.value_hider(root)
        if h is None:
            if strict:
                found[(1, "keys-unreadable")] = None  # fail closed, own kind: the reason, never "secret"
            else:
                note_skipped(root)
        else:
            try:
                hidden: dict[str, bool] = {}
                for n, raw in enumerate(text.split("\n"), 1):
                    hit = hidden.get(raw)
                    if hit is None:
                        bare = raw.replace("\r", "")
                        hit = hidden[raw] = h.hide_text(raw) != raw or h.hide_text(bare) != bare
                    if hit:
                        found[(n, "stored-key")] = None
                if not any(k == "stored-key" for _, k in found) and h.hide_text(text) != text:
                    found[(1, "stored-key")] = None  # a value that spans lines
            except Exception:  # noqa: BLE001 - never a pass
                found[(1, "stored-key")] = None
    return [{"kind": k, "line": ln} for (ln, k) in sorted(found)]


def refusal(found: list[dict], root: Path | None = None) -> str:
    """One sentence for the first hit. When the saved keys could not be compared, that comes first, with the
    core's reason and the way out (a moved folder names its command), never "a secret" for harmless text."""
    if any(f["kind"] == "keys-unreadable" for f in found):
        return unreadable_refusal(root)
    first = found[0]
    more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
    return (
        f"The text has {WORDS.get(first['kind'], 'a secret')} on line {first['line']}{more}. "
        "Remove it and try again."
    )


# Protocol fields that the wire needs and that are no content: only these top-level names are skipped, so a
# nested field called "token" or "key" is still scanned. Ids and hashes are NOT skipped (a secret put into an
# "id" is still a secret); they never look like one. Dict keys are scanned too.
_ALLOW_TOKEN = re.compile(r"ora_[A-Za-z0-9_-]{22}")  # the one-time allow token a delegate/start/allow carries
_ALLOW_FIELDS = {"allow_token", "token"}


def _leaves(doc, path: str = "", top: bool = True):
    """(field, text) for every string in a message body, nested ones too, and every dict key (named
    "field name", never by the key itself). The protocol fields above are skipped only in the OUTERMOST dict:
    a dict nested anywhere (also inside a list) is content."""
    if isinstance(doc, str):
        if doc:
            yield path or "text", doc
    elif isinstance(doc, dict):
        for k, v in doc.items():
            if top and k in _ALLOW_FIELDS and isinstance(v, str) and _ALLOW_TOKEN.fullmatch(v):
                continue  # the allow token sent on purpose; all else is scanned
            if isinstance(k, str) and k:
                yield f"{path}.field name" if path else "field name", k
            yield from _leaves(v, f"{path}.{k}" if path else str(k), False)
    elif isinstance(doc, (list, tuple)):
        for v in doc:
            yield from _leaves(v, path, False)


def _after(verb: str) -> str:
    return "Remove it and send again." if verb == "sent" else "Remove it and try again."


def refuse_if_secret_in(root: Path | None, body, what: str = "message", *, verb: str = "sent") -> None:
    """R5.2: nothing leaves this machine (relay, publish) with a secret in it. The one scanner, run on every
    string of the body. A hit raises Refused with one sentence naming the kind and the field, never the value.
    Fails closed when the scan itself breaks. verb: what did not happen ("sent"; "saved" for evidence)."""
    leaves = list(_leaves(body))
    if not leaves:
        return
    starts: list[tuple[int, str]] = []  # (first line in the joined text, field)
    lines = 1
    parts = []
    for field, text in leaves:
        starts.append((lines, field))
        parts.append(text)
        lines += text.count("\n") + 1
    try:
        found = find("\n".join(parts), root, strict=False)
    except Exception:  # noqa: BLE001 - a scan that cannot run is never a pass
        raise Refused(
            f"orch could not check the {what} for secrets, so nothing was {verb}. Try again."
        ) from None
    if not found:
        return
    first = found[0]
    field = next(f for ln, f in reversed(starts) if ln <= first["line"])
    more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
    kind = WORDS.get(first["kind"], "a secret")
    raise Refused(
        f"The {what} has {kind} in its {field.split('.')[-1]}{more}, so nothing was {verb}. " + _after(verb)
    )


def passes(data: bytes) -> list[tuple[bytes, bool]]:
    """(bytes, labels) to scan for a file: the file with every rule; or, for a PNG whose compressed pixel runs
    are proven (pngpixels: only Huffman-coded deflate data, which spells a short label by chance in about half
    of all screenshots, #1022), its label_view with every rule and the whole file with the token patterns and
    the stored-key check (labels=False). Any doubt about the picture: every byte, every rule."""
    from orch import pngpixels

    view = pngpixels.label_view(data) if data.startswith(pngpixels.MAGIC) else None
    return [(data, True)] if view is None else [(view, True), (data, False)]


def _views(window: bytes):
    """Every reading of a window of bytes that could show a secret: UTF-8, Latin-1, and UTF-16 (either byte
    order, either alignment). No guessing which one the file "really" is: all of them are scanned."""
    yield window.decode("utf-8", "replace")
    yield window.decode("latin-1")
    for off in (0, 1):
        part = window[off : len(window) - ((len(window) - off) % 2)]
        yield part.decode("utf-16-le", "replace")
        yield part.decode("utf-16-be", "replace")


_UNPACK_DEPTH = 3
_UNPACK_LIMIT = 256 * 1024 * 1024  # all unpacked bytes of one file; a bigger container is refused, not skipped


def _unpacked(data: bytes, budget: list[int], depth: int = 0):
    """The bytes themselves, then (zip, docx and the like, gzip, tar) everything inside, nested up to a few
    levels: a secret inside a compressed stream is as much a leak as one in the clear (#915)."""
    import gzip
    import io
    import tarfile
    import zipfile

    yield data
    if depth >= _UNPACK_DEPTH:
        return

    def take(chunk: bytes):
        budget[0] -= len(chunk)
        if budget[0] < 0:
            raise OverflowError("container too large")
        yield from _unpacked(chunk, budget, depth + 1)

    try:
        if data[:2] == b"PK" and zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    if info.file_size > budget[0]:
                        raise OverflowError("container too large")
                    yield from take(z.read(info))
        elif data[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as g:
                chunk = g.read(budget[0] + 1)
            yield from take(chunk)
        elif len(data) > 512 and data[257:262] == b"ustar":
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                for m in t:
                    f = t.extractfile(m) if m.isfile() else None
                    if f is not None:
                        yield from take(f.read(budget[0] + 1))
    except OverflowError:
        raise
    except Exception:  # noqa: BLE001 - not a readable container after all: the bytes above were scanned
        return


def _scan_bytes(data: bytes, root: Path | None) -> list[dict]:
    step, overlap = MAX_BYTES, 65536
    assert step > 2 * overlap and (step - overlap) % 2 == 0  # windows advance, and keep their alignment
    for blob, labels in passes(data):
        for start in range(0, max(len(blob), 1), step - overlap):
            for text in _views(blob[start : start + step]):
                found = find(text, root, strict=False, labels=labels)
                if found:
                    return found
            if start + step >= len(blob):
                break
    return []


def refuse_if_secret(
    data: bytes, what: str = "file", root: Path | None = None, *, verb: str = "sent"
) -> None:
    """The same scanner over a file about to be uploaded: the whole file, in overlapping windows, each window
    read in every encoding (_views) with the full find() including the stored-key check. A PNG's proven pixel
    runs are kept from the label rules only (passes). A zip, gzip or tar is scanned inside as well."""
    found: list[dict] = []
    try:
        for blob in _unpacked(data, [_UNPACK_LIMIT]):
            found = _scan_bytes(blob, root)
            if found:
                break
    except Exception:  # noqa: BLE001 - a scan that cannot run is never a pass
        raise Refused(
            f"orch could not check the {what} for secrets, so nothing was {verb}. Try again."
        ) from None
    if found:
        raise Refused(
            f"The {what} has {WORDS.get(found[0]['kind'], 'a secret')}, so nothing was {verb}. "
            + _after(verb)
        )

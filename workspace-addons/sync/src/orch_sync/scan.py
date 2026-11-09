"""Secret scan for what the sync add-on would commit or accept (git step 2, design D5). Pure: bytes + path in,
findings out, no git and no files. The caller feeds the FULL bytes of each blob (`git cat-file -p`), never a diff.

A finding with needs_click=False stops the whole step. A finding with needs_click=True ("can't check": an
archive or a file that is neither text nor a known media type) is held until a person clicks Allow once for that
file hash. Findings never contain the matched text.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

# name -> pattern. Run on the raw bytes (also with NUL bytes removed, which exposes UTF-16 text).
PATTERNS = {
    "orp-token": rb"(?<![A-Za-z0-9_])orp_[A-Za-z0-9_-]{20,}",
    "orn-token": rb"(?<![A-Za-z0-9_])orn_[A-Za-z0-9_-]{20,}",
    "private-key": rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    "github-token": rb"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
    "api-key": rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}",
    "aws-key": rb"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])",
    "slack-token": rb"(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}",
}
TICKET_PATTERNS = {"token-field": rb'"token"\s*:\s*"'}  # any ticket JSON

NEVER_DIRS = {"me", "secrets", "chat", "run", "inbox", "addons", "harness"}
_NAME_RE = re.compile(
    r"^(\.env.*|.*\.(pem|key|p8|p12|pfx|kdbx)|id_rsa.*|id_ed25519.*|credentials.*)$", re.IGNORECASE
)
_ARCHIVE_EXT = (".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".apk")
_ARCHIVE_MAGIC = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"\x1f\x8b",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
    b"BZh",
    b"\xfd7zXZ\x00",
)
_MEDIA_MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"OggS",
    b"ID3",
    b"\x1a\x45\xdf\xa3",
)
# a signature inside a "picture" means something is hidden in it (PDFs can carry compressed text: always a click)
_EMBEDDED = tuple(m for m in _ARCHIVE_MAGIC if m != b"\x1f\x8b") + (b"\x1f\x8b\x08",)
_TICKET_RE = re.compile(r"^tickets/t_[a-z0-9]{6,16}\.json$")


@dataclass(frozen=True)
class Finding:
    path: str
    code: str  # "path" | "secret" | "cannot-check"
    rule: str
    needs_click: bool = False
    sha256: str = ""  # cannot-check only: the hash the click approves


def _is_media(data):
    return (
        data.startswith(_MEDIA_MAGIC)
        or (data[:4] == b"RIFF" and data[8:12] in (b"WEBP", b"WAVE", b"AVI "))
        or data[4:8] == b"ftyp"
    )


def _is_text(data):
    if b"\x00" in data[:8192] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    try:
        data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8")
        return True
    except UnicodeDecodeError:
        return False


_IGNORABLE = {0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFFA0}
_IGNORABLE_RANGES = ((0x180B, 0x180F), (0xFE00, 0xFE0F), (0xE0100, 0xE01EF), (0xFFF0, 0xFFF8))


def _ignorable(c):
    o = ord(c)
    return (
        unicodedata.category(c) == "Cf" or o in _IGNORABLE or any(a <= o <= b for a, b in _IGNORABLE_RANGES)
    )


def norm_segment(seg):
    """The one form every path comparison uses: NFKC, default-ignorable code points (zero-width etc.) removed,
    casefolded. macOS/Windows are case-insensitive and Unicode-normalizing, so `Secrets`, `se\u200bcrets` and
    an NFD spelling all name the same folder there."""
    seg = "".join(c for c in unicodedata.normalize("NFKC", seg) if not _ignorable(c))
    return unicodedata.normalize("NFKC", seg.casefold())


def norm_path(path):
    """Normalized segments (list), or None when the path is unsafe: absolute, backslash, drive letter, empty,
    '.' or '..' segment (also after normalization), a segment ending in a dot or space, a ':', or a control character."""
    if (
        not path
        or path.startswith(("/", "\\"))
        or "\\" in path
        or ":" in path
        or any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in path)
    ):
        return None
    raw = path.split("/")
    parts = [norm_segment(p) for p in raw]
    # Windows drops a trailing dot or space: `me./x` would land in `me/` there
    if any(p in ("", ".", "..") or p[-1] in ". " for p in parts + raw):
        return None
    return parts


def scan_path(path):
    """Path rules only. Findings for a path that must never be synced."""
    parts = norm_path(path)
    if parts is None:
        return [Finding(path, "path", "unsafe-path")]
    out = []
    if parts[0] in NEVER_DIRS:
        out.append(Finding(path, "path", "never-synced-folder"))
    if any(_NAME_RE.match(p) for p in parts):
        out.append(Finding(path, "path", "secret-file-name"))
    return out


class _Pairs(list):
    """A JSON object kept as its list of (key, value) pairs, repeated keys included."""


def _json_hits(data, is_ticket):
    """Rule names found in the PARSED strings (keys and values) of a JSON file. Not parseable = no extra hits
    (the byte scan above already ran). Iterative walk, no recursion."""
    try:
        doc = json.loads(data, object_pairs_hook=_Pairs)
    except Exception:  # noqa: BLE001 - includes RecursionError on absurd nesting
        return set()
    hits, stack = set(), [doc]
    while stack:
        v = stack.pop()
        if isinstance(v, _Pairs):  # every pair, so a repeated key cannot hide the first value
            for k, x in v:
                if is_ticket and isinstance(x, str) and norm_segment(k) == "token":
                    hits.add("token-field")
                stack.append(k)
                stack.append(x)
        elif isinstance(v, list):
            stack.extend(v)
        elif isinstance(v, str):
            raw = v.encode("utf-8", "replace")
            hits |= {n for n, pat in PATTERNS.items() if re.search(pat, raw)}
    return hits


def scan_blob(path, data):
    """All findings for one blob: path rules, token forms in the full bytes, archives and unreadable files."""
    out = scan_path(path)
    haystacks = [data] + ([data.replace(b"\x00", b"")] if b"\x00" in data else [])
    pats = dict(PATTERNS)
    parts = norm_path(path)
    if parts is not None and _TICKET_RE.match("/".join(parts)):
        pats.update(TICKET_PATTERNS)
    hits = {name for name in pats if any(re.search(pats[name], h) for h in haystacks)}
    is_ticket = parts is not None and _TICKET_RE.match("/".join(parts))
    if is_ticket or path.lower().endswith(".json"):
        hits |= _json_hits(data, is_ticket)  # \u escapes hide tokens from the byte patterns
    out += [Finding(path, "secret", name) for name in sorted(hits)]
    low = path.lower()
    archive = low.endswith(_ARCHIVE_EXT) or data.startswith(_ARCHIVE_MAGIC) or data[257:262] == b"ustar"
    why = "archive" if archive else None
    if not why and data.startswith(b"%PDF-"):
        why = "pdf"
    elif not why and _is_media(data) and any(sig in data[8:] for sig in _EMBEDDED):
        why = "media-with-archive"
    elif not why and not (_is_media(data) or _is_text(data)):
        why = "unknown-format"
    if why:
        out.append(Finding(path, "cannot-check", why, True, hashlib.sha256(data).hexdigest()))
    return out


def blocking(findings, allowed_hashes=()):
    """The findings that stop the step: everything except cannot-check ones whose hash a person allowed."""
    return [f for f in findings if not (f.needs_click and f.sha256 in set(allowed_hashes))]

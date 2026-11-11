"""The ticket snapshot the phone's ticket chat shows (message.schema.json `body.ticket_view`).

Built from the ticket file: title, status, tasks, the last 30 history lines in plain words, and
the proof marked for the phone (evidence with role result or check: files are uploaded as relay
blobs, URLs and PRs become links), artifacts named in questions, options, summary or description, and the
ticket's refs. Secrets are cut from display text before it leaves.

It rides on update texts to phones (result, failure, stopped, question) and, quietly (kind note,
never pushed), when the tasks of a ticket the phone follows change: `sync` runs on every relay
inbox pull, at most once per DEBOUNCE seconds per ticket. State: .orch/secrets/phone-views.json.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime
from pathlib import Path

from orch import net, phone_results, refs, runs, safefile, tickets
from orch.errors import Refused
from orch.text import clean_untrusted

CAP = 16384  # the relay refuses a bigger ticket_view (compact UTF-8 JSON)
BUDGET = 15000  # what we aim for, a margin below the cap
SEND_KINDS = ("result", "failure", "stopped", "question")
PHONE_ROLES = ("result", "check")
DEBOUNCE = 20  # seconds between two quiet snapshots of one ticket
BLOB_DAYS = 30  # re-upload a cached blob after this (the relay deletes blobs after 90 days)
HISTORY = 30
ATTACHMENTS = 50
ARTIFACT_BYTES = 20 * 1024 * 1024
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic"}

_SECRET_PATTERNS = [
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?(-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
        re.S,
    ),  # PEM and PGP (PRIVATE KEY BLOCK)
    re.compile(r"\b(?:orn|orp|ora|whk|opk|apv)_[A-Za-z0-9_-]{16,}"),
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
# The ONE list of secret-name words: the key=value pattern of redact/_has_secret and secret_name() (labels of
# phone results) are both built from it, so a word added here reaches both (tests/test_phone_results.py).
SECRET_NAME_WORDS = (
    "passw", "passphrase", "passcode", "secret", "token", "credential", "bearer", "signature", "auth",
    "authoriz", "api key", "access key", "private key", "db pass", "sessid", "sessionid",
)  # fmt: skip
# whole words only (not inside another word). A bare "pass" counts, and so does any word that ENDS in pass
# (SSHPASS, DBPASS, smtppass; bypass and compass over-redact, accepted); secret_name drops the known harmless
# test-result phrases first (Pass/Fail, pass rate, pass count).
SECRET_LABEL_WORDS = (
    "pass",
    "key",
    "keys",
    "pin",
    "pincode",
    "pwd",
    "pw",
    "otp",
    "totp",
    "cookie",
    "cookies",
    "session",
    "sessions",
    "sig",  # an Azure SAS signature (&sig=), as in the query parameter names
    "sid",  # connect.sid
)


def _words_rx(sep: str) -> str:
    """The alternation of SECRET_NAME_WORDS; a space inside a word is `sep`. `auth` leaves Author, Authored,
    Authoring and Authority alone (Authorization is the word `authoriz`)."""
    parts = []
    for w in SECRET_NAME_WORDS:
        rx = sep.join(re.escape(x) for x in w.split(" "))
        parts.append(rx + (r"(?!or)" if w == "auth" else ""))
    return "|".join(parts)


# `name: value`. The name is captured as a whole run of name characters (letters, digits, _ - .) and
# ONE predicate, secret_name() (NFKC, camelCase, _ - . split), decides whether it is a secret name;
# no second regex. A name that is not secret never swallows a pair in its value: the scan goes on
# right after its separator (Config: password=x, a=1,token=x, user=bob&secret=x). Linear: the
# lookbehind allows one start per run, the run is possessive, and the value is only matched for a
# secret name. Authorization: Bearer x takes scheme AND token.
# A quoted or subscripted name counts ({"password": x}, config['token'] = x, os.environ["DB_PASSWORD"] = x):
# one closing quote and one `]` may stand between the name and the separator (group 2 keeps them, so the
# text around stays); the quote may be escaped by any number of backslashes (JSON inside a JSON string,
# a logged request body: {\"password\":\"x\"}, {\\\"token\\\": x}). Separators: : = := ?= += => (Go, Make,
# PHP/Ruby/Perl). A `:` value (YAML, headers, `password: correct horse battery`) and any cookie value
# (Cookie: a=1; sessionid=x) is hidden to the end of its line; an `=` value is one token or one quoted string.
_KV_HEAD = re.compile(r"(?<![\w.-])([\w.-]++)((?:\\*+[\"'`])?\]?\s*+(?P<sep>=>|:=|[?+]?=|:)\s*+)")
_KV_VAL = re.compile(
    r"(?:(?:bearer|basic|token|digest)\s++)?"
    r"(?:\"(?:[^\"\\\n]|\\.)*+\"?|'(?:[^'\\\n]|\\.)*+'?|`[^`\n]*+`?|\S++)",
    re.I,
)  # a quote (\" escapes inside) to its closing quote, an unclosed one to the end of the line, else one token
_TO_EOL = re.compile(r"(?i)cookie")


class _Hit:
    """What callers use of a regex match: group(0..3), start(), end() (1 name, 2 separator, 3 value)."""

    def __init__(self, text, head, end):
        self._g = (text[head.start() : end], head.group(1), head.group(2), text[head.end() : end])
        self._span = (head.start(), end)

    def group(self, i=0):
        return self._g[i]

    def start(self):
        return self._span[0]

    def end(self):
        return self._span[1]


class _KV:
    """The `name: value` scan (finditer/search/sub like a compiled regex). finditer and search look at the raw
    AND the NFKC form (a fullwidth name is caught); sub works on the text as given (redact normalizes)."""

    @staticmethod
    def _hits(text):
        pos = 0
        while (head := _KV_HEAD.search(text, pos)) is not None:
            pos = head.end()
            if not secret_name(head.group(1)):
                continue
            if head.group("sep") == ":" or _TO_EOL.search(head.group(1)):
                end = _line_end(text, pos)  # the rest of the line, scanned once: the scan goes on after it
            else:
                val = _KV_VAL.match(text, pos)
                end = val.end() if val is not None else pos
            if end > pos:
                yield _Hit(text, head, end)
                pos = end

    @classmethod
    def finditer(cls, text):
        norm = unicodedata.normalize("NFKC", text)
        yield from cls._hits(text)
        if norm != text:
            yield from cls._hits(norm)

    @classmethod
    def search(cls, text):
        return next(cls.finditer(text), None)

    @classmethod
    def sub(cls, repl, text):
        out, last = [], 0
        for hit in cls._hits(text):
            out.append(text[last : hit.start()])
            out.append(repl(hit))
            last = hit.end()
        out.append(text[last:])
        return "".join(out)


_SECRET_KV = _KV()

# Command-line flags. A long flag whose name secret_name() accepts (the one predicate, no second word list)
# hides the value after it: --password x, --password=x, --token x, --api-key "a b" (an en or em dash for --
# too: word processors make one of it). A short flag only after one of _FLAG_COMMANDS, anywhere on its line
# (after a prompt, sudo, a path, `&&`, `|`, `docker compose exec db`; .exe too), and only that command's
# password flag, case-sensitive (mysql -P is the port), alone or last in a cluster: mysql -pX / -p X,
# sshpass -p x, redis-cli -a x, curl -u user:pass, curl -su user:pass. -p 8080, ls -a, psql -p 5432 and
# --port 8080 stay. The value stays on the flag's line, and a command's flags end where the next command on
# the line starts. A secret long flag followed by another long flag has no value (--password --token x: x
# is hidden). Argv lists and quoted arguments count too (subprocess.run(["mysql", "-phunter2"]),
# command: ["redis-server", "--requirepass", "x"], "args": ["--token", "x"], sh -c 'mysql "-px"'): a flag
# may start right after a quote, `[`, `,` or `(`, its value may be the next quoted list item, and a value
# inside the flag's own quotes ends at the closing quote. Linear: one lookbehind-guarded start per flag
# and per path run, possessive runs, each line end is found once, and every scan goes on after the last
# one (nothing is scanned twice).
_FLAG_COMMANDS = {
    "mysqldump": "p",
    "mysql": "p",
    "mariadb-dump": "p",
    "mariadb": "p",
    "mysqladmin": "p",
    "mysqlimport": "p",
    "mysqlcheck": "p",
    "sshpass": "p",
    "redis-cli": "a",
    "curl": "u",
}
_LIST_SEP = r"[\"'`]\s*+,\s*+"  # "--token", "x": the end of one quoted list item and the start of the next
_LONG_FLAG = re.compile(rf"(?<![\w.-])(?:--|[\u2013\u2014])([\w.-]++)(?:=|[ \t]++|(?P<item>{_LIST_SEP}))")
# The boolean (argument-less) short flags per command, which may stand before the password letter in one
# cluster (curl -su x, mysql -sNpX). A cluster whose earlier letter is not one of them is not a cluster: the
# text after that letter is its value (mysql -upX: the user is pX), not a password.
_BOOL_SHORT = {
    "mysql": "ABCEGHINTUVWbfinqrstvw",
    "mysqldump": "acdefklnqQRtvx",
    "mariadb": "ABCEGHINTUVWbfinqrstvw",
    "mariadb-dump": "acdefklnqQRtvx",
    "mysqladmin": "EfrsvV",
    "mysqlimport": "dfiLlrsv",
    "mysqlcheck": "1aABcCeFfgmoqrsv",
    "sshpass": "ev",
    "redis-cli": "cex234",
    "curl": "sSLkvifIOJgGNZaR#",
}
_SHORT_FLAGS = {  # the letter alone (-pX: X is the value) or after boolean letters only (-su x)
    cmd: re.compile(rf"(?<![^\s\"'`\[,(])-[{re.escape(bools)}]*+{letter}(?:(?P<item>{_LIST_SEP})|[ \t]*+)")
    for cmd, letter in _FLAG_COMMANDS.items()
    for bools in (_BOOL_SHORT[cmd],)
}
# the next list item after "--token", : a quoted string, an already hidden value, else up to the item's end
_ITEM_VAL = re.compile(r"\"(?:[^\"\\\n]|\\.)*+\"?|'[^'\n]*+'?|`[^`\n]*+`?|\[hidden\]|[^\s,\])]++")
# the rest of a value inside the flag's own quotes ("-phunter2", "--token abc"): up to the closing quote
_IN_QUOTES = {
    '"': re.compile(r'(?:[^"\\\n]|\\.)++'),
    "'": re.compile(r"[^'\n]++"),
    "`": re.compile(r"[^`\n]++"),
}
_SHELL_OP = re.compile(r"(?:&&?|\|\|?|;|>>?|<)(?!\S)")
_CMD = re.compile(
    r"(?i)(?<![\w.~/\\-])(?:[\w.~/\\-]*[/\\])?("
    + "|".join(re.escape(c) for c in _FLAG_COMMANDS)
    + r")(?:\.exe)?(?![\w.-])"
)  # any case: MYSQL.EXE on Windows; the flag letters stay case-sensitive (mysql -P is the port)


def _line_end(text: str, pos: int) -> int:
    end = text.find("\n", pos)
    return len(text) if end == -1 else end


def _flag_value(text: str, flag, end: int):
    """The value match after a flag match, or None: the next quoted list item ("--token", "x"), the rest
    inside the flag's own quotes ("-px", "--token x"), else one token or one quoted string."""
    pos = flag.end()
    quote = text[flag.start() - 1] if flag.start() else ""
    if flag.group("item") is not None:
        return _ITEM_VAL.match(text, pos, end)
    if quote in _IN_QUOTES:
        return _IN_QUOTES[quote].match(text, pos, end)
    return _KV_VAL.match(text, pos, end)


_NEXT_FLAG = ("--", '"--', "'--", "`--")


def _flag_values(text: str) -> list[tuple[int, int]]:
    """(start, end) of every secret flag value in text, unsorted; values may overlap."""
    spans = []
    pos, eol = 0, -1
    while (flag := _LONG_FLAG.search(text, pos)) is not None:
        pos = flag.end()
        if pos > eol:
            eol = _line_end(text, pos)
        if not secret_name(flag.group(1)) or (text.startswith(_NEXT_FLAG, pos) and flag.group(0)[-1] != "="):
            continue  # a plain flag, or a secret one with no value: --password --token x, "--password", "--x"
        if (val := _flag_value(text, flag, eol)) is not None:
            spans.append(val.span())
            pos = val.end()
    cmds, eol = list(_CMD.finditer(text)), -1
    for i, cmd in enumerate(cmds):
        flag_rx, pos = _SHORT_FLAGS[cmd.group(1).lower()], cmd.end()
        if pos > eol:
            eol = _line_end(text, pos)
        end = min(eol, cmds[i + 1].start()) if i + 1 < len(cmds) else eol  # up to the next command
        while (flag := flag_rx.search(text, pos, end)) is not None:
            pos = flag.end()
            if _SHELL_OP.match(text, pos, end):
                continue  # mysql -p && next: no value (mysql asks for it)
            if (val := _flag_value(text, flag, end)) is not None:
                spans.append(val.span())
                pos = val.end()
    return spans


def _hide_flag_values(t: str) -> str:
    """Each secret flag value becomes [hidden] (overlapping values become one); the flag itself stays."""
    out, last = [], 0
    for start, end in sorted(_flag_values(t)):
        if start >= last:
            out += [t[last:start], HIDDEN]
        last = max(last, end)
    out.append(t[last:])
    return "".join(out)


# query parameter names: the secret-name words and a few old substrings anywhere, the label words (and a
# bare pass) as whole words; secret_name() too (camelCase)
_SECRET_PARAM = re.compile(
    "(?i)" + _words_rx("[_-]?") + r"|key|sig|code|password|passwd"
    r"|(?<![a-z])(?:" + "|".join(SECRET_LABEL_WORDS) + r")(?![a-z])"
)
HIDDEN = "[hidden]"
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")


_IMAGE_KINDS = {  # magic bytes -> the file extensions that type may carry
    b"\x89PNG\r\n\x1a\n": (".png",),
    b"\xff\xd8\xff": (".jpg", ".jpeg"),
    b"GIF87a": (".gif",),
    b"GIF89a": (".gif",),
}


_PACKED_MAGIC = (b"%PDF", b"PK\x03\x04", b"\xd0\xcf\x11\xe0")


def _is_image(data: bytes, name: str) -> bool:
    """A real image of the type its extension names (png, jpeg, gif, webp); its bytes are still scanned."""
    ext = Path(name).suffix.lower()
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ext == ".webp"
    return any(data.startswith(magic) and ext in exts for magic, exts in _IMAGE_KINDS.items())


PNG_MAX_CHUNKS = 10000  # a bounded walk: more chunks than this = can not be checked
# the critical chunks and a few harmless ancillary ones; any other (tEXt, zTXt, iTXt, eXIf, iCCP, unknown)
# could carry text the scan can not read
PNG_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"pHYs"}


def _image_clean(data: bytes) -> bool:
    """True when an image has nowhere to hide text the scan can not read. Only a PNG can be: its chunks are
    walked (bounded), only those in PNG_CHUNKS pass, and nothing may follow IEND. Every other image type,
    and anything odd, is False (fail closed)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        pos = 8
        for _ in range(PNG_MAX_CHUNKS):
            if pos + 8 > len(data):
                return False  # no IEND
            length = int.from_bytes(data[pos : pos + 4], "big")
            kind = data[pos + 4 : pos + 8]
            end = pos + 12 + length  # length, type, data, crc
            if end > len(data) or kind not in PNG_CHUNKS:  # text, exif, profiles, unknown: unreadable
                return False
            if kind == b"IEND":
                return end == len(data)
            pos = end
        return False
    # JPEG, GIF and WebP: no structural walk yet, so they can not be checked (fail closed)
    return False


def _clean_full(t: str) -> str:
    """clean_untrusted without its length cut (a whole file, a whole name); plain printable ASCII without a
    comment is already clean (NFC changes nothing, nothing is dropped)."""
    if t.isascii() and t.isprintable() and "<!--" not in t:
        return t
    return clean_untrusted(t, len(t) * 3 + 16)  # NFC grows a text by at most three times


def _has_secret(data: bytes) -> bool:
    """The file scan uses the SAME detection as redact (_scrub_text: patterns, key=value, spaced values, flag
    values and URL userinfo): a text hides something when the scrub changes it, in its raw, NFKC and cleaned
    (invisible characters and comments gone) form. Over-hiding is accepted: such a file is not sent."""
    text = data.decode(errors="ignore")
    cleaned = _clean_full(text)
    forms = (text, cleaned, unicodedata.normalize("NFKC", text), unicodedata.normalize("NFKC", cleaned))
    return any(_scrub_text(t) != t for t in dict.fromkeys(forms))


def _holds_stored_value(root: Path, data: bytes, texts: list[str]) -> bool:
    """True when the file holds a stored key value of the keystore (the value hider: exact needles in all the
    forms it knows). Read as _scan read it (`texts`: the BOM-decoded text of a UTF-16/32 file, else the UTF-8
    text), as raw bytes, and with CR removed (a CRLF copy of a multi-line value); plus the lenient UTF-16
    readings of a file without BOM. A hider that can not be built: True (fail closed)."""
    h = phone_results.value_hider(root)
    if h is None:
        return True
    more = [data[k:].decode(c, "ignore") for c in ("utf-16-le", "utf-16-be") for k in (0, 1)]
    seen = [t for t in dict.fromkeys(texts + more)]
    seen += [t.replace("\r", "") for t in seen if "\r" in t]
    return h.hide_bytes(data) != data or any(h.hide_text(t) != t for t in seen)


def _scan(data: bytes, name: str) -> str:
    """The verdict of _scan_texts."""
    return _scan_texts(data, name)[0]


def _scan_texts(data: bytes, name: str) -> tuple[str, list[str]]:
    """(verdict, texts). The verdict is one of ok, secret (looks like a password or key) or unknown (can not
    be checked: a PDF, zip, docx, xlsx or any other packed or binary file, or text with NULs; such a file is
    not sent, fail closed). Text (UTF-8, or UTF-32/UTF-16 with a BOM) is scanned as text; an image whose type
    matches its extension is scanned as its raw bytes (text in metadata or after the image is still caught).
    `texts` are exactly the texts the verdict was read from (the BOM-decoded text of a UTF-16/32 file, else
    the lenient UTF-8 text), so every other check of the same file (the stored-value needle check) reads
    it the same way."""
    if any(magic in data for magic in _PACKED_MAGIC):  # pdf, zip/OOXML, OLE office anywhere in the file
        return "unknown", []
    for bom, codec in (
        ((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"), "utf-32"),  # before UTF-16: same first two bytes
        ((b"\xff\xfe", b"\xfe\xff"), "utf-16"),
    ):
        if data.startswith(bom):
            try:
                text = data.decode(codec)
            except UnicodeDecodeError:
                return "unknown", []
            if "\x00" in text:
                return "unknown", []
            return ("secret" if _has_secret(text.encode()) else "ok"), [text]
    if _is_image(data, name):
        if not _image_clean(data):  # compressed text chunks or data after the end: can not be checked
            return "unknown", []
    else:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return "unknown", []
        if b"\x00" in data:
            return "unknown", []
    return ("secret" if _has_secret(data) else "ok"), [data.decode(errors="ignore")]


_ROUNDS = 3
TEXT_CUT = 20000  # redact looks at this much of a text
CUT_MARGIN = (
    128  # ... and drops this much more where it cuts: no token prefix too short for its pattern stays
)


def _round(t: str) -> str:
    """One round: clean, scrub the cleaned raw form, NFKC, scrub again; out = scrub(NFKC(scrub(clean(raw)))).
    When the raw and the NFKC form of the cleaned text do not agree on whether there is a secret, the whole
    value is hidden (fail closed); with no secret in either the cleaned text is returned unchanged. A text
    longer than TEXT_CUT is scrubbed as cut (TEXT_CUT + 1 characters: a token inside is matched whole), then
    its last CUT_MARGIN characters go and it ends in [hidden]: a token cut in two at the limit could leave a
    prefix that no pattern knows any more."""
    c = clean_untrusted(t, TEXT_CUT + 1)
    out = _scrub_round(c)
    if len(c) > TEXT_CUT and out != HIDDEN:
        out = out[: max(0, len(out) - CUT_MARGIN)] + HIDDEN
    return out


def _scrub_round(c: str) -> str:
    n = unicodedata.normalize("NFKC", c)
    raw_hit, norm_hit = _scrub_text(c) != c, _scrub_text(n) != n
    if raw_hit != norm_hit:
        return HIDDEN
    if not raw_hit:
        return c  # nothing secret in either form: shown as it is (not NFKC: … stays …)
    return _scrub_text(unicodedata.normalize("NFKC", _scrub_text(c)))


def redact(text: str) -> str:
    """Plain, safe text for the phone: invisible/control characters and comments go (clean_untrusted), then
    anything that looks like a key, token or password is replaced by [hidden]. One pipeline iterated to a
    fixed point: scrub(NFKC(scrub(clean(raw)))) repeats until the text stops changing, because
    cleaning or normalizing can join text into a new secret (a hidden comment between two halves, fullwidth
    names). Not stable after _ROUNDS rounds: the whole value is hidden."""
    t = str(text)
    for _ in range(_ROUNDS):
        nxt = _round(t)
        if nxt == t:
            return t
        t = nxt
    return HIDDEN


# A label with a value but no separator, in fixed shapes only (never prose): SQL `PASSWORD 'x'` (quoted),
# `IDENTIFIED BY x` / `IDENTIFIED BY PASSWORD 'x'`, .netrc `login u password x`, and a line that is only
# `password x`. The value is hidden, the label stays. Linear: a lookbehind-guarded start per word or line,
# possessive runs, the scan goes on after each value.
_SPACED_VALUES = (
    re.compile(
        r"(?i)(?<![\w.-])(?:(?:password|passwd)[ \t]++(?=['\"])"
        r"|identified[ \t]++by(?:[ \t]++password)?[ \t]++"
        r"|login[ \t]++\S++[ \t]++(?:password|passwd)[ \t]++)(?P<v>'[^'\n]*+'?|\"[^\"\n]*+\"?|\S++)"
    ),
    re.compile(r"(?im)^[ \t]*+(?:password|passwd)[ \t]++(?P<v>\S++)(?=[ \t]*+$)"),
)


# ACCEPTED GAPS: the one list of known cases that redact, the file scan (_has_secret, _scan) and the value
# hider (phone_results) do NOT catch; tests/test_phone_results.py pins what is covered.
# - a secret split across lines (a flag value after a `\` continuation, a key wrapped over two lines),
#   or base64, hex, URL-encoded or otherwise encoded so no pattern or label is visible (the value hider
#   knows these forms of a STORED value, not of others);
# - homoglyph or confusable names (Cyrillic `раssword=x`, a modifier-letter colon `password꞉x`): NFKC does
#   not map them;
# - short flags of commands not in _FLAG_COMMANDS (psql, docker, ...), long flags without a secret name
#   (curl --user u:p), single-dash long flags (-password x), and a secret value that starts with `--`
#   (--password --hunter2: read as a second flag);
# - a secret in prose without a label or a known shape ("the new one is hunter2"), unless it is a stored
#   value (the value hider);
# - tokens in URL paths other than Slack, Discord and Telegram webhooks (a token as a path segment);
# - a stored value in fullwidth/NFKC form, split over table cells, in base32, or as a host whose case
#   differs (value hider);
# - text drawn in pixels (a terminal screenshot) and bytes inside compressed image data (IDAT): only the raw
#   bytes of an image are scanned; JPEG, GIF and WebP get no structural walk (_image_clean): they are
#   "unknown" and not sent, never checked as clean;
# - HTML and SVG artifacts are active content: entities (`&#112;assword=`) or script (atob) can build any
#   text when the file is shown; the scan sees the source only;
# - past TEXT_CUT redact shows nothing (the text ends in [hidden]); a file is scanned whole;
# - attachments() clips its titles, labels and names without the value hider (a stored value across the
#   cut leaves a prefix the final view check does not know), and _scan/_has_secret do not use it: owned by
#   the upload-gate PR #541, not #497;
# - a label that is not right before its separator (`The password is: x`, `DB password (staging): x`), XML
#   and HTML element or attribute values (`<password>x</password>`, `key="DbPassword" value="x"`), and
#   default-ignorable characters that are not Cf (CGJ U+034F, variation selectors, Hangul fillers) inside a
#   name;
# - URL userinfo with a raw `/`, `?`, `#` in the password or an `@` in the user (`redis://:pa#ss@h`,
#   `https://bob@corp.ch:pw@h`) and scheme-less DSNs (`user:pw@tcp(h)/db`);
# - other operators and languages: `password == "x"`, `||=`, `??=`, `->`, `<-`, Dockerfile `ENV PASSWORD x`,
#   fish `set -x API_TOKEN x`, non-English labels (Kennwort, mot de passe), PuTTY `Private-Lines:`.
# Over-redaction is accepted (fail safe): `--token-count 512`, `use --token to set it` hide the next word,
# `bypass=1`, `compass: north` and the rest of a `token: ...` line are hidden.
def _scrub_text(t: str) -> str:
    for rx in _SECRET_PATTERNS:
        t = rx.sub(HIDDEN, t)
    t = _SECRET_KV.sub(lambda m: m.group(1) + m.group(2) + HIDDEN, t)
    for rx in _SPACED_VALUES:
        t = rx.sub(lambda m: m.group(0)[: m.start("v") - m.start()] + HIDDEN, t)
    return _hide_flag_values(t)


def _clip(text: str, n: int, h=None) -> str:
    """Phone text, at most n characters. With a value hider `h` (every text of a view) each stored key value
    is hidden too: before the scrub and again after it (cleaning can join a value split by an invisible
    character), and before the cut (a cut never leaves part of one)."""
    t = redact(text) if h is None else h.hide_text(redact(h.hide_text(str(text))))
    t = t.strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _secret_param(name: str) -> bool:
    """Does a query parameter name a secret? ?pwd=, ?pass=, ?otp=, ?api_key=, ?authToken=, fullwidth too."""
    return bool(_SECRET_PARAM.search(unicodedata.normalize("NFKC", name))) or secret_name(name)


def safe_url(url: str) -> str | None:
    """http(s) URLs only, without user:password, secret-looking query values hidden, a query key that is
    itself a secret (?eyJ..., ?sk_live_...) hidden with its value. None otherwise (also for a bad port)."""
    u = str(url).strip()
    try:
        p = urllib.parse.urlsplit(u)
        port = p.port  # raises for :99999 or :x
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname or any(c.isspace() for c in u):
        return None
    host = (f"[{p.hostname}]" if ":" in p.hostname else p.hostname) + (f":{port}" if port else "")  # IPv6
    q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    pairs = [
        (HIDDEN, HIDDEN) if redact(k) != k else (k, HIDDEN if _secret_param(k) else redact(v)) for k, v in q
    ]
    out = urllib.parse.urlunsplit((p.scheme, host, redact(p.path), urllib.parse.urlencode(pairs), ""))
    return out if len(out) <= 2000 else None


def _url(url, h) -> str | None:
    """safe_url for a view: None too when the address holds a stored key value (a link with a hole in it
    opens nothing useful, so it is left out)."""
    out = safe_url(url)
    return out if out is not None and h.hide_text(out) == out else None


_PASS_OK = re.compile(
    r"(?<![a-z])pass\s*/\s*fail(?![a-z])|(?<![a-z])pass\s+(?:rate|count|total|percent|percentage)(?![a-z])"
)
_NAME_SUBSTR = re.compile(_words_rx(" ?"))
_NAME_WORD = re.compile(
    r"(?<![a-z])(" + "|".join(SECRET_LABEL_WORDS) + r")(?![a-z])"
)  # letters only: key2, pin1
_NAME_PASS = re.compile(r"pass(?![a-z])")  # a word that ends in pass: SSHPASS, DBPASS, smtppass
# a word that ends in pwd, pw or pswd (ROOTPWD, ADMINPW, pswd), or in key after a known key kind (MASTERKEY,
# privkey, HMACKEY): a bare key suffix would take Monkey, Hotkey and Turkey too
_NAME_TAIL = re.compile(
    r"(?:pwd|pw|pswd)(?![a-z])|(?:master|encryption|enc|signing|sign|hmac|jwt|license|licence|app|db|crypt"
    r"|priv|aes|rsa|ssh|gpg|pgp)keys?(?![a-z])"
)


def secret_name(name: str) -> bool:
    """Does a label (kv key, column key or label, stat label) name a secret? The name as given AND cleaned
    (invisible characters and comments gone: to<ZWSP>ken, tok<!---->en), each NFKC, then camelCase, _ - .
    split into words, so basic_auth, authCode, X-Api-Key, DB_PASS, SSHPASS, PHPSESSID, session_id, ROOTPWD
    and MASTERKEY match; Author, Keyboard, Monkey, Hotkey, Turkey, Passed and Passage do not. The one
    predicate for labelled values in results, for key=value names in text and for long flags."""
    raw = str(name)
    for form in dict.fromkeys((raw, _clean_full(raw))):
        t = unicodedata.normalize("NFKC", form)
        words = re.sub(r"[_\-.]+", " ", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", t)).lower()
        words = _PASS_OK.sub(" ", words)  # test-result phrases: Pass/Fail, pass rate, pass count (not passed)
        if any(rx.search(words) for rx in (_NAME_SUBSTR, _NAME_WORD, _NAME_PASS, _NAME_TAIL)):
            return True
    return False


def size_of(view: dict) -> int:
    return len(json.dumps(view, separators=(",", ":"), ensure_ascii=False).encode())


def is_agent_history_author(by) -> bool:
    """Only explicit agent labels are safe as unverified synced attribution."""
    if not isinstance(by, str) or not by.isascii() or by != unicodedata.normalize("NFKC", by):
        return False
    label = by.casefold()
    return bool(re.fullmatch(r"agent:[a-z0-9._-]{1,40}", label)) and not label[6:].startswith(
        ("relay", "phone", "ph_")
    )


def _who(by: str, h=None) -> tuple[str, str]:
    """(display name, role) of a history author; `h`, the value hider, hides a stored value before the cut."""
    kind, _, name = str(by).strip().partition(":")
    name = _clip(name or kind, 64, h) or "Someone"
    if unicodedata.normalize("NFKC", kind).casefold() == "agent":
        # A sender suffix or raw phone id is not an agent display name.
        label = unicodedata.normalize("NFKC", name).casefold()
        if not re.fullmatch(r"[a-z0-9._-]{1,64}", label) or label.startswith("ph_"):
            return "orch", "agent"
        return name[:1].upper() + name[1:], "agent"
    return name, "person"


_ADMIN_NOTE = re.compile(
    r"(?:Set|Removed) ext\."
)  # add-on settings notes: admin business, not for a phone chat


def internal_wakeup(entry: dict) -> bool:
    """Hide the legacy automation prompt that used to be logged as helper speech."""
    return entry.get("by") != "you" and str(entry.get("text", "")).startswith(
        "A phone text in the General conversation is waiting for you. Answer it: orch relay send "
    )


def _agent(root: Path, ticket: dict, h=None) -> tuple[str | None, bool]:
    """(agent display name, running now); `h`: the value hider for the name."""
    rec = runs.read(root, ticket["id"])
    running = bool(rec) and runs.state(rec) != "dead"
    name = (rec or {}).get("agent") if running else None
    if not name:
        sessions = sorted(ticket.get("sessions") or [], key=lambda s: str(s.get("last_used", "")))
        name = sessions[-1].get("agent") if sessions else None
    return (_who(f"agent:{name}", h)[0] if name else None), running


def phone_proof(root: Path, ticket: dict) -> list[dict]:
    """Evidence marked for the phone (role result or check), newest last, from every task."""
    out = []
    for c in ticket.get("checklist") or []:
        for ev in c.get("evidence") or []:
            if ev.get("role") in PHONE_ROLES:
                out.append(ev)
    return out


def named_artifacts(root: Path, ticket: dict, artifacts: list[dict] | None = None) -> list[str]:
    """Up to 20 artifact names in questions, options, summary or description, in listing order."""
    texts = [ticket.get("summary") or "", ticket.get("description") or ""]
    for question in ticket.get("questions") or []:
        texts.append(question.get("text") or "")
        texts.extend(question.get("options") or [])
    out = []
    if artifacts is None:
        artifacts = tickets.artifacts_list(root, ticket["id"])
    for artifact in artifacts[:200]:
        name = artifact["name"]
        path = Path(name)
        prefix = r"(?:artifacts/)?" if path.suffix and len(path.stem) >= 4 else r"artifacts/"
        pattern = re.compile(r"(?<![\w./-])" + prefix + re.escape(name) + r"(?![\w/-]|\.\w)")
        if any(pattern.search(text) for text in texts):
            out.append(name)
            if len(out) == 20:
                break
    return out


def _proof_file(root: Path, tid: str, ev: dict) -> tuple[str, bytes] | None:
    """(name, bytes) of a copied proof file of this ticket, .orch/tickets/<tid>/evidence/<name>, never
    anything else: the ref has exactly that shape and the read goes through orch.safefile (the one reader)."""
    parts = str(ev.get("ref", "")).split("/")
    if len(parts) != 5 or parts[:4] != [".orch", "tickets", tid, "evidence"]:
        return None
    try:
        data = safefile.read_ticket_file(root, tid, "evidence", parts[4], tickets.MAX_PROOF_BYTES)
    except safefile.TooLarge:
        return None
    return (parts[4], data) if data is not None else None


def result_candidates(root: Path, ticket: dict) -> list[dict]:
    """The block documents the ticket holds today, as phone_results candidates: the agent's proof (a copied
    evidence file `<name>.json` holding an orch.blocks/1 document, role result or check). `from` is set here
    to agent (the core overwrites a producer's own value), `checked` only for a step that is done with proof.
    Job results (j_ ids) and results computed by orch have no store yet: nothing to add for them."""
    tid = ticket["id"]
    at0 = ticket["updated_at"] if _TIME.fullmatch(str(ticket.get("updated_at"))) else tickets.now()
    out: list[dict] = []
    for step in ticket.get("checklist") or []:
        for ev in step.get("evidence") or []:
            if ev.get("role") not in PHONE_ROLES or ev.get("type") != "file":
                continue
            f = _proof_file(root, tid, ev)
            if not f or not f[0].lower().endswith(".json") or len(f[1]) > 256 * 1024:
                continue  # a valid document is at most 64 KB
            try:
                doc = json.loads(f[1].decode("utf-8"))
            except Exception:  # ValueError, UnicodeDecodeError, RecursionError: never a failed send
                continue
            if not isinstance(doc, dict) or doc.get("schema") != "orch.blocks/1":
                continue
            doc["from"] = "agent"
            r = {
                "id": artifact_id("file", str(ev.get("ref", ""))),
                "from": "agent",
                "at": ev["at"] if _TIME.fullmatch(str(ev.get("at"))) else at0,
                "doc": doc,
            }
            if title := str(ev.get("title") or doc.get("title") or ""):
                r["title"] = title  # cut only after the hider (phone_results)
            if step.get("done") and step.get("evidence"):
                r["checked"] = True
            out.append(r)
    return out


def _state_path(root: Path) -> Path:
    return net.secrets_dir(root) / "phone-views.json"


def load_state(root: Path) -> dict:
    s = net.read_json(_state_path(root), {})
    if not isinstance(s, dict):
        s = {}
    s.setdefault("tickets", {})
    s.setdefault("blobs", {})
    return s


def save_state(root: Path, s: dict) -> None:
    net.write_json(_state_path(root), s, True)


STATE_LOCK_STALE = 10  # no more than the wait: a lock left by a holder that died is broken before giving up


def _break_stale_lock(lock: Path) -> bool:
    """Take away a lock left by a holder that died (older than STATE_LOCK_STALE; it is only ever held for one
    file write). Rename first, so only one waiter wins; what was taken must still be the old one, else (a new
    holder's fresh lock) it is put back without clobbering."""
    try:
        if time.time() - lock.stat().st_mtime <= STATE_LOCK_STALE:
            return False
        mine = lock.with_name(f"{lock.name}.{os.getpid()}.{time.monotonic_ns()}")
        os.replace(lock, mine)
    except OSError:
        return False
    try:
        if time.time() - mine.stat().st_mtime > STATE_LOCK_STALE:
            return True
        with contextlib.suppress(OSError):
            os.link(mine, lock)  # a live holder's lock: put it back (fails if a newer one is there already)
        return False
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            mine.unlink()


@contextlib.contextmanager
def _state_locked(root: Path, wait: float = 10.0):
    """One read-modify-write of phone-views.json at a time (sync, sync_open, remember, view_for may run in
    several orch processes at once). Its own lock, held only around the file, never around a send: remember()
    runs inside the relay lock (an ack while the inbox is handled), and the relay lock is not reentrant."""
    lock = net.secrets_dir(root) / "phone-views.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + wait
    token = f"{os.getpid()}-{time.monotonic_ns()}".encode()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, token)
            finally:
                os.close(fd)
            break
        except FileExistsError:
            if _break_stale_lock(lock):
                continue
            if time.monotonic() > end:
                raise Refused("The phone view state is busy. Try again in a moment.") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        # only our own lock goes, never one a later holder made: take it aside first (atomic), then check
        mine = lock.with_name(f"{lock.name}.{token.decode()}.rel")
        try:
            os.replace(lock, mine)
        except OSError:
            mine = None  # nothing taken aside: nothing to remove
        if mine is not None:
            try:
                ours = mine.read_bytes() == token
            except OSError:
                ours = False  # can not tell: treat it as someone else's
            if not ours:  # put it back; dropped only if a newer one is there already
                try:
                    os.link(mine, lock)
                except FileExistsError:
                    pass
                except OSError:  # no hard links on this file system: rename back when the place is still free
                    with contextlib.suppress(OSError):
                        if not lock.exists():
                            os.rename(mine, lock)
            with contextlib.suppress(OSError):
                mine.unlink()


def update_state(root: Path, fn) -> dict:
    """fn(state) changes the freshly read state under the lock; it is then saved. Returns the state."""
    with _state_locked(root):
        st = load_state(root)
        fn(st)
        save_state(root, st)
        return st


_JPEG_META_OK = {0xE0, 0xE1, 0xE2}  # APP0 (JFIF), APP1 (Exif/XMP), APP2 (ICC); COM and APP3+ are refused
_JPEG_PLAIN = {0xDB, 0xC4, 0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xDD, 0xDA}
JPEG_META_MAX = 128 * 1024  # all metadata segments together
JPEG_PLAIN_MAX = 8 * 1024  # all table/frame segments together (real files use ~1 KB): no payload room


def _jpeg_walk(data: bytes) -> list[bytes] | None:
    """The metadata segments of a JPEG that is structurally plain, else None: only known segments, then the
    entropy data up to one EOI that ends the file (NUL padding allowed). Nothing may follow (no archive behind
    the picture), no COM / APP3+ segment, bounded metadata."""
    if not data.startswith(b"\xff\xd8"):
        return None
    pos, meta, size, plain = 2, [], 0, 0
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        m = data[pos + 1]
        n = int.from_bytes(data[pos + 2 : pos + 4], "big")
        if n < 2 or pos + 2 + n > len(data):
            return None
        if m in _JPEG_META_OK:
            size += n
            meta.append(data[pos + 4 : pos + 2 + n])
            if size > JPEG_META_MAX:
                return None
        elif m not in _JPEG_PLAIN:
            return None
        else:
            plain += n
            if plain > JPEG_PLAIN_MAX:
                return None
        pos += 2 + n
        if m == 0xDA:  # entropy-coded data: FF00 and RSTn are data, any other marker ends it
            while pos + 1 < len(data):
                if data[pos] == 0xFF and data[pos + 1] not in (0x00, *range(0xD0, 0xD8)):
                    break
                pos += 1
            if data[pos : pos + 2] != b"\xff\xd9":
                return None
            return meta if not data[pos + 2 :].strip(b"\x00") else None
    return None


def _photo_verdict(data: bytes) -> str:
    """ok / secret / unknown for an evidence JPEG `_scan` could not fully check: it must be structurally plain
    (_jpeg_walk) and neither its bytes nor the UTF-16 readings of its metadata may hold a secret. Any other
    format is unknown (fail closed)."""
    meta = _jpeg_walk(data)
    if meta is None:
        return "unknown"
    texts = [data]
    for codec in ("utf-16-le", "utf-16-be"):  # both byte orders, both alignments, over the whole file
        texts += [data[k:].decode(codec, "ignore").encode() for k in (0, 1)]
    return "secret" if any(_has_secret(t) for t in texts) else "ok"


def _gate(root: Path, tid: str, data: bytes, name: str, state: dict | None, photo_ok: bool = False) -> bool:
    """The one secret gate in front of every phone upload (proof files and named artifacts alike): True when
    `data` may be sent. A file that looks like a password or key, or can't be checked, is not sent and is
    marked once in the ticket log and in state["secret_skipped"] (fail closed). `photo_ok` (evidence only): a
    picture that can't be fully checked (a JPEG photo) still goes when its raw bytes hold no secret."""
    try:
        verdict, texts = _scan_texts(data, name)
    except Exception:  # a malformed file skips only itself, never the whole view
        verdict, texts = "unknown", []
    if verdict == "unknown" and photo_ok and _is_image(data, name):
        verdict = _photo_verdict(data)
    if verdict == "ok" and _holds_stored_value(root, data, texts):
        verdict = "secret"  # the exact value of a stored key, whatever the label (or none)
    name = Path(name).name
    if verdict == "ok":
        return True
    why = (
        "it looks like it holds a password or key"
        if verdict == "secret"
        else "it can't be checked for passwords"
    )
    if state is not None:
        skipped = state.setdefault("secret_skipped", [])
        key = f"{name}:{hashlib.sha256(data).hexdigest()}"
        if key not in skipped:
            with contextlib.suppress(Exception):
                tickets.log(root, tid, f"{name} was not sent to the phone: {why}.", "orch")
            skipped.append(key)
            del skipped[:-200]
    return False


def _upload(root: Path, data: bytes, state: dict) -> dict | None:
    """Upload a proof file once (cached by content); {blob_id, size} or None when the relay says no."""
    from orch import relay

    sha = hashlib.sha256(data).hexdigest()
    got = state["blobs"].get(sha)
    if got and time.time() - got.get("at", 0) < BLOB_DAYS * 86400:
        return got
    try:
        blob = relay._api(root, "POST", "/v1/blobs", data, 300)[1]
    except Refused:
        return None
    if not isinstance(blob, dict) or blob.get("sha256") != sha or blob.get("size") != len(data):
        return None
    got = {"blob_id": blob["blob_id"], "size": len(data), "at": time.time()}
    state["blobs"][sha] = got
    return got


def artifact_id(source: str, ref: str) -> str:
    """a_ + 12 hex of sha256("<source>\\n<ref>"): stable across revisions (vectors/phone-v3-v1.json).
    source = the evidence type (pr, commit, file, url, command, note) or "link" for ticket refs."""
    return "a_" + hashlib.sha256(f"{source}\n{ref}".encode()).hexdigest()[:12]


def _short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


_PUBLISHED = re.compile(r"^/(?:f|a)/([A-Za-z0-9_.-]+)")


def _url_art(source: str, url: str, kind_hint: str | None = None) -> tuple[str, str]:
    """(kind, rev) of an artifact that is a link: a published page or app is html (rev = its publish id or app
    name), a pull request pr, a commit commit (rev = the commit sha), anything else link."""
    path = urllib.parse.urlsplit(url).path
    if m := _PUBLISHED.match(path):
        return "html", m.group(1)
    if source == "pr" or kind_hint == "pr":
        return "pr", _short(url)
    if source == "commit" or kind_hint == "commit" or re.search(r"/commit/([0-9a-f]{7,40})", path):
        c = re.search(r"/commit/([0-9a-f]{7,40})", path)
        return "commit", c.group(1) if c else _short(url)
    return "link", _short(url)


def _not_sent(root: Path, tid: str, state: dict | None, name: str, sha: str, verdict: str) -> None:
    """A file the scan refused: one line in the ticket history per name and content, never a failed send."""
    why = (
        "it looks like it holds a password or key"
        if verdict == "secret"
        else "it can't be checked for passwords"
    )
    if state is None:
        return
    skipped = state.setdefault("secret_skipped", [])
    key = f"{name}:{sha}"
    if key not in skipped:
        with contextlib.suppress(Exception):
            tickets.log(root, tid, f"{name} was not sent to the phone: {why}.", "orch")
        skipped.append(key)
        del skipped[:-200]


_ICON = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_LINK_STATUS = re.compile(r"[a-z0-9][a-z0-9 -]{0,23}")
STATUSES = ("open", "active", "waiting", "ready", "review", "done", "dropped")  # message.schema.json


def attachments(root: Path, ticket: dict, state: dict | None, upload: bool = True) -> list[dict]:
    """Proof files, named artifacts (uploaded), proof links and ticket links, newest first, at most 50."""
    tid = ticket["id"]
    at0 = ticket["updated_at"] if _TIME.fullmatch(str(ticket.get("updated_at"))) else tickets.now()
    out: list[dict] = []
    for ev in phone_proof(root, ticket):
        at = ev["at"] if _TIME.fullmatch(str(ev.get("at"))) else at0
        if ev.get("type") == "file":
            f = _proof_file(root, tid, ev)
            b = (
                _upload(root, f[1], state)
                if (f and upload and state is not None and _gate(root, tid, f[1], f[0], state, photo_ok=True))
                else None
            )
            if not b:
                continue
            kind = "image" if Path(f[0]).suffix.lower() in IMAGE_EXT else "file"
            name = _clip(f[0], 255) or "file"
            out.append(
                {
                    "kind": kind,
                    "title": _clip(ev.get("title") or f[0], 200) or name,
                    "blob_id": b["blob_id"],
                    "name": name,
                    "size": b["size"],
                    "at": at,
                    "id": artifact_id("file", str(ev.get("ref", ""))),
                    "rev": hashlib.sha256(f[1]).hexdigest(),
                }
            )
        elif ev.get("type") in ("url", "pr", "commit") and (url := safe_url(ev.get("ref", ""))):
            kind, rev = _url_art(ev["type"], url)
            out.append(
                {
                    "kind": kind,
                    "title": _clip(ev.get("title") or url, 200) or "Link",
                    "url": url,
                    "at": at,
                    "id": artifact_id(ev["type"], str(ev.get("ref", ""))),
                    "rev": rev,
                }
            )
        elif ev.get("type") == "commit" and re.fullmatch(r"[0-9a-f]{7,40}", str(ev.get("ref", ""))):
            pass  # a bare commit sha has no address to open: nothing for the phone to show
    kinds = refs.active_kinds(root) if ticket.get("refs") else []
    for ln in ticket.get("refs") or []:
        if not isinstance(ln, dict) or not (url := safe_url(ln.get("url", ""))):
            continue
        d = refs.describe(ln, kinds)  # same label, icon and status as the dashboard and CLI
        at = ln["at"] if _TIME.fullmatch(str(ln.get("at"))) else at0
        kind, rev = _url_art("link", url)
        a = {
            "kind": kind,
            "title": _clip(ln.get("title") or url, 200) or "Link",
            "url": url,
            "at": at,
            "id": artifact_id("link", str(ln.get("url", ""))),
            "rev": rev,
        }
        a.update(label=_clip(d["label"], 60) or "Link", icon=d["icon"])
        if d["mono"]:
            a["mono"] = d["mono"][:3]
        if d["status"]:
            a["status"] = d["status"]
        out.append(a)
    artifacts = tickets.artifacts_list(root, tid)[:200]
    named = named_artifacts(root, ticket, artifacts)
    mtimes = {a["name"]: a.get("mtime") for a in artifacts}
    artifact_entries = []
    artifact_bytes = 0
    evidence_hashes = {a["rev"] for a in out if "blob_id" in a}
    slots = max(0, ATTACHMENTS - len(out))
    for name in named:
        if len(artifact_entries) >= slots:
            break
        aid = artifact_id("file", f".orch/tickets/{tid}/artifacts/{name}")
        if any(a["id"] == aid for a in out):
            continue
        room = min(tickets.MAX_PROOF_BYTES, ARTIFACT_BYTES - artifact_bytes)
        if room <= 0:
            break
        try:  # safefile checks the size on the open file (fstat) before it reads: too big = never loaded
            data = safefile.read_ticket_file(root, tid, "artifacts", name, room)
        except safefile.TooLarge:
            continue
        if data is None:
            continue
        sha = hashlib.sha256(data).hexdigest()
        if not _gate(root, tid, data, name, state):
            continue
        if sha in evidence_hashes:  # the same content is already in the view (evidence or an artifact)
            continue
        b = _upload(root, data, state) if upload and state is not None else None
        if not b:
            continue
        artifact_bytes += len(data)
        evidence_hashes.add(sha)  # artifacts among themselves too
        at = mtimes.get(name)
        artifact_entries.append(
            {
                "kind": "image" if Path(name).suffix.lower() in IMAGE_EXT else "file",
                "title": _clip(name, 200) or "file",
                "blob_id": b["blob_id"],
                "name": _clip(Path(name).name, 255) or "file",
                "size": b["size"],
                "at": at if _TIME.fullmatch(str(at)) else at0,
                "id": aid,
                "rev": sha,
            }
        )
    out.extend(artifact_entries[:slots])
    out.sort(key=lambda a: a["at"], reverse=True)
    return pair_previews(out[:ATTACHMENTS])


def pair_previews(atts: list[dict]) -> list[dict]:
    """One result, one thing to open: a page (name.html) and its picture (name.png) that are both in the list.
    The page gets `preview` = the picture's artifact id and is followed directly by the picture; the picture
    stays in the list (an older phone still shows it, a newer one shows it inside the page). Only a PNG that
    is in this very list (already checked and uploaded) can be a preview; each picture belongs to one page.
    The list is cut to its size first, so a preview never names an entry that was cut off."""

    def stem(a: dict) -> str:
        return Path(str(a.get("name", ""))).stem.lower()

    pictures = {
        stem(a): a
        for a in reversed(atts)  # the newest picture of a name wins
        if a.get("kind") == "image" and a.get("id") and str(a.get("name", "")).lower().endswith(".png")
    }
    pair: dict[int, dict] = {}  # id(page) -> its picture
    taken: set[int] = set()
    for a in atts:
        if a.get("kind") != "file" or not a.get("id") or "preview" in a:
            continue
        if not str(a.get("name", "")).lower().endswith((".html", ".htm")):
            continue
        pic = pictures.get(stem(a))
        if pic is not None and id(pic) not in taken:
            pair[id(a)] = pic
            taken.add(id(pic))
    out: list[dict] = []
    for a in atts:
        if id(a) in taken:
            continue  # shown right behind its page
        out.append(a)
        if (pic := pair.get(id(a))) is not None:
            a["preview"] = pic["id"]
            out.append(pic)
    return out


def artifact_title(root: Path, ticket: dict, aid: str, h=None) -> str | None:
    """The title of the proof or link a phone feedback names (by artifact id), or None; `h`, the value hider,
    hides a stored value before the cut."""
    for ev in phone_proof(root, ticket):
        if artifact_id(str(ev.get("type")), str(ev.get("ref", ""))) == aid:
            return _clip(ev.get("title") or Path(str(ev.get("ref", ""))).name, 200, h) or None
    for ln in ticket.get("refs") or []:
        if isinstance(ln, dict) and artifact_id("link", str(ln.get("url", ""))) == aid:
            return _clip(ln.get("title") or ln.get("url", ""), 200, h) or None
    return None


def reference_views(root: Path, ticket: dict, h=None) -> list[dict]:
    """Shared references for the phone; local computer paths never leave this machine. `h`: the value hider
    (built here when not given; none can be built: no references, fail closed)."""
    h = h if h is not None else phone_results.value_hider(root)
    if h is None:
        return []
    out = []
    for ref in (ticket.get("refs") or [])[:ATTACHMENTS]:
        if not isinstance(ref, dict) or ref.get("local"):
            continue
        kind = ref.get("kind")
        if kind in ("ticket", "artifact"):
            tid = ref.get("ticket")
            if not isinstance(tid, str) or not re.fullmatch(r"t_[a-z0-9]{6,16}", tid):
                continue
            row = {"kind": kind, "ticket": tid}
            try:
                other = tickets.load(root, tid)
                row["title"] = _clip(other["title"], 200, h)
                if other.get("status") in STATUSES:
                    row["status"] = other["status"]
            except (Refused, OSError, ValueError, KeyError):
                pass
            if kind == "artifact":
                if safefile._parts(ref.get("name")) is None:
                    continue
                row["name"] = _clip(ref["name"], 240, h)
        elif kind == "file":
            path = ref.get("path")
            if not safefile.file_ref_ok(root, path):
                continue
            row = {"kind": kind, "path": _clip(path, 240, h)}
            line = ref.get("line")
            if type(line) is int and line > 0:
                row["line"] = line
        else:
            url = _url(ref.get("url", ""), h)
            if not url or not isinstance(kind, str) or not refs.KIND_RE.fullmatch(kind):
                continue
            row = {"kind": kind, "url": url, "title": _clip(ref.get("title") or url, 200, h)}
        out.append(row)
    return out


def _without_delivery(text: str, *, task: bool = False) -> str:
    """Remove only whole result-delivery sentences or a whole phone-delivery task."""
    destination = r"(?:back )?to (?:the |your )?phones?(?: via (?:the )?relay)?"
    if task and re.fullmatch(
        rf"(?:send|deliver) (?:the |your )?results? {destination}[.!?]?", text.strip(), re.I
    ):
        return ""
    cleaned = re.sub(
        rf"(^|(?<=[.!?])\s+|\n+)(?:the )?results? (?:was |were |is )?"
        rf"(?:sent|delivered) {destination}(?:[.!?](?=\s|$)|$)",
        "",
        text,
        flags=re.I,
    )
    return cleaned.strip() if cleaned != text else text


def _shown_checklist(ticket: dict) -> list[dict]:
    return [
        dict(c, text=text)
        for c in ticket.get("checklist") or []
        if (text := _without_delivery(c.get("text", ""), task=True)) or not c.get("text")
    ]


def shown_summary(ticket: dict, h=None) -> str:
    """The line the phone shows on top of the ticket chat: the summary, else the ticket's note (what the
    person asked for), so a fresh ticket made on the dashboard never shows an empty chat. Secrets cut (and
    stored key values, with the value hider `h`)."""
    summary = str(ticket.get("summary") or "").strip()
    note = str(ticket.get("note") or "").strip()
    summary = _without_delivery(summary)
    text = summary or note
    return _clip(text, 200, h) if text else ""


def _view_step(c: dict, h) -> dict:
    step = {"text": _clip(c.get("text", ""), 500, h) or "Task", "done": bool(c.get("done"))}
    if c.get("wont_do") and not step["done"]:  # a person's "Won't do": struck through on the phone
        step["wont_do"] = True
        if reason := _clip(str(c.get("reason") or ""), 200, h):
            step["reason"] = reason
    return step


def _status(ticket: dict) -> str:
    s = ticket.get("status", "open")
    return s if s in STATUSES else "open"


def _closed_view(ticket: dict, running: bool, done: int, total: int) -> dict:
    """The full view when stored key values can not be hidden (no value hider) or a text still holds one
    after hiding: no text from the ticket at all (fail closed), only counts and the status."""
    return {
        "title": "Ticket",
        "status": _status(ticket),
        "running": running,
        "checklist": [],
        "done": done,
        "total": total,
        "history_tail": [],
        "attachments": [],
    }


def build(root: Path, ticket: dict, atts: list[dict], h=None) -> dict:
    """The full view. Every text goes through the scrub and the value hider `h` (built here when not given):
    a stored key value never leaves, also in prose without a label. No value hider, or a value still in the
    finished view: _closed_view (fail closed)."""
    checklist = _shown_checklist(ticket)
    done, wont, total = tickets.checks_split({"checklist": checklist})
    h = h if h is not None else phone_results.value_hider(root)
    agent, running = _agent(root, ticket, h)
    if h is None:
        return _closed_view(ticket, running, done, total)
    hist = []
    for entry in (ticket.get("history") or [])[-HISTORY:]:
        if internal_wakeup(entry) or _ADMIN_NOTE.match(str(entry.get("text", ""))):
            continue
        # Ticket history has no verified relay sender; raw labels cannot name a phone.
        raw = str(entry.get("text", ""))
        text = _clip(tickets.history_line(raw, ticket.get("checklist") or []), 1000, h)
        if not text:
            continue
        at = str(entry.get("at") or "")
        if not _TIME.fullmatch(at):
            continue
        who, role = _who(entry.get("by", ""), h)
        hist.append({"at": at, "who": who, "role": role, "text": text})
    view: dict = {
        "title": _clip(ticket.get("title", ""), 200, h) or "Ticket",
        "status": _status(ticket),
        "running": running,
        "checklist": [_view_step(c, h) for c in checklist[:200]],
        "done": done,
        "total": total,
        "history_tail": hist,
        "attachments": atts,
    }
    if wont:
        view["wont_do"] = wont  # steps a person declined; "done" counts only steps done with proof
    if ticket.get("started") is True:
        view["started"] = True
    if shared_refs := reference_views(root, ticket, h):
        view["refs"] = shared_refs
    if agent:
        view["agent"] = agent
    if summary := shown_summary(ticket, h):
        view["summary"] = summary
    try:
        results = phone_results.prepare(root, result_candidates(root, ticket), h)
    except Exception:  # whatever is wrong with a result: the snapshot goes without results
        results = []
    if results:
        view["results"] = results  # full snapshots only: light_view never has them
    try:
        hidden_already = h.hide_json(view) == view  # names, agent, attachments given by the caller too
    except ValueError:
        hidden_already = False
    if not hidden_already:
        return _closed_view(ticket, running, done, total)
    return fit(view)


def fit(view: dict) -> dict:
    """Shrink under BUDGET: oldest history lines, then oldest attachments, then long task texts."""
    while size_of(view) > BUDGET and view["history_tail"]:
        view["history_tail"].pop(0)
    while size_of(view) > BUDGET and view["attachments"]:
        view["attachments"].pop()
    while size_of(view) > BUDGET and view.get("refs"):
        view["refs"].pop()
    for n in (120, 40):
        if size_of(view) > BUDGET:
            for c in view["checklist"]:
                c["text"] = c["text"] if len(c["text"]) <= n else c["text"][: n - 1] + "…"
    while size_of(view) > BUDGET and len(view.get("results") or []) > 1:
        view["results"].pop()  # the oldest first; the newest is never dropped
    while size_of(view) > BUDGET and view["checklist"]:
        view["checklist"].pop()
    return view


def view_for(root: Path, tid: str) -> dict | None:
    """The snapshot of a ticket now (uploads proof files on the way). None when the ticket can't be read, or
    when no value hider can be built (stored key values could not be hidden: the text goes without a view)."""
    try:
        ticket = tickets.load(root, tid)
    except (Refused, ValueError, KeyError, OSError):
        return None
    h = phone_results.value_hider(root)
    if h is None:
        return None
    state = load_state(root)
    atts = attachments(root, ticket, state)  # uploads: never under the lock

    def merge(st):
        st["blobs"].update(state["blobs"])
        skipped = st.setdefault("secret_skipped", [])
        skipped.extend(key for key in state.get("secret_skipped", []) if key not in skipped)
        del skipped[:-200]

    update_state(root, merge)
    return build(root, ticket, atts, h)


def _tasks_sig(ticket: dict, root: Path | None = None) -> str:
    """What the phone's snapshot depends on: tasks, status and whether an agent runs now (so "<agent> is
    working" on the phone ends when the agent stops, not only when a task changes)."""
    items = [
        [c.get("text"), bool(c.get("done")), *([True] if c.get("wont_do") else [])]
        for c in ticket.get("checklist") or []
    ]
    running = _agent(root, ticket)[1] if root is not None else None
    data = [items, ticket.get("status"), running]
    if ticket.get("started") is True:
        data.append(True)
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]


def remember(root: Path, tid: str, to: str) -> None:
    """The phone follows this ticket now: later task changes go to `to` quietly."""
    if not (to == "phones" or to.startswith("ph_")):
        return
    try:
        ticket = tickets.load(root, tid)
    except (Refused, ValueError, KeyError, OSError):
        return
    sig, status = _tasks_sig(ticket, root), ticket.get("status")

    phones = _paired(root) if to == "phones" else [to]

    def put(state):
        state["tickets"][tid] = {"to": to, "sig": sig, "at": time.time(), "status": status}
        for ph in phones:  # the phone has a chat for the ticket now: sync_open skips it, light updates follow
            _listed_now(state, ticket, ph, time.time())

    with contextlib.suppress(Refused):  # the message went out already: a busy state file never makes it fail
        update_state(root, put)


LIGHT_DEBOUNCE = 5  # seconds between two light updates of one ticket


def _light_sig(ticket: dict) -> str:
    data = [
        ticket.get("status"),
        ticket.get("title"),
        shown_summary(ticket),
        ticket.get("started") is True,
        bool(ticket.get("waiting_on")),
    ]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]


def light_view(root: Path, ticket: dict) -> dict:
    """A LIGHT ticket_view (`light: true`): title, status, started, running, summary, agent, updated_at only.
    The phone overlays these on its last full snapshot. No questions, no checklist, history or files. Texts
    pass the scrub and the value hider; without a value hider (or a stored value still in it) Refused: the
    light update is not sent (sync_light backs off), never sent with a value or with a blank title."""
    h = phone_results.value_hider(root)
    if h is None:
        raise Refused("Stored key values can't be hidden right now, so no light update was sent.")
    agent, running = _agent(root, ticket, h)
    view: dict = {
        "light": True,
        "title": _clip(ticket.get("title", ""), 200, h) or "Ticket",
        "status": _status(ticket),
        "running": running,
    }
    if ticket.get("started") is True:
        view["started"] = True
    if agent:
        view["agent"] = agent
    if summary := shown_summary(ticket, h):
        view["summary"] = summary
    at = str(ticket.get("updated_at") or "")
    if _TIME.fullmatch(at):
        view["updated_at"] = at
    if h.hide_json(view) != view:
        raise Refused("A stored key value is in this ticket's text, so no light update was sent.")
    return view


LIGHT_MAX = 20  # light sends per pull
LIGHT_BACKOFF = (15, 30, 60, 120)  # seconds before a refused phone is tried again (then the last one)


def _paired(root: Path) -> list[str]:
    from orch import relay

    phones = relay._read_dir(root).get("phones", [])
    return [p["id"] for p in phones if str(p.get("id", "")).startswith("ph_")]


def _listed_now(state: dict, ticket: dict, ph: str, now: float) -> None:
    """A message with this ticket reached phone `ph`: the phone lists it now (its list is the newest update
    per ticket), so it gets light updates from here on. The relay took a message for `ph`, so a light backoff
    of that phone ends too (a passing refusal must not keep a phone's list stale for long)."""
    if not ph.startswith("ph_"):
        return
    got = state.setdefault("synced", {}).setdefault(ph, [])
    if ticket["id"] not in got:
        got.append(ticket["id"])
        got.sort()
    _set_light_baseline(state, ticket, ph, now)
    state.setdefault("light_phone", {}).pop(ph, None)


def _set_light_baseline(state: dict, ticket: dict, ph: str | None, now: float) -> None:
    """The phone got a full view of this ticket now: what it carried is the baseline for light updates."""
    if ph and ph.startswith("ph_"):
        state.setdefault("light", {}).setdefault(ticket["id"], {})[ph] = {
            "sig": _light_sig(ticket),
            "at": now,
        }


def sync_light(root: Path, now: float | None = None) -> list[tuple[str, str]]:
    """Every ticket a phone lists (any ticket update reached that phone: sync_open's full view, an update to
    the phone or to all phones) gets a LIGHT quiet update when its status, title, summary, started or waiting
    flag changes: kind note, never pushed, no question content. State is per phone. At most LIGHT_MAX sends
    per pull; a refusal backs only that phone off (15 s growing to at most 2 min, and any message the relay
    takes for the phone ends it); phones that were unpaired are forgotten.
    Returns (phone, ticket id) pairs."""
    from orch import relay

    now = time.time() if now is None else now
    paired = {
        p["id"] for p in relay._read_dir(root).get("phones", []) if str(p.get("id", "")).startswith("ph_")
    }
    all_ = {t["id"]: t for t in tickets.list_all(root)}
    due: list[tuple[str, str, dict, str]] = []

    def claim(state):
        light = state.setdefault("light", {})
        listed = {(tid, ph) for ph, ids in state.get("synced", {}).items() for tid in ids if ph in paired}
        for tid in [k for k in light if k not in all_]:  # deleted tickets
            del light[tid]
        for tid in list(light):  # no longer listed to a paired phone
            for ph in [x for x in light[tid] if (tid, x) not in listed]:
                del light[tid][ph]
            if not light[tid]:
                del light[tid]
        backoff = state.setdefault("light_phone", {})
        for ph in [x for x in backoff if x not in paired]:
            del backoff[ph]
        for tid, ph in sorted(listed):
            t = all_.get(tid)
            if t is None or len(due) >= LIGHT_MAX or now < backoff.get(ph, {}).get("retry", 0):
                continue
            sig, rec = _light_sig(t), light.setdefault(tid, {}).get(ph)
            if rec is None:  # first sight: what the listing carried is the baseline
                light[tid][ph] = {"sig": sig, "at": now}
            elif (
                rec.get("sig") != sig
                and now - rec.get("at", 0) >= LIGHT_DEBOUNCE
                and now >= rec.get("retry", 0)
            ):
                due.append((ph, tid, t, rec.get("sig")))
                rec.update(sig=sig, at=now)

    update_state(root, claim)
    sent: list[tuple[str, str]] = []
    bad_phones: set[str] = set()
    for i, (ph, tid, t, _before) in enumerate(due):
        if ph in bad_phones:
            continue
        try:
            relay.send_text(root, ph, f"Status: {_status(t)}", tid, "note", view=light_view(root, t))
            sent.append((ph, tid))
            if ph in (load_state(root).get("light_phone") or {}):  # recovered: forget the backoff
                update_state(root, lambda st, ph=ph: st.get("light_phone", {}).pop(ph, None))
            continue
        except Refused:
            pass

        rest = tuple(d for d in due[i:] if d[0] == ph)

        def undo(st, bad=ph, rest=rest):
            for ph2, tid2, _t, before2 in rest:  # unsent ones go again later (no new sig, so nothing is lost)
                if rec := st.get("light", {}).get(tid2, {}).get(ph2):
                    rec.update(sig=before2, at=0)
            b = st.setdefault("light_phone", {}).setdefault(bad, {})
            b["fails"] = b.get("fails", 0) + 1
            b["retry"] = now + LIGHT_BACKOFF[min(b["fails"], len(LIGHT_BACKOFF)) - 1]

        with contextlib.suppress(Refused):
            update_state(root, undo)
        bad_phones.add(ph)  # this phone waits for its backoff; the other phones still get theirs
    return sent


FINISHED = ("review", "done")


def result_text(ticket: dict, h) -> str:
    """The pushed "it is finished" text: the title, then where things stand; scrubbed and value-hidden (`h`,
    phone_results.value_hider). relay.send_text hides nothing itself. No value hider (None): the word only,
    fail closed."""
    word = "Ready for your review" if ticket.get("status") == "review" else "Done"
    if h is None:
        return word
    text = f"{word}: {_clip(ticket.get('title', ''), 120, h)}"
    if summary := _without_delivery(ticket.get("summary") or ""):
        text += f"\n{_clip(summary, 400, h)}"
    return text


def _just_finished(prev, ticket: dict) -> bool:
    return prev is not None and prev not in FINISHED and ticket.get("status") in FINISHED


RESULT_MAX_CLAIMS = 3  # claims per review round after definite refusals
RESULT_LEASE = 30  # seconds an unsent result record is left to the pass that claimed it before a retry


def _claim_result(state: dict, tid: str, to: str) -> dict | None:
    """The ONE place that decides a result goes out (called under the state lock): a small outbox entry
    {mid, nonce, to, at, sent} per (ticket, review round). Returns the new entry, or None when this round
    already has one (sent, or claimed and still to be retried by _retry_results). The entry keeps its message
    id, so every retry sends the same message and the relay drops a duplicate. It is dropped when the ticket
    is seen outside Review/Done (a new round: an unsent result is dropped when the ticket leaves Review/Done)
    or on a definite refusal (compare-and-set on the nonce, at most RESULT_MAX_CLAIMS times per round)."""
    from orch import relay

    results = state.setdefault("results", {})
    if tid in results:
        return None
    if state.get("result_refused", {}).get(tid, 0) >= RESULT_MAX_CLAIMS:
        return None  # the relay refused this round's result for good several times: stop asking
    rec = {
        "mid": relay.new_id(),
        "nonce": f"{os.getpid()}-{time.monotonic_ns()}",
        "to": to,
        "at": time.time(),
        "sent": False,
    }
    results[tid] = rec
    return rec


def _retry_results(state: dict, all_: list, skip: set) -> list[tuple]:
    """Unsent result entries of tickets still in Review/Done (a crash, an ambiguous error or a bug kept
    them): due again with the same message id, never lost. The lease keeps two passes off one entry."""
    out, now = [], time.time()
    for t in all_:
        rec = state.get("results", {}).get(t["id"])
        if not rec or rec.get("sent") or t["id"] in skip or t.get("status") not in FINISHED:
            continue
        if now - rec.get("at", 0) < RESULT_LEASE:
            continue
        rec["at"] = now
        out.append((t["id"], rec["to"], t, rec, None, None))
    return out


def _definite_refusal(e: Refused) -> bool:
    """The relay said no for good: 400-499 except 408 and 429. A 5xx (also 502/503), a timeout or no status
    may have been stored, so those keep the entry."""
    status = getattr(e, "status", None)
    return isinstance(status, int) and 400 <= status < 500 and status not in (408, 429)


def sync(root: Path, now: float | None = None) -> list[str]:
    """Snapshots for followed tickets whose tasks, status or running agent changed, at most one per ticket
    every DEBOUNCE seconds (a change in between waits for the next pull). Quiet (kind note, never pushed),
    except when the ticket just moved to Review or Done: then a pushed `result` (fb11), unless the agent sent
    one itself (remember() then already saw the new status). A ticket nobody follows yet that moves to Review
    or Done sends its result to the phones too, in Mobile mode or when it (or a parent) came from the phone.
    Returns the ticket ids sent."""
    from orch import mobile_mode, relay

    now = time.time() if now is None else now
    on = False
    with contextlib.suppress(Refused, OSError, ValueError):
        on = mobile_mode.routes_to_phone(root)
    all_ = tickets.list_all(root)
    due: list[tuple] = []  # (ticket id, to, ticket, finished just now, status before, claimed sig or None)

    def claim(state):
        # under the lock: decide what goes out and mark it as sent first, so two pulls never send it twice
        seen = state.setdefault("status", {})
        for tid, rec in state["tickets"].items():
            t = next((x for x in all_ if x["id"] == tid), None)
            if t is None:
                continue
            sig = _tasks_sig(t, root)
            if sig == rec.get("sig") or now - rec.get("at", 0) < DEBOUNCE:
                continue
            fin = _claim_result(state, tid, rec["to"]) if _just_finished(rec.get("status"), t) else None
            due.append((tid, rec["to"], t, fin, rec.get("status"), sig))
            rec.update(sig=sig, at=now, status=t.get("status"))
        for t in all_:
            tid, prev = t["id"], seen.get(t["id"])
            seen[tid] = t.get("status")
            if t.get("status") not in FINISHED:
                state.get("results", {}).pop(tid, None)  # left Review/Done: the next finish is a new round
                state.get("result_refused", {}).pop(tid, None)
            if tid in state["tickets"] or not _just_finished(prev, t):
                continue
            with contextlib.suppress(Refused, OSError, ValueError):
                if on or mobile_mode.from_phone(root, tid):
                    if fin := _claim_result(state, tid, "phones"):
                        due.append((tid, "phones", t, fin, prev, None))
        due.extend(_retry_results(state, all_, {d[0] for d in due if d[3]}))

    update_state(root, claim)
    sent = []
    for tid, to, t, finished, before, claimed in due:
        shown = {"checklist": _shown_checklist(t)}
        if finished:
            if _send_result(root, tid, to, t, finished):
                sent.append(tid)
            continue
        try:
            relay.send_text(root, to, f"Tasks: {tickets.progress_text(shown)}", tid, "note", view=True)
            sent.append(tid)
        except Refused:  # not sent: undo the claim (also the status, so it is sent again next pull)

            def undo(st, tid=tid, before=before, claimed=claimed):
                # compare and set: only our own claim is undone, never a newer one another pull made meanwhile
                rec = st["tickets"].get(tid)
                if claimed is not None:
                    if rec is None or rec.get("sig") != claimed:
                        return
                    rec.update(sig=None, at=0)  # no debounce for the retry
                    if before is None:
                        rec.pop("status", None)
                    else:
                        rec["status"] = before

            with contextlib.suppress(Refused):
                update_state(root, undo)
    return sent


def _send_result(root: Path, tid: str, to: str, t: dict, rec: dict) -> bool:
    """Send one result entry with its own message id. Sent (or the relay already has it: 409) marks the entry
    sent. A definite refusal drops it, if it is still ours (nonce), so the next pull claims it again. Any
    other failure (timeout, 5xx, OSError, a bug) keeps it unsent: the next pull retries with the same id."""
    from orch import relay

    def settle(st, drop):
        cur = st.get("results", {}).get(tid)
        if not cur or cur.get("nonce") != rec["nonce"]:
            return  # a newer round's entry is never touched
        if drop:
            del st["results"][tid]
            n = st.setdefault("result_refused", {})
            n[tid] = n.get(tid, 0) + 1
            if n[tid] >= RESULT_MAX_CLAIMS:
                logging.getLogger("orch").warning(
                    "result push for %s refused %d times: giving up", tid, n[tid]
                )
            st.setdefault("status", {})[tid] = "open"  # seen as just finished again: claimed next pull
            if tid in st["tickets"]:
                st["tickets"][tid].update(sig=None, at=0, status="open")
        else:
            cur["sent"] = True

    ok = drop = False
    try:
        relay.send_text(
            root, to, result_text(t, phone_results.value_hider(root)), tid, "result", mid=rec["mid"]
        )
        ok = True
    except Refused as e:
        if getattr(e, "status", None) == 409:
            ok = True  # the relay has this message id already
        else:
            drop = _definite_refusal(e)
    except Exception:  # noqa: BLE001 - kept for retry, never lost
        pass
    if ok or drop:
        with contextlib.suppress(Refused, OSError):
            update_state(root, lambda st: settle(st, drop))
    return ok


def sync_reviews(root: Path) -> list[str]:
    """fb8: a ticket that enters Review sends the phones ONE review question ("Is this done?", options
    accept / changes, relay.send_review_question); the round (review-<n>) is open while the ticket stays in
    Review. A ticket that leaves Review (dashboard, CLI, an answer) closes its round: the question is stale
    and the next time it enters Review is a new round. Nothing goes out without a paired phone.
    Returns the ticket ids sent."""
    from orch import relay

    phones = _paired(root)
    due: list[tuple[str, dict, int, str]] = []

    def claim(state):
        rv = state.setdefault("reviews", {})
        for t in tickets.list_all(root):
            tid, rec = t["id"], rv.get(t["id"])
            if t.get("status") == "review" and t.get("general") is not True:
                if phones and not (rec and rec.get("open")):
                    n = int((rec or {}).get("round", 0)) + 1
                    mid = relay.new_id()  # the round is bound to this message: only an answer to it counts
                    rv[tid] = {"round": n, "open": True, "msg": mid}
                    due.append((tid, t, n, mid))
            elif rec and rec.get("open"):
                rec["open"] = False

    update_state(root, claim)
    sent = []
    for tid, t, n, mid in due:
        try:
            relay.send_review_question(root, t, n, mid)
            sent.append(tid)
        except (
            Refused,
            OSError,
        ):  # not sent: the round is burned (review-n is never used twice), next pull retries

            def undo(st, tid=tid, n=n, mid=mid):
                rec = st.get("reviews", {}).get(tid)
                if rec and rec.get("round") == n and rec.get("msg") == mid:
                    rec["open"] = False

            with contextlib.suppress(Refused):
                update_state(root, undo)
    return sent


def close_rounds(root: Path, tid: str) -> None:
    """The ticket left Review: its open review round is stale at once (called by tickets.apply_op under the
    ticket lock, before the new status is written). Reads first: without phones nothing is written."""
    rec = load_state(root).get("reviews", {}).get(tid)
    if not (isinstance(rec, dict) and rec.get("open")):
        return

    def op(st):
        r = st.get("reviews", {}).get(tid)
        if r:
            r["open"] = False

    update_state(root, op)


def close_review(root: Path, tid: str, n, msg_id) -> bool:
    """Close review round n of a ticket (compare and set), only for an answer to the round's own question
    message. True only for the call that closed it: the one answer that may act. A closed, older, unknown
    or other-message round is False."""
    won = []

    def op(st):
        rec = st.get("reviews", {}).get(tid)
        if rec and rec.get("open") and rec.get("round") == n and msg_id and rec.get("msg") == msg_id:
            rec["open"] = False
            won.append(True)

    update_state(root, op)
    return bool(won)


def reopen_review(root: Path, tid: str, n, msg_id) -> None:
    def op(st):
        rec = st.get("reviews", {}).get(tid)
        if rec and rec.get("round") == n and rec.get("msg") == msg_id:
            rec["open"] = True

    update_state(root, op)


NEW_TEXT = "Ticket on your workspace"
OPEN_MAX = 20  # open tickets the phone gets a chat for (newest first)
DONE_HOURS = 24  # a finished ticket stays on the phone this long


def _is_recent(ticket: dict, now: float) -> bool:
    if ticket.get("status") not in ("done", "dropped"):
        return True
    try:
        at = datetime.fromisoformat(str(ticket.get("updated_at"))).timestamp()
    except ValueError:
        return False
    return now - at <= DONE_HOURS * 3600


def sync_open(root: Path, now: float | None = None) -> list[str]:
    """Every open ticket (and a done one for 24 h) gets a chat on every paired phone: one quiet note with
    the snapshot (kind note, never pushed), at most OPEN_MAX, newest first, once per ticket and phone.
    It goes to the phone's own address: a note to "phones" is only shown to phones that were paired when
    it was sent, so a phone paired later would never see the old tickets. Returns the ticket ids sent."""
    from orch import relay

    now = time.time() if now is None else now
    phones = [
        p["id"] for p in relay._read_dir(root).get("phones", []) if str(p.get("id", "")).startswith("ph_")
    ]
    if not phones:
        return []
    state = load_state(root)
    done_for = state.setdefault("synced", {})
    open_ = [t for t in tickets.list_all(root) if _is_recent(t, now)]
    open_.sort(key=lambda t: str(t.get("created_at", "")), reverse=True)
    sent: list[str] = []
    for ph in phones:
        have = set(done_for.get(ph, []))
        for t in [t for t in open_[:OPEN_MAX] if t["id"] not in have]:
            progress = tickets.progress_text({"checklist": _shown_checklist(t)})
            text = f"Tasks: {progress}" if progress else NEW_TEXT
            try:
                relay.send_text(root, ph, text, t["id"], "note", view=True)
            except Refused:
                break  # the relay is away or refuses this phone: the next pull tries again
            have.add(t["id"])

            def mark(st, ph=ph, t=t):
                _listed_now(st, t, ph, time.time())

            update_state(root, mark)
            if t["id"] not in sent:
                sent.append(t["id"])
    return sent

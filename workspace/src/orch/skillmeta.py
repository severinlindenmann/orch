"""The flat skill header (skill format, ORCH-531) and `orch skill check | list | show`.

A skill header is the open-standard frontmatter: six top-level keys (name, description, license, compatibility,
allowed-tools, metadata), and `metadata` is one level of text values. Lists inside metadata are one line with
commas ("gh, git"). The reader is small on purpose and refuses anything fancier (nested maps, anchors, block
values, lists) instead of guessing; strict tools such as claude.ai upload refuse those too.

Shared by the install rules, the not-ready note and the relay: nobody else parses a SKILL.md header.
Other modules add checks that need every skill at once by appending to CHECKS (fn(entries, root) -> findings).
"""
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from orch.errors import Refused

STANDARD_KEYS = ("name", "description", "license", "compatibility", "allowed-tools", "metadata")
STATUS_WORDS = ("draft", "active", "deprecated", "retired")
PLATFORM_WORDS = ("macos", "windows", "linux")
PLATFORM_ALIASES = {"mac": "macos", "darwin": "macos", "osx": "macos", "win": "windows"}
NAME_MAX = 64
DESCRIPTION_MAX = 1024  # the standard's limit
DESCRIPTION_LONG = 600  # loaded in every session of every helper: a warning above this
DESCRIPTION_MIN = 20  # shorter cannot say what the skill does and when to use it

_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_KEY = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")
_NOT_TEXT = re.compile(
    r"^(?:[-+]?\d[\d_]*(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?|0x[0-9a-f_]+|0o[0-7_]+"
    r"|[-+]?\.inf|\.nan|true|false|yes|no|on|off|null|~)$",
    re.I,
)


_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "0": "\0", " ": " "}


class HeaderError(Refused):
    """A SKILL.md header this reader will not read; the message says what to change."""


def _scalar(raw: str, where: str) -> tuple[str, bool]:
    """(text, was_quoted) of one value; refuses YAML that is not a plain one-line text."""
    v = raw.strip()
    if not v or v.startswith("#"):
        return "", False
    if v[0] == '"':
        end, out, i = None, [], 1
        while i < len(v):
            c = v[i]
            if c == "\\" and i + 1 < len(v):
                e = v[i + 1]
                if e in _ESCAPES:
                    out.append(_ESCAPES[e])
                    i += 2
                    continue
                width = {"x": 2, "u": 4, "U": 8}.get(e)
                digits = v[i + 2 : i + 2 + width] if width else ""
                if (
                    not width
                    or len(digits) != width
                    or not re.fullmatch(r"[0-9A-Fa-f]+", digits)
                    or int(digits, 16) > 0x10FFFF
                    or 0xD800 <= int(digits, 16) <= 0xDFFF
                    or (int(digits, 16) < 0x20 and int(digits, 16) not in (9, 10))
                ):
                    raise HeaderError(
                        f"{where}: the escape \\{e} is not read here. Write the character itself."
                    )
                out.append(chr(int(digits, 16)))
                i += 2 + width
                continue
            if c == '"':
                end = i
                break
            out.append(c)
            i += 1
        rest = v[end + 1 :].strip() if end is not None else None
        if end is None or (rest and not rest.startswith("#")):
            raise HeaderError(f"{where}: the quoted value does not end where it should. Keep it on one line.")
        return "".join(out), True
    if v[0] == "'":
        m = re.match(r"^'((?:[^']|'')*)'\s*(#.*)?$", v)
        if not m:
            raise HeaderError(f"{where}: the quoted value does not end where it should. Keep it on one line.")
        return m.group(1).replace("''", "'"), True
    if v[0] in "|>":
        raise HeaderError(f"{where}: a block value ({v[0]}) is not read here. Write the value on one line.")
    if v[0] in "&*!":
        raise HeaderError(f"{where}: anchors, aliases and tags are not read here. Write plain text.")
    if v[0] in "[{":
        raise HeaderError(
            f'{where}: a list or map is not read here. Write one line with commas, like "gh, git".'
        )
    if v.startswith("- "):
        raise HeaderError(f'{where}: a list is not read here. Write one line with commas, like "gh, git".')
    v = re.split(r"\s+#", v, maxsplit=1)[0].rstrip()
    if ": " in v or v.endswith(":"):
        raise HeaderError(
            f"{where}: a value with a colon must be in quotes, or YAML reads it as a map. Put it in quotes."
        )
    return v, False


def _reads_as_not_text(val: str) -> bool:
    return bool(_NOT_TEXT.match(val) or re.match(r"^\d{4}-\d\d-\d\d", val))


def parse_header(text: str) -> tuple[dict, list[tuple[str, str]]]:
    """The header of a SKILL.md text and the metadata keys whose plain value a YAML reader would not take as
    text (a number, true/false, a date): ({"name": ..., "metadata": {...}}, [("metadata", "version")]). Raises HeaderError."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise HeaderError("SKILL.md does not start with a --- header.")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise HeaderError("The SKILL.md header has no closing --- line.") from None
    out: dict = {}
    not_text: list[tuple[str, str]] = []
    in_meta, meta_indent = False, ""
    for n, ln in enumerate(lines[1:end], start=2):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indented = ln[0] in " \t"
        m = _KEY.match(ln.strip())
        if indented:
            if not in_meta:
                raise HeaderError(
                    f"Line {n}: only metadata may have indented lines. Write the value on one line."
                )
            if not m:
                raise HeaderError(f"Line {n}: write metadata as key: value.")
            key, raw = m.group(1), m.group(2) or ""
            indent = ln[: len(ln) - len(ln.lstrip())]
            if meta_indent and indent != meta_indent:
                raise HeaderError(
                    f"Line {n}: metadata is one level deep. Give {key!r} the same indent as the others."
                )
            meta_indent = indent
            if not raw.strip():
                raise HeaderError(
                    f"Line {n}: metadata {key!r} needs a text value (one level only, no nested map)."
                )
            val, quoted = _scalar(raw, f"Line {n}")
            if not quoted and not val:
                raise HeaderError(
                    f"Line {n}: metadata {key!r} needs a text value (one level only, no nested map)."
                )
            if not quoted and _reads_as_not_text(val):
                not_text.append(("metadata", key))
            if key in out["metadata"]:
                raise HeaderError(f"Line {n}: metadata {key!r} is written twice.")
            out["metadata"][key] = val
            continue
        if not m:
            raise HeaderError(f"Line {n}: write the header as key: value.")
        key, raw = m.group(1), m.group(2) or ""
        if key in out:
            raise HeaderError(f"Line {n}: {key!r} is written twice.")
        if key == "metadata":
            if raw.strip() and raw.strip() != "{}":
                raise HeaderError(f"Line {n}: put each metadata value on its own indented line.")
            out["metadata"], in_meta, meta_indent = {}, not raw.strip(), ""
            continue
        in_meta = False
        out[key], quoted = _scalar(raw, f"Line {n}")
        if not quoted and _reads_as_not_text(out[key]):
            not_text.append(("", key))
    out.setdefault("metadata", {})
    return out, not_text


def read_header(skill_dir: Path) -> dict:
    """{"name", "description", ..., "metadata": {str: str}} of <skill_dir>/SKILL.md; raises HeaderError."""
    f = Path(skill_dir) / "SKILL.md"
    try:
        text = f.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise HeaderError(f"{f} cannot be read ({e.__class__.__name__}).") from None
    return parse_header(text)[0]


def try_header(skill_dir: Path) -> dict:
    """read_header, or {} when there is no readable header (for code that only wants what is there)."""
    try:
        return read_header(skill_dir)
    except HeaderError:
        return {}


def split_list(value: object) -> list[str]:
    """A comma list ("gh, git") as its non-empty parts."""
    return [w.strip() for w in str(value or "").split(",") if w.strip()]


# --- the check ---------------------------------------------------------------------------------------------

CHECKS: list = []  # fn(entries: list[dict], root: Path | None) -> list[finding]; other modules append (requires-skills)


def _finding(skill: str, level: str, field: str, message: str) -> dict:
    return {"skill": skill, "level": level, "field": field, "message": message}


def _templated(skill_dir: Path, desc: str) -> bool:
    """An orch source skill whose description is rendered at install from description.toml."""
    return "{{description}}" in desc and (Path(skill_dir) / "description.toml").is_file()


def _missing_here(root: Path | None, meta: dict) -> list[str]:
    try:
        from orch import skillready  # the not-ready note (ORCH-534) knows logins and add-ons too
    except ImportError:
        skillready = None
    if skillready is not None and root is not None and hasattr(skillready, "missing"):
        return list(skillready.missing(root, meta))
    return [p for p in split_list(meta.get("requires")) if shutil.which(p) is None]


def check_skill(skill_dir: Path, *, name: str | None = None, root: Path | None = None) -> list[dict]:
    """Findings for one skill folder: level "error" (the format is broken) or "warn" (works, but look)."""
    skill_dir = Path(skill_dir)
    name = name or skill_dir.name
    f = lambda level, field, msg: _finding(name, level, field, msg)  # noqa: E731
    try:
        text = (skill_dir / "SKILL.md").read_bytes().decode("utf-8")
        head, not_text = parse_header(text)
    except FileNotFoundError:
        return [f("error", "SKILL.md", "There is no SKILL.md in this folder.")]
    except (OSError, UnicodeDecodeError) as e:
        return [f("error", "SKILL.md", f"SKILL.md cannot be read ({e.__class__.__name__}).")]
    except HeaderError as e:
        return [f("error", "header", str(e))]
    out = []
    hname = head.get("name", "")
    if not hname:
        out.append(f("error", "name", "The header has no name."))
    elif hname != skill_dir.name:
        out.append(f("error", "name", f"The name {hname!r} is not the folder name {skill_dir.name!r}."))
    elif len(hname) > NAME_MAX or not _NAME.match(hname):
        out.append(
            f("error", "name", f"Use lowercase letters, digits and single dashes, at most {NAME_MAX}.")
        )
    desc = head.get("description", "")
    if not desc.strip():
        out.append(f("error", "description", "The header has no description."))
    elif not _templated(skill_dir, desc):
        if len(desc) > DESCRIPTION_MAX:
            out.append(
                f(
                    "error",
                    "description",
                    f"The description is {len(desc)} characters; at most {DESCRIPTION_MAX}.",
                )
            )
        elif len(desc) > DESCRIPTION_LONG:
            out.append(
                f(
                    "warn",
                    "description",
                    f"The description is {len(desc)} characters and is read in every session; move details into the text.",
                )
            )
        if len(desc.strip()) < DESCRIPTION_MIN:
            out.append(
                f(
                    "error",
                    "description",
                    "The description is too short to say what the skill does and when to use it.",
                )
            )
    for key in head:
        if key not in STANDARD_KEYS:
            out.append(f("error", key, f"{key!r} is not a standard header field; move it under metadata."))
    meta = head.get("metadata") or {}
    for scope, key in not_text:
        value = (meta if scope else head).get(key, "")
        path, label = (f"metadata.{key}", f"metadata {key!r}") if scope else (key, repr(key))
        out.append(
            f(
                "error",
                path,
                f'{label} is read as a number, a date or yes/no; put it in quotes, like "{value}".',
            )
        )
    status = meta.get("status")
    if status is not None and status not in STATUS_WORDS:
        out.append(
            f("error", "metadata.status", f"Unknown status {status!r}; use one of {', '.join(STATUS_WORDS)}.")
        )
    if status in ("deprecated", "retired") and not meta.get("replaced-by"):
        out.append(
            f("warn", "metadata.replaced-by", f"A {status} skill should say what replaces it (replaced-by).")
        )
    if "platforms" in meta:
        words = split_list(meta["platforms"])
        if not words:
            out.append(
                f("error", "metadata.platforms", "platforms is empty; leave it out for every platform.")
            )
        for w in words:
            if w.lower() in PLATFORM_ALIASES:
                out.append(
                    f(
                        "warn",
                        "metadata.platforms",
                        f"Write {PLATFORM_ALIASES[w.lower()]!r} instead of {w!r}.",
                    )
                )
            elif w not in PLATFORM_WORDS:
                out.append(
                    f(
                        "error",
                        "metadata.platforms",
                        f"Unknown platform {w!r}; use {', '.join(PLATFORM_WORDS)}.",
                    )
                )
    missing = _missing_here(root, meta)
    if missing:
        out.append(f("warn", "metadata.requires", "Not ready here: " + ", ".join(missing) + " missing."))
    return out


def check_all(entries: list[dict], root: Path | None = None) -> list[dict]:
    """Every finding for these list_skills() entries: each skill alone, then the CHECKS over all of them."""
    try:
        import orch.skillreview  # noqa: F401  (adds its checks to CHECKS when it is there)
    except ImportError:
        pass
    out = []
    for e in entries:
        out += check_skill(Path(e["path"]), name=e["name"], root=root)
    for fn in CHECKS:
        out += list(fn(entries, root))
    return out


# --- the list ----------------------------------------------------------------------------------------------


def _active_addons(root: Path) -> set[str]:
    try:
        return set((json.loads((root / ".orch" / "addons.json").read_text()) or {}).get("active") or {})
    except (OSError, ValueError, AttributeError):
        return set()


def _entry(name: str, path: Path, source: str) -> dict:
    try:
        return {"name": name, "path": str(path), "source": source, "header": read_header(path), "error": None}
    except HeaderError as e:
        return {"name": name, "path": str(path), "source": source, "header": None, "error": str(e)}


def list_skills(root: Path) -> list[dict]:
    """Every skill of this workspace: orch's and the add-ons' (.orch/harness/skills), then the workspace's own
    and the relay's (real folders or outside links in .agents/skills). Each with its parsed header or why not."""
    from orch import harness

    root = Path(root)
    hs = harness.harness_dir(root) / "skills"
    active = _active_addons(root)
    out, seen = [], set()
    if hs.is_dir() and not harness.is_link(hs):
        for p in sorted(hs.iterdir()):
            if p.is_dir() and not harness.is_link(p) and harness.safe_skill_name(p.name):
                short = p.name.removeprefix("orch-")
                src = f"addon:{short}" if p.name != "orch" and short in active else "orch"
                out.append(_entry(p.name, p, src))
                seen.add(p.name)
    base = root / ".agents" / "skills"
    if base.is_dir():  # read-only, so a linked .agents/skills (harness.link_skill) is read too
        hs_real = hs.resolve() if hs.is_dir() else None
        for p in sorted(base.iterdir()):
            if p.name in seen or not p.is_dir() or not harness.safe_skill_name(p.name):
                continue
            if hs_real is not None and hs_real in p.resolve().parents:
                continue  # a link orch made to its own copy
            src = "relay" if (p / ".orch-shared").exists() else "workspace"
            out.append(_entry(p.name, p, src))
            seen.add(p.name)
    return out


def find(root: Path, name: str) -> dict:
    for e in list_skills(root):
        if e["name"] == name:
            return e
    raise Refused(f"There is no skill {name!r} here. See them with: orch skill list")

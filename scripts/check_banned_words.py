#!/usr/bin/env python3
"""R4.1 banned-word diff check (stdlib only).

Fails when a line ADDED by the PR contains sign/signing/signature, certificate, keypair, approval or gate
(whole words, case-insensitive). Deleted lines never count, and a word the same file loses on a deleted line
cancels one re-added copy (one-line mockup pages re-add every word when a link changes). Passes when the PR has
the label `owner-approved`.
Real necessary hits go in scripts/banned_words_allowlist.txt (one path glob per line, `#` comments).

Usage: check_banned_words.py --base origin/develop [--labels "a,b"] [--repo DIR]
"""

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

BANNED = re.compile(r"(?<![A-Za-z])(signing|signature|signatures|sign|certificate|certificates|keypair|keypairs|approval|approvals|gate)(?![A-Za-z])", re.I)
LABEL = "owner-approved"
ALLOWLIST = Path(__file__).with_name("banned_words_allowlist.txt")
# "sign in / sign-in / sign out / sign up" is the normal page login (allowed by R4.1), not signing
LOGIN = re.compile(r"(?<![A-Za-z])sign(?:ed|s)?[ _-]?(?:in|out|up|on)(?![A-Za-z])", re.I)
HUNK = re.compile(r"^@@ -\S+ \+(\d+)")


def allow_patterns(path: Path = ALLOWLIST) -> list[str]:
    if not path.exists():
        return []
    lines = (ln.split("#", 1)[0].strip() for ln in path.read_text().splitlines())
    return [ln for ln in lines if ln]


def changed_lines(diff: str):
    """Yield (sign, file, line number, text) for every added (+) and deleted (-) line of a unified diff.

    The file is the new path; deleted files (+++ /dev/null) are skipped. Header lines are only read before
    the first hunk of each file, so a deleted line whose text starts with "--" is not taken for a header.
    """
    name, lineno, in_header = None, 0, False
    for raw in diff.splitlines():
        if raw.startswith("diff "):
            name, in_header = None, True
        elif in_header and raw.startswith("+++ "):
            name = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            in_header = False
            m = HUNK.match(raw)
            lineno = int(m.group(1)) if m else 0
        elif in_header or not name:
            continue
        elif raw.startswith("+"):
            yield "+", name, lineno, raw[1:]
            lineno += 1
        elif raw.startswith("-"):
            yield "-", name, lineno, raw[1:]
        elif raw.startswith(" "):
            lineno += 1


def words(text: str) -> list[str]:
    return [m.group(1).lower() for m in BANNED.finditer(LOGIN.sub(" ", text))]


def find_hits(diff: str, allow: list[str]) -> list[tuple[str, int, str]]:
    if not diff.startswith("diff "):
        diff = "diff --git\n" + diff  # bare hunks (tests) start with the file header
    removed: dict[tuple[str, str], int] = {}
    added = []
    for sign, name, lineno, text in changed_lines(diff):
        if any(fnmatch.fnmatch(name, p) for p in allow):
            continue
        for word in words(text):
            if sign == "-":
                removed[(name, word)] = removed.get((name, word), 0) + 1
            else:
                added.append((name, lineno, word))
    hits = []
    for name, lineno, word in added:
        if removed.get((name, word), 0) > 0:
            removed[(name, word)] -= 1
        else:
            hits.append((name, lineno, word))
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="base ref, e.g. origin/develop")
    ap.add_argument("--labels", default="", help="comma separated PR labels")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    if LABEL in [x.strip() for x in args.labels.split(",")]:
        print(f"label {LABEL} present: banned-word check skipped")
        return 0
    diff = subprocess.run(
        ["git", "-C", args.repo, "diff", "--unified=0", f"{args.base}...HEAD"], capture_output=True, text=True, check=True
    ).stdout
    hits = find_hits(diff, allow_patterns())
    for name, lineno, word in hits:
        print(f"{name}:{lineno}: {word}")
    if hits:
        print("Banned words added: remove the concept (R4.1) or ask the owner for the owner-approved label.")
        return 1
    print("no banned words added")
    return 0


if __name__ == "__main__":
    sys.exit(main())

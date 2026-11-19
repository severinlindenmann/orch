#!/usr/bin/env python3
"""Every file in the repository checks out on Windows without core.longpaths (ORCH-872, stdlib only).

Git for Windows refuses a path longer than 260 characters unless core.longpaths is on, and then leaves the checkout
half-done. The clone folder counts too (C:\\Users\\<name>\\OneDrive - <company>\\Documents\\... easily takes 100), so a
path inside the repository may be at most MAX_LEN characters. This check also fails on names Windows cannot hold:
  - a reserved device name as a part (CON, PRN, AUX, NUL, COM1-9, LPT1-9, COM and LPT with ¹ ² ³; also with an
    extension: aux.txt),
  - a part that ends in a dot or a space,
  - one of < > : " | ? * \\ or a control character,
  - two paths that differ only in upper and lower case (one of them is lost on Windows and macOS).

Usage: check_windows_paths.py [--repo DIR]
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

MAX_LEN = 120
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9\u00b9\u00b2\u00b3]|lpt[1-9\u00b9\u00b2\u00b3]) *(\..*)?$", re.IGNORECASE)
BAD_CHARS = re.compile(r'[<>:"|?*\\\x00-\x1f]')


def problems(paths: list[str]) -> list[str]:
    """What is wrong in a list of repository paths (empty when every one is fine)."""
    out = []
    seen: dict[str, str] = {}
    reported: set[tuple[str, str]] = set()
    for rel in sorted(paths):
        if len(rel) > MAX_LEN:
            out.append(f"{rel}: path is {len(rel)} characters, at most {MAX_LEN} (Windows stops the checkout)")
        parts = rel.split("/")
        for part in parts:
            if RESERVED.match(part):
                out.append(f"{rel}: '{part}' is a reserved name on Windows")
            if part.endswith((".", " ")):
                out.append(f"{rel}: '{part}' ends in a dot or a space, which Windows drops")
            if BAD_CHARS.search(part):
                out.append(f"{rel}: '{part}' holds a character Windows does not allow in a file name")
        # the file and every folder above it: two spellings of one name are one name on Windows
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            other = seen.setdefault(prefix.lower(), prefix)
            if other != prefix and (other, prefix) not in reported:
                reported.add((other, prefix))
                out.append(f"{rel}: '{prefix}' and '{other}' differ only in upper and lower case")
    return out


def files(repo: Path) -> list[str]:
    listed = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True)
    return [n for n in listed.stdout.decode("utf-8").split("\0") if n]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    found = problems(files(Path(ap.parse_args(argv).repo)))
    for p in found:
        print(p)
    if found:
        print(f"\n{len(found)} path(s) would break a checkout on Windows. Shorten or rename them (ORCH-872).")
        return 1
    print(f"Every path checks out on Windows (at most {MAX_LEN} characters, no reserved or clashing names).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

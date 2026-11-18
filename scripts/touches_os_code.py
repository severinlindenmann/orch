#!/usr/bin/env python3
"""Does this change touch file, process or path code? Then its pull request also runs the Windows tests.

Windows breaks where code moves files, sets file times or rights, starts or stops processes, or builds paths
(78 Windows failures went unseen in Nov 2026: a test called os.utime in a way Windows refuses). This reads the
diff against the base branch and answers `true` when a changed Python line under workspace/ or
workspace-addons/ uses such a call, or when a file whose job is exactly that changed (WHOLE_FILES).

Usage: python3 scripts/touches_os_code.py --base origin/develop   prints true or false (exit 0)
       python3 scripts/touches_os_code.py --base origin/develop --why   also names the first lines that matched
Plain text over `git diff`; no packages.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# files that are about files, processes, rights or paths through and through: any change runs Windows
WHOLE_FILES = re.compile(
    r"^(install\.ps1|install\.sh|e2e/windows/.*"
    r"|workspace/src/orch/(home|procs|safefile|winacl|winfinish|filesig|record_files)\.py)$"
)
# Python files where a changed line is read
CODE = re.compile(r"^(workspace/|workspace-addons/[^/]+/src/).*\.py$")
# an import alone changes nothing on any system
IMPORT = re.compile(r"^\s*(import|from)\s")
# calls that behave differently on Windows: file moves, times and rights, links, processes, signals, path parts
OS_CALL = re.compile(
    r"\b(subprocess|Popen|shutil\.|signal\.|tempfile\.|ctypes|msvcrt|fcntl|winreg"
    r"|os\.(replace|rename|remove|unlink|rmdir|utime|chmod|chown|stat|lstat|kill|killpg|getpid|getppid"
    r"|symlink|link|readlink|makedirs|mkdir|scandir|walk|open|fdopen|fsync|sep|pathsep|linesep|devnull"
    r"|getcwd|chdir|access|umask|setsid|fork|spawn|exec|startfile)"
    r"|os\.path\.|\.(chmod|symlink_to|hardlink_to|readlink|unlink|rmdir|resolve|touch|stat"
    r"|lstat|is_symlink|is_junction|as_posix|expanduser)\("
    r"|sys\.platform|os\.name|platform\.system|PureWindowsPath|PurePosixPath)"
)


def changed(base: str) -> list[tuple[str, str]]:
    """(path, line) for every added or removed line; ('path', '') for a file with no line diff (a rename)."""
    out = subprocess.run(
        ["git", "diff", "--no-color", "-U0", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return parse(out)


def parse(diff: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[-1]
            rows.append((path, ""))
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line[:1] in "+-" and path:
            rows.append((path, line[1:]))
    return rows


def reasons(rows: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for path, line in rows:
        if WHOLE_FILES.match(path):
            found.append(f"{path} changed")
        elif line and CODE.match(path):
            code = line.split("#", 1)[0]
            if not IMPORT.match(code) and OS_CALL.search(code):
                found.append(f"{path}: {line.strip()[:120]}")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="the base branch, such as origin/develop")
    ap.add_argument("--why", action="store_true", help="name the first lines that matched")
    args = ap.parse_args(argv)
    found = reasons(changed(args.base))
    print("true" if found else "false")
    if args.why:
        for r in list(dict.fromkeys(found))[:10]:
            print("  " + r, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

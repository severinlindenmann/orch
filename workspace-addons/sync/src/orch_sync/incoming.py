"""Pure incoming verdicts: inspect objects, never check out or apply them."""

import json
import math
from dataclasses import dataclass

from . import paths, repo, scan

MB = 1_000_000


@dataclass(frozen=True)
class Problem:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class Result:
    commit: str | None
    problems: list[Problem]


def strict_load(data):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out or k == "__proto__":
                raise ValueError("duplicate or unsafe key")
            out[k] = v
        return out

    value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    stack = [(value, 1)]
    while stack:
        v, depth = stack.pop()
        if isinstance(v, (dict, list)):
            if depth > 32:
                raise ValueError("JSON nesting exceeds 32")
            stack.extend((x, depth + 1) for x in (list(v) + list(v.values()) if isinstance(v, dict) else v))
        elif isinstance(v, str) and len(v.encode("utf-8")) > MB:
            raise ValueError("JSON string too long")
        elif isinstance(v, float) and not math.isfinite(v):
            raise ValueError("non-finite number")
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")  # noqa: TRY004 - malformed document
    return value


TREE_BYTES = (
    8 * MB
)  # 5000 entries with long artifact paths fit easily; a tree bomb is cut off while streaming


def tree(root, ref):
    raw = repo.git(root, "ls-tree", "-r", "-z", ref, max_output=TREE_BYTES).stdout
    return [
        (*entry.split(b"\t", 1)[0].decode("ascii").split(), entry.split(b"\t", 1)[1].decode("utf-8"))
        for entry in raw.split(b"\0")
        if entry
    ]


def _fold(prefix):
    return "/".join(scan.norm_segment(s) for s in prefix.split("/"))


def check(root, ref="origin/orch-state", *, base="HEAD", local=None, gone=()) -> Result:
    """PR 4 must merge result.commit only after accepting result.problems. `gone`: local paths a person
    renamed away (orch sync resolve --rename-local) that the next stage removes: no case clash with them."""
    # The step supplies the common ancestor: a new local-only ticket is not a remote deletion.
    problems = []
    tip = None
    try:
        repo.check(root)
        if ref.startswith("-") or not ref or any(c.isspace() for c in ref):
            raise ValueError("Invalid ref")
        # Pin once so tree, sizes and diff all describe the same commit.
        tip = repo.git(root, "rev-parse", "--verify", ref + "^{commit}").stdout.decode().strip()
        head = (
            (
                repo.git(root, "rev-parse", "--verify", base + "^{commit}").stdout
                if base
                else repo.git(root, "hash-object", "-w", "-t", "tree", "--stdin", input=b"").stdout
            )
            .decode()
            .strip()
        )
        entries, old = tree(root, tip), tree(root, head)
        if len(entries) > 5000:
            return Result(tip, [Problem("", "size", "Too many files")])
        seen = {}
        for mode, kind, oid, path in entries:
            if not paths.allowed(path) or mode != "100644" or kind != "blob":
                problems.append(Problem(path, "path", "The remote has files orch does not accept"))
            parts = path.split("/")
            for i in range(1, len(parts) + 1):
                prefix = "/".join(parts[:i])
                key = _fold(prefix)  # Fable B13: the same name on macOS/Windows (case, NFC/NFD, ignorables)
                if key in seen and seen[key] != prefix:
                    problems.append(Problem(path, "path", "Case-fold collision"))
                seen[key] = prefix
        # Fable A6/B13: an incoming name that only differs from one of this machine's files in case (a
        # case-only rename too) is the same file on a case-insensitive disk: a person decides.
        mine = {_fold(e[3]): e[3] for e in tree(root, local) if e[3] not in gone} if local else {}
        incoming_paths = {e[3] for e in entries}
        for path in sorted(incoming_paths):
            other = mine.get(_fold(path))
            if other is not None and other != path:
                problems.append(Problem(path, "path", "Same name as a local file in different case"))
        if problems:
            return Result(tip, problems)
        sizes = repo.git(
            root, "cat-file", "--batch-check", input="".join(f"{e[2]}\n" for e in entries).encode()
        ).stdout.splitlines()
        total = 0
        if len(sizes) != len(entries):
            raise ValueError("Missing object sizes")
        for entry, row in zip(entries, sizes):
            _, _, oid, path = entry
            got, kind, length = row.decode().split()
            size = int(length)
            if got != oid or kind != "blob" or size < 0:
                raise ValueError("Invalid object")
            total += size
            if size > (MB if paths.TICKET.fullmatch(path) else 25 * MB):
                problems.append(Problem(path, "size", "File exceeds sync limit"))
        if total > 500 * MB:
            problems.append(Problem("", "size", "Tree exceeds sync limit"))
        if problems:
            return Result(tip, problems)
        diff = repo.git(
            root,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-status",
            "-z",
            "--no-renames",
            f"{head}..{tip}",
            "--",
        ).stdout.split(b"\0")
        deleted = []
        for status, name in zip(diff[0::2], diff[1::2]):
            path = name.decode("utf-8")
            if status == b"D":
                if paths.TICKET.fullmatch(path):
                    problems.append(Problem(path, "ticket-deletion", "Incoming ticket deletion refused"))
                elif path == "ticket-counter.json":
                    problems.append(
                        Problem(path, "counter-deletion", "Incoming ticket counter deletion refused")
                    )
                elif paths.ARTIFACT.fullmatch(path):
                    deleted.append(path)
        count = sum(bool(paths.ARTIFACT.fullmatch(e[3])) for e in old)
        if len(deleted) > 5 or len(deleted) > count * 0.2:
            problems.append(Problem("", "needs-confirm", f"Many files were removed ({len(deleted)}). Apply?"))
        old_oids = {e[3]: e[2] for e in old}
        for _, _, oid, path in entries:
            data = repo.git(root, "cat-file", "blob", oid).stdout
            problems.extend(Problem(path, f.code, f.rule) for f in scan.scan_blob(path, data))
            if not (paths.TICKET.fullmatch(path) or path == "ticket-counter.json"):
                continue
            try:
                doc = strict_load(data)
            except (ValueError, RecursionError):
                # A content problem of one file: a person may still keep their own copy of it.
                problems.append(
                    Problem(path, "invalid", "Incoming state could not be validated: not valid JSON")
                )
                continue
            if doc.get("general") is True:
                problems.append(Problem(path, "private", "General ticket stays local"))
            if paths.TICKET.fullmatch(path):
                previous = (
                    strict_load(repo.git(root, "cat-file", "blob", old_oids[path]).stdout)
                    if path in old_oids
                    else {}
                )
                if doc.get("ext", {}) != previous.get("ext", {}):
                    problems.append(Problem(path, "held-ext", "Extension changes need local approval"))
    except (repo.Refused, ValueError, OSError, RecursionError) as e:
        problems.append(Problem("", "invalid", "Incoming state could not be validated: " + type(e).__name__))
    return Result(tip, problems)

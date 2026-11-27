#!/usr/bin/env python3
"""R9.4 contract checks (stdlib only).

1. Every vector file (contracts/vectors/*.json, one entry per sub-folder) is replayed by at least one consumer:
   its name appears in a test outside contracts/ (workspace, add-ons, relay, publish, mobile, transcription, e2e).
   Vectors with no code left to replay them are listed in NO_CONSUMER with the reason.
2. With --base: lists where the PR's changes to contract examples and vectors are not additive. A JSON file under
   contracts/examples, contracts/vectors or contracts/review may gain keys, list items and files; losing a file, a
   key or a list item, or changing a value (prose keys `about`, `note`, top-level `description` excepted) is
   printed as a warning for the reviewer. It does not fail: a fixed expected value is a real change whose
   consumers replay it in the same PR (part 1), and the owner reviews PRs labelled `contract` (AGENTS.md).

Usage: check_contracts.py [--base origin/develop] [--repo DIR]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

WATCHED = ("contracts/examples/", "contracts/vectors/", "contracts/review/")
PROSE = {"about", "note"}
CONSUMER_DIRS = ("workspace", "workspace-addons", "relay", "publish", "mobile", "transcription", "e2e", "companion")
TEST_SUFFIXES = {".py", ".rs", ".swift", ".js", ".cjs", ".mjs", ".ts", ".go"}
SKIP_DIRS = {"node_modules", ".venv", "target", "build", "__pycache__", ".git"}
# vector -> why no consumer replays it, and the issue that settles it
NO_CONSUMER = {
    "human-proof-v1": "human-proof was removed (docs/decisions.md 2026-11-15); only validate.py reads it (#3070)",
    "screen-v1": "the live screen is the dashboard terminal bridge (ORCH-743), not the orch.screen/1 stream (#3071)",
}


def vector_names(root: Path) -> list[str]:
    vec = root / "contracts" / "vectors"
    names = [p.stem for p in vec.glob("*.json")]
    names += [p.name for p in vec.iterdir() if p.is_dir()]
    return sorted(names)


def _consumer_files(root: Path):
    for d in CONSUMER_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        stack = [base]
        while stack:
            cur = stack.pop()
            for p in cur.iterdir():
                if p.is_dir():
                    if p.name not in SKIP_DIRS:
                        stack.append(p)
                elif p.suffix in TEST_SUFFIXES:
                    yield p


def unreplayed(root: Path) -> list[str]:
    """Vector names no consumer file mentions (as `<name>.json` or as the folder `vectors/<name>`)."""
    names = vector_names(root)
    left = {n: (f"{n}.json", f"vectors/{n}", f'"vectors" / "{n}"') for n in names}
    for p in _consumer_files(root):
        if not left:
            break
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for n in [n for n, keys in left.items() if any(k in text for k in keys)]:
            del left[n]
    return sorted(n for n in left if n not in NO_CONSUMER)


def losses(old, new, path="$"):
    """Where `new` is not a superset of `old`: missing keys, missing list items, changed values."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k, v in old.items():
            if path == "$" and k in PROSE | {"description"} or k in PROSE:
                continue
            if k not in new:
                out.append(f"{path}.{k}: removed")
            else:
                out += losses(v, new[k], f"{path}.{k}")
        return out
    if isinstance(old, list) and isinstance(new, list):
        out, pool = [], list(new)
        for i, item in enumerate(old):
            if i < len(new) and not losses(item, new[i]):
                continue
            hit = next((j for j, cand in enumerate(pool) if not losses(item, cand)), None)
            if hit is None:
                out.append(f"{path}[{i}]: removed or changed")
            else:
                pool.pop(hit)
        return out
    if type(old) is not type(new) or old != new:
        return [f"{path}: {json.dumps(old)[:60]} -> {json.dumps(new)[:60]}"]
    return []


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def breaking_changes(repo: Path, base: str) -> list[str]:
    """Non-additive changes to contract examples and vectors between base and HEAD."""
    out = []
    status = _git(repo, "diff", "--name-status", "--no-renames", f"{base}...HEAD", "--", *WATCHED)
    mb = _git(repo, "merge-base", base, "HEAD").strip()
    for line in status.splitlines():
        kind, name = line.split("\t", 1)
        if kind == "D":
            out.append(f"{name} file removed")
        elif kind == "M" and name.endswith(".json"):
            try:
                old = json.loads(_git(repo, "show", f"{mb}:{name}"))
                new = json.loads((repo / name).read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue  # validate.py reports files that do not parse
            out += [f"{name} {x}" for x in losses(old, new)]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="base ref for the additive check, e.g. origin/develop")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    repo, rc = Path(args.repo), 0
    missing = unreplayed(repo)
    for n in missing:
        print(f"contracts/vectors/{n}: no consumer test replays it")
    if missing:
        print("Add a replay test in every part that reads this contract (R9.4).")
        rc = 1
    if args.base:
        broken = breaking_changes(repo, args.base)
        for b in broken:
            name, _, what = b.partition(" ")
            print(f"::warning file={name}::not additive (R9.4): {what or b}")
        if broken:
            print("Contract changes should be additive (R9.4): add a new case or file; say in the PR why not.")
    if rc == 0:
        print("every contract vector is replayed by a consumer")
    return rc


if __name__ == "__main__":
    sys.exit(main())

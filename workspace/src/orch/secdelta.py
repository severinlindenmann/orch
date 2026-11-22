"""What a new head of a pull request really changed since its reviewed head (ORCH-1591), read from git only.

Two questions, both answered in the release keeper's own clone after it fetched develop and the head:

keep_check(R, H)   R = the newest head of the pull request with a security OK, H = its new head. Walks H's
                   first-parent chain back to R. Each step C has an "own part":
                     one parent      everything C changed;
                     two parents     what C changed beyond the clean automatic merge of its parents, when its
                                     second parent was a develop tip (on develop's first-parent chain: that
                                     content came through the merge queue and has its own review); a second
                                     parent anywhere else brings its whole side in, so that all counts as own;
                     more parents    everything C changed.
                   No own part touches a guarded path -> "same" (the OK is kept). Some do -> "delta" with
                   those steps (only they are reviewed). R not on the chain, or anything git does not
                   answer clearly -> "full" (today's whole review).
group_steps(G)     G = the head of a merge queue group pull request: a chain of two-parent commits
                   "Merge queue: take in #M", each the clean automatic merge of the step below and member #M's
                   head, down to a develop tip. Returns [(M, member head, guarded files of that step)], or
                   None when G is not exactly that shape (then the group is reviewed like any pull request).

git runs with replace objects off; a merge-tree that does not exit 0 (a conflict) or names another tree is
never taken as clean. Fail closed: every doubt ends in a review, never in a kept OK.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from orch import secreview

SHA = re.compile(r"[0-9a-f]{40}")
TAKE_IN = re.compile(r"Merge queue: take in #([0-9]{1,7})")
CHAIN_MAX = 400  # first-parent steps walked back to the reviewed head
GROUP_MAX = 40  # members of one group at most (the queue takes far fewer)
DEV_MAX = 20000  # develop first-parent commits read

Git = Callable[..., tuple[int, str]]  # git(*args) -> (exit code, stdout)


def develop_tips(git: Git, ref: str = "origin/develop") -> set[str] | None:
    """Every commit on develop's first-parent chain (each was develop's tip once); None on a failed read."""
    rc, out = git("rev-list", "--first-parent", f"--max-count={DEV_MAX}", ref)
    if rc != 0:
        return None
    tips = {x for x in out.split() if SHA.fullmatch(x)}
    return tips or None


def _commit(git: Git, sha: str) -> tuple[list[str], str, str] | None:
    """(parents, tree, subject) of one commit, or None."""
    rc, out = git("log", "-1", "--no-walk", "--format=%P%x1f%T%x1f%s", sha)
    p = out.strip("\n").split("\x1f") if rc == 0 else []
    if len(p) != 3 or not SHA.fullmatch(p[1]):
        return None
    parents = p[0].split()
    if not parents or not all(SHA.fullmatch(x) for x in parents):
        return None
    return parents, p[1], p[2]


def _clean_merge(git: Git, a: str, b: str) -> str | None:
    """The tree of the clean automatic merge of a and b, or None (a conflict or no clear answer)."""
    rc, out = git("merge-tree", "--write-tree", "--no-messages", a, b)
    tree = (out.splitlines() or [""])[0].strip()
    return tree if rc == 0 and SHA.fullmatch(tree) else None


def _auto_merge(git: Git, a: str, b: str) -> str | None:
    """The automatic merge's tree even with conflicts (conflict markers in it), or None."""
    rc, out = git("merge-tree", "--write-tree", "--no-messages", a, b)
    tree = (out.splitlines() or [""])[0].strip()
    return tree if rc in (0, 1) and SHA.fullmatch(tree) else None


def _names(git: Git, a: str, b: str) -> list[str] | None:
    rc, out = git("diff", "--no-renames", "--name-only", "-z", a, b)
    return [x for x in out.split("\0") if x] if rc == 0 else None


def keep_check(git: Git, reviewed: str, head: str, pats: tuple[str, ...], tips: set[str] | None) -> dict:
    """{"kind": "same"} | {"kind": "delta", "files": [...], "steps": [(from, commit), ...]} |
    {"kind": "full", "why": "..."}. steps name the own parts to review: `git diff from commit` for each."""
    if not (SHA.fullmatch(reviewed or "") and SHA.fullmatch(head or "")):
        return {"kind": "full", "why": "no full commit to compare"}
    if reviewed == head:
        return {"kind": "same"}
    if not tips:
        return {"kind": "full", "why": "develop's history could not be read"}
    rc, out = git("rev-list", "--first-parent", f"--max-count={CHAIN_MAX}", head)
    chain = out.split() if rc == 0 else []
    if reviewed not in chain:
        return {"kind": "full", "why": "the reviewed commit is not in the branch's history any more"}
    hits: set[str] = set()
    steps: list[tuple[str, str]] = []
    for c in chain[: chain.index(reviewed)]:
        info = _commit(git, c)
        if info is None:
            return {"kind": "full", "why": f"commit {c[:8]} could not be read"}
        parents, _, _ = info
        base = parents[0]
        if len(parents) == 2 and parents[1] in tips:
            base = _auto_merge(git, parents[0], parents[1])
            if base is None:
                return {"kind": "full", "why": f"the merge {c[:8]} could not be redone"}
        names = _names(git, base, c)
        if names is None:
            return {"kind": "full", "why": f"the change {c[:8]} could not be read"}
        mine = secreview.matched(names, pats)
        if mine:
            hits.update(mine)
            steps.append((base, c))
    if not hits:
        return {"kind": "same"}
    return {"kind": "delta", "files": sorted(hits), "steps": list(reversed(steps))}


def group_steps(git: Git, head: str, pats: tuple[str, ...], tips: set[str] | None) -> list | None:
    """[(member number, member head, [guarded files of its step])] bottom first; None: not a queue group."""
    if not tips or not SHA.fullmatch(head or "") or head in tips:
        return None
    out, cur = [], head
    for _ in range(GROUP_MAX):
        info = _commit(git, cur)
        if info is None:
            return None
        parents, tree, subject = info
        m = TAKE_IN.fullmatch(subject.strip())
        if not m or len(parents) != 2 or parents[1] in tips:
            return None
        if _clean_merge(git, parents[0], parents[1]) != tree:
            return None  # not the clean automatic merge: something was changed by hand
        names = _names(git, parents[0], cur)
        if names is None:
            return None
        out.append((int(m[1]), parents[1], secreview.matched(names, pats)))
        cur = parents[0]
        if cur in tips:
            return list(reversed(out))
    return None

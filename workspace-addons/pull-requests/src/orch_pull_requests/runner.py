"""The merge queue runner (`orch pull-requests queue run`). No AI call.

One runner per workspace (lock folder `runner.lock`). While pull requests wait, it takes up to MAX_GROUP of one
repository and base branch, in line order:

- one pull request: the core waiter merges it on green (orch.prwait.run_one, unchanged);
- several: one group commit (group.py) on a branch `orch-queue/<base>-<time>`, one pull request for it, the
  core waiter merges that on green with a merge commit. GitHub then marks every included pull request merged.
- a red group is closed and split in halves; each half runs again (a half of one runs alone). So a bad pull
  request costs about log2(n) extra runs and the good ones still merge.
- a pull request from a fork always runs alone: its code never lands on a branch of the repository unchecked.

Trouble that is neither green nor red (no room in the write limit, a failed fetch or push, the base branch
moving) sends the group back to the front with a pause; after MAX_TRIES such tries an entry leaves with the
reason. A runner that died leaves entries 'running': the next runner puts them back in line first.

Every GitHub write takes a slot of this computer's write limit (orch.ghlimit). The verdict of each pull request
goes on its ticket when it has one.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

from . import store
from .store import FINISHED, MERGED, OUT, RUNNING, Refused

MAX_GROUP = 5
MAX_TRIES = 3
PAUSE_SECS = 120  # before a group that hit trouble is tried again
BY = "agent:merge-queue"
NO_ROOM = "this computer's GitHub write limit had no room for the group"


class Runner:
    def __init__(
        self, root: Path, gh, make_git, waiter=None, take=None, log=print, clock=time.time, sleep=time.sleep
    ):
        from orch import ghlimit, prwait

        self.root, self.gh, self.make_git, self.log = root, gh, make_git, log
        self.clock, self.sleep = clock, sleep
        self.waiter = waiter or (lambda url: prwait.run_one(url, True))
        self.take = take or ghlimit.take

    # -- the loop ----------------------------------------------------------------------------------------
    def run(self) -> int:
        """Work until no pull request waits. Returns how many rounds ran."""
        self.recover()
        rounds = 0
        while True:
            batch = self.next_batch()
            if batch is None:
                return rounds
            if not batch:
                rest = store.waiting(self.root)
                later = [float(r.get("not_before") or 0) for r in rest]
                if rest and min(later) > self.clock():  # only paused entries left
                    self.sleep(min(min(later) - self.clock(), PAUSE_SECS) + 1)
                continue
            rounds += 1
            try:
                self.process(batch)
            except Exception as e:  # noqa: BLE001 - never leave entries 'running' behind a crash
                left = [b for b in batch if _state(self.root, b["url"]) == RUNNING]
                self.retry(left, f"the merge queue hit an error ({e.__class__.__name__}: {str(e)[:120]})")

    def recover(self) -> None:
        """Entries a dead runner left 'running' go back to the front; their open group pull request is closed."""
        stuck = [r for r in store.read(self.root) if r.get("state") == RUNNING]
        for g in dict.fromkeys(r["group"] for r in stuck if r.get("group")):
            if self.take("other", f"{g} close"):
                self.gh.close(g)
        if stuck:
            store.back_to_front(self.root, [r["url"] for r in stuck], "the last runner stopped; waits again")
            self.log("Back in line after a stopped runner: " + ", ".join(r["url"] for r in stuck))

    def next_batch(self) -> list[dict] | None:
        """Up to MAX_GROUP waiting pull requests of the first one's repository and base, marked running.
        None when nothing waits; [] when this round only cleared entries or everything is paused."""
        now = self.clock()
        rows = [r for r in store.waiting(self.root) if float(r.get("not_before") or 0) <= now]
        if not rows:
            return [] if store.waiting(self.root) else None
        repo, base, batch = rows[0]["repo"], None, []
        cards = merge_cards(self.root)
        for r in rows:
            if r["repo"] != repo or len(batch) >= MAX_GROUP:
                continue
            if r["url"] in cards:
                line = f"A person merges {r['url']} with the Merge card on {cards[r['url']]}; it left the merge queue."
                self.finish(r, OUT, line, "")
                continue
            v = self.gh.pr(r["url"])
            if v is None:
                self.finish(r, OUT, f"GitHub did not show {r['url']}; add it again when it is reachable.", "")
                continue
            if v.get("state") == "MERGED":
                self.finish(r, MERGED, f"{r['url']} is merged already.", "merged")
                continue
            if v.get("state") != "OPEN":
                self.finish(r, OUT, f"{r['url']} is closed; it left the merge queue.", "closed")
                continue
            if v.get("isDraft"):
                self.finish(r, OUT, f"{r['url']} is a draft: mark it ready, then add it again.", "")
                continue
            if self.gh.own_checks_failed(r["url"]):
                line = f"Checks of {r['url']} failed: fix them, push, then add it to the merge queue again."
                self.finish(r, OUT, line, "checks failed")
                continue
            b = v.get("baseRefName") or ""
            base = base or b
            if b != base:
                continue
            r.update(
                base=b, head=v["headRefOid"], fork=bool(v.get("isCrossRepository")),
                title=str(v.get("title") or "")[:200], closes=_closes(r["repo"], v),
            )  # fmt: skip
            batch.append(r)
        return store.claim(self.root, batch)

    def process(self, batch: list[dict]) -> None:
        if len(batch) == 1:
            self.single(batch[0])
            return
        red = self.group(batch)
        if len(red) > 1:
            half = (len(red) + 1) // 2
            self.log(f"The group was red: splitting it into {half} and {len(red) - half}.")
            for part in (red[:half], red[half:]):
                left = [e for e in part if _state(self.root, e["url"]) == RUNNING]
                if left:
                    self.process(left)
        elif red:
            self.single(red[0])

    # -- one pull request --------------------------------------------------------------------------------
    def single(self, e: dict, why: str = "") -> None:
        o = self.waiter(e["url"])
        line = o.line + (f" ({why})" if why else "")
        self.finish(e, MERGED if o.ok and o.status == "merged" else OUT, line, o.status)

    # -- a group -----------------------------------------------------------------------------------------
    def group(self, batch: list[dict]) -> list[dict]:
        """Check and merge batch as one group; every entry is finished or back in line, except those of a red
        group, which are returned (still running) so the caller checks them in smaller groups."""
        forks = [e for e in batch if e.get("fork")]
        batch = [e for e in batch if not e.get("fork")]
        for e in forks:  # a fork's code runs alone, as GitHub runs it for a fork pull request
            self.single(e, "a pull request from a fork is merged alone")
        if len(batch) < 2:
            for e in batch:
                self.single(e)
            return []
        repo, base = batch[0]["repo"], batch[0]["base"]
        nums = [e["number"] for e in batch]
        try:
            git = self.make_git(repo)
            heads = git.fetch(base, nums)
        except Refused as e:
            self.retry(batch, f"the group could not be built: {e}")
            return []
        moved = [e for e in batch if e.get("head") and heads.get(str(e["number"])) != e["head"]]
        if moved:  # pushed to since it was looked at: looked at again next round
            store.back_to_front(self.root, [e["url"] for e in moved], "it got a new commit; waits again")
            return self.group([e for e in batch if e not in moved])
        try:
            sha, included, conflicted = git.build(heads["base"], [(n, heads[str(n)]) for n in nums])
        except Refused as e:
            self.retry(batch, f"the group could not be built: {e}")
            return []
        inside = [e for e in batch if e["number"] in included]
        apart = [e for e in batch if e["number"] in conflicted]
        red = []
        if len(inside) < 2:
            for e in inside:
                self.single(e)
        else:
            red = self._check_group(repo, base, sha, inside)
        for (
            e
        ) in apart:  # conflicts with the group: alone, after it (the waiter takes the base in or says why)
            self.single(e, "it conflicted with other pull requests in the merge queue")
        return red

    def _check_group(self, repo: str, base: str, sha: str, inside: list[dict]) -> list[dict]:
        branch = f"orch-queue/{base}-{int(self.clock())}"
        if not self.take("other", f"{repo} push {branch}"):
            self.retry(inside, NO_ROOM, count=False)
            return []
        try:
            self.make_git(repo).push(sha, branch)
        except Refused as e:
            self.retry(inside, f"the group branch was not pushed: {e}")
            return []
        title, body = _group_text(inside)
        if not self.take("pr", f"{repo} group {branch}"):
            self._drop_branch(repo, branch)
            self.retry(inside, NO_ROOM, count=False)
            return []
        url = self.gh.create_pr(repo, base, branch, title, body)
        if url is None:
            self._drop_branch(repo, branch)
            self.retry(inside, "GitHub did not open the group pull request")
            return []
        self.log(f"Group {url}: " + ", ".join(f"#{e['number']}" for e in inside))
        for e in inside:
            store.set_state(self.root, e["url"], RUNNING, f"in the group {url}", group=url)
        o = self.waiter(url)
        if o.ok and o.status == "merged":
            self._drop_branch(repo, branch)
            for e in inside:
                if self._merged(e["url"]):
                    self.finish(
                        e, MERGED, f"Merged {e['url']} with the group {url} on green checks.", "merged"
                    )
                else:
                    store.back_to_front(
                        self.root, [e["url"]], "it got a new commit while the group was checked; waits again"
                    )
            return []
        if self.take("other", f"{url} close"):
            self.gh.close(url)
        if o.status == "checks failed":
            for e in inside:
                why = f"its group {url} was red; checked in a smaller group"
                store.set_state(self.root, e["url"], RUNNING, why, group=None)
            return inside
        self.retry(inside, f"the group {url} was not merged: {o.line}")
        return []

    def _merged(self, url: str) -> bool:
        for i in range(3):  # GitHub can take a moment to mark the included pull requests merged
            v = self.gh.pr(url)
            if v is not None and v.get("state") == "MERGED":
                return True
            if v is not None and v.get("state") == "OPEN" and i:
                return False
            self.sleep(5)
        return False

    def _drop_branch(self, repo: str, branch: str) -> None:
        if self.take("other", f"{repo} delete {branch}"):
            self.gh.delete_branch(repo, branch)

    def retry(self, entries: list[dict], why: str, count: bool = True) -> None:
        """Back to the front of the line after a pause; after MAX_TRIES counted tries, out with the reason."""
        rows = {r["url"]: r for r in store.read(self.root) if r.get("state") == RUNNING}
        back = []
        for e in entries:
            tries = int(rows.get(e["url"], {}).get("tries") or 0) + (1 if count else 0)
            if tries >= MAX_TRIES:
                self.finish(e, OUT, f"{e['url']} left the merge queue after {tries} tries: {why}.", "")
            else:
                store.set_state(self.root, e["url"], RUNNING, why, tries=tries)
                back.append(e["url"])
        if back:
            self.log(f"Back in line ({why}): " + ", ".join(back))
            store.back_to_front(self.root, back, f"waits again: {why}", not_before=self.clock() + PAUSE_SECS)

    # -- the ticket --------------------------------------------------------------------------------------
    def finish(self, e: dict, state: str, line: str, status: str) -> None:
        store.set_state(self.root, e["url"], state, line)
        self.log(line)
        tid = e.get("ticket")
        if not tid:
            return
        from orch import tickets
        from orch.errors import Refused as CoreRefused

        with contextlib.suppress(CoreRefused, OSError, KeyError, ValueError):
            tickets.note_history(self.root, tid, BY, line)
            if status:
                tickets.ref_set(self.root, tid, e["url"], status, BY)


def _state(root: Path, url: str) -> str | None:
    row = store.find(store.read(root), url)
    return row.get("state") if row else None


def merge_cards(root: Path) -> dict[str, str]:
    """{pull request url: ticket key} for every unanswered Merge card in the workspace: a person merges those."""
    from orch import review, tickets

    out = {}
    try:
        rows = tickets.list_all(root)
    except Exception:  # noqa: BLE001 - unreadable tickets: no card known (the core waiter still checks GitHub)
        return out
    for t in rows:
        for q in t.get("questions") or []:
            u = review.merge_url(q) if isinstance(q, dict) and q.get("answer") is None else None
            if u:
                out[u] = str(t.get("key") or t.get("id"))
    return out


def _closes(repo: str, v: dict) -> list[str]:
    """The issues GitHub itself says the pull request closes, as references for the group's body."""
    out = []
    for i in v.get("closingIssuesReferences") or []:
        if not isinstance(i, dict) or not isinstance(i.get("number"), int):
            continue
        r = i.get("repository") or {}
        full = f"{(r.get('owner') or {}).get('login', '')}/{r.get('name', '')}" if isinstance(r, dict) else ""
        out.append(f"#{i['number']}" if full in ("/", repo) else f"{full}#{i['number']}")
    return out


def _safe_title(title: str) -> str:
    """A title as inert code text: words like 'closes #5' in it must not close anything."""
    return "`" + " ".join(title.replace("`", "'").split())[:200] + "`" if title.strip() else ""


def _group_text(inside: list[dict]) -> tuple[str, str]:
    nums = ", ".join(f"#{e['number']}" for e in inside)
    lines = [
        "orch merge queue: these pull requests are merged together after one run of the checks.",
        "",
        *(f"- #{e['number']} {_safe_title(e.get('title') or '')}".rstrip() for e in inside),
    ]
    closes = [c for e in inside for c in e.get("closes") or []]
    if closes:
        lines += ["", *(f"Closes {c}" for c in dict.fromkeys(closes))]
    return f"Merge queue: {nums}", "\n".join(lines) + "\n"


def finished(row: dict | None) -> bool:
    return bool(row) and row.get("state") in FINISHED

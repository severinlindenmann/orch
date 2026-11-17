"""The merge queue runner (`orch pull-requests queue run`). No AI call.

One runner per workspace (lock folder `runner.lock`). It first checks which GitHub login gh uses: with the
setting `[pull_requests] login` it runs only as that login, and it only takes entries added by its own login.
While pull requests wait, it takes up to MAX_GROUP of one repository and base branch, in line order:

- one pull request: the core waiter merges it on green (orch.prwait.run_one);
- several: one group commit (group.py) on a branch `orch-queue/<base>-<time>`, one pull request for it, the
  core waiter merges that on green with a merge commit. GitHub then marks every included pull request merged.
- a red group is closed and split in halves; each half runs again (a half of one runs alone). So a bad pull
  request costs about log2(n) extra runs and the good ones still merge.
- a pull request from a fork always runs alone: its code never lands on a branch of the repository unchecked.

Every member is looked at again before its group is built, just before the group pull request is opened and
right before the merge (the waiter asks before_merge): one that was closed, made a draft, moved to another base
branch, got a new commit, got changes requested or a Merge card is taken out and never merged with the group.
Only the allowed base branches are merged into (settings.bases; never main).

Trouble that is neither green nor red (GitHub did not answer, no checks or no verdict in time, no room in the
write limit, a failed fetch or push) sends the entries back to the front with a pause; after MAX_TRIES such
tries an entry leaves with the reason. A runner that died leaves entries 'running': the next runner puts them
back in line first. Every group branch is written down before its push (store.groups) and stays there until
its pull request is closed and the branch deleted; each round and each start finish what is left.

Every GitHub write takes a slot of this computer's write limit (orch.ghlimit). The verdict of each pull request
goes on its ticket when it has one.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

from . import settings, store
from .store import FINISHED, MERGED, OUT, RUNNING, WAITING, Refused

MAX_GROUP = 5
MAX_TRIES = 3
PAUSE_SECS = 120  # before a group that hit trouble is tried again
MARK_SECS = 60  # how long GitHub may take to mark the members of a merged group merged
TIDY_TRIES = 5  # failed deletes of one group branch before it is left to a person
BY = "agent:merge-queue"
NO_ROOM = "this computer's GitHub write limit had no room for the group"
# what a look at one pull request found
OK, GONE_MERGED, LEAVE, AGAIN, UNKNOWN = "ok", "merged", "out", "again", "unknown"
BAD_REVIEW = {"CHANGES_REQUESTED": "changes were requested", "REVIEW_REQUIRED": "it still needs a review"}


class Runner:
    def __init__(
        self, root: Path, gh, make_git, waiter=None, take=None, log=print, clock=time.time, sleep=time.sleep
    ):
        from orch import ghlimit, prwait

        self.root, self.gh, self.make_git, self.log = root, gh, make_git, log
        self.clock, self.sleep = clock, sleep
        self.waiter = waiter or (
            lambda url, before_merge: prwait.run_one(url, True, before_merge=before_merge)
        )
        self.take = take or ghlimit.take
        self.me: str | None = None

    # -- the loop ----------------------------------------------------------------------------------------
    def run(self) -> int:
        """Work until no pull request of this login waits. Returns how many rounds ran."""
        if not self.sign_in():
            return 0
        self.recover()
        rounds = 0
        while True:
            if rounds and not self.sign_in():  # the login is checked again before every round
                return rounds
            batch = self.next_batch()
            if batch is None:
                return rounds
            if not batch:
                rest = self.mine()
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
            finally:
                self.tidy()

    def sign_in(self) -> bool:
        """Which login gh uses; False (and the runner does not run) when unknown or not the set one."""
        self.me = self.gh.login()
        want = settings.login(self.root)
        if self.me is None:
            self.log("GitHub did not say which login gh uses; the merge queue does not run now.")
            return False
        if want and not settings.same_login(self.me, want):
            self.log(
                f"gh uses the login {self.me}, but this merge queue merges only as {want}; it does not run."
            )
            self.me = None
            return False
        return True

    def mine(self) -> list[dict]:
        """Waiting entries this runner may merge: added by its own login."""
        return [r for r in store.waiting(self.root) if settings.same_login(r.get("login"), self.me)]

    def has_work(self) -> bool:
        return bool(self.me) and bool(self.mine())

    def recover(self) -> None:
        """Entries a dead runner left 'running' go back to the front; group branches left behind are cleaned."""
        stuck = [r for r in store.read(self.root) if r.get("state") == RUNNING]
        if stuck:
            store.back_to_front(self.root, [r["url"] for r in stuck], "the last runner stopped; waits again")
            self.log("Back in line after a stopped runner: " + ", ".join(r["url"] for r in stuck))
        self.tidy()

    def next_batch(self) -> list[dict] | None:
        """Up to MAX_GROUP waiting pull requests of the first one's repository and base, marked running.
        None when nothing waits; [] when this round only cleared entries or everything is paused."""
        now = self.clock()
        mine = self.mine()
        rows = [r for r in mine if float(r.get("not_before") or 0) <= now]
        if not rows:
            return [] if mine else None
        cards = merge_cards(self.root)
        if cards is None:  # tickets unreadable: nothing is merged until it is known who merges what
            self.log("The tickets could not be read; the merge queue waits and tries again.")
            self.sleep(PAUSE_SECS)
            return []
        bases = settings.bases(self.root)
        repo, base, batch, unseen, answered = rows[0]["repo"], None, [], [], False
        for r in rows:
            if r["repo"] != repo or len(batch) >= MAX_GROUP:
                continue
            v, kind, line, status = self.look(dict(r, head=None), cards, bases)
            answered = answered or kind != UNKNOWN
            if kind == UNKNOWN:
                unseen.append((r, line))
                continue
            if kind != OK:
                self.settle(r, kind, line, status)
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
        if unseen and not answered:  # GitHub showed none of them: does it answer at all?
            answered = self.gh.login() is not None
        for r, line in unseen:  # no answer from GitHub at all: an outage, which uses up no tries
            self.retry([r], line, count=answered)
        return store.claim(self.root, batch)

    # -- looking at a member again -----------------------------------------------------------------------
    def look(self, e: dict, cards: dict, bases: list[str], base: str | None = None):
        """(view, kind, line, status) for one entry as GitHub and the tickets show it now. With base, it must
        still go into that base; with e['head'], its head must not have moved."""
        u = e["url"]
        card = cards.get(pr_key(u))
        if card:
            return (
                None,
                LEAVE,
                f"A person merges {u} with the Merge card on {card}; it left the merge queue.",
                "",
            )
        v = self.gh.pr(u)
        if v is None:
            return None, UNKNOWN, f"GitHub did not show {u}", ""
        if v.get("state") == "MERGED":
            return v, GONE_MERGED, f"{u} is merged already.", "merged"
        if v.get("state") != "OPEN":
            return v, LEAVE, f"{u} is closed; it left the merge queue.", "closed"
        if v.get("isDraft"):
            return v, LEAVE, f"{u} is a draft: mark it ready, then add it again.", ""
        b = v.get("baseRefName") or ""
        if b not in bases:
            line = f"{u} goes into {b or '(unknown)'}; the merge queue merges only into {', '.join(bases) or '-'}."
            return v, LEAVE, line, ""
        if base and b != base:
            return v, AGAIN, f"{u} now goes into {b}", ""
        review = BAD_REVIEW.get(str(v.get("reviewDecision") or ""))
        if review:
            return v, LEAVE, f"{u}: {review}; it left the merge queue. Add it again when that is done.", ""
        if e.get("head") and v.get("headRefOid") != e["head"]:
            return v, AGAIN, f"{u} got a new commit", ""
        return v, OK, "", ""

    def settle(self, e: dict, kind: str, line: str, status: str) -> None:
        """Finish, put back or retry an entry a look did not find mergeable."""
        if kind == GONE_MERGED:
            self.finish(e, MERGED, line, status)
        elif kind == LEAVE:
            self.finish(e, OUT, line, status)
        elif kind == AGAIN:
            if _state(self.root, e["url"]) == RUNNING:
                store.back_to_front(self.root, [e["url"]], f"{line}; waits again")
        else:
            self.retry([e], line)

    def check_members(self, entries: list[dict], base: str) -> list[dict]:
        """Look at each entry again; those still mergeable come back, the others are settled."""
        if not entries:
            return []
        cards = merge_cards(self.root)
        if cards is None:
            self.retry(entries, "the tickets could not be read", count=False)
            return []
        bases, good = settings.bases(self.root), []
        for e in entries:
            _, kind, line, status = self.look(e, cards, bases, base)
            if kind == OK:
                good.append(e)
            else:
                self.settle(e, kind, line, status)
        return good

    def why_not(self, entries: list[dict], base: str) -> str | None:
        """For the waiter, right before the merge: the first reason one of the entries must not be merged now,
        or None. Changes nothing (the caller settles the entries after)."""
        cards = merge_cards(self.root)
        if cards is None:
            return "the tickets could not be read"
        bases = settings.bases(self.root)
        for e in entries:
            _, kind, line, _ = self.look(e, cards, bases, base)
            if kind != OK:
                return line or f"{e['url']} could not be looked at"
        return None

    def why_not_group(self, url: str, base: str, head: str) -> str | None:
        """The group pull request itself, right before its merge: still open, same head, same allowed base."""
        v = self.gh.pr(url)
        if v is None:
            return f"GitHub did not show the group {url}"
        if v.get("state") != "OPEN" or v.get("headRefOid") != head:
            return f"the group {url} was closed or got another commit"
        b = v.get("baseRefName") or ""
        if b != base or b not in settings.bases(self.root):
            return f"the group {url} was moved to {b or '(unknown)'}"
        return None

    # -- rounds ------------------------------------------------------------------------------------------
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
                if len(left) == 1:  # group() looks at members again; one alone is looked at here
                    left = self.check_members(left, left[0]["base"])
                if left:
                    self.process(left)
        elif red:
            self.single(red[0])

    # -- one pull request --------------------------------------------------------------------------------
    def single(self, e: dict, why: str = "") -> None:
        base = e.get("base") or ""
        o = self.waiter(e["url"], lambda head: self.why_not([dict(e, head=head)], base))
        line = o.line + (f" ({why})" if why else "")
        unknown = bool(getattr(getattr(o, "verdict", None), "unknown", False))
        if o.ok and o.status == "merged":
            self.finish(e, MERGED, line, o.status)
        elif o.status == "held":
            if self.check_members([dict(e, head=None)], base):  # fine again by now: next round
                self.retry([e], o.line, count=False)
        elif o.status == "changed":
            store.back_to_front(
                self.root, [e["url"]], "it got a new commit while its checks ran; waits again"
            )
        elif unknown or o.status in ("", "checks passed"):  # GitHub did not answer, or no room: not red
            self.retry([e], o.line)
        else:
            self.finish(e, OUT, line, o.status)

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
        batch = self.check_members(batch, base)
        if len(batch) < 2:
            for e in batch:
                self.single(e)
            return []
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
        used = {g["branch"] for g in store.groups(self.root) if g["repo"] == repo}
        n = 2
        while branch in used:  # a group built again within the same second gets a branch of its own
            branch, n = f"orch-queue/{base}-{int(self.clock())}-{n}", n + 1
        if not self.take("other", f"{repo} push {branch}"):
            self.retry(inside, NO_ROOM, count=False)
            return []
        store.change_group(self.root, repo, branch)  # before the push: a crash after it still leaves a note
        try:
            self.make_git(repo).push(sha, branch)
        except Refused as e:
            self.retry(inside, f"the group branch was not pushed: {e}")
            return []
        good = self.check_members(inside, base)  # just before the group pull request is opened
        if len(good) < len(inside):  # someone changed: this branch is not used (tidy deletes it)
            return self.group(good)
        title, body = _group_text(inside)
        if not self.take("pr", f"{repo} group {branch}"):
            self.retry(inside, NO_ROOM, count=False)
            return []
        url = self.gh.create_pr(repo, base, branch, title, body)
        if url is None:
            self.retry(inside, "GitHub did not open the group pull request")
            return []
        store.change_group(self.root, repo, branch, url=url)
        self.log(f"Group {url}: " + ", ".join(f"#{e['number']}" for e in inside))
        for e in inside:
            store.set_state(self.root, e["url"], RUNNING, f"in the group {url}", group=url)
        o = self.waiter(url, lambda head: self.why_not_group(url, base, head) or self.why_not(inside, base))
        self.tidy()  # merged: its branch goes; not merged: the group pull request is closed
        if o.ok and o.status == "merged":
            for e in inside:
                v = self._merged(e["url"])
                if v is not None and v.get("state") == "MERGED":
                    self.finish(
                        e, MERGED, f"Merged {e['url']} with the group {url} on green checks.", "merged"
                    )
                elif v is not None and v.get("headRefOid") != e["head"]:
                    store.back_to_front(
                        self.root, [e["url"]], "it got a new commit while the group was checked; waits again"
                    )
                else:
                    store.back_to_front(
                        self.root,
                        [e["url"]],
                        f"GitHub did not mark it merged after the group {url}; looked at again",
                    )
            return []
        if o.status == "held":
            good = self.check_members(inside, base)
            if good:
                why = f"a pull request of the group {url} changed before the merge; waits again"
                store.back_to_front(self.root, [e["url"] for e in good], why)
            return []
        unknown = bool(getattr(getattr(o, "verdict", None), "unknown", False))
        if o.status == "checks failed" and not unknown:
            for e in inside:
                why = f"its group {url} was red; checked in a smaller group"
                store.set_state(self.root, e["url"], RUNNING, why, group=None)
            return inside
        self.retry(inside, f"the group {url} was not merged: {o.line}")
        return []

    def _merged(self, url: str) -> dict | None:
        """The pull request once GitHub marked it merged, else as seen last (None: never seen)."""
        last = None
        for _ in range(int(MARK_SECS / 5)):  # GitHub can take a moment to mark the included pull requests
            v = self.gh.pr(url)
            last = v if v is not None else last
            if v is not None and v.get("state") == "MERGED":
                return v
            self.sleep(5)
        return last

    def tidy(self) -> None:
        """Close group pull requests and delete group branches that are no longer used. What gets no room in
        the write limit or no answer from GitHub stays written down for the next round or the next runner."""
        try:
            self._tidy()
        except Exception as e:  # noqa: BLE001 - the note stays; the next round or runner tries again
            self.log(f"Group branches were not cleaned up now ({e.__class__.__name__}: {str(e)[:120]}).")

    def _tidy(self) -> None:
        for g in store.groups(self.root):
            repo, branch, url = g["repo"], g["branch"], g.get("url")
            if url and not g.get("closed"):
                v = self.gh.pr(url)
                if v is None:
                    continue
                still_open = v.get("state") == "OPEN"
                if still_open and (not self.take("other", f"{url} close") or not self.gh.close(url)):
                    continue
                store.change_group(self.root, repo, branch, closed=True)
            if not self.take("other", f"{repo} delete {branch}"):
                continue
            if self.gh.delete_branch(repo, branch):
                store.change_group(self.root, repo, branch, drop=True)
                continue
            tries = int(g.get("tries") or 0) + 1
            if tries >= TIDY_TRIES:
                self.log(
                    f"The group branch {branch} of {repo} could not be deleted {tries} times; delete it by hand."
                )
                store.change_group(self.root, repo, branch, drop=True)
            else:
                store.change_group(self.root, repo, branch, tries=tries)

    def retry(self, entries: list[dict], why: str, count: bool = True) -> None:
        """Back to the front of the line after a pause; after MAX_TRIES counted tries, out with the reason.
        A waiting entry keeps its place and only gets the pause."""
        rows = {r["url"]: r for r in store.read(self.root) if r.get("state") in (RUNNING, WAITING)}
        back = []
        for e in entries:
            row = rows.get(e["url"])
            if row is None:
                continue
            tries = int(row.get("tries") or 0) + (1 if count else 0)
            if tries >= MAX_TRIES:
                self.finish(e, OUT, f"{e['url']} left the merge queue after {tries} tries: {why}.", "")
            elif row.get("state") == WAITING:
                store.set_state(
                    self.root, e["url"], WAITING, f"waits again: {why}", tries=tries,
                    not_before=self.clock() + PAUSE_SECS,
                )  # fmt: skip
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


def admit(root: Path, gh, url: str) -> dict:
    """What `queue add` checks before an entry goes in line: an open, ready pull request into an allowed base
    branch, without changes requested, added by the login the queue merges with. Returns {base, login}."""
    v = gh.pr(url)
    if v is None:
        raise Refused(f"GitHub did not show {url}; try again in a minute.")
    if v.get("state") == "MERGED":
        raise Refused(f"{url} is merged already.")
    if v.get("state") != "OPEN":
        raise Refused(f"{url} is closed; not queued.")
    if v.get("isDraft"):
        raise Refused(f"{url} is a draft: mark it ready, then add it again.")
    bases = settings.bases(root)
    b = v.get("baseRefName") or ""
    if b not in bases:
        raise Refused(
            f"{url} goes into {b or '(unknown)'}; the merge queue merges only into {', '.join(bases) or '-'}."
        )
    review = BAD_REVIEW.get(str(v.get("reviewDecision") or ""))
    if review:
        raise Refused(f"{url}: {review}; not queued.")
    me, want = gh.login(), settings.login(root)
    if me is None:
        raise Refused("GitHub did not say which login gh uses; try again in a minute.")
    if want and not settings.same_login(me, want):
        raise Refused(f"gh uses the login {me} here, but this merge queue merges only as {want}; not queued.")
    return {"base": b, "login": me}


def _state(root: Path, url: str) -> str | None:
    row = store.find(store.read(root), url)
    return row.get("state") if row else None


def pr_key(url: str) -> str | None:
    """One spelling per pull request: GitHub owner and repository names do not care about case."""
    m = store.PR_URL.fullmatch((url or "").strip())
    return f"{m[1].lower()}#{int(m[2])}" if m else None


def merge_cards(root: Path) -> dict[str, str] | None:
    """{pull request key: ticket key} for every unanswered Merge card in the workspace: a person merges those.
    None when the tickets cannot be read (the caller then merges nothing)."""
    from orch import review, tickets

    out = {}
    try:
        rows = tickets.list_all(root)
    except Exception:  # noqa: BLE001 - unreadable tickets: fail closed
        return None
    for t in rows:
        for q in t.get("questions") or []:
            u = review.merge_url(q) if isinstance(q, dict) and q.get("answer") is None else None
            k = pr_key(u) if u else None
            if k:
                out[k] = str(t.get("key") or t.get("id"))
    return out


def _closes(repo: str, v: dict) -> list[str]:
    """The issues GitHub itself says the pull request closes, as references for the group's body."""
    out = []
    for i in v.get("closingIssuesReferences") or []:
        if not isinstance(i, dict) or not isinstance(i.get("number"), int):
            continue
        r = i.get("repository") or {}
        full = f"{(r.get('owner') or {}).get('login', '')}/{r.get('name', '')}" if isinstance(r, dict) else ""
        out.append(f"#{i['number']}" if full.lower() in ("/", repo.lower()) else f"{full}#{i['number']}")
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

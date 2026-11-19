"""Merge a GitHub pull request when a person approves a merge card (orch ask --link --open PR --merge).

The merge runs with the person's OWN GitHub login: the one the GitHub command line (gh) is signed in with
on this computer. Token variables a helper's environment may carry (GH_TOKEN, GITHUB_TOKEN, ...) are
dropped, so a helper's account never does the merge. GitHub itself decides who may merge (branch rules);
a refusal comes back to the person in plain words. Only review.decide/change and `orch ref merge` call
merge(), after the person check. checks() only reads (orch needs uses it for a finished ticket whose pull
request is still open).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from orch import ghlimit
from orch.errors import Refused

PR_URL = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]{1,9}")
# gh reads these before its own sign-in; a helper's environment may set them for a helper account
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")


class MergeFailed(Refused):
    """GitHub (or the pull request itself) refused the merge: the review card sends it back to the helper."""


OPEN_IT = "Open the pull request and merge it there."
JQ_VIEW = '[.state, (.reviewDecision // ""), .headRefOid] | @tsv'
SHA = re.compile(r"[0-9a-f]{40}")
CHANGED = "The pull request changed after the card was made. Ask the helper for a new card."
REVIEW_BODY = "Merge clicked on the orch card."
NO_GH = "The merge needs the GitHub command line (gh) signed in with your own account. " + OPEN_IT


def is_pr_url(url) -> bool:
    return isinstance(url, str) and PR_URL.fullmatch(url) is not None


def own_env() -> dict:
    """This process's environment without any GitHub token variable: gh then uses its own sign-in."""
    return {k: v for k, v in os.environ.items() if k not in TOKEN_VARS}


def _gh(gh: str, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [gh, *args],
            env=own_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise Refused("GitHub did not answer in time. Try again in a minute, or " + OPEN_IT.lower()) from None
    except OSError:
        raise Refused(NO_GH) from None


def _first_line(text: str) -> str:
    line = next((x.strip() for x in (text or "").splitlines() if x.strip()), "no reason given")
    return line.removeprefix("X ").removeprefix("! ")[:200]


def _parts(url: str) -> tuple[str, str]:
    """(owner/repo, number) of a pull request address."""
    m = re.fullmatch(r"https://github\.com/([^/]+/[^/]+)/pull/([0-9]+)", url)
    if m is None:
        raise Refused("A merge card needs a GitHub pull request address.")
    return m[1], m[2]


def _view(gh: str, url: str, env_own: bool) -> tuple[str, str, str]:
    """(state, review decision, head commit) of the pull request."""
    args = ["pr", "view", url, "--json", "state,reviewDecision,headRefOid", "--jq", JQ_VIEW]
    v = _gh(gh, args, 15) if env_own else _gh_plain(gh, args, 15)
    if v.returncode != 0:
        raise Refused(f"GitHub did not show the pull request: {_first_line(v.stderr)}. {OPEN_IT}")
    state, review, head = ([*v.stdout.rstrip("\r\n").split("\t"), "", ""])[:3]
    if not SHA.fullmatch(head):
        raise Refused(f"GitHub did not show the pull request's newest commit. {OPEN_IT}")
    return state, review, head


def _gh_plain(gh: str, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Reading only, with whatever login this process has (a helper's is fine to read)."""
    try:
        return subprocess.run(
            [gh, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise Refused("GitHub did not answer in time. Try again in a minute.") from None
    except OSError:
        raise Refused("--merge needs the GitHub command line (gh) to read the pull request.") from None


JSON_CHECKS = "state,isDraft,headRefOid,statusCheckRollup"
PASSED = ("SUCCESS", "SKIPPED", "NEUTRAL")


def _newest(rollup: list) -> list:
    """One entry per check: GitHub lists every run of a workflow on the commit (a first run made while the
    pull request was a draft, the full run after), and only the newest run of a check counts."""
    last: dict = {}
    for n, c in enumerate(rollup):
        if not isinstance(c, dict):
            return rollup
        key = (c.get("workflowName"), c.get("name") or c.get("context") or n)
        when = str(c.get("startedAt") or "")
        if key not in last or when >= last[key][0]:
            last[key] = (when, c)
    return [c for _, c in last.values()]


def passed(rollup) -> bool:
    """True when every check of a pull request has finished, none failed and at least one succeeded."""
    if not isinstance(rollup, list) or not rollup:
        return False
    good = 0
    for c in _newest(rollup):
        if not isinstance(c, dict):
            return False
        if "state" in c and "status" not in c:  # a commit status (no run): SUCCESS or not
            word = c.get("state")
        elif c.get("status") != "COMPLETED":
            return False
        else:
            word = c.get("conclusion")
        if word not in PASSED:
            return False
        good += word == "SUCCESS"
    return good > 0


def checks(url: str) -> dict | None:
    """What GitHub says about a pull request now, read-only, with whatever login this process has:
    {"state": OPEN|MERGED|CLOSED, "head": <newest commit>, "green": <open, not a draft, checks passed>}.
    None when it cannot be read (no gh, not signed in, no network): the caller then shows nothing."""
    gh = shutil.which("gh")
    if gh is None or not is_pr_url(url):
        return None
    try:
        v = _gh_plain(gh, ["pr", "view", url, "--json", JSON_CHECKS], 15)
        data = json.loads(v.stdout) if v.returncode == 0 else None
    except (Refused, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("state"), str):
        return None
    head = data.get("headRefOid")
    if not isinstance(head, str) or not SHA.fullmatch(head):
        return None
    green = data["state"] == "OPEN" and data.get("isDraft") is False and passed(data.get("statusCheckRollup"))
    return {"state": data["state"], "head": head, "green": green}


MERGE_COMMIT = re.compile(r"Merge pull request #([0-9]{1,9}) from ")
MAX_ITEMS = 40


def checks_state(rollup) -> tuple[str, str]:
    """(tone, plain words) of a pull request's checks (ORCH-183): ("done", "All 18 checks passed"),
    ("working", "3 of 18 checks still running"), ("failed", "1 check failed: lint"). The newest run of each
    check counts, as in passed()."""
    if not isinstance(rollup, list) or not rollup:
        return "working", "No checks have run yet"
    runs = [c for c in _newest(rollup) if isinstance(c, dict)]
    failed, running = [], 0
    for c in runs:
        if "state" in c and "status" not in c:
            word = c.get("state")
            if word == "PENDING":
                running += 1
                continue
        elif c.get("status") != "COMPLETED":
            running += 1
            continue
        else:
            word = c.get("conclusion")
        if word not in PASSED:
            failed.append(str(c.get("name") or c.get("context") or "a check")[:60])
    if failed:
        n = len(failed)
        return "failed", f"{n} check{'' if n == 1 else 's'} failed: " + ", ".join(failed[:3]) + (
            " …" if n > 3 else ""
        )
    if running:
        return "working", f"{running} of {len(runs)} checks still running"
    return "done", f"All {len(runs)} checks passed" if len(runs) > 1 else "The check passed"


def summary(url: str, head: str) -> dict | None:
    """What a merge card shows (ORCH-183, owner 17 Nov: "the address is a link, not the content"), read
    once when the card is made, with whatever login this process has: {"title", "base", "checks" (plain
    words), "items": [{"pr": n, "title"}], "other": commits that are no pull request merge}. Items come from
    merge commit headlines, which a commit author writes: GitHub's own titles, never a ticket alone, and the
    count of other commits is always shown. None when GitHub cannot be read or the newest commit is no longer
    `head` (the commit the click merges): the card then shows only that commit."""
    gh = shutil.which("gh")
    if gh is None or not is_pr_url(url):
        return None
    try:
        v = _gh_plain(
            gh, ["pr", "view", url, "--json", "title,baseRefName,headRefOid,commits,statusCheckRollup"], 20
        )
        data = json.loads(v.stdout) if v.returncode == 0 else None
    except (Refused, ValueError):
        return None
    if not isinstance(data, dict) or data.get("headRefOid") != head:
        return None
    items, seen, other = [], set(), 0
    for c in data.get("commits") or []:
        if not isinstance(c, dict):
            continue
        m = MERGE_COMMIT.match(str(c.get("messageHeadline") or ""))
        if not m or m[1] in seen:
            other += 1
            continue
        seen.add(m[1])
        title = next((x.strip() for x in str(c.get("messageBody") or "").splitlines() if x.strip()), "")
        items.append({"pr": int(m[1]), "title": title[:200]})
    return {
        "title": str(data.get("title") or "")[:200],
        "base": str(data.get("baseRefName") or "")[:100],
        "checks": checks_state(data.get("statusCheckRollup")),
        "items": items[:MAX_ITEMS],
        "more": max(0, len(items) - MAX_ITEMS),
        "other": other,
    }


# A pull request that changes a CI workflow (ORCH-305, owner 17 Nov, option A): the helper account may push
# it, GitHub holds it until the owner approves (CODEOWNERS), and the owner's Merge card shows these checks of
# the lines it adds. A finding is said, never a reason to refuse: the owner decides. It reads lines, not YAML:
# the patterns match anywhere in a line (flow style `{uses: x}` and quoted keys too), and the card never says
# more than "nothing found in the added lines".
# ORCH-429 (owner 18 Nov): the card also shows the changed lines themselves, each risky added line marked
# (red on the card), tokens and downloads piped into a shell count too, and a change is labelled "Safe to
# merge" when a script check finds nothing: no finding in the added lines, and every changed workflow, read
# whole at the checked commit, declares its permissions, writes nothing, reads no secret and runs on no risky
# trigger. The label is words on the card only: the owner still clicks Merge.
WORKFLOW_DIR = ".github/workflows/"
ACTIONS_DIR = ".github/actions/"
SECRET = re.compile(  # GitHub's expressions ignore case: ${{ SECRETS.KEY }} is a secret too
    r"\bsecrets\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[|\))|\bsecrets['\"]?\s*:\s*['\"]?(inherit)\b", re.I
)
PERMISSION = re.compile(r"\bpermissions['\"]?\s*:|:\s*['\"]?write\b|\bwrite-all\b")
WRITES = re.compile(r":\s*['\"]?write\b|\bwrite-all\b")
TOP_PERMISSIONS = re.compile(r"^['\"]?permissions['\"]?\s*:", re.M)  # at the top: for every job
USES = re.compile(r"\buses['\"]?\s*:\s*['\"]?([^\s'\",}\]#]+)")
TOKEN = re.compile(r"\b(github\s*(?:\.\s*token\b|\[\s*['\"]token))|\b(\w*token\w*)\b", re.I)
_FETCH = r"\b(?:curl|wget)\b"
_RUNNER = r"(?:(?:sudo|env|command|exec|nohup|xargs|time)\b(?:\s+-\S+)*\s+)*"
_SHELL = rf"{_RUNNER}['\"]?(?:\S*/)?(?:(?:ba|z|da|k|fi)?sh|python\d?(?:\.\d+)?|perl|ruby|node|pwsh|iex)\b"
PIPE_SHELL = re.compile(  # a pipe anywhere after the download: | tee x | bash, | env bash, | "bash"
    rf"{_FETCH}.*\|\s*{_SHELL}|\b(?:ba|z)?sh\s+<\(\s*{_FETCH}|\b(?:ba|z)?sh\s+-c\s+['\"]?\$\(\s*{_FETCH}",
    re.I,
)
# What could hide a word from these line checks, so a file with it is never read-only: YAML escapes, tags
# (also `${{ !x }}`, a word too many), anchors and aliases.
ESCAPES = re.compile(r"\\[uUx0-9]|!!|(?:^|[:\[{,-])\s*!\S|(?:^|[\s:\[{,-])[&*][A-Za-z_]", re.M)
TOP_LINE = re.compile(
    r"(?:#|---|\.\.\.|['\"]?[A-Za-z_][\w-]*['\"]?\s*:)"
)  # a line at the top: key or comment
SAFE_NAME = re.compile(r"[A-Za-z0-9._/-]+")  # a workflow name read whole (never a query in the address)
COMPARE_MAX = 300  # GitHub's compare lists at most this many files: more could hide a workflow
OWN_ACTIONS = ("./", "actions/", "github/")
RISKY_TRIGGERS = ("pull_request_target", "workflow_run")
MAX_FINDINGS = 6
MAX_LINES = 30  # what a card's diff box holds (review.DOC_EXTRA "diff")
MAX_WHOLE = 10  # changed workflows read whole at the checked commit for the "Safe to merge" label
SAFE_WORDS = (
    "Safe to merge: every changed workflow says at its top that its jobs only read, and no added line "
    "reads a secret or token, gives more rights, uses an outside action, runs on a risky trigger or runs a "
    "download in a shell."
)


def is_workflow(path) -> bool:
    return isinstance(path, str) and path.startswith(WORKFLOW_DIR) and path.endswith((".yml", ".yaml"))


def is_action(path) -> bool:
    """A local action the workflows can run (`uses: ./...`): its change counts like a workflow's."""
    return isinstance(path, str) and (
        path.startswith(ACTIONS_DIR) or path.rsplit("/", 1)[-1] in ("action.yml", "action.yaml")
    )


def _is_ci(path) -> bool:
    return is_workflow(path) or is_action(path)


def line_risks(text: str) -> list[tuple[str, str, bool]]:
    """What one added workflow line does that the owner should see: [(finding words, short mark, blocks the
    "Safe to merge" label)]. Comments count too: a word too many is cheaper than one missed."""
    out: list[tuple[str, str, bool]] = []
    for m in SECRET.finditer(text):
        if (m[1] or "").upper() != "GITHUB_TOKEN":  # named below as a token
            out.append(("passes all secrets on" if m[2] else f"reads a secret ({m[1] or 'all secrets'})",
                        "secret", True))  # fmt: skip
    for m in TOKEN.finditer(text):  # GitHub's own token too: it can still send out what the job reads
        name = "github.token" if m[1] else m[2]
        out.append((f"uses a token ({name[:60]})", "token", True))
    if PERMISSION.search(text):
        # a line that only narrows rights (contents: read) leaves the label to the whole-file check
        out.append(
            ("changes what a job may do on GitHub (permissions)", "permissions", bool(WRITES.search(text)))
        )
    for u in USES.finditer(text):
        if not u[1].startswith(OWN_ACTIONS):
            out.append((f"uses an action from outside GitHub: {u[1][:80]}", "outside action", True))
    for trigger in RISKY_TRIGGERS:
        if re.search(rf"\b{trigger}\b", text):
            out.append((f"runs on {trigger}, which has more rights than a pull request run", "risky trigger",
                        True))  # fmt: skip
    if PIPE_SHELL.search(text):
        out.append(("runs a download straight in a shell", "download run in a shell", True))
    return out


def whole_is_read_only(text) -> bool:
    """A whole workflow file (at the checked commit) whose jobs can only read: it says its permissions at the
    top, none of them writes, it reads no secret but GitHub's own token, runs on no risky trigger, downloads
    nothing (curl, wget), and has no escape, tag, anchor or open quote that could hide a word.
    Lines, not YAML, like the rest of the check: when in doubt it is not read-only."""
    if not isinstance(text, str) or not TOP_PERMISSIONS.search(text) or ESCAPES.search(text):
        return False
    if WRITES.search(text) or re.search(_FETCH, text, re.I):  # any download at all: the owner looks
        return False
    for line in text.splitlines():
        if line[:1].strip() and not TOP_LINE.match(line):
            return False  # text at the top that is no key: a quoted value going on over lines
        if line.replace('\\"', "").count('"') % 2 or (line[:1].strip() and line.count("'") % 2):
            return False  # an open quote could carry a fake "permissions:" line
    if any((m[1] or "").upper() != "GITHUB_TOKEN" for m in SECRET.finditer(text)):
        return False
    return not any(re.search(rf"\b{t}\b", text) for t in RISKY_TRIGGERS)


def _pick_lines(lines: list[dict]) -> list[dict]:
    """At most MAX_LINES changed lines in their order: every marked line is kept first, then the others."""
    if len(lines) <= MAX_LINES:
        return lines
    keep = {i for i, x in enumerate(lines) if x.get("risk")}
    keep = set(sorted(keep)[:MAX_LINES])
    for i in range(len(lines)):
        if len(keep) >= MAX_LINES:
            break
        keep.add(i)
    return [x for i, x in enumerate(lines) if i in keep]


def check_workflows(files: list, whole: dict | None = None) -> dict | None:
    """The check of a pull request's changed files as GitHub lists them ({filename, status, additions,
    deletions, patch}): {"files": [{"name", "add", "del"}], "findings": [plain words], "more", "lines": [{op,
    text, file, risk?}], "lines_more", "safe"} for the CI workflow files among them, None when it changes
    none. Only added lines count: a new secret or token, a permissions change, an action from outside
    GitHub's own, a trigger that runs with more rights, a download run in a shell, a file without a patch.
    `whole` maps a workflow's name to its text at the checked commit (None: not read); without it nothing is
    "safe"."""
    shown, found, lines = [], [], []
    blocked = False
    whole = whole if isinstance(whole, dict) else {}

    def say(text: str) -> None:
        if text not in found:
            found.append(text)

    for f in files if isinstance(files, list) else []:
        if not isinstance(f, dict) or not (_is_ci(f.get("filename")) or _is_ci(f.get("previous_filename"))):
            continue
        name = str(f.get("filename"))
        if not is_workflow(name) and not is_workflow(f.get("previous_filename")):
            say(f"changes an action the workflows run: {name[:80]}")
            blocked = True
        shown.append({"name": name, "add": int(f.get("additions") or 0), "del": int(f.get("deletions") or 0)})
        if f.get("status") == "removed" or not whole_is_read_only(whole.get(name)):
            blocked = True  # a removed workflow may have been a check: the owner looks
        patch = f.get("patch")
        if not isinstance(patch, str):
            if f.get("status") != "removed":
                say(f"{name.removeprefix(WORKFLOW_DIR)} is too big to check here: open it")
                blocked = True
            continue
        for line in patch.splitlines():
            if line.startswith(("+++", "---")) or not line.startswith(("+", "-")):
                continue
            text = line[1:]
            shown_text = text.rstrip()
            if len(shown_text) > 200:  # both ends: what makes a long line risky is often at its end
                shown_text = shown_text[:120] + " … " + shown_text[-77:]
            row: dict = {"op": line[0], "text": shown_text, "file": name[:120]}
            if line[0] == "+":
                risks = line_risks(text)
                for words, _mark, blocks in risks:
                    say(words)
                    blocked = blocked or blocks
                marks = list(dict.fromkeys(mark for _w, mark, _b in risks))
                if marks:
                    row["risk"] = ", ".join(marks)[:60]
            if row["text"].strip():
                lines.append(row)
    if not shown:
        return None
    picked = _pick_lines(lines)
    return {
        "files": shown,
        "findings": found[:MAX_FINDINGS],
        "more": max(0, len(found) - MAX_FINDINGS),
        "lines": picked,
        "lines_more": len(lines) - len(picked),
        "safe": not blocked,
    }


def _whole_texts(read, gh: str, repo: str, head: str, files: list) -> dict:
    """{workflow name: its text at the commit `head`} for the changed workflows (at most MAX_WHOLE); a file
    GitHub does not give is left out, so the change is not labelled safe."""
    out: dict = {}
    names = [
        f.get("filename")
        for f in files
        if isinstance(f, dict) and is_workflow(f.get("filename")) and f.get("status") != "removed"
    ]
    if len(names) > MAX_WHOLE or len(files) >= COMPARE_MAX:
        return out
    for name in names:
        if not SAFE_NAME.fullmatch(str(name)):
            continue  # not read, so not safe
        path = f"repos/{repo}/contents/{name}?ref={head}"
        r = read(gh, ["api", path, "-H", "Accept: application/vnd.github.raw"], 20)
        if r.returncode == 0:
            out[name] = r.stdout
    return out


def workflow_check(url: str, head: str, own: bool = False) -> dict | None:
    """check_workflows() for exactly the commit `head` of the pull request at `url` (GitHub's compare of its
    base branch with that commit, and each changed workflow read whole at that commit), read-only with
    whatever login this process has (own: the person's own gh login, with no helper token, as on a Merge
    click). None when it changes no CI workflow or GitHub cannot be read."""
    gh = shutil.which("gh")
    if gh is None or not is_pr_url(url) or not SHA.fullmatch(str(head or "")):
        return None
    repo, _ = _parts(url)
    try:
        read = _gh if own else _gh_plain
        v = read(gh, ["pr", "view", url, "--json", "baseRefName"], 15)
        base = (json.loads(v.stdout) if v.returncode == 0 else {}).get("baseRefName")
        if not isinstance(base, str) or not base:
            return None
        c = read(gh, ["api", f"repos/{repo}/compare/{base}...{head}", "--jq", ".files"], 30)
        files = json.loads(c.stdout) if c.returncode == 0 else None
        if not isinstance(files, list) or not any(
            isinstance(f, dict) and (_is_ci(f.get("filename")) or _is_ci(f.get("previous_filename")))
            for f in files
        ):
            return None
        whole = _whole_texts(read, gh, repo, head, files)
    except (Refused, ValueError, AttributeError):
        return None
    return check_workflows(files, whole)


def workflow_words(wf: dict) -> str:
    """The one line a card shows for check_workflows()'s answer."""
    found = list(wf.get("findings") or [])
    if wf.get("more"):
        found.append(f"and {wf['more']} more")
    if wf.get("safe"):
        return SAFE_WORDS
    if not found:
        return (
            "Workflow check: no new secrets, tokens, permissions, outside actions, risky triggers or "
            "downloads run in a shell in added lines."
        )
    return "Workflow check, look at this: " + "; ".join(found) + "."


RELEASE_PREFIX = "release/"
RELEASE_FROM = "develop"  # a release only carries what is on this branch already (reviewed there)


def release_problem(url: str, head: str) -> str | None:
    """Why a pull request is not a release that may merge without a click (None = it is one): it must
    come from a release/... branch into the repository's default branch, and change nothing that is not on
    develop already (GitHub's compare develop...<commit> lists no file). Read-only, with any login."""
    repo, _ = _parts(url)
    gh = shutil.which("gh")
    if gh is None or not SHA.fullmatch(str(head or "")):
        return "GitHub could not be read"
    try:
        v = _gh_plain(gh, ["pr", "view", url, "--json", "baseRefName,headRefName,isCrossRepository"], 15)
        pr = json.loads(v.stdout) if v.returncode == 0 else None
        d = _gh_plain(gh, ["api", f"repos/{repo}", "--jq", ".default_branch"], 15)
        # the branch's own commit (a tag of that name cannot stand in), then compare commit to commit
        b = _gh_plain(gh, ["api", f"repos/{repo}/branches/{RELEASE_FROM}", "--jq", ".commit.sha"], 15)
        base = b.stdout.strip() if b.returncode == 0 else ""
        if not SHA.fullmatch(base):
            return "GitHub could not be read"
        c = _gh_plain(gh, ["api", f"repos/{repo}/compare/{base}...{head}", "--jq", ".files | length"], 20)
    except (Refused, ValueError):
        return "GitHub could not be read"
    if not isinstance(pr, dict) or v.returncode != 0 or d.returncode != 0:
        return "GitHub could not be read"
    if pr.get("isCrossRepository") is not False:
        return "it comes from another repository"
    if not str(pr.get("headRefName") or "").startswith(RELEASE_PREFIX):
        return f"it does not come from a {RELEASE_PREFIX}... branch"
    if pr.get("baseRefName") != d.stdout.strip():
        return "it does not go into the default branch"
    if c.returncode != 0 or c.stdout.strip() != "0":
        return f"it changes files that are not on {RELEASE_FROM}"
    return None


def head_of(url: str) -> str:
    """The newest commit of an open pull request, read when the card is made: the click merges exactly it."""
    _parts(url)
    gh = shutil.which("gh")
    if gh is None:
        raise Refused("--merge needs the GitHub command line (gh) to read the pull request.")
    state, _, head = _view(gh, url, env_own=False)
    if state != "OPEN":
        raise Refused("That pull request is not open on GitHub, so there is nothing to merge.")
    return head


def _unfinished_checks(gh: str, url: str) -> str | None:
    """Plain words when the pull request's checks have not all passed yet ("3 of 18 checks still running",
    "1 check failed: lint"), read now at GitHub; None when they passed, there are none (a repository without
    checks), or GitHub could not be read (GitHub's own rules then decide)."""
    try:
        v = _gh(gh, ["pr", "view", url, "--json", "statusCheckRollup"], 15)
        rollup = (json.loads(v.stdout) if v.returncode == 0 else {}).get("statusCheckRollup")
    except (ValueError, AttributeError, Refused):
        return None
    if not isinstance(rollup, list) or not rollup:
        return None
    tone, words = checks_state(rollup)
    return None if tone == "done" else words


def merge(url: str, head: str, add_review: bool = True) -> dict:
    """Merge the pull request at `url` as the person signed in to gh, only while its newest commit is still
    `head` (what the card showed). Returns {"login", "already"}: already is True when it was merged before (a
    second click, or a retry after a crash), which is not an error. add_review False (`orch ref merge`): the
    person's review is never added; where the branch rules want one, GitHub refuses and says so."""
    repo, num = _parts(url)
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise Refused("This merge card has no commit to merge. Ask the helper for a new card.")
    gh = shutil.which("gh")
    if gh is None:
        raise Refused(NO_GH)
    who = _gh(gh, ["api", "user", "--jq", ".login"], 15)
    login = who.stdout.strip()
    if who.returncode != 0 or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
        raise Refused(NO_GH)
    state, review, now = _view(gh, url, env_own=True)
    if state == "MERGED":
        return {"login": login, "already": True}
    if state != "OPEN":
        raise Refused("The pull request is closed on GitHub, so it cannot be merged. Open it to see why.")
    if now != head:
        raise MergeFailed(CHANGED)
    unfinished = _unfinished_checks(gh, url)
    if unfinished:  # say it plainly instead of GitHub's "base branch policy prohibits the merge"
        raise Refused(
            f"Its checks have not all passed yet ({unfinished}), so nothing was merged. "
            "The card stays: click Merge again when they are green."
        )
    # The branch rules want a review: the click is the person's, on THIS commit. A rule set (not the classic
    # branch protection) asks for the code owner's review without GitHub saying REVIEW_REQUIRED: the decision
    # comes back empty, so a CI workflow change (ORCH-305: always the code owner's) is approved as well
    # (ORCH-314: the owner's click on #1343 failed with "the base branch policy prohibits the merge").
    if add_review and (
        review == "REVIEW_REQUIRED" or (review == "" and workflow_check(url, head, own=True) is not None)
    ):
        _gh(  # the person's own pull request: GitHub says no, and the merge below tells what is missing
            gh,
            ["api", "-X", "POST", f"repos/{repo}/pulls/{num}/reviews", "-f", f"commit_id={head}",
             "-f", "event=APPROVE", "-f", f"body={REVIEW_BODY}"],
            15,
        )  # fmt: skip
    done = _gh(gh, ["pr", "merge", url, "--merge", "--match-head-commit", head], 25)
    if done.returncode != 0:
        raise MergeFailed(f"GitHub did not merge it: {_first_line(done.stderr or done.stdout)}. {OPEN_IT}")
    ghlimit.count("merge", url)  # the person's own click never waits, but it uses up the hour too
    return {"login": login, "already": False}

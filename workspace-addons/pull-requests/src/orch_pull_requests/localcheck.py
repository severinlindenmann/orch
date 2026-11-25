"""The local check: the before-merge checks of a queue group, run on this computer (ORCH-1124).

The setting `[pull_requests] group_check` (settings.group_check) says how a queue group is checked:

- `github` (default): GitHub's checks of the group pull request, as before.
- `shadow`: as `github`, and the local check runs next to it on the same group commit. Both verdicts are written
  to `local-checks.jsonl` so `orch pull-requests queue local-checks` shows whether they agree. GitHub's verdict decides.
- `local`: the local check runs on the group commit before the group pull request is opened. Green: the queue
  posts the required checks (required_checks.py, and its mark `orch/merge-queue`) as commit statuses and opens
  the group pull request with a line that tells ci.yml and rules.yml to skip it; the core waiter merges it on
  those statuses. Red: no group pull request; the group is split as a red one. The check crashed, did not finish
  in time or the group changes the check's own scripts: that group falls back to GitHub's checks (the old way).
  A status GitHub did not take: no group pull request; the group is built and checked again after a pause.

The check runs in a clean copy of the group commit (a worktree of the queue's own copy of the repository) with a
throwaway home, so it never touches the orch this computer uses. First the repository's own banned-words check
(scripts/check_banned_words.py, the check rules.yml runs; a repository without it falls back to GitHub), then the
check command, each in a process group of its own that is stopped as a whole on a timeout. The copy and the home sit
under <real home>/.orch-test and `ORCH_TEST_GUARD_ONLY` names the home: the test suites' guard then watches the
throwaway home instead of the real ~/.orch-tool, which this computer's own orch (this queue too) writes during
every run and so failed every green group (ORCH-1180, workspace/tests/conftest.py). Its command is the setting `check_command`
(a list; `{base}` is replaced with the base commit; the group's labels are in `ORCH_CHECK_LABELS`, ORCH-1363);
exit 0 = green, exit 1 = red, anything else = broken. It may write the names of the checks that failed, one per
line, to the file named by `ORCH_CHECK_FAILED`; they feed the split of a red group (blame.py). One local check runs at a time per runner.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import store

GREEN, RED, BROKEN = "green", "red", "broken"
CHECK_SECS = 15 * 60  # longer than this counts as broken: the group goes to GitHub
LOCAL_LINE = "orch-group-check: local"  # in the group pull request's body: ci.yml and rules.yml skip it
WORDS_SCRIPT = "scripts/check_banned_words.py"  # run on its own before the check command: banned-words is its result  # the develop rule's required checks the local check stands for
_ONE = threading.Lock()  # one at a time (a group on top of a running one waits for its turn)


@dataclass
class Result:
    verdict: str  # GREEN, RED or BROKEN
    secs: float
    line: str
    failed: list[str] = field(default_factory=list)
    out: str = ""  # the end of a red or broken check's output (save_output keeps it for the person who looks)


def run(
    git, sha: str, base_sha: str, command: list[str], timeout: float = CHECK_SECS, labels: str = ""
) -> Result:
    """Run the check on sha in a clean copy. Never raises: anything that goes wrong is BROKEN. labels: what the
    banned-words check is given as the group's labels (the owner-approved label of a member, ORCH-1363)."""
    with _ONE:
        start = time.monotonic()
        try:
            return _run(git, sha, base_sha, command, timeout, start, labels)
        except Exception as e:  # noqa: BLE001 - a broken check sends the group to GitHub, never merges it
            return Result(
                BROKEN, time.monotonic() - start, f"the check broke ({e.__class__.__name__}: {str(e)[:160]})"
            )


def _check_dir() -> Path:
    """A new folder for one check under <real home>/.orch-test, the only place the suites' guard accepts as
    ORCH_TEST_GUARD_ONLY; the system temp folder when that cannot be made (the guard then watches the real home)."""
    try:
        from orch import addons

        top = addons.real_home() / ".orch-test"
        top.mkdir(exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="orch-check-", dir=top))
    except Exception:  # noqa: BLE001 - no real home to use: the old place still runs the check
        return Path(tempfile.mkdtemp(prefix="orch-check-"))


def _run(
    git, sha: str, base_sha: str, command: list[str], timeout: float, start: float, labels: str = ""
) -> Result:
    if not command:
        return Result(BROKEN, 0.0, "no check command is set")
    tmp = _check_dir()
    copy, home = tmp / "copy", tmp / "home"
    home.mkdir()
    failed_file = tmp / "failed.txt"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "ORCH_HOME": str(home / "orch"),
        "ORCH_HOME_STRICT": "1",
        "ORCH_TEST_GUARD_ONLY": str(home),  # honoured only under <real home>/.orch-test (see _check_dir)
        "LANG": "C.UTF-8",
        "ORCH_CHECK_BASE": base_sha,
        "ORCH_CHECK_FAILED": str(failed_file),
        "ORCH_CHECK_LABELS": labels,  # the check command's own banned-words step reads it (ci_light --group)
    }
    for k in ("UV_CACHE_DIR", "PLAYWRIGHT_BROWSERS_PATH", "TMPDIR"):  # shared caches keep it fast
        if os.environ.get(k):
            env[k] = os.environ[k]
    try:
        try:
            git.worktree_add(copy, sha)
            # a group that changes the check itself is never checked by its own changed check: GitHub checks it
            # banned-words is posted under its own name, so it runs on its own: the very check rules.yml runs
            words = copy / WORDS_SCRIPT
            if not words.is_file():
                return Result(BROKEN, time.monotonic() - start, f"the copy has no {WORDS_SCRIPT}")
            # a group that changes the check itself is never checked by its own changed check: GitHub checks it
            # (os.path.isfile: an argument too long for a file name, `python -c <code>`, is no file, never an error)
            own = [WORDS_SCRIPT] + [
                a
                for a in command
                if not a.startswith("-") and not os.path.isabs(a) and os.path.isfile(copy / a)
            ]
            if base_sha != sha and git.changes(base_sha, sha, own):
                return Result(BROKEN, time.monotonic() - start, "the group changes the check itself")
            code, out, tail = _call(
                ["python3", WORDS_SCRIPT, "--base", base_sha, "--labels", labels], copy, env, timeout
            )
            if code is None:
                return Result(BROKEN, time.monotonic() - start, f"the banned-words check {out}", out=tail)
            if code != 0:
                secs = time.monotonic() - start
                return Result(
                    RED,
                    secs,
                    f"the local check failed in {int(secs)}s: banned words ({out})",
                    ["banned-words"],
                    out=tail,
                )
            left = max(1.0, timeout - (time.monotonic() - start))
            code, out, tail = _call([a.replace("{base}", base_sha) for a in command], copy, env, left)
            secs = time.monotonic() - start
            if code is None:
                return Result(BROKEN, secs, f"the check {out}", out=tail)
            failed = _failed(failed_file)
            if code == 0:
                return Result(GREEN, secs, f"the local check passed in {int(secs)}s")
            if code == 1:
                what = ", ".join(failed[:4]) or out or "see the runner's log"
                return Result(RED, secs, f"the local check failed in {int(secs)}s: {what}", failed, out=tail)
            return Result(BROKEN, secs, f"the check ended with exit code {code}: {out}", out=tail)
        finally:
            git.worktree_remove(copy)  # also after a worktree add that broke halfway
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _call(args: list[str], cwd: Path, env: dict, timeout: float) -> tuple[int | None, str, str]:
    """(exit code, last output line, end of the output); (None, why, end of the output) when it did not start or
    did not end in time. It runs in a
    process group of its own, and on a timeout the whole group is stopped (pytest workers, browsers). Its output
    goes to files, not pipes, so a process that left the group and still holds them never keeps the queue
    waiting."""
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
        try:
            proc = subprocess.Popen(
                args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                start_new_session=True,
            )  # fmt: skip
        except OSError as e:
            return None, f"did not start ({e.strerror or e})", ""
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_group(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
            out.seek(0)
            return None, f"did not finish in {int(timeout)}s", _tail(out.read())
        out.seek(0)
        tail = _tail(out.read())
        return code, _last_line(tail), tail


OUTPUT_KEEP = 20  # saved outputs of red or broken checks, the newest kept
OUTPUT_CHARS = 200_000  # the end of a check's output that is kept: a smoke's log ends well inside it


def _tail(text: str) -> str:
    return text[-OUTPUT_CHARS:]


def save_output(root: Path, sha: str, text: str) -> Path | None:
    """Keep the end of a red or broken check's output in local-checks/<sha>.log: the runner's log has only its
    last line, and a timeout in a smoke (groups 2579 and 2582 of 22 Nov) cannot be told apart from a real red
    without it. Lines that look like a secret are hidden first (orch.secretscan with the workspace's stored keys,
    as checks.log_end does for GitHub's logs; R5.2). Only the newest OUTPUT_KEEP files stay. None when it could not
    be written (it is extra)."""
    from .checks import _hidden

    rows = text.splitlines()
    hide = _hidden(rows, root)
    if hide is None:
        kept = "(the output could not be checked for secrets, so it is not kept)\n"
    else:
        kept = "\n".join(
            "(line hidden: it looks like a secret)" if i in hide else r for i, r in enumerate(rows, 1)
        )
    folder = store.folder(root) / "local-checks"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{sha[:12]}.log"
        path.write_text(kept, encoding="utf-8", errors="replace")
        old = sorted(folder.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)[OUTPUT_KEEP:]
        for f in old:
            f.unlink(missing_ok=True)
        return path
    except OSError:
        return None


def _stop_group(proc: subprocess.Popen) -> None:
    killpg = getattr(os, "killpg", None)
    if killpg is not None:
        try:
            killpg(proc.pid, signal.SIGKILL)
            return
        except OSError:
            pass
    proc.kill()


def _failed(path: Path) -> list[str]:
    try:
        return [x.strip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip()][:50]
    except OSError:
        return []


def _last_line(*texts: str) -> str:
    for t in texts:
        lines = [x.strip() for x in (t or "").splitlines() if x.strip()]
        if lines:
            return lines[-1][:160]
    return ""


# -- the record of each run (`orch pull-requests queue local-checks`) ----------------------------------------
def _log_file(root: Path) -> Path:
    return store.folder(root) / "local-checks.jsonl"


def record(root: Path, **row) -> None:
    row.setdefault("at", time.time())
    f = _log_file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def rows(root: Path) -> list[dict]:
    try:
        text = _log_file(root).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            v = json.loads(line)
        except ValueError:
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


def _middle(xs: list[float]) -> float | None:
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def summary(root: Path, last: int = 20) -> dict:
    """Side by side: groups where both verdicts are known and whether they agree. Local: the last `last` groups
    the local check decided, minutes from build to merged at the middle."""
    got = rows(root)
    shadow = [
        r
        for r in got
        if r.get("mode") == "shadow" and r.get("github") in (GREEN, RED) and r.get("local") in (GREEN, RED)
    ]
    differ = [r for r in shadow if r["github"] != r["local"]]
    local = [r for r in got if r.get("mode") == "local" and r.get("local") in (GREEN, RED)][-last:]
    merged = [
        (r["merged_at"] - r["built_at"]) / 60
        for r in local
        if isinstance(r.get("merged_at"), (int, float)) and isinstance(r.get("built_at"), (int, float))
    ]
    return {
        "shadow": {
            "groups": len(shadow),
            "same": len(shadow) - len(differ),
            "different": [{k: r.get(k) for k in ("url", "sha", "github", "local", "line")} for r in differ],
            "check_minutes_middle": _round(
                _middle([r["secs"] / 60 for r in shadow if isinstance(r.get("secs"), (int, float))])
            ),
        },
        "local": {
            "groups": len(local),
            "merged": len(merged),
            "minutes_to_merged_middle": _round(_middle(merged)),
            "fell_back": sum(1 for r in got if r.get("mode") == "local" and r.get("local") == BROKEN),
        },
    }


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 1)


def text(s: dict) -> str:
    sh, lo = s["shadow"], s["local"]
    lines = [
        f"Side by side: {sh['groups']} group(s) with both verdicts, {sh['same']} the same"
        + (
            f", local check {sh['check_minutes_middle']} min at the middle."
            if sh["check_minutes_middle"] is not None
            else "."
        ),
    ]
    for r in sh["different"]:
        lines.append(
            f"  different: {r['url']} GitHub {r['github']}, local {r['local']} ({r.get('line') or ''})"
        )
    lines.append(
        f"Local check: {lo['groups']} group(s), {lo['merged']} merged"
        + (
            f", {lo['minutes_to_merged_middle']} min from built to merged at the middle"
            if lo["minutes_to_merged_middle"] is not None
            else ""
        )
        + f"; {lo['fell_back']} went to GitHub because the check broke."
    )
    return "\n".join(lines)

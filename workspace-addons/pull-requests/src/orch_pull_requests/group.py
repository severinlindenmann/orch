"""Build one group commit from several pull requests, without a work folder.

A bare, blobless copy of the repository lives in `.orch/addons/pull-requests/git/<owner>-<name>.git`. The base
branch and each pull request's head (`refs/pull/N/head`) are fetched; then each head is merged on top of the
last result with `git merge-tree --write-tree` and `git commit-tree`. A head that conflicts is left out of the
group. Nothing is checked out, so this works next to any other git work on the computer. Pushing the result is
one GitHub write. git signs in through gh (`gh auth git-credential`), so no token is written anywhere.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .store import Refused

SHA = re.compile(r"[0-9a-f]{40}")
NO_GIT = "The merge queue needs git (2.38 or newer) on this computer to build a group."
NAME, EMAIL = "orch merge queue", "merge-queue@orch.invalid"


class Git:
    def __init__(self, folder: Path, repo: str, url: str | None = None):
        git = shutil.which("git")
        if git is None:
            raise Refused(NO_GIT)
        self.git, self.repo = git, repo
        self.dir = folder / "git" / (repo.replace("/", "-") + ".git")
        self.url = url or f"https://github.com/{repo}.git"
        gh = shutil.which("gh")
        self.cred = ["-c", "credential.helper="] + (
            ["-c", f'credential.helper=!"{gh}" auth git-credential'] if gh else []
        )

    def run(self, *args: str, timeout: int = 300, ok=(0,)) -> subprocess.CompletedProcess:
        # no inherited GIT_DIR / GIT_WORK_TREE / ...: they would point git at another repository
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_TERMINAL_PROMPT="0", LC_ALL="C")
        try:
            got = subprocess.run(
                [self.git, *self.cred, f"--git-dir={self.dir}", *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout, stdin=subprocess.DEVNULL, env=env, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise Refused(f"git {args[0]} did not finish in time.") from None
        except OSError:
            raise Refused(NO_GIT) from None
        if got.returncode not in ok:
            why = next((x.strip() for x in (got.stderr or got.stdout).splitlines() if x.strip()), "no reason")
            raise Refused(f"git {args[0]} failed: {why[:200]}")
        return got

    def prepare(self) -> None:
        if not (self.dir / "HEAD").is_file():
            self.dir.mkdir(parents=True, exist_ok=True)
            self.run("init", "--bare", "-q", str(self.dir))
        self.run("config", "remote.origin.url", self.url)

    def fetch(self, base: str, numbers: list[int]) -> dict[str, str]:
        """Fetch the base branch and the pull request heads. Returns {"base": sha, "<n>": sha}."""
        self.prepare()
        specs = [f"+refs/heads/{base}:refs/queue/base"] + [
            f"+refs/pull/{n}/head:refs/queue/pr/{n}" for n in numbers
        ]
        self.run("fetch", "-q", "--no-tags", "--filter=blob:none", "origin", *specs, timeout=600)
        out = {"base": self._sha("refs/queue/base")}
        for n in numbers:
            out[str(n)] = self._sha(f"refs/queue/pr/{n}")
        return out

    def _sha(self, ref: str) -> str:
        sha = self.run("rev-parse", "--verify", ref).stdout.strip()
        if not SHA.fullmatch(sha):
            raise Refused(f"git did not name a commit for {ref}.")
        return sha

    def build(self, base_sha: str, heads: list[tuple[int, str]]) -> tuple[str, list[int], list[int]]:
        """Merge each (number, head sha) on top of base_sha in order. Returns (result sha, included, conflicted)."""
        cur, included, conflicted = base_sha, [], []
        ident = [] if self._has_identity() else ["-c", f"user.name={NAME}", "-c", f"user.email={EMAIL}"]
        for n, head in heads:
            got = self.run("merge-tree", "--write-tree", "--no-messages", cur, head, ok=(0, 1))
            tree = (got.stdout.splitlines() or [""])[0].strip()
            if got.returncode == 1 or not SHA.fullmatch(tree):
                conflicted.append(n)
                continue
            msg = f"Merge queue: take in #{n}"
            cur = self.run(*ident, "commit-tree", tree, "-p", cur, "-p", head, "-m", msg).stdout.strip()
            included.append(n)
        return cur, included, conflicted

    def _has_identity(self) -> bool:
        got = self.run("config", "--get", "user.email", ok=(0, 1))
        return bool(got.stdout.strip())

    def push(self, sha: str, branch: str) -> None:
        self.run("push", "-q", "origin", f"{sha}:refs/heads/{branch}", timeout=600)

"""Set up the fake GitHub for an end-to-end run of the merge queue (ORCH-894): no network, no real GitHub.

    python3 e2e/fake_github.py <test HOME> [--login bot]

Makes <HOME>/fakegh/acme-app.git (a bare repository with `develop`), one branch per pull request below, the state
file <HOME>/fakegh/state.json, <HOME>/fakebin/gh (the fake, e2e/fixtures/fake-gh/gh) and a .gitconfig in <HOME> that
sends git's https://github.com/acme/app.git to the local repository. Run orch with PATH starting at <HOME>/fakebin
and FAKE_GH_STATE=<HOME>/fakegh/state.json. Touches nothing outside <HOME>.

Pull requests (acme/app, base develop):
  #1 feat/invoice-pdf   adds src/pdf.py                       green
  #2 feat/tax-round     adds src/tax.py                       green
  #3 feat/breaks-suite  adds src/csv.py + breaks-suites       light green, the group's `suites` fails
  #4 feat/readme        changes README.md                     green
  #5 feat/draft         adds src/try.py                       draft
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAKE = HERE / "fixtures" / "fake-gh" / "gh"
REPO = "acme/app"
PRS = [
    (1, "feat/invoice-pdf", "Show the invoice number on the PDF", {"src/pdf.py": "PDF = 1\n"}, {}),
    (2, "feat/tax-round", "Round tax per line", {"src/tax.py": "TAX = 2\n"}, {}),
    (3, "feat/breaks-suite", "Add CSV export", {"src/csv.py": "CSV = 3\n", "breaks-suites": "x\n"}, {}),
    (4, "feat/readme", "Explain the setup", {"README.md": "# app\n\nSetup: run make.\n"}, {}),
    (5, "feat/draft", "Try a new PDF library", {"src/try.py": "TRY = 5\n"}, {"draft": True}),
]


def git(cwd: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="dev", GIT_AUTHOR_EMAIL="dev@x.invalid", GIT_COMMITTER_NAME="dev",
               GIT_COMMITTER_EMAIL="dev@x.invalid", GIT_CONFIG_GLOBAL="/dev/null")  # fmt: skip
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def setup(home: Path, login: str = "bot", fakebin: Path | None = None) -> Path:
    root = home / "fakegh"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    bare, work = root / "acme-app.git", root / "work"
    git(root, "init", "-q", "--bare", "-b", "develop", str(bare))
    git(root, "init", "-q", "-b", "develop", str(work))
    (work / "README.md").write_text("# app\n", encoding="utf-8")
    (work / "src").mkdir()
    (work / "src" / "app.py").write_text("APP = 0\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "Start")
    git(work, "push", "-q", str(bare), "develop")
    prs = {}
    for n, branch, title, files, extra in PRS:
        git(work, "checkout", "-q", "-B", branch, "develop")
        for name, text in files.items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_text(text, encoding="utf-8")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", title)
        git(work, "push", "-q", str(bare), branch)
        prs[str(n)] = {"number": n, "title": title, "base": "develop", "head": branch, "state": "OPEN",
                       "author": login, **extra}  # fmt: skip
    state = {"repo": REPO, "login": login, "git": str(bare), "default": "develop", "required": ["light"],
             "prs": prs, "next": 100}  # fmt: skip
    (root / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    fakebin = fakebin or home / "fakebin"
    fakebin.mkdir(parents=True, exist_ok=True)
    shutil.copy(FAKE, fakebin / "gh")
    (fakebin / "gh").chmod(0o755)
    cfg = home / ".gitconfig"
    rule = f'[url "file://{bare}"]\n\tinsteadOf = https://github.com/{REPO}.git\n'
    old = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    if rule not in old:
        cfg.write_text(old + rule, encoding="utf-8")
    return root


def push(home: Path, branch: str, files: dict[str, str | None], msg: str = "More") -> str:
    """A new commit on a branch of the fake repository (a new branch starts at develop; None deletes a file);
    returns its sha."""
    work = home / "fakegh" / "work"
    bare = home / "fakegh" / "acme-app.git"
    remote = git(work, "ls-remote", str(bare), f"refs/heads/{branch}").split()
    base = remote[0] if remote else git(work, "ls-remote", str(bare), "refs/heads/develop").split()[0]
    git(work, "fetch", "-q", str(bare), base)
    git(work, "checkout", "-q", "-B", branch, base)
    for name, text in files.items():
        p = work / name
        if text is None:
            p.unlink(missing_ok=True)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", msg)
    git(work, "push", "-q", "-f", str(bare), branch)
    return git(work, "rev-parse", "HEAD")


def change(home: Path, **fields) -> None:
    """Change the fake's state under its lock (e.g. down=True: GitHub does not answer)."""
    import fcntl

    root = home / "fakegh"
    with (root / "state.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = root / "state.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        s.update(fields)
        p.write_text(json.dumps(s, indent=1), encoding="utf-8")


def open_pr(home: Path, n: int, branch: str, title: str, files: dict[str, str | None]) -> None:
    """A new pull request #n into develop from a new branch with these files."""
    import fcntl

    push(home, branch, files, title)
    root = home / "fakegh"
    with (root / "state.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = root / "state.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        s["prs"][str(n)] = {"number": n, "title": title, "base": "develop", "head": branch, "state": "OPEN",
                            "author": s["login"]}  # fmt: skip
        p.write_text(json.dumps(s, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    who = sys.argv[sys.argv.index("--login") + 1] if "--login" in sys.argv else "bot"
    print(setup(Path(sys.argv[1]).resolve(), who))

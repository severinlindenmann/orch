"""Proof pictures of a dashboard pull request, taken by CI (ORCH-312; job dash-shots, workflows/addons.yml).

Finds the dashboard pages the change shows on (orch.dashshots.pages_for), installs orch from this checkout
into a throwaway home, makes a workspace with a few sample tickets (a running one with steps and proof, a
question with options, one waiting for review, a new one), starts the real dashboard and takes pictures of
those pages with `orch shot` at 1280, 1920 and 390 px. The pictures and manifest.json land in --out; the job
uploads them as the artifact dashboard-shots; `orch ask ... --ci-shots <pull request>` shows them on a card.

usage: python e2e/dash_ci_shots.py --out <folder> [--base <commit>] [--head <sha>] [--pr <n>] [--files a,b]
Prints the pages it took; writes pages=<list> to $GITHUB_OUTPUT when set (empty: nothing to take).
Never run it with the real home: it makes its own HOME and ORCH_HOME under a temp folder."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "workspace" / "src"))

from orch import dashshots  # noqa: E402

MACHINERY = {
    "e2e/dash_ci_shots.py",
    ".github/workflows/dash-shots.yml",
    "workspace/src/orch/cli_shot.py",
    "workspace/src/orch/dashshots.py",
}


def changed_files(base: str) -> list[str]:
    r = subprocess.run(["git", "diff", "--name-only", base, "HEAD"], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"git diff against {base} failed: {r.stderr.strip()[:300]}")
    return [x for x in r.stdout.splitlines() if x.strip()]


class Home:
    """orch installed from this checkout into a throwaway home; every command runs there."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.bin = tmp / "bin"
        self.ws = tmp / "work" / "Pilatus"
        for d in (self.home, self.bin, self.ws):
            d.mkdir(parents=True, exist_ok=True)
        (self.home / ".gitconfig").write_text(
            "[init]\n\tdefaultBranch = main\n[user]\n\tname = CI\n\temail = ci@example.invalid\n"
        )
        path = os.pathsep.join(
            [str(self.bin), str(Path(shutil.which("uv") or "uv").parent), "/usr/bin", "/bin"]
        )
        self.env = {
            "PATH": path,
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "ORCH_HOME": str(tmp / "orch"),
            "ORCH_HOME_STRICT": "1",
            "UV_TOOL_DIR": str(tmp / "tools"),
            "UV_TOOL_BIN_DIR": str(self.bin),
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR") or str(tmp / "uv-cache"),
            "LANG": "C.UTF-8",
            "TZ": "Europe/Zurich",
        }
        if os.environ.get("ORCH_SHOT_BROWSER"):
            self.env["ORCH_SHOT_BROWSER"] = os.environ["ORCH_SHOT_BROWSER"]

    def run(self, *args: str, cwd: Path | None = None, timeout: int = 120) -> str:
        r = subprocess.run(
            list(args), cwd=cwd or self.ws, env=self.env, capture_output=True, text=True, timeout=timeout
        )
        if r.returncode != 0:
            sys.exit(f"{' '.join(args[:4])} failed ({r.returncode}): {(r.stderr or r.stdout).strip()[-600:]}")
        return r.stdout

    def orch(self, *args: str, timeout: int = 120) -> str:
        return self.run(str(self.bin / "orch"), *args, timeout=timeout)

    def orchj(self, *args: str) -> dict:
        return json.loads(self.orch(*args, "--json"))

    def install(self) -> None:
        self.run("uv", "tool", "install", "--quiet", str(REPO / "workspace"), cwd=self.tmp, timeout=600)
        # a dev install, as e2e/main.py does: the shipped add-ons come from this checkout
        shim = (self.bin / "orch").resolve().read_text(errors="replace").splitlines()[0]
        py = shim[2:].strip().split()[0]
        self.run(py, "-c", "import sys; from pathlib import Path; from orch import home as h; "
                 "h.write_install_record(Path(sys.prefix), 'dev')", cwd=self.tmp)  # fmt: skip

    def seed(self) -> str:
        """A small realistic workspace; returns the key of the ticket whose page is shown."""
        self.run("git", "init", "-q", "-b", "main")
        self.orch("init")
        self.orch("addon", "add", "dashboard", "--yes", timeout=600)
        lunch = self.orchj("ticket", "new", "Plan the team lunch on Friday")
        tid = lunch["id"]
        self.orch("ticket", "tidy", tid, "Plan the team lunch on Friday",
                  "--description", "Twelve people, one table near the office, a vegetarian choice.",
                  "--done-when", "A table is booked and everyone has the address.")  # fmt: skip
        for step in ("Ask the team who comes", "Find three places near the office", "Book the table"):
            self.orch("check", "add", tid, step)
        self.orch("ticket", "status", tid, "active")
        self.orch("check", "done", tid, "c1", "--summary", "Twelve people come, two eat vegetarian.",
                  "--note", "Answers collected in the team chat.")  # fmt: skip
        self.orch("check", "done", tid, "c2", "--summary", "Three places with a table on Friday at noon.",
                  "--note", "Linde, Rössli and Seegarten have room for twelve.")  # fmt: skip
        self.orch("check", "start", tid, "c3")
        sup = self.orchj("ticket", "new", "Answer the supplier about the delivery date")["id"]
        self.orch("check", "add", sup, "Write the answer")
        self.orch("ask", sup, "The supplier can deliver on Tuesday or Thursday. Which day?",
                  "--option", "Tuesday", "--option", "Thursday", "--recommend", "Tuesday")  # fmt: skip
        rep = self.orchj("ticket", "new", "Monthly sales report for October")["id"]
        self.orch("check", "add", rep, "Collect the numbers")
        self.orch(
            "check",
            "done",
            rep,
            "c1",
            "--summary",
            "Sales up 8% on September.",
            "--note",
            "From the shop export.",
        )
        self.orch("ticket", "summary", rep, "The October report is ready: sales up 8%, two new customers.")
        self.orch("ticket", "status", rep, "done")
        self.orchj("ticket", "new", "Book the meeting room for the quarterly review")
        return lunch.get("key") or tid

    def start(self) -> str:
        out = self.orchj("start", "--print-launch-url", "--no-open")
        url = next((x["url"] for x in out.get("launch") or [] if x.get("addon") == "dashboard"), None)
        if not url or "#launch=" not in url:
            sys.exit(f"orch start printed no sign-in link for the dashboard: {json.dumps(out)[:600]}")
        return url

    def stop(self) -> None:
        subprocess.run(
            [str(self.bin / "orch"), "stop"], cwd=self.ws, env=self.env, capture_output=True, timeout=60
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--base", default="HEAD^1", help="the commit to compare with (a pull request's merge: HEAD^1)"
    )
    ap.add_argument(
        "--head", default="", help="the pull request's newest commit (written into manifest.json)"
    )
    ap.add_argument("--pr", type=int, default=None)
    ap.add_argument("--files", default=None, help="comma list of changed files instead of git diff")
    a = ap.parse_args()
    files = a.files.split(",") if a.files is not None else changed_files(a.base)
    pages = dashshots.pages_for(files)
    if not pages and any(f.strip() in MACHINERY for f in files):
        pages = ["home"]  # a change to what takes the pictures proves itself on one page
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"pages={','.join(pages)}\n")
    if not pages:
        print("No dashboard page changed: no pictures.")
        return 0
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="orch-dash-shots-"))
    h = Home(tmp)
    try:
        h.install()
        key = h.seed()
        url = h.start()
        spec = ",".join(f"ticket=ticket/{key}" if p == "ticket" else p for p in pages)
        widths = ",".join(map(str, dashshots.WIDTHS))
        h.orch("shot", url, "--page", spec, "--width", widths, "--out", str(out), "--name", "dashboard",
               "--wait", "15", timeout=600)  # fmt: skip
    finally:
        h.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    m = dashshots.manifest(a.head, a.pr, pages, out)
    (out / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
    missing = [p["page"] for p in m["pages"] if len(p["files"]) != len(dashshots.WIDTHS)]
    print(f"Pictures of {', '.join(pages)} at {widths} px in {out}")
    if missing:
        print(f"Missing pictures for: {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

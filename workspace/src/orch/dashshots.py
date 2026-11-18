"""Pictures of a dashboard pull request, taken by CI (ORCH-312).

Helpers took their own screenshots: a keychain window on the person's screen, cut-off phone pictures, the
mockup instead of the product (ORCH-141). Now the CI job dash-shots starts the real dashboard on sample
tickets and takes pictures of the pages a pull request changes with `orch shot` at 1280, 1920 and 390 px
(e2e/dash_ci_shots.py). `orch ask ... --ci-shots <pull request>` fetches those pictures and puts them on the
review card as one page.

Here: which pages a change touches (pages_for), the list CI writes beside the pictures (manifest), fetching
them from GitHub (fetch) and the one page the card shows (sheet_html)."""

from __future__ import annotations

import base64
import html
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from orch import ghmerge
from orch.errors import Refused

CI_WORKFLOW = ".github/workflows/ci.yml"  # the workflow whose runs may carry the pictures
# A pull request that changes these takes its own pictures with its own code: the card says so.
MACHINERY = (
    "e2e/dash_ci_shots.py",
    ".github/workflows/",
    "workspace/src/orch/cli_shot.py",
    "workspace/src/orch/dashshots.py",
)
ARTIFACT = "dashboard-shots"  # the name of the CI job's upload (.github/workflows/addons.yml, dash-shots)
SCHEMA = "orch.dashboard-shots/1"
WIDTHS = (1280, 1920, 390)
WIDTH_NAMES = {1280: "Desktop", 1920: "Wide screen", 390: "Phone"}
# The main dashboard pages, in the order the card shows them. "ticket" is one ticket's page.
PAGES = {
    "home": "Home",
    "tickets": "Tickets",
    "ticket": "A ticket",
    "review": "Review",
    "chat": "Chat",
    "settings": "Settings",
}
WEB = "workspace-addons/dashboard/src/orch_dashboard/web/"
SERVER = "workspace-addons/dashboard/src/orch_dashboard/"
KIT = "workspace/src/orch_ui/static/"
# A page's own files (web/pages/<name>.js|css) change only that page; newticket is the form opened from Home.
OWN = {"newticket": "home"}
MAX_PNG = 4 * 1024 * 1024
MAX_SHEET = 9 * 1024 * 1024  # under the card's 10 MB for one file (review.MAX_FILE)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FILE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,60}-(?:1280|1920|390)\.png")


def pages_for(files: list[str]) -> list[str]:
    """The dashboard pages a change shows on, from the changed file paths. A page's own script or style
    sheet: that page; anything else the pages share (app, design system, the server that builds the
    data): every page. Tests and docs: none."""
    pages: set[str] = set()
    for f in files:
        f = f.strip().replace("\\", "/")
        if not f or "/tests/" in f or f.endswith((".md", ".txt")):
            continue
        if f.startswith(WEB + "pages/"):
            stem = f[len(WEB + "pages/") :].rsplit(".", 1)[0]
            page = OWN.get(stem, stem)
            if page in PAGES:
                pages.add(page)
                continue
            return list(PAGES)  # live layers, soft refresh and the like show on every page
        if f.startswith((WEB, KIT)) or (f.startswith(SERVER) and f.endswith(".py")):
            return list(PAGES)
    return [p for p in PAGES if p in pages]


def file_name(page: str, width: int, prefix: str = "page") -> str:
    return f"{prefix}-{page}-{width}.png"


def manifest(head: str, pr: int | None, pages: list[str], out: Path, prefix: str = "page") -> dict:
    """The list CI writes next to the pictures: which page is in which file, for which commit."""
    rows = []
    for p in pages:
        files = {str(w): file_name(p, w, prefix) for w in WIDTHS if (out / file_name(p, w, prefix)).is_file()}
        rows.append({"page": p, "label": PAGES.get(p, p), "files": files})
    return {"schema": SCHEMA, "head": head, "pr": pr, "pages": rows}


def _check_manifest(m, folder: Path) -> list[dict]:
    if not isinstance(m, dict) or m.get("schema") != SCHEMA or not isinstance(m.get("pages"), list):
        raise Refused("The pictures from CI came without their list. Run the checks again.")
    rows = []
    for row in m["pages"][: len(PAGES)]:
        if (
            not isinstance(row, dict)
            or row.get("page") not in PAGES
            or not isinstance(row.get("files"), dict)
        ):
            raise Refused("The list of pictures from CI is not readable. Run the checks again.")
        files = {}
        for w, name in row["files"].items():
            if w not in {str(x) for x in WIDTHS} or not isinstance(name, str) or not FILE_RE.fullmatch(name):
                raise Refused("The list of pictures from CI names an odd file. Run the checks again.")
            p = folder / name
            if not p.is_file() or p.is_symlink() or p.stat().st_size > MAX_PNG:
                raise Refused(f"The picture {name} is missing or too large. Run the checks again.")
            if p.read_bytes()[:8] != PNG_MAGIC:
                raise Refused(f"{name} is not a picture. Run the checks again.")
            files[int(w)] = name
        rows.append({"page": row["page"], "label": PAGES[row["page"]], "files": files})
    if not rows:
        raise Refused("CI took no pictures for this pull request: it changes no dashboard page.")
    return rows


def sheet_html(title: str, rows: list[dict], folder: Path, note: str = "") -> str:
    """One page with every picture in it (data addresses: a card's page is shown alone, in a sandbox)."""
    parts = []
    for row in rows:
        figs = []
        for w in WIDTHS:
            name = row["files"].get(w)
            if not name:
                continue
            data = base64.b64encode((folder / name).read_bytes()).decode("ascii")
            label = f"{row['label']}, {WIDTH_NAMES[w].lower()} ({w} px)"
            figs.append(
                f'<figure class="w{w}"><img src="data:image/png;base64,{data}" alt="{html.escape(label)}" '
                f'loading="lazy"><figcaption>{WIDTH_NAMES[w]} · {w} px</figcaption></figure>'
            )
        parts.append(
            f'<section><h2>{html.escape(row["label"])}</h2><div class="row">{"".join(figs)}</div></section>'
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>"
        ":root{--bg:#f6f6f4;--fg:#1d1d1b;--muted:#6b6b66;--line:#dcdcd6;--card:#fff}"
        "@media (prefers-color-scheme: dark){:root{--bg:#161615;--fg:#ececea;--muted:#a3a39e;--line:#33332f;"
        "--card:#1f1f1d}}"
        "body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}"
        "h1{font-size:18px;margin:0 0 4px}p{margin:0 0 16px;color:var(--muted)}"
        "h2{font-size:16px;margin:24px 0 8px}"
        ".row{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start}"
        "figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px}"
        "figure.w1280,figure.w1920{flex:1 1 100%;min-width:0}figure.w390{flex:0 1 390px;min-width:0}"
        "img{display:block;width:100%;height:auto;border-radius:4px}"
        "figcaption{font-size:13px;color:var(--muted);margin-top:6px}"
        "</style></head><body>"
        f"<h1>{html.escape(title)}</h1><p>{html.escape(note)}</p>{''.join(parts)}</body></html>"
    )


# ------------------------------------------------------------------ fetching from GitHub


def _gh(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    gh = shutil.which("gh")
    if gh is None:
        raise Refused("--ci-shots needs the GitHub command line (gh) to fetch the pictures.")
    try:
        return subprocess.run(
            [gh, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise Refused("GitHub did not answer in time. Try again in a minute.") from None


def _first(text: str) -> str:
    return (text or "").strip().splitlines()[0][:200] if (text or "").strip() else "no answer"


def _pr(url: str) -> tuple[str, int]:
    m = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([0-9]{1,9})", url or "")
    if m is None or not ghmerge.is_pr_url(url):
        raise Refused(
            "--ci-shots takes a GitHub pull request address, e.g. https://github.com/owner/repo/pull/12."
        )
    return m[1], int(m[2])


def find_artifact(repo: str, head: str) -> int:
    """The pictures of this commit: the id of the newest upload. It is there as soon as the picture job has
    uploaded it, while the run's other jobs may still go on."""
    # only the pull request runs of the ci workflow (it calls dash-shots): no other workflow's upload of the
    # same name counts
    pick = f'.path == "{CI_WORKFLOW}" and .event == "pull_request"'
    jq = f".workflow_runs[] | select({pick}) | [.id, .status] | @tsv"
    r = _gh(["api", f"repos/{repo}/actions/runs?head_sha={head}&per_page=50", "--jq", jq])
    if r.returncode != 0:
        raise Refused(f"GitHub did not list the checks of the pull request: {_first(r.stderr)}.")
    running = False
    for line in r.stdout.splitlines():
        rid, _, status = line.partition("\t")
        if not rid.isdigit():
            continue
        running = running or status != "completed"
        keep = f'.name == "{ARTIFACT}" and (.expired | not)'
        jq = f".artifacts[] | select({keep}) | [.id, .size_in_bytes] | @tsv"
        a = _gh(["api", f"repos/{repo}/actions/runs/{rid}/artifacts", "--jq", jq])
        found = []
        for row in a.stdout.splitlines() if a.returncode == 0 else []:
            aid, _, size = row.partition("\t")
            if aid.isdigit() and size.isdigit():
                found.append((int(aid), int(size)))
        if found:
            aid, size = max(found)
            if size > MAX_ZIP:  # asked before the download, so a huge upload is never fetched
                raise Refused("The pictures from CI are too large. Run the checks again.")
            return aid
    if running:
        raise Refused("CI is still taking the pictures of the newest commit. Ask again in a few minutes.")
    raise Refused(
        "CI kept no dashboard pictures for the newest commit of this pull request (it changes no "
        "dashboard page, or the checks did not run)."
    )


def _gh_bytes(args: list[str], timeout: int = 120) -> bytes:
    gh = shutil.which("gh")
    if gh is None:
        raise Refused("--ci-shots needs the GitHub command line (gh) to fetch the pictures.")
    try:
        r = subprocess.run([gh, *args], capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise Refused("GitHub did not answer in time. Try again in a minute.") from None
    if r.returncode != 0:
        raise Refused(
            f"GitHub did not hand over the pictures: {_first(r.stderr.decode('utf-8', 'replace'))}."
        )
    return r.stdout


MAX_ZIP = 40 * 1024 * 1024
MAX_UNPACKED = 3 * MAX_SHEET  # every picture of one pull request together


def _unpack(data: bytes, folder: Path) -> None:
    """Only the list and plainly named pictures, each within its size; nothing else leaves the archive."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
    except (zipfile.BadZipFile, ValueError):
        raise Refused("The pictures from CI came broken. Run the checks again.") from None
    files = [i for i in infos if not i.is_dir()]
    if len(files) > 1 + len(PAGES) * len(WIDTHS):
        raise Refused("The pictures from CI hold too many files. Run the checks again.")
    seen: set[str] = set()
    total = 0
    for i in files:
        if not (i.filename == "manifest.json" or FILE_RE.fullmatch(i.filename)) or i.filename in seen:
            raise Refused("The pictures from CI hold an odd file. Run the checks again.")
        seen.add(i.filename)
        with z.open(i) as f:  # read at most one byte over the limit, whatever the archive claims
            data = f.read(MAX_PNG + 1)
        total += len(data)
        if len(data) > MAX_PNG or total > MAX_UNPACKED:
            raise Refused(f"{i.filename} from CI is too large. Run the checks again.")
        (folder / i.filename).write_bytes(data)


def fetch(url: str, dest: Path) -> tuple[dict, list[dict]]:
    """Download the pictures CI took of the pull request's newest commit into dest: (manifest, rows)."""
    repo, number = _pr(url)
    v = _gh(["pr", "view", url, "--json", "headRefOid,files", "--jq", ".headRefOid, .files[].path"])
    head, *files = v.stdout.split("\n") if v.returncode == 0 else ("",)
    head = head.strip()
    if v.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise Refused(f"GitHub did not show the pull request: {_first(v.stderr)}.")
    art = find_artifact(repo, head)
    data = _gh_bytes(["api", f"repos/{repo}/actions/artifacts/{art}/zip"])
    if len(data) > MAX_ZIP:
        raise Refused("The pictures from CI are too large. Run the checks again.")
    tmp = Path(tempfile.mkdtemp(prefix="orch-ci-shots-"))
    try:
        _unpack(data, tmp)
        try:
            m = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = None
        rows = _check_manifest(m, tmp)
        if m.get("head") != head:
            raise Refused("The pictures from CI are of an older commit. Ask again when the checks are done.")
        dest.mkdir(parents=True, exist_ok=True)
        for row in rows:
            for name in row["files"].values():
                shutil.copyfile(tmp / name, dest / name)
        (dest / "manifest.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
        m["pr"] = number
        m["own_machinery"] = any(f.strip().startswith(MACHINERY) for f in files)
        return m, rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def card_file(root: Path, tid: str, url: str) -> str:
    """Fetch the pictures for the card and write the one page it shows; returns its card source
    (artifacts/<name>). The pictures stay in the ticket's files too."""
    from orch import tickets

    _repo, number = _pr(url)
    art = tickets.artifacts_dir(root, tid)
    folder = art / f"ci-pictures-pr{number}"
    m, rows = fetch(url, folder)
    widths = " · ".join(f"{WIDTH_NAMES[w].lower()} {w} px" for w in WIDTHS)
    note = f"Taken by CI on the real dashboard with sample tickets, commit {m['head'][:7]}: {widths}."
    if m.get("own_machinery"):
        note += " This pull request also changes how the pictures are taken: check them with that in mind."
    page = sheet_html(f"Pull request #{number}: the changed pages", rows, folder, note)
    if len(page.encode("utf-8")) > MAX_SHEET:
        raise Refused("The pictures from CI are too large for one card. Show fewer pages.")
    name = f"ci-pictures-pr{number}.html"
    (art / name).write_text(page, encoding="utf-8")
    return f"artifacts/{name}"

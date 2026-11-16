"""A proposal for the workspace profile (name, description, tags, icon), worked out from the folder itself.

`orch config propose --json` (Settings > Workspace profile > Suggest). Read-only: nothing is saved; the person
accepts or edits the proposal in the dashboard, which then saves it with `orch config set workspace.*`.

Sources, in this order: README, AGENTS.md / CLAUDE.md, package.json, pyproject.toml, Cargo.toml (first heading
and first line of prose), the ticket titles, the file types at the top of the folder and the folder name.
Every file is read through `saferead.read_private` (no links, nothing outside the folder, bounded), never
anything under .orch/ except the ticket titles orch already lists. No network, no helper run: it answers
at once.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from pathlib import Path

from orch import config, look, saferead

LIMIT = 64 * 1024  # bytes read from one file
DOCS = ("README.md", "README.markdown", "README.txt", "README", "readme.md", "AGENTS.md", "CLAUDE.md")
TECH = (  # file at the top -> tag
    ("pyproject.toml", "python"),
    ("requirements.txt", "python"),
    ("Cargo.toml", "rust"),
    ("package.json", "javascript"),
    ("go.mod", "go"),
    ("Gemfile", "ruby"),
    ("pom.xml", "java"),
)
# Headings that name the file, not the work.
GENERIC = re.compile(
    r"^(readme|agents?(\.md)?|claude(\.md)?|instructions?|rules|notes|todo|overview|introduction|"
    r"table of contents|contents|about|getting started|setup|installation|usage|license)$",
    re.I,
)
STOP = set(
    """
    a an and are as at be by can do does done for from get has have how if in into is it its let lets make
    new no not now of on one only or our out so that the their them then there this those to two up use
    via was we what when where which who why will with you your all any add adds added fix fixes fixed
    show shows set sets more less after before over under each every also just than too very same
    file files folder page pages work works working task tasks ticket tickets step steps thing things
    workspace workspaces orch-ticket owner person people user users helper helpers agent agents
    readme todo test tests check checks first last next still keep keeps own way ways stays stay
    start starts started stop stops stopped see sees seen give gives gave take takes run runs ran go goes
    went come comes came want wants need needs needed says say said like likes used using uses find finds
    found open opens opened close closes closed name names named click clicks clicked turn turns turned
    shared share shares builds build built help helps change changes changed move moves moved try tries
    good bad big small full part parts other others another many much some most wrong right soon later
    today tomorrow yes cannot can't don't isn't won't should would could must may might here about without
    """.split()
)
WORD = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,23}")


def _read(root: Path, rel: str) -> str:
    b = saferead.read_private(root, rel, LIMIT) if (root / rel).exists() else None
    if b is None:
        return ""
    return b.decode("utf-8", "replace")


def _strip_md(line: str) -> str:
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)  # images and badges
    line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)  # links keep their words
    line = re.sub(r"[`*_~]+", "", line)
    line = re.sub(r"<[^>]+>", "", line)
    return re.sub(r"\s+", " ", line).strip()


def _heading_and_line(text: str) -> tuple[str, str]:
    """The first useful heading and the first line of prose after any heading."""
    head, prose, fence = "", "", False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
            continue
        if fence or not s or s.startswith("@") or s.startswith("<!--"):
            continue
        if s.startswith("#") or re.match(r"<h[1-6][\s>]", s, re.I):
            h = _strip_md(s.lstrip("#"))
            if not head and h and not GENERIC.match(h):
                head = h
            continue
        if re.match(r"^([-*+>|]|\d+[.)]\s|={3,}|-{3,})", s):
            continue
        p = _strip_md(s)
        if len(p) >= 12 and not prose:
            prose = p
        if head and prose:
            break
    return head, prose


def _name_from(head: str) -> str:
    """'ORCH Development: rules for every agent' -> 'ORCH Development'; at most 4 words, 60 characters."""
    h = re.split(r"\s[-–—:|]\s|:\s", head, maxsplit=1)[0].strip(" .")
    words = h.split()
    if not words or len(words) > 6:
        return ""
    return " ".join(words[:4])[:60]


def _sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    s = (m.group(1) if m else text).strip()
    if len(s) > 140:
        s = s[:139].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return s


def _folder_name(root: Path) -> str:
    words = [w for w in re.split(r"[-_.\s]+", root.name) if w]
    return " ".join(w if w.isupper() else w.capitalize() for w in words)[:60] or "Workspace"


def _manifests(root: Path) -> tuple[str, str]:
    """(name, description) from package.json / pyproject.toml / Cargo.toml, if any says one."""
    try:
        pj = json.loads(_read(root, "package.json") or "{}")
        if isinstance(pj, dict) and isinstance(pj.get("description"), str) and pj["description"].strip():
            return str(pj.get("name") or ""), pj["description"].strip()
    except ValueError:
        pass
    for rel, table in (("pyproject.toml", "project"), ("Cargo.toml", "package")):
        try:
            doc = tomllib.loads(_read(root, rel) or "")
        except (tomllib.TOMLDecodeError, ValueError):
            continue
        t = doc.get(table) if isinstance(doc.get(table), dict) else {}
        if isinstance(t.get("description"), str) and t["description"].strip():
            return str(t.get("name") or ""), t["description"].strip()
    return "", ""


def _ticket_titles(root: Path) -> list[str]:
    from orch import tickets

    try:
        return [str(t.get("title") or "") for t in tickets.list_all(root)][:300]
    except Exception:  # noqa: BLE001 - a broken ticket must never break a proposal
        return []


def _tags(root: Path, texts: list[str], weights: list[int], name: str) -> list[str]:
    count: Counter[str] = Counter()
    skip = {"workspace", "orch-test", "project", "repo", "folder"}
    for text, weight in zip(texts, weights, strict=True):
        for w in WORD.findall(text):
            lw = w.lower().strip("-")
            if lw in STOP or lw in skip or lw.isdigit() or len(lw) < 3:
                continue
            if lw.endswith("s") and lw[:-1] in count:  # plural joins the singular
                lw = lw[:-1]
            count[lw] += weight
    tech = [tag for rel, tag in TECH if (root / rel).is_file()]
    tags: list[str] = []
    for t in tech[:1]:
        tags.append(t)
    for w, c in count.most_common():
        if len(tags) >= 3:
            break
        if c < 3:  # a word of the description needs one ticket title too; a title word needs three
            break
        t = re.sub(r"[^a-z0-9-]", "", w)[:24]
        if t and t not in tags:
            tags.append(t)
    return tags[: config.MAX_WS_TAGS]


ICON_WORDS = {  # common words the icon list does not name
    "development": "code",
    "software": "code",
    "app": "code",
    "python": "code",
    "rust": "code",
    "javascript": "code",
    "go": "code",
    "programming": "code",
    "agents": "robot",
    "release": "rocket",
    "website": "globe",
    "web": "globe",
    "newsletter": "mail",
    "finance": "wallet",
    "taxes": "bank",
    "budget": "savings",
    "photos": "camera",
    "research": "idea",
    "writing": "writing",
    "family": "house",
}


def _icon(words: list[str]) -> str | None:
    """The first icon whose label, id or keywords match a word of the proposal."""
    want = [w.lower() for w in words]
    for w in want:
        if w in ICON_WORDS and ICON_WORDS[w] in look.ICON_IDS:
            return ICON_WORDS[w]
        w = w[:-1] if w.endswith("s") and len(w) > 3 else w
        for i in look.DATA["icons"]:
            names = {i["id"].lower(), i["label"].lower(), *(k.lower() for k in i.get("keywords", []))}
            if w in names:
                return i["id"]
    return None


def propose(root: Path) -> dict:
    """{name, description, tags, icon, from}: a proposal only; `from` names the sources in plain words."""
    root = Path(root).resolve()
    head = prose = ""
    used: list[str] = []
    for rel in DOCS:
        text = _read(root, rel)
        pointer = rel == "CLAUDE.md" and all(x.startswith("@") for x in text.split())  # only "@AGENTS.md"
        if not text.strip() or pointer:
            continue
        h, p = _heading_and_line(text)
        if h and not head:
            head = h
            used.append(rel)
        if p and not prose:
            prose = p
            if rel not in used:
                used.append(rel)
        if head and prose:
            break
    m_name, m_desc = _manifests(root)
    name = _name_from(head) if head else ""
    if not name and m_name:
        name = _folder_name(Path(m_name))
    if not name:
        name = _folder_name(root)
        used.append("the folder name")
    desc = _sentence(prose) if prose else (_sentence(m_desc) if m_desc else "")
    titles = _ticket_titles(root)
    if titles:
        used.append("the ticket titles")
    texts = [name, desc, *titles]
    head_weight = 1 if "the folder name" in used else 3  # a folder name alone is no tag
    weights = [head_weight, 2, *([1] * len(titles))]
    tags = _tags(root, texts, weights, name)
    icon = _icon([*WORD.findall(name), *tags, *WORD.findall(desc)])
    try:
        now = look.read(root)
        if now["set_by"] == "human" and now["icon"]:
            icon = None  # the person picked the icon: never propose another
    except Exception:  # noqa: BLE001 - the look is optional here
        pass
    return {"name": name, "description": desc, "tags": tags, "icon": icon, "from": used}

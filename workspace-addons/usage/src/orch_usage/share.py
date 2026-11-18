"""How helper work is spread (ORCH-657): the owner's share, kept in .orch/addons/usage/share.json.

One small file next to accounts.json, schema `orch.usage-share/1`:

    {"schema": "orch.usage-share/1", "share": {
        "week_pct": 70,                 # at most this % of a subscription's week used ...
        "by_day": "wednesday",          # ... by the end of this weekday (day 3 of the 7 days of that week)
        "api_for": ["reviews", "scripts"],  # these kinds of work run on API credit
        "codex_one_in": 4,              # 0 = no Code tickets on Codex, 1 = all, N = one in N
        "when_ahead": "api",            # a subscription ahead of that pace: new starts go to api | codex | both | none
        "day_dollars": 10}}             # ... for up to this many dollars a day (only with api or both)

The order of the accounts is the order Usage already keeps (`orch usage order`); the share reads it back.
Every change is one line in history.jsonl (account "share"). A share that contradicts itself is refused with plain
words (`problems`). Only numbers, kinds and words: never a login, key or address.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from . import store
from .store import KINDS, Refused

SCHEMA = "orch.usage-share/1"
ACCOUNT = "share"  # the history lines of the share carry this instead of an account id
LABEL = "How work is spread"
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
AHEAD = ("api", "codex", "both", "none")
KIND_WORDS = {
    "lead": "Lead",
    "code": "Code",
    "reviews": "Reviews",
    "builds": "Builds",
    "scripts": "Scripts",
    "helpers": "Helpers",
}
AHEAD_WORDS = {
    "api": "API credit",
    "codex": "Codex",
    "both": "API credit, then Codex",
    "none": "the subscriptions",
}
MIN_PCT, MAX_PCT = 10, 100
MAX_ONE_IN = 20
MAX_DOLLARS = 1000

# The three ready-made spreads of the picked page draft (ORCH-656, draft C).
PRESETS = {
    "save": {
        "name": "Save the subscription",
        "what": "API credit and Codex take a big share, so the subscriptions last all week.",
        "share": {
            "week_pct": 50,
            "by_day": "wednesday",
            "api_for": ["reviews", "scripts", "helpers"],
            "codex_one_in": 2,
            "when_ahead": "both",
            "day_dollars": 20,
        },
    },
    "even": {
        "name": "Even spread",
        "what": "Reviews and Scripts on API credit, one in 4 Code tickets on Codex.",
        "share": {
            "week_pct": 70,
            "by_day": "wednesday",
            "api_for": ["reviews", "scripts"],
            "codex_one_in": 4,
            "when_ahead": "api",
            "day_dollars": 10,
        },
    },
    "sub": {
        "name": "Subscription first",
        "what": "Nearly everything on the subscriptions. API credit only when one runs ahead.",
        "share": {
            "week_pct": 90,
            "by_day": "friday",
            "api_for": [],
            "codex_one_in": 0,
            "when_ahead": "api",
            "day_dollars": 5,
        },
    },
}
FIELDS = tuple(PRESETS["even"]["share"])


def path(root: Path) -> Path:
    return store.usage_dir(root) / "share.json"


# ---------------------------------------------------------------- checking


def _shape_ok(s) -> bool:
    """The file's own shape: right fields and types. Contradictions are `problems`, not shape."""
    if not isinstance(s, dict) or set(s) != set(FIELDS):
        return False
    pct, one_in, dollars = s["week_pct"], s["codex_one_in"], s["day_dollars"]
    if not isinstance(pct, int) or isinstance(pct, bool) or not MIN_PCT <= pct <= MAX_PCT:
        return False
    if not isinstance(one_in, int) or isinstance(one_in, bool) or not 0 <= one_in <= MAX_ONE_IN:
        return False
    if not isinstance(dollars, (int, float)) or isinstance(dollars, bool) or not 0 <= dollars <= MAX_DOLLARS:
        return False
    if s["by_day"] not in DAYS or s["when_ahead"] not in AHEAD:
        return False
    kinds = s["api_for"]
    if not isinstance(kinds, list) or not all(isinstance(k, str) and k in KINDS for k in kinds):
        return False
    return len(set(kinds)) == len(kinds)


def problems(s: dict) -> list[str]:
    """Why a share contradicts itself, in plain words. Empty: it can be saved."""
    out = []
    ahead, dollars = s["when_ahead"], s["day_dollars"]
    if len(s["api_for"]) == len(KINDS):
        out.append(
            "Every kind of work is on API credit, so nothing starts on the subscriptions first. "
            "Leave at least one kind on the subscriptions."
        )
    if "code" in s["api_for"] and s["codex_one_in"] == 1:
        out.append("Code is on API credit and all Code tickets are on Codex. Pick one of the two.")
    if ahead in ("api", "both") and dollars <= 0:
        out.append(
            "New starts cannot go to API credit with $0 a day. Raise the dollars a day, or send them to Codex."
        )
    if ahead in ("codex", "none") and dollars > 0:
        out.append(
            "Dollars a day only count when new starts go to API credit; "
            + ("they go to Codex. " if ahead == "codex" else "they stay on the subscriptions. ")
            + 
"Set the dollars to 0 or send them to API credit."
        )
    if s["week_pct"] == MAX_PCT and ahead != "none":
        out.append(
            "At 100 % a subscription is never ahead of its pace, so the part about being ahead never happens. "
            "Lower the percent, or keep new starts on the subscriptions."
        )
    return out


# ---------------------------------------------------------------- reading and writing


def load(root: Path) -> dict | None:
    """The saved share, or None when the owner has not set one (or the file cannot be read)."""
    p = path(root)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not _shape_ok(data.get("share")):
        return None
    s = data["share"]
    s["api_for"] = [k for k in KINDS if k in s["api_for"]]  # always in the one order of the kinds
    return s


def unreadable(root: Path) -> bool:
    return path(root).exists() and load(root) is None


def newer_format(root: Path) -> bool:
    """The file is a later share format this Usage does not know: never overwrite it."""
    try:
        data = json.loads(path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    sch = data.get("schema") if isinstance(data, dict) else None
    return isinstance(sch, str) and sch.startswith("orch.usage-share/") and sch != SCHEMA


def _write(root: Path, s: dict | None) -> None:
    d = store.usage_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    if s is None:
        path(root).unlink(missing_ok=True)
        return
    body = json.dumps({"schema": SCHEMA, "share": s}, indent=1, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".share.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path(root))
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply(root: Path, who: str, changes: dict | None, preset: str | None = None, clear: bool = False) -> dict:
    """Change the share and write one history line. `changes` holds only the fields the person set.
    Returns {"share": new or None, "changed": bool}. Refused (nothing written) when it contradicts itself."""
    with store._lock(root):
        if newer_format(root):
            raise Refused("The share was saved by a newer orch. Update orch, then change it again.")
        old = load(root)
        if clear:
            new = None
        else:
            if preset is not None:
                if preset not in PRESETS:
                    raise Refused(f"There is no ready-made spread called '{preset}'. Use save, even or sub.")
                base = copy.deepcopy(PRESETS[preset]["share"])
            else:
                base = copy.deepcopy(old) if old else copy.deepcopy(PRESETS["even"]["share"])
            changes = dict(changes or {})
            # dollars a day belong to "API credit": choosing Codex or nothing without naming dollars sets them to 0;
            # choosing API credit again without naming dollars brings back a day limit that is not 0
            if "when_ahead" in changes and "day_dollars" not in changes:
                if changes["when_ahead"] in ("codex", "none"):
                    changes["day_dollars"] = 0
                elif base["day_dollars"] <= 0:
                    changes["day_dollars"] = PRESETS["even"]["share"]["day_dollars"]
            base.update(changes)
            if "api_for" in changes:
                base["api_for"] = [k for k in KINDS if k in base["api_for"]]
            if not _shape_ok(base):
                raise Refused("That share cannot be saved. Run `orch usage share` to see it, then try again.")
            bad = problems(base)
            if bad:
                raise Refused(" ".join(bad))
            new = base
        if new == old:
            return {"share": old, "changed": False}
        _write(root, new)
        store._append_history(root, [history_line(who, old, new, preset)])
        return {"share": new, "changed": True}


# ---------------------------------------------------------------- words


def kinds_words(kinds: list[str]) -> str:
    names = [KIND_WORDS[k] for k in KINDS if k in kinds]
    return _and(names) if names else "no kind of work"


def _and(items: list[str], last: str = "and") -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def one_in_words(n: int) -> str:
    return "no" if n == 0 else "all" if n == 1 else f"one in {n}"


def day_word(day: str) -> str:
    return day.capitalize()


def money(v: float) -> str:
    return f"${v:g}"


def _chain(labels: list[str]) -> str:
    return " (" + ", then ".join(labels) + ")" if len(labels) > 1 else (f" ({labels[0]})" if labels else "")


def sentence(s: dict | None, accounts: list[dict] | None = None) -> str:
    """The share as one plain sentence. With the accounts, it names them in the order Usage uses them."""
    if s is None:
        return "No share set: helpers use the accounts in their order, one after the other."
    accounts = [a for a in (accounts or []) if a.get("on", True)]
    subs = [a["label"] for a in accounts if a.get("type") == "subscription"]
    apis = [a["label"] for a in accounts if a.get("type") == "api-key"]
    api_part = (
        f"run {kinds_words(s['api_for'])} on API credit{_chain(apis)}" if s["api_for"] else "run nothing on API credit"
    )
    codex_part = f"{one_in_words(s['codex_one_in'])} Code tickets on Codex"
    text = (
        f"Use the subscriptions first{_chain(subs)}, up to {s['week_pct']} % of their week by {day_word(s['by_day'])}; "
        f"{api_part} and {codex_part}; "
    )
    if s["when_ahead"] == "none" or s["week_pct"] == MAX_PCT:
        text += "new starts stay on the subscriptions even when one is ahead of that pace."
    elif s["when_ahead"] == "codex":
        text += "when a subscription is ahead of that pace, send new starts to Codex."
    else:
        text += (
            f"when a subscription is ahead of that pace, send new starts to {AHEAD_WORDS[s['when_ahead']]} "
            f"for up to {money(s['day_dollars'])} a day."
        )
    return text


def counts(s: dict | None, resets: dict[str, str] | None = None) -> list[str]:
    """What each number counts and when it starts again. `resets`: subscription label -> its week's reset words."""
    if s is None:
        return []
    day_no = DAYS.index(s["by_day"]) + 1
    resets_part = ""
    if resets:
        resets_part = " (" + "; ".join(f"{k}: {v}" for k, v in resets.items()) + ")"
    out = [
        f"{s['week_pct']} % counts how much of a subscription's week is used. By {day_word(s['by_day'])} means after "
        f"{day_no} of the 7 days of that subscription's own week; each week starts again at its own reset{resets_part}."
    ]
    if s["codex_one_in"] > 1:
        out.append(
            f"One in {s['codex_one_in']} counts helper starts of Code tickets: every {s['codex_one_in']}th Code start "
            "goes to Codex. The count starts again every day at midnight, this computer's time."
        )
    elif s["codex_one_in"] == 1:
        out.append("All Code ticket starts go to Codex.")
    if s["when_ahead"] in ("api", "both") and s["week_pct"] < MAX_PCT:
        out.append(
            f"{money(s['day_dollars'])} a day counts dollars spent on API credit for new starts while a subscription "
            "is ahead of its pace. The day starts again at midnight, this computer's time."
        )
    return out


def _part_words(field: str, s: dict) -> str:
    if field in ("week_pct", "by_day"):
        return f"up to {s['week_pct']} % of the week by {day_word(s['by_day'])}"
    if field == "api_for":
        return f"{kinds_words(s['api_for'])} on API credit"
    if field == "codex_one_in":
        return f"{one_in_words(s['codex_one_in'])} Code tickets on Codex"
    if s["when_ahead"] in ("api", "both"):
        return f"when ahead: {AHEAD_WORDS[s['when_ahead']]} up to {money(s['day_dollars'])} a day"
    if s["when_ahead"] == "none":
        return "when ahead: stay on the subscriptions"
    return f"when ahead: {AHEAD_WORDS[s['when_ahead']]}"


def history_line(who: str, old: dict | None, new: dict | None, preset: str | None = None) -> dict:
    if new is None:
        what = "share removed; helpers use the accounts in their order"
    elif old is None and preset:
        what = f"{PRESETS[preset]['name']}: {sentence(new)}"
    elif old is None:
        what = sentence(new)
    else:
        groups = [("week_pct", "by_day"), ("api_for",), ("codex_one_in",), ("when_ahead", "day_dollars")]
        parts = [
            f"{_part_words(g[0], new)} (was {_part_words(g[0], old)})"
            for g in groups
            if any(old[f] != new[f] for f in g)
        ]
        what = "; ".join(parts)
        if preset:
            what = f"{PRESETS[preset]['name']}: {what}"
    return {
        "at": store.now(),
        "who": who,
        "what": what,
        "account": ACCOUNT,
        "label": LABEL,
        "before": old,
        "after": new,
    }


def preset_of(s: dict | None) -> str | None:
    for key, p in PRESETS.items():
        if s == p["share"]:
            return key
    return None


def warnings(s: dict | None, accounts: list[dict]) -> list[str]:
    """Parts of the share that have no account to go to yet (not a contradiction: they wait for one)."""
    if s is None:
        return []
    on = [a for a in accounts if a.get("on", True)]
    out = []
    has_api = any(a.get("type") == "api-key" for a in on)
    has_codex = any(a.get("type") == "helper-tool" and "codex" in a.get("label", "").lower() for a in on)
    if not has_api and (s["api_for"] or s["when_ahead"] in ("api", "both")):
        out.append(
            "No API credit is on in Usage yet. Until one is, work set for API credit stays on the subscriptions."
        )
    if not has_codex and (s["codex_one_in"] > 0 or s["when_ahead"] in ("codex", "both")):
        out.append("Codex is not on in Usage yet. Until it is, work set for Codex stays on the subscriptions.")
    return out


def week_resets(rows: list[dict]) -> dict[str, str]:
    """Subscription label -> when its week starts again, in this computer's time ('Wed 20:59')."""
    out = {}
    for r in rows:
        if r.get("type") != "subscription" or not r.get("on", True):
            continue
        at = ((r.get("use") or {}).get("week") or {}).get("resets_at")
        if not at:
            continue
        try:
            when = datetime.fromisoformat(str(at).replace("Z", "+00:00")).astimezone()
        except ValueError:
            continue
        out[r["label"]] = when.strftime("%a %H:%M")
    return out


def view(root: Path, rows: list[dict]) -> dict:
    """The share read back for the command and the page: the sentence, what each number counts, open points,
    the order of the accounts and the ready-made spreads. `rows`: accounts with their use (cli.gather)."""
    s = load(root)
    notes = warnings(s, rows)
    if unreadable(root):
        notes.insert(0, "The share file .orch/addons/usage/share.json could not be read; the next change replaces it.")
    return {
        "share": s,
        "preset": preset_of(s),
        "sentence": sentence(s, rows),
        "counts": counts(s, week_resets(rows)),
        "warnings": notes,
        "problems": problems(s) if s else [],
        "order": [r["label"] for r in rows],
        "presets": [{"id": k, "name": p["name"], "what": p["what"], "share": p["share"]} for k, p in PRESETS.items()],
        "kinds": [{"id": k, "label": KIND_WORDS[k]} for k in KINDS],
        "days": list(DAYS),
    }

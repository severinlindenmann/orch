"""The workspace look: one icon and one colour (contracts/look.md, vectors/look-v1.json).

Kept in `.orch/config.toml` [workspace] icon, color, pushed to every connected service (relay, publish) with
`PATCH /v1/me`. Applied at once, never pending. Who chose it ("agent" | "human", look.md `look_set_by`) is
kept
per machine in the orch home, keyed by the workspace path, like `permissions`: an agent that edits config.toml
cannot fake "agent" to unlock a person's pick. The caller (agent or person) comes from the environment, never
from a request field.
"""

from __future__ import annotations

import difflib
import json
import unicodedata
from pathlib import Path

from orch import config, net
from orch.errors import Refused

SERVICES = ("relay", "publish")
UNSET = object()

with (Path(__file__).with_name("look.json")).open(encoding="utf-8") as _f:
    DATA = json.load(_f)
ICON_IDS = [i["id"] for i in DATA["icons"]]
COLOR_IDS = [c["id"] for c in DATA["colors"]]


def listing() -> dict:
    """`orch look list --json`: {categories, icons, colors} as in look.json."""
    return {k: DATA[k] for k in ("categories", "icons", "colors")}


# ---- default (Automatic colour and letter), frozen in look-v1


def clean(name: str) -> str:
    return unicodedata.normalize("NFC", name).strip()  # str.strip() trims Unicode White_Space


def djb2_32(name: str) -> int:
    h = 5381
    for b in clean(name).encode("utf-8"):
        h = (h * 33 + b) & 0xFFFFFFFF
    return h


def default_color(name: str) -> str:
    return COLOR_IDS[djb2_32(name) % len(COLOR_IDS)]


def default_letter(name: str) -> str:
    for ch in clean(name):
        if unicodedata.category(ch)[0] in "LN":
            up = ch.upper()
            return up if len(up) == 1 else ch
    return "?"


# ---- what this workspace has


def read(root: Path) -> dict:
    """{icon, color, set_by}; a value not in look.json (hand edit) is ignored."""
    try:
        ws = config.read(root).get("workspace") or {}
    except Refused:
        ws = {}
    icon, color, by = ws.get("icon"), ws.get("color"), _set_by(root)
    return {
        "icon": icon if icon in ICON_IDS else None,
        "color": color if color in COLOR_IDS else None,
        "set_by": by if by in ("agent", "human") else None,
    }


def _by_file() -> Path:
    from orch import addons

    return addons.home() / "look-set-by.json"


def _set_by(root: Path) -> str | None:
    v = net.read_json(_by_file(), {})
    v = v.get(config._perm_key(root)) if isinstance(v, dict) else None
    return v if v in ("agent", "human") else None


def _save_set_by(root: Path, value: str) -> None:
    doc = net.read_json(_by_file(), {})
    doc = doc if isinstance(doc, dict) else {}
    doc[config._perm_key(root)] = value
    net.write_json(_by_file(), doc, private=False)


def _check(kind: str, value, allowed: list[str]) -> None:
    if value is None or value in allowed:
        return
    near = difflib.get_close_matches(str(value), allowed, n=4, cutoff=0.5)
    hint = f" Closest: {', '.join(near)}." if near else ""
    raise Refused(f"'{value}' is not an {kind} orch knows.{hint} See them all: orch look list")


def _write(root: Path, icon, color, set_by) -> None:
    config.set_key(root, "workspace", "icon", icon)
    config.set_key(root, "workspace", "color", color)
    config.set_key(root, "workspace", "look_set_by", None)  # never kept in the workspace (see top)
    _save_set_by(root, set_by)


def set_look(root: Path, icon=UNSET, color=UNSET, by: str = "human:owner", push: bool = True) -> dict:
    """Save the look here and send it on. `icon`/`color` left out = unchanged, None = back to the default.
    `by` is the actor ("agent:<tool>" or "human:<name>").
    Returns {icon, color, set_by, sent: {service: ok}}."""
    if icon is UNSET and color is UNSET:
        raise Refused("Say what to change: --icon or --color.")
    _check("icon", None if icon is UNSET else icon, ICON_IDS)
    _check("colour", None if color is UNSET else color, COLOR_IDS)
    cur = read(root)
    agent = by.startswith("agent:")
    if agent and cur["set_by"] == "human":
        raise Refused("The person chose this icon. Ask them to change it in the dashboard.")
    new = {
        "icon": cur["icon"] if icon is UNSET else icon,
        "color": cur["color"] if color is UNSET else color,
        "set_by": "agent" if agent else "human",
    }
    _write(root, new["icon"], new["color"], new["set_by"])
    return {**new, "sent": push_all(root) if push else {}}


# ---- sending it to the services


def _state_path(root: Path) -> Path:
    return root / ".orch" / "run" / "look-push.json"


def connected(root: Path) -> list[str]:
    return [s for s in SERVICES if (net.secrets_dir(root) / f"{s}.json").is_file()]


def _mark(root: Path, service: str, ok: bool) -> None:
    st = net.read_json(_state_path(root), {})
    st = st if isinstance(st, dict) else {}
    st[service] = "sent" if ok else "not yet sent"
    net.write_json(_state_path(root), st)


def push(root: Path, service: str) -> bool:
    """PATCH /v1/me {icon, color} to one service. False (and remembered as 'not yet sent') when it failed."""
    look = read(root)
    try:
        cfg = net.load_service(root, service)
        net.call_json(
            "PATCH",
            cfg["url"] + "/v1/me",
            net.auth_headers(cfg),
            {"icon": look["icon"], "color": look["color"]},
            timeout=30,
        )
        ok = True
    except Refused:
        ok = False
    _mark(root, service, ok)
    return ok


def push_all(root: Path) -> dict[str, bool]:
    return {s: push(root, s) for s in connected(root)}


def on_connect(root: Path, service: str, who: dict | None) -> None:
    """After `connect`: take over a look an admin set before (only when ours is empty), then send ours.
    Never fails the connect."""
    if service not in SERVICES:
        return
    try:
        mine = read(root)
        who = who if isinstance(who, dict) else {}
        if (
            mine["icon"] is None
            and mine["color"] is None
            and who.get("look_by") == "admin"
            and (who.get("icon") in ICON_IDS or who.get("color") in COLOR_IDS)
        ):
            icon = who.get("icon") if who.get("icon") in ICON_IDS else None
            color = who.get("color") if who.get("color") in COLOR_IDS else None
            _write(root, icon, color, "human")  # the admin is the owner: an agent may not replace it
        push(root, service)
    except Exception:  # a look must never break connecting
        _mark(root, service, False)


def show(root: Path) -> dict:
    """This workspace's look and what each connected service has."""
    out = read(root)
    st = net.read_json(_state_path(root), {})
    services = {}
    for s in connected(root):
        try:
            cfg = net.load_service(root, s)
            _, who = net.call_json("GET", cfg["url"] + "/v1/whoami", net.auth_headers(cfg), timeout=15)
            who = who if isinstance(who, dict) else {}
            services[s] = {k: who.get(k) for k in ("icon", "color", "look_by")}
        except Refused as e:
            services[s] = {"error": str(e)}
        if isinstance(st, dict) and st.get(s):
            services[s]["push"] = st[s]
    out["services"] = services
    return out


def _shared_file() -> Path:
    from orch import addons

    return addons.home() / "shared-pages.json"


def shared_pages(root: Path) -> bool:
    """Show the workspace name and icon on shared file pages (default on). Kept per machine, like the lock."""
    doc = net.read_json(_shared_file(), {})
    v = doc.get(config._perm_key(root)) if isinstance(doc, dict) else None
    return v if isinstance(v, bool) else True


def set_shared_pages(root: Path, on, by: str = "human:owner") -> bool:
    """Publish: show the workspace name and icon on shared file pages. Only a person (the signed-in dashboard
    session or a terminal) may change it, either way; an agent is refused. The caller never comes from a
    request field."""
    if by.startswith("agent:"):
        raise Refused("Only a person can change this. Ask them to switch it in the dashboard.")
    if not isinstance(on, bool):
        raise Refused("Choose on or off.")
    if "publish" in connected(root):
        cfg = net.load_service(root, "publish")
        net.call_json(
            "PATCH", cfg["url"] + "/v1/me", net.auth_headers(cfg), {"show_on_shared_pages": on}, timeout=30
        )
    doc = net.read_json(_shared_file(), {})
    doc = doc if isinstance(doc, dict) else {}
    doc[config._perm_key(root)] = on
    net.write_json(_shared_file(), doc)
    return on

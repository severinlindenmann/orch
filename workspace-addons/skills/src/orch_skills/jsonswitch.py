"""A helper tool's per-folder switches in a JSON settings file (format "json" in agents/switches.json).

A switch is a path in the file and either a map (`map_value`: {"<name>": "<map_value>"}) or a list of entries
(`entry`: a template with {server_id}, or the item's own full path). orch adds only entries it records
(switches.owned) and removes only those; the rest of the file stays.
"""

from __future__ import annotations

from pathlib import Path

from . import switches
from .switches import Refused


def _dig(doc, path: list[str]):
    for k in path:
        doc = doc.get(k) if isinstance(doc, dict) else None
    return doc


def entries(settings: dict, spec: dict) -> list[str]:
    got = _dig(settings, spec["path"])
    if "map_value" in spec:
        return sorted(k for k, v in got.items() if v == spec["map_value"]) if isinstance(got, dict) else []
    return [e for e in got if isinstance(e, str)] if isinstance(got, list) else []


def state(root: Path, name: str, tool: dict) -> dict[str, dict[str, str]]:
    """{switch kind: {entry: "orch" | "hand"}} of what is off in this tool's file here (read only, never raises).
    A recorded entry that is no longer in the file does not count: a line written by hand later stays "hand"."""
    fs = tool["switches"]
    kinds = [k for k in ("skill", "service", "rules") if isinstance(fs.get(k), dict)]
    try:
        settings, _ = switches._read(root, Path(fs["file"]))
    except Refused:
        return {k: {} for k in kinds}
    return {
        k: {e: ("orch" if e in switches.owned(root, name, k) else "hand") for e in entries(settings, fs[k])}
        for k in kinds
    }


def set_entry(root: Path, name: str, tool: dict, kind: str, entry: str, on: bool) -> bool:
    """Off: add orch's entry (and record it). On: remove it only when orch wrote it. True when it changed."""
    fs = tool["switches"]
    spec = fs.get(kind)
    rel = Path(fs["file"])
    if not isinstance(spec, dict) or not entry or len(entry) > 4096:
        raise Refused("That is not something orch can turn off here.")
    with switches._locked(root):
        settings, raw = switches._read(root, rel)
        for k in ("skill", "service", "rules"):  # a recorded line somebody removed: forget it
            if isinstance(fs.get(k), dict):
                rec, have = switches.owned(root, name, k), entries(settings, fs[k])
                if [e for e in rec if e not in have]:
                    switches.set_owned(root, name, k, [e for e in rec if e in have])
        mine = switches.owned(root, name, kind)
        now = entries(settings, spec)
        present = entry in now
        if on:
            if not present:
                return False
            if entry not in mine:
                raise Refused(f"It was turned off by hand in {rel}; orch leaves that alone. Remove the line there.")
            _change(settings, spec, entry, add=False, rel=rel)
            switches._write(root, rel, settings, expect=raw)  # the line goes first; its record after
            switches.set_owned(root, name, kind, [e for e in mine if e != entry])
            return True
        if present:
            return False
        switches.set_owned(root, name, kind, [*mine, entry])  # the record first: a crash leaves no orphan line
        _change(settings, spec, entry, add=True, rel=rel)
        try:
            switches._write(root, rel, settings, expect=raw)
        except Refused:  # not written: take the record back, so a line someone adds now stays theirs
            switches.set_owned(root, name, kind, mine)
            raise
    return True


def _change(settings: dict, spec: dict, entry: str, add: bool, rel: Path) -> None:
    *up, last = spec["path"]
    chain = [settings]
    for k in up:
        nxt = chain[-1].get(k)
        if nxt is None and add:
            nxt = chain[-1][k] = {}
        if not isinstance(nxt, dict):
            if not add and nxt is None:
                return
            raise Refused(f"{k} in {rel} is not an object. Fix it first.")
        chain.append(nxt)
    parent = chain[-1]
    want = dict if "map_value" in spec else list
    box = parent.get(last)
    if box is None:
        if not add:
            return
        box = parent[last] = want()
    if not isinstance(box, want):
        raise Refused(f"{last} in {rel} is not {'an object' if want is dict else 'a list'}. Fix it first.")
    if add:
        if want is dict:
            box[entry] = spec["map_value"]
        else:
            box.append(entry)
        return
    if want is dict:
        box.pop(entry, None)
    else:
        box[:] = [x for x in box if x != entry]
    if not box:  # take away containers orch's entry left empty
        parent.pop(last)
        for k, holder in zip(reversed(up), reversed(chain[:-1]), strict=True):
            if holder[k]:
                break
            holder.pop(k)


def render(spec: dict, server: str = "", file: str = "") -> str:
    """The entry of one item: the template with {server_id}, or the file's full path."""
    if "entry" in spec:
        return spec["entry"].replace("{server_id}", switches.safe_id(server))
    return file

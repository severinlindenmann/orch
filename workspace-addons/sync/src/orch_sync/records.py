"""Plain decision records. What a person decided about sync (choices incl. covers, checked files, allowed
deletions, allowed and ignored add-on values) is kept in run/sync/ as small entries bound to their kind and
target (what it is about: remote commit + path, ticket + add-on + value hash, ...). Readers take an entry only
when it names exactly what they are about to use it for. Old entries that still carry mac or pin fields load
as before: those fields are ignored."""

import uuid


def make(root, kind, target, fields):
    """An entry: `fields` plus kind, target and id."""
    return {**fields, "kind": kind, "target": target, "id": uuid.uuid4().hex}


def ok(root, kind, target, entry):
    """True when `entry` is a record of `kind` about exactly `target`. Never raises."""
    if not isinstance(entry, dict):
        return False
    return entry.get("kind") == kind and entry.get("target") == target and isinstance(entry.get("id"), str)

"""Signed decision records (contracts/human-proof.md "Action records"). Everything sync keeps in run/sync/ about a
person's decision (choices incl. covers, checked files, allowed deletions, approved and ignored add-on values)
is writable by any agent of the same user. So each entry is the core's action1 record: bound to its kind and
target (what it is about: remote commit + path, ticket + add-on + value hash, ...), with a random id, and
MAC'd with this workspace's key right after the CLI's gate (a person's proof where the decision needs one).
Readers take an entry only when it verifies for exactly what they are about to use it for; a single-use
entry also only while its id is not spent (spent in the guarded home, so planting it back never works).
An entry that does not verify counts for nothing (fail closed)."""

from orch import humanproof

from . import repo


def _target(kind, target):
    return f"sync-record:{kind}:{target}"


def make(root, kind, target, fields):
    """A signed entry: `fields` plus kind, target, id and mac. Refused when it cannot be signed (no key):
    the decision is not saved then."""
    body = {**fields, "kind": kind, "target": target, "id": humanproof.new_action_id()}
    mac = humanproof.action_sign(root, _target(kind, target), body)
    if not mac:
        raise repo.Refused("orch could not sign this decision; nothing was changed")
    return {**body, "mac": mac}


def ok(root, kind, target, entry, *, single_use=False):
    """True when `entry` is this core's signed record of `kind` about exactly `target` (and, single use, its id
    is not spent). Never raises."""
    if not isinstance(entry, dict):
        return False
    body = {k: v for k, v in entry.items() if k != "mac"}
    if body.get("kind") != kind or body.get("target") != target or not isinstance(body.get("id"), str):
        return False
    if not humanproof.action_is_human(root, _target(kind, target), body, entry.get("mac")):
        return False
    return not (single_use and humanproof.action_spent(root, body["id"]))


def spend(root, entry):
    """Use a single-use record up. Refused when that cannot be recorded (the caller must not apply it)."""
    if not humanproof.action_spend(root, [entry.get("id")]):
        raise repo.Refused("orch could not record this decision as used; nothing was changed")

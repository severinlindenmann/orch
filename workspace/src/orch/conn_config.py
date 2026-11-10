"""Effective connection recipes, projected only from the names-only inventory."""

from orch import humanproof, inventory


def no_grants(root, orch_home) -> dict:
    """Placeholder until the proof-backed grant store is wired."""
    return {}


def proof_grants(root, orch_home=None) -> dict:
    """Proof-made conn.allow grants from the guarded record (fail closed); orch_home is unused."""
    return humanproof.conn_grants(root)


def resolve(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split by precedence without mutating inputs; unproven sources are workspace."""
    entries = [
        {**item, "source": item["source"] if item["source"] in inventory.ORDER else "workspace"}
        for item in items
    ]
    entries.sort(key=lambda item: (item["name"], inventory.ORDER.index(item["source"])))
    winners, shadowed, sources = [], [], {}
    for item in entries:
        name = item["name"]
        if name not in sources:
            sources[name] = item["source"]
            winners.append(item)
        else:
            shadowed.append({**item, "shadowed_by": sources[name]})
    shadowed.sort(key=lambda item: (item["name"], item["source"]))
    return winners, shadowed


def effective(root, *, orch_home=None, account_home=None, grants=proof_grants) -> dict:
    """Return winner and shadowed recipe references, never launch commands or values."""
    items, also = inventory.connections(root, orch_home=orch_home, account_home=account_home, grants=grants)
    recipes = []
    for item in items:
        recipe = {
            key: item[key]
            for key in (
                "name",
                "source",
                "transport",
                "command",
                "host",
                "profile",
                "version",
                "allow_all",
                "state",
            )
        }
        if item.get("label"):
            recipe["label"] = item["label"]
        recipe["allowed_actions"] = sorted(a["name"] for a in item["actions"] if a["allowed"])
        recipe["recipe_ref"] = f"{item['source']}/{item['name']}@{item['version'][7:23]}"
        recipes.append(recipe)
    winners, shadowed = resolve(recipes)
    for item in winners:
        item["also_from"] = list(also.get(item["name"], []))
    return {"schema": "orch.conn-config/1", "connections": winners, "shadowed": shadowed}

"""Which stop items cannot be undone, derived by Factory from a fixed action list (not from the agent's own tag).

The agent still tags each item (routine / taste / cant-undo), but a tag can only be raised here, never lowered: an item
of the ship stage, or one whose words name an action from ACTIONS, is "cant-undo" whatever the agent wrote: autopilot
never decides it (always the person's). A stop that under-tags an ACTIONS item is refused (the agent re-files it).
Only raising: a false match costs one person's decision, a miss could let autopilot do something final."""

import re

# Actions whose effect leaves this workspace or destroys data: sending, publishing, paying, deleting, deploying.
ACTIONS = re.compile(
    r"\b("
    r"send|sends|sending|sent|e-?mail (?:it|them|the|to|out)|mail out|"
    r"publish|publishes|publishing|published|post (?:it |them |this )?(?:to|on)|tweet|"
    r"deploy|deploys|deploying|deployed|go live|goes live|launch|"
    r"delete|deletes|deleting|deleted|erase|wipe|purge|overwrite|"
    r"pay|pays|paying|payment|charge|refund|purchase|buy|transfer money|"
    r"merge (?:in)?to (?:main|master|production)|push to (?:main|master|production)|force[- ]push|"
    r"revoke|rotate (?:the )?(?:[a-z]+ )?(?:key|keys|secret|secrets|token|tokens|password)|"
    r"cancel (?:the )?(?:subscription|account|contract)|sign (?:the )?contract"
    r")\b",
    re.IGNORECASE,
)


def derived_tag(item, stage):
    """The tag Factory uses: cant-undo when the ship stage or an action from ACTIONS says so, else the agent's tag."""
    if stage == "ship" or ACTIONS.search(str(item.get("title") or "")):
        return "cant-undo"
    return item.get("tag")


def under_tagged(stop):
    """Titles of items whose words name an action from ACTIONS but are not tagged cant-undo (re-filed as cant-undo).
    The ship stage needs no tag: it is always the person's decision anyway."""
    return [
        i["title"]
        for i in stop["items"]
        if ACTIONS.search(str(i.get("title") or "")) and i["tag"] != "cant-undo"
    ]

---
name: orch-insights
description: Use when a person asks which skills, connections or keys the agents used, which ones fail or were never used, or what is shared with the admin. Insights is a read-only page over the workspace counts. Not for changing keys, connections or skills, and not for live work on one ticket (that is Focus).
---
# orch insights

Insights shows, for the last 30 days, how often skills, connections and keys were used and where they failed.
It only reads `orch record counts --json`. It never changes anything and never shows key values.

## When to use
- The user asks which skills, connections or keys are used, unused or failing.
- You are asked where to look before removing or fixing one of them.

## Recipes

**Open the page** (the user, or you when asked)

    orch insights open              # starts the page if needed and opens it
    orch insights open --no-open    # only print the address
    orch insights status            # is it running, and where?
    orch insights stop

**See the numbers without the page**

    orch record counts --days 30 --json

## Rules
- Read only: you do not need to feed Insights, and it cannot change anything.
- Numbers are counts with denominators ("5 of 23 runs"). "Can't tell yet" is not zero.
- Never copy key values anywhere; Insights has none.

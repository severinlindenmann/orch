---
name: orch-insights
description: Use when a person asks what the agents used, which skills, connections or keys are used or fail. Insights is a read-only page over the workspace counts; you do not need to feed it.
---
# orch insights

Insights shows, for the last 30 days, how often skills, connections and keys were used and where they failed.
It only reads `orch record counts --json`. It never changes anything and never shows key values.

## When to use
- The user asks which skills, connections or keys are used, unused or failing: open it with `orch insights open`.

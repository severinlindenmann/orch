---
name: orch-focus
description: Use when a person wants to watch helpers work live, answer their questions as they come, or send one a message while it works. Focus is the live page of every helper session in the dashboard; your part is to keep the ticket current. Not for a list of all tickets (that is the dashboard's ticket list).
---
# orch focus

Focus is the live page of every helper session, in the dashboard: a wall of the sessions, a bar under every page and
a layer that opens one, two or three sessions side by side with their screen, chat and earlier sessions. It starts,
messages and stops helpers only through `orch run start|send|stop`.

## When to use
- The user asks to watch, follow or steer a ticket live.
- You are the helper on a ticket someone may be watching: keep it current so the page is right.

## Recipes

**Open Focus on a ticket** (the user, or you when asked)

    orch focus open <ticket>            # opens that ticket's session in the dashboard; <ticket> = id or key (DM1-12)
    orch focus open <ticket> --no-open  # only print the address

The dashboard starts when it is on but not running. Without the dashboard there is no Focus.

**Keep the ticket current** (every helper; the page is built from this, so every helper looks the same)

    orch check start <ticket> <task>
    orch check done <ticket> <task> --note "what shows it"
    orch ask <ticket> "<question>" --option A --option B --recommend A

**What the person can do in Focus**
- A message to a running helper goes in after the current step; to a stopped helper it is saved for the next run.
- Continue an earlier conversation, or start fresh; answer a waiting question in the session's pane.

**The Manager** (one per workspace): an always-on helper session with the full rights of a normal helper. Nothing
ends it by itself.

    orch manager start [--fresh]    # made the first time, then started live; already on: nothing happens
    orch manager status             # on or off, and the terminal command to join it (orch run attach <id>)
    orch manager stop               # its conversation is kept for the next start

**Sessions without a ticket**: the bar's New menu starts an empty helper, the chat helper, a plain terminal or the
Manager; one of each, a second New goes to the open one. Only when the person asks:

    orch session new <empty|chat|terminal|manager>   # already open: nothing new starts
    orch session list                                # which ones exist and are open
    orch session close <kind>                        # a helper's conversation is kept; the terminal closes

Focus adds one row to `orch needs`: a live helper waiting for the person's OK on its screen.

## Rules
- Do not open Focus yourself unless the user asks.
- Never answer a question or give an OK for the person who is watching.

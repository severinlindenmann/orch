---
name: orch-focus
description: Use when a person wants to watch an agent work on one ticket live, answer its questions as they come, or send it a message while it works. Focus is a live page; your part is to keep the ticket current. Not for a list of all tickets (that is the dashboard).
---
# orch focus

Focus shows one ticket live: its tasks, what the agent is doing, its questions and a message box. The page starts,
messages and stops agents only through `orch run start|send|stop`.

## When to use
- The user asks to watch, follow or steer a ticket live.
- You are the agent on a ticket someone may be watching: keep it current so the page is right.

## Recipes

**Open the page** (the user, or you when asked)

    orch focus open <ticket>        # starts the page if needed and opens it
    orch focus open <ticket> --no-open
    orch focus status               # is it running, and where?
    orch focus stop

`orch focus start` runs the page in the background. Both open and start print the address.

**Keep the ticket current** (every agent; the board is built from this, so every agent looks the same)

    orch check start <ticket> <task>
    orch check done <ticket> <task> --note "what shows it"
    orch ask <ticket> "<question>" --option A --option B --recommend A

**What the person can do in the page**
- A message to a running agent goes in after the current step; to a stopped agent it is saved for the next run.
- Continue the earlier conversation, or start fresh; attach a file to the message.
- A one-shot agent refused a tool: the page asks "Allow and retry / Not now". Allow restarts that run with the tool
  allowed for this run only.

Focus adds rows to `orch needs` only for a live run waiting for an OK and for a refused tool nobody answered yet.
`orch focus view --json` feeds the Live tab of the dashboard.

## Rules
- Do not start Focus yourself unless the user asks.
- Never answer a question or give an OK for the person who is watching.

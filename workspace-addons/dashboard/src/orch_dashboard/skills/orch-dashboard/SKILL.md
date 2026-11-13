---
name: orch-dashboard
description: "{{description}}"
---
# orch dashboard

The dashboard shows your work on one page: tickets (active, waiting, open, done) with steps, proof and questions, and
one tab for every add-on that is turned on and has a page. It follows changes by itself.

- "Needs you" is the inbox. A person answers there or with `orch answer <ticket> <q> <answer>`; the answer shows as
  "Answered - <name> - dashboard".
- Every button is one `orch` command with `--by human:<user>`, never through a shell: answer, create a ticket, edit
  owner/due/note, log, start or stop a run (fresh, take over), start background work, choose the default agent, add
  an agent, turn add-ons on or off. These are the person's own clicks; you never click for them.
- An add-on's page shows what its view says. Its switches and buttons send one fixed verb
  (`orch <add-on> act <verb> -- <ticket>`).
- The ticket page has one agent line (Start, Continue, Start fresh, Stop, Start anyway, Try again). A ticket keeps its
  agent session.
- Proof is marked "You" (the person checked it) or "Helper says"; a missing file reads "on another computer".

## When to use
- The user wants to see the tickets, progress or proof in a browser, or asks for "the dashboard" or "the link".
- The user wants a read-only copy to send to someone.
- Not for changing tickets: use the `orch` commands (see the orch skill).

## Recipes

**Open it**

    orch start               # starts it in the background with the other add-ons and prints the link
    orch dashboard start     # only the dashboard
    orch dashboard status    # is it running, and where?
    orch dashboard stop

`orch dashboard` runs it in the foreground and prints its address (usually 127.0.0.1:8420). The link works on this computer only. Give the
user the printed link.

**A read-only copy**

    orch dashboard snapshot                  # writes dashboard-snapshot.html
    orch dashboard snapshot --with-addons    # include add-on tabs, only when the user asks
{{#publish}}
    orch dashboard snapshot --publish        # shares it as a private link, only when the user asks
{{/publish}}

A snapshot contains ticket titles, steps and history, never settings or the folder path. Make or share one only when
the user asked. Settings changes are logged to `.orch/run/dashboard/actions.log`.

## Rules
- Keep tickets clear: short title, steps with proof, questions with options. The dashboard shows exactly that.
- Never click for a person: answers and approvals in the page are theirs.

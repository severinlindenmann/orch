---
name: orch-dashboard
description: Use when the user wants to see their orch tickets in a browser, or share a read-only view of them. The dashboard only shows; it never changes tickets.
---

# orch dashboard

A light, read-only web page that shows the tickets in `.orch/tickets/` (active, waiting, open, done), the ticket details,
the scheduler (wake-ups and recurring tickets) and the relay inbox.

## Commands
- `orch dashboard` starts it on http://127.0.0.1:8420 (this computer only). Tell the user the link. It follows changes by itself.
- `orch dashboard snapshot` writes one static HTML file `dashboard-snapshot.html` (no inbox).
- `orch dashboard snapshot --publish` publishes that snapshot as a private publish app and prints the link.

## Rules
- You change tickets with the `orch` commands, never through the dashboard: it has no buttons that change data.
- Keep tickets clear: short title, checklist items with evidence, questions with options. The dashboard shows exactly that.
- Do not publish a snapshot unless the user asked for it: it contains ticket titles, checklists and history.

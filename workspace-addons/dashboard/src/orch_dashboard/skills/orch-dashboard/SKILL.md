---
name: orch-dashboard
description: Use when the user wants to see their orch tickets in a browser, or share a read-only view of them. The dashboard only shows; it never changes tickets.
---

# orch dashboard

A light, read-only web page that shows the tickets (active, waiting, open, done), the ticket details, the relay inbox
(only when the relay is set up) and one tab for every add-on that is turned on in this workspace and has a page
(for example Schedule). Add-on tabs and ticket rows appear when the add-on is turned on and go when it is turned off.

## Commands
- `orch start` starts it in the background with the other add-ons and prints the link (this computer only); `orch stop` stops them.
  Tell the user the link. `orch dashboard` runs it in the foreground on http://127.0.0.1:8420. It follows changes by itself.
- `orch dashboard snapshot` writes one static HTML file `dashboard-snapshot.html` (no inbox, no add-on tabs).
- Add `--with-addons` to a snapshot only when the user asks to include add-on tabs and their ticket rows.
- `orch dashboard snapshot --publish` publishes that snapshot as a private publish app and prints the link.

## Rules
- You change tickets with the `orch` commands, never through the dashboard: it has no buttons that change data.
- Keep tickets clear: short title, checklist items with evidence, questions with options. The dashboard shows exactly that.
- Do not publish a snapshot unless the user asked for it: it contains ticket titles, checklists and history.

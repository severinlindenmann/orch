---
name: orch-dashboard-tester
description: Use when the person wants the dashboard checked every day for broken pages, errors, slow pages, cut-off layouts or wrong words, or asks what the daily dashboard look found. It only opens pages and reads; it never clicks. Not for testing your own code changes (use orch shot for pictures).
---
# orch dashboard-tester

Once a day a program opens every dashboard page at 1280, 1920 and 390 px wide, plus the newest working and the newest
Review ticket. It only opens pages and reads them: it never clicks, types or presses anything, so it cannot answer a
card, start, merge, allow or delete. No helper runs and no tokens are spent when nothing is new.

What it finds: page errors, failed requests, empty pages, pages slower than 6 seconds, sideways scrolling at phone
width, buttons cut off at the right edge, words orch must never show, and program values such as null or NaN.
New findings become problem reports kept on this computer (never shared): each big one alone, small ones together,
at most 3 a day. A finding that an open ticket already names is not reported. When the ticket of a report is
finished, the next look checks it again and reports it once more if it is still there.

## Recipes

**Set it up** (only when the person asked for it; downloads a browser of about 100 MB once, unless Chrome is on this computer)

    orch dashboard-tester setup                    # a new ticket, every day at 06:30
    orch dashboard-tester setup --at 07:15 --ticket <id>

It adds the script to automation and a daily repeat on the ticket. A script you add runs only after the person
presses Allow this script on the repeat in the dashboard's Automation tab: tell them so.

**What did it find**

    orch dashboard-tester status

Each look also writes one line on the repeat's ticket. Pictures and page texts of the last look:
`.orch/addons/dashboard-tester/last/`.

**One look now**

    orch dashboard-tester run --dry-run     # looks, reports and keeps nothing

A look signs in to the dashboard with a one-time link that orch makes only for a run a person started (the daily
repeat). Started from a helper it is refused: that is on purpose.

**A helper per release** (optional, costs tokens): `orch dashboard-tester setup --helper-each-release`. When orch's
version changed, the look starts one helper at low priority on the small model that reads the pictures and texts of
the look and reports what a person would stumble over.

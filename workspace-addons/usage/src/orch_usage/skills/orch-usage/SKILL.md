---
name: orch-usage
description: Use when the person asks how far a subscription or API credit is used, which account is in use, whether Usage switches by itself, or asks to change an account's limit, the period it counts over, its order, to turn it on or off, or to make a rule temporary. Usage keeps only labels, numbers, rules and a history, never a login or key. Not for buying, topping up, adding or removing accounts.
---
# orch usage

Every place the helpers can spend is an **Account**: a subscription, an API key or credit. Each account has a rule:
one or two limits (any number, in % or $), the period each counts over (5 hours, week, month or until a date), its
place in the order, on or off, and an optional end. Every change lands in the history with who and when.
The person sees and changes the same on the Usage page of the dashboard; its clicks run these commands.

## When to use
- The person asks how much of a subscription or credit is used, or which account is in use now.
- The person asks to change a limit, a period, the order, to turn an account on or off, or "only until <date>".
- You need to know whether an account still has room before heavy work.

## Recipes

**See the accounts and their use**

    orch usage list
    orch usage history

**Change a rule** (only what the person asked for)

    orch usage limit <account> 70%                 # the weekly limit when it has one limit
    orch usage limit <account> 95% --period 5h     # a subscription has a 5-hour and a weekly limit
    orch usage limit <account> $100 --period month
    orch usage limit <account> none --period 5h    # take a limit away
    orch usage period <account> month --of week
    orch usage order <account> 1                   # first in the order
    orch usage on <account>
    orch usage off <account>

**Temporary rules**: add `--end YYYY-MM-DD` (to the end of that day) to a change, or end the current rule:

    orch usage limit <account> 20% --end 2026-11-20
    orch usage end <account> 2026-11-20
    orch usage end <account> none                  # keep the rule, no end

When a rule ends it falls back to the rule before its last change, and the history says so.

**Switching early** (subscriptions, through the account switcher)

    orch usage status                              # running? switching on or off? the last look
    orch usage switching on                        # only when the person asked for it
    orch usage switching off                       # show and warn only

Usage looks every 30 seconds while it runs (`orch start`). It keeps the first account in order that is under its
limits and would not reach one within 10 minutes at the current pace, and moves on before the limit. Every switch, a
switch it would make while switching is off, and a warning when every account is at or near its limit land in the
history. Switching is off until the person turns it on. Without the account switcher Usage shows and warns only.

An account is named by its label from `orch usage list` (or the start of it). Every command takes `--json`.

## Rules
- Change a rule only when the person asked for that change; never to make room for your own work.
- Never write a login, token, key or address into a label, a ticket or the history.
- Without the account switcher Usage shows and warns only; it never switches.
- Turn switching on or off only when the person asked for it. Never run the account switcher yourself to switch.

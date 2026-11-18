---
name: orch-usage
description: Use when the person asks how far a subscription or API credit is used, which account is in use, whether Usage switches by itself, or asks to change an account's limit, the period it counts over, its order, to turn it on or off, to make a rule temporary, to set one limit over several accounts, which model a kind of work may use, or to add or remove an API credit or helper tool, or to set what is left on an API credit. Usage keeps only labels, names, numbers, rules and a history, never a login or key. Not for buying or topping up credit.
---
# orch usage

Every place the helpers can spend is an **Account**: a subscription, an API key or credit. Each account has a rule:
one or two limits (any number, in % or $), the period each counts over (5 hours, week, month or until a date), its
place in the order, on or off, and an optional end. Every change lands in the history with who and when.
The person sees and changes the same on the Usage page of the dashboard; its clicks run these commands.

## When to use
- The person asks how much of a subscription or credit is used, or which account is in use now.
- The person asks to change a limit, a period, the order, to turn an account on or off, or "only until <date>".
- You need to know whether an account still has room before heavy work, or before a subagent or a credit
  skill spends: `orch usage ask <kind of work>`.

## Recipes

**See the accounts and their use**

    orch usage list
    orch usage history

**Change a rule** (only what the person asked for)

    orch usage limit <account> 70%                 # the weekly limit when it has one limit
    orch usage limit <account> 95% --period 5h     # a subscription has a 5-hour and a weekly limit
    orch usage limit <account> '$100' --period month
    orch usage limit <account> none --period 5h    # take a limit away
    orch usage period <account> month --of week
    orch usage order <account> 1                   # first in the order
    orch usage on <account>
    orch usage off <account>
    orch usage model <account> first               # small model first, the big one only once orch moves it up
    orch usage model <account> small               # the small model only (or: any). A model a person set wins
    orch usage together openai '$100'             # one limit over every OpenAI account together (or: none)

**Add or remove an API credit or helper tool** (only when the person asks; never a key, only the name the credit
skill already uses to find it):

    orch usage add "OpenAI credit" --provider openai --name openai --for reviews --limit '$100' --resets 2026-11-17 --first
    orch usage remove "OpenAI credit"              # kept as removed, never used; its history stays
    orch usage restore "OpenAI credit"             # bring it back with its rule and amount left
                                                   # (a subscription is turned off instead)

**What is left on an API credit** (in dollars; the person reads it at the provider and tells you; never a key).
Write amounts without $ or in single quotes: in a shell an unquoted $74 turns into 4.

    orch usage left "Claude API key 1" 74          # left now; orch keeps the time and counts down from it
    orch usage left "Claude API key 3" 0           # nothing left
    orch usage left "Claude API key 1" none        # take the amount away
    orch usage add "OpenAI credit" --provider openai --name openai --left 100

`orch usage list` then shows `left: $70.50 (set on 2026-11-18, minus $3.50 spent since); spent today $1.20, this
month $3.50`. Setting it again starts the count from the new figure. Every change lands in the history.

**An end for an API credit** (the credit itself stops being used then; not a temporary rule)

    orch usage end "Claude API key 1" 2026-12-01T08:00
    orch usage end "Claude API key 1" none

**After you spent** (a credit skill, after each call; the credit's label or the name the skill uses for it)

    orch usage spent key-1 0.42                    # dollars; --provider openai when two credits share a name

The amount counts down what is left and counts for the credit's $ limits. Report each spend once: a credit whose
skill writes its own spend log is already counted.

**Temporary rules**: add `--end YYYY-MM-DD` (to the end of that day) to a change, or end the current rule:

    orch usage limit <account> 20% --end 2026-11-20
    orch usage order <account> 1 --end 2026-11-13  # first until then, then back to its place before
    orch usage end <account> 2026-11-20
    orch usage end <account> none                  # keep the rule, no end

When a rule ends it falls back to the rule before its last change (and to its place in the order), and the history says so.

**Before you spend** (your own subagent, or a credit skill such as an Anthropic API or OpenAI call)

    orch usage ask reviews                         # a subagent: Lead, Code, Reviews, Builds, Scripts or Helpers
    orch usage ask reviews --provider openai       # a credit skill: only OpenAI credits (or anthropic)

It answers which account to use (its label, and for an API credit the name the credit skill already uses for it,
never a key), "nothing is set" (go ahead as usual), or No room with when it starts again (exit 3). On No room do not
start the work: say so on the ticket and wait. API credits count what their spend log says since the start of the
month (or since their reset day: `orch usage limit <account> '$100' --period month --resets 2026-11-17`). A credit
skill lists the credits it knows the first time it asks; the person changes their rules afterwards like any other.
A credit that is switched off, removed, past its end or has nothing left (what the person set minus what was spent
since) is refused the same way (exit 3, the reason in one sentence); the next credit with room is picked instead.

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

# Factory (add-on, phase 1)

Turn an idea into finished work without setting anything up. You tell your workspace agent what you want — with links,
photos or text, in the dashboard chat, Focus, the phone or any agent tool. The agent writes a small first draft, you polish
it together, and when you say "now plan it" the agent proposes the whole run:

- **the line**: the stages it picked and the stops where it will ask you, with a reason for each;
- **the crew**: who does what and with which tool (Claude, Codex, Copilot …), from what this project has connected;
- **what it needs**: connections, skills, tools — "Everything ready ✓" or what to connect;
- **time and budget**: about how long, by when, and when it needs you;
- **done means / won't do**, and what **Ship** does.

You answer one question: **Start**, **Edit** or **Not now**. Then the crew works alone. You can talk to it any time: small
things it just does and notes (at most 3 changes or 30 minutes in total); anything bigger comes back as a change proposal
with the extra time and the new ETA (**Accept**, **Edit**, **Save for later**). At the last stop you decide **Ship it** or
**Send back**.

Or type it straight into **Start with an idea** on the Factory page in the dashboard: one click saves it as a new order (as
you, not as an agent), starts your agent on the first draft and opens the draft. When the draft is ready it waits under **Drafts waiting
for you**: press **Plan the run** to get the proposal, or **Ask for changes** and write a line about what should change. If that can't be done (for example the
page is open without your dashboard session), your text stays and one more click sends it to your helper in Chat instead.

**Autopilot.** You can also ask the agent to keep improving how you work. It proposes an autopilot for 1, 3 or 7 days with
what it may decide alone (routine and taste items) and its limits. Shipping, scope changes, more budget, new connections,
anything that cannot be undone and other workspaces always come back to you. Every decision it takes alone is logged with
its reason and listed in a daily report. It can never extend its own autopilot.

```sh
$ orch addon add factory --yes
$ orch start                        # starts the Factory watcher: it wakes your agent when you answer
$ orch factory list                 # orders and what waits for you
```

The Factory watcher (started with `orch start`, or `orch factory start`) checks every 20 seconds. When you answer one of
Factory's questions, or a crew task finishes, it starts the agent's run on the order, once per answer and never while a run is
already going. With the watcher off, answers simply wait until it runs (the Factory tab says so).

## Answering on the Factory page
On the Factory tab a decision (Start, Ship it and the other stops) opens the dashboard's own question card in a dialog, so
you answer without leaving the page; the page refreshes when you have answered. The Factory page itself never answers: you
press the option in the card, where orch confirms it is you. Outside the dashboard the button links to the ticket.

## Ask another workspace
At a stop you can ask a connected workspace for its view first: press **Ask another workspace** on the stop (the button
only shows when another workspace is connected to yours). You pick who, and the dialog shows exactly what leaves this
computer: one line about the stop, the items you tick and their pictures. Nothing else goes: no other orders, no crew logs,
no budget, no chat. orch checks the pictures for passwords and keys when the dialog opens; a picture with a hit stays
unticked and nothing is sent until you remove it.

Their answer shows on the stop as "Design says: ..." (or "Design's helper says: ..."). **Add to my comments** copies it,
quoted, so you can paste it into your own comments; it is never sent by itself. An answer is advice: **Ship it** and
**Send back** are always yours, also while you wait, and a late answer is kept as a note. Autopilot never decides a stop you
asked about. If the other workspace is offline the row says Queued and the question goes out when it is back; if it could
not be delivered the row says Failed, with **Send again**. When you answer the stop, the ask is closed.

On the command line: `orch factory ask <order> <stop> <workspace> --item 0 --by human:<name>`.

## Hand one task to another workspace
Now and then another connected workspace is clearly better at one task (for example Design makes the pictures). Then the
proposal says so in one line: "Design makes the header picture · about 40 min", what they get (the brief and the files
listed, each one named) and "Design's time is not counted here". Everything else stays in your workspace. Pressing **Start**
is your click for those files too, so what you see on the proposal is exactly what leaves this computer; a file added later
is not sent. Before anything goes, every file is checked for passwords and keys and nothing is sent if one is found.

On the order page the task shows in plain words: Waiting for Design to start, Waiting for Design to allow, Queued at Design,
Working at Design, Ready for review at Design, Done, Design said no, Failed at Design. Design's person has to allow the task
on their side. When Design says it is done, the result is added to the task and the crew carries on; look at the result before
you rely on it. If nobody picks it up for a day the row offers **Ask Helper to do it here**. If Design says no or fails, your
helper is woken once and proposes **Do it here instead**; only your **Accept** takes the task back, and Design is told "No
longer needed". There is never a second copy without your Accept.

## What protects your decisions
Only your own answers count (the ones you give in the dashboard, Focus, the CLI or on your phone), and
only for questions Factory itself asked about a frozen proposal. A proposal cannot change after Start; more scope is always
a new question. In phase 1 this is enforced by Factory's own commands: an agent running as your user could still start a
ticket directly with `orch run start`. A core check for that is planned.

Contract: `contracts/addons/factory/README.md`. Mockup: the Factory pages of the dashboard mockup (Preview).

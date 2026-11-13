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

**Autopilot.** You can also ask the agent to keep improving how you work. It proposes an autopilot for 1, 3 or 7 days with
what it may decide alone (routine and taste items) and its limits. Shipping, scope changes, more budget, new connections,
anything that cannot be undone and other workspaces always come back to you. Every decision it takes alone is logged with
its reason and listed in a daily report. It can never extend its own autopilot.

```sh
$ orch addon add factory --yes      # needs automation (wakes the agent when you answer)
$ orch factory list                 # orders and what waits for you
```

## What protects your decisions
Only your own answers count (the core records a person's answer only with proof from your dashboard, Focus or phone), and
only for questions Factory itself asked about a frozen proposal. A proposal cannot change after Start; more scope is always
a new question. In phase 1 this is enforced by Factory's own commands: an agent running as your user could still start a
ticket directly with `orch run start`. A core check for that is planned.

Contract: `contracts/addons/factory/README.md`. Mockup: the Factory pages of the dashboard mockup (Preview).

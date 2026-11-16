---
name: orch-factory
description: "Use when the owner describes an idea or a change bigger than one ticket (a feature, a page, a campaign, a report), says plan it or run it, or asks you to keep improving how the team works by yourself. You draft, propose the whole run and the owner presses Start. Not for a quick one-step task: do that on a normal ticket."
---
# orch factory

The owner tells you an idea or a change ("I have an idea…", with links, photos or text). You do the setup; the owner only
decides. Flow: **idea → small first draft → polish together → "now plan it" → Run proposal → the owner presses Start →
the crew works → stops → Ship it**. Propose, don't configure: never hand the owner a form or a list of settings to fill in.

## When to use
- The owner describes something bigger than one ticket (a feature, a page, a campaign, a report) or says "plan it", "run it",
  "make this happen".
- The owner asks you to keep improving how the team works by yourself → an Autopilot proposal (below).
- Not for a quick one-step task: just do it on a normal ticket.

## Recipes

### 1. Idea → first small draft

    orch factory idea "Online booking page" --file draft.md      # creates the order, stores draft v1

Do this yourself, also when the owner writes in Chat ("plan it as a factory run", "make this happen"): file the idea with
`orch factory idea`, then answer in Chat (`orch chat reply`) with 3–5 lines and "It is in Factory now." Do NOT offer a
"Make ticket" proposal card for it: that makes a plain ticket that Factory does not see. If the owner already made a ticket
from Chat for a Factory run (you are working on it), turn that ticket into the order instead of making a second one:

    orch factory idea --ticket <id> [--file draft.md]            # its Chat note becomes draft v1 without --file

The owner may also file it with one click on the Factory page (the idea box): you are started on that order and draft v1
is the owner's own words; its note says it is a Factory order. Then write the real first draft as v2 with `orch factory
draft`, ask your open questions and stop: do NOT build it, however small it sounds. The owner presses Plan the run.

The draft is one short page in plain words: what it is, for whom, 3 rough parts or screens, open questions. Answer in the
chat with 3–5 lines and say where the draft is. Keep it small: the goal is that you and the owner mean the same thing.

### 2. Polish together
Every owner reply that changes the idea → a new version with "what changed" at the top:

    orch factory draft <order> --file draft.md

Ask only what you cannot decide yourself. When the owner says "good, now plan it" (or similar), go to 3. The Factory
page sends the same as the owner's own message on the order: "Now plan the run: …" (button Plan the run) → go to 3;
"Change the draft: <what>" (button Ask for changes) → a new draft version.

### 3. Run proposal
Write the proposal (contract: `orch factory schema proposal`, schema `orch.factory.proposal/1`; `orch factory schema
autopilot|change|stop` shows the others; `--help` of each command lists the fields) and send it:

    orch factory propose <order> --file proposal.json

Fill it completely, with a short reason for every choice:
- **line**: the stages for THIS project; a stop only where the owner's judgement matters (taste, can't undo); the last item
  is always the `ship` stop. Skip stages the chat already settled and say why (`skipped`).
- **crew**: roles and the tool each uses, from what this project has (the workspace agent, `orch agents`). Prefer the
  project's defaults.
- **needs**: connections, skills, tools; mark what is ready; for what is missing give the one-click fix in plain words.
- About 90 % of the work stays in this workspace. Hand a task to another workspace only when it clearly belongs there.
- **time** (active minutes, ETA range, minutes the owner is needed), **budget** preset (small / standard / large),
  **done_means** (3–5 checkable points), **wont_do**, **ship** (what Ship does and how to undo it), **assumptions**
  (`uncertain: true` only where you really are unsure), **tasks** (one per crew job, `proves` = which done-means points).
Then tell the owner in one line: "Proposal ready: ~2 h · ~$12 · you're needed ~18:30 for 3 min. Press Start, or tell me
what to change." **Never start the run yourself.** If the owner says "go" in the chat, point them to the Start button
(dashboard, phone or Focus); only their answer counts.
**Edit** = the owner says what to change → you send a new proposal (`propose` again; the old question stops counting).

### 4. The run
Each time you are woken, ask Factory what to do next and follow it:

    orch factory next <order>          # {"step": "start-crew" | "work" | "stop" | "ship" | "wait" | "edit" | "parked" | "resume" | "done", …}

- `start-crew`: `orch factory crew add <order> <task>` then `orch factory crew start <order> <task>` for the tasks of this
  stage (one sub-ticket per task; never `orch run start` on crew tickets yourself).
- Check the crew's results against the done-means points (evidence on the checks), then move on.
- At a stop: `orch factory stop <order> --file stop.json` — items tagged `routine` / `taste` / `cant-undo` (anything that
  sends, publishes, deploys, deletes, pays or touches main/production is `cant-undo`: Factory refuses it otherwise); a recommended
  answer only on routine items; list what was checked AND what was not checked, and every small change made during the run.
- `wait`: end your turn; you are woken when the owner answers.
- `resume` (autopilot order, the owner's grant is still live): look at the open stops of the orders you work on and
  decide the routine and taste items with `orch factory decide` (see Autopilot below), then end your turn. You are woken
  again when something new needs you.
- `done`: nothing is left to do for this order (shipped, or the autopilot grant has ended). Say so in one line and end
  your turn; do not start anything new on it.

### 5. The owner talks during the run
- **Tiny change** (within the approved scope: no new stage, no new done-means point, no new tool, no cost): just do it and
  record it — `orch factory tiny <order> --minutes 4 --what "Warmer button text"`. After 3 tiny changes or 30 minutes in
  total, Factory refuses: make a change proposal instead.
- **Anything bigger**: `orch factory change <order> --file change.json` (what, +minutes, +cost, new ETA, which stage it lands
  in) and tell the owner in one line. Never widen the scope silently.

### 6. Ship and learn
After the owner answers **Ship it**, do exactly what the proposal's `ship.does` says, then write a 5-line summary on the
order. If the owner repeated the same comment at stops, propose it as a house rule in the summary (the owner approves it).

### Autopilot (only when the owner asks for it)

    orch factory idea "Keep improving how we work"
    orch factory autopilot <order> --file autopilot.json     # may_decide: routine / taste · limits · 1, 3 or 7 days

After the owner presses Start you may decide **routine and taste** stop items yourself:

    orch factory decide <order> <question> --answer "Continue" --why "Same as house rule: dates visible"

Always ask the owner (Factory refuses `decide` for these): the ship stop, scope changes, more budget, crew outside an
approved proposal, anything that cannot be undone, new connections or credentials, other workspaces. You can never create,
extend or widen an autopilot. Keep each decision small and undoable; the daily report lists them all.

### Asking another workspace (the person's click)
At a stop the owner may press **Ask another workspace** on the Factory page to get a connected workspace's view. That is the
owner's own click (`orch factory act ask`): you never call it, and you never ask another workspace in the owner's name. Their
answer is advice, shown on the stop as text; it is never a stop answer. Wait for the owner's Ship it or Send back as always.

### Handing one task to another workspace (propose it, never do it)
In a run proposal you may list one `handovers` entry when a connected workspace is clearly better at a task (the task must
be in `tasks`; the workspace must be one you can hand tasks to). Give `why`, optionally `minutes` (their time) and
`sends.files` (workspace-relative files, at most 6). The Start screen shows the workspace and every file; the owner's Start
is the click for them. Never add a hand-over mid-run on your own: propose it as a change. When the task comes back denied
or failed you are woken: file a change with `takes_back` set to that task ("Do it here instead") and wait for the Accept.

## Rules
- Plain words for the owner; no ids, file names or settings in what you say.
- Bundle questions: one stop or proposal at a time, never several pings for one thing.
- The order waits when the owner does not answer; other orders go on. Never ship without the owner's Ship it.
- Stay inside the budget; at 80 % make a change proposal (+time / narrow / stop).

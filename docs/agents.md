# Agents

orch works with the agent tool you already use. It does not care which one: Claude, Codex, or any command you can type.
You pick one agent for the project. When orch starts work on a ticket, it starts that agent.

## Pick an agent

`orch init` looks for Claude and Codex on your computer and asks which one to use. Not found? Pick "Other" and give a command.
You can change it any time.

```sh
$ orch agents
$ orch config get workspace.agent
```

## Use any other agent

An agent is a command. `{prompt}` is where orch puts the task.

```sh
$ orch config agent add my-agent --command "my-agent {prompt}"
$ orch config set workspace.agent my-agent
$ orch agents
```

If the tool reads the task from standard input, add `--prompt-via stdin`. If it can also run as a live session,
add `--interactive "my-agent"`.

**What a generic agent does not get.** Every run starts fresh: it does not continue the earlier conversation.
You see no live steps, and no helper, usage or permission lines. The tasks it ticks off and the questions it asks still
show up everywhere, because it talks to orch through the same `orch` commands as every other agent.

## What the agent may do without asking

```sh
$ orch config get workspace.permissions        # ask, auto (default) or full
$ orch config set workspace.permissions ask
```

`ask`: the agent asks before it edits files or runs commands. `auto`: it works on its own and the tool checks risky
steps. `full`: it never asks. An agent orch has no setting for ignores this. It applies the next time an agent starts.

Codex has no way to ask while orch runs it, so every mode starts it with write access to this folder only (no network,
no other folders), never wider; if your own Codex config says read-only, that stays and orch says so at the start.
orch refuses to start an agent when its home folder (`ORCH_HOME`, `~/.orch-tool`) is inside the start folder or under
the temp folder: the agent could then change orch's own settings.

Live sessions close by themselves after an hour of waiting (or an hour after the ticket is Done); Continue picks the
conversation up again. Change the hour: `orch config set workspace.live_idle_minutes 120`.

## Start, watch and stop work

```sh
$ orch ticket new "Fix the invoice export"
$ orch check add <id> "Export the file"
$ orch run start <id>
$ orch run status <id>
$ orch run attach <id>  # skip
$ orch run stop <id>
```

- `run start` starts the chosen agent on the ticket. Only one agent works on a ticket at a time. If one is busy, your text is
  queued and goes in when it is ready. `--agent <name>` uses another agent for this run.
- `run attach` shows the agent's live screen (a tmux session). `--watch` only watches. Detach with Ctrl+B then D; the agent keeps working.
- `run stop` stops it. The work done so far stays on the ticket.
- Add-ons (automation, Focus, the phone) start work through the same `orch run start`, so there is never a second agent on a ticket.

## Sessions: Continue or Start fresh

orch remembers the agent's conversation for each ticket. The next start **continues** it. To begin again from the ticket
(tasks, proof, summary) without the old conversation:

```sh
$ orch run start <id> --fresh
```

If the conversation cannot be continued (another agent, another computer, session gone), orch starts fresh and says so.

## tmux is optional

A live session needs [tmux](https://github.com/tmux/tmux). Without it, or for agents that cannot run live, `run start` runs the
task once and stops when the agent exits. Everything else works the same.
On a Mac: `brew install tmux`. Without it you see the agent's steps in Focus (`orch focus open <id>`) or in its output
file (`.orch/run/logs/<id>-<run>.log`); `orch run attach` says so instead of opening a screen.

## A live agent that waits before it starts

Some tools ask a question the first time they open a folder (Claude asks whether to trust it). orch answers the trust
question in the tool's own settings before a live start. If the tool still shows a screen that waits for a person, the run
shows that question, not "working": open the live session with `orch run attach <id>` and answer it.

Every agent run may use the `orch` command itself, so it can add tasks, tick them and write the summary.

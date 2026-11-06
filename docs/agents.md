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

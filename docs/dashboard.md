# Dashboard

One page on your own computer with all your tickets and what needs you. It is optional and read from the same files as the `orch` command.

![Home](images/dashboard-home.png)

```sh
$ orch addon add dashboard --yes
$ orch start
$ orch status
$ orch stop
```

`orch status` prints the address (this computer only, usually `http://127.0.0.1:8420`).

- **Home:** Needs you first (questions, failed runs), then your tickets, then which agents are working.
- **Ticket page:** tasks with proof, questions, history, owner and due day, and a Continue or Start button for the agent.
  Your clicks count as you; an agent's changes count as the agent.
- **Add-ons:** each add-on you turn on gets its own tab (automation, publish's Shared tab, relay messages).

![A ticket](images/dashboard-ticket.png)

The board has six columns: Backlog, Ready, Working, Waiting, Review, and Done. Done initially shows three tickets. Review cards offer **Mark done** and **Send back**. An agent's activity appears separately on its ticket; Start moves the card to Working immediately.

Settings ends with **Workflow → Agents may mark tickets Done**, off by default. Browser actions are recorded as a person, including when an agent started the dashboard.

**References** holds tickets, web addresses, project files, and artifacts. Project text and image previews use stored references and the core's safe file reader. Files outside the project say **On this computer only** and remain text. Shared snapshots keep references but do not open files or artifacts.

The live dashboard listens on `/api/events` for changes, with a 20-second fallback refresh while connected and a 3-second refresh while disconnected. Shared snapshots make no requests.

## Mobile mode

A switch "Mobile mode" sits top right (it shows only when the relay add-on is on). The first click opens a short question first
(questions also go to your phone, the computer stays awake, a closed laptop lid still sleeps; "Don't ask again" is a browser
preference). While it is on, a bar on every page says so, with the start and end time and a Turn off button; if the computer could
not be kept awake the bar says so. Settings > General > Mobile mode picks the auto-off time (4, 8, 12 or 24 hours, default 12).
After a restart or an automatic end a one-line notice stays until you press OK. The dashboard only calls
`orch relay mobile on|off|hours|ack|status --json`; the mode itself lives in `.orch/run/mobile-mode.json`, not in the browser.

![Mobile mode on](images/dashboard-mobile-mode.png)

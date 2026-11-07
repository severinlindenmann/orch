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

## Mobile mode

A switch "Mobile mode" sits top right (it shows only when the relay add-on is on). The first click opens a short question first
(questions also go to your phone, the computer stays awake, a closed laptop lid still sleeps; "Don't ask again" is a browser
preference). While it is on, a bar on every page says so, with the start and end time and a Turn off button; if the computer could
not be kept awake the bar says so. Settings > General > Mobile mode picks the auto-off time (4, 8, 12 or 24 hours, default 12).
After a restart or an automatic end a one-line notice stays until you press OK. The dashboard only calls
`orch relay mobile on|off|hours|ack|status --json`; the mode itself lives in `.orch/run/mobile-mode.json`, not in the browser.

![Mobile mode on](images/dashboard-mobile-mode.png)

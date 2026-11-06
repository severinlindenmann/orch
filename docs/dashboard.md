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

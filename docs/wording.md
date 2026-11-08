# Wording: one set of words

Owner pick for X-13: **option b**. The UI says **Ticket** and **Task**; the CLI and the files say `ticket` and `check`.
The same thing has the same name on the dashboard, in Focus, on the phone and on the publish and relay pages.
`brand/tests/test_wording.py` fails when a "never use" word is added to a UI string file.

| Thing | UI word (dashboard, Focus, phone, portals) | CLI / files | Never use in the UI |
|---|---|---|---|
| one unit of work | Ticket | `ticket`, `t_...` | Request, Job, Issue |
| checklist item of a ticket | Task | `check`, `c1` | Todo, Subtask |
| child of a ticket | Sub-ticket | `ticket` (parent) | Epic, Subtask |
| status of a ticket not started | Backlog (status chip; the button that shows a ticket stays "Open") | `open` | Open (as a status) |
| list of things for the person | Needs you | `orch needs` | Over to you, Inbox |
| question with options | Question / Your answer | `question`, `q1` | Approval, Sign-off |
| the suggested option | Suggested | `recommended` | Recommended |
| proof on a task | Proof | `evidence` | Evidence, Artifact |
| repeating work | Repeats | `ext.scheduler` | Scheduler, Cron, Schedule |
| an AI tool working | its adapter label (Claude, Codex, ...) | `agent:<tool>` | Bot |
| the person | You / first name | `human:<name>` | Human |
| where it was done | dashboard, phone, terminal | `via` | CLI |
| another workspace | its name (landing-site) | `ws_...` | Peer, Node |
| private network | private network (VPN) | - | NetBird (any product name) |

Rules
- Words are the same in sentences: "Needs you (2)", "Answered Yes · Marco · phone", "Proof on this task".
- The agent's own text (what it writes in a ticket) is not rewritten. Only words that orch itself puts on screen follow the table.
- Add a word here first, then in the UI; the test list is in `brand/tests/test_wording.py`.

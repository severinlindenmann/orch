# Wording: one set of words

Owner pick for X-13: **option b**. The UI says **Ticket** and **Task**; the CLI and the files say `ticket` and `check`.
The same thing has the same name on the dashboard, in Focus, on the phone and on the publish and relay pages.
`brand/tests/test_wording.py` fails when a "never use" word is added to a UI string file.

| Thing | UI word (dashboard, Focus, phone, portals) | CLI / files | Never use in the UI |
|---|---|---|---|
| one unit of work | Ticket | `ticket`, `t_...` | Request, Job, Issue |
| checklist item of a ticket | Task | `check`, `c1` | Todo, Subtask |
| child of a ticket | Sub-ticket | `ticket` (parent) | Subtask |
| a ticket made with tickets inside it (owner, ORCH-14) | Epic | `ticket new --epic`, `epic` | Subtask |
| status of a ticket not started | Backlog (status chip; the button that shows a ticket stays "Open") | `open` | Open (as a status) |
| list of things for the person | Needs you | `orch needs` | Over to you, Inbox |
| a person looking at a helper's finished result (owner, ORCH-2140) | Review (status, lane, page); "Result to review" (row), "Test results" (button, ORCH-2172), "I review the result" (switch) | `review` status, `orch needs` | Check (for this step), Check result, Result to check, Human review needed |
| open tickets that need nobody (Home, `orch counts`; owner, ORCH-2140) | In progress (started: a task done, a helper on it, or worked on before) / Not started (saved, nobody on it yet) | `in_progress`, `not_started` | Quiet, Idle, Pending |
| question with options | Question / Your answer | `question`, `q1` | Approval, Sign-off |
| a click that decides for the person (a sync address, which version to keep) | Confirm / Needs your OK / Confirmed | `sign` (the click), `seen` | Sign, Signed, Signature, signed, signature ("Sign in" for the page login stays) |
| a question the helper withdrew | Taken back: <reason> | `--take-back`, `taken_back` | Cancelled, Deleted, Withdrawn |
| the task a question belongs to, on its card | About: <task text> | `--check c1` | Regarding, Subject |
| the suggested option | Suggested | `recommended` | Recommended |
| how much attention a Review card needs (owner, 26 Nov, ORCH-2184) | Quick look / Short decision / Take your time (tiles over the lanes); a round of up to 5 ends on What you decided | `attention.group` quick, short, time; `orch review list --group` | Decide (as a group name), about N min |
| the panel beside a Review card (owner, 26 Nov, ORCH-2185) | Ticket / Chat / What the helper does (tabs; "Terminal" only when the plain terminal's typing setting is on); in the card's More: Ask about this, Watch the helper | `#review?ticket=<id>&tab=chat\|helper` | Session, Open the session, Remind me |
| put a Review card off (owner, 26 Nov) | Later (one button; the choices under it are times only) | - | Remind me |
| sort a list of ideas on Review (owner, 26 Nov, ORCH-2186) | Keep / Later / No per idea; Save (Save, N left for later) | `orch ask --idea`, `ideas`, `left_from` | Approve, Reject, Maybe, Remind me |
| evidence on a task | Evidence | `evidence` | Proof, Artifact |
| repeating work | Repeats | `ext.scheduler` | Scheduler, Cron, Schedule |
| an AI tool working | its adapter label (Claude, Codex, ...) | `agent:<tool>` | Bot, Agent, Agents (the screen word is helper; add-on texts are word-checked too) |
| the person | You / first name | `human:<name>` | Human |
| where it was done | dashboard, phone, terminal | `via` | CLI |
| another workspace | its name (landing-site) | `ws_...` | Peer, Node |
| stop all automation | Pause automation / Paused | `orch pause`, `orch resume` | Stop all, Kill switch, Disable |
| outside item | its tool's name + its own word ("GitHub issue", "Jira issue") | web reference | "Issue" alone |
| the add-on that turns an idea into finished work, step by step (owner D3 B, 26 Nov, ORCH-2284) | Factory (menu, page, Home, Settings) | `orch factory` | Projects |
| something a helper learned here | Lesson (list: Lessons) | `orch lessons`, `l_...` | Memory, Tip |
| a tool's way in that a helper needs (owner, ORCH-43) | Login / Connection / Key (caption under each name) | - | Token, Credential |
| the add-on for messages between workspaces and phones (owner, ORCH-2166, RP8 B) | Relay | `orch relay` | Contacts, Phone link |
| the add-on that shares files by private link (owner, ORCH-2166, RP8 B) | Publish | `orch publish` | Shared, Shared pages, Shared links (as its name; "Share a file" as an action is fine) |
| list of every login, connection and key (Settings, Helper tab; owner, ORCH-43) | What helpers need | - | Logins and keys, Helper access |
| a site's sign-in kept for helpers (ORCH-1845, design) | Keep me signed in / Signed in / Sign-in ended / Forget sign-in | `orch browse signin forget <site>` | Profile, Session, Vault, Cookies, Remember me |
| one script in Personal that reaches one source on the person's own computer (Teams, Mail, a folder; owner, ORCH-605/ORCH-649) | Way in ("Teams: the way in stopped working") | - | Connector, Integration, Plugin |
| a login, connection or key that is fine | Works | - | Working well |
| a login that ends in a few days | Runs out soon · <date> | - | Expires, Ends in |
| a login that stopped working | Needs renewing | - | Expired, Login ended |
| a connection that does not answer | Cannot be reached | - | Offline, Not answering |
| start a new login for a tool | Renew (button) | - | Re-authenticate, Log in again |
| swap a key for a new one | Replace (button) | - | Renew key, Rotate |
| look at a connection or login again | Try again (connection) / Check again (after a renew done by hand) | - | Retry |
| Home warning when several stopped | <n> things stopped working · See what to fix | - | <n> problems |
| the place a key is typed in | Key entry | - | Safe key entry, Vault |
| private network | private network (VPN) | - | NetBird (any product name) |
| the card for a ticket's result to look at (owner, 26 Nov, ORCH-2178) | Test results | `test_results` | Check result |

Rules
- Words are the same in sentences: "Needs you (2)", "Answered Yes · Marco · phone", "Evidence on this task".
- The agent's own text (what it writes in a ticket) is not rewritten. Only words that orch itself puts on screen follow the table.
- Add a word here first, then in the UI; the test list is in `brand/tests/test_wording.py`.

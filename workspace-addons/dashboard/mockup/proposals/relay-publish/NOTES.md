# relay and publish drafts (lane relay-publish, 25 Nov)

Visual drafts for a non-developer who turns on the two optional add-ons: connect the workspace, write to another
workspace, hand over a task, add a phone, share a file by link, and what the screens say when the connection is gone.
Nothing here is built. The owner answers each one on the decision page (lane `relay-publish`); only accepted drafts
get a build ticket, and the build PR moves the accepted screen into the matching mockup page (`relay/`, `publish/`,
`settings/`, `home/`) and deletes its draft here.

Every page is the real dashboard shell of a sample workspace (taken on develop 7208bcbb5 with two test workspaces,
Marketing and Sales, on local test servers) with only the main area drafted. Styles come from the master
(`workspace/src/orch_ui/static`) and the dashboard's own sheets by relative path; no page-local style. Open them from
a static server rooted at the repo, or `orch shot <file>`. The "Now" pictures are screenshots of the real product from
the same walk; they are on the ticket, not in git. `rp8-words-now` and `rp9-cli-now` are the only "Now" pages here,
because words and terminal text have no screen of their own (`rp9-cli-now` shortens one line of today's output that
names the workspace key).

The menu still says "Contacts" and "Shared" on every draft except RP8: the names are their own decision.

| Problem today | Draft (recommended first) | Alternative |
|---|---|---|
| RP1 Turning Contacts on ends in "1. Phone link · Not set up" with a one-line field; the admin's text has six lines; after connecting nobody says whose step is next | `rp1-connect-b`, `rp1-connect-b2` two steps with whose turn it is; `rp1-connect-error` | `rp1-connect-a` one paste box |
| RP2 Turning Shared on shows an empty page; connecting works only in the terminal | `rp2-shared-connect-a` paste box on the Shared page | - |
| RP3 A first message says "sent" and then waits unseen until the other side accepts a 32-character fingerprint on the Contacts page | `rp3-accept-b`, `rp3-accept-b-home` no accept step when the admin connected the two | `rp3-accept-a`, `rp3-accept-a-sender` keep the step, on Home, in plain words |
| RP4 The card for a task from another workspace hides the task's text and says a helper asked | `rp4-task-a` three plain buttons | `rp4-task-b` two buttons and a switch |
| RP5 Messages are a flat log with no state; offline shows a banner but not which message waits | `rp5-thread-a`, `rp5-thread-a-phone` one conversation per contact | `rp5-list-b` same list, a state on every row |
| RP6 "Phones are paired on your phone link's admin page", a page the person cannot open | `rp6-phone-b` plain steps, the admin still adds it | `rp6-phone-a` add it yourself with a code (new feature) |
| RP7 Shared rows show no note and no ticket; with the server away the page waits about 20 s and lists nothing | `rp7-shared-a`, `rp7-shared-offline` | - |
| RP8 One thing has up to four names | `rp8-words-a` Contacts and Shared links | `rp8-words-b` Relay and Publish; `rp8-words-c` Workspaces and Shared links |
| RP9 Command line: "Next: orch addon list" after turning on, the same "carry on" line after everything, "Connected" while the server is down | `rp9-cli-a` | - |

What the challenge changed (Opus, as IT engineer, business manager, marketing person): RP1 the paste box became step 1
of the list, the phone left the step count, "Check again" became automatic, error states were added; RP3 B lost the
code box and "Block" (the admin sets pairs) and gained the message on Home; RP4 no longer claims "not your files" and
names no ticket number before the allow; RP5 says "Sent" and "Waiting for Sales" only (states the server reports
today), got its own phone-width page, and "Hand over a task" became "Hand over a ticket"; RP6 B dropped "Last seen"
and sending the code, A is marked as a new feature for a security look; RP7 says truthfully what the password check
does and greys out what cannot work offline; RP8 errors name the feature instead of two new server nouns, and C was
added; RP9 no longer points to another command or says "2 clicks".

Needs a contract first when accepted: a state sent back for a handed-over task (allowed, working, done) beyond
"waiting" and the answer message; the admin page listing workspaces that wait to be connected.

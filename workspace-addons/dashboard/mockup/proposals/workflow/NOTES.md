# workflow drafts (ORCH-2140, 25 Nov)

Visual drafts for the workspace workflow: write a ticket → a helper works → it asks → the person answers → review → done.
Nothing here is built. The owner answers each one on the decision page (lane `workspace-workflow`); only accepted
drafts get a build ticket, and the build PR moves the accepted screen into the matching mockup page
(`home/`, `ticket/`) and deletes its draft here.

Every page is the real dashboard markup of a sample workspace (taken on develop 8a1623b0) with only the drafted part
changed. Styles come from the master (`workspace/src/orch_ui/static`) and the dashboard's own sheets by relative
path; no page-local style. Open them from a static server rooted at the repo, or `orch shot <file>`.

| Problem | Now | Draft A (recommended) | Draft B |
|---|---|---|---|
| W1 Home hides work in progress | `w1-home-now` | `w1-home-a` In progress and Not started lists | `w1-home-b` four numbers |
| W2 A saved ticket is a dead end with no helper | `w2-saved-now` | `w2-saved-b` two ways to start | `w2-saved-a` one Set up a helper button |
| W3 The question is said three times | `w3-question-now` | `w3-question-a` one card | `w3-question-b` answer in the header |
| W4 The result to review is spread over three boxes | `w4-result-now` | `w4-result-a` one card with the buttons | `w4-result-b` asked / got |
| W5 Mixed words for the review step | `w5-words-now` | `w5-words-a`, `w5-words-a2` Review | `w5-words-b` Check |
| W6 CLI next-step lines | `w6-cli-now` | `w6-cli-a` | - |

What the challenge changed (Opus, as IT engineer, business manager, marketing person): W1 says truthfully "No helper
is on it right now" and caps the list; W2 dropped the unmeasured "2 minutes" and says where the pasted line works;
W3's line after the answer is true with and without a running helper; W4 shows the result file first and opens
Send back under the buttons; W5 shows the status pill and the switch too; W6 never prefills a person's answer and
uses the existing `orch ticket changes` for send back.

## What and why

ORCH-1852. New ticket page: the request text and a usable Save now sit side by side (Save right under the text on a phone); run options (helper, due date, plan, review, done when, parts, files) come after. A line under the request explains Save / prepare / Start per state; Start stays explicit, below, with its cost named ("uses its time and usage"). With no helper there is a single filled **Save**, no Start, no Helper choice, and the line says the ticket waits until a helper is added. Cmd/Ctrl+Enter saves (never starts). Mockup `board/new.html` updated incl. a "No helper" preview pill (`?helper=none`). Prepare logic untouched.

Before (no helper→ Save at y=1171 of 844 on a phone, 905 of 800 on desktop; now 563 / 373):

![before 390](./.pr/before-390.png)
![before 1440](./.pr/before-1440.png)
![after 390 no helper](./.pr/after-390.png)
![after 1440 no helper](./.pr/after-1440.png)

(Before/after are the mockup board/new at 390x844 and 1440x800; the "after" pictures show the no-helper state. 1280/1920 checked too: Save at y=373 in the first screen.)

## Rules (AGENTS.md)

- Rules touched: R4.2, R6.1-R6.3, R7.1-R7.3, R7.6
- New noun the user must learn? no
- Crosses the machine boundary (relay, publish, phone)? no
- Breaks a rule? no
- Decision log entry needed? no
- UI change: master library + gallery + mockup updated? yes: mockup + master mockup.css; uses existing `btn primary/outline`, no new component
- Dashboard click-through? yes, `new-ticket.cjs` extended (Save beside/under the request in first screen, cost line)
- UX checklist: Save/Start flow, empty/no-helper state, focus in request, 44px targets, shots at 1280/1920/390 taken; automatic checks green. Full manual 61-item pass not recorded.

## Evidence

- `node --test workspace-addons/dashboard/tests/*.test.js`: 1218 passed (new unit tests: no helper, helper, Cmd+Enter, retry keeps Save usable and text, restored text, focus in request)
- `pytest brand/tests tests/test_newticket_ui.py` (dashboard): 456 passed; style/css/wording subset 13 passed
- `node clickthrough/run.cjs --only new-ticket,new-ticket-epic-files,b-steps` (stand-in fake agent): 3/3; `new-ticket` also at 390x844 and 1280x900: passed

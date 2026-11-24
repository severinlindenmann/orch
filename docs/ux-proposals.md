# Seven dashboard drafts worth trying

**Owner recommendation, 24 November 2026 · ORCH-1842.** Start with New ticket and the ticket handover. A person should be able to leave a one-sentence request and come back tomorrow knowing whether anybody is working on it. Both problems showed up with four tickets, before adding a single optional dashboard tab. None of these proposals needs a new workflow object.

## Ranked experiments

The names in parentheses identify the `f60-ux-<name>.md` builder jobs. The last column is a test for the draft, not a measured user-study result.

| Priority | Before | After | How the owner can tell |
|---|---|---|---|
| 1. Capture a request (`ticket-intake`) | With no helper configured, New ticket asks about files, parts, date, plan and review. The save action is outside the first viewport at **both** widths. | Put a usable save beside the request. Keep the options available and distinguish saving, preparation and a paid start. | Marketing: type one sentence on a phone, save once without scrolling, find exactly one ticket. |
| 2. Trust the handover (`ticket-handoff`) | A lunch ticket says no helper is working; below it, “Claude · Book the table” and a task labelled “Working”. Two steps already have evidence, yet empty Results appears before Progress. | Distinguish the last marked step from a live run. Lead with what remains and what is known, not an empty result. Keep the underlying task mark. | IT: distinguish running, stopped and unknown from the first screen. A stopped helper need not mean the ticket is finished. |
| 3. Recover sign-in (`sign-in-recovery`) | The **live** Welcome screen asks for a token and tells a phone user to run a command on the workspace computer. | Keep token entry for those who have one. Explain who can provide a private link or token, including after an expired link. No new way to authenticate. | Manager: without a terminal, identify whom to ask and what to request in 20 seconds. |
| 4. Answer one question (`answer-one-question`) | Home offers Tuesday or Thursday directly. Review shows Waiting 1, 1 waiting and 1 of 1, then the choices and “Pick one”. | For an ordinary choice, let the named answer act directly. Keep Undo, history and the many-card deck; consequential actions keep their own behavior. | Manager: answer Thursday in one tap, see it on the ticket, and undo without recording a second answer. |
| 5. Read a finished result (`finished-outcomes`) | The sales report appears in Finished and What changed. Only the latter says sales rose 8%. Both are visible on desktop; the outcome falls below the phone fold. | Show each ticket's result at its first mention, after work that genuinely needs the person. Link to evidence rather than inventing a summary. | Marketing: find what changed without opening the ticket or passing a duplicate; the pending supplier question still comes first. |
| 6. Explain service impact (`service-impact`) | The reference failure offers Restart, Stop and Look into it. The live **sample** Services page is empty: no actual outage was observed. The current service view already knows some dependents when reviewing Stop. | Put the known effect on work beside the failure and the proposed recovery, before the technical log. Say when impact is unknown. | IT and manager: given a disposable failing service, independently identify what it affects and the safest next action. |
| 7. Use a first note (`first-personal-note`) | Empty Personal shows “Add a part” twice, suggests Notes or Calendar, then advertises future Files and Tasks. Neither entry names the task of using a brief. | Offer the existing Notes route directly, then carry one selected note to one ticket. Explain folder access separately from the attachment. Leave the populated page alone. | Marketing: attach a sample brief, verify it on the right ticket and explain what else the helper can read. |

## What the second reader changed

GPT-6.2 Astra and Claude Opus 5.5 independently read the core evidence. Opus moved sign-in above visual cleanup: people who cannot get in never see the rest. We dropped a Tickets redesign: eight filter chips are noisy on a phone, but the first group already contains the waiting ticket and its Answer action. We did **not** treat inconsistent numbers in a populated Review mockup as a product bug. Nor is an unfinished task proof of a stale process: draft 2 must use actual run data.

Opus rejected the Personal finding on the evidence then available: both reference pictures showed a populated page. The later empty-product pair confirmed the duplicated entry point, so it is a lower-ranked, first-use-only draft. Service impact remains a hypothesis pending reproduction. These are walkthroughs from three perspectives, not interviews or timings with users.

## Evidence and limits

The provided dashboard answered on port 63965; its state endpoint required a personal session. No personal sign-in was used. **Only the entry screen was observed on that instance.** The remainder is the real product from `81bdadd23`, running on disposable workspaces seeded with the repository's CI tickets. The second installation matched the live add-on list from `orch addon list`; it did not copy private tickets, accounts or integrations. Results cannot establish what a busy signed-in owner actually sees.

The local sprint evidence directory is `ux-evidence/ORCH-1842/`. Each stem below has a `-390.png` and `-1440.png` picture (390×844 and 1440×800). The full Opus challenge is `opus-challenge.txt` there. Pictures are not in git.

| Source | Pairs | What to inspect |
|---|---:|---|
| `live/` | 1 | `signed-out`. `orch shot` refused the persistent loading marker at both widths. The repository's keychain-safe browser captured the visible login instead. |
| `minimal/` | 6 | `page-home`, `new`, `ticket`, `tickets`, `review`, `settings` (all use `page-`). No optional add-on contributions or helper configured. |
| `sample/` | 39 | Six work pages (Home, Tickets, ticket, New ticket, Review, Chat); six Settings tabs; 13 `page-addon-*` routes and 14 `page-config-*` routes including the dashboard host. Captured with `orch shot`. A route attempt is not necessarily a distinct page. |
| `subpages/` | 13 | Six Personal destinations (parts, notes, meetings, calendar, mail, messages) with `orch shot`. Browser supplement for Board, Calendar, three ticket tabs, Projects Autopilot and settled Insights; `orch shot --page` does not accept query or nested hash selectors. |
| `mockup/` | 5 | Home, Review, ticket-review, Personal and Services references with `orch shot`. Use only for comparison; the board reference did not settle and is not counted. |

**Disposition of the optional pages.** Automation has a clear New repeat; Browser, Lessons and Pull requests explain their empty lists. Live leads with the ticket that needs someone; Chat provides sample starting questions. Projects has an idea field but calls itself Factory in the content. Contacts offers a settings route when disconnected. Backup presents the destinations; Usage shows no account; Insights initially shows skeletons, then the settled budget/usage view. These did not displace the seven drafts. The bare Publish route returned a 404, while its Shared settings page existed without an Open action; this is not evidence of a broken navigation link. The dashboard host's configuration route returned the installed add-ons list. Files and Skills were not installed on the supplied workspace. Account-specific data, active terminals, populated project orders and remote peer/phone states were not exercised.

Each job asks for an independent **draft** ticket and real implementation branch, paired before/after images at both widths, the matching mockup, the UX checklist and a draft PR into `develop`. The owner can accept or decline them independently. Only the planning report is ready for the normal queue.

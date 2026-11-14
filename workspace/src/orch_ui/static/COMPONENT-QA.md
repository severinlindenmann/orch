# Component QA — owner review, 13 Nov

Written before implementation. Scope: every top-level HTML page in the assigned folders, excluding opus-* and standalone file content. Findings are shared root causes; the inventory below records each page and its interactive surface.

## Findings

| ID | Page | What is wrong | Fix |
|---|---|---|---|
| QA-01 | All shell pages | Phone switch changes only its checkmark; no shared pairing state. | Pair before enabling; cancel restores Off; keep demo state across pages. |
| QA-02 | Home, Focus, Ticket, phone | Question implementations disagree; custom answers can select the first suggestion. | Use one question renderer with options, recommended label, validated custom reply and Undo. |
| QA-03 | Focus live pages | Saved answers disable buttons without Undo. | Restore the question and work status when undoing. |
| QA-04 | All dialogs and sheets | Close, Escape, backdrop and focus restoration are implemented separately. | Route all native dialogs through one overlay controller. |
| QA-05 | Full-screen previews and terminal | Full-screen state has no common focus or scroll lifecycle. | Use shared full-screen dialogs with visible Exit full screen and Escape. |
| QA-06 | File viewers | Closing navigates after a separate timer; backdrop and Escape disagree. | One close lifecycle then return to the file collection. |
| QA-07 | Embedded previews | A focused frame can swallow Escape. | Forward Escape from same-origin frames; keep visible exit outside every frame. |
| QA-08 | All overlays | Background scroll is not consistently locked. | Lock until the last overlay closes, then restore previous scroll styling. |
| QA-09 | All overlays | Open and close timings vary. | Use 150 ms entry and 100 ms exit, instant with reduced motion. |
| QA-10 | All selects | Visible native selects have inconsistent styling and keyboard treatment. | Progressively enhance native controls with one styled listbox. |
| QA-11 | Select changes and reset | Custom controls must follow programmatic values, disabled and invalid states. | Synchronize on change, reset, opening and attribute changes. |
| QA-12 | previews/files.html, previews/many.html | Sort, group and type labels do not align; toolbar wraps. | One 36 px row, labels inside triggers, view toggle at right. |
| QA-13 | All menus | Details menus lack a common arrow-key and outside-click contract. | One menu controller with Escape, arrows, Home/End and opener restoration. |
| QA-14 | Tabs | Arrow navigation and roving focus vary between pages. | One tabs controller preserving page-specific panel changes. |
| QA-15 | Segmented controls | Pressed and focus states differ. | Normalize keyboard movement and selection feedback. |
| QA-16 | Switches | On/off state is not consistently announced. | Use native checkbox semantics with switch role and shared focus/disabled styling. |
| QA-17 | board/new.html | Date picker lacks a shared implementation and day keyboard navigation. | Shared calendar with arrows, month navigation, clear and focus return. |
| QA-18 | Toasts | Several independent timers, dismissal patterns and live regions. | One toast with optional Undo, dismiss and paused expiry while focused. |
| QA-19 | Copy link | Success feedback differs and sometimes overwrites buttons. | Shared clipboard action; success only after copy succeeds; useful failure message. |
| QA-20 | Preview pill | State selection not indicated and focus may be outside a modal. | Show current state, keep pill in active dialog, keyboard and safe replay. |
| QA-21 | Loading states | Interactive controls can remain keyboard reachable behind skeletons. | Make loading content inert and announce busy state without moving layout. |
| QA-22 | Entry and hover motion | Transition durations and pressed/focus feedback vary. | Shared short motion, clear focus outline, instant reduced motion. |
| QA-23 | settings phone pairing | Pairing form can close without a meaningful paired result. | Demo pairing confirmation and working phone question preview. |
| QA-24 | Question counts | Answered state must agree with needs-you totals. | Update local counters and restore on Undo. |
| QA-25 | Question forms | Blank or whitespace-only custom replies need an inline error. | Keep form open, explain the error and focus the input. |
| QA-26 | Dynamic ticket sections | Controls added after page load need the same enhancement. | Observe additions and initialize shared components once. |
| QA-27 | system/components.html | No live component gallery in header navigation. | Add Shell · Components · Gallery · Motion navigation. |
| QA-28 | system/gallery.html | No complete live source of truth for component states. | Build clickable examples and default, focus, open, selected, disabled, loading and error demonstrations. |
| QA-29 | Menus inside overlays | Menus and select popovers can compete with modal Escape. | Close the innermost popover first and return focus. |
| QA-30 | Viewer return focus | Direct viewer routes have no in-page opener. | Return to collection with remembered scroll and focused file link; use visible fallback exit. |

## Page inventory

| Page | Buttons | Links | Dialogs | Selects | Details / menus | Inputs | Tabs | Applied findings |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| system/components.html | 41 | 72 | 3 | 3 | 9 | 13 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-27, QA-29 |
| system/motion.html | 22 | 27 | 2 | 0 | 3 | 1 | 1 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-14, QA-15, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| system/shell.html | 0 | 20 | 0 | 0 | 3 | 1 | 0 | QA-01, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| home/home.html | 11 | 37 | 1 | 0 | 3 | 1 | 0 | QA-01, QA-02, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-24, QA-25, QA-29 |
| board/board.html | 23 | 52 | 0 | 1 | 3 | 1 | 0 | QA-01, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| board/list.html | 12 | 47 | 1 | 3 | 3 | 2 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| board/new.html | 19 | 48 | 2 | 4 | 3 | 5 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-17, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| chat/chat-relay.html | 6 | 23 | 1 | 0 | 3 | 2 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| chat/chat.html | 13 | 23 | 1 | 0 | 3 | 2 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| ticket/ticket-change.html | 11 | 24 | 1 | 1 | 3 | 1 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-26, QA-29 |
| ticket/ticket-copy.html | 12 | 22 | 1 | 1 | 3 | 1 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-26, QA-29 |
| ticket/ticket-done.html | 10 | 22 | 1 | 1 | 3 | 1 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-26, QA-29 |
| ticket/ticket-question.html | 11 | 21 | 1 | 1 | 3 | 4 | 0 | QA-01, QA-02, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-24, QA-25, QA-26, QA-29 |
| ticket/ticket-review.html | 14 | 25 | 1 | 1 | 3 | 1 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-26, QA-29 |
| ticket/ticket-working.html | 11 | 25 | 1 | 1 | 3 | 1 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-26, QA-29 |
| focus/focus-help.html | 13 | 41 | 1 | 0 | 3 | 2 | 0 | QA-01, QA-02, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-24, QA-25, QA-29 |
| focus/focus-ticket-fullscreen.html | 18 | 23 | 2 | 0 | 3 | 2 | 0 | QA-01, QA-02, QA-03, QA-04, QA-05, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-24, QA-25, QA-29 |
| focus/focus-ticket-terminal.html | 18 | 23 | 2 | 0 | 3 | 2 | 0 | QA-01, QA-02, QA-03, QA-04, QA-05, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-24, QA-25, QA-29 |
| focus/focus-ticket.html | 18 | 23 | 2 | 0 | 3 | 2 | 0 | QA-01, QA-02, QA-03, QA-04, QA-05, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-24, QA-25, QA-29 |
| focus/focus.html | 12 | 40 | 0 | 0 | 3 | 2 | 0 | QA-01, QA-02, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-24, QA-25, QA-29 |
| insights/insights-settings.html | 4 | 23 | 0 | 2 | 3 | 2 | 0 | QA-01, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| insights/insights.html | 8 | 23 | 0 | 0 | 3 | 1 | 1 | QA-01, QA-13, QA-14, QA-15, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| automation/automation-edit.html | 5 | 23 | 0 | 2 | 3 | 15 | 0 | QA-01, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| automation/automation.html | 6 | 26 | 0 | 0 | 3 | 2 | 0 | QA-01, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| notes/note.html | 5 | 26 | 0 | 0 | 3 | 1 | 0 | QA-01, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| notes/notes.html | 5 | 23 | 0 | 0 | 3 | 1 | 0 | QA-01, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| settings/addon-detail.html | 14 | 23 | 8 | 0 | 3 | 10 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-23, QA-29 |
| settings/settings-addons.html | 55 | 36 | 9 | 0 | 3 | 32 | 1 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-14, QA-15, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-23, QA-29 |
| settings/settings-helper.html | 55 | 36 | 9 | 0 | 3 | 32 | 1 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-14, QA-15, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-23, QA-29 |
| settings/settings-phone-pair.html | 55 | 36 | 9 | 0 | 3 | 32 | 1 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-14, QA-15, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-23, QA-29 |
| settings/settings-phone.html | 55 | 36 | 9 | 0 | 3 | 32 | 1 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-14, QA-15, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-23, QA-29 |
| settings/settings.html | 55 | 36 | 9 | 0 | 3 | 32 | 1 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-14, QA-15, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-23, QA-29 |
| publish/publish.html | 20 | 21 | 8 | 0 | 3 | 6 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| relay/relay.html | 14 | 24 | 8 | 0 | 3 | 6 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| sync/sync.html | 15 | 22 | 8 | 0 | 3 | 9 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| errors/not-found.html | 14 | 24 | 8 | 0 | 3 | 6 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| errors/offline.html | 16 | 20 | 8 | 0 | 3 | 6 | 0 | QA-01, QA-04, QA-07, QA-08, QA-09, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| previews/files.html | 4 | 48 | 0 | 3 | 12 | 2 | 0 | QA-01, QA-10, QA-11, QA-12, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| previews/many.html | 5 | 40 | 0 | 3 | 5 | 2 | 0 | QA-01, QA-10, QA-11, QA-12, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| previews/review-card.html | 3 | 26 | 0 | 0 | 3 | 1 | 0 | QA-01, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |
| previews/viewer-audio.html | 7 | 55 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-code.html | 10 | 55 | 1 | 1 | 15 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-error.html | 7 | 55 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-html.html | 10 | 55 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-image.html | 11 | 71 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-large.html | 7 | 56 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-loading.html | 7 | 55 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-markdown.html | 8 | 55 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-pdf.html | 7 | 55 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-table.html | 16 | 56 | 1 | 1 | 12 | 4 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-text.html | 22 | 55 | 1 | 1 | 12 | 17 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-unknown.html | 7 | 56 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-video.html | 7 | 55 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-xlsx.html | 11 | 55 | 1 | 1 | 12 | 3 | 1 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-14, QA-15, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer-zip.html | 7 | 55 | 1 | 1 | 12 | 2 | 0 | QA-01, QA-04, QA-05, QA-06, QA-07, QA-08, QA-09, QA-10, QA-11, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29, QA-30 |
| previews/viewer.html | 0 | 43 | 0 | 0 | 3 | 1 | 0 | QA-01, QA-13, QA-16, QA-18, QA-19, QA-20, QA-21, QA-22, QA-29 |

New page: `system/gallery.html` implements QA-28 and exercises all shared behaviours above.

## Verification

**30 of 30 shared findings fixed.** Repeated occurrences are listed in the page inventory, not counted as separate bugs.

- 57 pages × loaded/loading/empty = **171 browser checks passed** at 1280 × 800: no script errors, horizontal overflow, missing Preview pills or visible unenhanced selects.
- **144 dialog/viewer checks passed**: visible close, Escape, scroll lock and instant reduced motion.
- **21 targeted interaction checks passed**, covering phone pairing and cancel, synchronized replies, blank-answer validation, custom answer preservation, Undo, full-screen exit, focus return, dropdowns, date keyboard input, tabs and the files toolbar.
- **10 additional checks passed** for backdrop close, scroll unlock, menu arrows/Escape, successful copy feedback, nested select Escape, the many-files toolbar and direct full-screen exit.
- **62 JavaScript sources parsed successfully.**
- Browser screenshots reviewed for Home, the file toolbar and the gallery.

Machine-readable results: `qa-results.json`, `qa-overlays.json`, `qa-interactions.json`, `qa-extra.json`. Tests use the local mockup in Chromium; real phone delivery and workspace mutations remain explicitly labelled demo actions.

Implementation: `overlay.js` is the single native-dialog lifecycle; `select.js` enhances native form selects; `components.js` owns toast, menus, tabs, switches, questions and phone pairing; `date.js` owns calendars. `interaction.css` provides the common motion and interaction states. Existing page action handlers call these shared behaviours; native selects remain the form value source.

The sweep also caught and fixed two missing Preview pills, calendar focus accidentally finding the Preview pill selection, and reduced-motion CSS specificity overriding the instant dialog rule. These are covered by QA-20, QA-17 and QA-09 respectively. Visual review also found a checkbox rule shrinking switches to 16 px; the shared switch rule now keeps a 36 × 24 px track (QA-16).

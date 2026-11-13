# Factory design mockup

Built screens: home, proposal, order, stop, autopilot, draft (phase 2a).

Open `factory.html` directly. Shared assets resolve through `../system/` and `../chat/`, which already exist in this monorepo. No other mockup folders were changed.

`chat-idea.html`, `edit.html`, and `defaults.html` show phase 2b+ (in-page Start via the dashboard question card, chat integration, defaults) and carry a visible **Preview** tag.

These owner-reviewed mockups preserve their local, simulated interactions and sample content. They are a design reference, not the live read-only page. The phase 2a page uses API data, renders draft markdown as plain text, and sends all answers to the dashboard ticket with `target="_top"`. No mockup interaction grants authority or changes real workspace data. Autopilot's live per-day limits are labelled targets, not enforced yet.

Preview controls offer loading and empty states; Reset Factory demo clears only `orch-factory-demo` local storage. The comparison slider and pins here are simulated; live-page pins are view-only.

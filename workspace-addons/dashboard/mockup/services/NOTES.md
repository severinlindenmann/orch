# Services (ORCH-268)

The product tab follows this page since ORCH-326 (see "Built" below). `services.html` is the page the owner picked on 17 Nov
(layout C of three drafts: table, cards by state, list and panel). `services-data.js` holds the demo snapshot and
the preview actions. Use the Preview pill for Loaded, Loading, Empty and Error.

Words: Services; Running, Stopped, Failing; Starts by itself; Start, Stop, Restart, Open log, Remove; Found on this
computer; Manage with orch.

## The page: list and panel

The open question is pinned on top at every width. Below it a slim list (state mark, name, state word, Stop or
Start) and the chosen service's panel with everything shown plainly: buttons, state, the switch, who made it,
health check, what depends on it, the log lines, and Remove at the bottom. On a phone the list comes first, then
the panel with "All services" to go back.

- Best at: one service in full without a sheet over the page; stays calm with 20 services.
- Worst at: two places to act (list button and panel), and Restart and the switch of the other services are hidden
  until you choose them.

## Rules the page keeps

- No "Details" toggles (owner rule kept). The panel shows it all.
- The panel shows, top to bottom: state and since when, Starts by itself with its words ("Yes, after
  this computer restarts" / "Only after a crash, not after this computer restarts"), made by, health check, Depends on it, last log lines,
  and Remove at the bottom, set apart, in the danger style. Open log shows only up to 720 px, where it jumps to the log lines further down the panel; on a wide screen the
  log lines are already in view, so there is no Open log button there (ORCH-935).
- A found service'spanel shows what was found and only Manage with orch. Once managed it reads "Found,
  now managed".
- Button order: Start or Stop, then Restart, then Open log.
- The failing service's question shows once per page with Restart, Stop and Look into it.
- Start, Stop and Restart change the state and show the shared toast (with Undo); Remove opens a small window that
  says what will happen, with Keep it and Remove; Manage with orch moves a found service into the main list.
- The openpanel has an address (`?svc=<service>`), and so has every
  state.
- Checked at 1280, 1920 and 390 wide: no sideways scroll, every control reachable with Tab with a visible focus
  mark, and at 390 the last row clears the bottom bar.

## Gaps in the design kit (nothing was added to the master)

- Page layout rules for a mockup page live in `mockup.css` under a `body.mk-<page>` scope, and no new rules may be
  added now. The page borrows the Automation scope (`body.mk-automation-automation`) for the page spacing, the
  loading mask and the small second line in a row. The build needs its own scope or, better, these few rules in
  the master.
- No status look for a service. Running uses the Done pill colour with a plain green dot (the Done tick would say
  "finished", the Working arc spins all the time); Failing uses the failed pill with the Needs-you mark.
- The shared Preview pill (`state-controls.js`) has no Error button; the page adds one to it with a few lines.
- `UI.state` takes a button with a click handler only; the Empty state's next step is a link ("Chat"), so
  it is appended by hand.
- No master-detail layout. The page uses `.chat-grid` (272 px list + panel) and `.focus-list` rows; on a phone the
  page script swaps list and panel because `.chat-grid` has no phone rule.
- The table has no phone-only label helper for a cell that holds a control; the switch cell relies on the cell's
  `data-label` text.
- No "found, not managed yet" tag; the page uses a neutral pill with the words "Running, not managed".
- The log lines use `.term` (made for the helper terminal); there is no plain "last lines" block.
- On a phone the Preview pill covers the More tab of the bottom bar (same on the other mockup pages).

## Built (ORCH-326, 17 Nov)

The tab is the view block `split` (contracts/addon-view.schema.json) drawn by the dashboard's blocks.js; the add-on
fills it with `orch services view --json`. Where the product differs from this page, and why:

- Kit gaps filled in the master (widgets.css, gallery entry "List and panel"): `.split-view` (272 px list + panel,
  phone: list first, a chosen item shows only its panel with "All services"), `.dot-off` for a stopped service,
  `.log-lines` for plain last lines. The product uses these; this mockup still borrows the Automation scope, `.chat-grid`
  and `.term` (unchanged, it looks the same).
- Stopped shows a hollow dot (`.dot-off`) instead of the To-do status icon: the dashboard swaps every picture inside an
  add-on view for its own icon, so a view block draws dots only.
- The address is `#addon/services?svc=<id>` (the dashboard's hash route) instead of `?svc=<id>`.
- A service's one-line "what it is" under the name shows only when the record has one; the add-on keeps none yet.
  Made by without a ticket or add-on reads "Added by hand".
- The Remove window is the dashboard's shared dialog: same words and buttons, plus its own Close.
- Health check, Depends on it, the failing state and its question show when the add-on sends them (later work).
- `services-data.js` closed its first comment too early, so this page stayed empty; fixed.

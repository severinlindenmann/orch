# Services (ORCH-268, Preview add-on)

Mockup only, nothing is built in the product yet. `services.html` is the page the owner picked on 17 Nov
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
  this computer restarts" / "No, you start it by hand"), made by, health check, Depends on it, last log lines,
  and Remove at the bottom, set apart, in the danger style. Open log jumps to the log lines in the panel.
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

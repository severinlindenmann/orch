# Browser add-on notes (ORCH-1494, watch only)

The owner's pick on ORCH-1341 ("Use A", pinch to zoom on the phone). Kit parts: `UI.browserView`, `UI.browserPeek`,
`.bview-beside` (browser.js / browser.css, gallery "The helper's browser, live"). `browser-sample.js` draws the sample
picture; the product gets the real pictures from the browser add-on's stream.

## browser.html: Browser (add-on nav tab, panel "browser")
- "Live now · N": a card per ticket, its title (a link to the ticket) and its wide small live preview; a click on the
  preview opens the live view in the ticket. "Ended today · N": one line per ticket, a link with "ended at 10:02".
- Empty (`?state=empty`): "No helper is using a browser right now" and one sentence. No Preview tag. Home shows nothing.
- Error (`?state=error`): the list did not load: "The browsers did not load", "The dashboard could not read them just
  now. It tries again on its own." and Try again; the page looks again every 5 s and the list replaces it.
- Off (`?state=off`): the dashboard has the tab but the add-on answers that it is off: "The browser is turned off in
  this workspace", "Turn it on again in Settings, under Add-ons." and Open add-ons.
- The nav icon is the master's `globe`; on a phone More is the current tab (the page sits under More).

## ticket-browser.html: a ticket after a click on its small live preview (`#ticket/<id>?browser=open`)
- The live view sits next to the steps (side by side from a 960 px column, about 1920 wide; on top of the steps below
  that), "Helper is driving", Stop and Hide in its bar, then the picture. On a phone the picture is the real 1280-wide
  page scaled to the width: pinch to zoom.
- The small live preview stays on top of the Activity with the brand edge while the view is open. Before the click
  only the preview shows; an ended browser is one quiet line "The helper's browser ended at 10:02.".
- The same preview sits in the Focus pane (under what the helper does now) and between the ticket chat and its box;
  there it opens the ticket's live view.

## Take over and give back (ORCH-1495, desktop first): ticket-browser.html?state=…
- (none): "Take over" (outline) in the live view's bar. A click: "The helper is finishing its step… Then you are in
  control." with "Stop its step now" (`?state=finishing`), then the view fills the window (`?state=you`): one bar on
  top (at the bottom on a phone) "You are in control. The helper is paused. What you type goes to the site, not to
  orch.", "When you give back, the helper starts on a fresh page and can see what the site itself shows (for example your sign-in or recent searches); orch kept nothing you typed.", "Keys go
  to the site. F6 moves to these buttons.", Give back to the helper (filled), Back to the ticket, Stop browser.
- `?state=back`: still in control, back at the ticket: the same bar in the view with "Full view".
- `?state=paused`: "The helper is paused. Nobody is in control: the page that had it went away…", under it the same
  "When you give back, the helper starts on a fresh page…" line as in control (ORCH-1858), with Give back to the
  helper (filled) and Take over again; Stop browser stays in the line on top.
- `?state=asks`: the helper asked for a person (`orch browse ask-person`): the bar on the needs colour, "The helper
  needs you in its browser." with its words and one Take over; the small preview says "Waiting for you". Home shows
  one line (`../home/home.html?browser=asks`): "The helper needs you in its browser. <words> · <ticket>" with "Open
  the browser".

## Keep a sign-in per site (ORCH-1845, design draft, not built)
Design note: `contracts/addons/browse/signin-design.md`.
- `ticket-browser.html?state=offer`: after Give back, one banner "Keep me signed in on <site>?" with Keep (filled) and Not now
  (outline). Keep turns it into one quiet line "Signed in on <site> is kept." with a Forget sign-in link; Not now closes it.
- `browser.html`: card "Signed-in sites · N" under Live now: a line per site with "Signed in" (or "Sign-in ended" on the needs
  colour, with one sentence under the list) and "Forget sign-in" (one click, the line goes, no typed confirm).
  `?signin=none`: the empty state "No sign-in kept"; it shows too after the last Forget.

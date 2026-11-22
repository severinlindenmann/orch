# Browser add-on notes (ORCH-1494, watch only)

The owner's pick on ORCH-1341 ("Use A", pinch to zoom on the phone). Kit parts: `UI.browserView`, `UI.browserPeek`,
`.bview-beside` (browser.js / browser.css, gallery "The helper's browser, live"). `browser-sample.js` draws the sample
picture; the product gets the real pictures from the browser add-on's stream.

## browser.html: Browser (add-on nav tab, panel "browser")
- "Live now · N": a card per ticket, its title (a link to the ticket) and its wide small live preview; a click on the
  preview opens the live view in the ticket. "Ended today · N": one line per ticket, a link with "ended at 10:02".
- Empty (`?state=empty`): "No helper is using a browser right now" and one sentence. No Preview tag. Home shows nothing.

## ticket-browser.html: a ticket after a click on its small live preview (`#ticket/<id>?browser=open`)
- The live view sits next to the steps (side by side from a 960 px column, about 1920 wide; on top of the steps below
  that), "Helper is driving", Stop and Hide in its bar, then the picture. On a phone the picture is the real 1280-wide
  page scaled to the width: pinch to zoom.
- The small live preview stays on top of the Activity with the brand edge while the view is open. Before the click
  only the preview shows; an ended browser is one quiet line "The helper's browser ended at 10:02.".
- The same preview sits in the Focus pane (under what the helper does now) and between the ticket chat and its box;
  there it opens the ticket's live view.

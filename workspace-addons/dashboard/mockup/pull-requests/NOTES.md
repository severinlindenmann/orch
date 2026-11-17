# Pull requests add-on notes

## pull-requests.html: Pull requests (add-on nav tab)
- Shows the open pull requests of the repositories the tickets link: 3 stats (Open, Checks failed, Ready to merge) and one table per repository (title, "N open", columns Pull request, Ticket, Checks, Merge; branch line under the first cell, "—" where no ticket is linked). Filled by `orch pull-requests view`; sample text is `e2e/fixtures/pull-requests-page.json`. The page is built from the stat and table blocks of `blocks.js`, inside cards.
- States: loaded (default), loading (`?state=loading`), empty (`?state=empty`: stats at 0, "No pull requests yet").
- Not running: no preview state yet (the kit has no CSS for a third state). The real page adds above the stats `<div class="banner attn"><p class="grow">Pull requests are not being read right now, so what you see may be old.</p><button type="button" class="btn outline sm">Start reading</button></div>`; the table stays visible.

# The dashboard as one product: the picked screens (owner, 26 Nov)

The owner's picks from draft #3291 (ORCH-2273), as built in ORCH-2282..2284. Plain HTML on the master design system.

| Decision | Screens | What it shows |
|---|---|---|
| D1 A: one top for every page (ORCH-2282) | `page-top.html` · `page-top-inner.html` | The name and one sentence left; Settings first, then the one filled button. A page inside another page has `← Automation` above its name (`UI.pageTop`, `UI.pageBack`). |
| D2 A: same side menu list, tidied (ORCH-2283); O-34: no menu row edits the list | `menu.html` · `menu-more.html` · `menu-edit.html` (way A) · `menu-inplace.html` (way B) | No pin on the rows; `More (n)` / `Fewer` unfolds the rest in place, Lessons included. "Change this list" is gone. Way A: a quiet `…` beside "Add-ons" (on hover or keyboard) opens Settings › Menu, where each page has a switch, a grip to drag and two arrows. Way B: every menu row is dragged in place and has its own `…` (Move up, Move down, Hide from menu; Show in menu under More). The owner picks one. |
| D3 B: Factory everywhere (ORCH-2284) | `factory.html` · `factory-home.html` | The page, the menu, Home and Settings say Factory; the page says `Needs you` like every other page. |

Open them from a static server rooted at the repo, for example
`http://127.0.0.1:<port>/workspace-addons/dashboard/mockup/one-product/page-top.html`.

# The dashboard as one product: drafts (ORCH-2273)

Draft screens only, on the master design system. Nothing here is built; the owner picks per problem on the decision page
(lane `dashboard`). Each page is plain HTML and can be edited by hand.

| Problem | Pages | Recommended |
|---|---|---|
| D1 The top of every page | `p1-a` `p1-a-sub` · `p1-b` `p1-b-sub` · `p1-c` `p1-c-sub` | A: one top for every page |
| D2 The side menu | `p2-a` `p2-a-open` · `p2-b` · `p2-c` `p2-c-all` | A: same list, tidied |
| D3 One name for one page | `p3-a` `p3-a-home` · `p3-b` `p3-b-home` | A: Projects everywhere |
| D4 A page with nothing in it yet | `p4-a` `p4-a-2` · `p4-b` `p4-b-2` · `p4-c` `p4-c-2` | A: one sentence and the first step |
| D5 When something is wrong | `p5-a` `p5-a-2` `p5-a-3` `p5-a-home` · `p5-b` `p5-b-2` · `p5-c` `p5-c-home` | A: one notice under the name |
| D6 An add-on's settings | `p6-a` `p6-a-settings` · `p6-b` · `p6-c` | A: one Settings button, one place |

Open them from a static server rooted at the repo, for example
`http://127.0.0.1:<port>/workspace-addons/dashboard/mockup/proposals/one-product/p1-a.html`.

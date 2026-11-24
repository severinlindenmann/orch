# Browse: keep a sign-in per site (design note, ORCH-1845)

Status: **design only, not built, waiting for the owner's OK.** Comes from the wish ORCH-1810 (owner picked A on
24 Nov). Rules: R1.4, R5.2, R6.3, R7.1, R9.4 (also R1.3, R1.6, R2.4, R4.2, R4.3, R4.4, R7.3, R7.5, R8.4).
Screens: `workspace-addons/dashboard/mockup/browser/` (`ticket-browser.html?state=offer`, `browser.html`,
`browser.html?signin=none`). Words: `docs/wording.md`.

Goal: a person signs in to a site once by hand (take-over, ORCH-1495; MFA included). Later tickets that list that
site start already signed in. The person decides per site, sees every kept sign-in on one list, and forgets one with
one click.

## The wall does not move (ORCH-1156 / ORCH-1158)
Every start is still a fresh Playwright temporary profile in the broker's own temp folder, over a pipe. Still no
`--user-data-dir`, no debugging port, no extension, no outside browser, read-only requests, the network filter. A
kept sign-in is **data loaded into that fresh context** (`new_context(storage_state=...)`, from memory), never a
saved browser profile. The wall tests stay as they are; new tests only add (see B2).

## Decisions

### 1. Where it lives (c1)
- Per workspace: `.orch/addons/browse/signin/`, folder 0700, files 0600, already covered by the manifest's
  `gitignore = [".orch/addons/browse/"]` (runtime state like `run/` and `sites/`, R1.3). Windows: a per-user
  folder ACL (as `run/` does today).
- `signin/<site>.json`: the secret, one site each, only that site's cookies and local storage (Playwright
  `storage_state` shape, filtered by host). `<site>` is the site-list entry (a name; covers its subdomains).
- `signin/index.json`: no secret, so the Browser page can list without decrypting:
  `{"v": 1, "sites": {"<site>": {"state": "kept"|"declined"|"ended", "saved": "<ISO>", "used": "<ISO>"}}}`.
  Hand-fixable (R1.3); unreadable or an unknown `v` = nothing is loaded, with one plain line (R8.2, R8.4).
- **At rest:** the file holds `{"v": 1, "nonce", "ct"}`: AES-256-GCM with one random key per person. The key is NOT
  in the workspace: it sits in orch's per-user folder (outside the workspace, so a workspace synced by OneDrive or
  iCloud or copied by hand never carries a readable sign-in, R1.6). Windows protects the key with DPAPI
  (CurrentUser, no prompt); macOS and Linux keep it 0600. **No Keychain or Credential Manager prompt** (ORCH-1101).
  Said plainly: this stops a stray copy of the workspace, not another process of the same user (R5.3, same limit
  as the broker channel key).
- Never in tickets, `orch log`, evidence, relay, publish, sync, screenshots or `net.jsonl` (hosts only today,
  unchanged). The dashboard never sends the file or its cookie names/values, only `index.json` fields.
- R5.2: the secret scan (evidence write, relay send, publish upload) gets a rule for a `signin/` path and for the
  storage_state shape (`"cookies"` with `"origins"`); a hit blocks and names the file. A planted-token test covers it
  (B6). Typed text is still never kept (unchanged).

### 2. How it is loaded and saved (c2)
- **Load:** at `open`, for the ticket's site list only. The broker reads `index.json`, decrypts the files of sites
  that are `kept` AND listed on this ticket, and passes only cookies and origins whose host is that site or a
  subdomain. A site that is not on the list is never read from disk. The helper never sees the data (no command
  returns it).
- **Save:** only after a person said Keep (below), and only for that site: at Give back the broker takes
  `context.storage_state()` before the pages are closed, filters to the site, encrypts, writes atomically (R8.2).
  For a site already `kept`, the broker also saves back at `close` so a refreshed token lasts. Nothing is saved for
  a site that is `declined`, unlisted, or forgotten while the browser ran (the broker re-reads `index.json`
  right before writing).
- **Contract (R9.4):** broker channel command `signin <generation> <page> <epoch> keep|notnow <site>`: only the page
  that holds control (same checks as `give`), only a person's dashboard route
  `POST /api/browse/signin {ticket, generation, page, epoch, site, action}` (action fence, the person's session, JSON
  only, exact fields, never an add-on frame); `orch browse` (the helper's CLI) has no such command. The Give back
  answer gains `offer: {site}` once per site that is listed, was driven by the person, and is neither `kept` nor
  `declined`; the watcher gets it in `control`. `GET /api/browse/list` gains `signins: [{site, state, used}]`.
  Additive; older peers ignore the new fields. Vectors and schema go with B3.

### 3. How it is allowed (c3)
- The person allows it **per site, by one click, after a take-over**: Give back → one banner "Keep me signed in on
  <site>?" with **Keep** (filled) and **Not now**. Pattern: a password manager's save prompt; Playwright
  `storage_state`; "keep me signed in" in Operator and Claude for Chrome.
- Not now writes `declined`; orch never asks again for that site. The person starts it later with a quiet
  "Keep me signed in" link in the take-over bar (not drawn yet, mockup follows in B3) or `orch browse signin keep
  <site> --ticket <id>` (a person only).
- A kept sign-in is used only on tickets whose site list names the site. The site list stays the limit; there is no
  second permission to learn (R4.4). Keep never adds a site to a list.

### 4. How long it lasts and how it goes away (c4)
- Lasts until the site's own cookie expiry (a session cookie lasts until the site ends it), at most **30 days
  unused** (a fixed default, no setting). When every saved cookie has expired or 30 days passed, the secret file is
  deleted and the site shows **Sign-in ended** (needs colour): the next take-over offers Keep again.
- **Forget sign-in**, one click, no typed confirm (R7.3): per site on the Browser page ("Signed-in sites"); CLI
  `orch browse signin forget <site>` is the same code path (R4.3) and refused inside a helper. Forget deletes the
  secret file and index entry; a browser that is open keeps its in-memory copy until it closes but never saves it
  back. Forget of the last one shows "No sign-in kept".
- Also forgotten: when the site is on no ticket's list any more (checked when a list changes and at the next
  `open`), and on `orch uninstall` / `orch addon remove browse` (folder and the per-user key). `orch browse signin
  list` prints sites, state and last use, no secret.

### 5. What the helper may do on a signed-in site (c5, R2.4)
- **Same read-only rules as today**: GET/HEAD/OPTIONS only, no WebSocket, no download, no form or beacon send, no
  new tab. Posting or sending as the person stays impossible for the helper; it needs the person's own take-over
  and the existing "Forms may go to" tick (ORCH-1495 q1). No new send path, so nothing new to ask.
- What changes: pages now show the person's private content (mail, chats) to the helper. The handover rules stay
  (R2.3: links and short notes, no whole pages), the page text keeps its nonce markers (inbound is data, R3.2), and
  the live view shows a quiet "Signed in" tag on the bar so the person sees it.
- Known limit, to find out before building (B7): Teams and similar apps need WebSockets and service workers, which
  the wall blocks, so they may show only a shell. The first build step is a spike on a real MFA site; if it does not
  load, the owner decides whether this feature still pays off. The wall is not loosened for it (out of scope).

### 6. Words (c6, R4.2, R7.5)
No new noun: **sign-in** is the existing word ("Sign in" for a page login stays). New row in `docs/wording.md`:
Keep me signed in / Signed in / Sign-in ended / Forget sign-in; never Profile, Session, Vault, Cookies, Remember me.
"Signed-in sites" is only the list heading. `brand/tests/test_wording.py` passes with the row. One question for
the owner: is the list heading acceptable, or should the list sit under Settings? (Recommended: stay on Browser.)

## Screens (c7, R6.3)
Drafted from the master library only (no new component: `.banner`, `.card`, `.row`, `.pill`, `.btn`):
1. `ticket-browser.html?state=offer`: Keep / Not now banner after Give back, then "Signed in on <site> is kept."
2. `browser.html`: "Signed-in sites · N": a line per site, `Signed in` or `Sign-in ended` tag, `Forget sign-in`.
3. `browser.html?signin=none`: empty state "No sign-in kept" (shown after the last Forget too).
Loading is not needed (reads a small local index); the error state is the plain line for an unreadable index.
Screenshots at 1280, 1920 and 390 are on the ticket as evidence, not in git.

## Follow-up build tickets (not created yet; to open once the owner accepts)
| # | Ticket | Scope |
|---|---|---|
| B1 | Browse: sign-in store | `signin/` folder, `index.json`, AES-GCM envelope, per-user key (DPAPI on Windows), 0700/0600, atomic writes, expiry and 30-day sweep; unit tests incl. unknown `v`, damaged file, paths with spaces and umlauts |
| B2 | Browse: load and save in the broker | load for listed sites only, save at Give back and at close; wall tests unchanged plus: no `--user-data-dir`, no debug port, unlisted site's cookies never loaded, nothing plaintext on disk |
| B3 | Browse: keep offer (channel, route, kit) | `signin` channel command, `/api/browse/signin`, `offer` in Give back, kit banner in `browser.js` with gallery entry, mockup update for the take-over bar link; contract schema and vectors |
| B4 | Browse: Signed-in sites list and Forget | dashboard card, `signins` in the list route, `orch browse signin list/forget/keep`, "Signed in" tag in the live view; mockup parity |
| B5 | Browse: cleanup paths | forget when the site leaves every list, on uninstall and add-on remove (incl. the per-user key) |
| B6 | Secret scan for a kept sign-in (R5.2) | scan rule for `signin/` paths and storage_state shape in evidence, relay send and publish upload; planted-token tests |
| B7 | Browse: spike on an MFA site | try Teams and one simple site behind the wall; report what loads; go/no-go for the owner |

Order: B7 first (cheap, decides the rest), then B1 → B2 → B3 → B4, B5 and B6 beside them.

## Out of scope
Showing an outside browser (debug Edge, Playwright) in the live view; any saved browser profile folder; syncing a
sign-in to another computer or workspace (never, R3.2/R5.2); writing or sending as the person.

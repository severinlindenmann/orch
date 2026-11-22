# Browser add-on contract (`orch browse`)

First step of the browser add-on (ORCH-1492; plan ORCH-1112, owner pick A on ORCH-1158, wall note ORCH-1156).
A helper reads public web pages in a private browser for its ticket. orch's broker owns the browser and a network
filter sits in front of it; the helper only gets a fixed set of commands. Off and invisible until
`orch addon add browse`; the browser itself is downloaded by a person with `orch browse setup`.

What it guards against: a page tricking the helper into reaching this computer, the local network, cloud metadata
or a site the person did not allow, and any send (form, beacon, POST) in this first step. What it does not guard
against: a helper that breaks out with its own shell (same as today; said plainly in the wall note).

## Manifest (`workspace-addons/browse/src/orch_browse/orch-addon.toml`)
`name = "browse"`, `recommended = false`, no `needs`, no `background`, no dashboard entry yet (the Browser page and
the live view come with ORCH-1493/1494), `gitignore = [".orch/addons/browse/"]`. One pinned dependency:
`playwright==1.64.1` (its own Chromium build; an update is its own pull request with the wall tests).

## Commands (exit 0 ok, 2 refused with a plain line)
The ticket comes from `ORCH_TICKET` inside a helper run, else `--ticket <id>`.

| Command | Does |
|---|---|
| `open <address>` | starts the ticket's broker and browser when none runs (refused when the site list is empty), opens the page, prints the page walk |
| `go <address>` | opens another page (http/https only, name only, port 80/443, on the site list) |
| `look` | page title and address, then the page text with numbered elements between `--- page content <nonce> ---` lines |
| `read` | the page's plain text between the same markers |
| `click <n>`, `type <n> <text>`, `press <key>`, `back` | act on the page; `type` refuses password and file fields |
| `shot` | saves a PNG under `.orch/addons/browse/shots/<ticket>/` and prints its path |
| `status` | open or not, the page; after an end the reason |
| `close` | closes the browser; the temporary profile folder is deleted |
| `sites [list\|add\|remove] [<ticket>] <site>...` | the ticket's site list; `add`/`remove` refused inside a helper (a person runs it); local names and addresses refused |
| `setup` | a person downloads the pinned browser (`playwright install chromium-headless-shell`) |

Every answer after a page step adds, once each: what the broker stopped (a send, a WebSocket, a download, a file
request, a page message it closed, a new tab) and "Not loaded (the network filter stopped them): <hosts>".

## Files (`.orch/addons/browse/`, gitignored)
- `sites/<ticket>.json`: `{"sites": ["example.com", ...]}`. A site entry covers the name and its subdomains. Missing =
  empty (nothing opens); unreadable = nothing opens.
- `run/<ticket>/` (0700): `channel.json` (0600: socket or pipe address and the run's random key), `state.json`
  (`{"pid", "state": "ready"|"ended", "why"}`), `net.jsonl` (one line per connection: `t`, `host`, `port`,
  `verdict`, `why`; never paths or bodies), `broker.log`, `profile.path`.
- `shots/<ticket>/page-<time>-<n>.png`.

## The broker
- One per ticket, a separate process (`python -m orch_browse.broker <root> <ticket>`). Channel: Unix socket in the
  0700 run folder (a short path in the temp folder when the path is too long), Windows a named pipe; the caller proves
  the run's key (HMAC challenge); JSON messages only. No eval, no pass-through to the browser.
- Browser: Playwright `launch()` + `new_context()`, headless, over a pipe (no debugging port), Playwright's temporary
  profile inside the broker's own temp folder, deleted on close and at the next start after a kill. Never
  `--user-data-dir` of a real profile, never a debugging port, never an extension (refused in `launch_args`).
  Keychain-safe options always on.
- Read only: requests other than GET/HEAD/OPTIONS are stopped before they leave; WebSockets never connect; downloads
  are off; file pickers and dialogs are refused or closed; service workers are blocked.
- Ends after 15 minutes without a command, when the filter stops answering, when the browser goes away, or on
  `close`.

## The network filter (`proxy.py`, `netcheck.py`, `localnets.py`)
- A proxy on 127.0.0.1 at a random port with a random user and password per run; Chromium uses it for everything,
  `<-loopback>` keeps localhost on the proxy, `--host-resolver-rules=MAP * ~NOTFOUND` stops the browser's own name
  lookups, QUIC is off, WebRTC may only use the proxy, background traffic is off.
- Per connection: port 80/443 only; local and metadata names refused by name; addresses refused (sites open by name);
  the name must be on the site list; then one lookup whose every answer must be outside loopback, private, link-local,
  carrier NAT, unique local, multicast, reserved, benchmark, the same inside IPv4-mapped/compatible, 6to4, Teredo
  and NAT64 (well-known and the network's own prefix from `ipv4only.arpa`), and outside every network this computer
  is on. It connects to exactly the checked address.
- Test-only exemption `ORCH_BROWSE_TEST_MAP` (name=127.0.0.1:port) is read only with `ORCH_HOME_STRICT=1`.

## Tests
- Unit: `tests/test_netcheck.py`, `tests/test_proxy.py`, `tests/test_cli.py`.
- Leak run with the real browser against a hostile test world (`tests/world.py`, `tests/test_wall_local.py`):
  canaries on 127.0.0.1 and ::1, an attacker site off the list, a page that tries fetch, images, frames, WebSockets,
  forms, beacons, redirects, prefetch, workers, WebRTC and tricky address spellings: zero hits. Runs on Linux, macOS
  and Windows wherever the pinned browser is downloaded (`PLAYWRIGHT_BROWSERS_PATH`).
- Linux test world with network namespaces, no test-only name map (`wall/linux-world.sh`, `wall/servers.py`,
  `tests/test_wall_linux.py`, CI job `browse-wall`; run `sudo -E bash wall/linux-world.sh` in
  `workspace-addons/browse` after `uv sync` and the browser download). "This computer" is a namespace with canaries
  on 127.0.0.1, ::1, 10.0.0.5, 192.168.1.5, 169.254.169.254 and fd00::5 (TCP 80/443, UDP 3478); site.test
  (203.0.113.10) and the attacker evil.test (203.0.113.66) sit behind a router in a second one. Names come from a
  hosts file mounted for the test only (local.test, meta.test, lan.test, both.test with a public and a loopback
  answer, mapped6.test are on the site list, so only the address rules stop them); the real /etc/hosts is never
  written. A packet capture is the independent record. Leak run: the browser has a route everywhere and only its
  proxy setting holds it back (nftables only watches). Hard run: nftables lets the browser's cgroup send only TCP
  to 127.0.0.1 in the filter's port range (the test checks the filter is the only listener there) and drops the
  rest, UDP included; a probe from that cgroup proves the rule drops. Fail-closed: a damaged site list opens
  nothing; a killed broker takes the browser with it and the next `open` deletes its temp folder. The browser is
  started through the test-only `ORCH_BROWSE_TEST_BROWSER` wrapper, read only with `ORCH_HOME_STRICT=1`.

## Live view (ORCH-1493, watch only)
- Channel commands besides the helper's: `watch` (keeps the connection; the broker sends JSON messages `hello
  {generation, ticket}`, `tabs {tabs: [{title, url, current}]}`, `frame {jpeg (base64), w, h, at}`, `clear`,
  `event {text, site_text?}`, `beat`, `end {why}`), `stop <generation>` (ends that browser only; another generation
  answers "That browser has already ended."), `close`. `stop`/`close` never wait for a seat or a running command;
  at most 8 watchers, 16 other connections.
- Pictures: CDP screencast of the helper's current page (the newest tab) over Playwright's own pipe session, JPEG
  q60, at most 1280x800; a still first; acked at once; each watcher gets only the newest picture; a picture of a page
  nobody streams any more is dropped. Pictures stay in memory only. Watching never counts as helper activity and
  changes nothing in the browser (page messages, file requests and downloads are handled as in the first step).
- `state.json` carries `generation` while the broker is ready.
- Dashboard (`workspace-addons/dashboard`, `browseview.py`): `GET /api/browse/stream?ticket=<id>` (server-sent events,
  the messages above, `end` with `final`), `GET /api/browse/state?ticket=<id>` (`{open, generation?, why?}`), both behind
  the same-origin check and the sign-in (checked again on every message); `POST /api/browse/stop {ticket, generation}`
  behind the action fence and the person's session. A page that stops reading is dropped after 20 s. No add-on frame
  reaches these routes. A signed-in person sees every ticket's browser, as with terminals.
- Kit: `UI.browserView` (`workspace/src/orch_ui/static/browser.js`), gallery "The helper's browser, live"; dashboard page
  `#browser/<ticket>` (`pages/livebrowse.js`).

## Places (ORCH-1494, watch only)
- `GET /api/browse/list` (dashboard, same checks as `/api/browse/state`: same origin, sign-in, no add-on frame):
  `{on, browsers: [{ticket, title, open, generation?, started?, ended?, why?}]}`, open ones first, then the ones that ended in
  the last 24 hours (time = when `state.json` was written), at most 60. `on` is false unless the add-on is installed
  and turned on in this workspace. A `ready` state whose broker process is gone counts as not open. Folders that are
  links or not ticket ids are skipped; no key, address or picture is in it.
- The manifest's `[dashboard]` has `panel = "browser"`: the dashboard draws the Browser page itself (every helper's
  browser: "Live now" with a small live preview each, "Ended today" as links); `orch browse view --json` answers an
  empty view.
- The small live preview (`UI.browserPeek`) is the one way into the live view: on the ticket (above the steps), in the
  Focus pane (under the conversation), in the ticket chat (above the message box) and on the Browser page. A click
  opens the live view in the ticket next to the steps (`#ticket/<id>?browser=open`), with Stop and Hide. An ended
  browser is one quiet line with its time; none shows nothing. Phone: the real picture scaled to the width, pinch to
  zoom.

## Take over and give back (ORCH-1495, desktop first)
- The lock (`takeover.py`, `Control`): `helper` (default) / `finishing` / `person` / `paused`, with an owner `epoch`
  bumped on every change. Take over waits for the helper's running step to end and the page to settle
  (`finishing`); the holder's Cancel ("Stop its step now") stops the step and reloads the page. `person`: only the
  page that took over sends input. A lost page (its watch closed: the page closed or reloaded, its sign-in ended),
  a lease that ran out (5 min, renewed every 20 s by the holder's page) pause; a take-over that never got control
  is dropped. `paused` never resumes the helper by itself: only Give back (any watching page) or Stop.
- The helper meanwhile: every command that arrived before a change waits (not counted as a hung step or as idle,
  at most 30 min) and comes back "The browser changed while a person used it; look again." (never replayed); a
  cancelled step comes back saying so. The helper reads nothing while a person drives, and what the browser
  stopped then is not queued for it. Its next answer after a give back starts with "A person used the browser from
  HH:MM to HH:MM; nothing typed was kept by orch."
- `orch browse ask-person "<why>"`: the helper asks for a person (`state.json` `control.asking`, the dashboard shows
  "Waiting for you"). Asking is not control. It returns after the give back, or "Nobody took over." after 30 min.
- Channel commands from the dashboard: `watch person` (the broker mints a page id for that watch and says it only in
  its `hello {page}`; a page id a caller names is never accepted), `take <generation> <page> <epoch> take|renew|cancel`,
  `give <generation> <page> <epoch>`, `input <generation> <page> <epoch> {w, h, events}`, `who`. Answers are JSON
  `{state, epoch, mine, since?, asking?, sent?, dropped?, text?}` or a plain refusal. They never wait behind the
  helper (own seats, 8). `orch browse` (the helper's CLI) has none of them. Every watcher gets `control {state,
  epoch, mine, since?, asking?}` on every change. `state.json` carries `control {state, asking?}`, never page ids.
- Input events (picture pixels of the current picture `w` x `h`; the broker refuses a batch for another size or
  before the first picture): `move/down/up/wheel {x, y, button?, count?, dx?, dy?, mod?}`, `key {type: down|up,
  key, mod?}` (Enter, Tab, Backspace, Delete, Escape, arrows, Home, End, PageUp, PageDown; Ctrl/Cmd + A, Z, Y as
  editing commands), `text`/`paste {text}` (Input.insertText; at most 2000 characters a batch, control characters
  dropped). At most 40 events a batch; outside the picture, odd fields, non-finite numbers: refused, never clamped.
  60 events a second (bursts of 60); too fast = dropped, letting go always passes. The epoch, the holder and the page
  are checked again right before each event goes in; a change drops the rest of the batch. CDP `Input.*` on the
  current page's own session. Held keys and buttons are let go on give back, pause and lease end.
- Give back: held keys and buttons are let go, then pages are closed until only one fresh page is left: EVERY page
  that existed or opened during the person's session (also one that opens during the give back) goes, so no history,
  no opener chain and nothing they typed on a page survives. The fresh page opens at the ORIGIN the person last had
  (`scheme://host/`, never a path: an app route can carry typed text); the give-back answer names only the host.
  Cookies and site storage (localStorage and the like) are NOT cleared: sites keep their sign-in there, and what a site
  shows of the person's own activity (a recent-searches list) is the same kind of thing as the sign-in staying. Said
  plainly on the card and in the answer: "The helper can see what the site itself shows after you give back (for
  example your sign-in or recent searches); orch kept nothing you typed." What the browser stopped on the person's
  pages is not passed to the helper.
- While a person is in control a GET form send (and a page script going to an address with a query) is stopped
  before it leaves (CDP `Page.frameRequestedNavigation`, reasons `formSubmissionGet` and `scriptInitiated`); the
  person sees "Stopped a form on <site>…" and is taken back to the form. The helper reads nothing meanwhile.
- Sends: one rule in the broker, `Broker._may_send` (requests and WebSockets). Still read only during take-over;
  TODO: the owner's pick (A: sends only to one site the person ticks while in control, B: look and click only,
  C: wait) changes only that function.
- Typed text is never logged: the dashboard keeps no request line for `/api/browse/input`, input errors are never
  echoed, `net.jsonl` keeps hosts only. A test types a secret marker and searches every file of the workspace.
- Limit, said plainly: the dashboard and the helper run as the same user, so a helper that leaves `orch browse` for
  its own shell can read the channel key and could send these commands too (wall note section 2: out of scope,
  same as today's browser control). The minted page ids and the epoch stop stale or guessed input, not such a helper.
- Dashboard: `POST /api/browse/take {ticket, generation, page, epoch, action}`, `/api/browse/give {ticket,
  generation, page, epoch}`, `/api/browse/input {ticket, generation, page, epoch, w, h, events}`: the action fence
  (host, origin, no other site), the person's own session (page secret), never an add-on frame, JSON only, exact
  fields, 1 KB (take, give) / 32 KB (input). 200 + the broker's JSON, 409 + its refusal, 404 no browser. The list
  rows carry `control` (finishing, person, paused) and `asking`.

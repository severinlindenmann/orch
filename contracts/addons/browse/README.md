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

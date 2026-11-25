# Live check of relay and publish

`scripts/live_check.py` checks the live relay (relay.severin.io) and publish (publish.severin.io) servers. It is a
plain program (no AI) and uses only the Python standard library.

## What it checks

| Check | Where it runs |
|---|---|
| `/health` answers `ok` | outside and inside |
| TLS valid for at least 14 more days | outside and inside |
| `Strict-Transport-Security` with max-age of at least 180 days (set in the Caddy sites, `relay/deploy/relay.caddy` and `publish/deploy/publish.caddy`) | outside and inside |
| `/admin`, `/admin/` and `/admin/api/workspaces` answer 404 on the public sites | outside and inside |
| Admin ports 8410-8412 closed on every public IPv4 and IPv6 address of both sites (an address this machine has no route to, such as IPv6 on GitHub's machines, is named in the line; none reachable fails) | outside only (GitHub Actions) |
| Admin listeners answer 200 over the private network (direct: hostinger-vps.nb.severin.io:8412 and :8411) | inside only |
| Admin pages answer 200 through the private https gateway (https://relay-admin.internal.severin.io/admin, https://publish-admin.internal.severin.io/admin; run by Management) | inside only |
| Newest outside run is green and at most 3 hours old | inside, with `--outside-from` |
| Starts the next outside run when the newest one is 50 minutes old or more (GitHub drops its own hourly plan) | inside by orch automation, with `--outside-from` |
| A relay message from one check workspace reaches another | inside, with `--relay-a` / `--relay-b` |
| A tiny file is published, fetched and deleted | inside, with `--publish-ws` |

Every status is the first answer: redirects are not followed, so a redirect is never read as 404 or 200.

A part that is not set up yet (no check workspaces, the outside job not on the default branch yet) shows as
`skip` and does not fail the check.

- **Outside**: `.github/workflows/live-check.yml` runs every hour on GitHub's machines, which are outside the
  private network. GitHub runs scheduled jobs only from the default branch, so this part starts after a release.
- **Inside**: an orch automation script on develop runs
  `python3 scripts/live_check.py --where inside --outside-from severinlindenmann/orch --out <file>` on a repeat.
  On develop the round trips use three check folders in `~/orch-livecheck` (`relay-a` and `relay-b`, joined to the
  relay as "Live check A" and "Live check B" with one rule A to B for text; `publish`, joined to publish as "Live
  check" with files only): `--relay-a ~/orch-livecheck/relay-a --relay-b ~/orch-livecheck/relay-b --publish-ws
  ~/orch-livecheck/publish`.
  Exit 1 makes orch put one question on the check's ticket. That question is the alert, so the owner hears
  about it only when a check fails.
- **Schedule**: the orch automation repeat (every hour, on ORCH-950) is the schedule that counts. GitHub drops or
  delays its own `schedule` runs (issue #2657), so the inside run starts the outside job itself
  (`gh workflow run live-check.yml`) when its newest run is 50 minutes old or more; the hourly cron in
  `live-check.yml` stays as a fallback, and a run it already made needs no extra start. Run by orch automation
  (`ORCH_ROOT` set), the check does nothing while the workspace is paused (`orch pause`), and after 30 runs in 24
  hours it stops with exit 1 until older runs leave the window (R8.6). A run by hand has neither limit and starts
  no outside run.

## Result format `orch.livecheck/1`

One JSON file per run, the same in every workspace that checks a live system: orch (relay and publish, this
script), Management (private network, inside view) and Fernscout (fernscout.ch). Each writes it into its check
ticket's files and exits 1 on a failure, so the alert is always the failed script's question on that ticket.

```json
{
  "schema": "orch.livecheck/1",
  "source": "orch",
  "where": "inside",
  "targets": ["https://relay.severin.io", "https://publish.severin.io"],
  "checked_at": "2026-11-19T21:40:00Z",
  "ok": false,
  "summary": "1 failed: relay TLS",
  "checks": [
    {"name": "relay health", "ok": true, "detail": "/health answered ok", "ms": 84},
    {"name": "relay TLS", "ok": false, "detail": "TLS ends in 9 days (less than 14)"},
    {"name": "publish file round trip", "ok": null, "detail": "check workspace not set up (--publish-ws)"}
  ]
}
```

`ok` on a check is `true` (passed), `false` (failed) or `null` (skipped). `ms` (optional) is how long the check
took, in milliseconds. Readers ignore fields they do not know, so a writer may add more. The run's `ok` is `false` when any check
failed. The program exits 0 when `ok` is `true` and 1 otherwise.

## Admin pages stay private

Relay (`ORCH_RELAY_ADMIN_LISTEN`) and publish (`ORCH_PUBLISH_ADMIN_LISTEN`, and the optional
`ORCH_PUBLISH_PRIVATE_LISTEN`) take one of two forms:

- `<interface>:<port>`, for example `wt0:8412`: the private address of the private-network interface, read at every
  start. This is the setting on the server: a server move or a rebuilt private network gives a new address and no
  config change is needed.
- `<IP>:<port>`: an IP address on loopback or the private network (10/8, 100.64/10, 172.16/12, 192.168/16,
  fd00::/8).

0.0.0.0, a public address, a host name and an interface without a private IPv4 address are refused, and the service
stops. It never falls back to another address. When the private network is not up yet at boot, the relay start fails
and systemd tries again every 10 seconds (`RestartSec=10`, no start limit). The publish private listener is optional:
without its interface, private-network apps stay hidden and the rest keeps running. The public Caddy sites only proxy
to the public listener, which has no admin paths. The live check proves this from the outside every hour.

### Runbook: set or change the admin address

1. In `/etc/orch-relay/env` set `ORCH_RELAY_ADMIN_LISTEN=wt0:8412`. In `/etc/orch-publish/env` set
   `ORCH_PUBLISH_ADMIN_LISTEN=wt0:8411` and, when private-network apps are used, `ORCH_PUBLISH_PRIVATE_LISTEN=wt0:8410`.
   The deploy only replaces the program, so these files stay as they are.
2. For publish, put `Restart=on-failure`, `RestartSec=10` and `StartLimitIntervalSec=0` in its unit too, the same as
   `relay/deploy/orch-relay.service`.
3. `systemctl restart orch-relay orch-publish`, then `journalctl -u orch-relay -n 5` shows `admin on <private IP>:8412`.
4. Check from a private-network device: the direct path `http://hostinger-vps.nb.severin.io:8412/admin` and `:8411/admin`,
   and the pages as people open them, `https://relay-admin.internal.severin.io/admin` and
   `https://publish-admin.internal.severin.io/admin` (Management's https gateway, no port), answer 200, and
   `python3 scripts/live_check.py --where inside` passes.

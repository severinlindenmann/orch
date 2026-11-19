# Moving relay and publish to a new server

Runbook for the move from the Infomaniak VPS (`orch-dev`) to the Hostinger VPS (KVM 4, Frankfurt, Ubuntu).
Owner decision 19 Nov 2026. Today the public side of `relay.severin.io` and `publish.severin.io` goes through the
NetBird Cloud reverse proxy (both names point to `eu1.netbird.services`). That proxy goes away, so on the new server
both names are public directly: Caddy on 80/443 with its own TLS certificates. The admin pages stay on the private
network only.

Production rule: nothing in this file is tried out on `orch-dev`. On `orch-dev` only the read-only inventory (step 0),
the stop and the data copy (move day) run.

## What moves

| | relay | publish |
|---|---|---|
| Binary | `/usr/local/bin/orch-relay` (web files built in) | `/usr/local/bin/orch-publish` (web files built in) |
| Service | `orch-relay.service` (`relay/deploy/`) | `orch-publish.service` (`publish/deploy/`) |
| Settings | `/etc/orch-relay/env` | `/etc/orch-publish/env` (+ drop-ins in `orch-publish.service.d/`) |
| Secrets | `master.key`, `admin-token`, `apns.p8` in `/etc/orch-relay/` | `admin-token` in `/etc/orch-publish/`, `app-cap.key` in the data folder |
| Data | `/var/lib/orch-relay/` (`relay.db` about 15 MB on 17 Nov, `blobs/`) | `/var/lib/orch-publish/` (`publish.db`, `files/`, `apps/`) |
| Public listener | `127.0.0.1:8103` behind Caddy | `127.0.0.1:8102` behind Caddy |
| Admin listener | `<private IP>:8412` | `<private IP>:8411` |
| Private apps | none | `<private IP>:80` (`ORCH_PUBLISH_PRIVATE_LISTEN` / `_URL`) |
| Public name | `relay.severin.io` | `publish.severin.io` |

Settings by name (values stay on the server): relay `ORCH_RELAY_LISTEN`, `_ADMIN_LISTEN`, `_DATA_DIR`,
`_MASTER_KEY_FILE`, `_ADMIN_TOKEN_FILE`, `_PUBLIC_ORIGIN`, `_APNS_KEY_FILE`, `_APNS_KEY_ID`, `_APNS_TEAM_ID`,
`_APNS_TOPIC`. Publish `ORCH_PUBLISH_LISTEN`, `_ADMIN_LISTEN`, `_PRIVATE_LISTEN`, `_PRIVATE_URL`, `_DATA_DIR`,
`_APPS_DIR`, `_PUBLIC_ORIGIN`, `_ADMIN_TOKEN_FILE`, `_SANDBOX`, `_DOCKER_APPS`, `_APP_SUBNETS`, `_IDLE_SECS`,
`_MAX_FILE_MB`, `_DEFAULT_DAYS`, `_MAX_DAYS`, `_APP_PORTS`, `ORCH_INSTALL_REF`.

What does not change: both public names, so workspaces, the phone app, webhook addresses and shared publish links keep
working without any change on their side. Workspace keys, phone pairings, rules, messages and files move with the data.

What changes: the private-network address of the admin pages (the new server gets its own address when it joins the
private network). Update bookmarks and the e2e harness (`e2e/main.py`, `e2e/full/harness/main.py`,
`e2e/walkthrough/walk.mjs` name the old address).

## Step 0: read-only inventory of the old server (move ticket, first thing)

Compare the live setup with this file; anything new goes into the table above before the move.

```sh
ssh orch-dev-root 'systemctl cat orch-relay orch-publish; ls /etc/systemd/system/orch-publish.service.d/ 2>/dev/null;
  sed -E "s/=.*//" /etc/orch-relay/env /etc/orch-publish/env; ls -la /etc/orch-relay /etc/orch-publish;
  du -sh /var/lib/orch-relay /var/lib/orch-publish /srv/orch-publish 2>/dev/null; ss -ltnp;
  command -v kiri && kiri --version; caddy version 2>/dev/null; ufw status numbered'
```

Only setting names are printed, never values.

## Day before: prepare the new server (no downtime)

1. ssh access (key from Proton, item "Hostinger VPS ssh key (root, KVM 4 Frankfurt)", `~/.ssh/hostinger-vps_ed25519`),
   updates, unattended upgrades on.
2. Join the private network. Note its private IP: it is the admin address below. If the self-hosted NetBird is not
   ready yet, join NetBird Cloud now and re-join the self-hosted network later (the admin address changes once more).
3. Firewall (Hostinger panel firewall and ufw, both): allow 22, 80, 443 from anywhere; allow 8411, 8412 and 80 only in on
   the private-network interface; default deny incoming. Then the Kiri rules from `docs/publish.md`
   ("Container mode: host setup").
4. Install Caddy (upstream package), Kiri (checked `.deb`), `sqlite3`.
5. Copy the release binaries (same release as production) and run `relay/deploy/install.sh <bin> <private IP>` and
   `publish/deploy/install.sh <bin> <private IP>`. Both make fresh secrets: they are replaced by the old ones on move
   day. Then stop both services again (`systemctl stop orch-relay orch-publish`).
6. Put `relay/deploy/Caddyfile` into `/etc/caddy/Caddyfile`, `caddy validate`, reload. Certificates can only be
   issued once DNS points here, so Caddy retries until move day; that is expected.
7. Master key: check that Proton holds the relay master key and that it matches the server
   (`sha256sum /etc/orch-relay/master.key` on `orch-dev`, compare with the Proton copy; never print the key). If Proton
   has none, store it now. Without the same master key every stored message, secret and webhook is unreadable.
8. At Namecheap: lower the TTL of `relay` and `publish` (today CNAME to `eu1.netbird.services`) to 60 seconds, at least
   24 hours before the switch, so old answers are gone by move day.
9. Tell the users (workspaces, phone) the time window.

## Move day

All times are from the moment the old services stop.

1. (0 min) Stop on the old server: `systemctl stop orch-relay orch-publish`. From now on nothing is written there.
2. (1 min) Consistent copies: `sqlite3 /var/lib/orch-relay/relay.db ".backup /var/lib/orch-relay/move.db"` and the same
   for `publish.db`, then `PRAGMA integrity_check` on both copies.
3. (2-10 min) Copy, server to server through the laptop (no key on either server for the other):
   `/var/lib/orch-relay`, `/var/lib/orch-publish`, `/srv/orch-publish` if it exists, `/etc/orch-relay/{master.key,admin-token,apns.p8}`,
   `/etc/orch-publish/admin-token`, and every setting that is not an address (APNs ids, sandbox, limits). Use
   `scp -3 -r` (or `rsync -a` through the laptop). Put `move.db` back as `relay.db` /
   `publish.db`. Owners `orch-relay:` / `orch-publish:`, keys 0600.
4. (10 min) Start on the new server: `systemctl start orch-relay orch-publish`; `curl -s localhost:8103/health` and
   `localhost:8102/health` say `ok`; admin pages answer on `http://<private IP>:8412/admin` and `:8411`.
   Check the public side before DNS moves: `curl --resolve relay.severin.io:443:<new public IP> -k https://relay.severin.io/health`.
5. (11 min) DNS at Namecheap: replace both CNAMEs with A records to the new public IP (and AAAA if the server has IPv6),
   TTL 60. Caddy gets both certificates within a minute of the first request that reaches it.
6. (12-15 min) Clients pick up the new address as the old answer runs out (60 s TTL; some resolvers keep it longer).
7. Remove the two reverse-proxy services in NetBird Cloud once the checks pass.

## Checks after the switch

- `https://relay.severin.io/health` and `https://publish.severin.io/health` say `ok`, with a valid certificate.
- Admin pages from the private network only: the public IP on 8411/8412 must not answer
  (`curl -m 5 http://<public IP>:8412/health` times out).
- A workspace: `orch relay inbox` works, a message to another workspace arrives.
- Phone app: opens, shows workspaces, a push arrives (APNs key moved).
- A webhook address of a workspace: one test call arrives in its inbox.
- An existing publish link (file) opens and decrypts; a new `orch publish` upload works.
- Each published app answers. Container images are built again on the first visit (first start takes a few
  minutes per app with build steps); open each app once after the switch to warm it.
- Private-reach apps open on the new private address.
- Counts match the old server: workspaces, phones, messages, files, apps (compare `SELECT count(*)` before step 1 and
  after step 4).

## Roll back

Until the checks pass, the old server keeps its data untouched (it was only stopped).

1. Namecheap: CNAMEs back to `eu1.netbird.services` (TTL still 60).
2. Old server: `systemctl start orch-relay orch-publish`.
3. New server: `systemctl stop orch-relay orch-publish`.

Messages and files written on the new server between the switch and the roll back are lost in a roll back; keep the
window short and decide within 30 minutes. After a week without problems, delete the data on the old server (it
becomes the self-hosted NetBird server).

## Downtime estimate

About 15 minutes in which relay and publish do not answer (stop, copy, start and DNS; the copy is the long part and
grows with the size of `/var/lib/orch-publish`). Plan a 30-minute window. Published apps take a few minutes more on
their first visit because their containers are built again. Nothing is lost: the old server stops before the copy.

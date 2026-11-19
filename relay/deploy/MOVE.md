# Moving relay and publish to a new server

Runbook for the move from the Infomaniak VPS (`orch-dev`) to the Hostinger VPS (KVM 4, Frankfurt, Ubuntu 26.04,
public `2.24.146.133`, private network `hostinger-vps.netbird.cloud` / `100.71.225.229` on 19 Nov).
Owner decision 19 Nov 2026. Today the public side of `relay.severin.io` and `publish.severin.io` goes through the
NetBird Cloud reverse proxy (both names point to `eu1.netbird.services`). That proxy goes away, so on the new server
both names are public directly: Caddy on 80/443 with its own TLS certificates. The admin pages stay on the private
network only.

Production rule: nothing in this file is tried out on `orch-dev`. On `orch-dev` only the read-only inventory (step 0),
the stop and the data copy (move day) run.

Who owns what on the new server: the Management workspace owns DNS, the firewall, ssh and Caddy's main Caddyfile.
Tell it before any change there (`orch relay send Management ...`) and send it "done" when the move is finished.
Caddy is the one web server on 80/443: each site is one file in `/etc/caddy/sites/`, then `caddy validate` and
`systemctl reload caddy`. Kiri (0.2.2, engine only) is installed; `docker` talks to it.

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
| Private apps | none | `<private IP>:8410` (`ORCH_PUBLISH_PRIVATE_LISTEN` / `_URL`; `:80` on the old server) |
| Public name | `relay.severin.io` | `publish.severin.io` |

Settings by name (values stay on the server): relay `ORCH_RELAY_LISTEN`, `_ADMIN_LISTEN`, `_DATA_DIR`,
`_MASTER_KEY_FILE`, `_ADMIN_TOKEN_FILE`, `_PUBLIC_ORIGIN`, `_APNS_KEY_FILE`, `_APNS_KEY_ID`, `_APNS_TEAM_ID`,
`_APNS_TOPIC`. Publish `ORCH_PUBLISH_LISTEN`, `_ADMIN_LISTEN`, `_PRIVATE_LISTEN`, `_PRIVATE_URL`, `_DATA_DIR`,
`_APPS_DIR`, `_PUBLIC_ORIGIN`, `_ADMIN_TOKEN_FILE`, `_SANDBOX`, `_ENGINE_SOCKET`, `_DOCKER`, `_DOCKER_APPS`, `_APP_SUBNETS`, `_IDLE_SECS`,
`_MAX_FILE_MB`, `_DEFAULT_DAYS`, `_MAX_DAYS`, `_APP_PORTS`, `ORCH_INSTALL_REF`.

What does not change: both public names, so workspaces, the phone app, webhook addresses and shared publish links keep
working without any change on their side. Workspace keys, phone pairings, rules, messages and files move with the data.

What changes: the private-network address of the admin pages (`http://100.71.225.229:8412/admin` and `:8411`; it
changes once more when the private network becomes self-hosted) and the address of private-reach publish apps: Caddy
holds port 80 on every address of the new server, so the private-app listener moves to port 8410, and private apps get
new links. Update bookmarks and the e2e harness (`e2e/main.py`, `e2e/full/harness/main.py`,
`e2e/walkthrough/walk.mjs` name the old address).

## Step 0: read-only inventory of the old server (move ticket, first thing)

Compare the live setup with this file; anything new goes into the table above before the move.

```sh
ssh orch-dev-root 'systemctl cat orch-relay orch-publish | sed -E "s/^(Environment=\"?[A-Za-z_]+)=.*/\1=<hidden>/";
  ls /etc/systemd/system/orch-publish.service.d/ 2>/dev/null;
  sed -E "s/=.*//" /etc/orch-relay/env /etc/orch-publish/env; ls -la /etc/orch-relay /etc/orch-publish;
  du -sh /var/lib/orch-relay /var/lib/orch-publish /srv/orch-publish 2>/dev/null; ss -ltnp;
  command -v kiri && kiri --version; caddy version 2>/dev/null; ufw status numbered'
```

Only setting names are printed, never values. If `ORCH_PUBLISH_APPS_DIR` (or an older `PUBLISH_APPS_DIR`) points
outside `/var/lib/orch-publish`, keep the same path on the new server and add a drop-in
`orch-publish.service.d/apps-dir.conf` with `[Service]` `ReadWritePaths=<that folder>`: the service may write only
inside its data folder otherwise. Note the sandbox mode (`ORCH_PUBLISH_SANDBOX`): the stop on move day depends on it.

## Day before: prepare the new server (no downtime)

Already done by Management (19 Nov): base setup, private network, firewall 22/80/443, fail2ban, unattended updates,
Caddy, Kiri. ssh: `root@2.24.146.133` with `~/.ssh/hostinger-vps_ed25519` (Proton, Agents vault, item "Hostinger VPS
ssh key (root, KVM 4 Frankfurt)").

1. Ask Management to open 8410, 8411 and 8412 only from the private network (never public), and to lower the TTL of
   `relay` and `publish` at Namecheap (today CNAME to `eu1.netbird.services`) to 60 seconds at least 24 hours before
   the switch.
2. Kiri rules for app containers: send Management the ufw rules from `docs/publish.md` ("Container mode: host setup")
   to apply (firewall is theirs). Check the engine socket path (`docker context inspect`) and set
   `ORCH_PUBLISH_ENGINE_SOCKET` if it is not `/run/kiri/docker.sock`. `install.sh` stops if `kiri host-access` does not
   exist in kiri-lite or the publish user cannot reach the engine: then give the user the socket's group by hand.
3. `apt install sqlite3`.
4. Copy the release binaries (same release as production) and run `relay/deploy/install.sh <bin> 100.71.225.229` and
   `publish/deploy/install.sh <bin> 100.71.225.229` (with `ORCH_PUBLISH_ENGINE_SOCKET` set to the socket path). Both make fresh keys and tokens,
   which the old ones replace on move day. Then stop both again (`systemctl stop orch-relay orch-publish`).
5. Copy `relay/deploy/relay.caddy` and `publish/deploy/publish.caddy` into `/etc/caddy/sites/`, `caddy validate`,
   `systemctl reload caddy`. Certificates can only be issued once DNS points here, so Caddy retries until move day;
   that is expected.
6. The relay master key. Check that Proton holds the relay master key and that it matches the server
   (`sha256sum /etc/orch-relay/master.key` on `orch-dev`, compare with the Proton copy; never print the key). If Proton
   has none, store it now. Without the same master key every stored message, secret and webhook is unreadable.
7. Tell the users (workspaces, phone) the time window.

## Move day

All times are from the moment the old services stop.

1. (0 min) Before the stop, note the counts for the last check (`SELECT count(*)` of workspaces, phones, messages in
   `relay.db`; files and apps in `publish.db`). Stop on the old server: `systemctl stop orch-relay orch-publish`.
   Published apps keep running on their own, so stop them too, or they write their data during the copy:
   container mode: `docker -H unix:///run/kiri/docker.sock ps -q --filter label=orch.publish.app | xargs -r docker -H unix:///run/kiri/docker.sock stop`,
   then the same `ps` must list nothing; systemd mode (transient units named `orch-app-<hex>-<port>`): `systemctl stop 'orch-app-*'` and
   `systemctl list-units --state=active 'orch-app-*'` shows none. From now on nothing is written there.
2. (1 min) Consistent copies: `sqlite3 /var/lib/orch-relay/relay.db ".backup /var/lib/orch-relay/move.db"` and the same
   for `publish.db`, then `PRAGMA integrity_check` on both copies.
3. (2-10 min) Copy, server to server through the laptop (no key on either server for the other):
   `/var/lib/orch-relay`, `/var/lib/orch-publish`, `/srv/orch-publish` if it exists, `/etc/orch-relay/{master.key,admin-token,apns.p8}`,
   `/etc/orch-publish/admin-token`, and every setting that is not an address (APNs ids, sandbox, limits). Stream a tar
   through the laptop so links, modes and owners stay as they are (apps keep `.venv` links and group-write folders for
   the container user; `scp` would break them):
   `ssh orch-dev-root 'tar -C / --exclude=etc/orch-relay/env --exclude=etc/orch-publish/env -cpf - var/lib/orch-relay var/lib/orch-publish etc/orch-relay etc/orch-publish' | ssh root@2.24.146.133 'tar -C / -xpf -'`
   (add `srv/orch-publish` if it exists). As root, tar maps owners by name (the users exist on both servers) and keeps
   numbers without a name (the container user). The `env` files are left out: copy the settings that are not addresses
   into the new ones by hand. On the new server delete any
   `relay.db-wal`, `relay.db-shm` (and the same for `publish.db`) first, then put `move.db` back as `relay.db` /
   `publish.db`. Owners `orch-relay:` / `orch-publish:`, keys 0600.
4. (10 min) Start on the new server: `systemctl start orch-relay orch-publish`; `curl -s localhost:8103/health` and
   `localhost:8102/health` say `ok`; admin pages answer on `http://<private IP>:8412/admin` and `:8411`; the publish
   log has no "cannot listen" line (the private-app listener came up); the counts match step 1. The public side can
   only be checked after the DNS switch (no certificate before).
5. (11 min) DNS at Namecheap (Management does it, on your message): replace both CNAMEs with A records to the new public IP (and AAAA if the server has IPv6),
   TTL 60. Caddy gets both certificates within a minute of the first request that reaches it.
6. (12-15 min) Clients pick up the new address as the old answer runs out (60 s TTL; some resolvers keep it longer).
7. Keep the two reverse-proxy services in NetBird Cloud until the roll back window is over (roll back needs them).

## Checks after the switch

- `https://relay.severin.io/health` and `https://publish.severin.io/health` say `ok`, with a valid certificate
  (plain `curl`, no `-k`).
- Admin pages and private apps from the private network only: from outside, `curl -m 5 http://2.24.146.133:8412/health`
  (and `:8411`, `:8410`) must time out.
- A workspace: `orch relay inbox` works, a message to another workspace arrives.
- Phone app: opens, shows workspaces, a push arrives (APNs key moved).
- A webhook address of a workspace: one test call arrives in its inbox.
- An existing publish link (file) opens and decrypts; a new `orch publish` upload works.
- Each published app answers. Container images are built again on the first visit (first start takes a few
  minutes per app with build steps); open each app once after the switch to warm it.
- Private-reach apps open on the new private address.

## Roll back

Until the checks pass, the old server keeps its data untouched (it was only stopped).

1. Namecheap (Management): CNAMEs back to `eu1.netbird.services` (TTL still 60). The NetBird Cloud proxy services must still exist
   (move-day step 7).
2. Old server: `systemctl start orch-relay orch-publish`.
3. New server: `systemctl stop orch-relay orch-publish`.

Messages and files written on the new server between the switch and the roll back are lost in a roll back; keep the
window short and decide within 30 minutes. After a week without problems, remove the NetBird Cloud proxy services and
delete the data on the old server (it becomes the self-hosted NetBird server).

## Downtime estimate

About 15 minutes in which relay and publish do not answer (stop, copy, start and DNS; the copy is the long part and
grows with the size of `/var/lib/orch-publish`). Plan a 30-minute window. Published apps take a few minutes more on
their first visit because their containers are built again. Nothing is lost: the old server stops before the copy.

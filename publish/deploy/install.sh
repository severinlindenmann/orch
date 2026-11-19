#!/bin/sh
# First install on the server (run as root): user, folders, admin token, settings, service.
# Usage: ./install.sh <path-to-orch-publish-binary> <private-ip>
# Apps run as containers on the Kiri engine: install Kiri and run `kiri host-access orch-publish` first
# (docs/publish.md, "Container mode: host setup").
set -eu
BIN="$1"; IP="$2"
id orch-publish >/dev/null 2>&1 || useradd --system --home /var/lib/orch-publish --shell /usr/sbin/nologin orch-publish
install -d -o orch-publish -g orch-publish -m 0750 /var/lib/orch-publish /etc/orch-publish
install -m 0755 "$BIN" /usr/local/bin/orch-publish
[ -f /etc/orch-publish/admin-token ] || head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' > /etc/orch-publish/admin-token
[ -f /etc/orch-publish/env ] || cat > /etc/orch-publish/env <<EOF
ORCH_PUBLISH_LISTEN=127.0.0.1:8102
ORCH_PUBLISH_ADMIN_LISTEN=$IP:8411
ORCH_PUBLISH_PRIVATE_LISTEN=$IP:80
ORCH_PUBLISH_PRIVATE_URL=http://$IP
ORCH_PUBLISH_DATA_DIR=/var/lib/orch-publish
ORCH_PUBLISH_ADMIN_TOKEN_FILE=/etc/orch-publish/admin-token
ORCH_PUBLISH_PUBLIC_ORIGIN=https://publish.severin.io
ORCH_PUBLISH_SANDBOX=container
EOF
chown orch-publish:orch-publish /etc/orch-publish/admin-token
chmod 0600 /etc/orch-publish/admin-token
install -m 0644 "$(dirname "$0")/orch-publish.service" /etc/systemd/system/orch-publish.service
systemctl daemon-reload && systemctl enable --now orch-publish
echo "Add the publish route (relay/deploy/Caddyfile), then: curl -s localhost:8102/health"

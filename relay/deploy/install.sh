#!/bin/sh
# First install on the VPS (run as root): user, folders, master key, admin token, service.
# Usage: ./install.sh <path-to-orch-relay-binary> [private-ip]
set -eu
BIN="$1"; IP="${2:-127.0.0.1}"
id orch-relay >/dev/null 2>&1 || useradd --system --home /var/lib/orch-relay --shell /usr/sbin/nologin orch-relay
install -d -o orch-relay -g orch-relay -m 0750 /var/lib/orch-relay /etc/orch-relay
install -m 0755 "$BIN" /usr/local/bin/orch-relay
[ -f /etc/orch-relay/master.key ] || { head -c 32 /dev/urandom > /etc/orch-relay/master.key; echo "Master key made: copy /etc/orch-relay/master.key to your password manager now."; }
[ -f /etc/orch-relay/admin-token ] || head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n' > /etc/orch-relay/admin-token
cat > /etc/orch-relay/env <<EOF
ORCH_RELAY_LISTEN=127.0.0.1:8103
ORCH_RELAY_ADMIN_LISTEN=$IP:8412
ORCH_RELAY_DATA_DIR=/var/lib/orch-relay
ORCH_RELAY_MASTER_KEY_FILE=/etc/orch-relay/master.key
ORCH_RELAY_ADMIN_TOKEN_FILE=/etc/orch-relay/admin-token
ORCH_RELAY_PUBLIC_ORIGIN=https://relay.severin.io
# ORCH_RELAY_APNS_KEY_FILE=/etc/orch-relay/apns.p8
EOF
chown orch-relay:orch-relay /etc/orch-relay/master.key /etc/orch-relay/admin-token
chmod 0600 /etc/orch-relay/master.key /etc/orch-relay/admin-token
install -m 0644 "$(dirname "$0")/orch-relay.service" /etc/systemd/system/orch-relay.service
systemctl daemon-reload && systemctl enable --now orch-relay
echo "Add the Caddyfile route (deploy/Caddyfile), then: curl -s localhost:8103/health"

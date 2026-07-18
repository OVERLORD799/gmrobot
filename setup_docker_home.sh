#!/usr/bin/env bash
# Move Docker data directory to /home (requires sudo once).
set -euo pipefail

NEW_ROOT="/home/czz/.docker-data"
DAEMON_JSON="/etc/docker/daemon.json"

echo "Target Docker data-root: ${NEW_ROOT}"
mkdir -p "${NEW_ROOT}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Re-running with sudo..."
  exec sudo bash "$0" "$@"
fi

mkdir -p /etc/docker
if [ -f "${DAEMON_JSON}" ]; then
  cp "${DAEMON_JSON}" "${DAEMON_JSON}.bak.$(date +%Y%m%d%H%M%S)"
fi

cat > "${DAEMON_JSON}" <<'JSON'
{
  "registry-mirrors": ["https://docker.m.daocloud.io"],
  "data-root": "/home/czz/.docker-data"
}
JSON

systemctl stop docker docker.socket 2>/dev/null || true

if [ -d /var/lib/docker ] && [ "$(du -s /var/lib/docker | awk '{print $1}')" -gt 4 ]; then
  echo "Migrating /var/lib/docker -> ${NEW_ROOT} ..."
  rsync -aH /var/lib/docker/ "${NEW_ROOT}/"
else
  echo "No significant data in /var/lib/docker; using fresh ${NEW_ROOT}"
fi

systemctl start docker
sleep 2
docker info | grep 'Docker Root Dir'
echo "Done."

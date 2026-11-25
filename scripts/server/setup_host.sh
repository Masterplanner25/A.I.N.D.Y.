#!/usr/bin/env bash
# Prepare a fresh Ubuntu 24.04 host to run A.I.N.D.Y. (OFF_LAPTOP_DEPLOYMENT_SPEC phase E; DEPLOYMENT.md §2, §6).
#
#   curl -fsSLO https://raw.githubusercontent.com/Masterplanner25/A.I.N.D.Y./main/scripts/server/setup_host.sh
#   sudo bash setup_host.sh                 # step 1: packages, docker-ce, tailscale, restic, the aindy user, the clone
#   sudo tailscale up                       # step 2: sign in (prints a URL); then note `tailscale ip -4`
#   sudo bash setup_host.sh --lock-ssh      # step 3: once SSH over the tailnet works, close it everywhere else
#
# Safe to run again: each step checks before it acts. It does not write `.env`, start the stack or restore anything:
# those are DEPLOYMENT.md §6 steps 2-3, done by hand, because `.env` holds the secrets and the master key.
#
# What it leaves:
# - docker-ce from Docker's own apt repository (never Docker Desktop, never the distro's docker.io);
# - tailscale, restic, python3, git, ufw (inbound: SSH only), unattended security upgrades;
# - user `aindy` in the docker group, the repo cloned at /home/aindy/aindy;
# - the nightly backup: systemd `aindy-backup.timer` (03:00 UTC, catches up after downtime) running
#   scripts/server/nightly_backup.sh as `aindy`. It does nothing off-server until /home/aindy/.aindy/offsite.env exists
#   (DEPLOYMENT.md §4).
#
# Docker publishes ports through its own iptables rules, past ufw. That is why every host port in compose is bound to
# 127.0.0.1 and the api to AINDY_BIND_ADDR (the tailnet address): ufw is not what keeps them private.
set -euo pipefail

REPO_URL="${AINDY_REPO_URL:-https://github.com/Masterplanner25/A.I.N.D.Y.}"
USER_NAME="aindy"
HOME_DIR="/home/${USER_NAME}"
CLONE="${HOME_DIR}/aindy"

say() { printf '\n== %s\n' "$*"; }
die() { printf 'setup_host: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"
. /etc/os-release
[ "${ID}" = "ubuntu" ] || die "written for Ubuntu (found ${ID}); read it and adapt"

lock_ssh() {
  command -v tailscale >/dev/null || die "tailscale is not installed: run without --lock-ssh first"
  tailscale ip -4 >/dev/null 2>&1 || die "tailscale is not up: sudo tailscale up, then check ssh over the tailnet works"
  say "ufw: SSH from the tailnet only"
  ufw allow in on tailscale0 to any port 22 proto tcp
  ufw delete allow OpenSSH >/dev/null 2>&1 || true
  ufw status verbose
  echo "Keep this session open and check a NEW ssh over the tailnet address before closing it."
}

if [ "${1:-}" = "--lock-ssh" ]; then lock_ssh; exit 0; fi
[ -z "${1:-}" ] || die "unknown argument: $1"

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq ca-certificates curl git python3 ufw restic unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

say "docker-ce (Docker's apt repository)"
if ! command -v docker >/dev/null || ! docker version --format '{{.Server.Platform.Name}}' 2>/dev/null | grep -qi "docker engine"; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker compose version

say "tailscale"
if ! command -v tailscale >/dev/null; then
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.noarmor.gpg" -o /usr/share/keyrings/tailscale-archive-keyring.gpg
  curl -fsSL "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.tailscale-keyring.list" -o /etc/apt/sources.list.d/tailscale.list
  apt-get update -q
  apt-get install -yq tailscale
fi
systemctl enable --now tailscaled

say "ufw: deny inbound except SSH (narrowed to the tailnet by --lock-ssh)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

say "user ${USER_NAME}"
id "${USER_NAME}" >/dev/null 2>&1 || useradd -m -s /bin/bash "${USER_NAME}"
usermod -aG docker "${USER_NAME}"
install -d -m 0700 -o "${USER_NAME}" -g "${USER_NAME}" "${HOME_DIR}/.aindy" "${HOME_DIR}/aindy-backups"
if [ -d /root/.ssh ] && [ -f /root/.ssh/authorized_keys ] && [ ! -f "${HOME_DIR}/.ssh/authorized_keys" ]; then
  install -d -m 0700 -o "${USER_NAME}" -g "${USER_NAME}" "${HOME_DIR}/.ssh"
  install -m 0600 -o "${USER_NAME}" -g "${USER_NAME}" /root/.ssh/authorized_keys "${HOME_DIR}/.ssh/authorized_keys"
fi

say "the repo"
if [ ! -d "${CLONE}/.git" ]; then
  sudo -u "${USER_NAME}" git clone -q "${REPO_URL}" "${CLONE}"
else
  sudo -u "${USER_NAME}" git -C "${CLONE}" fetch -q
fi
sudo -u "${USER_NAME}" git -C "${CLONE}" log --oneline -1

say "the nightly backup (systemd)"
cat > /etc/systemd/system/aindy-backup.service <<EOF
[Unit]
Description=A.I.N.D.Y. backup, restore test on Sundays, off-server copy
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=${USER_NAME}
WorkingDirectory=${CLONE}
ExecStart=/bin/bash ${CLONE}/scripts/server/nightly_backup.sh
EOF
cat > /etc/systemd/system/aindy-backup.timer <<'EOF'
[Unit]
Description=A.I.N.D.Y. backup, nightly at 03:00 UTC

[Timer]
OnCalendar=*-*-* 03:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now aindy-backup.timer
systemctl list-timers aindy-backup.timer --no-pager

say "done"
cat <<EOF
Next (DEPLOYMENT.md §6):
  1. sudo tailscale up           # sign in; then: tailscale ip -4
  2. from the laptop, ssh ${USER_NAME}@<tailnet address>; then: sudo bash setup_host.sh --lock-ssh
  3. as ${USER_NAME}: write ${CLONE}/.env (§3), and ${HOME_DIR}/.aindy/offsite.env (§4)
  4. restore a backup and start in dev mode (§6 step 3)
EOF

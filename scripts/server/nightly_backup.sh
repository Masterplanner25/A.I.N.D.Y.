#!/usr/bin/env bash
# The server's nightly backup (OFF_LAPTOP_DEPLOYMENT_SPEC §4, decision 5; DEPLOYMENT.md §4).
# Run by systemd `aindy-backup.timer` (setup_host.sh) as user aindy, from the clone. By hand: the same command.
#
# 1. backup_stack.py: a dated folder in ~/aindy-backups, 14 kept.
# 2. Sundays: restore_stack.py tests it (scratch databases, counts compared, dropped).
# 3. Off the server, when ~/.aindy/offsite.env exists: restic copies that folder to object storage, encrypted on this
#    host before it leaves; keeps 14 daily, 8 weekly, 6 monthly; on Sundays `restic check` reads back 5% of the data.
# 4. When AINDY_BACKUP_PING_URL is set (in offsite.env), it is pinged on success and `<url>/fail` on failure, so a
#    backup that stops running is noticed by something that is not this host.
#
# ~/.aindy/offsite.env (mode 600), any S3-compatible store:
#   RESTIC_REPOSITORY=s3:https://<endpoint>/<bucket>/aindy
#   RESTIC_PASSWORD_FILE=/home/aindy/.aindy/restic-password    # ALSO keep this password off the server
#   AWS_ACCESS_KEY_ID=...                                       # a key limited to this bucket
#   AWS_SECRET_ACCESS_KEY=...
#   AINDY_BACKUP_PING_URL=https://hc-ping.com/<uuid>            # optional
set -euo pipefail

cd "$(dirname "$0")/../.."
OFFSITE_ENV="${AINDY_OFFSITE_ENV:-$HOME/.aindy/offsite.env}"
BACKUPS="${AINDY_BACKUP_DIR:-$HOME/aindy-backups}"
PING=""

if [ -f "$OFFSITE_ENV" ]; then
  set -a; . "$OFFSITE_ENV"; set +a
  PING="${AINDY_BACKUP_PING_URL:-}"
fi

ping_url() { [ -z "$PING" ] || curl -fsS -m 10 --retry 3 -o /dev/null "$1" || true; }
trap 'ping_url "$PING/fail"' ERR

ping_url "$PING/start"
python3 scripts/backup_stack.py
stamp="$(ls -1 "$BACKUPS" | grep -E '^[0-9]{8}T[0-9]{6}Z$' | sort | tail -1)"
echo "newest backup: $stamp"

if [ "$(date -u +%u)" = "7" ]; then
  python3 scripts/restore_stack.py "$stamp"
fi

if [ -n "${RESTIC_REPOSITORY:-}" ]; then
  restic cat config >/dev/null 2>&1 || restic init
  restic backup --host aindy-server --tag nightly "$BACKUPS/$stamp"
  restic forget --host aindy-server --keep-daily 14 --keep-weekly 8 --keep-monthly 6 --prune
  if [ "$(date -u +%u)" = "7" ]; then
    restic check --read-data-subset=5%
  fi
  restic snapshots --host aindy-server --latest 1
else
  echo "off-server copy: SKIPPED ($OFFSITE_ENV not found). A backup on the same disk is not a backup."
fi

ping_url "$PING"

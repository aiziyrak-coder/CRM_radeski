#!/usr/bin/env bash
# Daily PostgreSQL backup for Radeski CRM. Run from cron (see docs/04_DEPLOY.md).
# Keeps 30 days of compressed dumps in $BACKUP_DIR.
set -euo pipefail
umask 077  # dumps and recordings hold patient data: owner-only files

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
cd "$PROJECT_DIR"

file="$BACKUP_DIR/crm-$(date +%F_%H%M).sql.gz"
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U crm -d crm --no-owner | gzip > "$file.tmp"
mv "$file.tmp" "$file"

# refuse to rotate if the new dump looks broken (empty / tiny)
if [ "$(stat -c %s "$file")" -lt 1024 ]; then
    echo "$(date -Is) backup too small: $file" >&2
    exit 1
fi

find "$BACKUP_DIR" -name 'crm-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date -Is) ok $file"

# call recordings (phase 3): copy the last two days' MP3s; the folder keeps growing, nothing is
# rotated here — retention is a clinic decision
mkdir -p "$BACKUP_DIR/recordings"
docker compose -f docker-compose.prod.yml exec -T worker     sh -c 'cd /recordings && find . -name "*.mp3" -mtime -2 -print0 | tar --null -cf - -T -'     | tar -xf - -C "$BACKUP_DIR/recordings"
echo "$(date -Is) ok recordings"

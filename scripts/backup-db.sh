#!/usr/bin/env bash
# Nightly Postgres dump for the prod VM. Keeps the newest 7 gzipped dumps in
# /opt/pawn/backups (mode 700; dumps hold encrypted BYOK keys, so not world-readable).
# Installed via cron by pawndeploy: see deployment.md section 4.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/pawn/backups}"
KEEP=7
CONTAINER="${PG_CONTAINER:-pawn-postgres-1}"

umask 077
mkdir -p "$BACKUP_DIR"
OUT="$BACKUP_DIR/pawn_$(date -u +%F_%H%M).sql.gz"

docker exec "$CONTAINER" pg_dump -U pawn pawn | gzip > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

ls -1t "$BACKUP_DIR"/pawn_*.sql.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "backup ok: $OUT"

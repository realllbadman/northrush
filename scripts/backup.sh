#!/usr/bin/env bash
# Nightly SQLite backup. Uses the online-backup API (not cp) so a snapshot
# taken mid-write is still consistent. Keeps KEEP_DAYS of history.
#
#   crontab -e
#   15 3 * * * /srv/northrush/scripts/backup.sh >> /var/log/northrush-backup.log 2>&1
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB="${APP_DIR}/northrush.db"
DEST="${BACKUP_DIR:-${APP_DIR}/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

[ -f "$DB" ] || { echo "$(date -Is) no database at $DB"; exit 1; }
mkdir -p "$DEST"

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${DEST}/northrush-${STAMP}.db"

python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
d = sqlite3.connect(dst)
with d:
    s.backup(d)          # consistent snapshot even while the app is writing
# verify the copy opens and the tables are intact before we trust it
n = d.execute("select count(*) from inquiries").fetchone()[0]
p = d.execute("select count(*) from products").fetchone()[0]
d.close(); s.close()
print(f"  snapshot verified: {p} products, {n} orders")
PY

gzip -f "$OUT"
gzip -t "${OUT}.gz" || { echo "$(date -Is) BACKUP CORRUPT: ${OUT}.gz"; exit 1; }

find "$DEST" -name 'northrush-*.db.gz' -mtime "+${KEEP_DAYS}" -delete
echo "$(date -Is) backup ok -> ${OUT}.gz ($(du -h "${OUT}.gz" | cut -f1))"

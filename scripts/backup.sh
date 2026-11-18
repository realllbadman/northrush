#!/usr/bin/env bash
# Nightly SQLite backup. Uses the online-backup API (not cp) so a snapshot
# taken mid-write is still consistent. Keeps KEEP_DAYS of history.
#
# Also mirrors photos uploaded in /admin (static/images/uploads/) into
# $DEST/uploads/. Upload names are content hashes and never rewritten, so the
# mirror is add-only: nothing is ever deleted from it, which also keeps the
# photos an older DB snapshot refers to.
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

UPLOADS="${APP_DIR}/static/images/uploads"
if [ -d "$UPLOADS" ]; then
    mkdir -p "${DEST}/uploads"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --exclude='*.part' "${UPLOADS}/" "${DEST}/uploads/"
    else
        cp -a "${UPLOADS}/." "${DEST}/uploads/"
    fi
    echo "  uploads mirrored: $(find "${DEST}/uploads" -type f | wc -l) photos"
fi
echo "$(date -Is) backup ok -> ${OUT}.gz ($(du -h "${OUT}.gz" | cut -f1))"

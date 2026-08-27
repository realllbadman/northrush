#!/usr/bin/env bash
#
# NorthRush Outdoors — deploy to a SHARED nginx box.
#
# Idempotent: first run installs, every later run ships a change.
# Additive only — it creates and touches exactly one systemd unit, one nginx
# vhost and one cron file, all named after this app. It never reads, edits or
# removes another site's configuration.
#
#   Usage:  REPO_URL=git@github.com:you/northrush.git ./install.sh
#
set -euo pipefail

# ─── configuration ────────────────────────────────────────────────────────────
APP=northrush
DOMAIN=northrushhunting.com
WWW=www.northrushhunting.com
PORT=8007
BRANCH="${BRANCH:-launch-hardening}"
REPO_URL="${REPO_URL:-}"

SRC=/opt/${APP}-src               # git checkout
APP_DIR=/opt/${APP}               # running copy
VENV=${APP_DIR}/.venv
DB=${APP_DIR}/northrush.db
ENV_FILE=${APP_DIR}/.env

UNIT=/etc/systemd/system/${APP}.service
VHOST_AVAIL=/etc/nginx/sites-available/${APP}
VHOST_LINK=/etc/nginx/sites-enabled/${APP}
CRON=/etc/cron.d/${APP}-backup
BACKUP_LOG=/var/log/${APP}-backup.log
DEPLOY_KEY=/root/.ssh/${APP}_deploy
# Shared prefix only — deliberately NOT the full header. enable-ssl.sh
# replaces this vhost with one headed "(deploy/enable-ssl.sh)", so matching the
# longer install.sh-specific string makes the script stop recognising its own
# file and refuse every redeploy after SSL is enabled.
MARKER="# managed-by: ${APP} deploy"

HERE="$(cd "$(dirname "$0")" && pwd)"

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mABORT:\033[0m %s\n' "$*" >&2; exit 1; }

# ─── 0. pre-flight ────────────────────────────────────────────────────────────
say "Pre-flight"

[ "$(id -u)" -eq 0 ] || die "run as root"

# `git reset --hard` below rewrites $SRC. Bash reads a script incrementally, so
# running this file from inside $SRC could corrupt execution mid-flight.
case "$HERE/" in
  "${SRC}/"*) die "do not run this from inside ${SRC} — git will rewrite it under you.
    Keep a bootstrap copy elsewhere, e.g. /root/${APP}-deploy/, and run it from there." ;;
esac

command -v nginx   >/dev/null || die "nginx not installed"
command -v git     >/dev/null || die "git not installed"
command -v rsync   >/dev/null || die "rsync not installed (apt install rsync)"
command -v python3 >/dev/null || die "python3 not installed"
command -v curl    >/dev/null || die "curl not installed"
command -v ss      >/dev/null || die "ss not installed (apt install iproute2)"
python3 -m venv --help >/dev/null 2>&1 || die "python3-venv missing (apt install python3-venv)"

systemctl is-active --quiet nginx || die "nginx is not running — refusing to touch a broken web tier"
info "nginx active, $(nginx -v 2>&1)"

# nginx serves /static/ straight off disk as its own user. If that is not
# www-data the app directory permissions have to be looser or every asset 403s.
NGINX_USER="$(awk '$1=="user"{gsub(/;/,"",$2); print $2; exit}' /etc/nginx/nginx.conf 2>/dev/null || true)"
NGINX_USER="${NGINX_USER:-www-data}"
if [ "$NGINX_USER" = "www-data" ]; then
    APP_DIR_MODE=750
else
    APP_DIR_MODE=755
    info "WARNING: nginx runs as '${NGINX_USER}', not www-data — using mode 755 on ${APP_DIR} so /static/ is readable"
fi
info "nginx worker user: ${NGINX_USER}"

# Port must be free, unless the thing holding it is us (a redeploy).
if ss -ltnH "sport = :${PORT}" | grep -q .; then
    if systemctl is-active --quiet "${APP}"; then
        info "port ${PORT} held by ${APP}.service — this is a redeploy"
    else
        ss -ltnp "sport = :${PORT}" || true
        die "port ${PORT} is in use by something that is not ${APP}.service. Pick another PORT."
    fi
else
    info "port ${PORT} is free"
fi

# Never clobber a vhost we did not write.
if [ -e "$VHOST_AVAIL" ] && ! grep -qF "$MARKER" "$VHOST_AVAIL"; then
    die "$VHOST_AVAIL exists and is NOT ours (no marker). Refusing to overwrite."
fi
if [ -e "$VHOST_LINK" ] && [ "$(readlink -f "$VHOST_LINK")" != "$(readlink -f "$VHOST_AVAIL")" ]; then
    die "$VHOST_LINK already points somewhere else. Refusing to touch it."
fi

# Warn about server_name collisions with the other six sites (read-only check).
if grep -rlE "server_name[^;]*\b${DOMAIN}\b" /etc/nginx/sites-enabled/ 2>/dev/null \
     | grep -v "/${APP}\$" | grep -q .; then
    die "another enabled vhost already claims ${DOMAIN}. Resolve by hand."
fi
info "no vhost conflicts for ${DOMAIN}"

# ─── 1. deploy key ────────────────────────────────────────────────────────────
say "Deploy key"

install -d -m 700 /root/.ssh
if [ ! -f "$DEPLOY_KEY" ]; then
    ssh-keygen -t ed25519 -N '' -q -f "$DEPLOY_KEY" -C "${APP}-deploy@$(hostname -s)"
    chmod 600 "$DEPLOY_KEY"
    cat <<KEYMSG

  A read-only deploy key was generated. Add this PUBLIC half to the repo
  (GitHub: Settings → Deploy keys → Add, leave "Allow write access" OFF):

$(cat "${DEPLOY_KEY}.pub")

  Then re-run this script.

KEYMSG
    exit 0
fi
info "deploy key present: $DEPLOY_KEY"

export GIT_SSH_COMMAND="ssh -i ${DEPLOY_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

# ─── 2. fetch source ──────────────────────────────────────────────────────────
say "Source → ${SRC}"

if [ ! -d "${SRC}/.git" ]; then
    [ -n "$REPO_URL" ] || die "REPO_URL not set and ${SRC} is not a checkout.
    Re-run as:  REPO_URL=git@github.com:you/northrush.git $0"
    git clone --branch "$BRANCH" "$REPO_URL" "$SRC"
else
    git -C "$SRC" remote set-url origin "${REPO_URL:-$(git -C "$SRC" remote get-url origin)}"
    git -C "$SRC" fetch --prune origin
    git -C "$SRC" checkout "$BRANCH"
    git -C "$SRC" reset --hard "origin/${BRANCH}"
fi
info "at $(git -C "$SRC" log --oneline -1)"

# Prefer templates from the checkout so unit/vhost changes ship with the code.
# Read-only use of $SRC — the script itself still runs from $HERE.
if [ -d "${SRC}/deploy" ] && [ -f "${SRC}/deploy/${APP}.service.template" ]; then
    TPL="${SRC}/deploy"
    info "templates from the checkout (${TPL})"
else
    TPL="$HERE"
    info "templates from the bootstrap copy (${TPL})"
fi

# ─── 3. sync to the running copy ──────────────────────────────────────────────
say "Sync → ${APP_DIR}"

install -d "$APP_DIR"

# .env and the database live only in APP_DIR and must survive every deploy.
rsync -a --delete \
    --exclude='.git/' \
    --exclude='.env' \
    --exclude='*.db' \
    --exclude='*.db-wal' \
    --exclude='*.db-shm' \
    --exclude='backups/' \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "${SRC}/" "${APP_DIR}/"
info "code synced (.env, *.db, backups/ preserved)"

# ─── 4. secrets ───────────────────────────────────────────────────────────────
say "Environment"

if [ ! -f "$ENV_FILE" ]; then
    cat <<ENVMSG

  ${ENV_FILE} is missing. Copy it up from your machine, then re-run:

      scp .env root@${DOMAIN}:${ENV_FILE}

  It is gitignored and excluded from the deploy rsync on purpose.

ENVMSG
    die "no .env"
fi

# scp as root leaves it root-owned; the service then cannot read it and the
# app silently falls back to code defaults.
chown www-data:www-data "$ENV_FILE"
chmod 600 "$ENV_FILE"
info "$(stat -c '%U:%G %a' "$ENV_FILE") $ENV_FILE"

# Refuse to publish with a default admin password.
if grep -qE '^ADMIN_PASSWORD=(change-me)?$' "$ENV_FILE"; then
    die "ADMIN_PASSWORD is unset or still 'change-me' — /admin would be wide open."
fi
grep -qE '^SITE_URL=https://' "$ENV_FILE" \
    || info "WARNING: SITE_URL is not set to https://${DOMAIN} — canonical tags, the sitemap and the customer email footer will be wrong."

# ─── 5. virtualenv ────────────────────────────────────────────────────────────
say "Python environment"

[ -x "${VENV}/bin/python" ] || python3 -m venv "$VENV"
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"
info "$(${VENV}/bin/python -V), $(${VENV}/bin/pip list 2>/dev/null | wc -l) packages"

# ─── 6. ownership ─────────────────────────────────────────────────────────────
say "Ownership"

# Whole tree, not just files: SQLite must create -wal/-shm siblings next to
# the database, which needs write permission on the DIRECTORY.
chown -R www-data:www-data "$APP_DIR"
chmod "$APP_DIR_MODE" "$APP_DIR"
info "www-data owns ${APP_DIR} (recursive), mode ${APP_DIR_MODE}"

# ─── 7. systemd ───────────────────────────────────────────────────────────────
say "systemd unit"

sed -e "s|@APP@|${APP}|g" \
    -e "s|@APP_DIR@|${APP_DIR}|g" \
    -e "s|@PORT@|${PORT}|g" \
    "${TPL}/${APP}.service.template" > "$UNIT"

systemctl daemon-reload
systemctl enable --quiet "${APP}"
systemctl restart "${APP}"
info "restarted ${APP}.service"

# ─── 8. health gate — nginx is not touched until the app answers ──────────────
say "Health check"

ok=0
for i in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        ok=1; info "healthy after ${i}s: $(curl -fsS http://127.0.0.1:${PORT}/health)"; break
    fi
    sleep 1
done
if [ "$ok" -ne 1 ]; then
    echo; systemctl status "${APP}" --no-pager -l | head -20 || true
    echo; journalctl -u "${APP}" -n 40 --no-pager || true
    die "app did not become healthy on 127.0.0.1:${PORT} — nginx left untouched"
fi

# ─── 9. nginx vhost ───────────────────────────────────────────────────────────
say "nginx vhost"

# If enable-ssl.sh has already installed the 443 block, leave it alone —
# re-running install.sh must not downgrade a live site back to plain HTTP.
if [ -f "$VHOST_AVAIL" ] && grep -q "listen 443" "$VHOST_AVAIL"; then
    info "HTTPS vhost already in place — keeping it"
else
    BACKUP=""
    if [ -f "$VHOST_AVAIL" ]; then
        BACKUP="${VHOST_AVAIL}.bak.$(date +%s)"
        cp -a "$VHOST_AVAIL" "$BACKUP"
    fi

    sed -e "s|@DOMAIN@|${DOMAIN}|g" \
        -e "s|@WWW@|${WWW}|g" \
        -e "s|@PORT@|${PORT}|g" \
        -e "s|@APP_DIR@|${APP_DIR}|g" \
        "${TPL}/nginx-http.conf.template" > "$VHOST_AVAIL"
    ln -sfn "$VHOST_AVAIL" "$VHOST_LINK"

    if nginx -t 2>/dev/null; then
        systemctl reload nginx
        info "vhost installed, nginx reloaded"
    else
        # Roll back OUR file only. The other six sites keep running on the
        # config nginx already has loaded, because we never reloaded.
        if [ -n "$BACKUP" ]; then mv -f "$BACKUP" "$VHOST_AVAIL"
        else rm -f "$VHOST_AVAIL" "$VHOST_LINK"; fi
        nginx -t || true
        die "nginx config test failed — rolled back our vhost, nginx NOT reloaded"
    fi
    [ -n "$BACKUP" ] && rm -f "$BACKUP" || true
fi

# ─── 10. nightly backup ───────────────────────────────────────────────────────
say "Backups"

touch "$BACKUP_LOG"; chown www-data:www-data "$BACKUP_LOG"
cat > "$CRON" <<CRONEOF
${MARKER}
# Nightly SQLite snapshot. Orders are the only irreplaceable data here —
# the catalog re-seeds from seed_data.py on every boot.
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
15 3 * * * www-data ${APP_DIR}/scripts/backup.sh >> ${BACKUP_LOG} 2>&1
CRONEOF
chmod 644 "$CRON"
info "cron installed: nightly 03:15 → ${APP_DIR}/backups/"

# Prove it works now rather than discovering it is broken in a month.
if sudo -u www-data "${APP_DIR}/scripts/backup.sh" >/dev/null 2>&1; then
    info "backup smoke test passed ($(ls -1 ${APP_DIR}/backups/*.db.gz 2>/dev/null | wc -l) snapshots)"
else
    info "WARNING: backup smoke test failed — check ${BACKUP_LOG}"
fi

# ─── done ─────────────────────────────────────────────────────────────────────
say "Deployed"
cat <<DONE
    app       ${APP}.service on 127.0.0.1:${PORT}  ($(systemctl is-active ${APP}))
    code      ${SRC} → ${APP_DIR}
    commit    $(git -C "$SRC" log --oneline -1)
    database  ${DB} $( [ -f "$DB" ] && echo "($(du -h "$DB" | cut -f1))" || echo "(created on first boot)" )

    Next:  http://${DOMAIN}/  should now answer.
           Then run:  ${HERE}/enable-ssl.sh
DONE

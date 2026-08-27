#!/usr/bin/env bash
#
# NorthRush Outdoors — issue a certificate and install the HTTPS vhost.
#
# Deliberately does NOT use `certbot --nginx`. On a multi-site box the nginx
# plugin selects a server block heuristically and has been observed writing
# the certificate into the wrong vhost. We use `certonly --webroot` and
# hand-write our own 443 block, so nothing outside our vhost is ever touched.
#
#   Usage:  ./enable-ssl.sh
#
set -euo pipefail

APP=northrush
DOMAIN=northrushhunting.com
WWW=www.northrushhunting.com
PORT=8007
APP_DIR=/opt/${APP}
WEBROOT=/var/www/html

VHOST_AVAIL=/etc/nginx/sites-available/${APP}
VHOST_LINK=/etc/nginx/sites-enabled/${APP}
LIVE=/etc/letsencrypt/live/${DOMAIN}
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC=/opt/${APP}-src
TPL="$([ -f "${SRC}/deploy/nginx-https.conf.template" ] && echo "${SRC}/deploy" || echo "$HERE")"

say()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[1;31mABORT:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root"
command -v certbot >/dev/null || die "certbot not installed"
systemctl is-active --quiet nginx || die "nginx is not running"

# The vhost must be ours before we rewrite it.
[ -f "$VHOST_AVAIL" ] || die "$VHOST_AVAIL not found — run install.sh first"
grep -q "managed-by: ${APP} deploy" "$VHOST_AVAIL" \
    || die "$VHOST_AVAIL is not ours — refusing to touch it"

# ─── 1. does DNS actually point at this machine? ──────────────────────────────
say "DNS"

resolve() {
    if command -v dig >/dev/null; then dig +short A "$1" | tail -1
    else getent ahostsv4 "$1" | awk 'NR==1{print $1}'; fi
}
LOCAL_IPS="$(ip -4 -o addr show scope global | awk '{split($4,a,"/"); print a[1]}')"
PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
ALL_IPS="$(printf '%s\n%s\n' "$LOCAL_IPS" "$PUBLIC_IP" | sed '/^$/d' | sort -u)"
info "this host: $(echo "$ALL_IPS" | tr '\n' ' ')"

for host in "$DOMAIN" "$WWW"; do
    got="$(resolve "$host")"
    [ -n "$got" ] || die "${host} does not resolve. Add the A record and wait for propagation."
    if echo "$ALL_IPS" | grep -qx "$got"; then
        info "${host} -> ${got}  ok"
    elif [ "${SKIP_DNS_CHECK:-0}" = "1" ]; then
        info "${host} -> ${got}  MISMATCH (ignored: SKIP_DNS_CHECK=1)"
    else
        die "${host} resolves to ${got}, which is not an address on this host.
    Fix DNS first — a wrong answer here burns a Let's Encrypt validation attempt.
    Override with SKIP_DNS_CHECK=1 only if you are behind a proxy/CDN."
    fi
done

# ─── 2. ACME pre-check with our own token ─────────────────────────────────────
# Let's Encrypt permits 5 failed validations per hostname per hour. Proving the
# path works with a token we control costs nothing; guessing costs an hour.
say "ACME reachability pre-check"

install -d -m 755 "${WEBROOT}/.well-known/acme-challenge"
TOKEN="${APP}-precheck-$(date +%s)"
TOKEN_FILE="${WEBROOT}/.well-known/acme-challenge/${TOKEN}"
echo "$TOKEN" > "$TOKEN_FILE"
chmod 644 "$TOKEN_FILE"
cleanup() { rm -f "$TOKEN_FILE"; }
trap cleanup EXIT

for host in "$DOMAIN" "$WWW"; do
    got="$(curl -fsS --max-time 10 "http://${host}/.well-known/acme-challenge/${TOKEN}" 2>/dev/null || true)"
    if [ "$got" = "$TOKEN" ]; then
        info "http://${host}/.well-known/... served correctly"
    else
        die "challenge path is NOT reachable on ${host} (got: '${got:-<nothing>}').
    Check that the vhost has, ABOVE location / :
        location ^~ /.well-known/acme-challenge/ { root ${WEBROOT}; }
    Not calling certbot — that would waste a validation attempt."
    fi
done

# ─── 3. certificate ───────────────────────────────────────────────────────────
say "Certificate"

EMAIL="${CERTBOT_EMAIL:-$(grep -E '^OWNER_EMAIL=' "${APP_DIR}/.env" 2>/dev/null | cut -d= -f2- | tr -d '"' | xargs || true)}"
[ -n "$EMAIL" ] || die "no email for the ACME account. Set CERTBOT_EMAIL=you@example.com"

if [ -d "$LIVE" ]; then
    info "existing cert found, expires: $(openssl x509 -enddate -noout -in "${LIVE}/fullchain.pem" | cut -d= -f2)"
    certbot certonly --webroot -w "$WEBROOT" \
        -d "$DOMAIN" -d "$WWW" \
        --non-interactive --agree-tos -m "$EMAIL" \
        --keep-until-expiring --deploy-hook "systemctl reload nginx"
else
    certbot certonly --webroot -w "$WEBROOT" \
        -d "$DOMAIN" -d "$WWW" \
        --non-interactive --agree-tos -m "$EMAIL" \
        --deploy-hook "systemctl reload nginx"
fi
[ -f "${LIVE}/fullchain.pem" ] || die "certbot finished but ${LIVE}/fullchain.pem is missing"
info "cert covers: $(openssl x509 -noout -text -in "${LIVE}/fullchain.pem" | grep -A1 'Subject Alternative Name' | tail -1 | xargs)"

# ─── 4. install the HTTPS vhost, with rollback ────────────────────────────────
say "HTTPS vhost"

BACKUP="${VHOST_AVAIL}.bak.$(date +%s)"
cp -a "$VHOST_AVAIL" "$BACKUP"

sed -e "s|@DOMAIN@|${DOMAIN}|g" \
    -e "s|@WWW@|${WWW}|g" \
    -e "s|@PORT@|${PORT}|g" \
    -e "s|@APP_DIR@|${APP_DIR}|g" \
    "${TPL}/nginx-https.conf.template" > "$VHOST_AVAIL"
ln -sfn "$VHOST_AVAIL" "$VHOST_LINK"

if nginx -t 2>/dev/null; then
    systemctl reload nginx
    rm -f "$BACKUP"
    info "HTTPS vhost live, nginx reloaded"
else
    mv -f "$BACKUP" "$VHOST_AVAIL"
    nginx -t || true
    die "nginx config test failed — rolled back to the HTTP vhost. nginx was NOT reloaded,
    so the other sites were never affected."
fi

# ─── 5. verify ────────────────────────────────────────────────────────────────
say "Verification"

sleep 1
code_https="$(curl -s -o /dev/null -w '%{http_code}' "https://${DOMAIN}/" || echo 000)"
code_http="$(curl -s -o /dev/null -w '%{http_code}' "http://${DOMAIN}/" || echo 000)"
code_www="$(curl -s -o /dev/null -w '%{http_code}' "https://${WWW}/" || echo 000)"
hsts="$(curl -sI "https://${DOMAIN}/" | grep -ci 'strict-transport-security' || true)"

info "https://${DOMAIN}/      -> ${code_https}  (want 200)"
info "http://${DOMAIN}/       -> ${code_http}  (want 301)"
info "https://${WWW}/  -> ${code_www}  (want 301)"
info "HSTS header present     -> ${hsts}  (want 1 — proves X-Forwarded-Proto reached the app)"

say "Renewal"
certbot renew --dry-run --cert-name "$DOMAIN" 2>&1 | tail -5 || info "WARNING: dry run failed — investigate before 60 days pass"

say "Done"
echo "    https://${DOMAIN}/ is live."

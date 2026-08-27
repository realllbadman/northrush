# Deploying NorthRush to the shared VPS

This box already serves six production sites behind one nginx. Everything here
is **additive**: it creates one systemd unit, one nginx vhost and one cron
file, all named `northrush`. It never reads, edits or removes another site's
configuration, and it never reloads nginx until `nginx -t` passes.

|            |                                    |
| ---------- | ---------------------------------- |
| Domain     | `northrushhunting.com` (+ `www`)   |
| Loopback   | `127.0.0.1:8007`                   |
| Source     | `/opt/northrush-src` (git)         |
| Running    | `/opt/northrush` (rsync target)    |
| Service    | `northrush.service` as `www-data`  |
| Database   | `/opt/northrush/northrush.db` (SQLite) |
| Health     | `GET /health` → `{"ok":true}`      |

## Command sequence

Everything runs **as root on the server**, except the one `scp`.

First, on your laptop, set the target. The address is kept out of this repo on
purpose — the repo is public, and publishing the IP of a box that accepts root
SSH just hands scanners a confirmed target:

```bash
cp deploy/server.local.env.example deploy/server.local.env   # then edit it
source deploy/server.local.env                               # exports SERVER_IP
```

### 1. First run — generates the deploy key, then stops

```bash
ssh root@${SERVER_IP}
mkdir -p /root/northrush-deploy      # bootstrap copy, kept OUTSIDE /opt/northrush-src
scp -r deploy/* root@${SERVER_IP}:/root/northrush-deploy/   # (from your laptop)
cd /root/northrush-deploy
./install.sh
```

It prints a public key and exits. Add it to the repo as a **read-only** deploy
key (GitHub: Settings → Deploy keys → Add, leave *Allow write access* unticked).

### 2. Copy the secrets up

`.env` is gitignored and excluded from the deploy rsync, so it never travels
through git. From your laptop:

```bash
scp .env root@${SERVER_IP}:/opt/northrush/.env
```

Set `SITE_URL=https://northrushhunting.com` in it first — canonical tags, the
sitemap and the customer email footer all derive from it. `install.sh` fixes
the ownership afterwards (`scp` as root leaves it root-owned, which the service
cannot read; the app would then silently fall back to code defaults).

### 3. Deploy

```bash
REPO_URL=git@github.com:you/northrush.git ./install.sh
```

Ends with the app answering on `127.0.0.1:8007` and the vhost installed.
DNS still points at the registrar at this stage, so verify by faking the
resolution rather than waiting:

```bash
curl --resolve northrushhunting.com:80:${SERVER_IP} \
     -sS -o /dev/null -w '%{http_code}\n' http://northrushhunting.com/
```

Expect `200`. If you get a **used-car dealership**, our vhost did not match and
the request fell through to the box's default server block — check
`nginx -T | grep -A2 northrushhunting`.

### 4. Point DNS at the box

**Deploy first, then flip DNS** — in that order. The default server block on
this box belongs to another site, so between DNS propagating and the app being
installed, visitors would be served a used-car dealership.

The domain is on Namecheap BasicDNS (`dns1/dns2.registrar-servers.com`). In
**Domain List → Manage → Advanced DNS**:

| Action     | Type  | Host  | Value                      |
| ---------- | ----- | ----- | -------------------------- |
| **delete** | A     | `@`   | `192.64.119.83` (parking)  |
| **delete** | CNAME | `www` | `parkingpage.namecheap.com`|
| **add**    | A     | `@`   | your server IP           |
| **add**    | A     | `www` | your server IP           |

Also remove any **URL Redirect Record** Namecheap added for parking.

**Leave the MX records and the SPF TXT alone.** The five
`eforward*.registrar-servers.com` MX entries and
`v=spf1 include:spf.efwd.registrar-servers.com ~all` are Namecheap's email
forwarding for `@northrushhunting.com`. They are unrelated to the website and
deleting them breaks mail to the domain.

Wait until both hostnames resolve to the VPS:

```bash
dig +short northrushhunting.com www.northrushhunting.com
```

`enable-ssl.sh` checks this itself and refuses to continue otherwise, because a
wrong answer burns one of five hourly validation attempts.

### 5. HTTPS

```bash
./enable-ssl.sh
```

### 6. Shipping a change afterwards

```bash
cd /root/northrush-deploy && ./install.sh
```

Re-running is the deploy. It pulls, rsyncs, reinstalls dependencies, restarts,
waits for `/health`, and leaves the HTTPS vhost alone.

The bootstrap copy lives in `/root/northrush-deploy/` deliberately, **not** in
`/opt/northrush-src`: `install.sh` runs `git reset --hard` on the checkout, and
bash reads a script incrementally, so running it from inside the tree it is
about to rewrite can corrupt execution mid-run. The script refuses to start if
you try. Once a checkout exists, the unit and vhost *templates* are read from
`/opt/northrush-src/deploy/` so they track the deployed commit — only the
script itself comes from the bootstrap copy.

## What each script guarantees

**`install.sh`** refuses to start if nginx is down, if port 8007 is held by
anything other than our own service, if an existing vhost lacks our marker
comment, or if another enabled vhost already claims the domain. It aborts if
`.env` is missing or still carries the default admin password. nginx is only
touched *after* `/health` answers; if `nginx -t` then fails it restores our
file and never reloads, so the other six sites keep running on the config
nginx already has in memory.

**`enable-ssl.sh`** verifies DNS resolves to this host, then proves the ACME
path works using a token it writes and fetches itself, before calling certbot
at all. It uses `certonly --webroot` — never `--nginx`, which picks a server
block by guessing and has been seen writing certs into the wrong vhost. The
443 block is ours, installed with the same test-and-rollback.

## Deliberate choices

- **`listen 443 ssl http2;`** — `http2 on;` is nginx 1.25.1+ and fails
  `nginx -t` on 1.24.
- **`location ^~ /.well-known/acme-challenge/` above `location /`**, in both
  the HTTP and HTTPS blocks. Without the `^~` the request reaches the proxy and
  the app's own 404 answers, which looks exactly like a DNS or firewall fault.
  It is in the 443 block too because renewal follows the redirect — omit it and
  renewal breaks silently around day 60.
- **`chown -R` on the whole directory**, not the files. SQLite creates
  `-wal`/`-shm` siblings and needs write permission on the *directory*.
- **No `EnvironmentFile=`** — the app already loads `.env` via python-dotenv,
  and systemd's stricter parser chokes on values containing spaces or `#`
  (`BUSINESS_HOURS` and `SMTP_PASSWORD` both contain spaces).
- **`Type=simple`, not `notify`** — gunicorn's sd_notify support varies by
  build; a missing `READY=1` hangs the unit for 90s. Polling `/health` is
  unambiguous.
- **Per-app SSL session zone names** (`northrush_ssl`) — a duplicate shared
  zone name across vhosts is a hard nginx error on a shared box.
- **The firewall is left alone.** Nothing here runs `ufw`.

## Rollback

```bash
# application only
systemctl stop northrush
git -C /opt/northrush-src checkout <previous-commit>
./install.sh

# take our site out of nginx without touching anyone else's
rm /etc/nginx/sites-enabled/northrush && nginx -t && systemctl reload nginx

# restore the database
gunzip -c /opt/northrush/backups/northrush-YYYYmmdd-HHMMSS.db.gz \
    > /opt/northrush/northrush.db
chown www-data:www-data /opt/northrush/northrush.db
systemctl restart northrush
```

## Backups

`install.sh` writes `/etc/cron.d/northrush-backup` — nightly 03:15, running
`scripts/backup.sh` as `www-data` into `/opt/northrush/backups/`, keeping 14
days, logging to `/var/log/northrush-backup.log`. It runs the backup once
during install to prove it works. Snapshots use SQLite's online-backup API, so
a copy taken mid-write is still consistent.

**Copy them off the box.** A backup on the same disk is not a backup. Orders
are the only irreplaceable data — the 98-product catalog re-seeds itself from
`seed_data.py` on every boot.

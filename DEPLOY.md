# Deploying NorthRush Outdoors

## 0. DNS

Point the domain at the server before running certbot — it validates over
HTTP and will fail if DNS has not propagated.

| Type | Name | Value |
| --- | --- | --- |
| A | `@` | your server's IPv4 |
| A | `www` | your server's IPv4 |
| AAAA | `@` | your server's IPv6 (if it has one) |

Check it resolves before continuing:

```bash
dig +short northrushhunting.com
dig +short www.northrushhunting.com
```

Both must return your server IP. Propagation is usually minutes, but allow
up to a few hours.

## 1. Server prep (Ubuntu)

```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx
sudo mkdir -p /srv/northrush && sudo chown $USER /srv/northrush
git clone <your-repo> /srv/northrush && cd /srv/northrush
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env   # real SMTP creds, admin password, business info
                                    # set SITE_URL=https://northrushhunting.com
                                    # (canonical/OG tags, sitemap, email footer)
```

## 2. systemd service

`/etc/systemd/system/northrush.service`:

```ini
[Unit]
Description=NorthRush Outdoors storefront
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/srv/northrush
ExecStart=/srv/northrush/.venv/bin/gunicorn backend.main:app \
  -k uvicorn.workers.UvicornWorker -w 2 -b 127.0.0.1:8007
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /srv/northrush
sudo systemctl daemon-reload
sudo systemctl enable --now northrush
curl -s localhost:8007/health   # → {"ok":true}
```

## 3. Nginx reverse proxy

`/etc/nginx/sites-available/northrush`:

```nginx
# Redirect www -> apex so pages have one canonical address
server {
    listen 80;
    server_name www.northrushhunting.com;
    return 301 http://northrushhunting.com$request_uri;
}

server {
    listen 80;
    server_name northrushhunting.com;

    # Freight photos are large; allow a sensible body size and long reads
    client_max_body_size 8m;

    location /static/ {
        alias /srv/northrush/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:8007;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/northrush /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 4. HTTPS

```bash
sudo certbot --nginx -d northrushhunting.com -d www.northrushhunting.com
```

## 5. Backups

```bash
sudo crontab -e
# nightly at 03:15
15 3 * * * /srv/northrush/scripts/backup.sh >> /var/log/northrush-backup.log 2>&1
```

Snapshots land in `/srv/northrush/backups/` (override with `BACKUP_DIR`) and
are pruned after `KEEP_DAYS` (default 14). Copy them off the box — a backup on
the same disk is not a backup. Restore with:

```bash
gunzip -c backups/northrush-YYYYmmdd-HHMMSS.db.gz > northrush.db
sudo systemctl restart northrush
```

## 6. Updating

```bash
cd /srv/northrush && git pull
sudo systemctl restart northrush   # catalog re-syncs on startup, orders untouched
```

Bump `ASSET_VERSION` in `backend/main.py` whenever CSS/JS changes so browsers
pick up the new files.

## Docker (alternative)

```bash
docker build -t northrush .
docker run -d --env-file .env -p 8007:8007 \
  -v $(pwd)/northrush.db:/app/northrush.db northrush
```

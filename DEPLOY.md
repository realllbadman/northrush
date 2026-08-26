# Deploying NorthRush Outdoors

## 1. Server prep (Ubuntu)

```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx
sudo mkdir -p /srv/northrush && sudo chown $USER /srv/northrush
git clone <your-repo> /srv/northrush && cd /srv/northrush
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env   # real SMTP creds, admin password, business info
                                    # set SITE_URL=https://yourdomain.com for
                                    # correct canonical/OG tags + sitemap
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
server {
    listen 80;
    server_name yourdomain.com;

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
sudo certbot --nginx -d yourdomain.com
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

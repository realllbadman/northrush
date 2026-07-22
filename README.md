# NorthRush Outdoors

Blinds-forward hunting/outdoor gear storefront: server-rendered FastAPI +
Jinja2, SQLite catalog of 98 products, client-side cart, quote/checkout flow
(orders arrive as inquiries — no card processing), financing calculator, and a
Basic-auth admin dashboard.

## Stack

- Python 3.10+ · FastAPI · SQLAlchemy · SQLite (`northrush.db`)
- Jinja2 server-rendered templates (no SPA, no build step)
- Vanilla JS + CSS · aiosmtplib for Gmail SMTP notifications

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit with your real values
uvicorn backend.main:app --reload --port 8007
```

Open http://localhost:8007 — the catalog auto-seeds on startup (98 products,
upserted by slug; re-running never duplicates and never touches orders).

## Configuration (.env)

| Var | Purpose |
| --- | --- |
| `SMTP_USER` / `SMTP_PASSWORD` | Gmail + app password (spaces are stripped automatically) |
| `OWNER_EMAIL` | Where order/booking notifications go |
| `BUSINESS_NAME/EMAIL/ADDRESS`, `OWNER_PHONE`, `BUSINESS_HOURS` | Shown in header/footer/contact |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | HTTP Basic creds for `/admin` |
| `DATABASE_URL` | Defaults to `sqlite:///./northrush.db` |

Email silently no-ops when SMTP is unconfigured — requests never fail because
of mail.

## Business rules

- Free domestic shipping over $1,500, else flat $14.99.
- International freight by region (Canada/Mexico $250 … Other Intl $900).
- Financing only on items over $1,500: $500 down, 36 months,
  monthly = (price − 500) / 36.
- Cart lives in `localStorage` (`northrush_cart_v1`); checkout POSTs the cart +
  contact details to `/inquiries/`. Owner follows up to confirm & take payment.

## Layout

```
backend/            FastAPI app (main.py), models, schemas, seed_data.py, routes/, services/
templates/          Jinja pages (base, _card macro, index, products, detail, checkout, …)
static/             css/main.css, js/main.js, js/animations.js, images/
frontend/admin.html Basic-auth admin dashboard (fetches /admin/data)
```

## Admin

`/admin` — HTTP Basic (constant-time compare). Lists and deletes order
inquiries and messages/bookings.

## Deploy

See [DEPLOY.md](DEPLOY.md). Short version:

```bash
gunicorn backend.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 127.0.0.1:8007
```

behind Nginx (serve `/static/` directly), as a systemd service, HTTPS via
certbot. A `Dockerfile` and `Procfile` are included.

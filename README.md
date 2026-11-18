# NorthRush Outdoors

Blinds-forward hunting/outdoor gear storefront: server-rendered FastAPI +
Jinja2, SQLite product catalog, client-side cart, quote/checkout flow
(orders arrive as inquiries — no card processing), financing calculator, and a
Basic-auth admin dashboard where products and photos are managed.

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

Open http://localhost:8007 — the catalog auto-seeds on startup from
`seed_data.py` (upserted by slug; re-running never duplicates, never touches
orders, and never overrides products managed in `/admin`).

## Configuration (.env)

| Var | Purpose |
| --- | --- |
| `SMTP_USER` / `SMTP_PASSWORD` | Gmail + app password (spaces are stripped automatically) |
| `OWNER_EMAIL` | Where order/booking notifications go |
| `BUSINESS_NAME/EMAIL/ADDRESS`, `OWNER_PHONE`, `BUSINESS_HOURS` | Shown in header/footer/contact |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | HTTP Basic creds for `/admin` |
| `DATABASE_URL` | Defaults to `sqlite:///./northrush.db` |
| `BUSINESS_WHATSAPP` | Digits only; blank hides the WhatsApp links |
| `SMARTSUPP_KEY` | Live-chat site key; **blank disables the widget** (keep it blank in dev) |
| `SITE_URL` | Public origin for canonical/OG tags and the sitemap; falls back to the request host |

Email silently no-ops when SMTP is unconfigured — requests never fail because
of mail.

## Email

Every submission sends **two** messages, both branded HTML with a plain-text
fallback:

1. **To the owner** — the order/enquiry details, `Reply-To` set to the customer.
2. **To the customer** — a confirmation, `Reply-To` set to the business, with
   the owner **bcc'd** so both sides of the conversation land in one inbox.

The bcc is an envelope recipient only — it never appears in the headers. A
customer address that resolves to the owner's own mailbox (including Gmail
plus-aliases) is deduped so nothing is delivered twice. Customers who order
without an email address simply get no confirmation; the order still saves.

## Spam protection

Both public POST endpoints (`/inquiries/`, `/bookings/`) are defended by:

- a **honeypot** field (`website`) hidden via `.hp-field`; when filled, the
  request gets the normal success message and is silently discarded;
- a **per-IP rate limit** of 5 submissions / 15 minutes, returning 429 with
  `Retry-After`.

Rate-limit state is per-process, so under `gunicorn -w N` the effective limit
is N x 5. That stops a flood; it is not a precise quota.

## Backups

`scripts/backup.sh` takes a consistent snapshot via SQLite's online-backup API
(not `cp`), gzips it, verifies it, and prunes beyond `KEEP_DAYS` (default 14).
Wire it to cron — see DEPLOY.md. Irreplaceable data: orders, and every product
added or edited in `/admin` (all in the database), plus the photos uploaded
there (`static/images/uploads/`). The script also mirrors that folder into
`backups/uploads/` — add-only, since upload names are content hashes — so a
restored DB snapshot always finds its photos. Restore both together.

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
frontend/admin.html Basic-auth admin dashboard (products, orders, messages)
```

## Legal pages

`/privacy`, `/terms` and `/shipping-returns` are served from `templates/` and
pull live values (shipping thresholds, freight regions, financing terms) from
config so they can't drift from the checkout. **They are drafts written to
match how the site actually behaves — have someone qualified review them
before launch.**

## Admin

`/admin` — HTTP Basic (constant-time compare). Three tabs:

- **Products** — add, edit and delete products and their photos. Photos are
  resized in the browser (longest side 1400px, JPEG) before upload, which also
  strips phone EXIF/GPS data, then stored content-addressed in
  `static/images/uploads/`. That folder is gitignored and excluded from the
  deploy rsync, so uploads survive deploys. (With the Dockerfile, mount it as
  a volume alongside the database.)
- **Orders** / **Messages** — list and delete inquiries and bookings.

**Who owns a product.** `seed_data.py` still seeds the catalog on every boot,
but the admin panel wins: once a product is created or edited in `/admin`
it is flagged `admin_managed` and the seed sync never overwrites or prunes it;
deleting a product in `/admin` records its slug in `removed_products` so the
seed never re-inserts it. Products nobody has touched in the admin keep
following `seed_data.py` as before. A product's slug (its URL) is set from the
name when created and never changes afterwards.

Write endpoints require an `X-Admin-Request: 1` header in addition to the
credentials — browsers resend Basic auth cross-site, and the custom header
forces a CORS preflight that blocks forged form posts.

## Deploy

See [DEPLOY.md](DEPLOY.md). Short version:

```bash
gunicorn backend.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 127.0.0.1:8007
```

behind Nginx (serve `/static/` directly), as a systemd service, HTTPS via
certbot. A `Dockerfile` and `Procfile` are included.

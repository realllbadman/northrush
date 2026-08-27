"""NorthRush Outdoors — FastAPI app: lifespan seeding, Jinja env, page routes."""
import os
import re
import struct
from html import escape
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from sqlalchemy import func, text
from sqlalchemy.orm import Session

load_dotenv()

from backend.database import Base, SessionLocal, engine, get_db  # noqa: E402
from backend.models import Product  # noqa: E402
from backend.routes import admin, bookings, inquiries  # noqa: E402
from backend.seed_data import (  # noqa: E402
    CATEGORY_LABELS,
    CATEGORY_SUBCATEGORIES,
    FEATURED_SLUGS,
    IMAGES_DIR,
    SLIDER_CHIPS,
    sync_products,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ASSET_VERSION = "7"  # bump on every CSS/JS change

# Smartsupp live chat. Public site key — blank it to disable the widget
# (kept out of dev/test that way).
SMARTSUPP_KEY = os.getenv("SMARTSUPP_KEY", "")

# Public origin, used for canonical/OG URLs and the sitemap. Falls back to
# whatever host the request arrived on, so dev keeps working unset.
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")


def site_url(request: Request) -> str:
    return SITE_URL or str(request.base_url).rstrip("/")

BUSINESS = {
    "name": os.getenv("BUSINESS_NAME", "NorthRush Outdoors"),
    "email": os.getenv("BUSINESS_EMAIL", os.getenv("OWNER_EMAIL", "")),
    "phone": os.getenv("OWNER_PHONE", ""),
    # The business line is WhatsApp-only. Digits only for wa.me; falls back to
    # OWNER_PHONE so a single configured number is enough.
    "whatsapp": re.sub(r"\D", "",
                       os.getenv("BUSINESS_WHATSAPP", "") or os.getenv("OWNER_PHONE", "")),
    "address": os.getenv("BUSINESS_ADDRESS", ""),
    "hours": os.getenv("BUSINESS_HOURS", "Mon–Sat 8am–6pm CT"),
    "free_ship_threshold": 1500,
    "flat_shipping": 14.99,
}

FREIGHT_REGIONS = [
    ("United States", 0),
    ("Canada / Mexico", 250),
    ("Europe / UK", 600),
    ("Asia", 750),
    ("Middle East", 800),
    ("Australia / New Zealand", 850),
    ("South America", 800),
    ("Other International", 900),
]

US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine",
    "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
    "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey",
    "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio",
    "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island", "South Carolina",
    "South Dakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia",
    "Washington", "West Virginia", "Wisconsin", "Wyoming",
]

FINANCING_MIN_PRICE = 1500
FINANCING_DOWN = 500
FINANCING_MONTHS = 36


# --------------------------------------------------------------------------- #
#  Template helpers
# --------------------------------------------------------------------------- #

def img_url(img):
    """Full URL passthrough; bare filenames serve from /static/images/."""
    if not img:
        return "/static/images/placeholder.jpg"
    if img.startswith("http://") or img.startswith("https://"):
        return img
    return "/static/images/" + img


_portrait_cache: dict = {}


def _read_dimensions(path):
    """(width, height) from a PNG IHDR or JPEG SOF header — no Pillow."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                w, h = struct.unpack(">II", head[16:24])
                return w, h
            if head.startswith(b"\xff\xd8"):
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    code = marker[1]
                    if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
                        continue
                    seg = f.read(2)
                    if len(seg) < 2:
                        return None
                    length = struct.unpack(">H", seg)[0]
                    if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                        sof = f.read(5)
                        if len(sof) < 5:
                            return None
                        h, w = struct.unpack(">HH", sof[1:5])
                        return w, h
                    f.seek(length - 2, 1)
    except OSError:
        return None
    return None


_dims_cache: dict = {}


def img_dims(filename):
    """(width, height) for a local image, or None. Cached — headers only."""
    if not filename or filename.startswith("http"):
        return None
    if filename not in _dims_cache:
        _dims_cache[filename] = _read_dimensions(os.path.join(IMAGES_DIR, filename))
    return _dims_cache[filename]


def img_size_attrs(filename):
    """Ready-to-drop width/height attributes — stops cumulative layout shift."""
    dims = img_dims(filename)
    return Markup(f' width="{dims[0]}" height="{dims[1]}"') if dims else Markup("")


def img_is_portrait(filename) -> bool:
    """True when the image is clearly taller than wide (used to style tall photos)."""
    if not filename or filename.startswith("http"):
        return False
    if filename in _portrait_cache:
        return _portrait_cache[filename]
    dims = _read_dimensions(os.path.join(IMAGES_DIR, filename))
    result = bool(dims) and dims[1] > dims[0] * 1.1
    _portrait_cache[filename] = result
    return result


# --------------------------------------------------------------------------- #
#  App + lifespan
# --------------------------------------------------------------------------- #

MIGRATIONS = [
    # Idempotent ALTERs for columns added after first release; each may fail silently.
    "ALTER TABLE inquiries ADD COLUMN freight_region VARCHAR DEFAULT ''",
    "ALTER TABLE inquiries ADD COLUMN payment_method VARCHAR DEFAULT ''",
    "ALTER TABLE inquiries ADD COLUMN best_time VARCHAR DEFAULT ''",
    "ALTER TABLE products ADD COLUMN images JSON",
    "ALTER TABLE products ADD COLUMN price_max FLOAT",
    "ALTER TABLE bookings ADD COLUMN product_interest VARCHAR DEFAULT ''",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for stmt in MIGRATIONS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()  # column already exists — fine
    db = SessionLocal()
    try:
        sync_products(db)
    finally:
        db.close()
    yield


app = FastAPI(title="NorthRush Outdoors", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

app.include_router(inquiries.router)
app.include_router(bookings.router)
app.include_router(admin.router)


@app.middleware("http")
async def security_and_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Only meaningful over TLS; Nginx forwards the original scheme.
    if request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# --------------------------------------------------------------------------- #
#  Jinja environment (Py3.12: cache_size=0; new TemplateResponse signature)
# --------------------------------------------------------------------------- #

_env = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    cache_size=0,
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals.update(
    BUSINESS=BUSINESS,
    CATEGORY_LABELS=CATEGORY_LABELS,
    CATEGORY_SUBCATEGORIES=CATEGORY_SUBCATEGORIES,
    SLIDER_CHIPS=SLIDER_CHIPS,
    FREIGHT_REGIONS=FREIGHT_REGIONS,
    US_STATES=US_STATES,
    ASSET_VERSION=ASSET_VERSION,
    LEGAL_UPDATED=datetime.now().strftime("%B %-d, %Y"),
    SMARTSUPP_KEY=SMARTSUPP_KEY,
    current_year=datetime.now().year,
    img_url=img_url,
    img_is_portrait=img_is_portrait,
    img_size_attrs=img_size_attrs,
    site_origin=site_url,
    og_image=lambda request: f"{site_url(request)}/static/images/logo.png",
)
templates = Jinja2Templates(env=_env)



# --------------------------------------------------------------------------- #
#  Homepage curation
# --------------------------------------------------------------------------- #

def _pick_featured(db: Session, count: int = 8):
    """3 pinned blinds first, then a cheapest→priciest spread of blinds >= $900."""
    pinned = []
    for slug in FEATURED_SLUGS[:3]:
        p = db.query(Product).filter(Product.slug == slug).first()
        if p:
            pinned.append(p)
    pool = (
        db.query(Product)
        .filter(
            Product.category == "deer-blinds-stands",
            Product.price >= 900,
            Product.slug.notin_([p.slug for p in pinned]),
        )
        .order_by(Product.price.asc())
        .all()
    )
    need = count - len(pinned)
    if len(pool) <= need:
        spread = pool
    else:  # evenly spaced picks across the sorted pool: cheapest → priciest
        step = (len(pool) - 1) / (need - 1) if need > 1 else 0
        spread = [pool[round(i * step)] for i in range(need)]
    return pinned + spread


def _hero_blinds(db: Session, count: int = 4):
    """Real-photo blinds for the hero: featured order first, then best sellers."""
    picks, seen = [], set()

    def add(p):
        if p and p.slug not in seen and p.image != "placeholder.jpg":
            picks.append(p)
            seen.add(p.slug)

    for slug in FEATURED_SLUGS:
        add(db.query(Product).filter(Product.slug == slug).first())
    for p in (
        db.query(Product)
        .filter(Product.category == "deer-blinds-stands", Product.badge == "Best Seller")
        .order_by(Product.price.desc())
        .all()
    ):
        add(p)
    return picks[:count]


def _spotlight(db: Session):
    """Flagship blind: the priciest real-photo blind in the catalog."""
    return (
        db.query(Product)
        .filter(Product.category == "deer-blinds-stands", Product.image != "placeholder.jpg")
        .order_by(Product.price.desc())
        .first()
    )


def _category_counts(db: Session):
    rows = (
        db.query(Product.category, func.count(Product.id))
        .group_by(Product.category)
        .all()
    )
    found = dict(rows)
    return {cat: found.get(cat, 0) for cat in CATEGORY_LABELS}


# --------------------------------------------------------------------------- #
#  Pages
# --------------------------------------------------------------------------- #

@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    category_counts = _category_counts(db)
    brand_counts = {}
    for (brand,) in db.query(Product.brand).all():
        if brand:
            brand_counts[brand] = brand_counts.get(brand, 0) + 1
    brand_counts = dict(sorted(brand_counts.items(), key=lambda kv: -kv[1]))
    return templates.TemplateResponse(request, "index.html", {
        "featured": _pick_featured(db),
        "hero_blinds": _hero_blinds(db),
        "spotlight": _spotlight(db),
        "brand_counts": brand_counts,
        "category_counts": category_counts,
        "total_products": db.query(Product).count(),
        "num_categories": len(CATEGORY_LABELS),
        "num_states": len(US_STATES),
    })


@app.get("/products")
def products_page(
    request: Request,
    category: str = "",
    subcategory: str = "",
    q: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Product)
    if category:
        query = query.filter(Product.category == category)
    if subcategory:
        query = query.filter(Product.subcategory == subcategory)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            Product.name.ilike(like)
            | Product.brand.ilike(like)
            | Product.description.ilike(like)
            | Product.model_number.ilike(like)
        )
    products = query.order_by(Product.price.asc()).all()
    return templates.TemplateResponse(request, "products.html", {
        "products": products,
        "result_count": len(products),
        "q": q,
        "active_category": category,
        "active_subcategory": subcategory,
        "category_label": CATEGORY_LABELS.get(category, "All Products"),
        "subcategories": CATEGORY_SUBCATEGORIES.get(category, []),
        "category_counts": _category_counts(db),
        "not_found": False,
    })


@app.get("/products/{slug}")
def product_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.slug == slug).first()
    if not product:
        products = db.query(Product).order_by(Product.price.asc()).limit(8).all()
        return templates.TemplateResponse(request, "products.html", {
            "products": products,
            "result_count": len(products),
            "q": "",
            "active_category": "",
            "active_subcategory": "",
            "category_label": "All Products",
            "subcategories": [],
            "category_counts": _category_counts(db),
            "not_found": True,
            "missing_slug": slug,
        }, status_code=404)
    related = (
        db.query(Product)
        .filter(Product.category == product.category, Product.slug != product.slug)
        .order_by(Product.price.asc())
        .limit(4)
        .all()
    )
    return templates.TemplateResponse(request, "product_detail.html", {
        "product": product,
        "related": related,
        "category_label": CATEGORY_LABELS.get(product.category, product.category),
        "financing_months": FINANCING_MONTHS,
        "financing_down": FINANCING_DOWN,
        "financing_min": FINANCING_MIN_PRICE,
    })


@app.get("/checkout")
def checkout(request: Request):
    return templates.TemplateResponse(request, "checkout.html", {})


@app.get("/financing")
def financing(request: Request, db: Session = Depends(get_db)):
    eligible = (
        db.query(Product)
        .filter(Product.price > FINANCING_MIN_PRICE)
        .order_by(Product.price.asc())
        .all()
    )
    return templates.TemplateResponse(request, "financing.html", {
        "eligible": eligible,
        "financing_months": FINANCING_MONTHS,
        "financing_down": FINANCING_DOWN,
        "financing_min": FINANCING_MIN_PRICE,
    })


@app.get("/contact")
def contact(request: Request):
    return templates.TemplateResponse(request, "contact.html", {})


@app.get("/about")
def about(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "about.html", {
        "total_products": db.query(Product).count(),
        "num_states": len(US_STATES),
    })


@app.get("/admin")
def admin_page(_: str = Depends(admin.require_admin)):
    # Basic auth on the page itself so the browser prompts once, then reuses
    # the credentials for the /admin/data fetch.
    return FileResponse(os.path.join(BASE_DIR, "frontend", "admin.html"))


@app.get("/privacy")
def privacy(request: Request):
    return templates.TemplateResponse(request, "privacy.html", {})


@app.get("/terms")
def terms(request: Request):
    return templates.TemplateResponse(request, "terms.html", {
        "financing_months": FINANCING_MONTHS,
        "financing_down": FINANCING_DOWN,
        "financing_min": FINANCING_MIN_PRICE,
    })


@app.get("/shipping-returns")
def shipping_returns(request: Request):
    return templates.TemplateResponse(request, "shipping.html", {
        "num_states": len(US_STATES),
    })


@app.get("/robots.txt", include_in_schema=False)
def robots(request: Request):
    body = "\n".join([
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /checkout",
        "",
        f"Sitemap: {site_url(request)}/sitemap.xml",
        "",
    ])
    return PlainTextResponse(body)


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request, db: Session = Depends(get_db)):
    base = site_url(request)
    urls = [(f"{base}/", "1.0"), (f"{base}/products", "0.9"),
            (f"{base}/financing", "0.7"), (f"{base}/about", "0.5"),
            (f"{base}/contact", "0.5"), (f"{base}/shipping-returns", "0.4"),
            (f"{base}/privacy", "0.3"), (f"{base}/terms", "0.3")]
    for cat in CATEGORY_LABELS:
        urls.append((f"{base}/products?category={cat}", "0.8"))
    for (slug,) in db.query(Product.slug).order_by(Product.slug).all():
        urls.append((f"{base}/products/{slug}", "0.8"))

    today = datetime.now().strftime("%Y-%m-%d")
    items = "".join(
        f"<url><loc>{escape(loc)}</loc><lastmod>{today}</lastmod>"
        f"<priority>{pri}</priority></url>"
        for loc, pri in urls
    )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"{items}</urlset>")
    return Response(content=xml, media_type="application/xml")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Browsers get the branded 404 page; API clients keep getting JSON."""
    wants_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == 404 and wants_html:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    headers = getattr(exc, "headers", None)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)


@app.get("/health")
def health():
    return JSONResponse({"ok": True})

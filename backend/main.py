"""NorthRush Outdoors — FastAPI app: lifespan seeding, Jinja env, page routes."""
import os
import struct
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
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

ASSET_VERSION = "2"  # bump on every CSS/JS change

BUSINESS = {
    "name": os.getenv("BUSINESS_NAME", "NorthRush Outdoors"),
    "email": os.getenv("BUSINESS_EMAIL", os.getenv("OWNER_EMAIL", "")),
    "phone": os.getenv("OWNER_PHONE", ""),
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
async def no_cache_html(request: Request, call_next):
    response = await call_next(request)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
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
    current_year=datetime.now().year,
    img_url=img_url,
    img_is_portrait=img_is_portrait,
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


@app.get("/health")
def health():
    return JSONResponse({"ok": True})

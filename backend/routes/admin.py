"""Admin JSON API — login form + signed session cookie, constant-time compare.

/admin shows a login form; a successful sign-in sets a signed session cookie.
Orders and messages are read/delete only. Products are full CRUD, plus photo
upload into static/images/uploads/ (gitignored, kept across deploys, mirrored
by scripts/backup.sh).
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Booking, Inquiry, Product, RemovedProduct
from backend.seed_data import CATEGORY_LABELS, CATEGORY_SUBCATEGORIES, IMAGES_DIR
from backend.services.antispam import client_ip

log = logging.getLogger("northrush.admin")
router = APIRouter(tags=["admin"])

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")


# --------------------------------------------------------------------------- #
#  Login: a form on /admin posts the credentials once, and gets back a signed,
#  HttpOnly session cookie. (This replaced the browser's Basic-auth popup,
#  which some browsers hide or skip silently once credentials are cached.)
# --------------------------------------------------------------------------- #

SESSION_COOKIE = "nr_admin"
SESSION_SECONDS = 7 * 24 * 3600
# Derived from the credentials, so every worker agrees on it without shared
# state, and changing ADMIN_PASSWORD logs every existing session out.
_SESSION_KEY = hashlib.sha256(
    "|".join(("northrush-admin-session", os.getenv("ADMIN_SESSION_SECRET", ""),
              ADMIN_USERNAME, ADMIN_PASSWORD)).encode()
).digest()

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 10        # per IP per window (per worker)
_login_failures: dict = defaultdict(deque)


def _session_mac(expires: int) -> str:
    return hmac.new(_SESSION_KEY, f"{ADMIN_USERNAME}|{expires}".encode(), hashlib.sha256).hexdigest()


def _session_ok(token: str) -> bool:
    try:
        exp_s, mac = token.split(".", 1)
        expires = int(exp_s)
    except (ValueError, AttributeError):
        return False
    return expires > time.time() and hmac.compare_digest(mac, _session_mac(expires))


def require_admin(request: Request):
    if not _session_ok(request.cookies.get(SESSION_COOKIE, "")):
        # Deliberately no WWW-Authenticate header: that is what made browsers
        # pop up their own login box instead of showing ours.
        raise HTTPException(status_code=401, detail="Please sign in")
    return ADMIN_USERNAME


def _require_admin_header(request: Request):
    """Custom header on every state-changing call.

    It forces a CORS preflight, which this app never grants, so another site
    cannot forge these requests. (The SameSite=Strict cookie already stops
    that; this is the second lock.)
    """
    if request.headers.get("x-admin-request") != "1":
        raise HTTPException(status_code=403, detail="Missing admin request header")


def require_admin_write(request: Request, user: str = Depends(require_admin)):
    _require_admin_header(request)
    return user


def _login_rate_check(ip: str) -> None:
    now = time.time()
    fails = _login_failures[ip]
    while fails and now - fails[0] > LOGIN_WINDOW_SECONDS:
        fails.popleft()
    if not fails:
        _login_failures.pop(ip, None)
    elif len(fails) >= LOGIN_MAX_FAILURES:
        retry = int(LOGIN_WINDOW_SECONDS - (now - fails[0]))
        raise HTTPException(
            status_code=429,
            detail=f"Too many wrong attempts. Try again in {max(retry // 60, 1)} minutes.",
            headers={"Retry-After": str(max(retry, 1))},
        )


class LoginIn(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=200)


@router.post("/admin/login")
def admin_login(data: LoginIn, request: Request, response: Response):
    _require_admin_header(request)
    ip = client_ip(request)
    _login_rate_check(ip)
    user_ok = secrets.compare_digest(data.username.encode(), ADMIN_USERNAME.encode())
    pass_ok = secrets.compare_digest(data.password.encode(), ADMIN_PASSWORD.encode())
    if not (user_ok and pass_ok):
        _login_failures[ip].append(time.time())
        log.warning("admin login failed from %s", ip)
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    _login_failures.pop(ip, None)
    expires = int(time.time()) + SESSION_SECONDS
    response.set_cookie(
        SESSION_COOKIE, f"{expires}.{_session_mac(expires)}",
        max_age=SESSION_SECONDS, path="/admin", httponly=True, samesite="strict",
        secure=request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https",
    )
    return {"user": ADMIN_USERNAME}


@router.post("/admin/logout")
def admin_logout(request: Request, response: Response):
    _require_admin_header(request)
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    return {"ok": True}


@router.get("/admin/session")
def admin_session(user: str = Depends(require_admin)):
    return {"user": user}


@router.get("/admin/data")
def admin_data(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    inquiries = db.query(Inquiry).order_by(Inquiry.created_at.desc()).all()
    bookings = db.query(Booking).order_by(Booking.created_at.desc()).all()
    return {
        "inquiries": [
            {
                "id": i.id,
                "name": f"{i.first_name} {i.last_name}".strip(),
                "phone": i.phone,
                "email": i.email,
                "company": i.company,
                "address": f"{i.address}, {i.city}, {i.state} {i.zip}".strip(", "),
                "country": i.country,
                "freight_region": i.freight_region,
                "contact_pref": i.contact_pref,
                "best_time": i.best_time,
                "payment_method": i.payment_method,
                "notes": i.notes,
                "items": i.items or [],
                "coupon_code": i.coupon_code or "",
                "discount": i.discount or 0,
                "total": i.total,
                "status": i.status,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in inquiries
        ],
        "bookings": [
            {
                "id": b.id,
                "name": f"{b.first_name} {b.last_name}".strip(),
                "phone": b.phone,
                "email": b.email,
                "service": b.service,
                "product_interest": b.product_interest,
                "details": b.details,
                "status": b.status,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in bookings
        ],
    }


@router.delete("/admin/inquiries/{inquiry_id}")
def delete_inquiry(inquiry_id: int, _: str = Depends(require_admin_write), db: Session = Depends(get_db)):
    inq = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inq:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    db.delete(inq)
    db.commit()
    return {"message": f"Inquiry #{inquiry_id} deleted"}


@router.delete("/admin/bookings/{booking_id}")
def delete_booking(booking_id: int, _: str = Depends(require_admin_write), db: Session = Depends(get_db)):
    bk = db.query(Booking).filter(Booking.id == booking_id).first()
    if not bk:
        raise HTTPException(status_code=404, detail="Booking not found")
    db.delete(bk)
    db.commit()
    return {"message": f"Booking #{booking_id} deleted"}


# --------------------------------------------------------------------------- #
#  Products
# --------------------------------------------------------------------------- #

BADGES = ["Best Seller", "New", "Sale", "Hot Deal"]
UPLOAD_SUBDIR = "uploads"
UPLOADS_DIR = os.path.join(IMAGES_DIR, UPLOAD_SUBDIR)
MAX_UPLOAD_BYTES = 6 * 1024 * 1024   # nginx allows 8m; the admin page sends ~300 KB


def _image_ok(name: str) -> bool:
    """A full URL, or a file that really exists inside static/images/."""
    if name.startswith(("http://", "https://")):
        return True
    root = os.path.realpath(IMAGES_DIR)
    path = os.path.realpath(os.path.join(root, name))
    return path.startswith(root + os.sep) and os.path.isfile(path)


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str = Field("", max_length=100)
    category: str
    subcategory: str = ""
    model_number: str = Field("", max_length=500)
    price: float = Field(ge=0, le=1_000_000)
    price_max: Optional[float] = Field(None, ge=0, le=1_000_000)
    original_price: Optional[float] = Field(None, ge=0, le=1_000_000)
    description: str = Field("", max_length=10_000)
    features: List[str] = Field(default_factory=list, max_length=50)
    in_stock: bool = True
    badge: Optional[str] = None
    images: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("name", "brand", "model_number", "description", "subcategory")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("features")
    @classmethod
    def _clean_features(cls, v: List[str]) -> List[str]:
        return [f.strip()[:300] for f in v if f and f.strip()]

    @field_validator("badge")
    @classmethod
    def _badge(cls, v):
        v = (v or "").strip()
        if not v:
            return None
        if v not in BADGES:
            raise ValueError(f"badge must be one of {BADGES}")
        return v

    @field_validator("images")
    @classmethod
    def _images(cls, v: List[str]) -> List[str]:
        out = []
        for name in v:
            name = (name or "").strip()
            if not name or name == "placeholder.jpg" or name in out:
                continue
            if not _image_ok(name):
                raise ValueError(f"image not found: {name}")
            out.append(name)
        return out

    def check_relations(self):
        if self.category not in CATEGORY_LABELS:
            raise HTTPException(422, "Unknown category")
        if self.subcategory and self.subcategory not in CATEGORY_SUBCATEGORIES.get(self.category, []):
            raise HTTPException(422, "That type doesn't belong to the chosen category")
        if self.price_max is not None and self.price_max <= self.price:
            raise HTTPException(422, "'Price up to' must be higher than the price")
        if self.original_price is not None and self.original_price <= self.price:
            raise HTTPException(422, "'Was' price must be higher than the price")


def _product_json(p: Product) -> dict:
    return {
        "id": p.id,
        "slug": p.slug,
        "name": p.name,
        "brand": p.brand or "",
        "category": p.category or "",
        "subcategory": p.subcategory or "",
        "model_number": p.model_number or "",
        "price": p.price or 0,
        "price_max": p.price_max,
        "original_price": p.original_price,
        "description": p.description or "",
        "features": list(p.features or []),
        "in_stock": bool(p.in_stock),
        "badge": p.badge,
        "images": [i for i in (p.images or []) if i and i != "placeholder.jpg"],
        "image": p.image or "placeholder.jpg",
        "admin_managed": bool(p.admin_managed),
    }


def _apply(p: Product, data: ProductIn):
    for f in ("name", "brand", "category", "subcategory", "model_number", "price",
              "price_max", "original_price", "description", "features", "badge"):
        setattr(p, f, getattr(data, f))
    p.in_stock = 1 if data.in_stock else 0
    p.images = list(data.images)
    p.image = data.images[0] if data.images else "placeholder.jpg"
    p.admin_managed = 1


def _slugify(text_: str) -> str:
    s = text_.lower().replace("×", "x").replace("°", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80].strip("-") or "product"


def _unique_slug(db: Session, base: str) -> str:
    slug, n = base, 2
    while db.query(Product.id).filter(Product.slug == slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


@router.get("/admin/products")
def list_products(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    products = db.query(Product).order_by(Product.category, Product.name).all()
    return {
        "products": [_product_json(p) for p in products],
        "categories": [{"value": k, "label": v} for k, v in CATEGORY_LABELS.items()],
        "subcategories": CATEGORY_SUBCATEGORIES,
        "badges": BADGES,
    }


@router.post("/admin/products", status_code=201)
def create_product(data: ProductIn, _: str = Depends(require_admin_write),
                   db: Session = Depends(get_db)):
    data.check_relations()
    p = Product(slug=_unique_slug(db, _slugify(data.name)))
    _apply(p, data)
    # Re-using a slug that was deleted earlier: the new product owns it now.
    db.query(RemovedProduct).filter(RemovedProduct.slug == p.slug).delete()
    db.add(p)
    db.commit()
    db.refresh(p)
    return _product_json(p)


@router.put("/admin/products/{product_id}")
def update_product(product_id: int, data: ProductIn, _: str = Depends(require_admin_write),
                   db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    data.check_relations()
    _apply(p, data)   # slug never changes: links and saved carts depend on it
    db.commit()
    db.refresh(p)
    return _product_json(p)


@router.delete("/admin/products/{product_id}")
def delete_product(product_id: int, _: str = Depends(require_admin_write),
                   db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    if not db.query(RemovedProduct).filter(RemovedProduct.slug == p.slug).first():
        db.add(RemovedProduct(slug=p.slug))
    db.delete(p)
    db.commit()
    return {"message": f"Deleted {p.name}"}


def _sniff_image(head: bytes) -> Optional[str]:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


@router.post("/admin/uploads", status_code=201)
async def upload_image(file: UploadFile = File(...), _: str = Depends(require_admin_write)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Photo is too large (6 MB max)")
    ext = _sniff_image(data[:16])
    if not ext:
        raise HTTPException(status_code=415, detail="Only JPG, PNG or WebP photos")
    # Content-addressed: the same photo uploaded twice is stored once, and a
    # name never points at different bytes, so the dimension caches stay valid.
    name = hashlib.sha256(data).hexdigest()[:20] + "." + ext
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    dest = os.path.join(UPLOADS_DIR, name)
    if not os.path.exists(dest):
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
    rel = f"{UPLOAD_SUBDIR}/{name}"
    return {"image": rel, "url": "/static/images/" + rel}

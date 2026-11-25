"""Shipping, freight and coupons: the one place these rules live.

The checkout page receives the same numbers (see ``checkout_config``) so its
live totals match what the server records; the server recomputes every order
total itself rather than trusting the figure the browser sends.
"""
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
#  Shipping
# --------------------------------------------------------------------------- #

# US orders: free above the threshold, flat fee below it.
FREE_SHIP_THRESHOLD = 1000
FLAT_SHIPPING = 150

# (region, freight fee). The first entry is domestic (no freight; the US rule
# above applies). Order here is the order of the checkout dropdown.
FREIGHT_REGIONS = [
    ("United States", 0),
    ("Canada / Mexico", 250),
    ("Europe / UK", 600),
    ("Africa", 600),
    ("Asia", 750),
    ("Middle East", 800),
    ("Australia / New Zealand", 850),
    ("South America", 800),
    ("Other International", 900),
]
_FREIGHT = dict(FREIGHT_REGIONS)
DOMESTIC_REGION = FREIGHT_REGIONS[0][0]

# --------------------------------------------------------------------------- #
#  Coupons
# --------------------------------------------------------------------------- #

# code -> settings. Codes are matched case-insensitively. ``percent`` comes off
# the items subtotal only (never shipping or freight). ``billboard`` puts the
# promotion on the homepage while it is active. ``ends`` is exclusive, UTC.
COUPONS = {
    "BLACKFRIDAY": {
        "percent": 10,
        "label": "Black Friday",
        "starts": None,
        # Monday 30 Nov 2026, 11:59pm Pacific — the end of Cyber Monday.
        "ends": datetime(2026, 12, 1, 8, 0, tzinfo=timezone.utc),
        "ends_text": "Cyber Monday, Nov 30",
        "billboard": True,
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def find_coupon(code: str, now: datetime = None):
    """The active coupon for ``code`` as a dict (with ``code``), or None."""
    code = (code or "").strip().upper()
    c = COUPONS.get(code)
    if not c:
        return None
    now = now or _now()
    if c["starts"] and now < c["starts"]:
        return None
    if c["ends"] and now >= c["ends"]:
        return None
    return {"code": code, **c}


def billboard_promo(now: datetime = None):
    """The coupon to feature on the homepage right now, or None."""
    for code, c in COUPONS.items():
        if c.get("billboard") and find_coupon(code, now):
            return find_coupon(code, now)
    return None


# --------------------------------------------------------------------------- #
#  Totals
# --------------------------------------------------------------------------- #

def compute_totals(items, freight_region: str, coupon_code: str = "", now: datetime = None) -> dict:
    """Subtotal, discount, shipping, freight and total for a cart.

    ``items`` are dicts or objects with ``price`` and ``qty``. The free-shipping
    threshold is judged on the subtotal *before* the coupon, so applying a
    discount can never make an order start paying shipping.
    """
    def get(it, key, default):
        return it.get(key, default) if isinstance(it, dict) else getattr(it, key, default)

    subtotal = round(sum(float(get(i, "price", 0) or 0) * int(get(i, "qty", 1) or 1) for i in items), 2)
    region = freight_region if freight_region in _FREIGHT else DOMESTIC_REGION
    freight = float(_FREIGHT[region])
    domestic = region == DOMESTIC_REGION
    if not items or not domestic or subtotal > FREE_SHIP_THRESHOLD:
        shipping = 0.0
    else:
        shipping = float(FLAT_SHIPPING)
    coupon = find_coupon(coupon_code, now) if items else None
    discount = round(subtotal * coupon["percent"] / 100, 2) if coupon else 0.0
    return {
        "subtotal": subtotal,
        "discount": discount,
        "coupon": coupon["code"] if coupon else "",
        "shipping": shipping,
        "freight": freight,
        "region": region,
        "total": round(subtotal - discount + shipping + freight, 2),
    }


def checkout_config() -> dict:
    """What the browser needs to show the same totals the server computes."""
    return {"freeShip": FREE_SHIP_THRESHOLD, "flatShip": FLAT_SHIPPING}

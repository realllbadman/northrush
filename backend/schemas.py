"""Pydantic schemas for the JSON API."""
from typing import List, Optional

from pydantic import BaseModel, Field


class CartItem(BaseModel):
    slug: str
    name: str
    price: float
    qty: int = Field(1, ge=1)
    image: Optional[str] = None


class InquiryCreate(BaseModel):
    first_name: str
    last_name: str = ""
    phone: str = ""
    email: str = ""
    company: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "United States"
    freight_region: str = "United States"
    contact_pref: str = "Phone"
    best_time: str = ""
    payment_method: str = "Cash App"
    notes: str = ""
    items: List[CartItem] = []
    coupon: str = Field("", max_length=40)
    total: float = 0.0         # ignored: the server recomputes it (pricing.py)
    website: str = ""          # honeypot — humans leave this empty


class BookingCreate(BaseModel):
    first_name: str
    last_name: str = ""
    phone: str = ""
    email: str = ""
    service: str = "General"
    product_interest: str = ""
    details: str = ""
    website: str = ""          # honeypot — humans leave this empty


class MessageOut(BaseModel):
    message: str
    id: Optional[int] = None    # order number — used as the ad conversion's transaction_id
    total: Optional[float] = None   # server-computed order value

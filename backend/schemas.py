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
    payment_method: str = "Bank Transfer"
    notes: str = ""
    items: List[CartItem] = []
    total: float = 0.0
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

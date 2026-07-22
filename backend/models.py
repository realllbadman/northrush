"""ORM models: Product (catalog), Inquiry (orders/quotes), Booking (services)."""
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text

from backend.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    brand = Column(String, default="")
    category = Column(String, index=True, default="")
    subcategory = Column(String, index=True, default="")
    model_number = Column(String, default="")          # "·"-joined spec string
    price = Column(Float, default=0.0)
    price_max = Column(Float, nullable=True)
    original_price = Column(Float, nullable=True)      # strike-through price
    description = Column(Text, default="")
    features = Column(JSON, default=list)              # list[str]
    in_stock = Column(Integer, default=1)              # 1/0
    badge = Column(String, nullable=True)              # Best Seller / New / Sale / Hot Deal
    image = Column(Text, default="placeholder.jpg")    # primary = first of images
    images = Column(JSON, default=list)                # list[str]


class Inquiry(Base):
    """Order / quote request submitted from checkout."""
    __tablename__ = "inquiries"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, default="")
    last_name = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    company = Column(String, default="")
    address = Column(String, default="")
    city = Column(String, default="")
    state = Column(String, default="")
    zip = Column(String, default="")
    country = Column(String, default="")
    freight_region = Column(String, default="")
    contact_pref = Column(String, default="")          # Phone / Text / Email
    best_time = Column(String, default="")
    payment_method = Column(String, default="")        # Bank Transfer / Zelle / PayPal / Other
    notes = Column(Text, default="")
    items = Column(JSON, default=list)                 # cart line items
    total = Column(Float, default=0.0)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)


class Booking(Base):
    """Install / consultation / general message."""
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, default="")
    last_name = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    service = Column(String, default="")
    product_interest = Column(String, default="")
    details = Column(Text, default="")
    status = Column(String, default="new")
    created_at = Column(DateTime, default=datetime.utcnow)

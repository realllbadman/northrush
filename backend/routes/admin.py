"""Admin JSON API — HTTP Basic auth with constant-time credential compare."""
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Booking, Inquiry

router = APIRouter(tags=["admin"])
security = HTTPBasic()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    user_ok = secrets.compare_digest(credentials.username.encode(), ADMIN_USERNAME.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


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
def delete_inquiry(inquiry_id: int, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    inq = db.query(Inquiry).filter(Inquiry.id == inquiry_id).first()
    if not inq:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    db.delete(inq)
    db.commit()
    return {"message": f"Inquiry #{inquiry_id} deleted"}


@router.delete("/admin/bookings/{booking_id}")
def delete_booking(booking_id: int, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    bk = db.query(Booking).filter(Booking.id == booking_id).first()
    if not bk:
        raise HTTPException(status_code=404, detail="Booking not found")
    db.delete(bk)
    db.commit()
    return {"message": f"Booking #{booking_id} deleted"}

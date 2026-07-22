"""POST /bookings/ — save an install/consultation/general request and notify the owner."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Booking
from backend.schemas import BookingCreate, MessageOut
from backend.services.email import format_booking, send_owner_email

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("/", response_model=MessageOut)
async def create_booking(payload: BookingCreate, db: Session = Depends(get_db)):
    bk = Booking(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        phone=payload.phone.strip(),
        email=payload.email.strip(),
        service=payload.service.strip() or "General",
        product_interest=payload.product_interest.strip(),
        details=payload.details.strip(),
    )
    db.add(bk)
    db.commit()
    db.refresh(bk)

    await send_owner_email(
        f"NorthRush {bk.service} request #{bk.id} — {bk.first_name} {bk.last_name}".strip(),
        format_booking(bk),
    )
    return {"message": "Thanks! Your request is in — we'll get back to you within one business day."}

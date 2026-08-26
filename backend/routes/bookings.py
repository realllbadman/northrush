"""POST /bookings/ — save an install/consultation/general request and notify the owner."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Booking
from backend.schemas import BookingCreate, MessageOut
from backend.services.antispam import enforce_rate_limit, is_bot
from backend.services.email import (
    BUSINESS_NAME,
    OWNER_EMAIL,
    format_booking,
    format_booking_html,
    format_customer_booking,
    format_customer_booking_html,
    send_email,
    send_owner_email,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("/", response_model=MessageOut)
async def create_booking(
    payload: BookingCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    enforce_rate_limit(request)
    if is_bot(payload, request):
        return {"message": "Thanks! Your request is in — we'll get back to you within one business day."}

    bk = Booking(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        phone=payload.phone.strip(),
        email=payload.email.strip().lower(),
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
        html_body=format_booking_html(bk),
        reply_to=bk.email or None,
    )

    # Customer confirmation — owner is bcc'd so both sides land in one inbox.
    if bk.email:
        await send_email(
            f"Thanks for your message — {BUSINESS_NAME}",
            format_customer_booking(bk),
            bk.email,
            html_body=format_customer_booking_html(bk),
            reply_to=OWNER_EMAIL,
            bcc=OWNER_EMAIL,
        )
    return {"message": "Thanks! Your request is in — we'll get back to you within one business day."}

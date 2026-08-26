"""POST /inquiries/ — save an order inquiry and notify the owner."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Inquiry
from backend.schemas import InquiryCreate, MessageOut
from backend.services.antispam import enforce_rate_limit, is_bot
from backend.services.email import BUSINESS_NAME
from backend.services.email import (
    OWNER_EMAIL,
    format_customer_inquiry,
    format_customer_inquiry_html,
    format_inquiry,
    format_inquiry_html,
    send_email,
    send_owner_email,
)

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


@router.post("/", response_model=MessageOut)
async def create_inquiry(
    payload: InquiryCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    enforce_rate_limit(request)
    if is_bot(payload, request):
        # Same reply a human gets — never confirm the trap to a bot.
        return {"message": "Order received! We'll contact you shortly to confirm and arrange payment."}

    inq = Inquiry(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        phone=payload.phone.strip(),
        email=payload.email.strip().lower(),
        company=payload.company.strip(),
        address=payload.address.strip(),
        city=payload.city.strip(),
        state=payload.state.strip(),
        zip=payload.zip.strip(),
        country=payload.country.strip(),
        freight_region=payload.freight_region,
        contact_pref=payload.contact_pref,
        best_time=payload.best_time.strip(),
        payment_method=payload.payment_method,
        notes=payload.notes.strip(),
        items=[it.model_dump() for it in payload.items],
        total=payload.total,
    )
    db.add(inq)
    db.commit()
    db.refresh(inq)

    await send_owner_email(
        f"NorthRush order inquiry #{inq.id} — ${inq.total:,.2f}",
        format_inquiry(inq),
        html_body=format_inquiry_html(inq),
        reply_to=inq.email or None,
    )

    # Customer confirmation — owner is bcc'd so both sides land in one inbox.
    if inq.email:
        await send_email(
            f"We've got your order request #{inq.id} — {BUSINESS_NAME}",
            format_customer_inquiry(inq),
            inq.email,
            html_body=format_customer_inquiry_html(inq),
            reply_to=OWNER_EMAIL,
            bcc=OWNER_EMAIL,
        )
    return {"message": "Order received! We'll contact you shortly to confirm and arrange payment."}

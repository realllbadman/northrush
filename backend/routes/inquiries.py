"""POST /inquiries/ — save an order inquiry and notify the owner."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Inquiry
from backend.schemas import InquiryCreate, MessageOut
from backend.services.email import format_inquiry, send_owner_email

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


@router.post("/", response_model=MessageOut)
async def create_inquiry(payload: InquiryCreate, db: Session = Depends(get_db)):
    inq = Inquiry(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        phone=payload.phone.strip(),
        email=payload.email.strip(),
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
    )
    return {"message": "Order received! We'll contact you shortly to confirm and arrange payment."}

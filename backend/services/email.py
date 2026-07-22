"""Async owner-notification email via Gmail SMTP (STARTTLS:587).

If SMTP is not configured the send becomes a logged no-op — a missing
password must never crash a customer-facing request.
"""
import logging
import os
from email.message import EmailMessage

import aiosmtplib
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("northrush.email")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
# Gmail app passwords are shown with spaces — strip them or auth fails.
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
OWNER_EMAIL = os.getenv("OWNER_EMAIL", SMTP_USER)


def _configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD and OWNER_EMAIL)


async def send_owner_email(subject: str, body: str) -> bool:
    """Send a plain-text notification to the owner. Returns True on success."""
    if not _configured():
        log.warning("SMTP not configured — skipping email %r", subject)
        return False

    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = OWNER_EMAIL
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            start_tls=True,
            timeout=20,
        )
        log.info("email sent: %s", subject)
        return True
    except Exception:  # noqa: BLE001 — email must never break a request
        log.exception("email send failed: %s", subject)
        return False


def format_inquiry(inq) -> str:
    lines = [
        f"New order inquiry #{inq.id} — {inq.first_name} {inq.last_name}".strip(),
        "",
        f"Phone:    {inq.phone}",
        f"Email:    {inq.email}",
        f"Company:  {inq.company}" if inq.company else None,
        f"Address:  {inq.address}, {inq.city}, {inq.state} {inq.zip}, {inq.country}",
        f"Freight:  {inq.freight_region}",
        f"Contact:  {inq.contact_pref}" + (f" ({inq.best_time})" if inq.best_time else ""),
        f"Payment:  {inq.payment_method}",
        "",
        "Items:",
    ]
    for it in inq.items or []:
        lines.append(f"  - {it.get('qty', 1)} x {it.get('name')} @ ${it.get('price', 0):,.2f}")
    lines += ["", f"TOTAL: ${inq.total:,.2f}"]
    if inq.notes:
        lines += ["", f"Notes: {inq.notes}"]
    return "\n".join(l for l in lines if l is not None)


def format_booking(bk) -> str:
    lines = [
        f"New {bk.service} request #{bk.id} — {bk.first_name} {bk.last_name}".strip(),
        "",
        f"Phone:   {bk.phone}",
        f"Email:   {bk.email}",
        f"Service: {bk.service}",
        f"Product: {bk.product_interest}" if bk.product_interest else None,
        "",
        bk.details or "(no details)",
    ]
    return "\n".join(l for l in lines if l is not None)

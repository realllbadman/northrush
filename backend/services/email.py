"""Async owner-notification email via Gmail SMTP (STARTTLS:587).

Every notification goes out as multipart/alternative: a branded HTML body
built from the same forest+amber tokens as static/css/main.css, with the
plain-text version as the fallback half.

If SMTP is not configured the send becomes a logged no-op — a missing
password must never crash a customer-facing request.
"""
import html
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

BUSINESS_NAME = os.getenv("BUSINESS_NAME", "NorthRush Outdoors")
BUSINESS_PHONE = os.getenv("OWNER_PHONE", "")
BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", OWNER_EMAIL)
BUSINESS_HOURS = os.getenv("BUSINESS_HOURS", "Mon-Sat 8am-6pm CT")

# --------------------------------------------------------------------------- #
#  Design tokens — mirror :root in static/css/main.css
# --------------------------------------------------------------------------- #
FOREST     = "#1f4d3a"
FOREST_DK  = "#163a2c"
AMBER      = "#e08a2b"
AMBER_DK   = "#c47420"
CANVAS     = "#f7f5f0"
INK        = "#16241d"
MUTED      = "#6b7580"
BORDER     = "#e6e3db"
SUBTLE     = "#faf9f6"
FONT       = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
              "Helvetica,Arial,sans-serif")


def _configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD and OWNER_EMAIL)


def _same_mailbox(a, b) -> bool:
    """Gmail plus-aliases and case both resolve to one inbox — don't double-send."""
    def norm(x):
        x = (x or "").strip().lower()
        if "@" not in x:
            return x
        local, _, domain = x.partition("@")
        return f"{local.split('+')[0]}@{domain}"
    return bool(a) and norm(a) == norm(b)


async def send_email(subject, body, to, html_body=None, reply_to=None, bcc=None) -> bool:
    """Send one notification. Returns True on success."""
    if not _configured():
        log.warning("SMTP not configured — skipping email %r", subject)
        return False
    if not to:
        log.warning("no recipient — skipping email %r", subject)
        return False

    msg = EmailMessage()
    msg["From"] = f"{BUSINESS_NAME} <{SMTP_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    # bcc stays out of the headers — passed as an envelope recipient only
    recipients = [to] + ([bcc] if bcc and not _same_mailbox(bcc, to) else [])

    try:
        await aiosmtplib.send(
            msg,
            recipients=recipients,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            start_tls=True,
            timeout=20,
        )
        log.info("email sent: %s -> %s", subject, ", ".join(recipients))
        return True
    except Exception:  # noqa: BLE001 — email must never break a request
        log.exception("email send failed: %s", subject)
        return False


async def send_owner_email(subject, body, html_body=None, reply_to=None) -> bool:
    """Notify the owner."""
    return await send_email(subject, body, OWNER_EMAIL,
                            html_body=html_body, reply_to=reply_to)


# --------------------------------------------------------------------------- #
#  HTML building blocks (tables + inline styles — the only thing mail clients
#  render consistently)
# --------------------------------------------------------------------------- #

def _esc(v) -> str:
    """Everything here is customer-supplied — escape without exception."""
    return html.escape(str(v if v is not None else "")).strip()


def _money(n) -> str:
    try:
        return f"${float(n):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _when(dt) -> str:
    if not dt:
        return ""
    stamp = dt.strftime("%b %-d, %Y at %-I:%M %p") if os.name != "nt" else dt.strftime("%b %d, %Y")
    return stamp


def _eyebrow(text) -> str:
    """The .section__eyebrow treatment: amber, uppercase, wide tracking."""
    return (
        f'<tr><td style="padding:26px 28px 10px;font:800 12px/1.2 {FONT};'
        f'letter-spacing:.14em;text-transform:uppercase;color:{AMBER_DK};">'
        f'{_esc(text)}</td></tr>'
    )


def _field(label, value, link=None) -> str:
    """One label/value row. Skipped entirely when the value is empty."""
    value = _esc(value)
    if not value:
        return ""
    if link:
        value = f'<a href="{link}" style="color:{FOREST};text-decoration:none;">{value}</a>'
    return (
        f'<tr>'
        f'<td width="34%" style="padding:7px 28px 7px 28px;font:600 14px/1.5 {FONT};'
        f'color:{MUTED};vertical-align:top;">{_esc(label)}</td>'
        f'<td style="padding:7px 28px 7px 0;font:600 14px/1.5 {FONT};color:{INK};'
        f'vertical-align:top;">{value}</td>'
        f'</tr>'
    )


def _divider() -> str:
    return (f'<tr><td colspan="2" style="padding:14px 28px 0;">'
            f'<div style="height:1px;background:{BORDER};line-height:1px;">&nbsp;</div>'
            f'</td></tr>')


def _shell(kicker, headline, hero_label, hero_value, sections_html, preheader,
           footer_note="Automated notification from your storefront. Reply to this email to answer the customer directly.") -> str:
    """Wrap content in the branded header/footer chrome."""
    phone_line = f' &middot; {_esc(BUSINESS_PHONE)}' if BUSINESS_PHONE else ""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{_esc(headline)}</title>
</head>
<body style="margin:0;padding:0;background:{CANVAS};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_esc(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{CANVAS};padding:24px 12px;">
<tr><td align="center">

<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid {BORDER};border-radius:16px;overflow:hidden;">

  <!-- Brand band -->
  <tr><td style="background:{FOREST_DK};padding:22px 28px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
      <td style="vertical-align:middle;">
        <div style="font:800 19px/1 {FONT};letter-spacing:.06em;color:#ffffff;">NORTHRUSH</div>
        <div style="font:700 9px/1 {FONT};letter-spacing:.42em;color:{AMBER};padding-top:5px;">OUTDOORS</div>
      </td>
      <td align="right" style="vertical-align:middle;font:800 11px/1.4 {FONT};letter-spacing:.12em;text-transform:uppercase;color:#9fb5a8;">
        {_esc(kicker)}
      </td>
    </tr></table>
  </td></tr>
  <tr><td style="background:{AMBER};height:4px;line-height:4px;font-size:0;">&nbsp;</td></tr>

  <!-- Hero -->
  <tr><td style="padding:26px 28px 22px;background:{SUBTLE};border-bottom:1px solid {BORDER};">
    <div style="font:800 21px/1.3 {FONT};color:{INK};">{_esc(headline)}</div>
    <div style="font:600 12px/1.2 {FONT};letter-spacing:.1em;text-transform:uppercase;color:{MUTED};padding-top:14px;">{_esc(hero_label)}</div>
    <div style="font:800 30px/1.15 {FONT};color:{FOREST};padding-top:4px;">{hero_value}</div>
  </td></tr>

  {sections_html}

  <!-- Footer -->
  <tr><td style="background:{FOREST_DK};padding:22px 28px;">
    <div style="font:800 13px/1.4 {FONT};color:#ffffff;">{_esc(BUSINESS_NAME)}</div>
    <div style="font:400 12px/1.7 {FONT};color:#9fb5a8;padding-top:5px;">
      {_esc(BUSINESS_HOURS)}{phone_line}
    </div>
    <div style="font:400 11px/1.6 {FONT};color:#7d968a;padding-top:12px;">
      {_esc(footer_note)}
    </div>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# --------------------------------------------------------------------------- #
#  Order inquiries
# --------------------------------------------------------------------------- #

def format_inquiry(inq) -> str:
    """Plain-text fallback."""
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


def format_inquiry_html(inq) -> str:
    name = f"{inq.first_name} {inq.last_name}".strip()
    items = inq.items or []

    # Items table
    rows = ""
    for it in items:
        qty = it.get("qty", 1) or 1
        price = float(it.get("price", 0) or 0)
        rows += (
            f'<tr>'
            f'<td style="padding:11px 10px 11px 0;font:600 14px/1.45 {FONT};color:{INK};'
            f'border-bottom:1px solid {BORDER};">{_esc(it.get("name"))}'
            f'<div style="font:400 12px/1.4 {FONT};color:{MUTED};padding-top:3px;">'
            f'{qty} &times; {_money(price)}</div></td>'
            f'<td align="right" style="padding:11px 0;font:700 14px/1.45 {FONT};color:{INK};'
            f'border-bottom:1px solid {BORDER};white-space:nowrap;">{_money(price * qty)}</td>'
            f'</tr>'
        )
    if not rows:
        rows = (f'<tr><td style="font:400 14px/1.5 {FONT};color:{MUTED};padding:11px 0;">'
                f'(no line items)</td><td></td></tr>')

    subtotal = sum(float(i.get("price", 0) or 0) * (i.get("qty", 1) or 1) for i in items)
    extra = float(inq.total or 0) - subtotal

    totals = (
        f'<tr><td style="padding:12px 10px 0 0;font:600 13px/1.5 {FONT};color:{MUTED};">'
        f'Items subtotal</td>'
        f'<td align="right" style="padding:12px 0 0;font:600 13px/1.5 {FONT};color:{INK};">'
        f'{_money(subtotal)}</td></tr>'
    )
    if abs(extra) >= 0.01:
        totals += (
            f'<tr><td style="padding:5px 10px 0 0;font:600 13px/1.5 {FONT};color:{MUTED};">'
            f'Shipping &amp; freight</td>'
            f'<td align="right" style="padding:5px 0 0;font:600 13px/1.5 {FONT};color:{INK};">'
            f'{_money(extra)}</td></tr>'
        )

    # Raw values only — _field() does the escaping, so pre-escaping here
    # would double-encode (& -> &amp;amp;).
    address = ", ".join(part for part in [
        (inq.address or "").strip(), (inq.city or "").strip(),
        f"{inq.state or ''} {inq.zip or ''}".strip(), (inq.country or "").strip()
    ] if part)

    contact = (inq.contact_pref or "").strip()
    if inq.best_time:
        contact = f"{contact} · {inq.best_time}".strip(" · ")

    sections = _eyebrow("Customer")
    sections += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
    sections += _field("Name", name)
    sections += _field("Phone", inq.phone, link=f"tel:{_esc(inq.phone).replace(' ', '')}" if inq.phone else None)
    sections += _field("Email", inq.email, link=f"mailto:{_esc(inq.email)}" if inq.email else None)
    sections += _field("Company", inq.company)
    sections += '</table>'

    sections += _eyebrow("Delivery")
    sections += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
    sections += _field("Address", address)
    sections += _field("Freight region", inq.freight_region)
    sections += '</table>'

    sections += _eyebrow("How to reach them")
    sections += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
    sections += _field("Preference", contact)
    sections += _field("Payment", inq.payment_method)
    sections += '</table>'

    sections += _eyebrow(f"Items ordered ({len(items)})")
    sections += (
        f'<tr><td style="padding:2px 28px 4px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'{rows}{totals}</table>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin-top:16px;background:{FOREST};border-radius:10px;"><tr>'
        f'<td style="padding:14px 16px;font:800 12px/1.2 {FONT};letter-spacing:.1em;'
        f'text-transform:uppercase;color:#bcd3c6;">Order total</td>'
        f'<td align="right" style="padding:14px 16px;font:800 20px/1.2 {FONT};color:#ffffff;">'
        f'{_money(inq.total)}</td>'
        f'</tr></table></td></tr>'
    )

    if inq.notes:
        sections += _eyebrow("Customer notes")
        sections += (
            f'<tr><td style="padding:2px 28px 4px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background:#fdf6ec;border-left:3px solid {AMBER};border-radius:0 8px 8px 0;">'
            f'<tr><td style="padding:14px 16px;font:400 14px/1.65 {FONT};color:{INK};">'
            f'{_esc(inq.notes)}</td></tr></table></td></tr>'
        )

    sections += f'<tr><td style="height:26px;line-height:26px;font-size:0;">&nbsp;</td></tr>'

    return _shell(
        kicker=f"Order inquiry #{inq.id}",
        headline=f"New order from {name or 'a customer'}",
        hero_label=_when(inq.created_at) or "Order total",
        hero_value=_money(inq.total),
        sections_html=sections,
        preheader=f"{name} — {_money(inq.total)} — {len(items)} item(s)",
    )


# --------------------------------------------------------------------------- #
#  Bookings / messages
# --------------------------------------------------------------------------- #

def format_booking(bk) -> str:
    """Plain-text fallback."""
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


def format_booking_html(bk) -> str:
    name = f"{bk.first_name} {bk.last_name}".strip()

    sections = _eyebrow("Customer")
    sections += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
    sections += _field("Name", name)
    sections += _field("Phone", bk.phone, link=f"tel:{_esc(bk.phone).replace(' ', '')}" if bk.phone else None)
    sections += _field("Email", bk.email, link=f"mailto:{_esc(bk.email)}" if bk.email else None)
    sections += _field("Enquiry type", bk.service)
    sections += _field("Product interest", bk.product_interest)
    sections += '</table>'

    sections += _eyebrow("Message")
    sections += (
        f'<tr><td style="padding:2px 28px 4px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#fdf6ec;border-left:3px solid {AMBER};border-radius:0 8px 8px 0;">'
        f'<tr><td style="padding:15px 17px;font:400 14px/1.7 {FONT};color:{INK};">'
        f'{_esc(bk.details) or "(no details provided)"}</td></tr></table></td></tr>'
    )
    sections += f'<tr><td style="height:26px;line-height:26px;font-size:0;">&nbsp;</td></tr>'

    return _shell(
        kicker=f"{bk.service} request #{bk.id}",
        headline=f"New enquiry from {name or 'a customer'}",
        hero_label=_when(bk.created_at) or "Enquiry type",
        hero_value=f'<span style="font-size:22px;">{_esc(bk.service)}</span>',
        sections_html=sections,
        preheader=f"{name} — {bk.service}",
    )


# --------------------------------------------------------------------------- #
#  Customer-facing confirmations
# --------------------------------------------------------------------------- #

CUSTOMER_FOOTER = ("You're receiving this because you submitted a request at "
                   "northrush.com. Reply to this email and it reaches us directly.")


def _steps(items) -> str:
    """Numbered 'what happens next' list."""
    out = (f'<tr><td style="padding:2px 28px 4px;">'
           f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">')
    for n, (title, blurb) in enumerate(items, 1):
        out += (
            f'<tr>'
            f'<td width="30" style="vertical-align:top;padding:6px 0;">'
            f'<div style="width:22px;height:22px;background:{FOREST};border-radius:11px;'
            f'font:800 12px/22px {FONT};color:#ffffff;text-align:center;">{n}</div></td>'
            f'<td style="padding:6px 0 6px 10px;">'
            f'<div style="font:700 14px/1.45 {FONT};color:{INK};">{_esc(title)}</div>'
            f'<div style="font:400 13px/1.6 {FONT};color:{MUTED};padding-top:2px;">{_esc(blurb)}</div>'
            f'</td></tr>'
        )
    return out + '</table></td></tr>'


def format_customer_inquiry(inq) -> str:
    """Plain-text customer confirmation."""
    lines = [
        f"Thanks {inq.first_name} — we've received your order request #{inq.id}.",
        "",
        "Nothing has been charged. This is a request, not a payment.",
        "",
        "What happens next:",
        "  1. We confirm stock and work out exact freight to your address.",
        f"  2. We contact you by {inq.contact_pref or 'phone'} to go through the details.",
        "  3. Once you're happy, we arrange payment and book the delivery.",
        "",
        "Your order:",
    ]
    for it in inq.items or []:
        lines.append(f"  - {it.get('qty', 1)} x {it.get('name')} @ ${it.get('price', 0):,.2f}")
    lines += ["", f"ESTIMATED TOTAL: ${inq.total:,.2f}",
              "(Final freight is confirmed before any payment.)", ""]
    if inq.address:
        lines += [f"Delivering to: {inq.address}, {inq.city}, {inq.state} {inq.zip}", ""]
    lines += [f"Questions? Call {BUSINESS_PHONE}" if BUSINESS_PHONE else "",
              f"{BUSINESS_NAME} · {BUSINESS_HOURS}"]
    return "\n".join(l for l in lines if l)


def format_customer_inquiry_html(inq) -> str:
    items = inq.items or []

    rows = ""
    for it in items:
        qty = it.get("qty", 1) or 1
        price = float(it.get("price", 0) or 0)
        rows += (
            f'<tr>'
            f'<td style="padding:11px 10px 11px 0;font:600 14px/1.45 {FONT};color:{INK};'
            f'border-bottom:1px solid {BORDER};">{_esc(it.get("name"))}'
            f'<div style="font:400 12px/1.4 {FONT};color:{MUTED};padding-top:3px;">'
            f'{qty} &times; {_money(price)}</div></td>'
            f'<td align="right" style="padding:11px 0;font:700 14px/1.45 {FONT};color:{INK};'
            f'border-bottom:1px solid {BORDER};white-space:nowrap;">{_money(price * qty)}</td>'
            f'</tr>'
        )

    sections = _eyebrow("What happens next")
    sections += _steps([
        ("We check stock and freight",
         "We confirm availability and work out the exact delivery cost to your address."),
        (f"We contact you by {(inq.contact_pref or 'phone').lower()}",
         f"{'Best time noted: ' + inq.best_time if inq.best_time else 'Usually within one business day.'}"),
        ("You approve, then we arrange payment",
         f"Preferred method noted: {inq.payment_method or 'to be confirmed'}. Nothing is charged until you say go."),
    ])

    sections += _eyebrow(f"Your order (#{inq.id})")
    sections += (
        f'<tr><td style="padding:2px 28px 4px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin-top:16px;background:{FOREST};border-radius:10px;"><tr>'
        f'<td style="padding:14px 16px;font:800 12px/1.2 {FONT};letter-spacing:.1em;'
        f'text-transform:uppercase;color:#bcd3c6;">Estimated total</td>'
        f'<td align="right" style="padding:14px 16px;font:800 20px/1.2 {FONT};color:#ffffff;">'
        f'{_money(inq.total)}</td></tr></table>'
        f'<div style="font:400 12px/1.6 {FONT};color:{MUTED};padding-top:9px;">'
        f'Final freight is confirmed with you before any payment is taken.</div>'
        f'</td></tr>'
    )

    address = ", ".join(part for part in [
        (inq.address or "").strip(), (inq.city or "").strip(),
        f"{inq.state or ''} {inq.zip or ''}".strip(), (inq.country or "").strip()
    ] if part)
    if address:
        sections += _eyebrow("Delivering to")
        sections += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        sections += _field("Address", address)
        sections += _field("Something wrong?", "Just reply to this email and we'll fix it.")
        sections += '</table>'

    sections += f'<tr><td style="height:26px;line-height:26px;font-size:0;">&nbsp;</td></tr>'

    return _shell(
        kicker=f"Order request #{inq.id}",
        headline=f"Thanks {_esc(inq.first_name) or 'for your order'} — we've got it",
        hero_label="Estimated total · nothing charged yet",
        hero_value=_money(inq.total),
        sections_html=sections,
        preheader=f"We've received order #{inq.id} — {_money(inq.total)}. Nothing has been charged.",
        footer_note=CUSTOMER_FOOTER,
    )


def format_customer_booking(bk) -> str:
    """Plain-text customer confirmation."""
    return "\n".join(l for l in [
        f"Thanks {bk.first_name} — we've received your message.",
        "",
        "A real person reads every one of these. We'll get back to you within",
        "one business day.",
        "",
        f"Your enquiry ({bk.service}):",
        f"  {bk.details or '(no details)'}",
        "",
        f"Product of interest: {bk.product_interest}" if bk.product_interest else "",
        f"Need us sooner? Call {BUSINESS_PHONE}" if BUSINESS_PHONE else "",
        f"{BUSINESS_NAME} · {BUSINESS_HOURS}",
    ] if l)


def format_customer_booking_html(bk) -> str:
    sections = _eyebrow("What happens next")
    sections += _steps([
        ("A real hunter reads it", "Not a bot — someone who has sat in the blinds we sell."),
        ("We reply within one business day", f"During {BUSINESS_HOURS}."),
        ("We answer straight", "Freight, lead times, or which blind actually suits your land."),
    ])

    sections += _eyebrow("What you sent us")
    sections += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
    sections += _field("Topic", bk.service)
    sections += _field("Product", bk.product_interest)
    sections += '</table>'
    sections += (
        f'<tr><td style="padding:10px 28px 4px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#fdf6ec;border-left:3px solid {AMBER};border-radius:0 8px 8px 0;">'
        f'<tr><td style="padding:15px 17px;font:400 14px/1.7 {FONT};color:{INK};">'
        f'{_esc(bk.details) or "(no details provided)"}</td></tr></table></td></tr>'
    )
    sections += f'<tr><td style="height:26px;line-height:26px;font-size:0;">&nbsp;</td></tr>'

    return _shell(
        kicker=f"Enquiry #{bk.id} received",
        headline=f"Thanks {_esc(bk.first_name) or 'for getting in touch'} — message received",
        hero_label="We reply within",
        hero_value='<span style="font-size:22px;">One business day</span>',
        sections_html=sections,
        preheader="We've got your message and we'll reply within one business day.",
        footer_note=CUSTOMER_FOOTER,
    )

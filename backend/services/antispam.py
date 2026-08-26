"""Spam defences for the two public POST endpoints.

Two independent layers:

1. Honeypot — a field hidden from humans by CSS. Bots fill every input they
   find, so a non-empty value means "not a person". We accept the request
   with a normal success message and quietly drop it, because telling a bot
   it failed only teaches it to retry.

2. Per-IP rate limit — a sliding window over recent submissions. State is
   in-process, so with gunicorn -w N each worker keeps its own counter and
   the effective limit is N x MAX_PER_WINDOW. That is fine for stopping a
   flood; it is not a precise quota. Move to Redis if that ever matters.
"""
import logging
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

log = logging.getLogger("northrush.antispam")

WINDOW_SECONDS = 15 * 60      # 15 minutes
MAX_PER_WINDOW = 5            # submissions per IP per window
PRUNE_EVERY = 500             # sweep idle IPs every N checks

_hits: dict = defaultdict(deque)
_checks = 0


def client_ip(request: Request) -> str:
    """Real client IP, honouring the X-Forwarded-For that Nginx sets."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(now: float) -> None:
    for ip in [ip for ip, hits in _hits.items() if not hits or now - hits[-1] > WINDOW_SECONDS]:
        _hits.pop(ip, None)


def enforce_rate_limit(request: Request) -> None:
    """Raise 429 when this IP has submitted too often. Call before saving."""
    global _checks
    now = time.time()
    ip = client_ip(request)

    hits = _hits[ip]
    while hits and now - hits[0] > WINDOW_SECONDS:
        hits.popleft()

    _checks += 1
    if _checks % PRUNE_EVERY == 0:
        _prune(now)

    if len(hits) >= MAX_PER_WINDOW:
        retry = int(WINDOW_SECONDS - (now - hits[0]))
        log.warning("rate limited %s (%d in window)", ip, len(hits))
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please call us instead — we'll sort it out faster.",
            headers={"Retry-After": str(max(retry, 1))},
        )
    hits.append(now)


def is_bot(payload, request: Request) -> bool:
    """True when the honeypot was filled in."""
    trap = (getattr(payload, "website", "") or "").strip()
    if trap:
        log.warning("honeypot tripped by %s (value=%r)", client_ip(request), trap[:60])
        return True
    return False

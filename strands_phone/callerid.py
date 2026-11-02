"""Who is calling: the caller number from the SIP INVITE, normalised to E.164, and the owner check.

The number is the user part of the INVITE's From URI (sip:+15550001234@host or tel:+1-555-000-1234). A withheld
number (anonymous / restricted / unavailable, a Privacy: id header, or anything that is not a phone number) is None:
treat that caller as a stranger.

CALLER ID IS SPOOFABLE. Anyone who can put the owner's number in the From header of a call that reaches the Voice
Connector is treated as the owner. It is a convenience for the owner's own phone, not authentication.
"""

from __future__ import annotations

import os
import re
from urllib.parse import unquote

WITHHELD = {"", "?", "anonymous", "restricted", "unavailable", "unknown", "private", "withheld", "null"}
DEFAULT_CC = "1"  # bare 10-digit numbers are North American (the line is a US Chime number); LEAF_PHONE_DEFAULT_CC


def _uri_user(value: str) -> str:
    """The user part of a From/To header value or URI: '"Bob" <sip:+1555@h>;tag=x' -> '+1555'."""
    v = (value or "").strip()
    if "<" in v and ">" in v:
        v = v[v.index("<") + 1 : v.index(">")]
    v = v.split(";tag=")[0].strip()
    for scheme in ("sips:", "sip:", "tel:"):
        if v.lower().startswith(scheme):
            v = v[len(scheme) :]
            break
    v = v.split("@")[0]
    return v.split(";")[0].strip()  # ;user=phone, ;phone-context=…


def normalize(number: str | None, default_cc: str | None = None) -> str | None:
    """E.164 ('+15550001234') or None when withheld/unparseable. Accepts '+1 (555) 000-1234', '15550001234',
    '5550001234', '0015550001234', '%2B15550001234', 'tel:+1-555-000-1234', 'sip:+15550001234@host;user=phone'."""
    if number is None:
        return None
    raw = unquote(str(number)).strip()
    if any(raw.lower().startswith(s) for s in ("sip:", "sips:", "tel:")) or "<" in raw or "@" in raw:
        raw = unquote(_uri_user(raw))
    if raw.strip().lower() in WITHHELD:
        return None
    if not re.fullmatch(r"\+?[\d\s().\-]+", raw):
        return None  # letters, '#', '*', 'x123' extensions…: not a plain number
    plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not plus and digits.startswith("00"):
        digits, plus = digits[2:], True
    if not plus:
        cc = (default_cc or os.environ.get("LEAF_PHONE_DEFAULT_CC") or DEFAULT_CC).lstrip("+")
        if cc == "1" and len(digits) == 11 and digits.startswith("1"):
            plus = True
        elif len(digits) == 10:
            digits, plus = cc + digits, True
        else:
            return None
    if not (8 <= len(digits) <= 15) or digits.startswith("0"):
        return None
    return "+" + digits


def caller_from_invite(headers: dict[str, list[str]]) -> str | None:
    """E.164 caller number from parsed INVITE headers (lower-case keys, as sip.parse_sip returns), or None."""
    privacy = " ".join(headers.get("privacy", [])).lower()
    if "id" in re.split(r"[\s;,]+", privacy) or "user" in re.split(r"[\s;,]+", privacy):
        return None
    frm = (headers.get("from") or [""])[0]
    return normalize(_uri_user(frm)) if frm else None


def owner_numbers(env: str | None = None) -> frozenset[str]:
    """LEAF_PHONE_OWNER_NUMBERS: comma list of trusted numbers (any format normalize() accepts). Empty = nobody."""
    raw = os.environ.get("LEAF_PHONE_OWNER_NUMBERS", "") if env is None else env
    return frozenset(n for n in (normalize(p) for p in raw.split(",")) if n)


def is_owner(caller: str | None, owners: frozenset[str] | None = None) -> bool:
    n = normalize(caller) if caller else None
    return bool(n) and n in (owner_numbers() if owners is None else owners)


def redact(number: str | None) -> str:
    """For logs: '+1551***4110'."""
    n = normalize(number) if number else None
    return f"{n[:5]}***{n[-4:]}" if n else "withheld"

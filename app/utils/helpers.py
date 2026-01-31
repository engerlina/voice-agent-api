"""Helper utility functions."""

import re
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


def generate_order_number() -> str:
    """Generate a unique order number.

    Format: TRV-YYYYMMDD-XXXXXX
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    unique_part = uuid4().hex[:6].upper()
    return f"TRV-{date_part}-{unique_part}"


def generate_ticket_number() -> str:
    """Generate a unique support ticket number.

    Format: TKT-YYYYMMDD-XXXXXX
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    unique_part = uuid4().hex[:6].upper()
    return f"TKT-{date_part}-{unique_part}"


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Normalize phone number to E.164 format."""
    if not phone:
        return None

    # Remove all non-digit characters except +
    cleaned = re.sub(r"[^\d+]", "", phone)

    # Ensure it starts with +
    if not cleaned.startswith("+"):
        # Assume Australian number if no country code
        if cleaned.startswith("0"):
            cleaned = "+61" + cleaned[1:]
        else:
            cleaned = "+" + cleaned

    return cleaned


def mask_email(email: str) -> str:
    """Mask email for logging (privacy)."""
    if not email or "@" not in email:
        return "***"

    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = "*" * len(local)
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]

    return f"{masked_local}@{domain}"


def mask_phone(phone: str) -> str:
    """Mask phone number for logging (privacy)."""
    if not phone or len(phone) < 4:
        return "***"

    return "***" + phone[-4:]


def calculate_sla_breach(
    start_time: datetime,
    threshold_seconds: float,
) -> tuple[bool, float]:
    """Calculate if SLA threshold was breached.

    Returns: (breached: bool, elapsed_seconds: float)
    """
    now = datetime.now(timezone.utc)
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    elapsed = (now - start_time).total_seconds()
    breached = elapsed > threshold_seconds

    return breached, elapsed


def format_currency(amount: float, currency: str = "AUD") -> str:
    """Format amount as currency string."""
    symbols = {
        "AUD": "A$",
        "USD": "$",
        "SGD": "S$",
        "GBP": "£",
        "MYR": "RM",
        "IDR": "Rp",
    }
    symbol = symbols.get(currency.upper(), currency + " ")
    return f"{symbol}{amount:.2f}"

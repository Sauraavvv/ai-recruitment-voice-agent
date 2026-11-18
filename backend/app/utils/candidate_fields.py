"""Field rules shared by manual candidate entry (API schemas) and file import validation."""

import re
from urllib.parse import urlparse

from email_validator import EmailNotValidError, validate_email

MAX_NAME_LENGTH = 200
MAX_TEXT_LENGTH = 500
MAX_NOTES_LENGTH = 2000
MAX_EXPERIENCE_YEARS = 60.0

_EXPERIENCE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|y)?\.?$", re.IGNORECASE)


def parse_experience(raw: str) -> float:
    """'5', '5.5', '5 years', '5 yrs', '5+' -> float years. Raises ValueError otherwise."""
    match = _EXPERIENCE.match(raw.strip())
    if not match:
        raise ValueError("Experience must be a number of years, e.g. 5 or 5.5")
    years = float(match.group("value"))
    return check_experience(years)


def check_experience(years: float) -> float:
    if not 0 <= years <= MAX_EXPERIENCE_YEARS:
        raise ValueError(f"Experience must be between 0 and {MAX_EXPERIENCE_YEARS:g} years")
    return years


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ValueError("Email address is not valid") from exc


def check_http_url(raw: str) -> str:
    value = raw.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Resume URL must start with http:// or https://")
    return value

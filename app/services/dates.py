"""Deterministic date parsing and comparisons. The model does not decide these."""
from datetime import datetime
import re

DISPLAY_FORMATS = ("%d %B %Y", "%d %b %Y")
INCEPTION_RE = re.compile(r"Policy period commences (\d{1,2} \w+ \d{4})", re.IGNORECASE)
CLAIMED_INCIDENT_RE = re.compile(
    r"Claimed incident date:\s*(\d{1,2} \w+ \d{4})", re.IGNORECASE
)
POLICE_INCIDENT_RE = re.compile(
    r"Incident reported as occurring on (\d{1,2} \w+ \d{4})", re.IGNORECASE
)
POLICY_VERSION_RE = re.compile(r"Policy version ([A-Z0-9.\-]+)")
POLICY_NUMBER_RE = re.compile(r"Policy number (POL-\d+)")
REGISTRATION_RE = re.compile(r"registration ([A-Z]{2}\d{2} [A-Z]{3})")


def parse_display_date(value: str):
    text = value.strip()
    for fmt in DISPLAY_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def iso_date(value: str) -> str | None:
    parsed = parse_display_date(value)
    if parsed is None:
        return None
    return parsed.isoformat()

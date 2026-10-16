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


def compare_dates(left: str, right: str) -> str:
    """Return before, equal, after, or unparsed. The model does not decide this."""
    left_date = parse_display_date(left or "")
    right_date = parse_display_date(right or "")
    if left_date is None or right_date is None:
        return "unparsed"
    if left_date < right_date:
        return "before"
    if left_date > right_date:
        return "after"
    return "equal"


def compare_dates_result(left: str, right: str) -> dict:
    return {
        "left_iso": iso_date(left or ""),
        "right_iso": iso_date(right or ""),
        "order": compare_dates(left, right),
    }

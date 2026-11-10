"""Turn the raw JSON the model returns into a clean, typed record."""
import re
from datetime import datetime

FIELDS = [
    "provider", "tariff", "sanctioned_load_kw", "bill_month", "reading_date", "issue_date",
    "due_date", "previous_reading", "current_reading", "units_consumed", "charges",
    "total_charges", "taxes", "total_taxes", "current_bill", "arrears",
    "payable_within_due_date", "payable_after_due_date",
]
NUMBER_FIELDS = [
    "sanctioned_load_kw", "previous_reading", "current_reading", "units_consumed",
    "total_charges", "total_taxes", "current_bill", "arrears",
    "payable_within_due_date", "payable_after_due_date",
]
DATE_FIELDS = ["reading_date", "issue_date", "due_date"]
CHARGE_TYPES = {"energy", "fixed", "fpa", "quarterly_adjustment", "surcharge", "meter_rent", "subsidy", "other"}
TAX_TYPES = {"gst", "electricity_duty", "income_tax", "municipal_tax", "other_tax"}
PROVIDERS = ("KE", "LESCO", "IESCO")

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def to_number(value):
    """'19,964' / 'Rs. 3,430' / '38209CR' / '39411 / 2' -> a number. Unreadable -> None.

    Only the first number in the text is used, so annotations such as '39411 / 2'
    (arrears for 2 months) are read as 39411 rather than glued into 394112.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
    else:
        s = str(value).replace(",", "").replace("Rs.", "").replace("Rs", "").strip()
        match = _NUMBER_RE.search(s)
        if not match:
            return None
        n = float(match.group())
        if "CR" in s.upper() or (s.startswith("(") and s.endswith(")")):
            n = -abs(n)
    return int(n) if n.is_integer() else round(n, 2)


_DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d %b %y", "%d %b %Y", "%d/%m/%Y", "%d/%m/%y",
                 "%d-%m-%Y", "%d.%m.%Y", "%b %d, %Y")
_MONTH_FORMATS = ("%Y-%m", "%b-%y", "%b %y", "%b-%Y", "%b %Y", "%m/%y", "%m/%Y", "%B %Y", "%b%y")


def to_date(value):
    """Normalise a printed date to YYYY-MM-DD; None if it can't be parsed."""
    if not value:
        return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", str(value).strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s.title() if "%b" in fmt else s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def to_month(value):
    """Normalise 'AUG 26', 'Aug-2026', '08/26', '2026-08-01' to 'YYYY-MM'; None if unparseable."""
    if not value:
        return None
    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", s):
        return s[:7]
    for fmt in _MONTH_FORMATS:
        try:
            return datetime.strptime(s.title(), fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return None


def shift_month(month, delta):
    """shift_month('2026-01', -1) -> '2025-12'."""
    y, m = map(int, month.split("-"))
    total = y * 12 + (m - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def normalise_provider(value):
    p = str(value or "").upper().replace("-", " ")
    if p in PROVIDERS:
        return p
    if "K ELECTRIC" in p or "KELECTRIC" in p.replace(" ", "") or p.startswith("KE") or "KESC" in p:
        return "KE"
    if "LAHORE" in p or "LESCO" in p:
        return "LESCO"
    if "ISLAMABAD" in p or "IESCO" in p:
        return "IESCO"
    return None


def clean_items(items, allowed, fallback):
    """Keep valid line items, drop zero/blank ones, force a valid type."""
    cleaned = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        amount = to_number(item.get("amount"))
        if amount is None or amount == 0:
            continue
        t = str(item.get("type", "")).strip().lower()
        cleaned.append({"type": t if t in allowed else fallback, "amount": amount})
    return cleaned


def clean_history(items):
    """Valid {month, units} rows, one per month, oldest first."""
    by_month = {}
    for item in items or []:
        if isinstance(item, dict):
            month, units = to_month(item.get("month")), to_number(item.get("units"))
            if month and units is not None:
                by_month.setdefault(month, units)
    return [{"month": m, "units": by_month[m]} for m in sorted(by_month)]


def clean_billing(items):
    """Valid {month, billed_amount, payment} rows, one per month, oldest first."""
    by_month = {}
    for item in items or []:
        if isinstance(item, dict):
            month = to_month(item.get("month"))
            if month:
                by_month.setdefault(month, {"month": month,
                                            "billed_amount": to_number(item.get("billed_amount")),
                                            "payment": to_number(item.get("payment"))})
    return [by_month[m] for m in sorted(by_month)]


def postprocess(data):
    """Make sure every schema field exists and has the right type."""
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        data = {}
    out = {f: data.get(f) for f in FIELDS}
    out["provider"] = normalise_provider(out["provider"])
    out["tariff"] = str(out["tariff"]).strip() if out["tariff"] not in (None, "") else None
    out["bill_month"] = to_month(out["bill_month"])
    for f in DATE_FIELDS:
        out[f] = to_date(out[f])
    for f in NUMBER_FIELDS:
        out[f] = to_number(out[f])
    out["charges"] = clean_items(out["charges"], CHARGE_TYPES, "other")
    out["taxes"] = clean_items(out["taxes"], TAX_TYPES, "other_tax")
    for c in out["charges"]:
        if c["type"] == "subsidy":
            c["amount"] = -abs(c["amount"])
    out["total_fpa"] = to_number(data.get("total_fpa"))  # helper for the consistency checks
    out["usage_history"] = clean_history(data.get("usage_history"))
    out["billing_history"] = clean_billing(data.get("billing_history"))
    return out

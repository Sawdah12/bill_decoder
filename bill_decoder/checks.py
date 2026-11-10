"""Arithmetic consistency checks on an extracted bill, with targeted re-reads.

Every printed bill satisfies a few identities (charges + taxes = current bill, current bill + arrears
[+ FPA] = amount payable, charge lines sum to the charges subtotal). When an extraction breaks one of
them, a digit or a field was probably misread, so we ask the model to re-read only those numbers.
A correction is accepted ONLY if the re-read values satisfy the identity; otherwise the original
values are kept and the check is reported as a mismatch. This way a check can never make a
consistent extraction worse.

`ask(prompt) -> dict` is injected (bound to the bill image) so the logic is testable offline.
"""
from .parsing import CHARGE_TYPES, clean_items, shift_month, to_number
from .prompts import CHARGES_RETRY_PROMPT, PAYABLE_RETRY_PROMPT, TOTALS_RETRY_PROMPT

OK, FIXED, MISMATCH, NA = "ok", "fixed", "mismatch", "n/a"
TOLERANCE = 2  # PKR; bills round to whole rupees in places


def _close(a, b, tol=TOLERANCE):
    return abs(a - b) <= tol


def _subsidy(out):
    return sum(c["amount"] for c in out["charges"] if c["type"] == "subsidy")


def _fpa(out):
    """FPA billed on top of the current bill (LESCO/IESCO 'Total FPA'); falls back to the FPA charge lines."""
    if out.get("total_fpa") is not None:
        return out["total_fpa"]
    return sum(c["amount"] for c in out["charges"] if c["type"] == "fpa")


def totals_consistent(out, tc=None, tt=None, cb=None):
    """charges + taxes (- subsidy) (- FPA billed separately) == current bill."""
    tc = out["total_charges"] if tc is None else tc
    tt = out["total_taxes"] if tt is None else tt
    cb = out["current_bill"] if cb is None else cb
    if None in (tc, tt, cb):
        return None
    return any(_close(tc + tt + s - f, cb) for s in (0, _subsidy(out)) for f in (0, _fpa(out)))


def payable_consistent(out, pw=None, pa=None):
    """current bill + arrears (+ FPA on LESCO/IESCO) == payable within due date; late amount >= it."""
    pw = out["payable_within_due_date"] if pw is None else pw
    pa = out["payable_after_due_date"] if pa is None else pa
    cb = out["current_bill"]
    if pw is None or cb is None:
        return None
    base = cb + (out["arrears"] or 0)
    if not any(_close(base + f, pw) for f in (0, _fpa(out))):
        return False
    return pa is None or pw <= 0 or pa >= pw


def charges_consistent(out, charges=None):
    """The charge lines add up to the printed charges subtotal (with or without subsidy / FPA lines)."""
    charges = out["charges"] if charges is None else charges
    tc = out["total_charges"]
    if tc is None or not charges:
        return None
    gross = [c["amount"] for c in charges if c["type"] != "subsidy"]
    no_fpa = [c["amount"] for c in charges if c["type"] not in ("subsidy", "fpa")]
    candidates = (sum(gross), sum(no_fpa), sum(c["amount"] for c in charges))
    return any(_close(s, tc, 1) for s in candidates)


def readings_consistent(out):
    prev, cur, units = out["previous_reading"], out["current_reading"], out["units_consumed"]
    if None in (prev, cur, units):
        return None
    return abs(cur - prev - units) <= 1  # multiplying factor is 1 on residential meters


def expected_history_months(provider, bill_month):
    """Months the history section normally covers: (usage months, billing months)."""
    if not bill_month:
        return [], []
    if provider == "KE":
        usage = [shift_month(bill_month, -i) for i in range(12, -1, -1)]          # 13 bars incl. current
        billing = [shift_month(bill_month, -i) for i in range(3, 0, -1)]          # last 3 months
        return usage, billing
    months = [shift_month(bill_month, -i) for i in range(12, 0, -1)]              # 12 previous months
    return months, months


def missing_history_months(out):
    usage_exp, billing_exp = expected_history_months(out["provider"], out["bill_month"])
    have_u = {h["month"] for h in out["usage_history"]}
    have_b = {h["month"] for h in out["billing_history"]}
    return sorted({m for m in usage_exp if m not in have_u} | {m for m in billing_exp if m not in have_b})


def _safe_ask(ask, prompt):
    try:
        reply = ask(prompt)
        return reply if isinstance(reply, dict) else {}
    except Exception as e:  # a failed re-read must never break extraction
        print(f"  re-read skipped: {e}")
        return {}


def _check_totals(out, ask):
    status = totals_consistent(out)
    if status is None:
        return NA
    if status or ask is None:
        return OK if status else MISMATCH
    reply = _safe_ask(ask, TOTALS_RETRY_PROMPT.replace("<<TC>>", str(out["total_charges"]))
                      .replace("<<TT>>", str(out["total_taxes"])).replace("<<CB>>", str(out["current_bill"])))
    new = {k: to_number(reply.get(k)) for k in ("total_charges", "total_taxes", "current_bill")}
    if None not in new.values() and totals_consistent(out, new["total_charges"], new["total_taxes"],
                                                       new["current_bill"]):
        old_tt = out["total_taxes"]
        for t in out["taxes"]:  # a single combined tax line mirrors the total
            if t["amount"] == old_tt:
                t["amount"] = new["total_taxes"]
        out.update(new)
        return FIXED
    return MISMATCH


def _check_charges(out, ask):
    status = charges_consistent(out)
    if status is None:
        return NA
    if status or ask is None:
        return OK if status else MISMATCH
    items = ", ".join(f"{c['type']} {c['amount']}" for c in out["charges"])
    total = round(sum(c["amount"] for c in out["charges"] if c["type"] != "subsidy"), 2)
    reply = _safe_ask(ask, CHARGES_RETRY_PROMPT.replace("<<TC>>", str(out["total_charges"]))
                      .replace("<<SUM>>", str(total)).replace("<<ITEMS>>", items))
    new = clean_items(reply.get("charges"), CHARGE_TYPES, "other")
    for c in new:
        if c["type"] == "subsidy":
            c["amount"] = -abs(c["amount"])
    if new and charges_consistent(out, new):
        out["charges"] = new
        return FIXED
    return MISMATCH


def _check_payable(out, ask):
    status = payable_consistent(out)
    if status is None:
        return NA
    if status or ask is None:
        return OK if status else MISMATCH
    reply = _safe_ask(ask, PAYABLE_RETRY_PROMPT.replace("<<PW>>", str(out["payable_within_due_date"]))
                      .replace("<<PA>>", str(out["payable_after_due_date"]))
                      .replace("<<CB>>", str(out["current_bill"])).replace("<<AR>>", str(out["arrears"])))
    pw, pa = to_number(reply.get("payable_within_due_date")), to_number(reply.get("payable_after_due_date"))
    if pw is not None and payable_consistent(out, pw, pa):
        out["payable_within_due_date"] = pw
        if pa is not None:
            out["payable_after_due_date"] = pa
        return FIXED
    return MISMATCH


def run_checks(out, ask=None):
    """Run every check (repairing where possible) and record the outcome in out['checks']."""
    checks = {
        "charges_plus_taxes_equal_current_bill": _check_totals(out, ask),
        "charge_lines_sum_to_subtotal": _check_charges(out, ask),
        "payable_equals_current_bill_plus_arrears": _check_payable(out, ask),
    }
    r = readings_consistent(out)
    checks["meter_readings_match_units"] = NA if r is None else (OK if r else MISMATCH)
    missing = missing_history_months(out)
    checks["history_complete"] = OK if not missing else f"missing {', '.join(missing)}"
    out["checks"] = checks
    return out

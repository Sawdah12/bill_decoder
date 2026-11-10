"""Exact numbers computed in code for the Q&A step, so the LLM never has to count or do arithmetic."""
from .parsing import shift_month

SUMMER, WINTER = ("06", "07", "08"), ("12", "01", "02")


def _avg(xs):
    return round(sum(xs) / len(xs), 2) if xs else None


def _summary(rows):
    if not rows:
        return None
    units = [r["units"] for r in rows]
    return {"months": [r["month"] for r in rows], "average": _avg(units), "total": round(sum(units), 2),
            "highest": max(rows, key=lambda r: r["units"]), "lowest": min(rows, key=lambda r: r["units"])}


def history_stats(history):
    """Usage-history statistics. `history` is oldest-first and its last entry is the current month."""
    if not history:
        return {"note": "No usage history is printed on this bill."}
    current, previous = history[-1], history[:-1]
    by_month = {h["month"]: h for h in history}
    stats = {
        "note": "EXACT numbers computed by code. Last entry = current bill month. Use these; do not recount.",
        "months_shown_including_current": len(history),
        "current_month": current,
        "last_12_months_including_current": _summary(history[-12:]),
        "previous_12_months_excluding_current": _summary(previous[-12:]),
        "last_3_months": history[-3:],
    }
    if previous:
        stats["previous_month"] = previous[-1]
        stats["current_minus_previous_month"] = round(current["units"] - previous[-1]["units"], 2)
        stats["current_minus_previous_12_month_average"] = round(
            current["units"] - _avg([h["units"] for h in previous[-12:]]), 2)

    last3 = [h["units"] for h in history[-3:]]
    if len(last3) == 3:
        stats["last_3_months_trend"] = ("going up" if last3[0] < last3[1] < last3[2]
                                        else "going down" if last3[0] > last3[1] > last3[2] else "mixed")

    try:
        last_year = shift_month(current["month"], -12)
        if last_year in by_month:
            stats["same_month_last_year"] = by_month[last_year]
            stats["current_minus_same_month_last_year"] = round(current["units"] - by_month[last_year]["units"], 2)
        else:
            stats["same_month_last_year"] = f"{last_year} is NOT shown on this bill - say so, do not use another month."
        nxt = shift_month(current["month"], 1)
        stats["next_month"] = nxt
        stats["next_month_ESTIMATE_avg_of_last_3_months"] = _avg(last3)
        stats["next_month_ESTIMATE_avg_of_last_12_months"] = _avg([h["units"] for h in history[-12:]])
        if shift_month(nxt, -12) in by_month:
            stats["next_month_ESTIMATE_same_month_last_year"] = by_month[shift_month(nxt, -12)]
    except (ValueError, KeyError, AttributeError):
        pass

    last12 = history[-12:]
    summer = [h for h in last12 if h["month"][5:7] in SUMMER]
    winter = [h for h in last12 if h["month"][5:7] in WINTER]
    stats["summer_jun_aug"] = _summary(summer)
    stats["winter_dec_feb"] = _summary(winter)
    if summer and winter:
        stats["summer_minus_winter_average_per_month"] = round(
            _avg([h["units"] for h in summer]) - _avg([h["units"] for h in winter]), 2)
    for t in (100, 200, 300, 500, 700):
        stats[f"months_above_{t}_excluding_current"] = [h["month"] for h in previous if h["units"] > t]
        stats[f"months_above_{t}_including_current"] = [h["month"] for h in history if h["units"] > t]
    return stats


def billing_stats(rows):
    if not rows:
        return {"note": "No billing/payment history table is printed on this bill."}
    billed = [r["billed_amount"] for r in rows if r["billed_amount"] is not None]
    unpaid = [r["month"] for r in rows if not r["payment"]]
    stats = {"note": "EXACT numbers computed by code from billing_history. A blank payment on a "
                     "credit (negative) bill month is normal.",
             "months_shown": len(rows),
             "months_with_a_payment": len(rows) - len(unpaid),
             "months_with_no_or_zero_payment": unpaid}
    if billed:
        stats["total_billed"] = round(sum(billed), 2)
        stats["ESTIMATE_monthly_set_aside_avg_billed_amount"] = round(sum(billed) / len(billed), 2)
    return stats


def bill_facts(d):
    facts = {"note": "EXACT numbers computed by code from the extracted fields. Use these."}
    cb, tt, tc = d.get("current_bill"), d.get("total_taxes"), d.get("total_charges")
    pw, pa, units = d.get("payable_within_due_date"), d.get("payable_after_due_date"), d.get("units_consumed")
    if tt is not None and cb:
        facts["taxes_percent_of_current_bill"] = round(tt / cb * 100, 2)
    if tc is not None and cb:
        facts["charges_percent_of_current_bill"] = round(tc / cb * 100, 2)
    if pw is not None and pa is not None:
        facts["extra_if_paid_after_due_date"] = round(pa - pw, 2)
    if cb and units:
        facts["current_bill_per_unit"] = round(cb / units, 2)
    if tc and units:
        facts["charges_per_unit"] = round(tc / units, 2)
    fpa = [c["amount"] for c in d.get("charges") or [] if c["type"] == "fpa"]
    if fpa:
        facts["fpa_charged_total"] = round(sum(fpa), 2)
    return facts

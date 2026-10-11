import re
from llm import call_gemini
import json
from prompts import EXTRACTION_PROMPT, QA_PROMPT

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
CHARGE_TYPES = {"energy", "fixed", "fpa", "quarterly_adjustment", "surcharge", "meter_rent", "subsidy", "other"}
TAX_TYPES = {"gst", "electricity_duty", "income_tax", "municipal_tax", "other_tax"}


def to_number(value):
    """Turn '19,964', 'Rs. 3,430', '38209CR' into a number; anything unreadable -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).replace(",", "").replace("Rs.", "").replace("Rs", "").strip()
    negative = s.upper().endswith("CR")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        n = float(s)
    except ValueError:
        return None
    n = -abs(n) if negative else n
    return int(n) if n.is_integer() else n


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
    """Keep valid {month, units} entries from the usage history."""
    history = []
    for item in items or []:
        if isinstance(item, dict):
            units = to_number(item.get("units"))
            month = str(item.get("month") or "").strip()
            if units is not None and month:
                history.append({"month": month, "units": units})
    return history

def history_stats(history):
    """Exact usage-history numbers computed in code, so the LLM doesn't do math."""
    if not history:
        return {"note": "No usage history is printed on this bill."}

    def avg(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    def summary(h):
        if not h:
            return None
        u = [x["units"] for x in h]
        return {"months": [x["month"] for x in h], "average": avg(u), "total": round(sum(u), 2),
                "highest": max(h, key=lambda x: x["units"]), "lowest": min(h, key=lambda x: x["units"])}

    current, previous = history[-1], history[:-1]
    stats = {
        "note": "EXACT numbers computed by code. Last entry = current bill month. Use these; do not recount.",
        "current_month": current,
        "last_12_months_including_current": summary(history[-12:]),
        "previous_12_months_excluding_current": summary(previous[-12:]),
        "last_3_months": history[-3:],
    }
    if previous:
        prev_avg = avg([x["units"] for x in previous[-12:]])
        stats["current_minus_previous_12_month_average"] = round(current["units"] - prev_avg, 2)
        stats["previous_month"] = previous[-1]
        stats["current_minus_previous_month"] = round(current["units"] - previous[-1]["units"], 2)
    l3 = [x["units"] for x in history[-3:]]
    if len(l3) == 3:
        stats["last_3_months_trend"] = ("going up" if l3[0] < l3[1] < l3[2]
                                        else "going down" if l3[0] > l3[1] > l3[2] else "mixed")
    try:
        y, m = map(int, current["month"][:7].split("-"))
        by_month = {x["month"][:7]: x for x in history}
        last_year = by_month.get(f"{y - 1}-{m:02d}")
        if last_year:
            stats["same_month_last_year"] = last_year
            stats["current_minus_same_month_last_year"] = round(current["units"] - last_year["units"], 2)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        stats["next_month"] = f"{ny}-{nm:02d}"
        stats["next_month_ESTIMATE_avg_of_last_3_months"] = avg(l3)
        stats["next_month_ESTIMATE_avg_of_last_12_months"] = avg([x["units"] for x in history[-12:]])
        if by_month.get(f"{ny - 1}-{nm:02d}"):
            stats["next_month_ESTIMATE_same_month_last_year"] = by_month[f"{ny - 1}-{nm:02d}"]
    except (ValueError, KeyError):
        pass
    last12 = history[-12:]
    summer = [x for x in last12 if x["month"][5:7] in ("06", "07", "08")]
    winter = [x for x in last12 if x["month"][5:7] in ("12", "01", "02")]
    stats["summer_jun_aug"] = summary(summer)
    stats["winter_dec_feb"] = summary(winter)
    if summer and winter:
        stats["summer_minus_winter_average_per_month"] = round(
            avg([x["units"] for x in summer]) - avg([x["units"] for x in winter]), 2)
    for t in (100, 200, 300, 500, 700):
        stats[f"months_above_{t}_excluding_current"] = [h["month"] for h in previous if h["units"] > t]
        stats[f"months_above_{t}_including_current"] = [h["month"] for h in history if h["units"] > t]
    return stats


def clean_billing(items):
    rows = []
    for item in items or []:
        if isinstance(item, dict) and item.get("month"):
            rows.append({"month": str(item["month"]).strip(),
                         "billed_amount": to_number(item.get("billed_amount")),
                         "payment": to_number(item.get("payment"))})
    return rows


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

def postprocess(data):
    """Make sure every field exists and has the right type."""
    if not isinstance(data, dict):
        data = {}
    out = {f: data.get(f) for f in FIELDS}
    for f in NUMBER_FIELDS:
        out[f] = to_number(out[f])
    out["charges"] = clean_items(out["charges"], CHARGE_TYPES, "other")
    out["taxes"] = clean_items(out["taxes"], TAX_TYPES, "other_tax")
    for c in out["charges"]:
        if c["type"] == "subsidy":
            c["amount"] = -abs(c["amount"])
    if out["provider"] not in ("KE", "LESCO", "IESCO"):
        p = str(out["provider"] or "").upper()
        out["provider"] = "KE" if "K" in p and "ELECTRIC" in p else None
    out["usage_history"] = clean_history(data.get("usage_history"))
    out["billing_history"] = clean_billing(data.get("billing_history"))
    return out

def verify_totals(image_path, out):
    """Self-check: if charges + taxes != current bill, ask Gemini to re-read those numbers."""
    tc, tt, cb = out.get("total_charges"), out.get("total_taxes"), out.get("current_bill")
    if None in (tc, tt, cb):
        return out
    sub = sum(c["amount"] for c in out["charges"] if c["type"] == "subsidy")

    def adds_up(c, t, b):
        return abs(c + t - b) <= 2 or abs(c + sub + t - b) <= 2

    if adds_up(tc, tt, cb):
        return out
    prompt = (f"Look again at this electricity bill. I read: total electricity charges = {tc}, "
              f"taxes total = {tt}, current bill = {cb}. These do not add up, so a digit was probably "
              f"misread (e.g. 3 vs 8, 1 vs 7, 5 vs 6). Re-read these three printed numbers digit by digit, "
              f'exactly as printed. Return JSON: {{"total_charges": number, "total_taxes": number, '
              f'"current_bill": number}}')
    try:
        fix = call_gemini(prompt, image_path=image_path, json_mode=True)
        new = {k: to_number(fix.get(k)) for k in ("total_charges", "total_taxes", "current_bill")}
    except Exception as e:
        print(f"  verify skipped: {e}")
        return out
    if None not in new.values() and adds_up(new["total_charges"], new["total_taxes"], new["current_bill"]):
        for t in out["taxes"]:
            if t["amount"] == tt:
                t["amount"] = new["total_taxes"]
        out.update(new)
        print(f"  self-check corrected totals: {tc}/{tt}/{cb} -> {new}")
    return out
    
def extract_bill(image_path):
    """Level 1: image -> clean JSON dict."""
    raw = call_gemini(EXTRACTION_PROMPT, image_path=image_path, json_mode=True)
    if isinstance(raw, list) and raw:
        raw = raw[0]
    return postprocess(raw)

def bill_facts(d):
    """Exact derived numbers computed in code, so the LLM doesn't have to do arithmetic."""
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
    return facts

def answer_questions(image_path, bill_data, questions):
    """Level 2: answer a list of (question_id, question) pairs about one bill in a single call."""
    q_text = "\n".join(f"{qid}: {q}" for qid, q in questions)
    enriched = dict(bill_data)
    history = list(bill_data.get("usage_history") or [])
    month, units = bill_data.get("bill_month"), bill_data.get("units_consumed")
    if month and units is not None and (not history or history[-1]["month"] != month):
        history.append({"month": month, "units": units})  # add current month if the table omits it
    enriched["history_stats"] = history_stats(history)
    facts = bill_facts(bill_data)
    hs = enriched["history_stats"]
    if hs.get("previous_month") and facts.get("current_bill_per_unit"):
        facts["ESTIMATE_bill_if_same_units_as_previous_month"] = round(
            hs["previous_month"]["units"] * facts["current_bill_per_unit"], 2)
    enriched["computed_facts"] = facts
    enriched["billing_stats"] = billing_stats(bill_data.get("billing_history", []))    
    prompt = (QA_PROMPT
              .replace("<<BILL_JSON>>", json.dumps(enriched, indent=2))
              .replace("<<QUESTIONS>>", q_text))
    try:
        raw = call_gemini(prompt, image_path=image_path, json_mode=True)
    except Exception as e:
        print(f"  Q&A failed for {image_path}: {e}")
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    fallback = "Sorry, I could not generate an answer for this question from the bill."
    return {qid: str(raw.get(qid) or fallback).strip() for qid, _ in questions}

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "train_bills/KESC_0008.png"
    data = extract_bill(path)
    print(json.dumps(data, indent=2))
    sample_qs = [
        ("Q1", "How much of my bill is taxes?"),
        ("Q2", "How many months in my history went above 200 units?"),
    ]
    for qid, ans in answer_questions(path, data, sample_qs).items():
        print(f"\n{qid}: {ans}")
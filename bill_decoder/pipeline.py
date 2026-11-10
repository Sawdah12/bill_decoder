"""Bill image -> validated JSON (Level 1) -> grounded answers to questions (Level 2)."""
import json

from .checks import expected_history_months, run_checks
from .llm import call_gemini
from .parsing import FIELDS, clean_billing, clean_history, postprocess
from .prompts import EXTRACTION_PROMPT, HISTORY_PROMPT, HISTORY_RETRY_PROMPT, LAYOUT_DISCO, LAYOUT_KE, QA_PROMPT
from .stats import bill_facts, billing_stats, history_stats


def level1_record(bill):
    """Only the official Level-1 schema fields (no history, checks or helper fields)."""
    return {f: bill.get(f) for f in FIELDS}


def _history_prompt(provider, bill_month):
    usage_months, _ = expected_history_months(provider, bill_month)
    layout = LAYOUT_KE if provider == "KE" else LAYOUT_DISCO
    if usage_months:
        layout = layout.replace("<<FIRST>>", usage_months[0]).replace("<<LAST>>", usage_months[-1])
    else:
        layout = layout.replace(" normally covers", " covers").replace("<<FIRST>> to <<LAST>>", "shown")
    return (HISTORY_PROMPT.replace("<<PROVIDER>>", provider or "unknown provider")
            .replace("<<BILL_MONTH>>", bill_month or "unknown").replace("<<LAYOUT>>", layout))


def _coverage(usage, billing, expected_usage, expected_billing):
    have = {h["month"] for h in usage} | {"b" + h["month"] for h in billing}
    return sum(m in have for m in expected_usage) + sum("b" + m in have for m in expected_billing)


def read_history(image_path, provider, bill_month, llm=call_gemini):
    """Focused call for the usage/billing history, with one retry naming any months it skipped."""
    exp_u, exp_b = expected_history_months(provider, bill_month)
    raw = llm(_history_prompt(provider, bill_month), image_path=image_path, json_mode=True)
    raw = raw if isinstance(raw, dict) else {}
    usage, billing = clean_history(raw.get("usage_history")), clean_billing(raw.get("billing_history"))

    missing = sorted({m for m in exp_u if m not in {h["month"] for h in usage}}
                     | {m for m in exp_b if m not in {h["month"] for h in billing}})
    if missing and (usage or billing):
        try:
            retry = llm(HISTORY_RETRY_PROMPT.replace("<<MISSING>>", ", ".join(missing)),
                        image_path=image_path, json_mode=True)
            retry = retry if isinstance(retry, dict) else {}
            u2, b2 = clean_history(retry.get("usage_history")), clean_billing(retry.get("billing_history"))
            if _coverage(u2, b2, exp_u, exp_b) > _coverage(usage, billing, exp_u, exp_b):
                usage, billing = u2, b2
        except Exception as e:
            print(f"  history retry skipped: {e}")
    return usage, billing


def extract_bill(image_path, llm=call_gemini):
    """Level 1: image -> clean, cross-checked dict (schema fields + history + checks)."""
    bill = postprocess(llm(EXTRACTION_PROMPT, image_path=image_path, json_mode=True))
    try:
        bill["usage_history"], bill["billing_history"] = read_history(
            image_path, bill["provider"], bill["bill_month"], llm=llm)
    except Exception as e:
        print(f"  history read failed: {e}")
    return run_checks(bill, ask=lambda prompt: llm(prompt, image_path=image_path, json_mode=True))


def build_context(bill):
    """The extracted bill plus every number the Q&A step needs, computed exactly in code."""
    ctx = {k: v for k, v in bill.items() if k != "checks"}
    history = list(bill.get("usage_history") or [])
    month, units = bill.get("bill_month"), bill.get("units_consumed")
    if month and units is not None and (not history or history[-1]["month"] != month):
        history.append({"month": month, "units": units})  # tables on LESCO/IESCO bills omit the current month
    ctx["history_stats"] = history_stats(history)
    facts = bill_facts(bill)
    prev = ctx["history_stats"].get("previous_month")
    if prev and facts.get("current_bill_per_unit"):
        facts["ESTIMATE_bill_if_same_units_as_previous_month"] = round(
            prev["units"] * facts["current_bill_per_unit"], 2)
    ctx["computed_facts"] = facts
    ctx["billing_stats"] = billing_stats(bill.get("billing_history") or [])
    return ctx


def answer_questions(image_path, bill, questions, llm=call_gemini):
    """Level 2: answer a list of (question_id, question) pairs about one bill in a single call."""
    prompt = (QA_PROMPT.replace("<<BILL_JSON>>", json.dumps(build_context(bill), indent=2))
              .replace("<<QUESTIONS>>", "\n".join(f"{qid}: {q}" for qid, q in questions)))
    try:
        raw = llm(prompt, image_path=image_path, json_mode=True)
    except Exception as e:
        print(f"  Q&A failed for {image_path}: {e}")
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    fallback = "Sorry, I could not generate an answer for this question from the bill."
    return {qid: str(raw.get(qid) or fallback).strip() for qid, _ in questions}


if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    data = extract_bill(path)
    print(json.dumps(data, indent=2))
    for qid, ans in answer_questions(path, data, [("Q1", "How much of my bill is taxes?")]).items():
        print(f"\n{qid}: {ans}")

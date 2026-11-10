"""End-to-end pipeline tests with a scripted fake LLM (no network)."""
from bill_decoder.parsing import FIELDS
from bill_decoder.pipeline import answer_questions, extract_bill, level1_record

MAIN = {"provider": "IESCO", "tariff": "A-1a(01)", "bill_month": "2026-08", "units_consumed": 676,
        "charges": [{"type": "energy", "amount": 29807}], "total_charges": 29807, "taxes": [],
        "total_taxes": 8516, "current_bill": 38323, "arrears": 31203, "total_fpa": 370.76,
        "payable_within_due_date": 69897, "payable_after_due_date": 72878}
FULL_YEAR = [f"2025-{m:02d}" for m in range(8, 13)] + [f"2026-{m:02d}" for m in range(1, 8)]


def history(months):
    return {"usage_history": [{"month": m, "units": 100} for m in months],
            "billing_history": [{"month": m, "billed_amount": 1000, "payment": 1000} for m in months]}


class ScriptedLLM:
    """Returns replies in order, recording which prompts were sent."""

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, prompt, image_path=None, json_mode=False):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def test_extract_uses_history_retry_when_months_missing():
    llm = ScriptedLLM(MAIN, history(FULL_YEAR[1:]), history(FULL_YEAR))
    bill = extract_bill("bill.png", llm=llm)
    assert len(llm.prompts) == 3
    assert "2025-08" in llm.prompts[2]                       # retry names the skipped month
    assert bill["usage_history"][0]["month"] == "2025-08"
    assert bill["checks"]["history_complete"] == "ok"
    assert all(v in ("ok", "n/a") for v in bill["checks"].values())


def test_retry_that_is_worse_is_ignored():
    llm = ScriptedLLM(MAIN, history(FULL_YEAR[1:]), history(FULL_YEAR[5:]))
    bill = extract_bill("bill.png", llm=llm)
    assert len(bill["usage_history"]) == 11
    assert bill["checks"]["history_complete"] == "missing 2025-08"


def test_complete_history_needs_two_calls_only():
    llm = ScriptedLLM(MAIN, history(FULL_YEAR))
    extract_bill("bill.png", llm=llm)
    assert len(llm.prompts) == 2


def test_level1_record_has_exact_schema():
    bill = extract_bill("bill.png", llm=ScriptedLLM(MAIN, history(FULL_YEAR)))
    assert list(level1_record(bill)) == FIELDS


def test_answers_fall_back_when_llm_fails():
    def broken(prompt, image_path=None, json_mode=False):
        raise RuntimeError("quota exceeded")
    answers = answer_questions("bill.png", {"usage_history": []}, [("Q1", "a?"), ("Q2", "b?")], llm=broken)
    assert set(answers) == {"Q1", "Q2"} and all("Sorry" in a for a in answers.values())


def test_answers_are_mapped_by_question_id():
    llm = ScriptedLLM({"Q1": "PKR 8,516 (22.2%)", "Q2": ""})
    answers = answer_questions("bill.png", {"usage_history": []}, [("Q1", "taxes?"), ("Q2", "x?")], llm=llm)
    assert answers["Q1"] == "PKR 8,516 (22.2%)" and "Sorry" in answers["Q2"]
    assert "taxes?" in llm.prompts[0]

from bill_decoder.pipeline import build_context
from bill_decoder.stats import billing_stats, history_stats

# IESCO_0002 usage history (Aug 2025 - Jul 2026) + current month Aug 2026 = 676 units
HISTORY = [{"month": m, "units": u} for m, u in [
    ("2025-08", 721), ("2025-09", 597), ("2025-10", 656), ("2025-11", 182), ("2025-12", 143), ("2026-01", 155),
    ("2026-02", 175), ("2026-03", 142), ("2026-04", 154), ("2026-05", 267), ("2026-06", 412), ("2026-07", 525),
    ("2026-08", 676)]]


def test_same_month_last_year_and_trend():
    s = history_stats(HISTORY)
    assert s["same_month_last_year"] == {"month": "2025-08", "units": 721}
    assert s["current_minus_same_month_last_year"] == -45
    assert s["last_3_months_trend"] == "going up"
    assert s["previous_month"] == {"month": "2026-07", "units": 525}
    assert s["next_month"] == "2026-09"
    assert s["next_month_ESTIMATE_same_month_last_year"] == {"month": "2025-09", "units": 597}


def test_missing_same_month_is_stated_not_substituted():
    s = history_stats(HISTORY[1:])  # drop Aug 2025
    assert "NOT shown" in s["same_month_last_year"]
    assert "current_minus_same_month_last_year" not in s


def test_seasons_and_thresholds():
    s = history_stats(HISTORY)
    assert s["summer_jun_aug"]["months"] == ["2026-06", "2026-07", "2026-08"]
    assert s["winter_dec_feb"]["average"] == round((143 + 155 + 175) / 3, 2)
    assert s["months_above_500_excluding_current"] == ["2025-08", "2025-09", "2025-10", "2026-07"]
    assert s["months_above_500_including_current"][-1] == "2026-08"
    assert "2025-08" not in s["last_12_months_including_current"]["months"]


def test_empty_history():
    assert "No usage history" in history_stats([])["note"]
    assert "No billing" in billing_stats([])["note"]


def test_billing_stats_counts_unpaid_months():
    rows = [{"month": "2026-01", "billed_amount": 100, "payment": 100},
            {"month": "2026-02", "billed_amount": 300, "payment": 0},
            {"month": "2026-03", "billed_amount": 200, "payment": None}]
    s = billing_stats(rows)
    assert s["months_shown"] == 3 and s["months_with_a_payment"] == 1
    assert s["months_with_no_or_zero_payment"] == ["2026-02", "2026-03"]
    assert s["ESTIMATE_monthly_set_aside_avg_billed_amount"] == 200


def test_context_appends_current_month_and_facts():
    bill = {"bill_month": "2026-08", "units_consumed": 676, "usage_history": HISTORY[:-1], "billing_history": [],
            "current_bill": 38323, "total_taxes": 8516, "total_charges": 29807, "payable_within_due_date": 69897,
            "payable_after_due_date": 72878, "charges": [], "checks": {"x": "ok"}}
    ctx = build_context(bill)
    assert "checks" not in ctx
    assert ctx["history_stats"]["current_month"] == {"month": "2026-08", "units": 676}
    assert ctx["computed_facts"]["extra_if_paid_after_due_date"] == 2981
    assert ctx["computed_facts"]["taxes_percent_of_current_bill"] == 22.22
    assert ctx["computed_facts"]["ESTIMATE_bill_if_same_units_as_previous_month"] == round(525 * 56.69, 2)

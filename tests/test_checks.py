from bill_decoder.checks import (
    charges_consistent,
    expected_history_months,
    missing_history_months,
    payable_consistent,
    run_checks,
    totals_consistent,
)
from bill_decoder.parsing import postprocess


def lesco_bill(**overrides):
    """A LESCO-layout bill (values from a real bill) where every identity holds."""
    data = {
        "provider": "LESCO", "bill_month": "2026-09", "previous_reading": 9919, "current_reading": 10107,
        "units_consumed": 188, "charges": [{"type": "energy", "amount": 7348}, {"type": "subsidy", "amount": -566},
                                           {"type": "fpa", "amount": 471}],
        "total_charges": 7348, "taxes": [], "total_taxes": 1314, "current_bill": 8096, "arrears": 0,
        "total_fpa": 471, "payable_within_due_date": 8567, "payable_after_due_date": 9245,
    }
    data.update(overrides)
    return postprocess(data)


def ke_bill(**overrides):
    data = {
        "provider": "KE", "bill_month": "2026-04",
        "charges": [{"type": "fixed", "amount": 900}, {"type": "energy", "amount": 1054},
                    {"type": "energy", "amount": 663.51}, {"type": "quarterly_adjustment", "amount": 52.91},
                    {"type": "fpa", "amount": 125.27}, {"type": "surcharge", "amount": 64.93}],
        "total_charges": 2860.62, "total_taxes": 569.62, "current_bill": 3430.24, "arrears": -0.53,
        "payable_within_due_date": 3430, "payable_after_due_date": 3716,
    }
    data.update(overrides)
    return postprocess(data)


class FakeAsk:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.reply


def test_consistent_bills_pass_without_reread():
    for bill in (lesco_bill(), ke_bill()):
        ask = FakeAsk({})
        checks = run_checks(bill, ask)["checks"]
        assert checks["charges_plus_taxes_equal_current_bill"] == "ok"
        assert checks["charge_lines_sum_to_subtotal"] == "ok"
        assert checks["payable_equals_current_bill_plus_arrears"] == "ok"
        assert ask.prompts == []


def test_misread_tax_total_is_corrected():
    bill = ke_bill(total_taxes=869.62)  # 5 misread as 8
    ask = FakeAsk({"total_charges": 2860.62, "total_taxes": 569.62, "current_bill": 3430.24})
    checks = run_checks(bill, ask)["checks"]
    assert checks["charges_plus_taxes_equal_current_bill"] == "fixed"
    assert bill["total_taxes"] == 569.62


def test_inconsistent_reread_is_rejected():
    bill = ke_bill(total_taxes=869.62)
    ask = FakeAsk({"total_charges": 1, "total_taxes": 2, "current_bill": 999})
    checks = run_checks(bill, ask)["checks"]
    assert checks["charges_plus_taxes_equal_current_bill"] == "mismatch"
    assert bill["total_taxes"] == 869.62  # original kept


def test_late_amount_picked_as_payable_is_corrected():
    bill = lesco_bill(payable_within_due_date=8906)  # the "Till <date>" amount
    ask = FakeAsk({"payable_within_due_date": 8567, "payable_after_due_date": 9245})
    checks = run_checks(bill, ask)["checks"]
    assert checks["payable_equals_current_bill_plus_arrears"] == "fixed"
    assert bill["payable_within_due_date"] == 8567


def test_missing_charge_line_is_restored():
    # Old LESCO layout: the extraction skipped the "FUEL PRICE ADJUSTMENT 193.60" line.
    lines = [{"type": "energy", "amount": 938.5}, {"type": "surcharge", "amount": 38.27},
             {"type": "quarterly_adjustment", "amount": 31.19}, {"type": "fixed", "amount": 400}]
    bill = lesco_bill(charges=lines, total_charges=1601.56, total_taxes=308.44, current_bill=1678.5,
                      total_fpa=231.5, payable_within_due_date=1910, payable_after_due_date=2051)
    fixed = [*lines, {"type": "fpa", "amount": 193.6}]
    checks = run_checks(bill, FakeAsk({"charges": fixed}))["checks"]
    assert checks["charge_lines_sum_to_subtotal"] == "fixed"
    assert {"type": "fpa", "amount": 193.6} in bill["charges"]
    assert checks["charges_plus_taxes_equal_current_bill"] == "ok"   # current bill excludes Total FPA here


def test_failed_reread_never_raises():
    def boom(prompt):
        raise RuntimeError("rate limited")
    bill = ke_bill(total_taxes=869.62)
    assert run_checks(bill, boom)["checks"]["charges_plus_taxes_equal_current_bill"] == "mismatch"


def test_net_metering_credit_is_consistent():
    bill = lesco_bill(charges=[{"type": "energy", "amount": 17367.77}], total_charges=17367.77, total_taxes=3358.23,
                      current_bill=20726, arrears=-75496, total_fpa=None, payable_within_due_date=-54770,
                      payable_after_due_date=None)
    assert payable_consistent(bill) is True
    assert totals_consistent(bill) is True


def test_missing_values_are_not_applicable():
    bill = postprocess({})
    checks = run_checks(bill)["checks"]
    assert checks["charges_plus_taxes_equal_current_bill"] == "n/a"
    assert charges_consistent(bill) is None


def test_expected_history_months():
    usage, billing = expected_history_months("KE", "2026-04")
    assert usage[0] == "2025-04" and usage[-1] == "2026-04" and len(usage) == 13
    assert billing == ["2026-01", "2026-02", "2026-03"]
    usage, billing = expected_history_months("IESCO", "2026-08")
    assert usage[0] == "2025-08" and usage[-1] == "2026-07" and usage == billing


def test_missing_history_months_detected():
    hist = [{"month": f"2026-{m:02d}", "units": 1, "billed_amount": 1, "payment": 1} for m in range(1, 8)]
    bill = postprocess({"provider": "IESCO", "bill_month": "2026-08", "usage_history": hist, "billing_history": hist})
    missing = missing_history_months(bill)
    assert missing == ["2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]

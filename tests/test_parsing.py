import pytest

from bill_decoder.parsing import normalise_provider, postprocess, shift_month, to_date, to_month, to_number


@pytest.mark.parametrize("raw, expected", [
    ("19,964", 19964),
    ("Rs. 3,430", 3430),
    ("Rs.3,430.24", 3430.24),
    ("38209CR", -38209),
    ("54770 CR", -54770),
    ("-0.53", -0.53),
    ("39411 / 2", 39411),     # arrears with an age suffix must not become 394112
    ("(1,250)", -1250),
    (12.0, 12),
    ("", None),
    ("—", None),
    (None, None),
    (True, None),
])
def test_to_number(raw, expected):
    assert to_number(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("2026-09-22", "2026-09-22"),
    ("22-Sep-2026", "2026-09-22"),
    ("08 AUG 26", "2026-08-08"),
    ("22nd Sep 2026", "2026-09-22"),
    ("not a date", None),
])
def test_to_date(raw, expected):
    assert to_date(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("2026-08", "2026-08"), ("2026-08-01", "2026-08"), ("AUG 26", "2026-08"), ("Aug-2026", "2026-08"),
    ("08/26", "2026-08"), ("JUL 2026", "2026-07"), ("Sep25", "2025-09"), ("garbage", None),
])
def test_to_month(raw, expected):
    assert to_month(raw) == expected


def test_shift_month_wraps_years():
    assert shift_month("2026-01", -1) == "2025-12"
    assert shift_month("2025-12", 1) == "2026-01"
    assert shift_month("2026-09", -12) == "2025-09"


@pytest.mark.parametrize("raw, expected", [
    ("KE", "KE"), ("K-Electric", "KE"), ("LESCO", "LESCO"), ("Lahore Electric Supply Company", "LESCO"),
    ("iesco", "IESCO"), ("WAPDA", None), (None, None),
])
def test_normalise_provider(raw, expected):
    assert normalise_provider(raw) == expected


def test_postprocess_fills_schema_and_cleans_items():
    out = postprocess({
        "provider": "K-Electric", "bill_month": "Sep-26", "due_date": "22-Sep-2026", "arrears": "0.41CR",
        "charges": [{"type": "Energy", "amount": "1,054"}, {"type": "subsidy", "amount": 300},
                    {"type": "weird", "amount": 5}, {"type": "fixed", "amount": 0}],
        "taxes": [{"type": "gst", "amount": "520.21"}, {"type": "tv", "amount": 35}],
    })
    assert out["provider"] == "KE"
    assert out["bill_month"] == "2026-09"
    assert out["due_date"] == "2026-09-22"
    assert out["arrears"] == -0.41
    assert out["tariff"] is None and out["units_consumed"] is None
    assert out["charges"] == [{"type": "energy", "amount": 1054}, {"type": "subsidy", "amount": -300},
                              {"type": "other", "amount": 5}]
    assert out["taxes"] == [{"type": "gst", "amount": 520.21}, {"type": "other_tax", "amount": 35}]


def test_postprocess_sorts_and_dedupes_history():
    out = postprocess({
        "usage_history": [{"month": "MAR 26", "units": 115}, {"month": "2026-01", "units": 96},
                          {"month": "2026-01", "units": 999}, {"month": None, "units": 3}],
        "billing_history": [{"month": "03/26", "billed_amount": "12,136.42", "payment": "12136"},
                            {"month": "01/26", "billed_amount": 10059.17, "payment": None}],
    })
    assert out["usage_history"] == [{"month": "2026-01", "units": 96}, {"month": "2026-03", "units": 115}]
    assert [r["month"] for r in out["billing_history"]] == ["2026-01", "2026-03"]
    assert out["billing_history"][1]["billed_amount"] == 12136.42


def test_postprocess_handles_garbage():
    out = postprocess("not json")
    assert out["charges"] == [] and out["usage_history"] == [] and out["provider"] is None
    assert postprocess([{"provider": "LESCO"}])["provider"] == "LESCO"

import copy

from eval.evaluate import SCALAR_FIELDS, evaluate, load_ground_truth, score_billing, score_usage


def as_prediction(gt):
    pred = {f: gt[f] for f in SCALAR_FIELDS}
    pred["usage_history"] = [{"month": m, "units": u} for m, u in gt["usage_history"].items()]
    pred["billing_history"] = [{"month": m, "billed_amount": b, "payment": p} for m, b, p in gt["billing_history"]]
    return pred


def test_ground_truth_is_well_formed():
    truth = load_ground_truth()
    assert len(truth) == 15
    for bid, gt in truth.items():
        assert set(SCALAR_FIELDS) <= set(gt), bid
        assert gt["usage_history"] and gt["billing_history"], bid


def test_perfect_predictions_score_100():
    truth = load_ground_truth()
    report = evaluate({b: as_prediction(gt) for b, gt in truth.items()}, truth)
    assert report["scalar_accuracy"] == 1 and report["usage_accuracy"] == 1 and report["billing_accuracy"] == 1
    assert report["perfect_bills"] == 15 and report["errors"] == []


def test_errors_are_counted():
    truth = {"X": load_ground_truth()["IESCO_0002"]}
    pred = as_prediction(copy.deepcopy(truth["X"]))
    pred["payable_within_due_date"] = 71388
    pred["tariff"] = "a-1A(01)"  # case differences are not errors
    report = evaluate({"X": pred}, truth)
    assert report["field_accuracy"]["payable_within_due_date"] == 0
    assert report["field_accuracy"]["tariff"] == 1
    assert report["perfect_bills"] == 0


def test_history_scoring_penalises_missing_and_invented_months():
    gt = {"2026-01": 10, "2026-02": 20}
    assert score_usage([{"month": "2026-01", "units": 10}], gt) == (1, 2)
    assert score_usage([{"month": "2026-01", "units": 10}, {"month": "2026-02", "units": 20},
                        {"month": "2026-03", "units": 5}], gt) == (2, 3)
    rows = [["2026-01", 100.5, None]]
    assert score_billing([{"month": "2026-01", "billed_amount": 100.5, "payment": 0}], rows) == (1, 1)
    assert score_billing([{"month": "2026-01", "billed_amount": 100.0, "payment": None}], rows) == (0, 1)

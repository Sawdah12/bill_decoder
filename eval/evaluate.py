"""Score Level-1 extraction against the hand-labelled ground truth.

    python -m eval.evaluate --pred-dir eval/predictions --bills test/bills source/train_bills --run

--run extracts any bill that has no saved prediction yet (needs GEMINI_API_KEY); without it, only
already-saved predictions are scored. Predictions are cached as <pred-dir>/<bill_id>.json.
"""
import argparse
import json
import sys
from pathlib import Path

GT_PATH = Path(__file__).with_name("ground_truth.json")

SCALAR_FIELDS = [
    "provider", "tariff", "sanctioned_load_kw", "bill_month", "reading_date", "issue_date", "due_date",
    "previous_reading", "current_reading", "units_consumed", "total_charges", "total_taxes",
    "current_bill", "arrears", "payable_within_due_date", "payable_after_due_date",
]


def load_ground_truth(path=GT_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def same_number(a, b, tol=0.011):
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def same_value(field, pred, truth):
    if field == "tariff":
        norm = lambda s: None if s is None else str(s).replace(" ", "").casefold()  # noqa: E731
        return norm(pred) == norm(truth)
    if isinstance(truth, (int, float)) or isinstance(pred, (int, float)):
        return same_number(pred, truth)
    return pred == truth


def score_usage(pred_hist, truth_hist):
    """Correct months / (labelled months + extra months the model invented)."""
    pred = {}
    for row in pred_hist or []:
        pred.setdefault(str(row.get("month"))[:7], row.get("units"))
    correct = sum(1 for m, u in truth_hist.items() if m in pred and same_number(pred[m], u))
    extra = len(set(pred) - set(truth_hist))
    return correct, len(truth_hist) + extra


def score_billing(pred_rows, truth_rows):
    """A row counts only if both billed amount and payment match. Blank payment == 0 (both mean unpaid)."""
    pred = {}
    for row in pred_rows or []:
        pred.setdefault(str(row.get("month"))[:7], row)
    correct = 0
    for month, billed, paid in truth_rows:
        p = pred.get(month)
        if p and same_number(p.get("billed_amount"), billed) and same_number(p.get("payment") or 0, paid or 0):
            correct += 1
    extra = len(set(pred) - {r[0] for r in truth_rows})
    return correct, len(truth_rows) + extra


def evaluate(predictions, truth):
    field_hits = {f: 0 for f in SCALAR_FIELDS}
    usage = [0, 0]
    billing = [0, 0]
    per_bill, errors = {}, []
    for bid, gt in truth.items():
        pred = predictions.get(bid)
        if pred is None:
            continue
        hits = 0
        for f in SCALAR_FIELDS:
            if same_value(f, pred.get(f), gt[f]):
                field_hits[f] += 1
                hits += 1
            else:
                errors.append((bid, f, pred.get(f), gt[f]))
        uc, ut = score_usage(pred.get("usage_history"), gt["usage_history"])
        bc, bt = score_billing(pred.get("billing_history"), gt["billing_history"])
        usage[0] += uc; usage[1] += ut          # noqa: E702
        billing[0] += bc; billing[1] += bt      # noqa: E702
        if uc < ut:
            errors.append((bid, "usage_history", f"{uc}/{ut} months right", ""))
        if bc < bt:
            errors.append((bid, "billing_history", f"{bc}/{bt} rows right", ""))
        per_bill[bid] = {"fields": hits, "usage": (uc, ut), "billing": (bc, bt)}
    n = len(per_bill)
    total_fields = sum(field_hits.values())
    return {
        "bills": n,
        "field_accuracy": {f: field_hits[f] / n for f in SCALAR_FIELDS} if n else {},
        "scalar_accuracy": total_fields / (n * len(SCALAR_FIELDS)) if n else 0,
        "usage_accuracy": usage[0] / usage[1] if usage[1] else 0,
        "billing_accuracy": billing[0] / billing[1] if billing[1] else 0,
        "perfect_bills": sum(1 for b in per_bill.values() if b["fields"] == len(SCALAR_FIELDS)
                             and b["usage"][0] == b["usage"][1] and b["billing"][0] == b["billing"][1]),
        "per_bill": per_bill,
        "errors": errors,
    }


def format_report(r):
    lines = [f"Bills evaluated: {r['bills']}",
             f"Scalar fields:   {r['scalar_accuracy']:.1%}  ({len(SCALAR_FIELDS)} fields per bill)",
             f"Usage history:   {r['usage_accuracy']:.1%}  (month-level)",
             f"Billing history: {r['billing_accuracy']:.1%}  (row-level, billed + payment)",
             f"Fully correct bills: {r['perfect_bills']}/{r['bills']}", "", "Per-field accuracy:"]
    for f, acc in r["field_accuracy"].items():
        lines.append(f"  {f:<26}{acc:6.1%}")
    if r["errors"]:
        lines += ["", "Errors (bill, field, predicted, expected):"]
        lines += [f"  {b:<11} {f:<24} {p!r:<22} {t!r}" for b, f, p, t in r["errors"]]
    return "\n".join(lines)


def find_image(dirs, bill_id):
    for d in dirs:
        for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
            p = Path(d) / f"{bill_id}{ext}"
            if p.exists():
                return p
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pred-dir", default="eval/predictions")
    ap.add_argument("--bills", nargs="*", default=["test/bills", "source/train_bills"])
    ap.add_argument("--run", action="store_true", help="extract bills that have no saved prediction")
    ap.add_argument("--json", help="also write the summary as JSON to this path")
    args = ap.parse_args(argv)

    truth = load_ground_truth()
    pred_dir = Path(args.pred_dir)
    pred_dir.mkdir(parents=True, exist_ok=True)
    predictions = {}
    for bid in truth:
        path = pred_dir / f"{bid}.json"
        if not path.exists() and args.run:
            img = find_image(args.bills, bid)
            if img is None:
                print(f"skip {bid}: image not found", file=sys.stderr)
                continue
            from bill_decoder.pipeline import extract_bill
            print(f"extracting {bid} ...", file=sys.stderr)
            path.write_text(json.dumps(extract_bill(str(img)), ensure_ascii=False, indent=1), encoding="utf-8")
        if path.exists():
            predictions[bid] = json.loads(path.read_text(encoding="utf-8"))

    report = evaluate(predictions, truth)
    print(format_report(report))
    if args.json:
        summary = {k: v for k, v in report.items() if k not in ("errors", "per_bill")}
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

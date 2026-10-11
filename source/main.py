"""Fill level1.csv and level2.csv for a folder of bill images.

Usage: python main.py --bills <bills_folder> --csv <csv_folder> --out <output_folder>
"""
import argparse
import csv
import json
from pathlib import Path

from pipeline import extract_bill, answer_questions, postprocess


def find_image(bills_dir, bill_id):
    for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
        p = Path(bills_dir) / f"{bill_id}{ext}"
        if p.exists():
            return str(p)
    return None


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bills", required=True, help="folder with bill images")
    ap.add_argument("--csv", required=True, help="folder with level1.csv and level2.csv templates")
    ap.add_argument("--out", required=True, help="output folder")
    args = ap.parse_args()

    out_dir = Path(args.out)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    l1_fields, l1_rows = read_csv(Path(args.csv) / "level1.csv")
    l2_fields, l2_rows = read_csv(Path(args.csv) / "level2.csv")
    bill_ids = list(dict.fromkeys([r["bill_id"] for r in l1_rows] + [r["bill_id"] for r in l2_rows]))

    # ---- Level 1: extraction (cached so re-runs don't repeat API calls) ----
    bills = {}
    for i, bid in enumerate(bill_ids, 1):
        cache = cache_dir / f"{bid}_l1.json"
        img = find_image(args.bills, bid)
        print(f"[L1 {i}/{len(bill_ids)}] {bid}")
        if cache.exists():
            bills[bid] = json.loads(cache.read_text(encoding="utf-8"))
            continue
        if not img:
            print(f"  WARNING: no image found for {bid}")
            bills[bid] = postprocess({})
            continue
        try:
            bills[bid] = extract_bill(img)
            cache.write_text(json.dumps(bills[bid], ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"  ERROR extracting {bid}: {e}")
            bills[bid] = postprocess({})

    for row in l1_rows:
        data = {k: v for k, v in bills[row["bill_id"]].items() if k not in ("usage_history", "billing_history")}        
        row["json"] = json.dumps(data, ensure_ascii=False)
    write_csv(out_dir / "level1.csv", l1_fields, l1_rows)
    print(f"Wrote {out_dir / 'level1.csv'}")

    # ---- Level 2: one Q&A call per bill ----
    for i, bid in enumerate(bill_ids, 1):
        rows = [r for r in l2_rows if r["bill_id"] == bid]
        if not rows:
            continue
        print(f"[L2 {i}/{len(bill_ids)}] {bid}")
        cache = cache_dir / f"{bid}_l2.json"
        if cache.exists():
            answers = json.loads(cache.read_text(encoding="utf-8"))
        else:
            questions = [(r["question_id"], r["question"]) for r in rows]
            img = find_image(args.bills, bid)
            answers = answer_questions(img, bills[bid], questions) if img else {}
            if img:
                cache.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
        for r in rows:
            r["answer"] = answers.get(r["question_id"]) or "The bill image could not be read, so this question cannot be answered."
    write_csv(out_dir / "level2.csv", l2_fields, l2_rows)
    print(f"Wrote {out_dir / 'level2.csv'}")


if __name__ == "__main__":
    main()
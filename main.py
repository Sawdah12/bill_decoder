"""Fill level1.csv and level2.csv for a folder of bill images.

Usage: python main.py --bills <bills_folder> --csv <csv_folder> --out <output_folder>
"""
import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bill_decoder.parsing import postprocess
from bill_decoder.pipeline import answer_questions, extract_bill, level1_record

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG")


def find_image(bills_dir, bill_id):
    for ext in IMAGE_EXTS:
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


def cached(path, compute):
    """Return the JSON cached at `path`, or compute it, cache it and return it."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = compute()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    return value


def extract_one(bills_dir, cache_dir, bid):
    img = find_image(bills_dir, bid)
    if not img:
        print(f"  WARNING: no image found for {bid}")
        return bid, postprocess({})
    try:
        return bid, cached(cache_dir / f"{bid}_l1.json", lambda: extract_bill(img))
    except Exception as e:
        print(f"  ERROR extracting {bid}: {e}")
        return bid, postprocess({})


def answer_one(bills_dir, cache_dir, bid, bill, rows):
    img = find_image(bills_dir, bid)
    if not img:
        return bid, {}
    questions = [(r["question_id"], r["question"]) for r in rows]
    return bid, cached(cache_dir / f"{bid}_l2.json", lambda: answer_questions(img, bill, questions))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bills", required=True, help="folder with bill images")
    ap.add_argument("--csv", required=True, help="folder with level1.csv and level2.csv templates")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--workers", type=int, default=2, help="bills processed in parallel (mind API rate limits)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    l1_fields, l1_rows = read_csv(Path(args.csv) / "level1.csv")
    l2_fields, l2_rows = read_csv(Path(args.csv) / "level2.csv")
    bill_ids = list(dict.fromkeys([r["bill_id"] for r in l1_rows] + [r["bill_id"] for r in l2_rows]))

    # ---- Level 1: extraction + consistency checks (cached so re-runs skip finished bills) ----
    print(f"Level 1: extracting {len(bill_ids)} bills")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        bills = dict(pool.map(lambda b: extract_one(args.bills, cache_dir, b), bill_ids))
    for bid in bill_ids:
        flags = {k: v for k, v in (bills[bid].get("checks") or {}).items() if v not in ("ok", "n/a")}
        print(f"  {bid}: {flags or 'all checks passed'}")

    for row in l1_rows:
        row["json"] = json.dumps(level1_record(bills[row["bill_id"]]), ensure_ascii=False)
    write_csv(out_dir / "level1.csv", l1_fields, l1_rows)
    print(f"Wrote {out_dir / 'level1.csv'}")

    # ---- Level 2: one Q&A call per bill ----
    print("Level 2: answering questions")
    rows_by_bill = {bid: [r for r in l2_rows if r["bill_id"] == bid] for bid in bill_ids}
    jobs = [(bid, bills[bid], rows) for bid, rows in rows_by_bill.items() if rows]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        answers = dict(pool.map(lambda j: answer_one(args.bills, cache_dir, *j), jobs))
    for row in l2_rows:
        row["answer"] = (answers.get(row["bill_id"], {}).get(row["question_id"])
                         or "The bill image could not be read, so this question cannot be answered.")
    write_csv(out_dir / "level2.csv", l2_fields, l2_rows)
    print(f"Wrote {out_dir / 'level2.csv'}")


if __name__ == "__main__":
    main()

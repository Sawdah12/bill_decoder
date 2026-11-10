# ⚡ Utility Bill Decoder

[![CI](https://github.com/Sawdah12/bill_decoder/actions/workflows/ci.yml/badge.svg)](https://github.com/Sawdah12/bill_decoder/actions/workflows/ci.yml)

Reads Pakistani electricity bills (**K-Electric, LESCO, IESCO**) from phone photos or scans, turns them into
structured JSON, **cross-checks the numbers against each other**, and answers customer questions about the bill in
plain English ("How much of my bill is taxes?", "Am I using more than last year?").

- **Level 1 – extraction:** bill image → 18-field JSON (tariff, readings, every charge and tax line, arrears,
  payable amounts) + 12–13 months of usage and payment history.
- **Level 2 – Q&A:** grounded answers that quote the bill's own numbers. All arithmetic (averages, trends,
  percentages, estimates) is done in Python, not by the LLM.
- **Streamlit app:** upload a bill, see the extracted values, charts and check results, and chat about it.

## How it works

```
bill image
   │
   ├─► [Gemini] extraction prompt ───────────► schema fields
   ├─► [Gemini] focused history-table prompt ─► usage + billing history (retries naming any skipped month)
   │
   ▼
postprocess (Python): types, dates → ISO, "38209CR" → -38209, dedupe/sort history
   │
   ▼
consistency checks (Python)                           ┌─ charges + taxes            = current bill
   every bill obeys a few identities  ────────────────┤  current bill + arrears (+FPA) = payable by due date
   if one breaks → re-read ONLY those numbers         └─ charge lines              = charges subtotal
   accept the re-read only if it satisfies the identity
   │
   ├──► level1.csv / JSON
   ▼
Python computes exact facts: history stats, same-month-last-year, trends, tax %, late fee, per-unit cost
   │
   ▼
[Gemini] image + validated JSON + facts + all questions for the bill ──► level2.csv / chat answers
```

**Why the consistency checks matter.** A vision model reading a crumpled phone photo will occasionally misread
a digit or grab the wrong box. These errors are rare but the costly kind: the wrong *amount to pay*.
Because a bill's numbers must add up, most such errors can be detected without any labels, and repaired with a
targeted re-read. A repair is accepted only if the new numbers are consistent, so a check can never make a
correct extraction worse. Each bill carries a `checks` report (`ok` / `fixed` / `mismatch`) that the app shows
to the user.

## Evaluation

I hand-labelled **15 real bills** (5 KE, 5 LESCO, 5 IESCO; clean PDFs, scans and tilted phone photos, including
net-metered bills) in [`eval/ground_truth.json`](eval/ground_truth.json): 16 scalar fields per bill, plus every
usage-history month and billing-history row. [`eval/evaluate.py`](eval/evaluate.py) scores predictions per field.

**Baseline (v1, single extraction prompt)** on the 10 held-out test bills:

| Metric | v1 |
|---|---|
| Scalar fields (160) | 98.8% |
| Usage-history months (124) | 97.6% |
| Billing-history rows (84) | 95.2% |
| Bills with **zero** errors | 6 / 10 |

The remaining errors were systematic, which is what drove the v2 changes:

| Error in v1 | Example | v2 fix |
|---|---|---|
| Picked the "Till ‹date›" late amount as *payable within due date* | 25,359 instead of 24,372 | payable identity check + targeted re-read; prompt says explicitly it is never a "Till" amount |
| Misread digit in a subtotal | taxes 3,516 instead of 8,516 | charges + taxes = current bill check + re-read |
| Dropped the history row printed *inside* the table header, shifting months | Aug-25 missing → "same month last year" answered wrongly | dedicated history prompt with the expected month range; retry naming missing months |
| Mixed the Billed and Payment columns | 12,866.04 instead of 12,866.40 | history prompt reads each column separately |
| Q&A substituted a different month when one was missing | compared with Sep-25 instead of Aug-25 | code states "not shown on this bill" explicitly |
| `"39411 / 2"` (arrears + age) parsed as 394112 | – | number parser takes the first number only |

**Offline check of the detectors:** run on v1's outputs (no API calls), the consistency checks flag all 3 bills
that had a wrong money field or a missing charge line (IESCO_0002, LESCO_0002, LESCO_0008) and raise
**no false alarms** on the other 7.

Reproduce:

```bash
python -m eval.evaluate --run           # extracts all labelled bills (cached in eval/predictions/) and scores them
```

> The bill images themselves are not in the repo: they contain personal details. The labels contain no
> personal data.

## Run it

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # add a Gemini API key from Google AI Studio
```

**Web app**

```bash
streamlit run app.py
```

**Batch mode** (fills CSV templates; results are cached so a re-run only repeats failed bills)

```bash
python main.py --bills path/to/bills --csv path/to/templates --out output --workers 2
```

`--csv` holds `level1.csv` (`bill_id,json`) and `level2.csv` (`bill_id,question_id,question,answer`).

**Tests** (offline: the LLM is replaced by a scripted fake, so no key is needed)

```bash
pip install -r requirements-dev.txt
pytest -q && ruff check .
```

## Project layout

| Path | Purpose |
|---|---|
| `bill_decoder/llm.py` | Gemini client: image input, JSON mode, backoff on transient errors, fail-fast on auth errors |
| `bill_decoder/prompts.py` | Extraction, history, re-read and Q&A prompts |
| `bill_decoder/parsing.py` | Schema enforcement and normalisation (numbers, credits, dates, months, providers) |
| `bill_decoder/checks.py` | Consistency checks and accept-only-if-consistent repairs |
| `bill_decoder/stats.py` | Exact history / billing statistics and derived facts for Q&A |
| `bill_decoder/pipeline.py` | `extract_bill()`, `answer_questions()` |
| `main.py` | Batch CLI for the CSV templates |
| `app.py` | Streamlit app |
| `eval/` | Ground-truth labels and the evaluation script |
| `tests/` | 63 unit / pipeline tests |

## Design notes

- **LLM reads, Python computes.** Small vision models miscount chart bars and slip on arithmetic, so the model
  only transcribes values. Counts, averages, maxima, trends, percentages and estimates are computed in code and
  passed to the Q&A prompt as exact facts.
- **Privacy:** prompts forbid outputting names, addresses, CNIC, account or meter numbers, and the schema has no
  field for them.
- **Cost:** 2 calls per bill for extraction (+1–3 targeted re-reads only when a check fails), 1 call per bill for
  all of its questions. Model: `gemini-3.1-flash-lite` (configurable via `MODEL_NAME`).

## Limitations

- 15 labelled bills is a small evaluation set. The checks were designed after inspecting these bills, so
  results on unseen layouts may be lower.
- Values hidden under grey boxes or unreadable are returned as `null` by design.
- On net-metered bills with several meter-reading rows, readings and (sometimes) units are `null`.
- History bar labels on very low-resolution photos can still be misread; the checks cannot detect those.

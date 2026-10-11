# ⚡ Utility Bill Decoder

An AI assistant that reads Pakistani electricity bills (K-Electric, LESCO, IESCO) from scanned images or photos. It does two things:

- **Level 1:** extracts the billing details into a fixed JSON schema.
- **Level 2:** answers customer questions about the bill in plain English.

## Runtime
- Python 3.11
- Dependencies are pinned in `requirements.txt`

## Setup
```bash
cd source
python -m venv venv
source venv/Scripts/activate      # Windows Git Bash  (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env              # then put your API key in .env
```

## Run

**Batch mode (generates both CSVs):**
```bash
python main.py --bills ../test/bills --csv ../test/csv --out ../output
```
- `--bills`: folder of bill images (`.png` / `.jpg`)
- `--csv`: folder containing the `level1.csv` and `level2.csv` templates
- `--out`: where the completed `level1.csv` and `level2.csv` are written

Results are cached in `<out>/cache/`, so a re-run after an error only repeats the failed bills.

**Demo UI:**
```bash
streamlit run app.py
```
Upload a bill to see the extracted fields and usage chart, then ask any question about it.

## Architecture

```
bill image
   │
   ▼
[Gemini call 1] vision + extraction prompt (JSON mode, temperature 0)
   │
   ▼
postprocess (Python): enforce schema, numbers, CR → negative, drop 0-lines, valid types
   │
   ├──► level1.csv
   ▼
Python computes exact facts: usage-history stats, tax %, late-payment extra, per-unit cost
   │
   ▼
[Gemini call 2] image + extracted JSON + computed facts + all questions for that bill (JSON mode)
   │
   ▼
level2.csv
```

| File | Purpose |
|---|---|
| `llm.py` | Gemini client, image input, JSON mode, retry with exponential backoff |
| `prompts.py` | Extraction prompt (schema, rules, worked example) and Q&A prompt |
| `pipeline.py` | `extract_bill()`, `postprocess()`, usage-history stats, `answer_questions()` |
| `main.py` | CLI that fills both CSV templates |
| `app.py` | Streamlit demo |

## How AI is used
- **Reading the bill (Gemini vision):** the model reads the image directly, including tilted photos, Urdu labels and grey-boxed fields. No OCR is used. The prompt holds the full schema, the classification rules and one worked example, and it asks for JSON output.
- **Python does the math, not the LLM:** small models miscount chart bars and slip on arithmetic. The LLM only *reads* values (including the 12/13-month usage history). Python then computes counts, averages, maximum/minimum, percentages and late-payment differences. Those exact facts go to the Q&A call, so answers are grounded and the numbers are correct.
- **Answering questions:** one call per bill answers all its questions together. That cuts API calls to 2 per bill and keeps answers consistent. The prompt requires plain English, bill only facts, labelled estimates, stated interpretations for ambiguous questions, and no personal identifiers.
- **Reliability:** temperature 0, JSON mode, schema enforcement in code, retry with backoff for rate limits, per-bill caching, and fallbacks so a failed bill never crashes the run.

## AI usage
- **Models:** Gemini 3.1 Flash-Lite (`gemini-3.1-flash-lite`)
- **APIs:** Google Gemini API via Google AI Studio (`google-genai` SDK)
- **Other AI services:** none
- **OCR / document-extraction services:** none
- **AI tools used to write the code:** Claude (Anthropic)

## Limitations
- Values covered by grey boxes or unreadable are returned as `null` by design.
- Bars in the usage chart can occasionally be misread on low quality photos.
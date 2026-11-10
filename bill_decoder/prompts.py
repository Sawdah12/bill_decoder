EXTRACTION_PROMPT = """You are an expert at reading Pakistani electricity bills (K-Electric, LESCO, IESCO).
Extract the billing details from the attached bill image and return ONE JSON object with EXACTLY these keys:

{
  "provider": "KE" | "LESCO" | "IESCO",
  "tariff": string,
  "sanctioned_load_kw": number,
  "bill_month": "YYYY-MM",
  "reading_date": "YYYY-MM-DD",
  "issue_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "previous_reading": number,
  "current_reading": number,
  "units_consumed": number,
  "charges": [{"type": "energy|fixed|fpa|quarterly_adjustment|surcharge|meter_rent|subsidy|other", "amount": number}],
  "total_charges": number,
  "taxes": [{"type": "gst|electricity_duty|income_tax|municipal_tax|other_tax", "amount": number}],
  "total_taxes": number,
  "current_bill": number,
  "arrears": number,
  "total_fpa": number,
  "payable_within_due_date": number,
  "payable_after_due_date": number
}

RULES
- Copy values exactly as printed. Do NOT recalculate, round or correct anything.
- Numbers are plain JSON numbers in PKR: remove "Rs.", commas, spaces. "Rs. 19,964" -> 19964.
- Credits are negative: "38209CR" -> -38209, "-0.53" stays -0.53. Subsidies are negative.
- Use null for any value that is not printed, blank, covered by a grey box, or unreadable. Never guess.
- Never output names, addresses, CNIC, account/reference/consumer/meter numbers.
- provider: K-Electric bills -> "KE".
- tariff: exactly as printed (e.g. "A1-R", "A-1a(01)").
- sanctioned_load_kw: labelled "Sanc Load", "S.Load" or "San Load".
- due_date: last date to pay WITHOUT late surcharge.
- previous_reading / current_reading: if the bill shows a single meter reading row, use it. If it shows
  several rows (e.g. Off Peak / Peak / Import / Export), return null for both.
- units_consumed: the units billed this month as printed (e.g. the "Current Month ... units" box, or the
  single UNITS value in meter info). If several unit rows are shown and no single total is printed, null.
- charges: one entry per printed line in the charges section ABOVE the charges subtotal.
  Skip blank lines and lines printed as 0. Keep duplicates as separate entries.
  energy = cost of units (Variable ..., Cost of Electricity, Energy Charges); fixed = Fixed Charges;
  fpa = FPA / FCA / Fuel Price Adjustment; quarterly_adjustment = QTA / Uniform Quarterly Adjustment;
  surcharge = Additional Surcharge (PHL), F.C Surcharge; meter_rent = meter/service rent;
  subsidy = government subsidy/relief (negative); other = anything else.
  LESCO/IESCO "BILL CHARGES BREAKDOWN" layout: Total Electricity Charges -> one energy entry, Subsidies -> subsidy,
  Total FPA -> fpa.
- total_charges: the printed charges subtotal ("Electricity Charges" on KE, "Total Electricity Charges" or the
  LESCO CHARGES "TOTAL" on LESCO/IESCO), else null.
- taxes: one entry per line in the tax/government section, classified by SECTION not name.
  gst = Sales Tax / GST (incl. GST on FPA); electricity_duty = Electricity Duty / ED (incl. ED on FPA);
  income_tax; municipal_tax = municipal/local charges such as MUCT (KMC); other_tax = TV fee, extra/further tax, etc.
  If only one combined tax amount is printed, return [] and put it in total_taxes.
- total_taxes: the printed tax subtotal ("Taxes and Duties", "Taxes", or the GOVT. CHARGES "TOTAL"), else null.
- current_bill: printed amount for this month's bill (KE: "Electricity Charges for current month";
  LESCO/IESCO: "Current Bill").
- arrears: previous dues carried forward ("Previous Dues" / "Arrears" / "ARREAR / AGE"), keep the sign; null if blank.
  If printed with an age suffix like "39411 / 2", the amount is 39411.
- total_fpa: LESCO/IESCO only - the "Total FPA" amount printed next to the charges breakdown. KE: null.
- payable_within_due_date: the amount payable BY the due date (KE: "Amount Due" / "Amount Payable within Due Date";
  LESCO/IESCO: "PAYABLE WITHIN DUE DATE" box, which equals "Grand Total"). It is NEVER one of the
  "Till <date>" / "Upto <date>" / "After <date>" amounts - those are late amounts.
- payable_after_due_date: amount payable after the due date. If several late amounts are shown
  ("Till ..." and "After ..."), use the HIGHEST. "NOT TO BE PAID" -> null.
- Net metering lines (e.g. "Net Metering Benefit") printed below the charges/tax subtotals are NOT charges.

EXAMPLE (a KE bill) -> correct output:
{"provider":"KE","tariff":"A1-R","sanctioned_load_kw":3,"bill_month":"2026-04","reading_date":"2026-04-03",
"issue_date":"2026-04-07","due_date":"2026-04-21","previous_reading":8819,"current_reading":8970,"units_consumed":151,
"charges":[{"type":"fixed","amount":900},{"type":"energy","amount":1054},{"type":"energy","amount":663.51},
{"type":"quarterly_adjustment","amount":52.91},{"type":"fpa","amount":125.27},{"type":"surcharge","amount":64.93}],
"total_charges":2860.62,"taxes":[{"type":"electricity_duty","amount":29.41},{"type":"gst","amount":520.21},
{"type":"municipal_tax","amount":20}],"total_taxes":569.62,"current_bill":3430.24,"arrears":-0.53,"total_fpa":null,
"payable_within_due_date":3430,"payable_after_due_date":3716}

Return ONLY the JSON object."""


HISTORY_PROMPT = """You are reading the HISTORY section of a Pakistani electricity bill (<<PROVIDER>>, bill month <<BILL_MONTH>>).
Read it slowly, row by row, and return ONE JSON object:

{"usage_history": [{"month": "YYYY-MM", "units": number}],
 "billing_history": [{"month": "YYYY-MM", "billed_amount": number, "payment": number|null}]}

WHERE TO LOOK
<<LAYOUT>>

RULES
- Oldest month first. One entry per month. Copy every number exactly as printed, including decimals and minus signs.
- Each row/bar has its own month label - use it. Do not shift values between months.
- Read each column separately: never copy a value from the PAYMENT column into the BILL column or vice versa.
- Negative values stay negative ("-809" -> -809). Credits printed as "CR" are negative.
- payment: null if the cell is blank, 0 if printed 0.
- The FIRST row under a table header is often printed overlapping the header text (e.g. "MONTH 25 ... UNITS 781
  BILL(RS.) -35,552" squeezed into the header line). It is still a real month - include it.
- If no history is printed, return empty lists.

Return ONLY the JSON object."""

LAYOUT_DISCO = """- LESCO/IESCO bills have one "BILL HISTORY" table with columns MONTH, (STATUS), UNITS, BILL (RS.), (ADJ.), PAYMENT (RS.).
  It is often split into two blocks side by side (6 months left, 6 months right) - read BOTH blocks.
- Each table row gives one usage_history entry (MONTH, UNITS) and one billing_history entry (MONTH, BILL, PAYMENT).
- The table normally covers the 12 months <<FIRST>> to <<LAST>>."""

LAYOUT_KE = """- usage_history: the "13 Month Usage History" bar chart. Each bar has its units printed on/inside it and the month
  under it; years are shown above the chart. It normally covers the 13 months <<FIRST>> to <<LAST>> (the last, dark
  bar is the current month).
- billing_history: the "Billing & Payment History" table (MM/YY, Billed Amount, Pay-Date, Payment). Usually 3 rows.
  billed_amount comes from the "Billed Amount" column (has 2 decimals), payment from the "Payment" column."""

HISTORY_RETRY_PROMPT = """Look again at the history section of this bill. Your previous reading was missing these months:
<<MISSING>>. They are usually there - often the first row of a table block is squeezed into the header line.
Re-read the WHOLE history section carefully and return the complete JSON again, in the same format:
{"usage_history": [{"month": "YYYY-MM", "units": number}],
 "billing_history": [{"month": "YYYY-MM", "billed_amount": number, "payment": number|null}]}
If a month is truly not printed, leave it out. Never invent values."""

TOTALS_RETRY_PROMPT = """Look again at this electricity bill. I read: total electricity charges = <<TC>>, taxes total = <<TT>>,
current bill = <<CB>>. These do not add up (charges + taxes, less any subsidy, should equal the current bill), so a digit
was probably misread (e.g. 3 vs 8, 1 vs 7, 5 vs 6). Re-read these three printed numbers digit by digit, exactly as
printed. Return JSON: {"total_charges": number, "total_taxes": number, "current_bill": number}"""

PAYABLE_RETRY_PROMPT = """Look again at this electricity bill. I read "payable within due date" = <<PW>> and
"payable after due date" = <<PA>>, but with current bill <<CB>> and arrears <<AR>> that does not look right.
Re-read them exactly as printed:
- payable_within_due_date: the amount to pay BY the due date ("Amount Due", "Amount Payable within Due Date",
  "PAYABLE WITHIN DUE DATE", "Grand Total"; also printed on the bank stub at the bottom). NOT a "Till <date>" amount.
- payable_after_due_date: the HIGHEST late amount ("After <date>").
Return JSON: {"payable_within_due_date": number, "payable_after_due_date": number|null}"""

CHARGES_RETRY_PROMPT = """Look again at the charges section of this electricity bill. The printed charges subtotal is <<TC>>,
but the charge lines I read add up to <<SUM>>: <<ITEMS>>. A line is probably missing or misread
(for example Fuel Price Adjustment / FPA / FCA). List EVERY non-zero line above the charges subtotal again, exactly as
printed, classified as energy|fixed|fpa|quarterly_adjustment|surcharge|meter_rent|subsidy|other.
Return JSON: {"charges": [{"type": string, "amount": number}]}"""


QA_PROMPT = """You are a friendly assistant that explains Pakistani electricity bills to customers.
You are given the bill image and the details already extracted from it (JSON below).
Answer EVERY question using ONLY information printed on this bill.

RULES
- Answer in clear, plain English (even if parts of the bill are in Urdu). 1-4 sentences each.
- Be specific: quote the exact amounts (PKR), units, dates and month names from the bill.
- Use the numbers in computed_facts, history_stats and billing_stats: they were calculated exactly by code.
  Do not redo the arithmetic and do not count chart bars yourself.
- Give the relevant breakdown when the bill shows it: e.g. for taxes, list each tax line and its amount;
  for charges, list each charge line. Also mention any percentage split printed on the bill.
- For "how much of my bill" questions, give the amount AND its percentage of the current bill.
- For usage-history counts/averages, say whether the current month is included. If including it changes
  the answer, give both (history_stats has both versions).
- If history_stats says a month is not shown on the bill (e.g. same month last year), say so plainly.
  Never substitute a different month.
- For estimates/forecasts, use the estimates in history_stats and computed_facts, call the result an ESTIMATE,
  and explain the method in one sentence.
- For payment questions, use billing_stats and say how many months the bill actually shows.
- If a question has more than one reasonable meaning, say which meaning you used, or answer both.
- If the bill does not show the needed information, say so plainly. Never guess or use outside tariff rates.
- Credits are shown as negative amounts or "CR"; explain them as credits in your answer.
- Never mention names, addresses, CNIC, account, reference, consumer or meter numbers.

EXTRACTED BILL DETAILS:
<<BILL_JSON>>

QUESTIONS:
<<QUESTIONS>>

Return ONE JSON object mapping each question id to its answer string, e.g.
{"Q1": "answer...", "Q2": "answer..."}"""

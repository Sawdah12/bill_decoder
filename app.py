import hashlib
import json
import tempfile
from pathlib import Path

import streamlit as st

from bill_decoder.pipeline import answer_questions, extract_bill, level1_record

st.set_page_config(page_title="Utility Bill Decoder", page_icon="⚡", layout="wide")

CHECK_LABELS = {
    "charges_plus_taxes_equal_current_bill": "Charges + taxes = current bill",
    "charge_lines_sum_to_subtotal": "Charge lines add up to the subtotal",
    "payable_equals_current_bill_plus_arrears": "Payable = current bill + arrears (+ FPA)",
    "meter_readings_match_units": "Meter readings match units",
    "history_complete": "Usage / billing history complete",
}
CHECK_ICONS = {"ok": "✅", "fixed": "🛠️ re-read and corrected", "n/a": "➖ not applicable"}

if "bills" not in st.session_state:
    st.session_state.bills = {}      # file hash -> {"name", "path", "data", "qa"}
if "current" not in st.session_state:
    st.session_state.current = None


def fmt(v, prefix=""):
    if v is None:
        return "—"
    return f"{prefix}{v:,}" if isinstance(v, (int, float)) else str(v)


@st.cache_data(show_spinner=False)
def cached_extract(file_hash, path):  # keyed by content hash, so re-uploading a bill costs no API calls
    return extract_bill(path)


# ---------- Sidebar: add bills + bill list ----------
with st.sidebar:
    st.header("⚡ Bill Decoder")
    st.caption("K-Electric • LESCO • IESCO")
    up = st.file_uploader("➕ Add a bill", type=["png", "jpg", "jpeg"])
    if up:
        digest = hashlib.sha256(up.getvalue()).hexdigest()
        if digest not in st.session_state.bills:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(up.name).suffix)
            tmp.write(up.getvalue())
            tmp.close()
            with st.spinner("Reading the bill and cross-checking the numbers..."):
                try:
                    data = cached_extract(digest, tmp.name)
                    st.session_state.bills[digest] = {"name": up.name, "path": tmp.name, "data": data, "qa": []}
                    st.session_state.current = digest
                except Exception as e:
                    st.error(f"Could not read this bill: {e}")

    if st.session_state.bills:
        st.subheader("📂 Your bills")
        keys = list(st.session_state.bills)
        idx = keys.index(st.session_state.current) if st.session_state.current in keys else 0
        st.session_state.current = st.radio("Select a bill", keys, index=idx, label_visibility="collapsed",
                                            format_func=lambda k: st.session_state.bills[k]["name"])

# ---------- Main area ----------
if not st.session_state.current:
    st.title("⚡ Utility Bill Decoder")
    st.info("Upload a K-Electric, LESCO or IESCO bill (photo or scan) from the sidebar. Gemini reads it, the "
            "numbers are cross-checked against each other, and you can ask questions in plain English.")
    st.stop()

bill = st.session_state.bills[st.session_state.current]
data = bill["data"]
st.title(f"⚡ {data.get('provider') or 'Bill'} — {data.get('bill_month') or ''}")

checks = data.get("checks") or {}
problems = [k for k, v in checks.items() if v not in ("ok", "fixed", "n/a")]
if problems:
    st.warning("Some numbers on this bill did not cross-check — double-check the highlighted values: "
               + ", ".join(CHECK_LABELS.get(k, k) for k in problems))

m = st.columns(4)
m[0].metric("Units consumed", fmt(data.get("units_consumed")))
m[1].metric("Current bill", fmt(data.get("current_bill"), "PKR "))
m[2].metric("Payable by due date", fmt(data.get("payable_within_due_date"), "PKR "))
m[3].metric("Due date", fmt(data.get("due_date")))
m = st.columns(4)
m[0].metric("Tariff", fmt(data.get("tariff")))
m[1].metric("Arrears", fmt(data.get("arrears"), "PKR "))
m[2].metric("Payable after due date", fmt(data.get("payable_after_due_date"), "PKR "))
m[3].metric("Taxes", fmt(data.get("total_taxes"), "PKR "))

left, right = st.columns([1, 1])
with left:
    st.image(bill["path"], caption=bill["name"], width="stretch")
with right:
    tabs = st.tabs(["💰 Charges & taxes", "📊 Usage history", "🧾 Payments", "✔️ Checks", "{ } JSON"])
    with tabs[0]:
        st.markdown("**Charges**")
        st.dataframe(data.get("charges") or [{"type": "—", "amount": None}], width="stretch")
        st.markdown("**Taxes**")
        st.dataframe(data.get("taxes") or [{"type": "combined total only", "amount": data.get("total_taxes")}],
                     width="stretch")
    with tabs[1]:
        hist = data.get("usage_history") or []
        if hist:
            st.bar_chart({h["month"]: h["units"] for h in hist}, x_label="Month", y_label="Units")
        else:
            st.write("No usage history printed on this bill.")
    with tabs[2]:
        rows = data.get("billing_history") or []
        if rows:
            st.dataframe(rows, width="stretch")
        else:
            st.write("No billing history printed on this bill.")
    with tabs[3]:
        for key, status in checks.items():
            st.write(f"{CHECK_ICONS.get(status, '⚠️ ' + status)} — {CHECK_LABELS.get(key, key)}")
    with tabs[4]:
        record = level1_record(data)
        st.json(record, expanded=False)
        st.download_button("Download JSON", json.dumps(record, indent=2), file_name=f"{Path(bill['name']).stem}.json",
                           mime="application/json")

st.divider()
st.subheader("💬 Ask about this bill")
quick = ["How much of my bill is taxes?", "Which month had the highest units?",
         "What will I pay after the due date?", "How many units should I expect next month?"]
qc = st.columns(len(quick))
clicked = None
for i, q in enumerate(quick):
    if qc[i].button(q, key=f"quick_{i}", width="stretch"):
        clicked = q
typed = st.chat_input("Ask your own question about this bill...")
question = clicked or typed
if question:
    with st.spinner("Thinking..."):
        ans = answer_questions(bill["path"], data, [("Q1", question)])["Q1"]
    bill["qa"].append((question, ans))

for q, a in reversed(bill["qa"]):
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        st.write(a)

import tempfile
from pathlib import Path

import streamlit as st
from pipeline import extract_bill, answer_questions

st.set_page_config(page_title="Utility Bill Decoder", page_icon="⚡", layout="wide")

if "bills" not in st.session_state:
    st.session_state.bills = {}      # file name -> {"path", "data", "qa"}
if "current" not in st.session_state:
    st.session_state.current = None


def fmt(v, prefix=""):
    if v is None:
        return "—"
    return f"{prefix}{v:,}" if isinstance(v, (int, float)) else str(v)


# ---------- Sidebar: add bills + bill history ----------
with st.sidebar:
    st.header("⚡ Bill Decoder")
    st.caption("K-Electric • LESCO • IESCO")
    up = st.file_uploader("➕ Add a new bill", type=["png", "jpg", "jpeg"])
    if up and up.name not in st.session_state.bills:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(up.name).suffix)
        tmp.write(up.getvalue())
        tmp.close()
        with st.spinner("Reading the bill with Gemini..."):
            try:
                data = extract_bill(tmp.name)
                st.session_state.bills[up.name] = {"path": tmp.name, "data": data, "qa": []}
                st.session_state.current = up.name
            except Exception as e:
                st.error(f"Could not read this bill: {e}")

    if st.session_state.bills:
        st.subheader("📂 Your bills")
        names = list(st.session_state.bills)
        idx = names.index(st.session_state.current) if st.session_state.current in names else 0
        st.session_state.current = st.radio("Select a bill", names, index=idx, label_visibility="collapsed")

# ---------- Main area ----------
if not st.session_state.current:
    st.title("⚡ Utility Bill Decoder")
    st.info("Upload a K-Electric, LESCO or IESCO bill from the sidebar. Gemini reads it, extracts every "
            "detail, and answers your questions in plain English.")
    st.stop()

bill = st.session_state.bills[st.session_state.current]
data = bill["data"]
st.title(f"⚡ {data.get('provider') or 'Bill'} — {data.get('bill_month') or ''}")

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
    st.image(bill["path"], caption=st.session_state.current, use_container_width=True)
with right:
    t1, t2, t3 = st.tabs(["💰 Charges & taxes", "📊 Usage history", "🧾 Level 1 JSON"])
    with t1:
        st.markdown("**Charges**")
        st.dataframe(data.get("charges") or [{"type": "—", "amount": None}], use_container_width=True)
        st.markdown("**Taxes**")
        st.dataframe(data.get("taxes") or [{"type": "combined total only", "amount": data.get("total_taxes")}],
                     use_container_width=True)
    with t2:
        hist = data.get("usage_history") or []
        if hist:
            st.bar_chart({h["month"]: h["units"] for h in hist})
        else:
            st.write("No usage history printed on this bill.")
    with t3:
        st.json({k: v for k, v in data.items() if k not in ("usage_history", "billing_history")}, expanded=False)

st.divider()
st.subheader("💬 Ask about this bill")
quick = ["How much of my bill is taxes?", "Which month had the highest units?",
         "What will I pay after the due date?", "How many units should I expect next month?"]
qc = st.columns(len(quick))
clicked = None
for i, q in enumerate(quick):
    if qc[i].button(q, key=f"quick_{i}", use_container_width=True):
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
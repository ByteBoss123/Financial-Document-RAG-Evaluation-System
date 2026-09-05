"""
dashboard.py

Streamlit monitoring dashboard for FinDocQA. Shows failure rate over time
by category, latency distribution, and a searchable log of flagged
requests -- the "is this thing quietly degrading" view that's missing from
most RAG demos.

Run:
    streamlit run dashboard/dashboard.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.observability import load_logs

st.set_page_config(page_title="FinDocQA Monitoring", layout="wide")
st.title("FinDocQA — LLM Failure Mode Monitoring")
st.caption(
    "Observability dashboard for a financial-filings RAG service. "
    "Tracks failure rate by category, retrieval confidence, and latency "
    "across every logged request."
)

logs = load_logs()

if not logs:
    st.warning(
        "No requests logged yet. Start the API (`uvicorn app.main:app`) and "
        "send a few questions to `/ask`, then refresh this page."
    )
    st.stop()

df = pd.DataFrame(logs)
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
df["passed"] = df["passed"].fillna(False)

# --- Top-line metrics ---------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
total = len(df)
failed = (~df["passed"]).sum()
fail_rate = failed / total if total else 0
avg_latency = df["latency_ms"].mean()
avg_top_score = df["top_score"].mean()

col1.metric("Total requests", total)
col2.metric("Failure rate", f"{fail_rate:.1%}", delta=None)
col3.metric("Avg latency", f"{avg_latency:.0f} ms")
col4.metric("Avg retrieval confidence", f"{avg_top_score:.2f}" if pd.notna(avg_top_score) else "N/A")

st.divider()

# --- Failure rate over time, by category --------------------------------
st.subheader("Failure categories over time")

exploded = df.explode("failure_categories")
exploded = exploded[exploded["failure_categories"].notna()]

if not exploded.empty:
    time_bucket = exploded.set_index("timestamp").resample("5min")["failure_categories"]
    cat_counts = (
        exploded.groupby([pd.Grouper(key="timestamp", freq="5min"), "failure_categories"])
        .size()
        .reset_index(name="count")
    )
    fig = px.bar(
        cat_counts, x="timestamp", y="count", color="failure_categories",
        title="Flagged failures over time (5-min buckets)",
        labels={"failure_categories": "Failure category"},
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No failures flagged yet — nothing to chart here, which is good news.")

# --- Failure breakdown pie ------------------------------------------------
left, right = st.columns(2)

with left:
    if not exploded.empty:
        cat_totals = exploded["failure_categories"].value_counts().reset_index()
        cat_totals.columns = ["category", "count"]
        fig2 = px.pie(cat_totals, names="category", values="count", title="Failure mix")
        st.plotly_chart(fig2, use_container_width=True)

with right:
    fig3 = px.histogram(
        df, x="top_score", nbins=20,
        title="Retrieval confidence distribution",
        labels={"top_score": "Top similarity score"},
    )
    fig3.add_vline(x=0.35, line_dash="dash", line_color="red",
                    annotation_text="failure threshold")
    st.plotly_chart(fig3, use_container_width=True)

# --- Latency trend ---------------------------------------------------------
st.subheader("Latency over time")
fig4 = px.line(df.sort_values("timestamp"), x="timestamp", y="latency_ms",
               title="Request latency (ms)", markers=True)
st.plotly_chart(fig4, use_container_width=True)

# --- Flagged request browser ----------------------------------------------
st.subheader("Flagged requests")
flagged = df[~df["passed"]].sort_values("timestamp", ascending=False)

if flagged.empty:
    st.success("No flagged requests in the log.")
else:
    for _, row in flagged.iterrows():
        with st.expander(f"⚠️ {row['question'][:80]}  —  {', '.join(row['failure_categories'])}"):
            st.write(f"**Question:** {row['question']}")
            st.write(f"**Answer:** {row['answer']}")
            st.write(f"**Top retrieval score:** {row.get('top_score')}")
            st.write(f"**Failure details:**")
            for d in row.get("failure_details", []):
                st.write(f"- {d}")

st.divider()
st.subheader("Raw request log")
st.dataframe(
    df[["timestamp", "question", "passed", "failure_categories", "top_score", "latency_ms"]]
    .sort_values("timestamp", ascending=False),
    use_container_width=True,
)

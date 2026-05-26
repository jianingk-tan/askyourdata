"""
app.py — AskYourData Streamlit interface.

Design notes:
  • Editorial-style typography (serif display + sans body) — avoids generic SaaS look
  • Deep navy + amber accent, not the usual purple-on-white AI aesthetic
  • SQL is shown transparently so recruiters can see the agent's reasoning
  • Sample questions in the sidebar so a reviewer can demo it in 30 seconds
"""

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.agent import ask_agent
from src.sql_tools import get_schema
from src.visualizer import auto_chart

load_dotenv()

# ---------- Auto-download database on first launch ----------
# Streamlit Cloud doesn't have the 24 MB northwind.db file (it's gitignored).
# Download it on first launch so the app works out of the box.

DB_FILE = Path(__file__).resolve().parent / "data" / "northwind.db"
if not DB_FILE.exists():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with st.spinner("First-time setup: downloading Northwind database (~24 MB)..."):
        import urllib.request
        try:
            urllib.request.urlretrieve(
                "https://github.com/jpwhite3/northwind-SQLite3/raw/main/dist/northwind.db",
                DB_FILE,
            )
        except Exception as exc:
            st.error(f"Failed to download database: {exc}")
            st.stop()
    st.success("Database ready! Refreshing...")
    st.rerun()

# ---------- Page config ----------

st.set_page_config(
    page_title="AskYourData",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Custom styling ----------
# Editorial / minimalist palette — no purple-gradient AI slop.

CUSTOM_CSS = """
<style>
  /* Typography — serif for display, geometric sans for body */
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Inter+Tight:wght@400;500;600&display=swap');

  html, body, [class*="css"] {
      font-family: 'Inter Tight', -apple-system, BlinkMacSystemFont, sans-serif;
  }

  h1, h2, h3 {
      font-family: 'Fraunces', Georgia, serif !important;
      font-weight: 600 !important;
      letter-spacing: -0.02em;
  }

  /* Headline block */
  .ayd-hero {
      border-left: 3px solid #C2410C;
      padding-left: 1.25rem;
      margin: 0.5rem 0 1.75rem 0;
  }
  .ayd-hero h1 {
      font-size: 2.4rem !important;
      margin: 0 0 0.25rem 0 !important;
      color: #0F172A;
  }
  .ayd-hero p {
      color: #64748B;
      font-size: 1.0rem;
      margin: 0;
      max-width: 640px;
  }

  /* Insight callout */
  .ayd-insight {
      background: #FFF7ED;
      border-left: 3px solid #C2410C;
      padding: 1rem 1.25rem;
      border-radius: 4px;
      font-size: 1.02rem;
      line-height: 1.6;
      color: #1F2937;
  }

  /* Sample-question buttons */
  .stButton > button {
      width: 100%;
      text-align: left;
      background: #F8FAFC;
      border: 1px solid #E2E8F0;
      color: #334155;
      font-size: 0.88rem;
      padding: 0.55rem 0.75rem;
      border-radius: 4px;
      transition: all 0.15s ease;
  }
  .stButton > button:hover {
      border-color: #C2410C;
      color: #C2410C;
      background: #FFF7ED;
  }

  /* Primary button (Analyze) */
  .stButton button[kind="primary"] {
      background: #0F172A;
      color: #FFFFFF;
      border-color: #0F172A;
      text-align: center;
      font-weight: 500;
      min-width: 140px;
      padding: 0.55rem 1.5rem;
      margin-top: 0.5rem;
  }
  .stButton button[kind="primary"]:hover {
      background: #C2410C;
      border-color: #C2410C;
      color: #FFFFFF;
  }

  /* Meta info row */
  .ayd-meta {
      color: #94A3B8;
      font-size: 0.82rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-top: 1.5rem;
      margin-bottom: 0.5rem;
  }

  /* Footer */
  .ayd-footer {
      color: #94A3B8;
      font-size: 0.78rem;
      text-align: center;
      padding: 2rem 0 0.5rem 0;
      border-top: 1px solid #E2E8F0;
      margin-top: 3rem;
  }

  /* Hide Streamlit branding for a cleaner demo */
  #MainMenu { visibility: hidden; }
  footer { visibility: hidden; }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------- Sample questions ----------

SAMPLE_QUESTIONS = [
    "Which 5 customers brought in the most revenue?",
    "What's the average order value by country?",
    "Which employee closed the most orders?",
    "Show me monthly revenue for the most recent 12 months in the data",
    "Which product categories generate the highest revenue?",
    "Which suppliers ship from outside North America?",
]


# ---------- Sidebar ----------

with st.sidebar:
    st.markdown("### Try a question")
    st.caption("Tap any example to load it.")

    for q in SAMPLE_QUESTIONS:
        if st.button(q, key=f"sample_{q}"):
            st.session_state["question"] = q

    st.markdown("---")
    st.markdown("### About")
    st.markdown(
        "**AskYourData** is an AI agent that turns plain-English questions "
        "into SQL, validates them, and explains the results in business terms. "
        "Queries run against Microsoft's classic Northwind sample database — "
        "a small-business ERP with 16K orders, 93 customers, 77 products, "
        "and 9 employees."
    )

    with st.expander("View database schema"):
        st.code(get_schema(), language="sql")

    st.markdown("---")
    st.markdown("### Built with")
    st.markdown(
        "- Anthropic Claude (tool use)\n"
        "- SQLite + sqlparse safety layer\n"
        "- Streamlit + Plotly"
    )

    # Show API key status (without revealing the key)
    if os.getenv("ANTHROPIC_API_KEY"):
        st.success("API key loaded ✓", icon="🔑")
    else:
        st.error("ANTHROPIC_API_KEY not set", icon="⚠️")


# ---------- Hero ----------

st.markdown(
    """
    <div class="ayd-hero">
      <h1>AskYourData</h1>
      <p>Type a business question in plain English. The agent writes the SQL,
      executes it safely, and explains what the numbers mean.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------- Input ----------

question = st.text_input(
    "Your question",
    value=st.session_state.get("question", ""),
    placeholder="e.g. Which products generated the most revenue last year?",
    label_visibility="collapsed",
)

run = st.button("Analyze", type="primary", use_container_width=False)


# ---------- Run the agent ----------

if run and question.strip():
    if not os.getenv("ANTHROPIC_API_KEY"):
        st.error(
            "No API key found. Add `ANTHROPIC_API_KEY=...` to your `.env` file "
            "(or to Streamlit secrets if deployed) and refresh."
        )
        st.stop()

    with st.spinner("Agent is thinking..."):
        result = ask_agent(question)

    # ---------- Meta info ----------
    st.markdown(
        f'<div class="ayd-meta">Iterations: {result.iterations} · '
        f'SQL queries: {len(result.sql_queries)}</div>',
        unsafe_allow_html=True,
    )

    # ---------- Insight ----------
    st.markdown("### Insight")
    st.markdown(
        f'<div class="ayd-insight">{result.final_answer}</div>',
        unsafe_allow_html=True,
    )

    # ---------- Data + chart ----------
    last_result = result.last_successful_result
    if last_result and last_result.get("rows"):
        df = pd.DataFrame(last_result["rows"])

        # Chart first (visual impact), data table below
        fig = auto_chart(df)
        if fig is not None:
            st.markdown("### Chart")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Data")
        st.dataframe(df, use_container_width=True, hide_index=True)
        if last_result.get("truncated"):
            st.caption(
                f"Showing first 100 of {last_result['row_count']:,} rows."
            )

    # ---------- SQL transparency ----------
    if result.sql_queries:
        with st.expander(f"🔍 SQL generated by the agent ({len(result.sql_queries)} queries)"):
            for i, sql in enumerate(result.sql_queries, start=1):
                st.markdown(f"**Query {i}**")
                st.code(sql, language="sql")

    if result.error:
        st.warning(f"Note: {result.error}")

elif run:
    st.info("Please type a question first.")


# ---------- Footer ----------

st.markdown(
    '<div class="ayd-footer">'
    'AskYourData · An agentic SQL analyst built with Claude\'s tool-use API'
    '</div>',
    unsafe_allow_html=True,
)

"""
app.py -- Stock Intel Agent (Prompt 1: minimal, runnable proof-of-life)

This stage only proves the data layer works end to end:
  ticker in -> live data out -> price + day change + a 1-year chart.

Styling and the Robinhood look come in Prompt 2. Keep all data access in
agent/tools.py; this file only calls those functions and renders.
"""

import plotly.graph_objects as go
import streamlit as st

from agent import tools

st.set_page_config(page_title="Stock Intel Agent", page_icon="📈", layout="wide")

st.title("📈 Stock Intel Agent")
st.caption("Educational tool — not financial advice.")

ticker = st.text_input("Ticker", value="AAPL").strip().upper()

if ticker:
    fundamentals = tools.get_fundamentals(ticker)

    if fundamentals is None:
        st.warning(f"Couldn't find data for '{ticker}'. Double-check the symbol and try again.")
    else:
        price = fundamentals["current_price"]
        change = fundamentals["day_change"]
        change_pct = fundamentals["day_change_pct"]

        st.subheader(f"{fundamentals['long_name']} ({fundamentals['symbol']})")

        if price is not None:
            up = (change or 0) >= 0
            arrow = "▲" if up else "▼"
            color = "#16c784" if up else "#ea3943"
            change_txt = ""
            if change is not None and change_pct is not None:
                change_txt = (
                    f"<span style='color:{color};font-size:1.1rem;'>"
                    f"{arrow} {change:+.2f} ({change_pct:+.2f}%)</span>"
                )
            st.markdown(
                f"<div style='font-size:2.4rem;font-weight:700;'>"
                f"{fundamentals['currency']} {price:,.2f}</div>{change_txt}",
                unsafe_allow_html=True,
            )

        # 1-year price chart
        hist = tools.get_price_history(ticker, "1y")
        if hist is None or hist.empty:
            st.info("No price history available for this ticker.")
        else:
            net_up = hist["Close"].iloc[-1] >= hist["Close"].iloc[0]
            line_color = "#16c784" if net_up else "#ea3943"

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=hist["Date"],
                    y=hist["Close"],
                    mode="lines",
                    line=dict(color=line_color, width=2),
                    name="Close",
                )
            )
            fig.update_layout(
                template="plotly_dark",
                height=420,
                margin=dict(l=10, r=10, t=30, b=10),
                title=f"{ticker} — 1Y",
            )
            st.plotly_chart(fig, use_container_width=True)

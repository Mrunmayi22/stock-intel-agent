"""
app.py -- Stock Intel Agent (Prompt 3: dashboard + name-search + news cards)

UI layer only. All data comes from agent/tools.py.
"""

import html
from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st

from agent import tools

st.set_page_config(page_title="Stock Intel Agent", page_icon="📈", layout="centered")

GREEN = "#00c805"
RED = "#ff433d"
MUTED = "#8b949e"
CARD_BG = "#161b22"
BORDER = "#232a33"

RANGES = {"1D": "1d", "1W": "1w", "1M": "1m", "1Y": "1y", "5Y": "5y"}


@st.cache_data(ttl=60, show_spinner=False)
def cached_fundamentals(symbol):
    return tools.get_fundamentals(symbol)


@st.cache_data(ttl=60, show_spinner=False)
def cached_history(symbol, period):
    return tools.get_price_history(symbol, period)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(query):
    return tools.search_symbols(query)


@st.cache_data(ttl=300, show_spinner=False)
def cached_news(symbol):
    return tools.get_news(symbol, limit=6)


st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
      html, body, [class*="css"], .stApp {{
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      }}
      .stApp {{ background-color: #0b0e11; }}
      #MainMenu, header, footer {{ visibility: hidden; }}
      .block-container {{ padding-top: 2.2rem; padding-bottom: 2rem; max-width: 860px; }}

      .stTextInput input {{
          background-color: {CARD_BG}; color: #e6edf3; border: 1px solid {BORDER};
          border-radius: 10px; font-size: 1.05rem; padding: 0.6rem 0.9rem;
      }}
      .stTextInput input:focus {{ border-color: {GREEN}; box-shadow: none; }}

      .company-name {{ color: {MUTED}; font-size: 0.95rem; font-weight: 500; margin-bottom: 0.1rem; }}
      .ticker-badge {{
          display: inline-block; background: {CARD_BG}; border: 1px solid {BORDER};
          color: #e6edf3; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.04em;
          padding: 0.12rem 0.5rem; border-radius: 6px; margin-left: 0.5rem; vertical-align: middle;
      }}
      .price {{ font-size: 2.9rem; font-weight: 800; color: #ffffff; line-height: 1.1; margin: 0.1rem 0; }}
      .change {{ font-size: 1.05rem; font-weight: 600; }}
      .change .range-tag {{ color: {MUTED}; font-weight: 500; }}

      .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; margin-top: 0.5rem; }}
      @media (max-width: 640px) {{ .stat-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
      .stat-card {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 12px; padding: 0.85rem 0.95rem; }}
      .stat-label {{ color: {MUTED}; font-size: 0.68rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.28rem; }}
      .stat-value {{ color: #e6edf3; font-size: 1.15rem; font-weight: 700; }}

      .section-label {{ color: {MUTED}; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin: 1.4rem 0 0.6rem 0; }}

      .news-card {{
          background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 12px;
          padding: 0.85rem 1rem; margin-bottom: 0.6rem; transition: border-color 0.15s ease;
      }}
      .news-card:hover {{ border-color: #3a434e; }}
      .news-card a {{ color: #e6edf3; text-decoration: none; font-weight: 600; font-size: 0.98rem; line-height: 1.35; }}
      .news-card a:hover {{ color: {GREEN}; }}
      .news-meta {{ color: {MUTED}; font-size: 0.75rem; margin-top: 0.35rem; }}
      .news-empty {{ color: {MUTED}; font-size: 0.9rem; padding: 0.6rem 0; }}

      .disclaimer {{ color: #5b636d; font-size: 0.72rem; text-align: center; margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid {BORDER}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def fmt_price(x, currency="$"):
    return "—" if x is None else f"{currency}{x:,.2f}"


def fmt_ratio(x):
    return "—" if x is None else f"{x:,.2f}"


def fmt_pct(x):
    return "—" if x is None else f"{x:.2f}%"


def fmt_big(x):
    if x is None:
        return "—"
    x = float(x)
    for divisor, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if abs(x) >= divisor:
            return f"{x / divisor:.2f}{suffix}"
    return f"{x:,.0f}"


def stat_card(label, value):
    return f'<div class="stat-card"><div class="stat-label">{label}</div><div class="stat-value">{value}</div></div>'


def relative_time(dt):
    """Human '3h ago' style timestamp; tolerant of None, naive datetimes, or ISO strings."""
    if dt is None:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = max((datetime.now(timezone.utc) - dt).total_seconds(), 0)
    mins, hours, days = secs / 60, secs / 3600, secs / 86400
    if secs < 60:
        return "just now"
    if mins < 60:
        return f"{int(mins)}m ago"
    if hours < 24:
        return f"{int(hours)}h ago"
    if days < 7:
        return f"{int(days)}d ago"
    if days < 35:
        return f"{int(days / 7)}w ago"
    if days < 365:
        return f"{int(days / 30)}mo ago"
    return f"{int(days / 365)}y ago"


st.markdown("### 📈 Stock Intel Agent")
query = st.text_input(
    "Search a ticker or company", value="AAPL", label_visibility="collapsed",
    placeholder="Search a ticker or company (e.g. AAPL or Tesla)",
).strip()

if not query:
    st.stop()

fundamentals = cached_fundamentals(query.upper())
ticker = query.upper()

if fundamentals is None:
    matches = cached_search(query)
    if not matches:
        st.warning(f"No matches for '{query}'. Try a different name or symbol.")
        st.stop()
    labels = [f"{m['symbol']} — {m['name']}" + (f"  ·  {m['exchange']}" if m["exchange"] else "")
              for m in matches]
    idx = st.selectbox("Did you mean…", options=list(range(len(matches))),
                       format_func=lambda i: labels[i])
    ticker = matches[idx]["symbol"]
    fundamentals = cached_fundamentals(ticker)
    if fundamentals is None:
        st.warning(f"Couldn't load data for {ticker}. Try another match.")
        st.stop()

range_label = st.segmented_control(
    "Range", options=list(RANGES.keys()), default="1Y", label_visibility="collapsed"
) or "1Y"

hist = cached_history(ticker, RANGES[range_label])

current_price = fundamentals["current_price"]
symbol_sign = "$" if fundamentals.get("currency") == "USD" else f"{fundamentals.get('currency','')} "

change_val = change_pct = None
net_up = True
if hist is not None and not hist.empty:
    first_close = hist["Close"].iloc[0]
    last_close = hist["Close"].iloc[-1]
    if current_price is None:
        current_price = last_close
    change_val = last_close - first_close
    change_pct = (change_val / first_close * 100) if first_close else None
    net_up = change_val >= 0

color = GREEN if net_up else RED
arrow = "▲" if net_up else "▼"

st.markdown(
    f'<div class="company-name">{html.escape(fundamentals["long_name"])}'
    f'<span class="ticker-badge">{fundamentals["symbol"]}</span></div>',
    unsafe_allow_html=True,
)
st.markdown(f'<div class="price">{fmt_price(current_price, symbol_sign)}</div>', unsafe_allow_html=True)
if change_val is not None:
    st.markdown(
        f'<div class="change" style="color:{color};">{arrow} {change_val:+,.2f} '
        f'({change_pct:+.2f}%) <span class="range-tag">· {range_label}</span></div>',
        unsafe_allow_html=True,
    )

if hist is None or hist.empty:
    st.info("No price history available for this range.")
else:
    fill_rgba = "rgba(0,200,5,0.10)" if net_up else "rgba(255,67,61,0.10)"
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=hist["Date"], y=hist["Close"], mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy", fillcolor=fill_rgba,
            hovertemplate="%{y:$,.2f}<extra></extra>",
        )
    )
    ymin, ymax = float(hist["Close"].min()), float(hist["Close"].max())
    pad = (ymax - ymin) * 0.12 or 1.0
    fig.update_layout(
        height=340, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, hovermode="x unified",
        xaxis=dict(showgrid=False, showline=False, zeroline=False, color=MUTED,
                   rangeslider=dict(visible=False)),
        yaxis=dict(showgrid=False, showline=False, zeroline=False, color=MUTED,
                   range=[ymin - pad, ymax + pad]),
    )
    fig.update_xaxes(showspikes=True, spikecolor=BORDER, spikethickness=1, spikemode="across", spikedash="dot")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.markdown('<div class="section-label">Key Stats</div>', unsafe_allow_html=True)
cards = [
    ("Market Cap", fmt_big(fundamentals["market_cap"])),
    ("P/E", fmt_ratio(fundamentals["pe"])),
    ("Forward P/E", fmt_ratio(fundamentals["forward_pe"])),
    ("EPS", fmt_ratio(fundamentals["eps"])),
    ("52-Wk High", fmt_price(fundamentals["week52_high"], symbol_sign)),
    ("52-Wk Low", fmt_price(fundamentals["week52_low"], symbol_sign)),
    ("Div Yield", fmt_pct(fundamentals["dividend_yield"])),
    ("Avg Volume", fmt_big(fundamentals["avg_volume"])),
]
st.markdown('<div class="stat-grid">' + "".join(stat_card(l, v) for l, v in cards) + "</div>",
            unsafe_allow_html=True)

# Recent news
st.markdown('<div class="section-label">Recent News</div>', unsafe_allow_html=True)
news_items = cached_news(ticker)
if not news_items:
    st.markdown('<div class="news-empty">No recent news available for this ticker.</div>',
                unsafe_allow_html=True)
else:
    for item in news_items:
        title = html.escape(item.get("title") or "Untitled")
        publisher = html.escape(item.get("publisher") or "Unknown")
        link = item.get("link") or ""
        when = relative_time(item.get("published"))
        meta = publisher + (f"  ·  {when}" if when else "")
        title_html = (f'<a href="{link}" target="_blank" rel="noopener">{title}</a>'
                      if link else f'<span style="color:#e6edf3;font-weight:600;">{title}</span>')
        st.markdown(
            f'<div class="news-card">{title_html}<div class="news-meta">{meta}</div></div>',
            unsafe_allow_html=True,
        )

st.markdown(
    '<div class="disclaimer">Educational tool — not financial advice. '
    'Data via Yahoo Finance (yfinance), may be delayed.</div>',
    unsafe_allow_html=True,
)

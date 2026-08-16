"""
app.py -- Stock Intel Agent
Single-ticker dashboard (chart + chat side by side, AI brief, stats, news) with a
Compare toggle that switches to a two-ticker view (overlaid normalized chart,
side-by-side metrics, comparative AI brief). UI layer only; logic lives in agent/*.
"""

import html
from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st

from agent import tools, analyst, router, llm

st.set_page_config(page_title="Stock Intel Agent", page_icon="📈", layout="wide")

GREEN = "#00c805"
RED = "#ff433d"
MUTED = "#8b949e"
CARD_BG = "#161b22"
BORDER = "#232a33"
CHART_H = 340
A_COLOR = "#4aa8ff"   # comparison: ticker A
B_COLOR = "#ff8c42"   # comparison: ticker B

RANGES = {"1D": "1d", "1W": "1w", "1M": "1m", "1Y": "1y", "5Y": "5y"}


# ------------------------- cached data access ------------------------------ #
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
    f = cached_fundamentals(symbol)  # cache hit — no extra network call
    name = f.get("long_name") if f else None
    return tools.get_news(symbol, limit=6, company_name=name)


@st.cache_data(ttl=600, show_spinner="Generating AI analyst brief…")
def cached_brief(symbol):
    f = tools.get_fundamentals(symbol)
    if not f:
        return None
    return analyst.generate_brief(f, tools.get_news(symbol, limit=6))


@st.cache_data(ttl=600, show_spinner="Generating comparison…")
def cached_comparison(ta, tb):
    fa, fb = tools.get_fundamentals(ta), tools.get_fundamentals(tb)
    if not fa or not fb:
        return None
    return analyst.generate_comparison(fa, tools.get_news(ta, 6), fb, tools.get_news(tb, 6))


@st.cache_data(ttl=600, show_spinner="Explaining price moves…")
def cached_move_explanations(ticker, range_label):
    hist = tools.get_price_history(ticker, RANGES[range_label])
    if hist is None or hist.empty:
        return []
    news = tools.get_news(ticker, limit=12)
    out = []
    for mv in tools.detect_significant_moves(hist):
        matching = tools.news_near_date(news, mv["date"], window_days=3)
        expl = analyst.explain_move(ticker, mv["date"], mv["pct"], matching) if matching else None
        out.append({**mv, "explanation": expl})
    return out


# ------------------------------- styles ------------------------------------ #
st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
      html, body, [class*="css"], .stApp {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }}
      .stApp {{ background-color: #0b0e11; }}
      #MainMenu, header, footer {{ visibility: hidden; }}
      .block-container {{ padding-top: 2.2rem; padding-bottom: 2rem; max-width: 1180px; margin: 0 auto; }}

      .stTextInput input {{ background-color: {CARD_BG}; color: #e6edf3; border: 1px solid {BORDER};
          border-radius: 10px; font-size: 1.0rem; padding: 0.55rem 0.85rem; }}
      .stTextInput input:focus {{ border-color: {GREEN}; box-shadow: none; }}

      .company-name {{ color: {MUTED}; font-size: 0.95rem; font-weight: 500; margin-bottom: 0.1rem; }}
      .ticker-badge {{ display: inline-block; background: {CARD_BG}; border: 1px solid {BORDER};
          color: #e6edf3; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.04em;
          padding: 0.12rem 0.5rem; border-radius: 6px; margin-left: 0.5rem; vertical-align: middle; }}
      .price {{ font-size: 2.6rem; font-weight: 800; color: #ffffff; line-height: 1.1; margin: 0.1rem 0; }}
      .price-sm {{ font-size: 1.7rem; font-weight: 800; color: #ffffff; line-height: 1.1; margin: 0.1rem 0; }}
      .change {{ font-size: 1.0rem; font-weight: 600; }}
      .change-sm {{ font-size: 0.9rem; font-weight: 600; }}
      .change .range-tag, .change-sm .range-tag {{ color: {MUTED}; font-weight: 500; }}
      .range-change {{ font-size: 0.85rem; font-weight: 600; margin-top: 0.3rem; }}
      .swatch {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:middle; }}

      .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; margin-top: 0.5rem; }}
      @media (max-width: 640px) {{ .stat-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
      .stat-card {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 12px; padding: 0.85rem 0.95rem; }}
      .stat-label {{ color: {MUTED}; font-size: 0.68rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.28rem; }}
      .stat-value {{ color: #e6edf3; font-size: 1.15rem; font-weight: 700; }}

      .cmp-table {{ width:100%; border-collapse:separate; border-spacing:0; background:{CARD_BG};
          border:1px solid {BORDER}; border-radius:12px; overflow:hidden; margin-top:0.4rem; }}
      .cmp-table th, .cmp-table td {{ padding:0.6rem 0.9rem; text-align:right; font-size:0.95rem; }}
      .cmp-table th {{ color:{MUTED}; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; border-bottom:1px solid {BORDER}; }}
      .cmp-table td:first-child, .cmp-table th:first-child {{ text-align:left; color:{MUTED}; font-weight:600; }}
      .cmp-table td {{ color:#e6edf3; font-weight:700; border-bottom:1px solid rgba(35,42,51,0.6); }}
      .cmp-table tr:last-child td {{ border-bottom:none; }}

      .section-label {{ color: {MUTED}; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; margin: 1.4rem 0 0.6rem 0; }}
      .chat-title {{ color: #e6edf3; font-size: 0.82rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.5rem; }}

      .ai-panel {{ background: linear-gradient(180deg, rgba(0,200,5,0.06), rgba(0,0,0,0)) , {CARD_BG};
          border: 1px solid {BORDER}; border-left: 3px solid {GREEN}; border-radius: 12px; padding: 1rem 1.15rem; margin-top: 0.4rem; }}
      .ai-label {{ color: {GREEN}; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 0.5rem; }}
      .ai-body {{ color: #d5dbe2; font-size: 0.95rem; line-height: 1.55; }}
      .ai-muted {{ color: {MUTED}; font-size: 0.9rem; }}

      .news-card {{ background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: 12px; padding: 0.85rem 1rem; margin-bottom: 0.6rem; transition: border-color 0.15s ease; }}
      .news-card:hover {{ border-color: #3a434e; }}
      .news-card a {{ color: #e6edf3; text-decoration: none; font-weight: 600; font-size: 0.98rem; line-height: 1.35; }}
      .news-card a:hover {{ color: {GREEN}; }}
      .news-meta {{ color: {MUTED}; font-size: 0.75rem; margin-top: 0.35rem; }}
      .news-empty {{ color: {MUTED}; font-size: 0.9rem; padding: 0.6rem 0; }}

      .move-row {{ background:{CARD_BG}; border:1px solid {BORDER}; border-left:3px solid #ffd33d;
          border-radius:10px; padding:0.6rem 0.9rem; margin-bottom:0.5rem; font-size:0.92rem; color:#d5dbe2; }}
      .move-date {{ color:{MUTED}; font-weight:600; margin-right:0.4rem; }}
      .move-exp {{ display:block; margin-top:0.25rem; color:#d5dbe2; }}

      .disclaimer {{ color: #5b636d; font-size: 0.72rem; text-align: center; margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid {BORDER}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------- formatting helpers ------------------------------ #
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


def sign_for(f):
    return "$" if f.get("currency") == "USD" else f"{f.get('currency','')} "


def safe_html(text):
    """LLM text going into an unsafe_allow_html block: escape HTML, neutralize the
    '$' LaTeX delimiter (Streamlit reads $...$ as math), and keep line breaks."""
    return html.escape(text or "").replace("$", "&#36;").replace("\n", "<br>")


def safe_md(text):
    """LLM text going into st.markdown as plain markdown: only neutralize '$' so a
    pair of dollar amounts isn't parsed as inline LaTeX."""
    return (text or "").replace("$", "&#36;")


def resolve(query, sel_key):
    """Resolve a typed query to (ticker, fundamentals). Shows a 'did you mean'
    picker for names/typos. Returns (None, None) if nothing matches."""
    f = cached_fundamentals(query.upper())
    if f is not None:
        return query.upper(), f
    matches = cached_search(query)
    if not matches:
        return None, None
    labels = [f"{m['symbol']} — {m['name']}" + (f"  ·  {m['exchange']}" if m["exchange"] else "")
              for m in matches]
    idx = st.selectbox("Did you mean…", options=list(range(len(matches))),
                       format_func=lambda i: labels[i], key=sel_key)
    t = matches[idx]["symbol"]
    return t, cached_fundamentals(t)


# ------------------------------ rendering ---------------------------------- #
def render_header(f, big=True):
    dch, dpct = f.get("day_change"), f.get("day_change_pct")
    up = (dch or 0) >= 0
    col = GREEN if up else RED
    arrow = "▲" if up else "▼"
    price_cls = "price" if big else "price-sm"
    chg_cls = "change" if big else "change-sm"
    st.markdown(
        f'<div class="company-name">{html.escape(f["long_name"])}'
        f'<span class="ticker-badge">{f["symbol"]}</span></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="{price_cls}">{fmt_price(f.get("current_price"), sign_for(f))}</div>',
                unsafe_allow_html=True)
    if dch is not None and dpct is not None:
        st.markdown(f'<div class="{chg_cls}" style="color:{col};">{arrow} {dch:+,.2f} '
                    f'({dpct:+.2f}%) <span class="range-tag">· today</span></div>', unsafe_allow_html=True)


def render_price_chart(ticker, range_label, moves=None):
    hist = cached_history(ticker, RANGES[range_label])
    if hist is None or hist.empty:
        st.info("No price history available for this range.")
        return
    first_close, last_close = hist["Close"].iloc[0], hist["Close"].iloc[-1]
    rng_change = last_close - first_close
    rng_pct = (rng_change / first_close * 100) if first_close else 0.0
    net_up = rng_change >= 0
    color = GREEN if net_up else RED
    fill = "rgba(0,200,5,0.10)" if net_up else "rgba(255,67,61,0.10)"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["Date"], y=hist["Close"], mode="lines",
                             line=dict(color=color, width=2), fill="tozeroy", fillcolor=fill,
                             hovertemplate="%{y:$,.2f}<extra></extra>"))
    ymin, ymax = float(hist["Close"].min()), float(hist["Close"].max())
    pad = (ymax - ymin) * 0.12 or 1.0
    fig.update_layout(height=CHART_H, margin=dict(l=0, r=0, t=6, b=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False, hovermode="x unified",
                      xaxis=dict(showgrid=False, showline=False, zeroline=False, color=MUTED, rangeslider=dict(visible=False)),
                      yaxis=dict(showgrid=False, showline=False, zeroline=False, color=MUTED, range=[ymin - pad, ymax + pad]))
    fig.update_xaxes(showspikes=True, spikecolor=BORDER, spikethickness=1, spikemode="across", spikedash="dot")
    # "Explain the Move" markers: gold dots ONLY on moves we can actually explain.
    explained = [m for m in (moves or []) if m.get("explanation")]
    if explained:
        mtext = [f"{m['date']}  {m['pct']:+.1f}%<br>{m['explanation']}" for m in explained]
        fig.add_trace(go.Scatter(
            x=[m["date"] for m in explained], y=[m["close"] for m in explained], mode="markers",
            marker=dict(size=12, color="#ffd33d", line=dict(color="#0b0e11", width=2)),
            text=mtext, hovertemplate="%{text}<extra></extra>", showlegend=False))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    r_arrow = "▲" if net_up else "▼"
    st.markdown(f'<div class="range-change" style="color:{color};">{r_arrow} {rng_change:+,.2f} '
                f'({rng_pct:+.2f}%) <span class="range-tag">over {range_label}</span></div>',
                unsafe_allow_html=True)


def render_chat(ticker, fundamentals, news_items, scope_key=None):
    scope_key = scope_key or ticker
    st.markdown('<div class="chat-title">💬 Ask the Analyst</div>', unsafe_allow_html=True)
    # Reset the conversation when the scope (ticker, or the compared pair) changes.
    if st.session_state.get("chat_scope") != scope_key:
        st.session_state["messages"] = []
        st.session_state["chat_scope"] = scope_key
    box_h = 260 if st.session_state["messages"] else 110
    with st.container(height=box_h):
        if not st.session_state["messages"]:
            st.caption(f"Ask about {ticker} — or any other ticker; I'll fetch it and answer. "
                       f"Try: \"compare it with MSFT\".")
        for m in st.session_state["messages"]:
            with st.chat_message(m["role"]):
                st.markdown(safe_md(m["content"]))
    with st.form("chat_form", clear_on_submit=True, border=False):
        c_in, c_btn = st.columns([4, 1])
        user_q = c_in.text_input("q", label_visibility="collapsed", placeholder=f"Ask about {ticker}…")
        sent = c_btn.form_submit_button("Ask", use_container_width=True)
    if sent and user_q.strip():
        q = user_q.strip()
        st.session_state["messages"].append({"role": "user", "content": q})
        ok, refusal = router.is_on_topic(q)
        if not ok:
            st.session_state["messages"].append({"role": "assistant", "content": refusal})
        else:
            with st.spinner("Analyzing…"):
                # Fresh-fetch: the model may call get_stock_data() to pull other
                # tickers mid-conversation (see analyst.answer_with_tools).
                ans = analyst.answer_with_tools(q, ticker, fundamentals, news_items,
                                                history=st.session_state["messages"][:-1])
            if not ans:
                ans = ("AI is unavailable — check your GROQ_API_KEY."
                       if not llm.has_key() else "Something went wrong. Please try again.")
            st.session_state["messages"].append({"role": "assistant", "content": ans})
        st.rerun()


def render_brief(ticker):
    brief = cached_brief(ticker)
    st.markdown('<div class="section-label">AI Analyst Brief</div>', unsafe_allow_html=True)
    if brief:
        st.markdown(f'<div class="ai-panel"><div class="ai-label">🤖 AI Analyst</div>'
                    f'<div class="ai-body">{safe_html(brief)}</div></div>', unsafe_allow_html=True)
    else:
        msg = ("Add a GROQ_API_KEY to your .env to enable AI analysis."
               if not llm.has_key() else "AI analysis is unavailable right now — try again shortly.")
        st.markdown(f'<div class="ai-panel"><div class="ai-label">🤖 AI Analyst</div>'
                    f'<div class="ai-muted">{msg}</div></div>', unsafe_allow_html=True)


def render_stats(f):
    st.markdown('<div class="section-label">Key Stats</div>', unsafe_allow_html=True)
    s = sign_for(f)
    cards = [
        ("Market Cap", fmt_big(f["market_cap"])), ("P/E", fmt_ratio(f["pe"])),
        ("Forward P/E", fmt_ratio(f["forward_pe"])), ("EPS", fmt_ratio(f["eps"])),
        ("52-Wk High", fmt_price(f["week52_high"], s)), ("52-Wk Low", fmt_price(f["week52_low"], s)),
        ("Div Yield", fmt_pct(f["dividend_yield"])), ("Avg Volume", fmt_big(f["avg_volume"])),
    ]
    st.markdown('<div class="stat-grid">' + "".join(stat_card(l, v) for l, v in cards) + "</div>",
                unsafe_allow_html=True)


def render_news(news_items):
    st.markdown('<div class="section-label">Recent News</div>', unsafe_allow_html=True)
    if not news_items:
        st.markdown('<div class="news-empty">No recent news available for this ticker.</div>',
                    unsafe_allow_html=True)
        return
    for item in news_items:
        title = html.escape(item.get("title") or "Untitled")
        publisher = html.escape(item.get("publisher") or "Unknown")
        link = item.get("link") or ""
        when = relative_time(item.get("published"))
        meta = publisher + (f"  ·  {when}" if when else "")
        title_html = (f'<a href="{link}" target="_blank" rel="noopener">{title}</a>'
                      if link else f'<span style="color:#e6edf3;font-weight:600;">{title}</span>')
        st.markdown(f'<div class="news-card">{title_html}<div class="news-meta">{meta}</div></div>',
                    unsafe_allow_html=True)


def render_move_explanations(moves):
    explained = [m for m in (moves or []) if m.get("explanation")]
    if not explained:
        return  # nothing we can honestly explain -> show nothing at all
    st.markdown('<div class="section-label">📌 Explain the Move</div>', unsafe_allow_html=True)
    for m in explained:
        col = GREEN if m["pct"] >= 0 else RED
        arrow = "▲" if m["pct"] >= 0 else "▼"
        st.markdown(
            f'<div class="move-row"><span class="move-date">{m["date"]}</span>'
            f'<span style="color:{col};font-weight:700;">{arrow} {m["pct"]:+.1f}%</span>'
            f'<span class="move-exp">{safe_html(m["explanation"])}</span></div>',
            unsafe_allow_html=True)


def render_single(ticker, fundamentals):
    news_items = cached_news(ticker)
    render_header(fundamentals, big=True)
    col_chart, col_chat = st.columns([1.5, 1], gap="large")
    with col_chart:
        range_label = st.segmented_control("Range", options=list(RANGES.keys()),
                                           default="1Y", label_visibility="collapsed",
                                           key="range_single") or "1Y"
        moves = cached_move_explanations(ticker, range_label)
        render_price_chart(ticker, range_label, moves)
    with col_chat:
        render_chat(ticker, fundamentals, news_items)
    render_move_explanations(moves)
    render_brief(ticker)
    render_stats(fundamentals)
    render_news(news_items)


def render_comparison(ta, fa, tb, fb):
    range_label = st.segmented_control("Range", options=list(RANGES.keys()),
                                       default="1Y", label_visibility="collapsed",
                                       key="range_cmp") or "1Y"

    # Dual header
    hcol_a, hcol_b = st.columns(2, gap="large")
    with hcol_a:
        st.markdown(f'<div style="color:{A_COLOR};font-size:0.72rem;font-weight:700;">'
                    f'<span class="swatch" style="background:{A_COLOR};"></span>{ta}</div>',
                    unsafe_allow_html=True)
        render_header(fa, big=False)
    with hcol_b:
        st.markdown(f'<div style="color:{B_COLOR};font-size:0.72rem;font-weight:700;">'
                    f'<span class="swatch" style="background:{B_COLOR};"></span>{tb}</div>',
                    unsafe_allow_html=True)
        render_header(fb, big=False)

    # Overlaid comparison chart (left) + chat (right), mirroring single mode
    ha = cached_history(ta, RANGES[range_label])
    hb = cached_history(tb, RANGES[range_label])
    col_chart, col_chat = st.columns([1.5, 1], gap="large")
    with col_chart:
        st.markdown('<div class="section-label" style="margin-top:0;">Relative Performance (%)</div>',
                    unsafe_allow_html=True)
        if ha is None or ha.empty or hb is None or hb.empty:
            st.info("Not enough price history to compare over this range.")
        else:
            fig = go.Figure()
            for h, color, name in [(ha, A_COLOR, ta), (hb, B_COLOR, tb)]:
                base = h["Close"].iloc[0]
                norm = (h["Close"] / base - 1) * 100 if base else h["Close"] * 0
                fig.add_trace(go.Scatter(x=h["Date"], y=norm, mode="lines",
                                         line=dict(color=color, width=2), name=name,
                                         hovertemplate=name + " %{y:+.2f}%<extra></extra>"))
            fig.update_layout(height=CHART_H, margin=dict(l=0, r=0, t=6, b=0),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              hovermode="x unified",
                              legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(color=MUTED)),
                              xaxis=dict(showgrid=False, showline=False, zeroline=False, color=MUTED, rangeslider=dict(visible=False)),
                              yaxis=dict(showgrid=True, gridcolor="rgba(35,42,51,0.5)", zeroline=True,
                                         zerolinecolor=BORDER, color=MUTED, ticksuffix="%"))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with col_chat:
        render_chat(ta, fa, cached_news(ta), scope_key=f"{ta}|{tb}")

    # Side-by-side metrics table
    st.markdown('<div class="section-label">Key Stats</div>', unsafe_allow_html=True)
    sa, sb = sign_for(fa), sign_for(fb)
    rows = [
        ("Market Cap", fmt_big(fa["market_cap"]), fmt_big(fb["market_cap"])),
        ("P/E", fmt_ratio(fa["pe"]), fmt_ratio(fb["pe"])),
        ("Forward P/E", fmt_ratio(fa["forward_pe"]), fmt_ratio(fb["forward_pe"])),
        ("EPS", fmt_ratio(fa["eps"]), fmt_ratio(fb["eps"])),
        ("52-Wk High", fmt_price(fa["week52_high"], sa), fmt_price(fb["week52_high"], sb)),
        ("52-Wk Low", fmt_price(fa["week52_low"], sa), fmt_price(fb["week52_low"], sb)),
        ("Div Yield", fmt_pct(fa["dividend_yield"]), fmt_pct(fb["dividend_yield"])),
        ("Avg Volume", fmt_big(fa["avg_volume"]), fmt_big(fb["avg_volume"])),
    ]
    body = "".join(f"<tr><td>{lbl}</td><td>{va}</td><td>{vb}</td></tr>" for lbl, va, vb in rows)
    st.markdown(
        f'<table class="cmp-table"><thead><tr><th>Metric</th><th>{ta}</th><th>{tb}</th></tr></thead>'
        f'<tbody>{body}</tbody></table>', unsafe_allow_html=True)

    # Comparative AI brief
    st.markdown('<div class="section-label">AI Comparison</div>', unsafe_allow_html=True)
    cmp_text = cached_comparison(ta, tb)
    if cmp_text:
        st.markdown(f'<div class="ai-panel"><div class="ai-label">🤖 AI Analyst · {ta} vs {tb}</div>'
                    f'<div class="ai-body">{safe_html(cmp_text)}</div></div>', unsafe_allow_html=True)
    else:
        msg = ("Add a GROQ_API_KEY to your .env to enable AI analysis."
               if not llm.has_key() else "AI comparison is unavailable right now — try again shortly.")
        st.markdown(f'<div class="ai-panel"><div class="ai-label">🤖 AI Analyst</div>'
                    f'<div class="ai-muted">{msg}</div></div>', unsafe_allow_html=True)


# ------------------------------- controls ---------------------------------- #
st.markdown("### 📈 Stock Intel Agent")

top_l, top_r = st.columns([3, 1])
with top_l:
    query = st.text_input("Search a ticker or company", value="AAPL", label_visibility="collapsed",
                          placeholder="Search a ticker or company (e.g. AAPL or Tesla)").strip()
with top_r:
    compare_on = st.toggle("Compare")

query_b = ""
if compare_on:
    query_b = st.text_input("Second ticker", value="", label_visibility="collapsed",
                            placeholder="Compare with… (e.g. MSFT)").strip()

if not query:
    st.stop()

ticker_a, fund_a = resolve(query, "sel_a")
if fund_a is None:
    st.warning(f"No matches for '{query}'. Try a different name or symbol.")
    st.stop()

compare_mode = False
ticker_b = fund_b = None
if compare_on and query_b:
    ticker_b, fund_b = resolve(query_b, "sel_b")
    if fund_b is None:
        st.warning(f"Couldn't load a second ticker for '{query_b}'. Showing {ticker_a} only.")
    elif ticker_b == ticker_a:
        st.warning("Pick two different tickers to compare.")
    else:
        compare_mode = True
elif compare_on and not query_b:
    st.caption("Enter a second ticker above to compare.")

# ------------------------------- dispatch ---------------------------------- #
if compare_mode:
    render_comparison(ticker_a, fund_a, ticker_b, fund_b)
else:
    render_single(ticker_a, fund_a)

st.markdown('<div class="disclaimer">Educational tool — not financial advice. '
            'Data via Yahoo Finance (yfinance), may be delayed.</div>', unsafe_allow_html=True)

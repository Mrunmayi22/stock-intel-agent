"""
agent/tools.py
--------------
Pure data-fetching functions for Stock Intel Agent.

RULES (do not break these):
  * No Streamlit imports or calls in this file.
  * Every function takes plain arguments and returns plain data.
  * Every function fails gracefully -- an invalid ticker or a network hiccup
    returns None / an empty list, never an uncaught exception.

Keeping this layer clean and standalone is what lets the chat agent call these
same functions to fetch data mid-conversation later, with no rework.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------------------
# Time-range handling
# ---------------------------------------------------------------------------
# Map the UI's friendly range labels to a (period, interval) pair that yfinance
# understands. Intraday ranges need a fine interval; long ranges need a coarse
# one, otherwise Yahoo either refuses the request or returns too many points.
_PERIOD_MAP: dict[str, dict[str, str]] = {
    "1d":  {"period": "1d",  "interval": "5m"},
    "1w":  {"period": "5d",  "interval": "30m"},
    "1wk": {"period": "5d",  "interval": "30m"},
    "5d":  {"period": "5d",  "interval": "30m"},
    "1m":  {"period": "1mo", "interval": "1d"},
    "1mo": {"period": "1mo", "interval": "1d"},
    "1y":  {"period": "1y",  "interval": "1d"},
    "5y":  {"period": "5y",  "interval": "1wk"},
}

# Ranges expressed in trading terms are accepted case-insensitively.
DEFAULT_RANGE = "1y"


def _normalize_range(period: str) -> dict[str, str]:
    """Return the {period, interval} yfinance kwargs for a friendly label."""
    return _PERIOD_MAP.get((period or "").lower(), _PERIOD_MAP[DEFAULT_RANGE])


# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------
def get_price_history(ticker: str, period: str = DEFAULT_RANGE) -> Optional[pd.DataFrame]:
    """
    Return an OHLCV DataFrame for `ticker` over the requested range.

    The returned frame has a plain integer index and these columns:
        Date, Open, High, Low, Close, Volume
    `Date` is a datetime column (renamed from Yahoo's 'Date'/'Datetime' index).

    Returns None if the ticker is invalid or no data comes back.
    """
    if not ticker or not ticker.strip():
        return None

    kwargs = _normalize_range(period)
    try:
        df = yf.Ticker(ticker.strip().upper()).history(
            period=kwargs["period"],
            interval=kwargs["interval"],
            auto_adjust=True,
        )
    except Exception:
        return None

    if df is None or df.empty:
        return None

    df = df.reset_index()
    # Yahoo names the time column 'Date' for daily data and 'Datetime' for intraday.
    time_col = "Datetime" if "Datetime" in df.columns else "Date"
    if time_col not in df.columns:
        # Whatever the first column is, treat it as the timestamp.
        time_col = df.columns[0]
    df = df.rename(columns={time_col: "Date"})

    keep = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[keep]


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------
def _safe_num(value) -> Optional[float]:
    """Coerce to float, or return None for missing/blank values."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _dividend_yield_pct(info: dict, current_price: Optional[float]) -> Optional[float]:
    """
    Return the dividend yield as a percentage.

    The raw `dividendYield` field has been reported by Yahoo/yfinance as both a
    fraction (0.0044) and a percentage (0.44) across versions, and the two forms
    overlap in the 0-1 range (a real 0.44% yield is indistinguishable from a
    0.44 fraction by magnitude alone). To avoid that ambiguity we compute the
    yield from unambiguous inputs when we can:

        yield% = annual_dividend_rate / current_price * 100

    and only fall back to the raw field if the rate isn't available.
    """
    rate = _safe_num(info.get("dividendRate")) or _safe_num(
        info.get("trailingAnnualDividendRate")
    )
    if rate is not None and current_price:
        return (rate / current_price) * 100
    # Fallback: current Yahoo returns dividendYield already as a percentage.
    return _safe_num(info.get("dividendYield"))


def get_fundamentals(ticker: str) -> Optional[dict]:
    """
    Return a dict of key fundamentals for `ticker`, or None if it's invalid.

    Keys:
        symbol, long_name, currency,
        current_price, previous_close, day_change, day_change_pct,
        market_cap, pe, forward_pe, eps,
        week52_high, week52_low, dividend_yield, avg_volume
    """
    if not ticker or not ticker.strip():
        return None

    symbol = ticker.strip().upper()
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return None

    current_price = _safe_num(info.get("currentPrice")) or _safe_num(
        info.get("regularMarketPrice")
    )
    previous_close = _safe_num(info.get("previousClose")) or _safe_num(
        info.get("regularMarketPreviousClose")
    )
    long_name = info.get("longName") or info.get("shortName")

    # If we got neither a name nor a price, treat the ticker as invalid.
    if current_price is None and not long_name:
        return None

    day_change = None
    day_change_pct = None
    if current_price is not None and previous_close:
        day_change = current_price - previous_close
        day_change_pct = (day_change / previous_close) * 100

    return {
        "symbol": symbol,
        "long_name": long_name or symbol,
        "currency": info.get("currency") or "USD",
        "current_price": current_price,
        "previous_close": previous_close,
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "market_cap": _safe_num(info.get("marketCap")),
        "pe": _safe_num(info.get("trailingPE")),
        "forward_pe": _safe_num(info.get("forwardPE")),
        "eps": _safe_num(info.get("trailingEps")),
        "week52_high": _safe_num(info.get("fiftyTwoWeekHigh")),
        "week52_low": _safe_num(info.get("fiftyTwoWeekLow")),
        "dividend_yield": _dividend_yield_pct(info, current_price),
        "avg_volume": _safe_num(info.get("averageVolume")),
    }


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------
def _parse_article(article: dict) -> Optional[dict]:
    """
    Normalize one raw yfinance news article into a flat dict:
        {title, publisher, link, published}   (published is a datetime or None)

    Handles BOTH shapes:
      * new (yfinance >= ~0.2.40 / 1.x): fields nested under 'content'
      * old: flat 'title' / 'publisher' / 'link' / 'providerPublishTime'
    """
    if not isinstance(article, dict):
        return None

    content = article.get("content")
    if isinstance(content, dict):
        # ---- new nested shape ----
        title = content.get("title")
        provider = content.get("provider") or {}
        publisher = provider.get("displayName") if isinstance(provider, dict) else None

        link = None
        for key in ("canonicalUrl", "clickThroughUrl"):
            node = content.get(key)
            if isinstance(node, dict) and node.get("url"):
                link = node["url"]
                break

        published = None
        raw_date = content.get("pubDate") or content.get("displayTime")
        if raw_date:
            try:
                published = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                published = None
    else:
        # ---- old flat shape ----
        title = article.get("title")
        publisher = article.get("publisher")
        link = article.get("link")
        published = None
        ts = article.get("providerPublishTime")
        if ts:
            try:
                published = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                published = None

    if not title:
        return None

    return {
        "title": title,
        "publisher": publisher or "Unknown",
        "link": link or "",
        "published": published,
    }


_NAME_SUFFIXES = {
    "inc", "corp", "corporation", "co", "ltd", "plc", "group", "holdings",
    "company", "the", "and", "sa", "nv", "ag", "class",
}


def _match_terms(ticker: str, company_name: Optional[str]) -> set:
    """Build the set of lowercase terms that mark a headline as company-specific:
    the ticker base (e.g. 'aapl') plus the first distinctive word of the company
    name (e.g. 'apple'), skipping generic suffixes like Inc/Corp."""
    terms = set()
    base = ticker.split(".")[0].split("-")[0].lower()
    if len(base) >= 2:
        terms.add(base)
    if company_name:
        for w in re.findall(r"[A-Za-z]+", company_name):
            wl = w.lower()
            if wl not in _NAME_SUFFIXES and len(wl) >= 3:
                terms.add(wl)
                break  # first distinctive word is enough
    return terms


def get_news(ticker: str, limit: int = 6, company_name: Optional[str] = None) -> list[dict]:
    """
    Return up to `limit` recent news items for `ticker` as a list of dicts:
        {title, publisher, link, published}

    Company-specific headlines are ranked first (matched on the ticker or the
    company name), but this is LENIENT: market-wide items are kept to fill the
    list, so the section is never left empty. Returns [] only on error/no news.
    """
    if not ticker or not ticker.strip():
        return []

    symbol = ticker.strip().upper()
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception:
        return []

    parsed: list[dict] = []
    for article in raw:
        item = _parse_article(article)
        if item:
            parsed.append(item)

    if not parsed:
        return []

    # Rank company-specific first, keep the rest (lenient), then trim to limit.
    terms = _match_terms(symbol, company_name)
    if terms:
        relevant, others = [], []
        for it in parsed:
            title = (it.get("title") or "").lower()
            (relevant if any(t in title for t in terms) else others).append(it)
        parsed = relevant + others

    return parsed[:limit]


# ---------------------------------------------------------------------------
# Manual smoke test:  python -m agent.tools AAPL
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Fundamentals for {sym}:")
    print(get_fundamentals(sym))
    print("\nPrice rows (1y): ", end="")
    hist = get_price_history(sym, "1y")
    print(len(hist) if hist is not None else "None")
    print(f"\nNews for {sym}:")
    for n in get_news(sym):
        print(" -", n["title"], "|", n["publisher"], "|", n["published"])


# ---------------------------------------------------------------------------
# Symbol search / name resolution  (added for name->ticker lookup)
# ---------------------------------------------------------------------------
def search_symbols(query: str, limit: int = 6) -> list[dict]:
    """
    Resolve a free-text query (company name, partial name, or symbol) to a list
    of matching instruments via Yahoo's search endpoint.

    Returns a list of dicts: {symbol, name, type, exchange}. Empty list on error
    or no match. Fuzzy matching is enabled so light typos still resolve.
    """
    if not query or not query.strip():
        return []

    try:
        res = yf.Search(
            query.strip(),
            max_results=limit,
            enable_fuzzy_query=True,
            include_cb=False,
            include_nav_links=False,
            include_research=False,
            news_count=0,
            lists_count=0,
            recommended=0,
            raise_errors=False,
        )
        quotes = res.quotes or []
    except Exception:
        return []

    out: list[dict] = []
    for q in quotes:
        if not isinstance(q, dict):
            continue
        sym = q.get("symbol")
        if not sym:
            continue
        name = (
            q.get("longname")
            or q.get("shortname")
            or q.get("longName")
            or q.get("shortName")
            or sym
        )
        out.append(
            {
                "symbol": sym,
                "name": name,
                "type": q.get("quoteType") or q.get("typeDisp") or "",
                "exchange": q.get("exchDisp") or q.get("exchange") or "",
            }
        )
        if len(out) >= limit:
            break
    return out


def resolve_symbol(query: str) -> Optional[str]:
    """Return the single best-matching symbol for a query, or None."""
    matches = search_symbols(query, limit=1)
    return matches[0]["symbol"] if matches else None


# ---------------------------------------------------------------------------
# "Explain the Move": significant price moves + date-matched news
# ---------------------------------------------------------------------------
def detect_significant_moves(price_df, top_n: int = 3, min_pct: float = 2.5) -> list[dict]:
    """
    Return the largest single-period % moves in a price frame.

    Each item: {date (datetime.date), pct (float), close (float)}.
    Only moves whose absolute % change >= min_pct are considered; the top_n by
    magnitude are returned. Empty list if the frame is too small or has no
    qualifying moves.
    """
    if price_df is None or len(price_df) < 2:
        return []
    df = price_df.copy()
    df["pct"] = df["Close"].pct_change() * 100
    df = df.dropna(subset=["pct"])
    sig = df[df["pct"].abs() >= min_pct]
    if sig.empty:
        return []
    order = sig["pct"].abs().sort_values(ascending=False).index
    out = []
    for i in order[:top_n]:
        row = sig.loc[i]
        d = row["Date"]
        out.append({
            "date": d.date() if hasattr(d, "date") else d,
            "pct": float(row["pct"]),
            "close": float(row["Close"]),
        })
    return out


def news_near_date(news: list, target_date, window_days: int = 3) -> list[dict]:
    """Return news items published within +/- window_days of target_date."""
    matches = []
    for n in (news or []):
        p = n.get("published")
        pdate = p.date() if hasattr(p, "date") else None
        if pdate is None:
            continue
        try:
            if abs((pdate - target_date).days) <= window_days:
                matches.append(n)
        except Exception:
            continue
    return matches

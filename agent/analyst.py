"""
agent/analyst.py
----------------
The reasoning layer. Turns already-fetched stock data into plain-English output
via Groq. Two entry points share one context builder:

    generate_brief(fundamentals, news)            -> the AI analyst brief
    answer_question(question, fundamentals, news) -> scoped Q&A for the chat

Design rules baked into the prompts:
  * cite the SPECIFIC numbers/headlines provided (no generic filler)
  * analysis only, never buy/sell advice
  * every output is grounded in the data passed in, nothing invented

Both return None if the LLM is unavailable (e.g. no GROQ_API_KEY), so the UI can
show a graceful "add a key" state instead of crashing.
"""

from __future__ import annotations

from agent import llm


def _pct_in_range(cur, lo, hi):
    if None in (cur, lo, hi) or hi == lo:
        return None
    return (cur - lo) / (hi - lo) * 100


def build_context(fundamentals: dict, news: list) -> str:
    """Compact, specific text block of the data the model may reason over."""
    f = fundamentals
    lines = [f"Company: {f.get('long_name')} ({f.get('symbol')})"]

    price = f.get("current_price")
    if price is not None:
        s = f"Current price: {price:,.2f} {f.get('currency', '')}".strip()
        if f.get("day_change_pct") is not None:
            s += f" (day {f['day_change_pct']:+.2f}%)"
        lines.append(s)

    val = []
    if f.get("pe") is not None:
        val.append(f"P/E {f['pe']:.2f}")
    if f.get("forward_pe") is not None:
        val.append(f"forward P/E {f['forward_pe']:.2f}")
    if f.get("eps") is not None:
        val.append(f"EPS {f['eps']:.2f}")
    if f.get("market_cap") is not None:
        val.append(f"market cap {f['market_cap']:,.0f}")
    if val:
        lines.append("Valuation: " + ", ".join(val))

    hi, lo = f.get("week52_high"), f.get("week52_low")
    if hi and lo:
        pos = _pct_in_range(price, lo, hi)
        tail = f" (~{pos:.0f}% of the way up its 52-week range)" if pos is not None else ""
        lines.append(f"52-week range: {lo:,.2f}–{hi:,.2f}{tail}")

    if f.get("dividend_yield") is not None:
        lines.append(f"Dividend yield: {f['dividend_yield']:.2f}%")
    if f.get("avg_volume") is not None:
        lines.append(f"Average volume: {f['avg_volume']:,.0f}")

    if news:
        lines.append("Recent headlines:")
        for n in news[:6]:
            d = n.get("published")
            ds = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else ""
            prefix = f"[{ds}] " if ds else ""
            lines.append(f"- {prefix}{n.get('title')} ({n.get('publisher')})")

    return "\n".join(lines)


_BRIEF_SYSTEM = (
    "You are a concise equity research analyst. Using ONLY the data provided, write a short brief "
    "on the stock. You MUST reference the specific numbers you are given (the actual P/E, market "
    "cap, 52-week position, dividend yield, etc.) and the actual headlines — no generic filler, and "
    "never invent data that isn't provided.\n\n"
    "Cover, in a few tight paragraphs:\n"
    "1. A one-line snapshot of the company and where the stock stands.\n"
    "2. A valuation read: is the P/E high or low, and what that implies.\n"
    "3. What the recent headlines signal.\n"
    "4. Two or three concrete risks to watch.\n\n"
    "Frame everything as analysis, NEVER as a recommendation. Do not say buy, sell, or hold. "
    "End with a single line: 'Not financial advice.'"
)

_QA_SYSTEM = (
    "You are the Stock Intel analyst assistant, answering questions about {ticker}. "
    "Answer using ONLY the data below. Be specific — cite the actual numbers and headlines.\n\n"
    "Handle these cases gracefully instead of dead-ending:\n"
    "- If asked what to buy/sell/hold or 'which is best', do NOT give a recommendation. In one "
    "sentence, say you provide analysis rather than buy/sell advice, then offer to walk through the "
    "relevant considerations or analyze a specific name.\n"
    "- If asked about a company or sector that isn't in the loaded data (e.g. comparing several "
    "stocks), say you can analyze any single ticker they load, or compare two using the Compare "
    "toggle — and invite them to do that.\n"
    "- NEVER assess, rate, or label bullish/bearish any company that is not present in the DATA "
    "section below — not even from your own prior knowledge, which may be outdated. Redirect instead.\n"
    "- If the answer simply isn't in this data, say so plainly.\n\n"
    "Always analysis, never advice. Be concise.\n\n"
    "DATA:\n{context}"
)


def generate_brief(fundamentals: dict, news: list) -> str | None:
    if not fundamentals:
        return None
    ctx = build_context(fundamentals, news or [])
    return llm.chat(
        [
            {"role": "system", "content": _BRIEF_SYSTEM},
            {"role": "user", "content": f"Here is the data:\n\n{ctx}\n\nWrite the analyst brief."},
        ],
        model=llm.SMART_MODEL,
        temperature=0.4,
        max_tokens=1200,
    )


def answer_question(question: str, fundamentals: dict, news: list, history: list | None = None) -> str | None:
    if not fundamentals:
        return None
    ctx = build_context(fundamentals, news or [])
    sys = _QA_SYSTEM.format(ticker=fundamentals.get("symbol", "this stock"), context=ctx)
    msgs = [{"role": "system", "content": sys}]
    for m in (history or [])[-6:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": question})
    return llm.chat(msgs, model=llm.SMART_MODEL, temperature=0.3, max_tokens=1000)


_COMPARE_SYSTEM = (
    "You are an equity research analyst comparing two stocks. Using ONLY the data provided for each, "
    "write a short comparative analysis. Cite the specific numbers for BOTH names (their actual P/E, "
    "market cap, 52-week position, dividend yield) and reference their headlines. Never invent data.\n\n"
    "Cover, in a few tight paragraphs:\n"
    "1. How the two differ on valuation (which looks richer/cheaper on P/E and why).\n"
    "2. How their recent momentum and news compare.\n"
    "3. The key trade-offs an investor would weigh between them.\n\n"
    "Do NOT tell the user which to buy, sell, or hold, and do NOT declare an overall 'winner'. "
    "Present the trade-offs and let the reader decide. End with a single line: 'Not financial advice.'"
)


def generate_comparison(fund_a: dict, news_a: list, fund_b: dict, news_b: list) -> str | None:
    if not fund_a or not fund_b:
        return None
    ctx_a = build_context(fund_a, news_a or [])
    ctx_b = build_context(fund_b, news_b or [])
    user = (f"STOCK A:\n{ctx_a}\n\nSTOCK B:\n{ctx_b}\n\n"
            "Write the comparative analysis.")
    return llm.chat(
        [
            {"role": "system", "content": _COMPARE_SYSTEM},
            {"role": "user", "content": user},
        ],
        model=llm.SMART_MODEL,
        temperature=0.4,
        max_tokens=1200,
    )


_EXPLAIN_SYSTEM = (
    "You explain a single stock price move in ONE short sentence, using ONLY the headlines "
    "provided. If the headlines do not plausibly explain the move, respond with exactly the word "
    "UNCLEAR. Never invent a reason, never speculate beyond the headlines, and give no advice."
)


def explain_move(symbol: str, when, pct: float, matching_news: list) -> str | None:
    """
    Return a one-sentence, news-grounded explanation for a price move, or None
    if there is no usable news (never fabricate). Also returns None if the model
    judges the headlines don't explain the move (it replies UNCLEAR).
    """
    if not matching_news:
        return None
    heads = "\n".join(f"- {n.get('title')} ({n.get('publisher')})" for n in matching_news[:4])
    user = (f"{symbol} moved {pct:+.1f}% around {when}. Headlines near that date:\n{heads}\n\n"
            "One-sentence explanation, or UNCLEAR.")
    out = llm.chat(
        [{"role": "system", "content": _EXPLAIN_SYSTEM},
         {"role": "user", "content": user}],
        model=llm.FAST_MODEL, temperature=0.2, max_tokens=300,
    )
    if not out:
        return None
    if "UNCLEAR" in out.strip().upper():
        return None
    return out.strip()


# ---------------------------------------------------------------------------
# Fresh-fetch tool-calling chat: the model can pull other tickers mid-chat.
# ---------------------------------------------------------------------------
import json  # noqa: E402  (kept local to this feature block)

from agent import tools as _tools  # noqa: E402

_TOOLS_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "get_stock_data",
        "description": (
            "Fetch current fundamentals and recent news for a stock ticker or company "
            "(e.g. 'AAPL', 'Microsoft'). Call this whenever the user asks about a company "
            "you do not already have loaded, or to compare against another company."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Ticker symbol or company name, e.g. AAPL or Tesla"}
            },
            "required": ["ticker"],
        },
    },
}]

_TOOLS_SYSTEM = (
    "You are the Stock Intel analyst assistant. You already have data for {ticker} (below). "
    "You can call get_stock_data(ticker) to fetch fundamentals and news for ANY other company the "
    "user asks about, or to compare two companies. Fetch before you analyze a company you don't "
    "have.\n\n"
    "Rules: use ONLY data you have loaded or fetched via the tool — never rate or describe a company "
    "from your own memory. Be specific and cite actual numbers/headlines. Give analysis only, never "
    "buy/sell/hold advice, and never declare an overall 'winner'. Be concise.\n\n"
    "LOADED DATA for {ticker}:\n{context}"
)


def _tool_get_stock_data(ticker: str) -> dict:
    """Executor for the get_stock_data tool: resolve, fetch, return compact context."""
    if not ticker or not ticker.strip():
        return {"error": "No ticker provided."}
    sym = ticker.strip().upper()
    f = _tools.get_fundamentals(sym)
    if f is None:
        resolved = _tools.resolve_symbol(ticker)
        if resolved:
            sym, f = resolved, _tools.get_fundamentals(resolved)
    if f is None:
        return {"error": f"No data found for '{ticker}'."}
    news = _tools.get_news(sym, limit=5, company_name=f.get("long_name"))
    return {"ticker": sym, "data": build_context(f, news)}


def answer_with_tools(question: str, ticker: str, fundamentals: dict, news: list,
                      history: list | None = None, max_rounds: int = 3) -> str | None:
    """
    Answer a chat question, letting the model fetch other tickers via get_stock_data.
    Falls back to a plain (no-tool) answer if tool-calling is unavailable.
    """
    if not fundamentals:
        return None

    ctx = build_context(fundamentals, news or [])
    messages = [{"role": "system", "content": _TOOLS_SYSTEM.format(ticker=ticker, context=ctx)}]
    for m in (history or [])[-6:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": question})

    for _ in range(max_rounds):
        msg = llm.chat_raw(messages, model=llm.SMART_MODEL, tools=_TOOLS_SCHEMA,
                           tool_choice="auto", temperature=0.3, max_tokens=1200)
        if msg is None:
            # Tool-calling unavailable -> graceful fallback to a plain answer.
            return answer_question(question, fundamentals, news, history=history)

        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return (getattr(msg, "content", "") or "").strip() or None

        # Record the assistant's tool-call turn, then run each tool.
        messages.append({
            "role": "assistant", "content": getattr(msg, "content", "") or "",
            "tool_calls": [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            } for tc in tool_calls],
        })
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result = (_tool_get_stock_data(args.get("ticker", ""))
                      if tc.function.name == "get_stock_data" else {"error": "unknown tool"})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    # Out of rounds: force a final answer from what we've gathered.
    return llm.chat(messages, model=llm.SMART_MODEL, max_tokens=1000)

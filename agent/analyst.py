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
    "Answer using ONLY the data below. Be specific — cite the actual numbers and headlines. "
    "If the answer isn't in this data, say you can only speak to the currently loaded data for "
    "{ticker}. Give analysis only — never buy/sell/hold advice. Be concise.\n\n"
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

# 📈 Stock Intel Agent

**Live demo:** https://stock-intel-agent-mm8syl9gnd4x2zxigplexk.streamlit.app

An agentic stock-analysis dashboard. Enter a ticker (or company name) and get a
Robinhood-style price chart, key fundamentals, recent news, and an AI analyst
brief that reasons over the live data — plus a chat panel that can fetch and
compare other tickers on demand.

> Educational tool — not financial advice.

## What it does

- **Dashboard**: live price, day/range change, an interactive price chart, and
  a key-stats grid (market cap, P/E, EPS, 52-week range, dividend yield, volume).
- **Name search**: type a company name instead of a ticker and pick from a
  "Did you mean…" list.
- **AI Analyst Brief**: a data-grounded summary — cites the actual numbers and
  headlines it was given, never invents figures, and is framed as analysis
  only (no buy/sell/hold recommendations).
- **Ask the Analyst (chat)**: a guarded Q&A panel scoped to stock/market
  questions. Off-topic or jailbreak-style prompts are refused by a two-layer
  router (LLM classifier + keyword fallback). The model can fetch fresh data
  for *any other* ticker mid-conversation via tool calling.
- **Compare mode**: toggle to view two tickers side by side — normalized
  relative-performance chart, side-by-side stats, and a comparative AI brief.
- **Explain the Move**: flags the largest recent price swings and links them
  to matching news headlines — with a strict no-hallucination rule: if no
  news actually explains a move, it says so instead of guessing.

## Why it's a "bounded" agent

The assistant is purpose-built for stock/market analysis and refuses
everything else — including prompt-injection attempts ("ignore your
instructions...") — via a guardrail that runs on every chat message.

## Tech stack

| Layer | Tool |
|---|---|
| UI | Streamlit |
| Live market data | yfinance (no API key required) |
| Charts | Plotly |
| LLM | Groq (`openai/gpt-oss-120b` / `openai/gpt-oss-20b`), free tier |
| Hosting | Streamlit Community Cloud |

## Architecture

```
app.py            UI only — renders what agent/* returns, no data/LLM logic
agent/tools.py     Pure data-fetching functions (yfinance) — no Streamlit
agent/router.py    Guardrail: is this query on-topic?
agent/analyst.py   Groq calls that turn data into analysis
agent/llm.py       Single place the LLM provider/client lives
```

## Running locally

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
```

Then run:

```bash
streamlit run app.py
```

## Future work

- Deeper eval harness (execution accuracy against a benchmark set of
  questions) for the AI brief and Q&A quality.
- Support additional comparison sizes (3+ tickers) beyond the current
  two-ticker Compare mode.

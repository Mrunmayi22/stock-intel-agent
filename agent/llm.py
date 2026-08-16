"""
agent/llm.py
------------
Single place where the LLM provider lives. Router and analyst both import from
here, so swapping providers (or model names) is a one-file change.

Provider: Groq (free tier, open-weight models). The client reads GROQ_API_KEY
from the environment / .env. If no key is present, get_client() returns None so
callers can degrade gracefully instead of crashing.
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Current Groq model IDs (llama-3.3-70b-versatile was deprecated June 2026).
FAST_MODEL = "openai/gpt-oss-20b"     # classification / guardrail
SMART_MODEL = "openai/gpt-oss-120b"   # analyst brief / Q&A


def get_client():
    """Return a Groq client, or None if no API key is configured."""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=key)
    except Exception:
        return None


def chat(messages, model: str = SMART_MODEL, temperature: float = 0.3,
         max_tokens: int = 1024, reasoning_effort: str = "low") -> Optional[str]:
    """
    Send a chat completion and return the text, or None on any failure
    (including a missing key). Callers decide how to handle None.

    The Groq GPT-OSS models are *reasoning* models: hidden reasoning tokens are
    drawn from the same max_tokens budget as the visible answer. We therefore
    (a) keep reasoning_effort low for these summarize/classify tasks, and
    (b) hide the reasoning trace so `.content` is the clean final answer.
    Callers must still pass a max_tokens large enough to cover a little
    reasoning plus the answer.
    """
    client = get_client()
    if client is None:
        return None

    kwargs = dict(
        model=model, messages=messages,
        temperature=temperature, max_tokens=max_tokens,
    )
    # reasoning_* params only apply to the GPT-OSS reasoning models.
    if reasoning_effort and model.startswith("openai/gpt-oss"):
        kwargs["reasoning_effort"] = reasoning_effort
        kwargs["reasoning_format"] = "hidden"

    try:
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content
    except Exception:
        # Retry once without the reasoning params in case a model/endpoint
        # rejects them, so a param mismatch never silently kills the feature.
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        except Exception:
            return None


def has_key() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def chat_raw(messages, model: str = SMART_MODEL, tools=None, tool_choice: str = "auto",
             temperature: float = 0.3, max_tokens: int = 1200, reasoning_effort: str = "low"):
    """
    Like chat(), but returns the full assistant *message object* (which may carry
    .tool_calls) instead of just text, so callers can run a tool-calling loop.
    Returns None on any failure. reasoning_format is forced to 'hidden', which
    Groq requires when tool calls are in play.
    """
    client = get_client()
    if client is None:
        return None
    kwargs = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice
    if model.startswith("openai/gpt-oss"):
        kwargs["reasoning_effort"] = reasoning_effort
        kwargs["reasoning_format"] = "hidden"
    try:
        resp = client.chat.completions.create(**kwargs)
        return resp.choices[0].message
    except Exception:
        return None

"""Groq provider using the OpenAI-compatible API."""

import os
from functools import lru_cache

from openai import OpenAI


GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _raw_key():
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key or key.upper() in {
        "YOUR_API_KEY_HERE", "REPLACE_ME", "REPLACE-ME", "NONE"
    }:
        return None
    return key


def configured_model():
    # Set this to a model currently available in your Groq account.
    return (os.getenv("GROQ_MODEL") or "").strip()


def groq_available():
    return bool(_raw_key() and configured_model())


@lru_cache(maxsize=4)
def _client_for_key(key):
    return OpenAI(
        api_key=key,
        base_url=GROQ_BASE_URL,
        timeout=45.0,
        max_retries=0,
    )


def _client(timeout=45):
    key = _raw_key()
    if not key:
        raise RuntimeError("Groq API key is not configured")
    if not configured_model():
        raise RuntimeError("Groq model is not configured")
    client = _client_for_key(key)
    # Apply the per-request timeout without changing the cached client.
    return client.with_options(timeout=max(1, float(timeout)), max_retries=0)


def classify_groq_error(error):
    """Return a safe error category; never expose raw error text to users."""
    message = f"{type(error).__name__}: {error}".lower()

    if "401" in message or "403" in message or "invalid api key" in message:
        return "auth_invalid"
    if "429" in message or "rate limit" in message:
        if "quota" in message or "billing" in message:
            return "quota_exceeded"
        return "rate_limited"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "connection" in message or "network" in message:
        return "connection_error"
    if "model" in message and (
        "not found" in message or "decommission" in message
    ):
        return "model_unavailable"
    return "provider_error"


def generate_answer(prompt, timeout=45, max_tokens=1200, model=None):
    response = _client(timeout).chat.completions.create(
        model=model or configured_model(),
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=max_tokens,
        temperature=0.3,
    )
    if not response.choices:
        return None
    return (response.choices[0].message.content or "").strip() or None


def stream_pieces(prompt, timeout=60, max_tokens=1800, model=None):
    stream = _client(timeout).chat.completions.create(
        model=model or configured_model(),
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=max_tokens,
        temperature=0.3,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        piece = chunk.choices[0].delta.content
        if piece:
            yield piece

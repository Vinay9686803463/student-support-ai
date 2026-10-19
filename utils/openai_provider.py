"""OpenAI provider for AI-generated study answers (official SDK v2).

Configuration (server-side environment only, never frontend/Git):
  OPENAI_API_KEY   - required; the project reads it at request time.
  OPENAI_MODEL     - optional override; default "gpt-4o-mini"
                     (live-verified in the account's model list).

All errors map to stable codes; nothing secret is ever logged or
returned to the client.
"""

import os

DEFAULT_MODEL = "gpt-4o-mini"

_PLACEHOLDERS = frozenset({
    "", "YOUR_API_KEY_HERE", "REPLACE-ME", "REPLACE_ME", "NONE",
    "YOUR_OPENAI_API_KEY",
})


def configured_model():
    """Model name from env, defaulting to the verified default."""
    name = (os.getenv("OPENAI_MODEL") or "").strip()
    return name or DEFAULT_MODEL


def _raw_key():
    return (os.getenv("OPENAI_API_KEY") or "").strip()


def openai_key_present():
    """True when a non-placeholder key is configured (never its value)."""
    return _raw_key().upper() not in _PLACEHOLDERS and bool(_raw_key())


def openai_available():
    """True when the SDK imports AND a key is configured."""
    if not openai_key_present():
        return False
    try:
        import openai  # noqa: F401
        return True
    except Exception:
        return False


_CLIENT_CACHE = {"key": None, "cls": None, "clients": {}}


def _client(timeout):
    import openai as _openai_module

    OpenAI = _openai_module.OpenAI
    key = _raw_key()
    # One client per timeout bucket (rebuilt if the key changes): the
    # SDK keeps its own connection pool, so repeat messages reuse TLS
    # sessions instead of paying a fresh handshake every request.
    # The cache is also dropped whenever the OpenAI class object
    # itself is replaced (tests patch openai.OpenAI per case); in
    # normal runtime the class never changes and the pool persists.
    bucket = round(max(float(timeout), 1.0), 1)
    if _CLIENT_CACHE["key"] != key or _CLIENT_CACHE["cls"] is not OpenAI:
        _CLIENT_CACHE["key"] = key
        _CLIENT_CACHE["cls"] = OpenAI
        _CLIENT_CACHE["clients"] = {}
    cached = _CLIENT_CACHE["clients"].get(bucket)
    if cached is None:
        cached = OpenAI(api_key=key, timeout=bucket)
        _CLIENT_CACHE["clients"][bucket] = cached
    return cached


def classify_openai_error(error):
    """Map an OpenAI SDK exception to a stable error code."""
    status = getattr(error, "status_code", None)
    if status == 401 or status == 403:
        return "auth_invalid"
    if status == 429:
        # 429 covers both rate limits and exhausted quota/billing.
        inner = str(getattr(error, "body", "") or "").lower()
        if "insufficient_quota" in inner or "billing" in inner \
                or "credit" in inner:
            return "quota_exhausted"
        return "rate_limited"
    if status == 404:
        return "model_not_found"
    if status == 400:
        return "bad_request"
    if isinstance(status, int) and status >= 500:
        return "server_error"

    name = type(error).__name__
    text = f"{name}: {error}".lower()

    if "insufficient_quota" in text or "credit_balance_exhausted" in text \
            or "no credits remaining" in text:
        return "quota_exhausted"
    if name in ("AuthenticationError", "PermissionDeniedError") \
            or "invalid api key" in text or "incorrect api key" in text:
        return "auth_invalid"
    if name in ("RateLimitError",):
        return "rate_limited"
    if name in ("NotFoundError",):
        return "model_not_found"
    if name in ("BadRequestError",):
        return "bad_request"
    if name in ("APITimeoutError",) or "timeout" in text or "timed out" in text:
        return "timeout"
    if name in ("APIConnectionError",) or "connect" in text or "dns" in text \
            or "network" in text or "unreachable" in text:
        return "network"
    return "unknown"


def provider_error_message(code):
    """User-safe, actionable message per error code (no secrets)."""
    return {
        "provider_not_configured":
            "AI answering is not configured on the server (missing API key).",
        "auth_invalid":
            "AI authentication failed. The server API key is invalid.",
        "quota_exhausted":
            "The AI account has no credits remaining. Add billing credits "
            "to continue.",
        "rate_limited":
            "The AI service is rate-limited right now. Please retry shortly.",
        "model_not_found":
            "The configured AI model is invalid. Ask the administrator to "
            "check OPENAI_MODEL.",
        "bad_request":
            "The AI request was rejected. Please try a shorter question.",
        "timeout":
            "The AI service timed out. Please retry.",
        "network":
            "Could not reach the AI service. Check the server connection.",
        "server_error":
            "The AI service had an internal error. Please retry shortly.",
        "unknown":
            "AI generation failed. Please retry.",
    }.get(code, "AI generation failed. Please retry.")


def generate_answer(prompt, timeout=45, max_tokens=1200, model=None):
    """Full generated answer text, or raise the SDK exception."""
    client = _client(timeout)
    response = client.chat.completions.create(
        model=model or configured_model(),
        messages=[
            {"role": "system",
             "content": ("You are Student Support AI, an academic assistant "
                         "for VTU Computer Science and Engineering students.")},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=max_tokens,
        timeout=float(timeout),
    )
    return ((response.choices[0].message.content or "").strip()
            if response.choices else "")


def stream_pieces(prompt, timeout=60, max_tokens=1800, model=None):
    """Yield generated text pieces as they stream in."""
    client = _client(timeout)
    stream = client.chat.completions.create(
        model=model or configured_model(),
        messages=[
            {"role": "system",
             "content": ("You are Student Support AI, an academic assistant "
                         "for VTU Computer Science and Engineering students.")},
            {"role": "user", "content": prompt},
        ],
        max_completion_tokens=max_tokens,
        timeout=float(timeout),
        stream=True,
    )
    for event in stream:
        try:
            delta = event.choices[0].delta.content or ""
        except (AttributeError, IndexError):
            continue
        if delta:
            yield delta
